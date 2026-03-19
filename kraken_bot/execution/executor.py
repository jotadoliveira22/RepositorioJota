"""Order execution: place, manage, OCO synthetic, cancel/replace."""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from ..config import BotConfig, ExecutionConfig
from ..connectors.spot import KrakenSpotConnector
from ..connectors.futures import KrakenFuturesConnector
from ..persistence.database import Database
from ..risk.manager import RiskManager
from ..strategy.engine import Signal

logger = logging.getLogger(__name__)


class OrderExecutor:
    """Handles order placement, OCO management, trailing stops."""

    def __init__(self, config: BotConfig, spot: KrakenSpotConnector,
                 futures: KrakenFuturesConnector, db: Database, risk: RiskManager):
        self.cfg = config
        self.exec_cfg = config.execution
        self.spot = spot
        self.futures = futures
        self.db = db
        self.risk = risk
        self._oco_pairs: Dict[str, Dict] = {}  # position_id -> {sl_cid, tp_cid}
        self._dry_run = config.mode in ("dry-run", "shadow")

    async def execute_signal(self, signal: Signal) -> Optional[int]:
        """Execute a trading signal. Returns position ID or None."""
        if signal.blocked:
            self.db.save_signal(
                signal.symbol, signal.market_type, signal.direction,
                signal.signal_type, signal.entry_price, signal.sl_price,
                signal.tp_price, signal.reason,
                signal.filters_passed, signal.filters_blocked
            )
            self.db.log_event("INFO", "signal_blocked",
                            f"Signal blocked: {signal.filters_blocked}",
                            signal.symbol)
            return None

        if self.cfg.mode == "shadow":
            sig_id = self.db.save_signal(
                signal.symbol, signal.market_type, signal.direction,
                signal.signal_type, signal.entry_price, signal.sl_price,
                signal.tp_price, signal.reason,
                signal.filters_passed, signal.filters_blocked
            )
            self.db.log_event("INFO", "shadow_signal", signal.reason, signal.symbol)
            return None

        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            self.db.log_event("WARNING", "trade_rejected", reason, signal.symbol)
            return None

        # Calculate position size
        leverage = self.risk.validate_leverage(self.cfg.risk.default_leverage)
        if signal.market_type in ("spot", "xstock"):
            leverage = 1.0  # No leverage on spot or xStocks

        size, valid, size_reason = self.risk.calculate_position_size(
            signal.entry_price, signal.sl_price, leverage
        )
        if not valid:
            self.db.log_event("WARNING", "size_invalid", size_reason, signal.symbol)
            return None

        # Save signal
        sig_id = self.db.save_signal(
            signal.symbol, signal.market_type, signal.direction,
            signal.signal_type, signal.entry_price, signal.sl_price,
            signal.tp_price, signal.reason,
            signal.filters_passed, signal.filters_blocked
        )
        self.db.mark_signal_acted(sig_id)

        # Place entry order
        direction = "buy" if signal.direction == "long" else "sell"
        entry_result = await self._place_order(
            signal.symbol, signal.market_type, direction, "market",
            size, signal_id=sig_id, leverage=leverage
        )

        if "error" in entry_result:
            self.db.log_event("ERROR", "order_failed",
                            str(entry_result["error"]), signal.symbol)
            return None

        # Open position in DB
        pos_id = self.db.open_position(
            signal.symbol, signal.market_type, signal.direction,
            signal.entry_price, size, signal.sl_price, signal.tp_price,
            leverage
        )

        # Place OCO (SL + TP)
        await self._place_oco(
            pos_id, signal.symbol, signal.market_type,
            signal.direction, size, signal.sl_price, signal.tp_price,
            leverage
        )

        self.db.log_event("INFO", "trade_opened",
                         f"{signal.direction} {signal.symbol} size={size:.6g} "
                         f"entry={signal.entry_price:.6g} sl={signal.sl_price:.6g} "
                         f"tp={signal.tp_price:.6g}",
                         signal.symbol)

        return pos_id

    async def _place_order(
        self, symbol: str, market_type: str, direction: str,
        order_type: str, volume: float, price: Optional[float] = None,
        price2: Optional[float] = None, signal_id: Optional[int] = None,
        reduce_only: bool = False, post_only: bool = False,
        leverage: float = 1.0, client_order_id: Optional[str] = None,
    ) -> Dict:
        """Place an order on the appropriate exchange."""
        if market_type in ("spot", "fx", "xstock"):
            result = await self.spot.add_order(
                pair=symbol, direction=direction, order_type=order_type,
                volume=volume, price=price, price2=price2,
                post_only=post_only, client_order_id=client_order_id,
                leverage=str(int(leverage)) if leverage > 1 else None,
                asset_class="tokenized_asset" if market_type == "xstock" else None,
            )
            cid = result.get("client_order_id", client_order_id or "unknown")
        else:
            ft_order_type = self._map_futures_order_type(order_type)
            result = await self.futures.send_order(
                symbol=symbol, side=direction, size=volume,
                order_type=ft_order_type, limit_price=price,
                stop_price=price2, reduce_only=reduce_only,
                client_order_id=client_order_id,
            )
            cid = result.get("client_order_id", client_order_id or "unknown")

        # Save to DB
        self.db.save_order(
            cid, symbol, market_type, direction, order_type, volume,
            price, price2, post_only, reduce_only,
            str(leverage), signal_id
        )

        if "error" not in result:
            exchange_id = result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("order_id")
            self.db.update_order_status(cid, "open", exchange_order_id=str(exchange_id) if exchange_id else None)
        else:
            self.db.update_order_status(cid, "rejected", error_msg=str(result["error"]))

        return result

    async def _place_oco(self, pos_id: int, symbol: str, market_type: str,
                         direction: str, size: float, sl_price: float,
                         tp_price: float, leverage: float):
        """Place synthetic OCO: SL + TP orders."""
        # SL direction is opposite
        sl_direction = "sell" if direction == "long" else "buy"
        tp_direction = sl_direction
        is_futures = market_type == "futures"

        # Stop Loss
        sl_result = await self._place_order(
            symbol, market_type, sl_direction,
            "stop-loss" if not is_futures else "stp",
            size, price2=sl_price if not is_futures else None,
            price=sl_price if is_futures else None,
            reduce_only=is_futures, leverage=leverage,
        )
        sl_cid = sl_result.get("client_order_id", "")

        # Take Profit
        tp_result = await self._place_order(
            symbol, market_type, tp_direction,
            "take-profit" if not is_futures else "take_profit",
            size, price2=tp_price if not is_futures else None,
            price=tp_price if is_futures else None,
            reduce_only=is_futures, leverage=leverage,
        )
        tp_cid = tp_result.get("client_order_id", "")

        # Track OCO pair
        self._oco_pairs[str(pos_id)] = {"sl_cid": sl_cid, "tp_cid": tp_cid}
        self.db.update_position(pos_id, sl_order_id=sl_cid, tp_order_id=tp_cid)

    async def handle_fill(self, client_order_id: str, fill_price: float,
                          fill_volume: float, fee: float = 0):
        """Handle a fill event - update DB and manage OCO cancellation."""
        # Find order in DB
        orders = self.db.get_open_orders()
        order = None
        for o in orders:
            if o["client_order_id"] == client_order_id:
                order = o
                break
        if not order:
            return

        # Save fill
        self.db.save_fill(order["id"], fill_price, fill_volume, fee)
        self.db.update_order_status(client_order_id, "filled")

        # Check slippage
        if order.get("price"):
            ok, slippage = self.risk.check_slippage(order["price"], fill_price)
            if not ok:
                self.db.log_event("WARNING", "slippage_exceeded",
                                f"Slippage {slippage:.4f}% on {client_order_id}",
                                order["symbol"])

        # Handle OCO cancellation
        for pos_id, oco in list(self._oco_pairs.items()):
            if client_order_id == oco["sl_cid"]:
                await self._cancel_order_safe(oco["tp_cid"], order["market_type"])
                del self._oco_pairs[pos_id]
                self.db.close_position(int(pos_id), 0, "stop_loss")
                break
            elif client_order_id == oco["tp_cid"]:
                await self._cancel_order_safe(oco["sl_cid"], order["market_type"])
                del self._oco_pairs[pos_id]
                self.db.close_position(int(pos_id), 0, "take_profit")
                break

    async def _cancel_order_safe(self, client_order_id: str, market_type: str):
        """Cancel an order safely (log errors, don't throw)."""
        try:
            if market_type in ("spot", "fx", "xstock"):
                await self.spot.cancel_order(client_order_id)
            else:
                await self.futures.cancel_order(cli_ord_id=client_order_id)
            self.db.update_order_status(client_order_id, "cancelled")
        except Exception as e:
            logger.error(f"Failed to cancel {client_order_id}: {e}")
            self.db.log_event("ERROR", "cancel_failed", str(e))

    async def manage_trailing_stops(self, positions: List[Dict], current_prices: Dict[str, float]):
        """Update trailing stops for open positions."""
        if not self.cfg.risk.trailing_enabled:
            return
        for pos in positions:
            symbol = pos["symbol"]
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            entry = pos["entry_price"]
            direction = pos["direction"]
            risk = abs(entry - pos["sl_price"])

            if direction == "long":
                profit = price - entry
                if profit >= risk * self.cfg.risk.trailing_activation_r:
                    new_sl = price * (1 - self.cfg.risk.trailing_pct / 100)
                    if new_sl > pos["sl_price"]:
                        self.db.update_position(pos["id"], sl_price=new_sl, trailing_active=1, trailing_price=new_sl)
                        logger.info(f"Trailing SL updated for {symbol}: {new_sl:.6g}")
            else:
                profit = entry - price
                if profit >= risk * self.cfg.risk.trailing_activation_r:
                    new_sl = price * (1 + self.cfg.risk.trailing_pct / 100)
                    if new_sl < pos["sl_price"]:
                        self.db.update_position(pos["id"], sl_price=new_sl, trailing_active=1, trailing_price=new_sl)
                        logger.info(f"Trailing SL updated for {symbol}: {new_sl:.6g}")

    async def check_time_stops(self, positions: List[Dict]):
        """Close positions that exceeded time stop."""
        for pos in positions:
            candles = pos.get("candles_elapsed", 0) + 1
            self.db.update_position(pos["id"], candles_elapsed=candles)
            if candles >= self.cfg.risk.time_stop_candles:
                logger.info(f"Time stop triggered for {pos['symbol']} after {candles} candles")
                await self.close_position(pos, "time_stop")

    async def close_position(self, pos: Dict, reason: str):
        """Close a position with market order."""
        direction = "sell" if pos["direction"] == "long" else "buy"
        is_futures = pos["market_type"] == "futures"

        await self._place_order(
            pos["symbol"], pos["market_type"], direction,
            "market" if not is_futures else "mkt",
            pos["size"], reduce_only=is_futures,
        )

        # Cancel OCO orders
        pos_id_str = str(pos["id"])
        if pos_id_str in self._oco_pairs:
            oco = self._oco_pairs[pos_id_str]
            await self._cancel_order_safe(oco["sl_cid"], pos["market_type"])
            await self._cancel_order_safe(oco["tp_cid"], pos["market_type"])
            del self._oco_pairs[pos_id_str]

        self.db.close_position(pos["id"], 0, reason)
        self.db.log_event("INFO", "position_closed", f"{pos['symbol']} closed: {reason}", pos["symbol"])

    async def close_all_positions(self, reason: str = "kill_switch"):
        """Emergency close all positions."""
        positions = self.db.get_open_positions()
        for pos in positions:
            await self.close_position(pos, reason)

        # Cancel all orders on exchange
        try:
            await self.spot.cancel_all()
        except Exception as e:
            logger.error(f"Spot cancel_all error: {e}")
        try:
            await self.futures.cancel_all_orders()
        except Exception as e:
            logger.error(f"Futures cancel_all error: {e}")

    async def reconcile_orders(self):
        """Reconcile local order state with exchange state."""
        try:
            exchange_orders = await self.spot.get_open_orders()
            local_orders = self.db.get_open_orders()
            local_cids = {o["client_order_id"] for o in local_orders}
            exchange_cids = set()
            for oid, odata in exchange_orders.items():
                cid = odata.get("cl_ord_id", "")
                if cid:
                    exchange_cids.add(cid)

            # Orders in local but not in exchange = probably filled/cancelled
            desync = local_cids - exchange_cids
            if desync:
                logger.warning(f"Desync detected: {len(desync)} orders not on exchange")
                self.db.log_event("WARNING", "order_desync",
                                f"Orders not on exchange: {list(desync)[:5]}")
        except Exception as e:
            logger.error(f"Reconciliation error: {e}")

    def _map_futures_order_type(self, ot: str) -> str:
        mapping = {
            "market": "mkt",
            "limit": "lmt",
            "stop-loss": "stp",
            "take-profit": "take_profit",
            "stop-loss-limit": "stp",
        }
        return mapping.get(ot, ot)

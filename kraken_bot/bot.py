"""Main bot orchestrator: coordinates all modules."""
import asyncio
import logging
import time
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .config import BotConfig, load_config
from .connectors.spot import KrakenSpotConnector
from .connectors.futures import KrakenFuturesConnector
from .persistence.database import Database
from .strategy.engine import StrategyEngine, Signal
from .risk.manager import RiskManager
from .execution.executor import OrderExecutor
from .portfolio.manager import PortfolioManager
from .alerts.notifier import AlertNotifier

logger = logging.getLogger(__name__)

# Market session helpers
FX_MARKETS = {"EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD"}
XSTOCK_SUFFIX = "x"


def is_weekday() -> bool:
    return datetime.now(timezone.utc).weekday() < 5


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.db = Database(config.db_path)
        self.spot = KrakenSpotConnector(
            config.kraken_spot_api_key, config.kraken_spot_api_secret,
            dry_run=config.mode != "live"
        )
        self.futures = KrakenFuturesConnector(
            config.kraken_futures_api_key, config.kraken_futures_api_secret,
            dry_run=config.mode != "live"
        )
        self.risk = RiskManager(config.risk, self.db)
        self.executor = OrderExecutor(config, self.spot, self.futures, self.db, self.risk)
        self.portfolio = PortfolioManager(self.db, self.risk)
        self.strategy = StrategyEngine(config.strategy, config.execution)
        self.alerts = AlertNotifier(config.alerts)

        self._start_time = time.time()
        self._status = "initializing"
        self._run_id: Optional[int] = None
        self._spot_pairs: Dict[str, str] = {}  # watchlist -> exchange ID
        self._futures_instruments: Dict[str, str] = {}
        self._current_prices: Dict[str, float] = {}
        self._running = False
        self._dead_man_task: Optional[asyncio.Task] = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    async def initialize(self):
        """Initialize bot: connect DB, discover markets, setup dead man switch."""
        logger.info(f"Initializing bot in {self.config.mode} mode...")
        self.db.connect()
        self._run_id = self.db.start_run(
            self.config.mode,
            json.dumps({"mode": self.config.mode}, default=str),
            "1.0.0"
        )

        # Discover spot pairs (crypto + FX)
        all_watchlist = (
            self.config.watchlist.crypto_spot +
            self.config.watchlist.spot_fx
        )
        try:
            self._spot_pairs = await self.spot.discover_pairs(all_watchlist)
            logger.info(f"Discovered {len(self._spot_pairs)} spot pairs")
        except Exception as e:
            logger.error(f"Spot discovery failed: {e}")
            self.db.log_event("ERROR", "discovery_failed", f"Spot: {e}")

        # Discover xStocks pairs (tokenized equities)
        if self.config.watchlist.xstocks:
            try:
                xstock_mapping = await self.spot.discover_pairs(self.config.watchlist.xstocks)
                self._spot_pairs.update(xstock_mapping)
                logger.info(f"Discovered {len(xstock_mapping)} xStocks pairs: "
                            f"{list(xstock_mapping.keys())}")
            except Exception as e:
                logger.error(f"xStocks discovery failed: {e}")
                self.db.log_event("ERROR", "discovery_failed", f"xStocks: {e}")

        # Discover futures instruments
        try:
            self._futures_instruments = await self.futures.discover_instruments(
                self.config.watchlist.futures
            )
            logger.info(f"Discovered {len(self._futures_instruments)} futures instruments")
        except Exception as e:
            logger.error(f"Futures discovery failed: {e}")
            self.db.log_event("ERROR", "discovery_failed", f"Futures: {e}")

        # Activate dead man switch
        if self.config.mode == "live":
            try:
                await self.spot.cancel_all_after(self.config.execution.dead_man_switch_timeout_spot)
                await self.futures.dead_man_switch(self.config.execution.dead_man_switch_timeout_futures)
                logger.info("Dead man switches activated")
            except Exception as e:
                logger.error(f"Dead man switch setup failed: {e}")

        self._status = "ready"
        self.db.log_event("INFO", "bot_initialized",
                         f"Mode={self.config.mode}, Spot={len(self._spot_pairs)}, "
                         f"Futures={len(self._futures_instruments)}")

    async def run(self):
        """Main bot loop."""
        await self.initialize()
        self._running = True
        self._status = "running"
        logger.info("Bot started, entering main loop...")

        await self.alerts.send(f"Bot started in {self.config.mode} mode", "INFO")

        try:
            while self._running:
                cycle_start = time.time()
                try:
                    await self._run_cycle()
                except Exception as e:
                    logger.error(f"Cycle error: {e}", exc_info=True)
                    self.db.log_event("ERROR", "cycle_error", str(e))

                # Wait for next 1H candle close (or shorter for responsiveness)
                elapsed = time.time() - cycle_start
                wait_time = max(60, 300 - elapsed)  # Check every 5 min minimum
                logger.debug(f"Cycle took {elapsed:.1f}s, waiting {wait_time:.0f}s")
                await asyncio.sleep(wait_time)
        finally:
            await self.shutdown()

    async def _run_cycle(self):
        """Single analysis + execution cycle."""
        # Renew dead man switch
        if self.config.mode == "live":
            try:
                await self.spot.renew_dead_man_switch(
                    self.config.execution.dead_man_switch_timeout_spot)
                await self.futures.renew_dead_man_switch(
                    self.config.execution.dead_man_switch_timeout_futures)
            except Exception as e:
                logger.error(f"Dead man switch renewal failed: {e}")
                self.db.log_event("ERROR", "dead_man_renewal_failed", str(e))

        # Check kill switch
        if self.risk.check_kill_switch():
            await self._handle_kill_switch()
            return

        # Update equity from exchange
        await self._update_equity()

        # Save equity snapshot
        self.risk.save_snapshot()

        # Manage existing positions (trailing, time stops)
        open_positions = self.db.get_open_positions()
        if open_positions:
            await self.executor.manage_trailing_stops(open_positions, self._current_prices)
            await self.executor.check_time_stops(open_positions)

        # Reconcile orders
        await self.executor.reconcile_orders()

        # Analyze all watchlist symbols
        await self._analyze_spot_crypto()
        await self._analyze_spot_fx()
        await self._analyze_xstocks()
        await self._analyze_futures()

    async def _analyze_spot_crypto(self):
        """Analyze crypto spot pairs."""
        for human_name, exchange_id in self._spot_pairs.items():
            if human_name not in self.config.watchlist.crypto_spot:
                continue
            await self._analyze_symbol(human_name, exchange_id, "spot", is_fx=False)

    async def _analyze_spot_fx(self):
        """Analyze FX pairs (weekday only)."""
        if not is_weekday():
            return
        for human_name, exchange_id in self._spot_pairs.items():
            if human_name not in self.config.watchlist.spot_fx:
                continue
            pip_size = 0.01 if "JPY" in human_name else 0.0001
            await self._analyze_symbol(human_name, exchange_id, "fx", is_fx=True, pip_size=pip_size)

    async def _analyze_xstocks(self):
        """Analyze xStocks pairs (weekday only, 24/5 market)."""
        if not is_weekday():
            return
        for human_name, exchange_id in self._spot_pairs.items():
            if human_name not in self.config.watchlist.xstocks:
                continue
            await self._analyze_symbol(
                human_name, exchange_id, "xstock", is_fx=False,
                asset_class="tokenized_asset",
            )

    async def _analyze_futures(self):
        """Analyze futures instruments."""
        for human_name, exchange_id in self._futures_instruments.items():
            try:
                candles_raw = await self.futures.get_candles(exchange_id, "1h")
                if not candles_raw or len(candles_raw) < 50:
                    continue

                candles = self._normalize_futures_candles(candles_raw)
                self.db.upsert_candles(exchange_id, "futures", candles)

                spread_pct = await self.futures.get_spread(exchange_id)

                signals = self.strategy.analyze(
                    exchange_id, "futures", candles, spread_pct, is_fx=False
                )

                for sig in signals:
                    if not sig.blocked:
                        pos_id = await self.executor.execute_signal(sig)
                        if pos_id:
                            await self.alerts.send(
                                f"Trade opened: {sig.direction} {sig.symbol} @ {sig.entry_price:.6g}")
                    else:
                        self.db.save_signal(
                            sig.symbol, sig.market_type, sig.direction,
                            sig.signal_type, sig.entry_price, sig.sl_price,
                            sig.tp_price, sig.reason,
                            sig.filters_passed, sig.filters_blocked
                        )
            except Exception as e:
                logger.error(f"Futures analysis error for {human_name}: {e}")
                self.db.log_event("ERROR", "analysis_error", str(e), human_name)

    async def _analyze_symbol(self, human_name: str, exchange_id: str,
                               market_type: str, is_fx: bool = False,
                               pip_size: float = 0.0001,
                               asset_class: Optional[str] = None):
        """Analyze a single spot symbol."""
        try:
            candles_raw = await self.spot.get_ohlc(
                exchange_id, interval=60, asset_class=asset_class
            )
            if not candles_raw or len(candles_raw) < 50:
                self.db.log_event("DEBUG", "insufficient_candles",
                                f"{human_name}: {len(candles_raw) if candles_raw else 0} candles",
                                human_name)
                return

            candles = self._normalize_spot_candles(candles_raw)
            self.db.upsert_candles(exchange_id, market_type, candles)

            # Update current price
            if candles:
                self._current_prices[exchange_id] = candles[-1]["close"]

            spread_pct = await self.spot.get_spread(exchange_id, asset_class=asset_class)

            signals = self.strategy.analyze(
                exchange_id, market_type, candles, spread_pct, is_fx, pip_size
            )

            for sig in signals:
                if not sig.blocked:
                    pos_id = await self.executor.execute_signal(sig)
                    if pos_id:
                        await self.alerts.send(
                            f"Trade opened: {sig.direction} {sig.symbol} @ {sig.entry_price:.6g}")
                else:
                    self.db.save_signal(
                        sig.symbol, sig.market_type, sig.direction,
                        sig.signal_type, sig.entry_price, sig.sl_price,
                        sig.tp_price, sig.reason,
                        sig.filters_passed, sig.filters_blocked
                    )
        except Exception as e:
            logger.error(f"Analysis error for {human_name}: {e}")
            self.db.log_event("ERROR", "analysis_error", str(e), human_name)

    def _normalize_spot_candles(self, raw: list) -> List[Dict]:
        """Normalize Kraken spot OHLC format to standard dict."""
        candles = []
        for c in raw:
            if len(c) >= 7:
                candles.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[6]),
                })
        return candles

    def _normalize_futures_candles(self, raw: list) -> List[Dict]:
        """Normalize Kraken futures candle format."""
        candles = []
        for c in raw:
            if isinstance(c, dict):
                candles.append({
                    "timestamp": int(c.get("time", 0)),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": float(c.get("volume", 0)),
                })
        return candles

    async def _update_equity(self):
        """Update equity from exchange balances."""
        try:
            if self.config.mode == "live":
                balance = await self.spot.get_trade_balance()
                equity = float(balance.get("eb", self.risk.equity))
                self.risk.update_equity(equity)
            else:
                # In dry-run, calculate from initial + realized PnL
                total_pnl = self.portfolio.update_position_prices(self._current_prices)
                self.risk.update_equity(self.config.risk.initial_equity + total_pnl)
        except Exception as e:
            logger.error(f"Equity update error: {e}")

    async def _handle_kill_switch(self):
        """Handle kill switch activation."""
        logger.critical("Kill switch activated!")
        self._status = "paused"
        await self.executor.close_all_positions("kill_switch")
        await self.alerts.send(
            f"KILL SWITCH ACTIVATED: {self.risk.kill_reason}", "CRITICAL")
        self.risk.save_snapshot()

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self._running = False
        self._status = "stopped"

        # Disable dead man switch
        try:
            await self.spot.cancel_all_after(0)
            await self.futures.dead_man_switch(0)
        except Exception:
            pass

        if self._run_id:
            self.db.end_run(self._run_id)

        await self.spot.close()
        await self.futures.close()
        await self.alerts.close()
        self.db.close()
        logger.info("Bot shutdown complete")

    def stop(self):
        """Signal the bot to stop."""
        self._running = False

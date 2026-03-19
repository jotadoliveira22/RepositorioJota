"""Portfolio manager: tracks positions, equity, exposure."""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from ..persistence.database import Database
from ..risk.manager import RiskManager

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Tracks portfolio state, positions, and equity."""

    def __init__(self, db: Database, risk: RiskManager):
        self.db = db
        self.risk = risk

    def get_summary(self) -> Dict:
        """Get portfolio summary."""
        positions = self.db.get_open_positions()
        equity = self.risk.equity
        daily_dd, weekly_dd = self.risk.get_drawdown()
        trades_today = self.db.get_trades_today_count()

        total_exposure = sum(p["size"] * p["entry_price"] for p in positions)
        total_unrealized = sum(p.get("pnl_unrealized", 0) for p in positions)

        return {
            "equity": equity,
            "daily_dd_pct": daily_dd,
            "weekly_dd_pct": weekly_dd,
            "open_positions": len(positions),
            "total_exposure": total_exposure,
            "total_unrealized_pnl": total_unrealized,
            "trades_today": trades_today,
            "is_paused": self.risk.is_paused,
            "kill_reason": self.risk.kill_reason,
            "positions": positions,
        }

    def update_position_prices(self, current_prices: Dict[str, float]):
        """Update unrealized PnL for all open positions."""
        positions = self.db.get_open_positions()
        total_pnl = 0
        for pos in positions:
            symbol = pos["symbol"]
            if symbol in current_prices:
                price = current_prices[symbol]
                if pos["direction"] == "long":
                    pnl = (price - pos["entry_price"]) * pos["size"]
                else:
                    pnl = (pos["entry_price"] - price) * pos["size"]
                self.db.update_position(pos["id"], current_price=price, pnl_unrealized=pnl)
                total_pnl += pnl
        return total_pnl

    def get_positions_by_type(self) -> Dict[str, List]:
        """Get positions grouped by market type."""
        positions = self.db.get_open_positions()
        grouped = {"spot": [], "futures": [], "fx": [], "xstock": []}
        for pos in positions:
            mt = pos.get("market_type", "spot")
            if mt in grouped:
                grouped[mt].append(pos)
            else:
                grouped["spot"].append(pos)
        return grouped

    def get_exposure_by_symbol(self) -> Dict[str, float]:
        """Get exposure per symbol."""
        positions = self.db.get_open_positions()
        exposure = {}
        for pos in positions:
            sym = pos["symbol"]
            val = pos["size"] * pos["entry_price"]
            exposure[sym] = exposure.get(sym, 0) + val
        return exposure

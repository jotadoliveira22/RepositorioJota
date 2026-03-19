"""Risk management: position sizing, drawdown, kill switch."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from ..config import RiskConfig
from ..persistence.database import Database

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages risk: sizing, trade limits, drawdown, kill switch."""

    def __init__(self, config: RiskConfig, db: Database):
        self.cfg = config
        self.db = db
        self._equity = config.initial_equity
        self._equity_high_daily = config.initial_equity
        self._equity_high_weekly = config.initial_equity
        self._daily_start_equity = config.initial_equity
        self._weekly_start_equity = config.initial_equity
        self._last_daily_reset = datetime.now(timezone.utc).date()
        self._last_weekly_reset = datetime.now(timezone.utc).isocalendar()[1]
        self._paused = False
        self._kill_reason = ""

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def update_equity(self, new_equity: float):
        """Update current equity and check drawdown."""
        self._equity = new_equity
        self._equity_high_daily = max(self._equity_high_daily, new_equity)
        self._equity_high_weekly = max(self._equity_high_weekly, new_equity)

        # Reset daily/weekly trackers
        now = datetime.now(timezone.utc)
        if now.date() != self._last_daily_reset:
            self._daily_start_equity = new_equity
            self._equity_high_daily = new_equity
            self._last_daily_reset = now.date()

        current_week = now.isocalendar()[1]
        if current_week != self._last_weekly_reset:
            self._weekly_start_equity = new_equity
            self._equity_high_weekly = new_equity
            self._last_weekly_reset = current_week

    def get_drawdown(self) -> Tuple[float, float]:
        """Returns (daily_dd_pct, weekly_dd_pct)."""
        daily_dd = 0.0
        if self._daily_start_equity > 0:
            daily_dd = (self._daily_start_equity - self._equity) / self._daily_start_equity * 100

        weekly_dd = 0.0
        if self._weekly_start_equity > 0:
            weekly_dd = (self._weekly_start_equity - self._equity) / self._weekly_start_equity * 100

        return max(0, daily_dd), max(0, weekly_dd)

    def check_kill_switch(self) -> bool:
        """Check if kill switch should activate. Returns True if triggered."""
        if self._paused:
            return True

        daily_dd, weekly_dd = self.get_drawdown()

        if daily_dd >= self.cfg.kill_switch_daily_dd_pct:
            self._paused = True
            self._kill_reason = f"Daily drawdown {daily_dd:.1f}% >= {self.cfg.kill_switch_daily_dd_pct}%"
            logger.critical(f"KILL SWITCH: {self._kill_reason}")
            self.db.log_event("CRITICAL", "kill_switch", self._kill_reason)
            return True

        if weekly_dd >= self.cfg.kill_switch_weekly_dd_pct:
            self._paused = True
            self._kill_reason = f"Weekly drawdown {weekly_dd:.1f}% >= {self.cfg.kill_switch_weekly_dd_pct}%"
            logger.critical(f"KILL SWITCH: {self._kill_reason}")
            self.db.log_event("CRITICAL", "kill_switch", self._kill_reason)
            return True

        return False

    def can_trade(self) -> Tuple[bool, str]:
        """Check if a new trade is allowed."""
        if self._paused:
            return False, f"Bot paused: {self._kill_reason}"

        if self.check_kill_switch():
            return False, f"Kill switch active: {self._kill_reason}"

        trades_today = self.db.get_trades_today_count()
        if trades_today >= self.cfg.max_trades_per_day:
            return False, f"Daily trade limit reached: {trades_today}/{self.cfg.max_trades_per_day}"

        return True, "OK"

    def calculate_position_size(
        self,
        entry_price: float,
        sl_price: float,
        leverage: float = 1.0,
        min_order_size: float = 0.0,
        step_size: float = 0.00000001,
    ) -> Tuple[float, bool, str]:
        """
        Calculate position size based on risk parameters.
        Returns (size, valid, reason).
        """
        risk_amount = self._equity * self.cfg.risk_per_trade_pct / 100
        distance_pct = abs(entry_price - sl_price) / entry_price
        if distance_pct == 0:
            return 0.0, False, "SL distance is zero"

        # Position size in base currency value
        position_value = risk_amount / distance_pct
        # Apply leverage
        margin_required = position_value / leverage
        # Size in units
        size = position_value / entry_price

        # Round to step size
        if step_size > 0:
            size = int(size / step_size) * step_size

        if size < min_order_size:
            return size, False, f"Size {size} below minimum {min_order_size}"

        if margin_required > self._equity:
            return size, False, f"Margin {margin_required:.2f} exceeds equity {self._equity:.2f}"

        return size, True, "OK"

    def validate_leverage(self, requested: float) -> float:
        """Enforce max leverage cap."""
        return min(requested, self.cfg.max_leverage)

    def check_slippage(self, expected_price: float, fill_price: float) -> Tuple[bool, float]:
        """Check if slippage is within acceptable range."""
        if expected_price == 0:
            return True, 0.0
        slippage_pct = abs(fill_price - expected_price) / expected_price * 100
        from ..config import ExecutionConfig
        # Use default, actual threshold passed from execution layer
        return slippage_pct <= 0.05, slippage_pct

    def pause(self, reason: str = "Manual pause"):
        self._paused = True
        self._kill_reason = reason
        self.db.log_event("WARNING", "bot_paused", reason)

    def resume(self):
        self._paused = False
        self._kill_reason = ""
        self.db.log_event("INFO", "bot_resumed", "Bot resumed from pause")

    def save_snapshot(self):
        """Save current equity snapshot to DB."""
        daily_dd, weekly_dd = self.get_drawdown()
        open_positions = len(self.db.get_open_positions())
        trades_today = self.db.get_trades_today_count()
        self.db.save_equity_snapshot(
            self._equity, max(self._equity_high_daily, self._equity_high_weekly),
            daily_dd, weekly_dd, open_positions, trades_today, ""
        )

"""Tests for risk management."""
import pytest
import tempfile
import os
from kraken_bot.risk.manager import RiskManager
from kraken_bot.config import RiskConfig
from kraken_bot.persistence.database import Database


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    database.connect()
    yield database
    database.close()
    os.unlink(path)


@pytest.fixture
def risk(db):
    config = RiskConfig(initial_equity=100.0, risk_per_trade_pct=5.0,
                        stop_loss_pct=5.0, max_trades_per_day=5,
                        kill_switch_daily_dd_pct=15.0, max_leverage=2.0)
    return RiskManager(config, db)


class TestPositionSizing:
    def test_basic_sizing(self, risk):
        size, valid, reason = risk.calculate_position_size(
            entry_price=50000, sl_price=47500, leverage=1.0
        )
        assert valid
        assert size > 0
        # Risk = $5, distance = 5%, so position_value = $100
        # size = $100 / $50000 = 0.002
        assert size == pytest.approx(0.002, rel=0.01)

    def test_leverage_sizing(self, risk):
        size, valid, reason = risk.calculate_position_size(
            entry_price=50000, sl_price=47500, leverage=2.0
        )
        assert valid
        assert size > 0

    def test_below_minimum(self, risk):
        size, valid, reason = risk.calculate_position_size(
            entry_price=50000, sl_price=47500, leverage=1.0,
            min_order_size=1.0  # way above what $100 can buy
        )
        assert not valid
        assert "minimum" in reason.lower()

    def test_zero_sl_distance(self, risk):
        size, valid, reason = risk.calculate_position_size(
            entry_price=100, sl_price=100
        )
        assert not valid

    def test_leverage_cap(self, risk):
        assert risk.validate_leverage(5.0) == 2.0
        assert risk.validate_leverage(1.0) == 1.0
        assert risk.validate_leverage(2.0) == 2.0


class TestKillSwitch:
    def test_daily_drawdown_trigger(self, risk):
        risk.update_equity(100)
        risk.update_equity(84)  # 16% drawdown
        triggered = risk.check_kill_switch()
        assert triggered
        assert risk.is_paused

    def test_no_trigger_within_limit(self, risk):
        risk.update_equity(100)
        risk.update_equity(90)  # 10% drawdown
        triggered = risk.check_kill_switch()
        assert not triggered

    def test_pause_resume(self, risk):
        risk.pause("test")
        assert risk.is_paused
        assert risk.kill_reason == "test"
        risk.resume()
        assert not risk.is_paused

    def test_can_trade_when_paused(self, risk):
        risk.pause("test")
        can, reason = risk.can_trade()
        assert not can


class TestTradeLimit:
    def test_trade_limit_check(self, risk, db):
        can, reason = risk.can_trade()
        assert can  # no trades yet

    def test_drawdown_calculation(self, risk):
        risk.update_equity(100)
        risk.update_equity(92)
        daily_dd, weekly_dd = risk.get_drawdown()
        assert daily_dd == pytest.approx(8.0, rel=0.1)

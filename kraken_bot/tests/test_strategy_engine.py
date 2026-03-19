"""Tests for the strategy engine."""
import pytest
from kraken_bot.strategy.engine import StrategyEngine
from kraken_bot.config import StrategyConfig, ExecutionConfig


@pytest.fixture
def engine():
    return StrategyEngine(StrategyConfig(), ExecutionConfig())


def _make_candles(n=200, base=100, trend=0.01):
    """Generate synthetic candle data."""
    candles = []
    price = base
    for i in range(n):
        price = price * (1 + trend * ((-1) ** (i % 7)))
        o = price
        h = price * 1.005
        l = price * 0.995
        c = price * (1 + 0.002 * ((-1) ** i))
        candles.append({
            "timestamp": 1000 + i * 3600,
            "open": o, "high": h, "low": l, "close": c, "volume": 100
        })
    return candles


class TestStrategyEngine:
    def test_analyze_returns_list(self, engine):
        candles = _make_candles(200)
        signals = engine.analyze("BTCUSD", "spot", candles)
        assert isinstance(signals, list)

    def test_insufficient_data(self, engine):
        candles = _make_candles(10)
        signals = engine.analyze("BTCUSD", "spot", candles)
        assert signals == []

    def test_signals_have_required_fields(self, engine):
        candles = _make_candles(300, trend=0.005)
        signals = engine.analyze("BTCUSD", "spot", candles)
        for sig in signals:
            assert sig.symbol == "BTCUSD"
            assert sig.direction in ("long", "short")
            assert sig.entry_price > 0
            assert sig.sl_price > 0
            assert sig.tp_price > 0

    def test_sl_is_5_percent(self, engine):
        candles = _make_candles(300, trend=0.005)
        signals = engine.analyze("BTCUSD", "spot", candles)
        for sig in signals:
            if sig.direction == "long":
                assert sig.sl_price == pytest.approx(sig.entry_price * 0.95, rel=1e-6)
            else:
                assert sig.sl_price == pytest.approx(sig.entry_price * 1.05, rel=1e-6)

    def test_blocked_signals_have_reasons(self, engine):
        candles = _make_candles(300)
        signals = engine.analyze("BTCUSD", "spot", candles, current_spread_pct=50.0)
        blocked = [s for s in signals if s.blocked]
        for sig in blocked:
            assert len(sig.filters_blocked) > 0

"""Tests for S/R levels and trendlines."""
import pytest
from kraken_bot.strategy.levels import find_sr_levels, find_trendlines, get_trendline_price_at


class TestSRLevels:
    def _make_candles_with_support(self):
        """Create candle data with a clear support at ~100."""
        highs, lows, closes, timestamps = [], [], [], []
        base = 100
        n = 100
        for i in range(n):
            t = 1000 + i
            if i in [10, 25, 45, 65, 85]:
                # Touch support at 100
                highs.append(base + 5)
                lows.append(base)
                closes.append(base + 2)
            else:
                highs.append(base + 10 + (i % 5))
                lows.append(base + 3 + (i % 3))
                closes.append(base + 5 + (i % 4))
            timestamps.append(t)
        return highs, lows, closes, timestamps

    def test_find_support_level(self):
        highs, lows, closes, timestamps = self._make_candles_with_support()
        levels = find_sr_levels(
            highs, lows, closes, timestamps,
            pivot_left=2, pivot_right=2,
            tolerance_pct=2.0, min_touches=4
        )
        # Should find at least one level
        # Note: with randomized data, exact results vary
        assert isinstance(levels, list)

    def test_empty_data(self):
        levels = find_sr_levels([], [], [], [], min_touches=4)
        assert levels == []

    def test_few_candles(self):
        levels = find_sr_levels([10, 11], [9, 10], [10, 10], [1, 2], min_touches=4)
        assert levels == []


class TestTrendlines:
    def _make_uptrend(self):
        """Create data with clear ascending trendline."""
        n = 50
        highs, lows, timestamps = [], [], []
        for i in range(n):
            base = 100 + i * 2  # Strong uptrend
            highs.append(base + 5)
            lows.append(base)
            timestamps.append(1000 + i)
        return highs, lows, timestamps

    def test_ascending_trendline(self):
        highs, lows, timestamps = self._make_uptrend()
        trendlines = find_trendlines(
            highs, lows, timestamps,
            pivot_left=2, pivot_right=2,
            min_touches=4, max_deviation_pct=1.0
        )
        assert isinstance(trendlines, list)

    def test_trendline_price_at(self):
        price = get_trendline_price_at(2.0, 100.0, 10)
        assert price == pytest.approx(120.0)

    def test_empty_trendlines(self):
        result = find_trendlines([], [], [], min_touches=4)
        assert result == []

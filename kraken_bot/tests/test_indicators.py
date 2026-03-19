"""Tests for technical indicators."""
import pytest
import math
from kraken_bot.strategy.indicators import (
    calculate_ema, calculate_atr, detect_pivots, calculate_atr_daily_average
)


class TestEMA:
    def test_basic_ema(self):
        closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        ema = calculate_ema(closes, 3)
        assert len(ema) == len(closes)
        assert math.isnan(ema[0])
        assert math.isnan(ema[1])
        assert ema[2] == pytest.approx(11.0, rel=1e-6)
        # EMA should trend upward
        valid = [v for v in ema if not math.isnan(v)]
        for i in range(1, len(valid)):
            assert valid[i] > valid[i - 1]

    def test_ema_insufficient_data(self):
        closes = [10, 11]
        ema = calculate_ema(closes, 5)
        assert all(math.isnan(v) for v in ema)

    def test_ema_constant(self):
        closes = [50.0] * 20
        ema = calculate_ema(closes, 5)
        valid = [v for v in ema if not math.isnan(v)]
        for v in valid:
            assert v == pytest.approx(50.0, rel=1e-6)


class TestATR:
    def test_basic_atr(self):
        highs = [12, 13, 14, 13, 15, 14, 16, 15, 17, 16]
        lows = [10, 11, 12, 11, 13, 12, 14, 13, 15, 14]
        closes = [11, 12, 13, 12, 14, 13, 15, 14, 16, 15]
        atr = calculate_atr(highs, lows, closes, 3)
        assert len(atr) == len(closes)
        valid = [v for v in atr if not math.isnan(v)]
        assert len(valid) > 0
        assert all(v > 0 for v in valid)

    def test_atr_daily_average(self):
        atr_1h = [1.0] * 240  # 10 days of hourly data
        avg = calculate_atr_daily_average(atr_1h, 5)
        assert avg > 0


class TestPivots:
    def test_detect_swing_high(self):
        highs = [10, 11, 12, 15, 12, 11, 10, 9, 10, 11]
        lows = [9, 10, 11, 14, 11, 10, 9, 8, 9, 10]
        sh, sl = detect_pivots(highs, lows, left=2, right=2)
        assert 3 in sh  # index 3 is swing high (15)

    def test_detect_swing_low(self):
        highs = [15, 14, 13, 10, 13, 14, 15, 16, 15, 14]
        lows = [14, 13, 12, 8, 12, 13, 14, 15, 14, 13]
        sh, sl = detect_pivots(highs, lows, left=2, right=2)
        assert 3 in sl  # index 3 is swing low (8)

    def test_no_pivots_flat(self):
        highs = [10] * 10
        lows = [9] * 10
        sh, sl = detect_pivots(highs, lows, left=2, right=2)
        assert len(sh) == 0
        assert len(sl) == 0

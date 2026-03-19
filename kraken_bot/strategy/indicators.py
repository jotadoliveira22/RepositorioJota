"""Technical indicators: EMA, ATR, pivot detection."""
import numpy as np
from typing import List, Tuple, Optional


def calculate_ema(closes: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average."""
    if len(closes) < period:
        return [np.nan] * len(closes)
    ema = [np.nan] * (period - 1)
    k = 2 / (period + 1)
    ema.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        ema.append(closes[i] * k + ema[-1] * (1 - k))
    return ema


def calculate_atr(highs: List[float], lows: List[float], closes: List[float],
                  period: int = 14) -> List[float]:
    """Calculate Average True Range."""
    if len(closes) < 2:
        return [0.0] * len(closes)
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))
    atr = [np.nan] * (period - 1)
    atr.append(sum(tr[:period]) / period)
    for i in range(period, len(tr)):
        atr.append((atr[-1] * (period - 1) + tr[i]) / period)
    return atr


def detect_pivots(highs: List[float], lows: List[float],
                  left: int = 3, right: int = 3) -> Tuple[List[int], List[int]]:
    """
    Detect swing high and swing low pivot points.
    Returns (swing_high_indices, swing_low_indices).
    """
    swing_highs = []
    swing_lows = []
    n = len(highs)

    for i in range(left, n - right):
        # Swing high: higher than left and right neighbors
        is_high = True
        for j in range(1, left + 1):
            if highs[i] <= highs[i - j]:
                is_high = False
                break
        if is_high:
            for j in range(1, right + 1):
                if highs[i] <= highs[i + j]:
                    is_high = False
                    break
        if is_high:
            swing_highs.append(i)

        # Swing low: lower than left and right neighbors
        is_low = True
        for j in range(1, left + 1):
            if lows[i] >= lows[i - j]:
                is_low = False
                break
        if is_low:
            for j in range(1, right + 1):
                if lows[i] >= lows[i + j]:
                    is_low = False
                    break
        if is_low:
            swing_lows.append(i)

    return swing_highs, swing_lows


def calculate_atr_daily_average(atr_1h: List[float], lookback_days: int = 14) -> float:
    """Calculate average daily ATR from 1H ATR values.
    24 candles = 1 day for crypto (use last valid values)."""
    valid = [v for v in atr_1h if not np.isnan(v)]
    candles_per_day = 24
    days_available = len(valid) // candles_per_day
    if days_available == 0:
        return valid[-1] if valid else 0.0
    days_to_use = min(lookback_days, days_available)
    daily_atrs = []
    for d in range(days_to_use):
        start = len(valid) - (d + 1) * candles_per_day
        end = start + candles_per_day
        chunk = valid[start:end]
        if chunk:
            daily_atrs.append(max(chunk))
    return sum(daily_atrs) / len(daily_atrs) if daily_atrs else 0.0

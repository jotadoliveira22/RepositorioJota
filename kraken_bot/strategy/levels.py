"""Support/Resistance levels and Trendline detection."""
import numpy as np
from typing import Dict, List, Optional, Tuple
from .indicators import detect_pivots


def find_sr_levels(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    timestamps: List[int],
    pivot_left: int = 3,
    pivot_right: int = 3,
    tolerance_pct: float = 0.5,
    min_touches: int = 4,
) -> List[Dict]:
    """
    Find support and resistance levels with >= min_touches.
    Groups nearby pivot points within tolerance_pct.
    """
    swing_highs, swing_lows = detect_pivots(highs, lows, pivot_left, pivot_right)

    # Collect all pivot prices
    pivot_points = []
    for idx in swing_highs:
        pivot_points.append({
            "price": highs[idx],
            "type": "resistance",
            "index": idx,
            "timestamp": timestamps[idx] if idx < len(timestamps) else 0,
        })
    for idx in swing_lows:
        pivot_points.append({
            "price": lows[idx],
            "type": "support",
            "index": idx,
            "timestamp": timestamps[idx] if idx < len(timestamps) else 0,
        })

    if not pivot_points:
        return []

    # Sort by price
    pivot_points.sort(key=lambda x: x["price"])

    # Group nearby pivots into levels
    levels = []
    used = set()

    for i, pivot in enumerate(pivot_points):
        if i in used:
            continue
        group = [pivot]
        used.add(i)
        tolerance = pivot["price"] * tolerance_pct / 100

        for j in range(i + 1, len(pivot_points)):
            if j in used:
                continue
            if abs(pivot_points[j]["price"] - pivot["price"]) <= tolerance:
                group.append(pivot_points[j])
                used.add(j)

        if len(group) >= min_touches:
            avg_price = sum(p["price"] for p in group) / len(group)
            # Determine type by majority
            support_count = sum(1 for p in group if p["type"] == "support")
            resistance_count = len(group) - support_count
            level_type = "support" if support_count >= resistance_count else "resistance"

            # Score: touches + recency bonus
            last_touch_ts = max(p["timestamp"] for p in group)
            max_ts = max(timestamps) if timestamps else 1
            recency = last_touch_ts / max_ts if max_ts > 0 else 0
            score = len(group) * 1.0 + recency * 2.0

            # Check if invalidated (close significantly beyond level)
            current_close = closes[-1] if closes else 0
            invalidated = False
            if level_type == "support" and current_close < avg_price * (1 - tolerance_pct * 2 / 100):
                invalidated = True
            elif level_type == "resistance" and current_close > avg_price * (1 + tolerance_pct * 2 / 100):
                invalidated = True

            if not invalidated:
                levels.append({
                    "price": round(avg_price, 8),
                    "type": level_type,
                    "touches": len(group),
                    "last_touch_ts": last_touch_ts,
                    "score": round(score, 4),
                    "price_range": (
                        round(min(p["price"] for p in group), 8),
                        round(max(p["price"] for p in group), 8)
                    ),
                })

    # Sort by score descending
    levels.sort(key=lambda x: x["score"], reverse=True)
    return levels


def find_trendlines(
    highs: List[float],
    lows: List[float],
    timestamps: List[int],
    pivot_left: int = 3,
    pivot_right: int = 3,
    min_touches: int = 4,
    max_deviation_pct: float = 0.3,
) -> List[Dict]:
    """
    Find ascending/descending trendlines with >= min_touches.
    Uses linear regression on pivot points.
    """
    swing_highs, swing_lows = detect_pivots(highs, lows, pivot_left, pivot_right)
    trendlines = []

    # Ascending trendlines (connecting swing lows)
    if len(swing_lows) >= min_touches:
        low_points = [(idx, lows[idx]) for idx in swing_lows]
        ascending = _fit_trendlines(low_points, "ascending", min_touches, max_deviation_pct, timestamps)
        trendlines.extend(ascending)

    # Descending trendlines (connecting swing highs)
    if len(swing_highs) >= min_touches:
        high_points = [(idx, highs[idx]) for idx in swing_highs]
        descending = _fit_trendlines(high_points, "descending", min_touches, max_deviation_pct, timestamps)
        trendlines.extend(descending)

    trendlines.sort(key=lambda x: x["score"], reverse=True)
    return trendlines


def _fit_trendlines(
    points: List[Tuple[int, float]],
    direction: str,
    min_touches: int,
    max_deviation_pct: float,
    timestamps: List[int],
) -> List[Dict]:
    """Fit trendlines using iterative approach with pivot points."""
    results = []
    n = len(points)
    if n < min_touches:
        return results

    # Try all pairs of starting points and find lines that touch enough pivots
    best_lines = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            idx_a, price_a = points[i]
            idx_b, price_b = points[j]
            if idx_b == idx_a:
                continue

            slope = (price_b - price_a) / (idx_b - idx_a)
            intercept = price_a - slope * idx_a

            # For ascending: slope should be positive; descending: negative
            if direction == "ascending" and slope <= 0:
                continue
            if direction == "descending" and slope >= 0:
                continue

            # Count touches within tolerance
            touches = []
            max_dev = 0
            for k in range(n):
                idx_k, price_k = points[k]
                expected = slope * idx_k + intercept
                if expected == 0:
                    continue
                deviation_pct = abs(price_k - expected) / expected * 100
                if deviation_pct <= max_deviation_pct:
                    touches.append(points[k])
                    max_dev = max(max_dev, deviation_pct)

            if len(touches) >= min_touches:
                # Recency score
                max_ts_idx = max(t[0] for t in touches)
                max_idx = max(p[0] for p in points) if points else 1
                recency = max_ts_idx / max_idx if max_idx > 0 else 0
                score = len(touches) * 1.5 + recency * 2.0

                best_lines.append({
                    "direction": direction,
                    "slope": slope,
                    "intercept": intercept,
                    "touches": len(touches),
                    "points": [(t[0], t[1]) for t in touches],
                    "score": round(score, 4),
                    "max_deviation": round(max_dev, 4),
                })

    # Deduplicate similar lines
    seen = set()
    for line in sorted(best_lines, key=lambda x: x["score"], reverse=True):
        key = (round(line["slope"], 6), round(line["intercept"], 2))
        if key not in seen:
            seen.add(key)
            results.append(line)
            if len(results) >= 5:
                break

    return results


def get_trendline_price_at(slope: float, intercept: float, index: int) -> float:
    """Get the trendline price at a given candle index."""
    return slope * index + intercept

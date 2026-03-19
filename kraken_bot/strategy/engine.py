"""Strategy engine: generates trading signals."""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .indicators import calculate_ema, calculate_atr, calculate_atr_daily_average
from .levels import find_sr_levels, find_trendlines, get_trendline_price_at
from ..config import StrategyConfig, ExecutionConfig

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    market_type: str
    direction: str  # long / short
    signal_type: str  # sr_bounce / sr_break / trendline_bounce / trendline_break
    entry_price: float
    sl_price: float
    tp_price: float
    reason: str
    filters_passed: List[str] = field(default_factory=list)
    filters_blocked: List[str] = field(default_factory=list)
    blocked: bool = False
    rr_ratio: float = 0.0
    level_info: Dict = field(default_factory=dict)


class StrategyEngine:
    """Main strategy engine for S/R + Trendlines + EMA confirmation."""

    def __init__(self, strategy_config: StrategyConfig, execution_config: ExecutionConfig):
        self.cfg = strategy_config
        self.exec_cfg = execution_config

    def analyze(
        self,
        symbol: str,
        market_type: str,
        candles: List[Dict],
        current_spread_pct: float = 0.0,
        is_fx: bool = False,
        pip_size: float = 0.0001,
    ) -> List[Signal]:
        """
        Analyze candles and generate signals.
        Returns list of signals (may be empty, may have blocked signals).
        """
        if len(candles) < max(self.cfg.ema_slow, self.cfg.lookback_candles // 2):
            logger.debug(f"{symbol}: not enough candles ({len(candles)})")
            return []

        opens = [c["open"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        timestamps = [c["timestamp"] for c in candles]

        # Calculate indicators
        ema_fast = calculate_ema(closes, self.cfg.ema_fast)
        ema_slow = calculate_ema(closes, self.cfg.ema_slow)
        atr = calculate_atr(highs, lows, closes, self.exec_cfg.atr_period)

        current_close = closes[-1]
        current_high = highs[-1]
        current_low = lows[-1]
        prev_close = closes[-2] if len(closes) > 1 else current_close
        current_ema_fast = ema_fast[-1] if ema_fast else None
        current_ema_slow = ema_slow[-1] if ema_slow else None
        current_atr = atr[-1] if atr else 0

        # EMA confirmation
        if current_ema_fast is None or current_ema_slow is None:
            return []

        import math
        if math.isnan(current_ema_fast) or math.isnan(current_ema_slow):
            return []

        ema_bullish = current_ema_fast > current_ema_slow
        ema_bearish = current_ema_fast < current_ema_slow

        # Macro filter (optional)
        if self.cfg.use_macro_filter and len(closes) >= self.cfg.ema_macro:
            ema_macro = calculate_ema(closes, self.cfg.ema_macro)
            if not math.isnan(ema_macro[-1]):
                if ema_bullish and current_close < ema_macro[-1]:
                    ema_bullish = False
                if ema_bearish and current_close > ema_macro[-1]:
                    ema_bearish = False

        # Find S/R levels
        sr_levels = find_sr_levels(
            highs, lows, closes, timestamps,
            self.cfg.pivot_left, self.cfg.pivot_right,
            self.cfg.sr_tolerance_pct, self.cfg.sr_min_touches
        )

        # Find trendlines
        trendlines = find_trendlines(
            highs, lows, timestamps,
            self.cfg.pivot_left, self.cfg.pivot_right,
            self.cfg.trendline_min_touches, self.cfg.trendline_max_deviation_pct
        )

        signals = []

        # --- S/R Bounce Signals ---
        for level in sr_levels:
            proximity_range = current_close * self.cfg.entry_proximity_pct / 100

            if level["type"] == "support" and ema_bullish:
                if abs(current_low - level["price"]) <= proximity_range:
                    # Bullish rejection candle: close > open and close in upper half
                    candle_range = current_high - current_low
                    if candle_range > 0 and current_close > opens[-1]:
                        close_position_in_range = (current_close - current_low) / candle_range
                        if close_position_in_range >= 0.5:
                            sl = level["price"] * (1 - self.cfg.sr_tolerance_pct / 100)
                            tp = self._find_next_resistance(sr_levels, current_close)
                            if tp is None:
                                # Use min R:R
                                risk = current_close - sl
                                tp = current_close + risk * self.cfg.min_rr_ratio
                            sig = Signal(
                                symbol=symbol, market_type=market_type,
                                direction="long", signal_type="sr_bounce",
                                entry_price=current_close, sl_price=sl, tp_price=tp,
                                reason=f"Support bounce at {level['price']:.6g} ({level['touches']} touches), EMA20>EMA50",
                                level_info=level,
                            )
                            self._apply_filters(sig, current_atr, atr, current_spread_pct, is_fx, pip_size)
                            signals.append(sig)

            elif level["type"] == "resistance" and ema_bearish:
                if abs(current_high - level["price"]) <= proximity_range:
                    candle_range = current_high - current_low
                    if candle_range > 0 and current_close < opens[-1]:
                        close_position_in_range = (current_high - current_close) / candle_range
                        if close_position_in_range >= 0.5:
                            sl = level["price"] * (1 + self.cfg.sr_tolerance_pct / 100)
                            tp = self._find_next_support(sr_levels, current_close)
                            if tp is None:
                                risk = sl - current_close
                                tp = current_close - risk * self.cfg.min_rr_ratio
                            sig = Signal(
                                symbol=symbol, market_type=market_type,
                                direction="short", signal_type="sr_bounce",
                                entry_price=current_close, sl_price=sl, tp_price=tp,
                                reason=f"Resistance bounce at {level['price']:.6g} ({level['touches']} touches), EMA20<EMA50",
                                level_info=level,
                            )
                            self._apply_filters(sig, current_atr, atr, current_spread_pct, is_fx, pip_size)
                            signals.append(sig)

        # --- Trendline Bounce Signals ---
        current_idx = len(candles) - 1
        for tl in trendlines:
            tl_price = get_trendline_price_at(tl["slope"], tl["intercept"], current_idx)
            proximity_range = current_close * self.cfg.entry_proximity_pct / 100

            if tl["direction"] == "ascending" and ema_bullish:
                if abs(current_low - tl_price) <= proximity_range and current_close > tl_price:
                    candle_range = current_high - current_low
                    if candle_range > 0 and current_close > opens[-1]:
                        sl = tl_price * (1 - self.cfg.sr_tolerance_pct / 100)
                        tp = self._find_next_resistance(sr_levels, current_close)
                        if tp is None:
                            risk = current_close - sl
                            tp = current_close + risk * self.cfg.min_rr_ratio
                        sig = Signal(
                            symbol=symbol, market_type=market_type,
                            direction="long", signal_type="trendline_bounce",
                            entry_price=current_close, sl_price=sl, tp_price=tp,
                            reason=f"Ascending trendline bounce ({tl['touches']} touches), EMA20>EMA50",
                        )
                        self._apply_filters(sig, current_atr, atr, current_spread_pct, is_fx, pip_size)
                        signals.append(sig)

            elif tl["direction"] == "descending" and ema_bearish:
                if abs(current_high - tl_price) <= proximity_range and current_close < tl_price:
                    candle_range = current_high - current_low
                    if candle_range > 0 and current_close < opens[-1]:
                        sl = tl_price * (1 + self.cfg.sr_tolerance_pct / 100)
                        tp = self._find_next_support(sr_levels, current_close)
                        if tp is None:
                            risk = sl - current_close
                            tp = current_close - risk * self.cfg.min_rr_ratio
                        sig = Signal(
                            symbol=symbol, market_type=market_type,
                            direction="short", signal_type="trendline_bounce",
                            entry_price=current_close, sl_price=sl, tp_price=tp,
                            reason=f"Descending trendline bounce ({tl['touches']} touches), EMA20<EMA50",
                        )
                        self._apply_filters(sig, current_atr, atr, current_spread_pct, is_fx, pip_size)
                        signals.append(sig)

        # Enforce SL = 5% from entry
        for sig in signals:
            if sig.direction == "long":
                sig.sl_price = sig.entry_price * 0.95
            else:
                sig.sl_price = sig.entry_price * 1.05
            # Recalculate R:R
            risk = abs(sig.entry_price - sig.sl_price)
            reward = abs(sig.tp_price - sig.entry_price)
            sig.rr_ratio = reward / risk if risk > 0 else 0

        return signals

    def _find_next_resistance(self, levels: List[Dict], current_price: float) -> Optional[float]:
        """Find the next resistance level above current price."""
        resistances = sorted(
            [l for l in levels if l["type"] == "resistance" and l["price"] > current_price * 1.001],
            key=lambda x: x["price"]
        )
        return resistances[0]["price"] if resistances else None

    def _find_next_support(self, levels: List[Dict], current_price: float) -> Optional[float]:
        """Find the next support level below current price."""
        supports = sorted(
            [l for l in levels if l["type"] == "support" and l["price"] < current_price * 0.999],
            key=lambda x: x["price"],
            reverse=True
        )
        return supports[0]["price"] if supports else None

    def _apply_filters(self, signal: Signal, current_atr: float,
                       atr_series: List[float], spread_pct: float,
                       is_fx: bool, pip_size: float):
        """Apply execution quality filters to a signal."""
        import math

        # Filter 1: Spread check
        risk = abs(signal.entry_price - signal.sl_price)
        reward = abs(signal.tp_price - signal.entry_price)
        cost_ratio = spread_pct / 100 * signal.entry_price / reward if reward > 0 else 1.0

        if is_fx:
            spread_pips = spread_pct / 100 * signal.entry_price / pip_size
            if spread_pips > self.exec_cfg.max_spread_fx_pips:
                signal.filters_blocked.append(
                    f"spread_fx: {spread_pips:.1f} pips > {self.exec_cfg.max_spread_fx_pips}")
                signal.blocked = True
            else:
                signal.filters_passed.append(f"spread_fx: {spread_pips:.1f} pips OK")

        if cost_ratio > self.exec_cfg.max_cost_tp_ratio:
            signal.filters_blocked.append(
                f"cost_tp_ratio: {cost_ratio:.2%} > {self.exec_cfg.max_cost_tp_ratio:.0%}")
            signal.blocked = True
        else:
            signal.filters_passed.append(f"cost_tp_ratio: {cost_ratio:.2%} OK")

        # Filter 2: ATR exhaustion
        if not math.isnan(current_atr) and current_atr > 0:
            atr_daily_avg = calculate_atr_daily_average(
                atr_series, self.exec_cfg.atr_daily_lookback)
            if atr_daily_avg > 0:
                atr_ratio = current_atr / atr_daily_avg
                if atr_ratio >= self.exec_cfg.atr_filter_threshold:
                    signal.filters_blocked.append(
                        f"atr_exhaustion: {atr_ratio:.1%} >= {self.exec_cfg.atr_filter_threshold:.0%}")
                    signal.blocked = True
                else:
                    signal.filters_passed.append(f"atr_ratio: {atr_ratio:.1%} OK")

        # Filter 3: Minimum R:R
        rr = reward / risk if risk > 0 else 0
        signal.rr_ratio = rr
        if rr < self.cfg.min_rr_ratio:
            signal.filters_blocked.append(
                f"rr_ratio: {rr:.2f} < {self.cfg.min_rr_ratio}")
            signal.blocked = True
        else:
            signal.filters_passed.append(f"rr_ratio: {rr:.2f} OK")

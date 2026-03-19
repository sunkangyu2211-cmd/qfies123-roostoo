"""Trend rider strategy — rides strong trends using EMA + ADX + volume.

Combines multiple trend-confirmation signals:
- EMA alignment (fast > medium > slow = uptrend)
- ADX strength filter (only trade when trend is strong)
- Volume-weighted price action
- Trailing logic via EMA crossover for exits

Designed to capture big moves in trending volatile coins.
"""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class TrendRiderStrategy(BaseStrategy):
    """Ride strong trends with multi-EMA alignment + ADX confirmation."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.ema_fast: int = config.get("trend_ema_fast", 8)
        self.ema_medium: int = config.get("trend_ema_medium", 21)
        self.ema_slow: int = config.get("trend_ema_slow", 50)
        self.adx_period: int = config.get("trend_adx_period", 14)
        self.adx_threshold: float = config.get("trend_adx_threshold", 20)
        self.volume_ma: int = config.get("trend_volume_ma", 20)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        min_periods = self.ema_slow + 10
        if ohlcv is None or len(ohlcv) < min_periods:
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Insufficient data")

        high = ohlcv["high"].astype(float)
        low = ohlcv["low"].astype(float)
        close = ohlcv["close"].astype(float)
        volume = ohlcv["volume"].astype(float)

        # Triple EMA
        ema_fast = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_medium = close.ewm(span=self.ema_medium, adjust=False).mean()
        ema_slow = close.ewm(span=self.ema_slow, adjust=False).mean()

        # ADX for trend strength
        adx_indicator = ta.trend.ADXIndicator(
            high=high, low=low, close=close, window=self.adx_period
        )
        adx = adx_indicator.adx()
        plus_di = adx_indicator.adx_pos()
        minus_di = adx_indicator.adx_neg()

        # Volume relative to average
        vol_ma = volume.rolling(self.volume_ma).mean()

        current_close = close.iloc[-1]
        ef = ema_fast.iloc[-1]
        em = ema_medium.iloc[-1]
        es = ema_slow.iloc[-1]
        current_adx = adx.iloc[-1]
        current_plus_di = plus_di.iloc[-1]
        current_minus_di = minus_di.iloc[-1]
        current_vol = volume.iloc[-1]
        avg_vol = vol_ma.iloc[-1]

        if pd.isna(current_adx) or pd.isna(es):
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Indicators not ready")

        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        ema_aligned_bull = ef > em > es
        ema_aligned_bear = ef < em < es
        trend_strong = current_adx > self.adx_threshold

        # Previous bar EMAs for crossover detection
        prev_ef = ema_fast.iloc[-2]
        prev_em = ema_medium.iloc[-2]

        reasons = []
        action = "HOLD"
        confidence = 0.0

        # BUY: EMAs aligned bullish + strong trend + DI+ > DI-
        if ema_aligned_bull and trend_strong and current_plus_di > current_minus_di:
            # Extra: fast EMA just crossed above medium (fresh signal)
            fresh_cross = prev_ef <= prev_em and ef > em
            adx_strength = min((current_adx - self.adx_threshold) / 30, 1.0)
            confidence = 0.5 + adx_strength * 0.3
            if fresh_cross:
                confidence += 0.2
                reasons.append("Fresh EMA crossover")
            if vol_ratio > 1.2:
                confidence = min(confidence + 0.1, 1.0)
                reasons.append(f"Volume surge ({vol_ratio:.1f}x)")

            action = "BUY"
            reasons.append(
                f"EMA aligned bullish (ADX={current_adx:.0f}, +DI={current_plus_di:.0f})"
            )

        # SELL: EMAs aligned bearish OR fast crosses below medium
        elif ema_aligned_bear and trend_strong and current_minus_di > current_plus_di:
            action = "SELL"
            confidence = 0.7
            reasons.append(
                f"EMA aligned bearish (ADX={current_adx:.0f}, -DI={current_minus_di:.0f})"
            )
        elif prev_ef >= prev_em and ef < em and current_close < em:
            # Fast EMA crossed below medium — exit signal
            action = "SELL"
            confidence = 0.6
            reasons.append("Fast EMA crossed below medium — trend weakening")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No trend signal",
        )

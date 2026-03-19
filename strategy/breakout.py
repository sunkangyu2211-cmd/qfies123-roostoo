"""Volatility breakout strategy — buy when price breaks above recent range.

Uses ATR (Average True Range) to detect volatility expansion and
Donchian channels to identify breakouts. Designed for high-volatility
coins where breakouts lead to sustained moves.
"""

from typing import Any, Optional

import numpy as np
import pandas as pd
import ta

from .base import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    """Buy on breakouts above the Donchian channel with ATR confirmation."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.channel_period: int = config.get("breakout_channel_period", 20)
        self.atr_period: int = config.get("breakout_atr_period", 14)
        self.atr_multiplier: float = config.get("breakout_atr_multiplier", 1.5)
        self.volume_surge: float = config.get("breakout_volume_surge", 1.3)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        if ohlcv is None or len(ohlcv) < self.channel_period + 5:
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Insufficient data")

        high = ohlcv["high"].astype(float)
        low = ohlcv["low"].astype(float)
        close = ohlcv["close"].astype(float)
        volume = ohlcv["volume"].astype(float)

        # Donchian channel: highest high / lowest low over N periods
        upper_channel = high.rolling(self.channel_period).max()
        lower_channel = low.rolling(self.channel_period).min()

        # ATR for volatility measurement
        atr = ta.volatility.AverageTrueRange(
            high=high, low=low, close=close, window=self.atr_period
        ).average_true_range()

        current_close = close.iloc[-1]
        prev_close = close.iloc[-2]
        current_atr = atr.iloc[-1]
        prev_upper = upper_channel.iloc[-2]  # Previous bar's channel top
        prev_lower = lower_channel.iloc[-2]

        if pd.isna(current_atr) or pd.isna(prev_upper):
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="ATR not ready")

        # Volume confirmation: current volume vs recent average
        avg_vol = volume.iloc[-20:].mean()
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

        reasons = []
        action = "HOLD"
        confidence = 0.0

        # BREAKOUT BUY: price breaks above channel + ATR expansion + volume surge
        if current_close > prev_upper:
            breakout_strength = (current_close - prev_upper) / current_atr
            if breakout_strength >= 0.5 and vol_ratio >= self.volume_surge:
                action = "BUY"
                confidence = min(breakout_strength * 0.5 + (vol_ratio - 1) * 0.3, 1.0)
                reasons.append(
                    f"Breakout above {prev_upper:.2f} "
                    f"(strength={breakout_strength:.1f}x ATR, vol={vol_ratio:.1f}x)"
                )

        # BREAKDOWN SELL: price breaks below channel
        elif current_close < prev_lower:
            breakdown_strength = (prev_lower - current_close) / current_atr
            if breakdown_strength >= 0.3:
                action = "SELL"
                confidence = min(breakdown_strength * 0.5, 1.0)
                reasons.append(
                    f"Breakdown below {prev_lower:.2f} "
                    f"(strength={breakdown_strength:.1f}x ATR)"
                )

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No breakout detected",
        )

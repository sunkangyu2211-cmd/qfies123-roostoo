"""Aggressive RSI strategy — wider triggers + momentum filter for volatile coins.

A more aggressive variant of RSI that:
- Uses tighter oversold/overbought thresholds to trigger more trades
- Adds a short-term momentum filter (5-period rate of change)
- Scales confidence by how far RSI is from neutral
- Designed for high-volatility coins where mean reversion is faster
"""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class AggressiveRSIStrategy(BaseStrategy):
    """Aggressive RSI mean-reversion tuned for volatile assets."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.rsi_period: int = config.get("aggressive_rsi_period", 10)
        self.rsi_oversold: float = config.get("aggressive_rsi_oversold", 25)
        self.rsi_overbought: float = config.get("aggressive_rsi_overbought", 75)
        self.roc_period: int = config.get("aggressive_roc_period", 5)
        self.roc_threshold: float = config.get("aggressive_roc_threshold", 0.5)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        if ohlcv is None or len(ohlcv) < max(self.rsi_period, self.roc_period) + 5:
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Insufficient data")

        close = ohlcv["close"].astype(float)

        # RSI
        rsi = ta.momentum.RSIIndicator(close=close, window=self.rsi_period).rsi()
        current_rsi = rsi.iloc[-1]

        # Rate of change (short-term momentum)
        roc = close.pct_change(self.roc_period) * 100
        current_roc = roc.iloc[-1]

        if pd.isna(current_rsi) or pd.isna(current_roc):
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Indicators not ready")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        # BUY: RSI oversold AND momentum starting to recover (ROC turning positive)
        if current_rsi < self.rsi_oversold:
            rsi_depth = (self.rsi_oversold - current_rsi) / self.rsi_oversold
            if current_roc > -self.roc_threshold:
                # Momentum is recovering from dip — good entry
                action = "BUY"
                confidence = min(rsi_depth + 0.3, 1.0)
                reasons.append(f"RSI({current_rsi:.1f}) oversold + momentum recovering (ROC={current_roc:.1f}%)")
            elif current_rsi < 15:
                # Extreme oversold — buy even without momentum confirmation
                action = "BUY"
                confidence = min(rsi_depth, 1.0)
                reasons.append(f"RSI({current_rsi:.1f}) extreme oversold")

        # SELL: RSI overbought AND momentum fading
        elif current_rsi > self.rsi_overbought:
            rsi_height = (current_rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
            if current_roc < self.roc_threshold:
                action = "SELL"
                confidence = min(rsi_height + 0.3, 1.0)
                reasons.append(f"RSI({current_rsi:.1f}) overbought + momentum fading (ROC={current_roc:.1f}%)")
            elif current_rsi > 85:
                action = "SELL"
                confidence = min(rsi_height, 1.0)
                reasons.append(f"RSI({current_rsi:.1f}) extreme overbought")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else f"RSI={current_rsi:.1f} neutral",
        )

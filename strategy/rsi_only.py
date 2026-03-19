"""RSI-only trading strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class RSIOnlyStrategy(BaseStrategy):
    """Pure RSI oversold/overbought strategy."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.rsi_period: int = config.get("rsi_period", 14)
        self.rsi_oversold: int = config.get("rsi_oversold", 30)
        self.rsi_overbought: int = config.get("rsi_overbought", 70)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if ohlcv is not None and len(ohlcv) >= self.rsi_period:
            close = ohlcv["close"].astype(float)
            rsi_series = ta.momentum.RSIIndicator(close=close, window=self.rsi_period).rsi()
            current_rsi = rsi_series.iloc[-1]

            if not pd.isna(current_rsi):
                if current_rsi < self.rsi_oversold:
                    action = "BUY"
                    confidence = min((self.rsi_oversold - current_rsi) / 30.0, 1.0)
                    reasons.append(f"RSI({current_rsi:.1f}) oversold")
                elif current_rsi > self.rsi_overbought:
                    action = "SELL"
                    confidence = min((current_rsi - self.rsi_overbought) / 30.0, 1.0)
                    reasons.append(f"RSI({current_rsi:.1f}) overbought")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "RSI in neutral zone",
        )

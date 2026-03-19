"""MACD crossover strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class MACDStrategy(BaseStrategy):
    """MACD line and signal line crossover strategy."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.macd_fast: int = config.get("macd_fast", 12)
        self.macd_slow: int = config.get("macd_slow", 26)
        self.macd_signal: int = config.get("macd_signal", 9)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if ohlcv is not None and len(ohlcv) >= self.macd_slow + self.macd_signal - 1:
            close = ohlcv["close"].astype(float)
            macd = ta.trend.MACD(close=close, window_fast=self.macd_fast, window_slow=self.macd_slow, window_sign=self.macd_signal)
            macd_line = macd.macd()
            signal_line = macd.macd_signal()

            if len(macd_line) >= 2 and len(signal_line) >= 2:
                curr_macd = macd_line.iloc[-1]
                prev_macd = macd_line.iloc[-2]
                curr_signal = signal_line.iloc[-1]
                prev_signal = signal_line.iloc[-2]

                if not any(pd.isna(v) for v in [curr_macd, prev_macd, curr_signal, prev_signal]):
                    # MACD crosses above signal line - bullish
                    if prev_macd <= prev_signal and curr_macd > curr_signal:
                        action = "BUY"
                        confidence = 0.75
                        reasons.append(f"MACD crossed above signal line")
                    # MACD crosses below signal line - bearish
                    elif prev_macd >= prev_signal and curr_macd < curr_signal:
                        action = "SELL"
                        confidence = 0.75
                        reasons.append(f"MACD crossed below signal line")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No MACD signal",
        )

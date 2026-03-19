"""Stochastic oscillator strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class StochasticStrategy(BaseStrategy):
    """Stochastic oscillator oversold/overbought strategy."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.k_period: int = config.get("k_period", 14)
        self.d_period: int = config.get("d_period", 3)
        self.oversold: float = config.get("stoch_oversold", 20.0)
        self.overbought: float = config.get("stoch_overbought", 80.0)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if ohlcv is not None and len(ohlcv) >= self.k_period + self.d_period - 1:
            high = ohlcv["high"].astype(float)
            low = ohlcv["low"].astype(float)
            close = ohlcv["close"].astype(float)

            stoch = ta.momentum.StochasticOscillator(
                high=high, low=low, close=close, window=self.k_period, smooth_window=self.d_period
            )
            k_line = stoch.stoch()
            d_line = stoch.stoch_signal()

            if len(k_line) > 0 and len(d_line) > 0:
                curr_k = k_line.iloc[-1]
                curr_d = d_line.iloc[-1]

                if not any(pd.isna(v) for v in [curr_k, curr_d]):
                    # Oversold - bullish
                    if curr_k < self.oversold:
                        action = "BUY"
                        confidence = min((self.oversold - curr_k) / self.oversold, 1.0)
                        reasons.append(f"Stoch K={curr_k:.1f} oversold")
                    # Overbought - bearish
                    elif curr_k > self.overbought:
                        action = "SELL"
                        confidence = min((curr_k - self.overbought) / (100 - self.overbought), 1.0)
                        reasons.append(f"Stoch K={curr_k:.1f} overbought")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "Stochastic in neutral zone",
        )

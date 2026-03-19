"""Simple moving average crossover strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class MAcrossoverStrategy(BaseStrategy):
    """Moving average crossover using fast (20) and slow (50) MAs."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.ma_fast: int = config.get("ma_fast", 20)
        self.ma_slow: int = config.get("ma_slow", 50)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if ohlcv is not None and len(ohlcv) >= self.ma_slow:
            close = ohlcv["close"].astype(float)
            ma_fast = ta.trend.SMAIndicator(close=close, window=self.ma_fast).sma_indicator()
            ma_slow = ta.trend.SMAIndicator(close=close, window=self.ma_slow).sma_indicator()

            if len(ma_fast) >= 2 and len(ma_slow) >= 2:
                curr_fast = ma_fast.iloc[-1]
                prev_fast = ma_fast.iloc[-2]
                curr_slow = ma_slow.iloc[-1]
                prev_slow = ma_slow.iloc[-2]

                if not any(pd.isna(v) for v in [curr_fast, prev_fast, curr_slow, prev_slow]):
                    # Golden cross: fast MA crosses above slow MA
                    if prev_fast <= prev_slow and curr_fast > curr_slow:
                        action = "BUY"
                        confidence = 0.8
                        reasons.append(f"MA({self.ma_fast}) crossed above MA({self.ma_slow})")
                    # Death cross: fast MA crosses below slow MA
                    elif prev_fast >= prev_slow and curr_fast < curr_slow:
                        action = "SELL"
                        confidence = 0.8
                        reasons.append(f"MA({self.ma_fast}) crossed below MA({self.ma_slow})")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No MA crossover",
        )

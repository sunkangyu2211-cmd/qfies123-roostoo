"""ADX trend strength with moving average strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class ADXTrendStrategy(BaseStrategy):
    """Uses ADX to confirm trend strength + MA direction."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.adx_period: int = config.get("adx_period", 14)
        self.adx_threshold: float = config.get("adx_threshold", 25.0)
        self.ma_period: int = config.get("ma_period", 20)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        # ADX needs more data to calculate properly (at least 2x the period)
        if ohlcv is not None and len(ohlcv) >= max(self.adx_period * 2 + 5, self.ma_period):
            try:
                high = ohlcv["high"].astype(float)
                low = ohlcv["low"].astype(float)
                close = ohlcv["close"].astype(float)

                # Calculate ADX
                adx = ta.trend.ADXIndicator(high=high, low=low, close=close, window=self.adx_period)
                adx_values = adx.adx()
                di_plus = adx.adx_pos()
                di_minus = adx.adx_neg()

                # Calculate moving average
                ma = ta.trend.SMAIndicator(close=close, window=self.ma_period).sma_indicator()

                if len(adx_values) > 0 and len(ma) > 0:
                    curr_adx = adx_values.iloc[-1]
                    curr_plus = di_plus.iloc[-1]
                    curr_minus = di_minus.iloc[-1]
                    curr_price = close.iloc[-1]
                    curr_ma = ma.iloc[-1]

                    if not any(pd.isna(v) for v in [curr_adx, curr_plus, curr_minus, curr_price, curr_ma]):
                        # Strong uptrend: ADX > threshold, +DI > -DI, price > MA
                        if curr_adx > self.adx_threshold and curr_plus > curr_minus and curr_price > curr_ma:
                            action = "BUY"
                            confidence = min(curr_adx / 50.0, 1.0)
                            reasons.append(f"Strong uptrend: ADX={curr_adx:.1f}")
                        # Strong downtrend: ADX > threshold, -DI > +DI, price < MA
                        elif curr_adx > self.adx_threshold and curr_minus > curr_plus and curr_price < curr_ma:
                            action = "SELL"
                            confidence = min(curr_adx / 50.0, 1.0)
                            reasons.append(f"Strong downtrend: ADX={curr_adx:.1f}")
            except (IndexError, ValueError):
                # ADX calculation can fail with insufficient data
                pass

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No strong trend",
        )

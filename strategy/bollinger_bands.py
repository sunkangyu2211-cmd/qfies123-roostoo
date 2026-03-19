"""Bollinger Bands mean reversion strategy."""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class BollingerBandsStrategy(BaseStrategy):
    """Mean reversion strategy using Bollinger Bands."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.bb_period: int = config.get("bb_period", 20)
        self.bb_std: float = config.get("bb_std", 2.0)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if ohlcv is not None and len(ohlcv) >= self.bb_period:
            close = ohlcv["close"].astype(float)
            bb = ta.volatility.BollingerBands(close=close, window=self.bb_period, window_dev=self.bb_std)
            bb_high = bb.bollinger_hband()
            bb_low = bb.bollinger_lband()
            bb_mid = bb.bollinger_mavg()

            if len(bb_high) > 0 and len(bb_low) > 0 and len(bb_mid) > 0:
                curr_price = close.iloc[-1]
                curr_high = bb_high.iloc[-1]
                curr_low = bb_low.iloc[-1]
                curr_mid = bb_mid.iloc[-1]

                if not any(pd.isna(v) for v in [curr_price, curr_high, curr_low, curr_mid]):
                    # Price touches lower band - oversold
                    if curr_price <= curr_low:
                        action = "BUY"
                        confidence = 0.7
                        reasons.append(f"Price touched lower BB ({curr_price:.2f} <= {curr_low:.2f})")
                    # Price touches upper band - overbought
                    elif curr_price >= curr_high:
                        action = "SELL"
                        confidence = 0.7
                        reasons.append(f"Price touched upper BB ({curr_price:.2f} >= {curr_high:.2f})")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "Price in BB middle zone",
        )

"""Dip buyer strategy — aggressively buys sharp dips in uptrending coins.

Uses a combination of:
- Bollinger Band %B to detect when price dips below the lower band
- Longer-term EMA trend filter (only buy dips in uptrends)
- RSI for oversold confirmation
- Quick exit when price returns to mean (middle Bollinger Band)

Designed for volatile coins that trend up but have sharp pullbacks.
"""

from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal


class DipBuyerStrategy(BaseStrategy):
    """Buy sharp dips in uptrending volatile coins."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.bb_period: int = config.get("dip_bb_period", 20)
        self.bb_std: float = config.get("dip_bb_std", 2.0)
        self.trend_ema: int = config.get("dip_trend_ema", 50)
        self.rsi_period: int = config.get("dip_rsi_period", 14)
        self.rsi_threshold: float = config.get("dip_rsi_threshold", 35)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        min_periods = max(self.bb_period, self.trend_ema) + 5
        if ohlcv is None or len(ohlcv) < min_periods:
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Insufficient data")

        close = ohlcv["close"].astype(float)

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=close, window=self.bb_period, window_dev=self.bb_std
        )
        bb_upper = bb.bollinger_hband()
        bb_middle = bb.bollinger_mavg()
        bb_lower = bb.bollinger_lband()
        pct_b = bb.bollinger_pband()  # %B: 0 = at lower band, 1 = at upper

        # Trend filter: long EMA
        trend_ema = close.ewm(span=self.trend_ema, adjust=False).mean()

        # RSI
        rsi = ta.momentum.RSIIndicator(close=close, window=self.rsi_period).rsi()

        current_close = close.iloc[-1]
        current_pct_b = pct_b.iloc[-1]
        current_ema = trend_ema.iloc[-1]
        current_rsi = rsi.iloc[-1]
        current_middle = bb_middle.iloc[-1]
        current_upper = bb_upper.iloc[-1]

        if pd.isna(current_pct_b) or pd.isna(current_ema) or pd.isna(current_rsi):
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Indicators not ready")

        in_uptrend = current_close > current_ema * 0.98  # Allow slight dip below EMA
        reasons = []
        action = "HOLD"
        confidence = 0.0

        # BUY: Price dipped below/near lower Bollinger Band in an uptrend
        if current_pct_b < 0.1 and in_uptrend:
            dip_depth = max(0, -current_pct_b)  # How far below lower band
            confidence = 0.5 + min(dip_depth * 2, 0.3)

            if current_rsi < self.rsi_threshold:
                confidence = min(confidence + 0.2, 1.0)
                reasons.append(f"RSI({current_rsi:.0f}) oversold")

            action = "BUY"
            reasons.append(f"Dip to BB lower (%B={current_pct_b:.2f}) in uptrend")

        # Even more aggressive: extreme dip (below band) regardless of trend
        elif current_pct_b < -0.1 and current_rsi < 25:
            action = "BUY"
            confidence = 0.8
            reasons.append(f"Extreme dip: %B={current_pct_b:.2f}, RSI={current_rsi:.0f}")

        # SELL: Price reached upper Bollinger Band — take profit
        elif current_pct_b > 0.95:
            action = "SELL"
            confidence = min(current_pct_b - 0.5, 1.0)
            reasons.append(f"Price at BB upper (%B={current_pct_b:.2f}) — take profit")

        # SELL: Price returned to middle band from a dip buy (mean reversion complete)
        elif current_pct_b > 0.6 and current_rsi > 60:
            action = "SELL"
            confidence = 0.5
            reasons.append(f"Mean reversion complete (%B={current_pct_b:.2f}, RSI={current_rsi:.0f})")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No dip detected",
        )

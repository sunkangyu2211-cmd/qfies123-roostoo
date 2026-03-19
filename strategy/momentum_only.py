"""Simple momentum-based trading strategy."""

from typing import Any, Optional

import pandas as pd

from .base import BaseStrategy, Signal


class SimpleMomentumStrategy(BaseStrategy):
    """Pure 24-hour momentum strategy with optional volume confirmation."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.momentum_threshold: float = config.get("momentum_threshold_pct", 1.5)
        self.volume_confirm: bool = config.get("volume_confirm", False)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        change_24h: float = market_data.get("change_24h", 0.0)
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        reasons = []
        action = "HOLD"
        confidence = 0.0

        if change_24h > self.momentum_threshold:
            action = "BUY"
            confidence = min(abs(change_24h) / 5.0, 1.0)
            reasons.append(f"24h momentum +{change_24h:.1f}% bullish")
        elif change_24h < -self.momentum_threshold:
            action = "SELL"
            confidence = min(abs(change_24h) / 5.0, 1.0)
            reasons.append(f"24h momentum {change_24h:.1f}% bearish")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No momentum threshold hit",
        )

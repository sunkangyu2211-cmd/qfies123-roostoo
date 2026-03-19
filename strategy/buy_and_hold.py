"""Buy-and-hold strategy — the simplest fallback.

Buys once at the start and holds indefinitely. Used as a baseline
and as the fallback when no active strategy outperforms it.
"""

from typing import Any, Optional

import pandas as pd

from .base import BaseStrategy, Signal


class BuyAndHoldStrategy(BaseStrategy):
    """Buy on first signal, then hold forever.

    Tracks whether a position exists via market_data context.
    Never generates SELL signals.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._bought: set[str] = set()

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")

        # If we haven't bought yet, buy with full confidence
        if pair not in self._bought:
            self._bought.add(pair)
            return Signal(
                pair=pair,
                action="BUY",
                confidence=1.0,
                reason="Buy and hold: initial purchase",
            )

        # Already holding — do nothing
        return Signal(
            pair=pair,
            action="HOLD",
            confidence=0.0,
            reason="Buy and hold: holding position",
        )

    def reset(self) -> None:
        """Reset bought state (used between backtest runs)."""
        self._bought.clear()

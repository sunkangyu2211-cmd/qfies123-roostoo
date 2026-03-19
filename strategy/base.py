"""Abstract base strategy and Signal dataclass.

Defines the interface all trading strategies must implement,
and the Signal dataclass that represents a trading recommendation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Signal:
    """A trading signal produced by a strategy.

    Attributes:
        pair: Trading pair (e.g. "BTC/USD").
        action: Recommended action.
        confidence: Signal strength from 0.0 to 1.0.
        reason: Human-readable explanation of which indicators fired.
    """

    pair: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    reason: str


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Subclasses must implement generate_signal() to produce
    trading recommendations from market data.
    """

    @abstractmethod
    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate a trading signal from current market data.

        Args:
            market_data: Dict containing OHLCV, prices, indicators, etc.

        Returns:
            A Signal with the recommended action.
        """

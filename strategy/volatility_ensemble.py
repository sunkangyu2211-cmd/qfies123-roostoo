"""Volatility ensemble — combines breakout, dip-buying, and trend signals.

This is the main competition strategy. It runs three sub-strategies
and takes the strongest signal. Designed for high-volatility coins.

Logic:
- If a strong breakout is detected, take it (momentum play)
- If a dip is detected in an uptrend, buy the dip (mean reversion)
- If a strong trend is confirmed, ride it (trend following)
- Among competing signals, take the one with highest confidence
"""

from typing import Any

from .base import BaseStrategy, Signal
from .breakout import BreakoutStrategy
from .aggressive_rsi import AggressiveRSIStrategy
from .trend_rider import TrendRiderStrategy
from .dip_buyer import DipBuyerStrategy


class VolatilityEnsemble(BaseStrategy):
    """Ensemble of aggressive strategies for volatile coins."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.breakout = BreakoutStrategy(config)
        self.aggressive_rsi = AggressiveRSIStrategy(config)
        self.trend_rider = TrendRiderStrategy(config)
        self.dip_buyer = DipBuyerStrategy(config)

        self._sub_strategies = [
            ("breakout", self.breakout),
            ("aggressive_rsi", self.aggressive_rsi),
            ("trend_rider", self.trend_rider),
            ("dip_buyer", self.dip_buyer),
        ]

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair: str = market_data["pair"]

        signals: list[tuple[str, Signal]] = []
        for name, strat in self._sub_strategies:
            sig = strat.generate_signal(market_data)
            if sig.action != "HOLD":
                signals.append((name, sig))

        if not signals:
            return Signal(pair=pair, action="HOLD", confidence=0.0, reason="No sub-strategy triggered")

        # Separate buys and sells
        buys = [(n, s) for n, s in signals if s.action == "BUY"]
        sells = [(n, s) for n, s in signals if s.action == "SELL"]

        # If we have sells, check if majority says sell
        if len(sells) >= 2:
            best_name, best_sig = max(sells, key=lambda x: x[1].confidence)
            return Signal(
                pair=pair,
                action="SELL",
                confidence=best_sig.confidence,
                reason=f"[ensemble:{best_name}+{len(sells)-1}] {best_sig.reason}",
            )

        # For buys: take the highest confidence signal
        if buys:
            best_name, best_sig = max(buys, key=lambda x: x[1].confidence)
            # Boost confidence if multiple strategies agree
            agreement_bonus = min(0.1 * (len(buys) - 1), 0.2)
            final_confidence = min(best_sig.confidence + agreement_bonus, 1.0)
            return Signal(
                pair=pair,
                action="BUY",
                confidence=final_confidence,
                reason=f"[ensemble:{best_name}+{len(buys)-1}] {best_sig.reason}",
            )

        # Single sell
        if sells:
            best_name, best_sig = sells[0]
            return Signal(
                pair=pair,
                action="SELL",
                confidence=best_sig.confidence,
                reason=f"[ensemble:{best_name}] {best_sig.reason}",
            )

        return Signal(pair=pair, action="HOLD", confidence=0.0, reason="Conflicting signals")

"""Multi-signal trading strategy combining RSI, EMA crossover, and momentum.

Uses the `ta` library for technical indicator calculations and applies
a Fear & Greed macro filter to modulate signal generation.
"""

import logging
from typing import Any, Optional

import pandas as pd
import ta

from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class MultiSignalStrategy(BaseStrategy):
    """Composite strategy scoring RSI, EMA crossover, and momentum.

    Each indicator contributes +1 or -1 to a composite score (-3 to +3).
    BUY if score >= min_signal_score, SELL if score <= -min_signal_score.
    Fear & Greed index acts as a macro filter.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize with strategy parameters from config.

        Args:
            config: Strategy config section from config.yaml.
        """
        self.rsi_period: int = config.get("rsi_period", 14)
        self.rsi_oversold: int = config.get("rsi_oversold", 35)
        self.rsi_overbought: int = config.get("rsi_overbought", 65)
        self.ema_fast: int = config.get("ema_fast", 12)
        self.ema_slow: int = config.get("ema_slow", 26)
        self.momentum_threshold: float = config.get("momentum_threshold_pct", 2.0)
        self.min_signal_score: int = config.get("min_signal_score", 2)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate a composite signal from multiple indicators.

        Args:
            market_data: Must contain keys:
                - "pair": str
                - "ohlcv": pd.DataFrame with close column
                - "change_24h": float (percent change)
                - "fear_greed": int (0-100)

        Returns:
            Signal with action, confidence, and detailed reason.
        """
        pair: str = market_data["pair"]
        ohlcv: Optional[pd.DataFrame] = market_data.get("ohlcv")
        change_24h: float = market_data.get("change_24h", 0.0)
        fear_greed: Optional[int] = market_data.get("fear_greed")

        score = 0
        reasons: list[str] = []

        if ohlcv is not None and len(ohlcv) >= self.rsi_period:
            rsi_score, rsi_reason = self._score_rsi(ohlcv)
            score += rsi_score
            if rsi_reason:
                reasons.append(rsi_reason)

            ema_score, ema_reason = self._score_ema_crossover(ohlcv)
            score += ema_score
            if ema_reason:
                reasons.append(ema_reason)

        momentum_score, momentum_reason = self._score_momentum(change_24h)
        score += momentum_score
        if momentum_reason:
            reasons.append(momentum_reason)

        score = self._apply_fear_greed_filter(score, fear_greed, reasons)

        action, confidence = self._resolve_action(score)
        reason_str = "; ".join(reasons) if reasons else "No signals fired"

        logger.info(
            "%s: score=%d action=%s confidence=%.2f (%s)",
            pair,
            score,
            action,
            confidence,
            reason_str,
        )
        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason=reason_str,
        )

    def _score_rsi(self, ohlcv: pd.DataFrame) -> tuple[int, str]:
        """Score based on RSI indicator.

        Args:
            ohlcv: DataFrame with close prices.

        Returns:
            Tuple of (score adjustment, reason string).
        """
        close = ohlcv["close"].astype(float)
        rsi_series = ta.momentum.RSIIndicator(close=close, window=self.rsi_period).rsi()
        current_rsi = rsi_series.iloc[-1]

        if pd.isna(current_rsi):
            return 0, ""
        if current_rsi < self.rsi_oversold:
            return 1, f"RSI({current_rsi:.1f})<{self.rsi_oversold} oversold"
        if current_rsi > self.rsi_overbought:
            return -1, f"RSI({current_rsi:.1f})>{self.rsi_overbought} overbought"
        return 0, ""

    def _score_ema_crossover(self, ohlcv: pd.DataFrame) -> tuple[int, str]:
        """Score based on EMA crossover.

        Args:
            ohlcv: DataFrame with close prices.

        Returns:
            Tuple of (score adjustment, reason string).
        """
        close = ohlcv["close"].astype(float)
        ema_fast = ta.trend.EMAIndicator(
            close=close, window=self.ema_fast
        ).ema_indicator()
        ema_slow = ta.trend.EMAIndicator(
            close=close, window=self.ema_slow
        ).ema_indicator()

        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return 0, ""

        curr_fast = ema_fast.iloc[-1]
        prev_fast = ema_fast.iloc[-2]
        curr_slow = ema_slow.iloc[-1]
        prev_slow = ema_slow.iloc[-2]

        if any(pd.isna(v) for v in [curr_fast, prev_fast, curr_slow, prev_slow]):
            return 0, ""

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return 1, (
                f"EMA({self.ema_fast}) crossed above " f"EMA({self.ema_slow}) bullish"
            )
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return -1, (
                f"EMA({self.ema_fast}) crossed below " f"EMA({self.ema_slow}) bearish"
            )
        return 0, ""

    def _score_momentum(self, change_24h: float) -> tuple[int, str]:
        """Score based on 24h price momentum.

        Args:
            change_24h: 24-hour percent price change.

        Returns:
            Tuple of (score adjustment, reason string).
        """
        if change_24h > self.momentum_threshold:
            return 1, f"24h momentum +{change_24h:.1f}% bullish"
        if change_24h < -self.momentum_threshold:
            return -1, f"24h momentum {change_24h:.1f}% bearish"
        return 0, ""

    def _apply_fear_greed_filter(
        self,
        score: int,
        fear_greed: Optional[int],
        reasons: list[str],
    ) -> int:
        """Apply Fear & Greed macro filter to the composite score.

        In extreme greed (>75), suppress BUY signals.
        In extreme fear (<25), allow BUY signals through.

        Args:
            score: Current composite score.
            fear_greed: Fear & Greed index (0-100), or None.
            reasons: Mutable list of reason strings.

        Returns:
            Adjusted score.
        """
        if fear_greed is None:
            return score

        if fear_greed > 75 and score > 0:
            reasons.append(f"F&G={fear_greed} extreme greed, suppressing BUY")
            return 0
        if fear_greed < 25:
            reasons.append(f"F&G={fear_greed} extreme fear, BUY allowed")
        return score

    def _resolve_action(self, score: int) -> tuple[str, float]:
        """Convert composite score to action and confidence.

        Args:
            score: Composite score from -3 to +3.

        Returns:
            Tuple of (action string, confidence float).
        """
        confidence = abs(score) / 3.0
        if score >= self.min_signal_score:
            return "BUY", confidence
        if score <= -self.min_signal_score:
            return "SELL", confidence
        return "HOLD", confidence

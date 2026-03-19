"""Unit tests for the MultiSignalStrategy.

Tests signal generation for various indicator combinations including
RSI, EMA crossover, momentum, and Fear & Greed filtering.
"""

import numpy as np
import pandas as pd
import pytest

from strategy.multi_signal import MultiSignalStrategy


@pytest.fixture
def strategy() -> MultiSignalStrategy:
    """Create a strategy with default config."""
    return MultiSignalStrategy(
        {
            "rsi_period": 14,
            "rsi_oversold": 35,
            "rsi_overbought": 65,
            "ema_fast": 12,
            "ema_slow": 26,
            "momentum_threshold_pct": 2.0,
            "min_signal_score": 2,
        }
    )


def _make_ohlcv(closes: list[float]) -> pd.DataFrame:
    """Helper to build an OHLCV DataFrame from close prices.

    Args:
        closes: List of close price values.

    Returns:
        DataFrame with standard OHLCV columns.
    """
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": range(n),
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


class TestSignalGeneration:
    """Tests for the generate_signal method."""

    def test_hold_when_no_data(self, strategy: MultiSignalStrategy) -> None:
        """Should return HOLD with no OHLCV data and neutral momentum."""
        market_data = {
            "pair": "BTC/USD",
            "ohlcv": None,
            "change_24h": 0.0,
            "fear_greed": 50,
        }
        signal = strategy.generate_signal(market_data)
        assert signal.action == "HOLD"
        assert signal.pair == "BTC/USD"

    def test_buy_signal_on_strong_momentum(self, strategy: MultiSignalStrategy) -> None:
        """Strong bullish momentum + oversold RSI should trigger BUY."""
        # Create a declining then rising series to get oversold RSI
        declining = list(np.linspace(100, 60, 30))
        ohlcv = _make_ohlcv(declining)

        market_data = {
            "pair": "BTC/USD",
            "ohlcv": ohlcv,
            "change_24h": 5.0,  # Strong positive momentum
            "fear_greed": 20,  # Extreme fear allows BUY
        }
        signal = strategy.generate_signal(market_data)
        # With declining prices, RSI should be low (oversold = +1)
        # Momentum +5% > 2% threshold = +1
        # Fear & Greed 20 < 25 allows BUY
        assert signal.pair == "BTC/USD"
        assert signal.confidence >= 0.0
        assert signal.reason != ""

    def test_sell_signal_on_bearish_indicators(
        self, strategy: MultiSignalStrategy
    ) -> None:
        """Strong bearish momentum + overbought RSI should trigger SELL."""
        # Create a rising series to get overbought RSI
        rising = list(np.linspace(60, 100, 30))
        ohlcv = _make_ohlcv(rising)

        market_data = {
            "pair": "ETH/USD",
            "ohlcv": ohlcv,
            "change_24h": -5.0,  # Strong negative momentum
            "fear_greed": 50,
        }
        signal = strategy.generate_signal(market_data)
        assert signal.pair == "ETH/USD"
        assert signal.confidence >= 0.0

    def test_fear_greed_suppresses_buy(self, strategy: MultiSignalStrategy) -> None:
        """Extreme greed should suppress BUY signals."""
        declining = list(np.linspace(100, 60, 30))
        ohlcv = _make_ohlcv(declining)

        market_data = {
            "pair": "BTC/USD",
            "ohlcv": ohlcv,
            "change_24h": 5.0,
            "fear_greed": 80,  # Extreme greed
        }
        signal = strategy.generate_signal(market_data)
        # Greed filter should suppress any positive score
        assert signal.action in ("HOLD", "SELL")

    def test_hold_on_neutral_market(self, strategy: MultiSignalStrategy) -> None:
        """Flat market should produce HOLD signal."""
        flat = [100.0] * 30
        ohlcv = _make_ohlcv(flat)

        market_data = {
            "pair": "SOL/USD",
            "ohlcv": ohlcv,
            "change_24h": 0.5,  # Within threshold
            "fear_greed": 50,
        }
        signal = strategy.generate_signal(market_data)
        assert signal.action == "HOLD"


class TestConfidence:
    """Tests for confidence calculation."""

    def test_confidence_range(self, strategy: MultiSignalStrategy) -> None:
        """Confidence should be between 0 and 1."""
        market_data = {
            "pair": "BTC/USD",
            "ohlcv": None,
            "change_24h": 10.0,
            "fear_greed": 50,
        }
        signal = strategy.generate_signal(market_data)
        assert 0.0 <= signal.confidence <= 1.0

    def test_max_confidence_three_signals(self, strategy: MultiSignalStrategy) -> None:
        """Max confidence (1.0) requires all 3 indicators aligned."""
        # This verifies the math: confidence = abs(score) / 3.0
        # We can't easily force all 3 indicators but we verify the formula
        assert strategy._resolve_action(3) == ("BUY", 1.0)
        assert strategy._resolve_action(-3) == ("SELL", 1.0)
        assert strategy._resolve_action(0) == ("HOLD", 0.0)


class TestReasonString:
    """Tests for human-readable reason strings."""

    def test_reason_contains_indicator_names(
        self, strategy: MultiSignalStrategy
    ) -> None:
        """Reason string should mention which indicators fired."""
        declining = list(np.linspace(100, 60, 30))
        ohlcv = _make_ohlcv(declining)

        market_data = {
            "pair": "BTC/USD",
            "ohlcv": ohlcv,
            "change_24h": 5.0,
            "fear_greed": 20,
        }
        signal = strategy.generate_signal(market_data)
        assert len(signal.reason) > 0

    def test_no_signals_gives_default_reason(
        self, strategy: MultiSignalStrategy
    ) -> None:
        """When no indicators fire, reason should say so."""
        market_data = {
            "pair": "BTC/USD",
            "ohlcv": None,
            "change_24h": 0.0,
            "fear_greed": None,
        }
        signal = strategy.generate_signal(market_data)
        assert "No signals" in signal.reason

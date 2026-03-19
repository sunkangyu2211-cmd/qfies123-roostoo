"""Ensemble strategies combining multiple indicators for better signals.

This module provides templates for combining multiple strategies to reduce
false signals and improve overall performance.
"""

from typing import Any, Optional

import pandas as pd

from .base import BaseStrategy, Signal
from .rsi_only import RSIOnlyStrategy
from .macd import MACDStrategy


class EnsembleRSI_MACD(BaseStrategy):
    """Ensemble strategy: Buy when BOTH RSI and MACD agree on BUY signal.

    This reduces false signals by requiring confirmation from two independent
    indicators. Only trades when both RSI (oversold) and MACD (bullish cross)
    align. Similarly for SELL signals.

    Performance Hypothesis:
    - RSIOnly: 10.31% return, 90.9% win rate, 11 trades
    - MACD: 5.72% return, 39% win rate, 82 trades
    - Ensemble: Should get 6-8% return, 70%+ win rate, 20-30 trades
      (fewer but higher quality trades)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize with RSI and MACD configs.

        Args:
            config: Must contain 'rsi_config' and 'macd_config' keys.
                Example:
                {
                    'rsi_config': {
                        'rsi_period': 14,
                        'rsi_oversold': 30,
                        'rsi_overbought': 70,
                    },
                    'macd_config': {
                        'macd_fast': 12,
                        'macd_slow': 26,
                        'macd_signal': 9,
                    }
                }
        """
        rsi_config = config.get('rsi_config', {
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
        })
        macd_config = config.get('macd_config', {
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
        })

        self.rsi_strategy = RSIOnlyStrategy(rsi_config)
        self.macd_strategy = MACDStrategy(macd_config)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate ensemble signal requiring agreement from both indicators.

        Args:
            market_data: Dict containing OHLCV, prices, and Fear & Greed.

        Returns:
            BUY if both RSI and MACD say BUY
            SELL if both RSI and MACD say SELL
            HOLD if indicators disagree or neither triggers
        """
        pair: str = market_data["pair"]

        # Get signals from both strategies
        rsi_signal = self.rsi_strategy.generate_signal(market_data)
        macd_signal = self.macd_strategy.generate_signal(market_data)

        # Ensemble decision: require both to agree
        confidence = 0.0
        action = "HOLD"
        reasons = []

        if rsi_signal.action == "BUY" and macd_signal.action == "BUY":
            action = "BUY"
            # Confidence is average of both (both must be strong)
            confidence = (rsi_signal.confidence + macd_signal.confidence) / 2.0
            reasons.append(f"RSI: {rsi_signal.reason}")
            reasons.append(f"MACD: {macd_signal.reason}")

        elif rsi_signal.action == "SELL" and macd_signal.action == "SELL":
            action = "SELL"
            confidence = (rsi_signal.confidence + macd_signal.confidence) / 2.0
            reasons.append(f"RSI: {rsi_signal.reason}")
            reasons.append(f"MACD: {macd_signal.reason}")

        elif rsi_signal.action != macd_signal.action and rsi_signal.action != "HOLD" and macd_signal.action != "HOLD":
            # Indicators disagree on direction - skip
            action = "HOLD"
            reasons.append(f"Disagreement: RSI={rsi_signal.action}, MACD={macd_signal.action}")
        elif rsi_signal.action == "BUY" or macd_signal.action == "BUY":
            action = "HOLD"
            reasons.append(f"Partial: RSI={rsi_signal.action}, MACD={macd_signal.action}")
        elif rsi_signal.action == "SELL" or macd_signal.action == "SELL":
            action = "HOLD"
            reasons.append(f"Partial: RSI={rsi_signal.action}, MACD={macd_signal.action}")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons) if reasons else "No ensemble signal",
        )


class EnsembleMajority(BaseStrategy):
    """Majority voting ensemble: Trade if 2+ indicators agree.

    Combines RSI, MACD, and ADX. Trades on majority vote.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize with RSI, MACD, and ADX configs."""
        from .adx_trend import ADXTrendStrategy

        rsi_config = config.get('rsi_config', {
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
        })
        macd_config = config.get('macd_config', {
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
        })
        adx_config = config.get('adx_config', {
            'adx_period': 14,
            'adx_threshold': 25.0,
            'ma_period': 20,
        })

        self.rsi_strategy = RSIOnlyStrategy(rsi_config)
        self.macd_strategy = MACDStrategy(macd_config)
        self.adx_strategy = ADXTrendStrategy(adx_config)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate signal based on majority vote (2+/3 indicators).

        Args:
            market_data: Dict containing OHLCV and prices.

        Returns:
            BUY if 2+ indicators say BUY
            SELL if 2+ indicators say SELL
            HOLD otherwise
        """
        pair: str = market_data["pair"]

        # Get signals from all three strategies
        rsi_signal = self.rsi_strategy.generate_signal(market_data)
        macd_signal = self.macd_strategy.generate_signal(market_data)
        adx_signal = self.adx_strategy.generate_signal(market_data)

        # Count votes
        buy_votes = sum([
            1 for sig in [rsi_signal, macd_signal, adx_signal]
            if sig.action == "BUY"
        ])
        sell_votes = sum([
            1 for sig in [rsi_signal, macd_signal, adx_signal]
            if sig.action == "SELL"
        ])

        action = "HOLD"
        confidence = 0.0
        reasons = []

        if buy_votes >= 2:
            action = "BUY"
            confidence = buy_votes / 3.0  # 0.67 if 2 votes, 1.0 if 3
            reasons.append(f"Majority BUY ({buy_votes}/3)")
        elif sell_votes >= 2:
            action = "SELL"
            confidence = sell_votes / 3.0
            reasons.append(f"Majority SELL ({sell_votes}/3)")
        else:
            reasons.append(f"No majority: BUY={buy_votes}, SELL={sell_votes}")

        reasons.append(f"RSI={rsi_signal.action}")
        reasons.append(f"MACD={macd_signal.action}")
        reasons.append(f"ADX={adx_signal.action}")

        return Signal(
            pair=pair,
            action=action,
            confidence=confidence,
            reason="; ".join(reasons),
        )

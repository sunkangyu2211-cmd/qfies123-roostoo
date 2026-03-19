from .base import BaseStrategy, Signal
from .multi_signal import MultiSignalStrategy
from .momentum_only import SimpleMomentumStrategy
from .rsi_only import RSIOnlyStrategy
from .ma_crossover import MAcrossoverStrategy
from .bollinger_bands import BollingerBandsStrategy
from .macd import MACDStrategy
from .adx_trend import ADXTrendStrategy
from .stochastic import StochasticStrategy
from .ensemble import EnsembleRSI_MACD, EnsembleMajority
from .buy_and_hold import BuyAndHoldStrategy
from .breakout import BreakoutStrategy
from .aggressive_rsi import AggressiveRSIStrategy
from .trend_rider import TrendRiderStrategy
from .dip_buyer import DipBuyerStrategy
from .volatility_ensemble import VolatilityEnsemble

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "multi_signal": MultiSignalStrategy,
    "rsi_only": RSIOnlyStrategy,
    "macd": MACDStrategy,
    "adx_trend": ADXTrendStrategy,
    "ma_crossover": MAcrossoverStrategy,
    "momentum_only": SimpleMomentumStrategy,
    "bollinger_bands": BollingerBandsStrategy,
    "stochastic": StochasticStrategy,
    "ensemble_rsi_macd": EnsembleRSI_MACD,
    "ensemble_majority": EnsembleMajority,
    "buy_and_hold": BuyAndHoldStrategy,
    "breakout": BreakoutStrategy,
    "aggressive_rsi": AggressiveRSIStrategy,
    "trend_rider": TrendRiderStrategy,
    "dip_buyer": DipBuyerStrategy,
    "volatility_ensemble": VolatilityEnsemble,
}

__all__ = [
    "BaseStrategy",
    "Signal",
    "MultiSignalStrategy",
    "SimpleMomentumStrategy",
    "RSIOnlyStrategy",
    "MAcrossoverStrategy",
    "BollingerBandsStrategy",
    "MACDStrategy",
    "ADXTrendStrategy",
    "StochasticStrategy",
    "EnsembleRSI_MACD",
    "EnsembleMajority",
    "BuyAndHoldStrategy",
    "BreakoutStrategy",
    "AggressiveRSIStrategy",
    "TrendRiderStrategy",
    "DipBuyerStrategy",
    "VolatilityEnsemble",
    "STRATEGY_REGISTRY",
]

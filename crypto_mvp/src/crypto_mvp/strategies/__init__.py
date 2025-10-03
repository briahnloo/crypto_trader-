"""
Trading strategies module for the Crypto MVP application.
"""

from .arbitrage import ArbitrageStrategy
from .base import (
    BaseStrategy,
    OrderType,
    SignalType,
    Strategy,
    StrategyConfig,
    TradingSignal,
)
from .breakout import BreakoutStrategy
from .composite import ProfitMaximizingSignalEngine
from .correlation import CorrelationStrategy
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy
from .news_driven import NewsDrivenStrategy
from .on_chain import OnChainStrategy
from .sentiment import SentimentStrategy
from .volatility import VolatilityStrategy
from .whale_tracking import WhaleTrackingStrategy

__all__ = [
    # Base classes
    "Strategy",
    "BaseStrategy",
    "StrategyConfig",
    "TradingSignal",
    "SignalType",
    "OrderType",
    # Individual strategies
    "MomentumStrategy",
    "BreakoutStrategy",
    "MeanReversionStrategy",
    "ArbitrageStrategy",
    "SentimentStrategy",
    "VolatilityStrategy",
    "CorrelationStrategy",
    "WhaleTrackingStrategy",
    "NewsDrivenStrategy",
    "OnChainStrategy",
    # Composite engine
    "ProfitMaximizingSignalEngine",
]

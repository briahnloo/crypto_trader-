"""
Base strategy class for all trading strategies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from ..core.logging_utils import LoggerMixin


class SignalType(Enum):
    """Trading signal types."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderType(Enum):
    """Order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class TradingSignal:
    """Trading signal data structure."""

    symbol: str
    signal_type: SignalType
    confidence: float
    price: float
    timestamp: datetime
    strategy_name: str
    metadata: dict[str, Any]
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: Optional[float] = None


@dataclass
class StrategyConfig:
    """Strategy configuration data structure."""

    name: str
    enabled: bool
    weight: float
    parameters: dict[str, Any]
    risk_limits: dict[str, float]


class Strategy(ABC, LoggerMixin):
    """Abstract base class for all trading strategies."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        """Initialize the strategy.

        Args:
            config: Strategy configuration (optional for minimal implementations)
        """
        # Initialize LoggerMixin first to set up self.logger
        super().__init__()
        
        if config:
            self.config = config
            self.name = config.name
            self.enabled = config.enabled
            self.weight = config.weight
            self.parameters = config.parameters
            self.risk_limits = config.risk_limits
        else:
            # Default configuration for minimal implementations
            self.config = None
            self.name = self.__class__.__name__.lower().replace("strategy", "")
            self.enabled = True
            self.weight = 1.0
            self.parameters = {}
            self.risk_limits = {}

        # Strategy state
        self.positions: dict[str, float] = {}
        self.last_signals: dict[str, TradingSignal] = {}
        self.performance_metrics: dict[str, Any] = {}

        # Initialize performance tracking
        self._initialize_performance_tracking()

    def _initialize_performance_tracking(self) -> None:
        """Initialize performance tracking variables."""
        self.performance_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
        }

    @abstractmethod
    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze market data and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (e.g., '1h', '4h', '1d') - optional

        Returns:
            Dictionary containing analysis results with keys:
            - score: Strategy score (-1 to 1, where 1 is strong buy, -1 is strong sell)
            - signal_strength: Signal strength (0 to 1)
            - entry_price: Suggested entry price (optional)
            - stop_loss: Suggested stop loss price (optional)
            - take_profit: Suggested take profit price (optional)
            - volatility: Market volatility measure (optional)
            - correlation: Correlation with other assets (optional)
            - confidence: Confidence in the signal (0 to 1)
            - metadata: Additional strategy-specific data
        """
        pass

    def get_required_data(self) -> list[str]:
        """Get list of required data types for this strategy.

        Returns:
            List of required data types
        """
        return ["ohlcv", "volume"]

    def validate_signal(self, signal: TradingSignal) -> bool:
        """Validate trading signal before execution.

        Args:
            signal: Trading signal to validate

        Returns:
            True if signal is valid, False otherwise
        """
        # Check if strategy is enabled
        if not self.enabled:
            return False

        # Check confidence threshold
        min_confidence = self.parameters.get("min_confidence", 0.5)
        if signal.confidence < min_confidence:
            return False

        # Check risk limits
        if signal.position_size and signal.position_size > self.risk_limits.get(
            "max_position_size", 1.0
        ):
            return False

        # Check stop loss and take profit
        if signal.stop_loss and signal.take_profit:
            if signal.signal_type == SignalType.BUY:
                if (
                    signal.stop_loss >= signal.price
                    or signal.take_profit <= signal.price
                ):
                    return False
            elif signal.signal_type == SignalType.SELL:
                if (
                    signal.stop_loss <= signal.price
                    or signal.take_profit >= signal.price
                ):
                    return False

        return True

    def update_position(self, symbol: str, size: float) -> None:
        """Update position size for a symbol.

        Args:
            symbol: Trading symbol
            size: Position size (positive for long, negative for short)
        """
        self.positions[symbol] = size
        self.logger.info(f"Updated position for {symbol}: {size}")

    def get_position(self, symbol: str) -> float:
        """Get current position size for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Current position size
        """
        return self.positions.get(symbol, 0.0)

    def update_performance(self, trade_result: dict[str, Any]) -> None:
        """Update strategy performance metrics.

        Args:
            trade_result: Trade result data
        """
        self.performance_metrics["total_trades"] += 1

        pnl = trade_result.get("pnl", 0.0)
        self.performance_metrics["total_pnl"] += pnl

        if pnl > 0:
            self.performance_metrics["winning_trades"] += 1
        else:
            self.performance_metrics["losing_trades"] += 1

        # Update win rate
        total_trades = self.performance_metrics["total_trades"]
        winning_trades = self.performance_metrics["winning_trades"]
        self.performance_metrics["win_rate"] = (
            winning_trades / total_trades if total_trades > 0 else 0.0
        )

        # Update max drawdown
        if pnl < 0:
            current_drawdown = abs(pnl)
            if current_drawdown > self.performance_metrics["max_drawdown"]:
                self.performance_metrics["max_drawdown"] = current_drawdown

        # Update average win/loss
        if pnl > 0:
            wins = self.performance_metrics["winning_trades"]
            current_avg = self.performance_metrics["average_win"]
            self.performance_metrics["average_win"] = (
                current_avg * (wins - 1) + pnl
            ) / wins
        else:
            losses = self.performance_metrics["losing_trades"]
            current_avg = self.performance_metrics["average_loss"]
            self.performance_metrics["average_loss"] = (
                current_avg * (losses - 1) + abs(pnl)
            ) / losses

        # Update profit factor
        avg_win = self.performance_metrics["average_win"]
        avg_loss = self.performance_metrics["average_loss"]
        if avg_loss > 0:
            self.performance_metrics["profit_factor"] = avg_win / avg_loss

    def get_performance_summary(self) -> dict[str, Any]:
        """Get strategy performance summary.

        Returns:
            Performance summary dictionary
        """
        return self.performance_metrics.copy()

    def reset_performance(self) -> None:
        """Reset performance metrics."""
        self._initialize_performance_tracking()
        self.positions.clear()
        self.last_signals.clear()

    def get_risk_metrics(self) -> dict[str, Any]:
        """Get current risk metrics.

        Returns:
            Risk metrics dictionary
        """
        total_exposure = sum(abs(size) for size in self.positions.values())

        return {
            "total_exposure": total_exposure,
            "position_count": len(self.positions),
            "max_position_size": (
                max(abs(size) for size in self.positions.values())
                if self.positions
                else 0.0
            ),
            "risk_limits": self.risk_limits.copy(),
        }

    def should_exit_position(self, symbol: str, current_price: float) -> bool:
        """Check if position should be exited based on risk management.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            True if position should be exited
        """
        position = self.get_position(symbol)
        if position == 0:
            return False

        # Check stop loss
        last_signal = self.last_signals.get(symbol)
        if last_signal and last_signal.stop_loss:
            if position > 0 and current_price <= last_signal.stop_loss:
                return True
            elif position < 0 and current_price >= last_signal.stop_loss:
                return True

        # Check take profit
        if last_signal and last_signal.take_profit:
            if position > 0 and current_price >= last_signal.take_profit:
                return True
            elif position < 0 and current_price <= last_signal.take_profit:
                return True

        return False

    def __str__(self) -> str:
        """String representation of the strategy."""
        return f"{self.name} Strategy (enabled={self.enabled}, weight={self.weight})"

    def __repr__(self) -> str:
        """Detailed string representation of the strategy."""
        return (
            f"{self.__class__.__name__}(name='{self.name}', enabled={self.enabled}, "
            f"weight={self.weight}, positions={len(self.positions)})"
        )


# Legacy BaseStrategy class for backward compatibility
class BaseStrategy(Strategy):
    """Legacy base strategy class for backward compatibility."""

    def __init__(self, config: StrategyConfig):
        """Initialize the legacy strategy."""
        super().__init__(config)

    @abstractmethod
    async def analyze_legacy(
        self, symbol: str, data: dict[str, Any], current_price: float
    ) -> Optional[TradingSignal]:
        """Legacy analyze method for backward compatibility."""
        pass

"""
Risk management system for cryptocurrency trading.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import numpy as np

from ..core.logging_utils import LoggerMixin


class RiskLevel(Enum):
    """Risk level enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    """Risk metrics data structure."""

    var_95: float
    var_99: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    beta: float
    correlation: float
    volatility: float
    risk_level: RiskLevel


class ProfitOptimizedRiskManager(LoggerMixin):
    """Profit-optimized risk manager with Kelly Criterion and volatility/correlation adjustments."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the profit-optimized risk manager.

        Args:
            config: Risk management configuration (optional)
        """
        super().__init__()
        self.config = config or {}

        # Risk limits from config
        self.max_risk_per_trade = self.config.get(
            "max_risk_per_trade", 0.02
        )  # 2% max risk per trade
        self.max_portfolio_risk = self.config.get(
            "max_portfolio_risk", 0.10
        )  # 10% max portfolio risk
        self.max_position_size = self.config.get(
            "max_position_size", 0.20
        )  # 20% max position size
        self.kelly_fraction_limit = self.config.get(
            "kelly_fraction_limit", 0.25
        )  # 25% max Kelly fraction
        self.min_kelly_fraction = self.config.get(
            "min_kelly_fraction", 0.01
        )  # 1% min Kelly fraction

        # Volatility and correlation adjustments
        self.volatility_adjustment_factor = self.config.get(
            "volatility_adjustment_factor", 1.0
        )
        self.correlation_penalty_factor = self.config.get(
            "correlation_penalty_factor", 0.5
        )
        self.max_correlation = self.config.get("max_correlation", 0.7)

        # Kelly Criterion parameters
        self.kelly_safety_factor = self.config.get(
            "kelly_safety_factor", 0.5
        )  # Fractional Kelly
        self.min_win_rate = self.config.get(
            "min_win_rate", 0.45
        )  # Minimum win rate for Kelly
        self.min_profit_factor = self.config.get(
            "min_profit_factor", 1.1
        )  # Minimum profit factor

        # Portfolio tracking
        self.positions: dict[str, dict[str, Any]] = {}
        self.portfolio_value = self.config.get("initial_portfolio_value", 100000.0)
        self.risk_metrics: dict[str, RiskMetrics] = {}

        self.initialized = False

    def initialize(self) -> None:
        """Initialize the risk manager."""
        if self.initialized:
            self.logger.info("ProfitOptimizedRiskManager already initialized")
            return

        self.logger.info("Initializing ProfitOptimizedRiskManager")
        self.logger.info(f"Max risk per trade: {self.max_risk_per_trade:.1%}")
        self.logger.info(f"Max portfolio risk: {self.max_portfolio_risk:.1%}")
        self.logger.info(f"Kelly safety factor: {self.kelly_safety_factor:.1%}")

        self.initialized = True

    def calculate_optimal_position_size(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        current_price: float,
        portfolio_value: Optional[float] = None,
        volatility: Optional[float] = None,
        correlation: Optional[float] = None,
    ) -> dict[str, Any]:
        """Calculate optimal position size using Kelly Criterion with adjustments.

        Args:
            symbol: Trading symbol
            signal_data: Signal data from strategies (score, confidence, etc.)
            current_price: Current market price
            portfolio_value: Current portfolio value (optional)
            volatility: Asset volatility (optional)
            correlation: Correlation with portfolio (optional)

        Returns:
            Dictionary containing:
            - position_size: Optimal position size (> 0)
            - kelly_fraction: Kelly fraction used
            - risk_adjusted_size: Risk-adjusted position size
            - max_risk_respected: Whether max risk limits are respected
            - metadata: Additional calculation details
        """
        if not self.initialized:
            self.initialize()

        self.logger.debug(f"Calculating optimal position size for {symbol}")

        # Use provided portfolio value or default
        portfolio_value = portfolio_value or self.portfolio_value

        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Estimate Kelly parameters
        win_rate = self._estimate_win_rate(signal_data)
        avg_win = self._estimate_avg_win(signal_data)
        avg_loss = self._estimate_avg_loss(signal_data)

        # Calculate Kelly fraction
        kelly_fraction = self._calculate_kelly_fraction(win_rate, avg_win, avg_loss)

        # Apply volatility adjustment
        volatility_adjustment = self._calculate_volatility_adjustment(volatility)

        # Apply correlation adjustment
        correlation_adjustment = self._calculate_correlation_adjustment(correlation)

        # Calculate base position size
        base_position_size = kelly_fraction * portfolio_value / current_price

        # Apply adjustments
        adjusted_position_size = (
            base_position_size * volatility_adjustment * correlation_adjustment
        )

        # Apply risk limits
        risk_limited_size = self._apply_risk_limits(
            adjusted_position_size, current_price, portfolio_value, signal_confidence
        )

        # Ensure position size is positive
        final_position_size = max(0.0, risk_limited_size)

        # Check if max risk is respected
        position_value = final_position_size * current_price
        position_risk = position_value / portfolio_value
        max_risk_respected = position_risk <= self.max_risk_per_trade

        result = {
            "position_size": final_position_size,
            "kelly_fraction": kelly_fraction,
            "risk_adjusted_size": risk_limited_size,
            "max_risk_respected": max_risk_respected,
            "metadata": {
                "symbol": symbol,
                "current_price": current_price,
                "portfolio_value": portfolio_value,
                "signal_score": signal_score,
                "signal_confidence": signal_confidence,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "volatility": volatility,
                "volatility_adjustment": volatility_adjustment,
                "correlation": correlation,
                "correlation_adjustment": correlation_adjustment,
                "position_value": position_value,
                "position_risk": position_risk,
                "max_risk_per_trade": self.max_risk_per_trade,
                "timestamp": datetime.now().isoformat(),
            },
        }

        self.logger.info(
            f"Position size for {symbol}: {final_position_size:.4f} "
            f"(Kelly: {kelly_fraction:.3f}, Risk: {position_risk:.1%})"
        )

        return result

    def _estimate_win_rate(self, signal_data: dict[str, Any]) -> float:
        """Estimate win rate from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated win rate (0 to 1)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base win rate from signal strength and confidence
        base_win_rate = (signal_strength + signal_confidence) / 2

        # Adjust based on signal score direction
        if signal_score > 0:
            # Positive signal - boost win rate
            score_adjustment = min(0.2, signal_score * 0.1)
        else:
            # Negative signal - reduce win rate
            score_adjustment = max(-0.2, signal_score * 0.1)

        estimated_win_rate = base_win_rate + score_adjustment

        # Clamp to reasonable bounds
        estimated_win_rate = max(self.min_win_rate, min(0.8, estimated_win_rate))

        return estimated_win_rate

    def _estimate_avg_win(self, signal_data: dict[str, Any]) -> float:
        """Estimate average win from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated average win (as decimal, e.g., 0.05 for 5%)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base average win from signal strength
        base_avg_win = signal_strength * 0.05  # Max 5% average win

        # Adjust based on signal score
        if signal_score > 0:
            score_adjustment = signal_score * 0.02  # Up to 2% additional
        else:
            score_adjustment = 0.0  # No win for negative signals

        # Adjust based on confidence
        confidence_adjustment = signal_confidence * 0.01  # Up to 1% additional

        estimated_avg_win = base_avg_win + score_adjustment + confidence_adjustment

        # Clamp to reasonable bounds
        estimated_avg_win = max(0.01, min(0.10, estimated_avg_win))  # 1% to 10%

        return estimated_avg_win

    def _estimate_avg_loss(self, signal_data: dict[str, Any]) -> float:
        """Estimate average loss from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated average loss (as decimal, e.g., 0.03 for 3%)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base average loss from signal strength (inverse relationship)
        base_avg_loss = (1.0 - signal_strength) * 0.04  # Max 4% average loss

        # Adjust based on signal score
        if signal_score < 0:
            score_adjustment = abs(signal_score) * 0.02  # Up to 2% additional loss
        else:
            score_adjustment = 0.0  # No additional loss for positive signals

        # Adjust based on confidence (lower confidence = higher loss)
        confidence_adjustment = (1.0 - signal_confidence) * 0.01  # Up to 1% additional

        estimated_avg_loss = base_avg_loss + score_adjustment + confidence_adjustment

        # Clamp to reasonable bounds
        estimated_avg_loss = max(0.01, min(0.08, estimated_avg_loss))  # 1% to 8%

        return estimated_avg_loss

    def _calculate_kelly_fraction(
        self, win_rate: float, avg_win: float, avg_loss: float
    ) -> float:
        """Calculate Kelly fraction.

        Args:
            win_rate: Win rate (0 to 1)
            avg_win: Average win (as decimal)
            avg_loss: Average loss (as decimal)

        Returns:
            Kelly fraction (0 to 1)
        """
        # Protect against division by zero
        if avg_loss <= 0:
            return 0.0

        # Kelly formula: f = (bp - q) / b
        # where b = avg_win/avg_loss, p = win_rate, q = 1 - win_rate
        b = avg_win / avg_loss
        p = win_rate
        q = 1.0 - win_rate

        kelly_fraction = (b * p - q) / b

        # Apply safety factor (fractional Kelly)
        kelly_fraction *= self.kelly_safety_factor

        # Clamp to limits
        kelly_fraction = max(0.0, min(self.kelly_fraction_limit, kelly_fraction))

        # Ensure minimum Kelly fraction for strong signals
        if kelly_fraction > 0 and kelly_fraction < self.min_kelly_fraction:
            kelly_fraction = self.min_kelly_fraction

        return kelly_fraction

    def _calculate_volatility_adjustment(self, volatility: Optional[float]) -> float:
        """Calculate volatility adjustment factor.

        Args:
            volatility: Asset volatility (optional)

        Returns:
            Volatility adjustment factor (0 to 1)
        """
        if volatility is None:
            return 1.0  # No adjustment if volatility unknown

        # Higher volatility = lower position size
        # Use inverse relationship with some smoothing
        adjustment = 1.0 / (1.0 + volatility * self.volatility_adjustment_factor)

        # Clamp to reasonable bounds
        adjustment = max(0.1, min(1.0, adjustment))

        return adjustment

    def _calculate_correlation_adjustment(self, correlation: Optional[float]) -> float:
        """Calculate correlation adjustment factor.

        Args:
            correlation: Correlation with portfolio (optional)

        Returns:
            Correlation adjustment factor (0 to 1)
        """
        if correlation is None:
            return 1.0  # No adjustment if correlation unknown

        # Higher correlation = lower position size (diversification benefit)
        abs_correlation = abs(correlation)

        if abs_correlation > self.max_correlation:
            # High correlation - significant penalty
            adjustment = 0.1
        else:
            # Moderate correlation - gradual penalty
            adjustment = 1.0 - (abs_correlation * self.correlation_penalty_factor)

        # Clamp to reasonable bounds
        adjustment = max(0.1, min(1.0, adjustment))

        return adjustment

    def _apply_risk_limits(
        self,
        position_size: float,
        current_price: float,
        portfolio_value: float,
        signal_confidence: float,
    ) -> float:
        """Apply risk limits to position size.

        Args:
            position_size: Proposed position size
            current_price: Current market price
            portfolio_value: Portfolio value
            signal_confidence: Signal confidence

        Returns:
            Risk-limited position size
        """
        # Calculate position value
        position_value = position_size * current_price

        # Max risk per trade limit
        max_position_value = portfolio_value * self.max_risk_per_trade
        if position_value > max_position_value:
            position_size = max_position_value / current_price

        # Max position size limit
        max_position_value = portfolio_value * self.max_position_size
        if position_value > max_position_value:
            position_size = max_position_value / current_price

        # Adjust based on signal confidence
        confidence_adjustment = 0.5 + (signal_confidence * 0.5)  # 0.5 to 1.0
        position_size *= confidence_adjustment

        return position_size

    def update_portfolio_value(self, new_value: float) -> None:
        """Update portfolio value.

        Args:
            new_value: New portfolio value
        """
        self.portfolio_value = new_value
        self.logger.info(f"Updated portfolio value to {new_value:,.2f}")

    def get_risk_summary(self) -> dict[str, Any]:
        """Get risk summary for the portfolio.

        Returns:
            Risk summary dictionary
        """
        total_position_value = sum(
            pos.get("size", 0) * pos.get("price", 0) for pos in self.positions.values()
        )

        return {
            "portfolio_value": self.portfolio_value,
            "total_position_value": total_position_value,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_portfolio_risk": self.max_portfolio_risk,
            "max_position_size": self.max_position_size,
            "kelly_fraction_limit": self.kelly_fraction_limit,
            "kelly_safety_factor": self.kelly_safety_factor,
            "positions_count": len(self.positions),
            "risk_utilization": total_position_value / self.portfolio_value
            if self.portfolio_value > 0
            else 0,
        }


# Legacy RiskManager class for backward compatibility
class RiskManager(ProfitOptimizedRiskManager):
    """Legacy risk manager for backward compatibility."""

    def __init__(self, config: dict[str, Any]):
        """Initialize legacy risk manager."""
        super().__init__(config)
        # Map legacy config keys to new structure
        self.max_drawdown = config.get("max_drawdown", 0.15)
        self.max_correlation = config.get("max_correlation", 0.7)
        self.var_confidence = config.get("var_confidence", 0.95)
        self.var_horizon = config.get("var_horizon", 1)
        self.max_sector_exposure = config.get("max_sector_exposure", 0.3)
        self.max_currency_exposure = config.get("max_currency_exposure", 0.4)
        self.max_leverage = config.get("max_leverage", 2.0)
        self.global_stop_loss = config.get("global_stop_loss", 0.10)
        self.trailing_stop = config.get("trailing_stop", 0.05)
        self.time_based_stop = config.get("time_based_stop", 24)

        # Risk tracking
        self.risk_metrics: dict[str, RiskMetrics] = {}
        self.alert_thresholds: dict[str, float] = {}

    def calculate_var(
        self, returns: list[float], confidence: float = 0.95, horizon: int = 1
    ) -> float:
        """Calculate Value at Risk (VaR)."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        var_percentile = (1 - confidence) * 100
        var_value = np.percentile(returns_array, var_percentile)
        return var_value * np.sqrt(horizon)

    def calculate_max_drawdown(self, returns: list[float]) -> float:
        """Calculate maximum drawdown."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        cumulative_returns = np.cumprod(1 + returns_array)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        return abs(np.min(drawdown))

    def calculate_sharpe_ratio(
        self, returns: list[float], risk_free_rate: float = 0.02
    ) -> float:
        """Calculate Sharpe ratio."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate / 252
        if np.std(excess_returns) == 0:
            return 0.0
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)

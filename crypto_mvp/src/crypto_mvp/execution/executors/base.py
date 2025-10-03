"""
Base executor class for all trading strategy executors.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from ...core.logging_utils import LoggerMixin


class BaseExecutor(ABC, LoggerMixin):
    """
    Base class for all trading strategy executors.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the base executor.

        Args:
            config: Executor configuration (optional)
        """
        super().__init__()
        self.config = config or {}
        self.name = self.__class__.__name__
        self.initialized = False

    def initialize(self) -> None:
        """Initialize the executor."""
        if self.initialized:
            self.logger.info(f"{self.name} already initialized")
            return

        self.logger.info(f"Initializing {self.name}")
        self.initialized = True

    @abstractmethod
    def execute(
        self, signal: dict[str, Any], position: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a trading signal.

        Args:
            signal: Trading signal data
            position: Current position data

        Returns:
            Execution result with keys:
            - filled: bool - Whether order was filled
            - entry_price: float - Entry price
            - stop_loss: float - Stop loss price
            - take_profit: float - Take profit price
            - fees: float - Trading fees
            - expected_pnl: float - Expected profit/loss
        """
        pass

    def _calculate_expected_pnl(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: float,
        side: str,
    ) -> float:
        """Calculate expected PnL based on entry, stop loss, and take profit.

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            quantity: Position quantity
            side: Position side ('buy' or 'sell')

        Returns:
            Expected PnL
        """
        if side.lower() == "buy":
            # Long position
            profit = (take_profit - entry_price) * quantity
            loss = (entry_price - stop_loss) * quantity
        else:
            # Short position
            profit = (entry_price - take_profit) * quantity
            loss = (stop_loss - entry_price) * quantity

        # Expected PnL (assuming 50% win rate for simplicity)
        expected_pnl = (profit + loss) / 2

        return expected_pnl

    def _validate_signal(self, signal: dict[str, Any]) -> bool:
        """Validate trading signal.

        Args:
            signal: Trading signal to validate

        Returns:
            True if signal is valid, False otherwise
        """
        required_keys = ["symbol", "score", "confidence"]
        return all(key in signal for key in required_keys)

    def _get_signal_strength(self, signal: dict[str, Any]) -> float:
        """Get signal strength from signal data.

        Args:
            signal: Trading signal

        Returns:
            Signal strength (0 to 1)
        """
        score = signal.get("score", 0.0)
        confidence = signal.get("confidence", 0.0)
        signal_strength = signal.get("signal_strength", 0.0)

        # Combine metrics
        strength = abs(score) * 0.4 + confidence * 0.3 + signal_strength * 0.3

        return min(1.0, max(0.0, strength))

    def _determine_position_side(self, signal: dict[str, Any]) -> str:
        """Determine position side from signal.

        Args:
            signal: Trading signal

        Returns:
            Position side ('buy' or 'sell')
        """
        score = signal.get("score", 0.0)
        return "buy" if score > 0 else "sell"

    def _calculate_position_size(
        self,
        signal: dict[str, Any],
        position: dict[str, Any],
        available_capital: float,
        current_price: float,
    ) -> float:
        """Calculate position size based on signal and available capital.

        Args:
            signal: Trading signal
            position: Current position
            available_capital: Available capital
            current_price: Current market price

        Returns:
            Position size
        """
        # Get signal strength
        signal_strength = self._get_signal_strength(signal)

        # Base position size as percentage of available capital
        base_size_pct = signal_strength * 0.1  # Max 10% of capital

        # Adjust based on confidence
        confidence = signal.get("confidence", 0.5)
        size_pct = base_size_pct * confidence

        # Calculate position size
        position_value = available_capital * size_pct
        position_size = position_value / current_price

        return position_size

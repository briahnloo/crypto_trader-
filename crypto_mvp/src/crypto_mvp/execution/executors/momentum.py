"""
Momentum strategy executor.
"""

from typing import Any

from .base import BaseExecutor


class MomentumExecutor(BaseExecutor):
    """
    Executor for momentum trading strategy.
    """

    def __init__(self, config: dict[str, Any] = None):
        """Initialize momentum executor.

        Args:
            config: Executor configuration
        """
        super().__init__(config)
        self.name = "MomentumExecutor"

        # Momentum-specific parameters
        self.stop_loss_pct = self.config.get("stop_loss_pct", 0.02)  # 2% stop loss
        self.take_profit_pct = self.config.get(
            "take_profit_pct", 0.06
        )  # 6% take profit
        self.momentum_threshold = self.config.get(
            "momentum_threshold", 0.6
        )  # Minimum momentum

    def execute(
        self, signal: dict[str, Any], position: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute momentum trading signal.

        Args:
            signal: Trading signal data
            position: Current position data

        Returns:
            Execution result
        """
        if not self.initialized:
            self.initialize()

        # Validate signal
        if not self._validate_signal(signal):
            return self._empty_result()

        # Check momentum threshold
        signal_strength = self._get_signal_strength(signal)
        if signal_strength < self.momentum_threshold:
            return self._empty_result()

        # Get signal data
        symbol = signal.get("symbol", "")
        score = signal.get("score", 0.0)
        confidence = signal.get("confidence", 0.0)
        current_price = signal.get("current_price", 0.0)

        if current_price <= 0:
            return self._empty_result()

        # Determine position side
        side = self._determine_position_side(signal)

        # Calculate position size
        available_capital = position.get("available_capital", 10000.0)
        quantity = self._calculate_position_size(
            signal, position, available_capital, current_price
        )

        if quantity <= 0:
            return self._empty_result()

        # Calculate entry price (with slight slippage for momentum)
        entry_price = current_price * (1.001 if side == "buy" else 0.999)

        # Calculate stop loss and take profit
        if side == "buy":
            stop_loss = entry_price * (1 - self.stop_loss_pct)
            take_profit = entry_price * (1 + self.take_profit_pct)
        else:
            stop_loss = entry_price * (1 + self.stop_loss_pct)
            take_profit = entry_price * (1 - self.take_profit_pct)

        # Calculate fees (assume taker fee for momentum)
        fees = quantity * entry_price * 0.002  # 0.2% taker fee

        # Calculate expected PnL
        expected_pnl = self._calculate_expected_pnl(
            entry_price, stop_loss, take_profit, quantity, side
        )

        # Simulate fill (momentum orders typically fill quickly)
        filled = confidence > 0.5 and signal_strength > 0.6

        return {
            "filled": filled,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fees": fees,
            "expected_pnl": expected_pnl,
            "strategy": "momentum",
            "side": side,
            "quantity": quantity,
            "signal_strength": signal_strength,
            "confidence": confidence,
        }

    def _empty_result(self) -> dict[str, Any]:
        """Return empty execution result.

        Returns:
            Empty result dictionary
        """
        return {
            "filled": False,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "fees": 0.0,
            "expected_pnl": 0.0,
            "strategy": "momentum",
            "side": "none",
            "quantity": 0.0,
            "signal_strength": 0.0,
            "confidence": 0.0,
        }

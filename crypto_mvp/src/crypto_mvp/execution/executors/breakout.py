"""
Breakout strategy executor.
"""

from typing import Any

from .base import BaseExecutor


class BreakoutExecutor(BaseExecutor):
    """
    Executor for breakout trading strategy.
    """

    def __init__(self, config: dict[str, Any] = None):
        """Initialize breakout executor.

        Args:
            config: Executor configuration
        """
        super().__init__(config)
        self.name = "BreakoutExecutor"

        # Breakout-specific parameters
        self.stop_loss_pct = self.config.get("stop_loss_pct", 0.015)  # 1.5% stop loss
        self.take_profit_pct = self.config.get(
            "take_profit_pct", 0.045
        )  # 4.5% take profit
        self.breakout_threshold = self.config.get(
            "breakout_threshold", 0.7
        )  # Minimum breakout strength
        self.volume_confirmation = self.config.get(
            "volume_confirmation", True
        )  # Require volume confirmation

    def execute(
        self, signal: dict[str, Any], position: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute breakout trading signal.

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

        # Check breakout threshold
        signal_strength = self._get_signal_strength(signal)
        if signal_strength < self.breakout_threshold:
            return self._empty_result()

        # Check volume confirmation if required
        if self.volume_confirmation:
            volume_ratio = signal.get("volume_ratio", 1.0)
            if volume_ratio < 1.5:  # Require 50% above average volume
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

        # Calculate position size (breakout positions can be larger)
        available_capital = position.get("available_capital", 10000.0)
        base_quantity = self._calculate_position_size(
            signal, position, available_capital, current_price
        )

        # Breakout positions can be 1.5x normal size
        quantity = base_quantity * 1.5

        if quantity <= 0:
            return self._empty_result()

        # Calculate entry price (breakouts often have slippage)
        slippage = 0.002 if side == "buy" else -0.002  # 0.2% slippage
        entry_price = current_price * (1 + slippage)

        # Calculate stop loss and take profit
        if side == "buy":
            stop_loss = entry_price * (1 - self.stop_loss_pct)
            take_profit = entry_price * (1 + self.take_profit_pct)
        else:
            stop_loss = entry_price * (1 + self.stop_loss_pct)
            take_profit = entry_price * (1 - self.take_profit_pct)

        # Calculate fees (assume taker fee for breakouts)
        fees = quantity * entry_price * 0.002  # 0.2% taker fee

        # Calculate expected PnL
        expected_pnl = self._calculate_expected_pnl(
            entry_price, stop_loss, take_profit, quantity, side
        )

        # Simulate fill (breakout orders fill with high probability)
        filled = confidence > 0.6 and signal_strength > 0.7

        return {
            "filled": filled,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fees": fees,
            "expected_pnl": expected_pnl,
            "strategy": "breakout",
            "side": side,
            "quantity": quantity,
            "signal_strength": signal_strength,
            "confidence": confidence,
            "volume_ratio": signal.get("volume_ratio", 1.0),
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
            "strategy": "breakout",
            "side": "none",
            "quantity": 0.0,
            "signal_strength": 0.0,
            "confidence": 0.0,
            "volume_ratio": 1.0,
        }

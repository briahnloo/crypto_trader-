"""
Breakout strategy executor implementation.
"""

from typing import Any

from ...core.logging_utils import LoggerMixin
from ..order_manager import OrderManager, OrderSide, OrderType


class BreakoutExecutor(LoggerMixin):
    """Breakout strategy executor."""

    def __init__(self, order_manager: OrderManager, config: dict[str, Any]):
        """Initialize breakout executor.

        Args:
            order_manager: Order manager instance
            config: Executor configuration
        """
        self.order_manager = order_manager
        self.config = config

        # Execution parameters
        self.max_position_size = config.get("max_position_size", 0.1)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)
        self.take_profit_pct = config.get("take_profit_pct", 0.08)
        self.volume_confirmation = config.get("volume_confirmation", True)
        self.volume_multiplier = config.get("volume_multiplier", 1.5)

    async def execute_breakout_signal(
        self, symbol: str, signal: dict[str, Any], current_price: float
    ) -> dict[str, Any]:
        """Execute breakout trading signal.

        Args:
            symbol: Trading symbol
            signal: Trading signal data
            current_price: Current market price

        Returns:
            Execution result
        """
        try:
            # Validate signal
            if not self._validate_breakout_signal(signal):
                return {"status": "rejected", "reason": "Invalid signal"}

            # Check volume confirmation
            if self.volume_confirmation and not self._check_volume_confirmation(signal):
                return {"status": "rejected", "reason": "Volume confirmation failed"}

            # Calculate position size
            position_size = self._calculate_position_size(signal, current_price)

            # Determine order side
            order_side = (
                OrderSide.BUY if signal["signal_type"] == "buy" else OrderSide.SELL
            )

            # Create order
            order, error_reason = self.order_manager.create_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position_size,
                price=current_price,
                metadata={
                    "strategy": "breakout",
                    "confidence": signal.get("confidence", 0.0),
                    "signal_metadata": signal.get("metadata", {}),
                },
            )

            if not order:
                return {"status": "failed", "reason": f"Order creation failed: {error_reason}"}

            # Submit order
            success = self.order_manager.submit_order(order.id)

            if success:
                # Set stop loss and take profit
                self._set_risk_management(order.id, symbol, current_price, order_side)

                return {
                    "status": "executed",
                    "order_id": order.id,
                    "position_size": position_size,
                    "order_side": order_side.value,
                }
            else:
                return {"status": "failed", "reason": "Order submission failed"}

        except Exception as e:
            self.logger.error(f"Breakout execution failed: {e}")
            return {"status": "error", "error": str(e)}

    def _validate_breakout_signal(self, signal: dict[str, Any]) -> bool:
        """Validate breakout signal.

        Args:
            signal: Trading signal

        Returns:
            True if signal is valid
        """
        required_fields = ["signal_type", "confidence", "price"]

        for field in required_fields:
            if field not in signal:
                return False

        # Check signal type
        if signal["signal_type"] not in ["buy", "sell"]:
            return False

        # Check confidence
        if signal["confidence"] < 0.6:
            return False

        # Check price
        if signal["price"] <= 0:
            return False

        # Check breakout metadata
        metadata = signal.get("metadata", {})
        if "breakout_type" not in metadata:
            return False

        return True

    def _check_volume_confirmation(self, signal: dict[str, Any]) -> bool:
        """Check volume confirmation for breakout signal.

        Args:
            signal: Trading signal

        Returns:
            True if volume confirmation passes
        """
        metadata = signal.get("metadata", {})
        volume_ratio = metadata.get("volume_ratio", 1.0)

        return volume_ratio >= self.volume_multiplier

    def _calculate_position_size(
        self, signal: dict[str, Any], current_price: float
    ) -> float:
        """Calculate position size for breakout signal.

        Args:
            signal: Trading signal
            current_price: Current market price

        Returns:
            Position size
        """
        # Base position size
        base_size = self.max_position_size

        # Adjust by confidence
        confidence = signal.get("confidence", 0.5)
        confidence_multiplier = confidence * 2  # Scale to 0-1

        # Adjust by breakout strength
        metadata = signal.get("metadata", {})
        breakout_strength = metadata.get("breakout_strength", 0.02)
        strength_multiplier = min(1.0, breakout_strength * 10)  # Scale to 0-1

        # Adjust by volume confirmation
        volume_ratio = metadata.get("volume_ratio", 1.0)
        volume_multiplier = min(1.0, volume_ratio / self.volume_multiplier)

        # Calculate final position size
        position_size = (
            base_size * confidence_multiplier * strength_multiplier * volume_multiplier
        )

        # Ensure minimum and maximum limits
        min_size = 0.01
        max_size = self.max_position_size

        return max(min_size, min(position_size, max_size))

    def _set_risk_management(
        self, order_id: str, symbol: str, current_price: float, order_side: OrderSide
    ) -> None:
        """Set stop loss and take profit for order.

        Args:
            order_id: Order ID
            symbol: Trading symbol
            current_price: Current price
            order_side: Order side
        """
        try:
            # Calculate stop loss and take profit prices
            if order_side == OrderSide.BUY:
                stop_loss_price = current_price * (1 - self.stop_loss_pct)
                take_profit_price = current_price * (1 + self.take_profit_pct)
            else:  # SELL
                stop_loss_price = current_price * (1 + self.stop_loss_pct)
                take_profit_price = current_price * (1 - self.take_profit_pct)

            # Create stop loss order
            stop_loss_order, stop_loss_error = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.SELL if order_side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=0,  # Will be set when main order is filled
                price=stop_loss_price,
                stop_price=stop_loss_price,
                metadata={
                    "strategy": "breakout",
                    "type": "stop_loss",
                    "parent_order": order_id,
                },
            )

            # Create take profit order
            take_profit_order, take_profit_error = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.SELL if order_side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=0,  # Will be set when main order is filled
                price=take_profit_price,
                metadata={
                    "strategy": "breakout",
                    "type": "take_profit",
                    "parent_order": order_id,
                },
            )

            # Log results
            if stop_loss_order and take_profit_order:
                self.logger.info(
                    f"Set risk management for order {order_id}: "
                    f"SL={stop_loss_price:.2f}, TP={take_profit_price:.2f}"
                )
            else:
                if not stop_loss_order:
                    self.logger.warning(f"Failed to create stop loss order: {stop_loss_error}")
                if not take_profit_order:
                    self.logger.warning(f"Failed to create take profit order: {take_profit_error}")

        except Exception as e:
            self.logger.error(f"Failed to set risk management: {e}")

    def get_executor_summary(self) -> dict[str, Any]:
        """Get executor summary.

        Returns:
            Executor summary dictionary
        """
        return {
            "executor_type": "breakout",
            "max_position_size": self.max_position_size,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "volume_confirmation": self.volume_confirmation,
            "volume_multiplier": self.volume_multiplier,
        }

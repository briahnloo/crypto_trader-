"""
Sentiment strategy executor implementation.
"""

from typing import Any

from ...core.logging_utils import LoggerMixin
from ..order_manager import OrderManager, OrderSide, OrderType


class SentimentExecutor(LoggerMixin):
    """Sentiment strategy executor."""

    def __init__(self, order_manager: OrderManager, config: dict[str, Any]):
        """Initialize sentiment executor.

        Args:
            order_manager: Order manager instance
            config: Executor configuration
        """
        self.order_manager = order_manager
        self.config = config

        # Execution parameters
        self.max_position_size = config.get("max_position_size", 0.1)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.06)
        self.take_profit_pct = config.get("take_profit_pct", 0.12)
        self.sentiment_threshold = config.get("sentiment_threshold", 0.6)
        self.volume_threshold = config.get("volume_threshold", 1.2)
        self.news_impact_threshold = config.get("news_impact_threshold", 0.7)

    async def execute_sentiment_signal(
        self, symbol: str, signal: dict[str, Any], current_price: float
    ) -> dict[str, Any]:
        """Execute sentiment trading signal.

        Args:
            symbol: Trading symbol
            signal: Trading signal data
            current_price: Current market price

        Returns:
            Execution result
        """
        try:
            # Validate signal
            if not self._validate_sentiment_signal(signal):
                return {"status": "rejected", "reason": "Invalid signal"}

            # Check sentiment confirmation
            if not self._check_sentiment_confirmation(signal):
                return {"status": "rejected", "reason": "Sentiment confirmation failed"}

            # Calculate position size
            position_size = self._calculate_position_size(signal, current_price)

            # Determine order side
            order_side = (
                OrderSide.BUY if signal["signal_type"] == "buy" else OrderSide.SELL
            )

            # Create order
            order_id = self.order_manager.create_order(
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=position_size,
                price=current_price,
                metadata={
                    "strategy": "sentiment",
                    "confidence": signal.get("confidence", 0.0),
                    "signal_metadata": signal.get("metadata", {}),
                },
            )

            # Submit order
            success = self.order_manager.submit_order(order_id)

            if success:
                # Set stop loss and take profit
                self._set_risk_management(order_id, symbol, current_price, order_side)

                return {
                    "status": "executed",
                    "order_id": order_id,
                    "position_size": position_size,
                    "order_side": order_side.value,
                }
            else:
                return {"status": "failed", "reason": "Order submission failed"}

        except Exception as e:
            self.logger.error(f"Sentiment execution failed: {e}")
            return {"status": "error", "error": str(e)}

    def _validate_sentiment_signal(self, signal: dict[str, Any]) -> bool:
        """Validate sentiment signal.

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
        if signal["confidence"] < self.sentiment_threshold:
            return False

        # Check price
        if signal["price"] <= 0:
            return False

        # Check sentiment metadata
        metadata = signal.get("metadata", {})
        if "sentiment_type" not in metadata:
            return False

        return True

    def _check_sentiment_confirmation(self, signal: dict[str, Any]) -> bool:
        """Check sentiment confirmation for signal.

        Args:
            signal: Trading signal

        Returns:
            True if sentiment confirmation passes
        """
        metadata = signal.get("metadata", {})

        # Check sentiment type
        sentiment_type = metadata.get("sentiment_type", "")
        if sentiment_type not in [
            "bullish",
            "bearish",
            "moderate_bullish",
            "moderate_bearish",
        ]:
            return False

        # Check volume confirmation
        volume_ratio = metadata.get("volume_ratio", 1.0)
        if volume_ratio < self.volume_threshold:
            return False

        # Check news impact
        news_impact_score = metadata.get("news_impact_score", 0.0)
        if news_impact_score < self.news_impact_threshold:
            return False

        return True

    def _calculate_position_size(
        self, signal: dict[str, Any], current_price: float
    ) -> float:
        """Calculate position size for sentiment signal.

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

        # Adjust by sentiment strength
        metadata = signal.get("metadata", {})
        sentiment_type = metadata.get("sentiment_type", "moderate")

        strength_multiplier = {
            "bullish": 1.0,
            "bearish": 1.0,
            "moderate_bullish": 0.7,
            "moderate_bearish": 0.7,
        }.get(sentiment_type, 0.7)

        # Adjust by news impact
        news_impact_score = metadata.get("news_impact_score", 0.5)
        news_multiplier = min(1.0, news_impact_score)

        # Adjust by volume confirmation
        volume_ratio = metadata.get("volume_ratio", 1.0)
        volume_multiplier = min(1.0, volume_ratio / self.volume_threshold)

        # Calculate final position size
        position_size = (
            base_size
            * confidence_multiplier
            * strength_multiplier
            * news_multiplier
            * volume_multiplier
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
            stop_loss_order_id = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.SELL if order_side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=0,  # Will be set when main order is filled
                price=stop_loss_price,
                stop_price=stop_loss_price,
                metadata={
                    "strategy": "sentiment",
                    "type": "stop_loss",
                    "parent_order": order_id,
                },
            )

            # Create take profit order
            take_profit_order_id = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.SELL if order_side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=0,  # Will be set when main order is filled
                price=take_profit_price,
                metadata={
                    "strategy": "sentiment",
                    "type": "take_profit",
                    "parent_order": order_id,
                },
            )

            self.logger.info(
                f"Set risk management for order {order_id}: "
                f"SL={stop_loss_price:.2f}, TP={take_profit_price:.2f}"
            )

        except Exception as e:
            self.logger.error(f"Failed to set risk management: {e}")

    def get_executor_summary(self) -> dict[str, Any]:
        """Get executor summary.

        Returns:
            Executor summary dictionary
        """
        return {
            "executor_type": "sentiment",
            "max_position_size": self.max_position_size,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "sentiment_threshold": self.sentiment_threshold,
            "volume_threshold": self.volume_threshold,
            "news_impact_threshold": self.news_impact_threshold,
        }

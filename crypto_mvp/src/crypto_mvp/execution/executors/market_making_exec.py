"""
Market making strategy executor implementation.
"""

from datetime import datetime
from typing import Any

from ...core.logging_utils import LoggerMixin
from ..order_manager import OrderManager, OrderSide, OrderType


class MarketMakingExecutor(LoggerMixin):
    """Market making strategy executor."""

    def __init__(self, order_manager: OrderManager, config: dict[str, Any]):
        """Initialize market making executor.

        Args:
            order_manager: Order manager instance
            config: Executor configuration
        """
        self.order_manager = order_manager
        self.config = config

        # Execution parameters
        self.max_position_size = config.get("max_position_size", 0.1)
        self.spread_pct = config.get("spread_pct", 0.002)  # 0.2%
        self.order_size = config.get("order_size", 0.01)
        self.max_inventory = config.get("max_inventory", 0.05)
        self.inventory_rebalance_threshold = config.get(
            "inventory_rebalance_threshold", 0.8
        )
        self.order_refresh_time = config.get("order_refresh_time", 30)  # 30 seconds

        # Market making state
        self.active_orders: dict[str, list[str]] = {}  # symbol -> list of order IDs
        self.inventory: dict[str, float] = {}  # symbol -> inventory
        self.last_order_time: dict[str, datetime] = {}  # symbol -> last order time

    async def execute_market_making(
        self, symbol: str, market_data: dict[str, Any], current_price: float
    ) -> dict[str, Any]:
        """Execute market making strategy.

        Args:
            symbol: Trading symbol
            market_data: Market data including order book
            current_price: Current market price

        Returns:
            Execution result
        """
        try:
            # Check if we need to refresh orders
            if not self._should_refresh_orders(symbol):
                return {"status": "skipped", "reason": "Orders not due for refresh"}

            # Cancel existing orders
            await self._cancel_existing_orders(symbol)

            # Check inventory limits
            if not self._check_inventory_limits(symbol):
                return {"status": "skipped", "reason": "Inventory limits exceeded"}

            # Calculate bid and ask prices
            bid_price, ask_price = self._calculate_market_making_prices(current_price)

            # Calculate order sizes
            bid_size, ask_size = self._calculate_order_sizes(symbol, current_price)

            # Create market making orders
            orders_created = await self._create_market_making_orders(
                symbol, bid_price, ask_price, bid_size, ask_size
            )

            if orders_created:
                return {
                    "status": "executed",
                    "orders_created": orders_created,
                    "bid_price": bid_price,
                    "ask_price": ask_price,
                    "spread": ask_price - bid_price,
                }
            else:
                return {
                    "status": "failed",
                    "reason": "Failed to create market making orders",
                }

        except Exception as e:
            self.logger.error(f"Market making execution failed: {e}")
            return {"status": "error", "error": str(e)}

    def _should_refresh_orders(self, symbol: str) -> bool:
        """Check if orders need to be refreshed.

        Args:
            symbol: Trading symbol

        Returns:
            True if orders should be refreshed
        """
        if symbol not in self.last_order_time:
            return True

        time_since_last = (
            datetime.now() - self.last_order_time[symbol]
        ).total_seconds()
        return time_since_last >= self.order_refresh_time

    async def _cancel_existing_orders(self, symbol: str) -> None:
        """Cancel existing market making orders for symbol.

        Args:
            symbol: Trading symbol
        """
        if symbol not in self.active_orders:
            return

        for order_id in self.active_orders[symbol]:
            self.order_manager.cancel_order(order_id)

        self.active_orders[symbol] = []

    def _check_inventory_limits(self, symbol: str) -> bool:
        """Check if inventory is within limits.

        Args:
            symbol: Trading symbol

        Returns:
            True if inventory is within limits
        """
        current_inventory = abs(self.inventory.get(symbol, 0.0))
        return current_inventory <= self.max_inventory

    def _calculate_market_making_prices(
        self, current_price: float
    ) -> tuple[float, float]:
        """Calculate bid and ask prices for market making.

        Args:
            current_price: Current market price

        Returns:
            Tuple of (bid_price, ask_price)
        """
        half_spread = current_price * self.spread_pct / 2

        bid_price = current_price - half_spread
        ask_price = current_price + half_spread

        return bid_price, ask_price

    def _calculate_order_sizes(
        self, symbol: str, current_price: float
    ) -> tuple[float, float]:
        """Calculate order sizes for market making.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            Tuple of (bid_size, ask_size)
        """
        base_size = self.order_size

        # Adjust based on inventory
        current_inventory = self.inventory.get(symbol, 0.0)
        inventory_ratio = abs(current_inventory) / self.max_inventory

        if current_inventory > 0:  # Long inventory
            # Reduce bid size, increase ask size
            bid_size = base_size * (1 - inventory_ratio * 0.5)
            ask_size = base_size * (1 + inventory_ratio * 0.5)
        elif current_inventory < 0:  # Short inventory
            # Increase bid size, reduce ask size
            bid_size = base_size * (1 + inventory_ratio * 0.5)
            ask_size = base_size * (1 - inventory_ratio * 0.5)
        else:  # Neutral inventory
            bid_size = base_size
            ask_size = base_size

        # Ensure minimum size
        min_size = 0.001
        bid_size = max(min_size, bid_size)
        ask_size = max(min_size, ask_size)

        return bid_size, ask_size

    async def _create_market_making_orders(
        self,
        symbol: str,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
    ) -> list[str]:
        """Create market making orders.

        Args:
            symbol: Trading symbol
            bid_price: Bid price
            ask_price: Ask price
            bid_size: Bid size
            ask_size: Ask size

        Returns:
            List of created order IDs
        """
        orders_created = []

        try:
            # Create bid order
            bid_order_id = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=bid_size,
                price=bid_price,
                metadata={
                    "strategy": "market_making",
                    "order_type": "bid",
                    "spread_pct": self.spread_pct,
                },
            )

            # Create ask order
            ask_order_id = self.order_manager.create_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=ask_size,
                price=ask_price,
                metadata={
                    "strategy": "market_making",
                    "order_type": "ask",
                    "spread_pct": self.spread_pct,
                },
            )

            # Submit orders
            bid_success = self.order_manager.submit_order(bid_order_id)
            ask_success = self.order_manager.submit_order(ask_order_id)

            if bid_success and ask_success:
                orders_created = [bid_order_id, ask_order_id]

                # Track orders
                if symbol not in self.active_orders:
                    self.active_orders[symbol] = []
                self.active_orders[symbol].extend(orders_created)

                # Update last order time
                self.last_order_time[symbol] = datetime.now()

                self.logger.info(
                    f"Created market making orders for {symbol}: "
                    f"Bid {bid_size} @ {bid_price}, Ask {ask_size} @ {ask_price}"
                )

        except Exception as e:
            self.logger.error(f"Failed to create market making orders: {e}")

        return orders_created

    def update_inventory(self, symbol: str, size: float) -> None:
        """Update inventory for a symbol.

        Args:
            symbol: Trading symbol
            size: Position size change
        """
        if symbol not in self.inventory:
            self.inventory[symbol] = 0.0

        self.inventory[symbol] += size

        self.logger.info(f"Updated inventory for {symbol}: {self.inventory[symbol]}")

    def get_inventory(self, symbol: str) -> float:
        """Get current inventory for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Current inventory
        """
        return self.inventory.get(symbol, 0.0)

    def get_executor_summary(self) -> dict[str, Any]:
        """Get executor summary.

        Returns:
            Executor summary dictionary
        """
        return {
            "executor_type": "market_making",
            "max_position_size": self.max_position_size,
            "spread_pct": self.spread_pct,
            "order_size": self.order_size,
            "max_inventory": self.max_inventory,
            "active_orders": sum(len(orders) for orders in self.active_orders.values()),
            "inventory": self.inventory.copy(),
        }

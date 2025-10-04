"""
Order management system for cryptocurrency trading.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from ..core.logging_utils import LoggerMixin
from ..core.utils import get_mark_price, validate_mark_price


class OrderType(Enum):
    """Order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TAKE_PROFIT = "take_profit"
    TAKE_PROFIT_LIMIT = "take_profit_limit"


class OrderSide(Enum):
    """Order sides."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status."""

    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Order data structure."""

    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"  # Good Till Cancelled
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_price: Optional[float] = None
    fees: float = 0.0
    timestamp: datetime = None
    strategy: str = ""
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class Fill:
    """Fill data structure."""

    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fees: float
    timestamp: datetime
    strategy: str = ""
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class OrderManager(LoggerMixin):
    """
    Order management system with side-effect-free order handling and mock fill simulation.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the order manager.

        Args:
            config: Order management configuration (optional)
        """
        super().__init__()
        self.config = config or {}

        # Fee configuration (in basis points)
        self.maker_fee_bps = self.config.get("maker_fee_bps", 10)  # 0.1%
        self.taker_fee_bps = self.config.get("taker_fee_bps", 20)  # 0.2%

        # Simulation parameters
        self.simulate = self.config.get("simulate", True)  # Paper trading mode
        self.sandbox_mode = self.config.get(
            "sandbox_mode", True
        )  # Sandbox/testnet mode
        self.dry_run = self.config.get("dry_run", False)  # Dry run guard for staging

        # Safety rails
        self.live_mode = self.config.get("live_mode", False)
        self.api_keys_validated = False
        self.slippage_bps = self.config.get("slippage_bps", 5)  # 0.05% slippage
        
        # Session management
        self.current_session_id = None

        # Market simulation parameters
        self.volatility_factor = self.config.get(
            "volatility_factor", 0.02
        )  # 2% volatility
        self.liquidity_factor = self.config.get(
            "liquidity_factor", 0.95
        )  # 95% fill probability

        # Order tracking
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.order_counter = 0

        self.initialized = False
        
        # Data engine for getting mark prices (will be set by trading system)
        self.data_engine = None
        
        # State store for session cash management (will be set by trading system)
        self.state_store = None

    def validate_api_keys(self, config: dict[str, Any]) -> bool:
        """
        Validate that all required API keys are present for live trading.

        Args:
            config: Configuration dictionary

        Returns:
            True if all required API keys are present, False otherwise
        """
        if not self.live_mode:
            return True  # No API keys needed for paper trading

        # Check exchange API keys
        exchanges = config.get("exchanges", {})
        for exchange_name, exchange_config in exchanges.items():
            if exchange_config.get("enabled", False):
                api_key = exchange_config.get("api_key")
                secret = exchange_config.get("secret")

                if not api_key or api_key in ["your_api_key_here", ""]:
                    self.logger.error(f"Missing API key for exchange: {exchange_name}")
                    return False

                if not secret or secret in ["your_secret_key_here", ""]:
                    self.logger.error(
                        f"Missing secret key for exchange: {exchange_name}"
                    )
                    return False

        # Check data source API keys if required
        data_sources = config.get("data_sources", {})

        # Check sentiment data sources
        sentiment = data_sources.get("sentiment", {})
        for source_name, source_config in sentiment.get("sources", {}).items():
            if source_config.get("enabled", False):
                api_keys = source_config.get("api_keys", {})
                for key_name, key_value in api_keys.items():
                    if not key_value or key_value in ["your_api_key_here", ""]:
                        self.logger.warning(
                            f"Missing API key for sentiment source {source_name}.{key_name}"
                        )

        # Check on-chain data sources
        on_chain = data_sources.get("on_chain", {})
        api_keys = on_chain.get("api_keys", {})
        for key_name, key_value in api_keys.items():
            if not key_value or key_value in ["your_api_key_here", ""]:
                self.logger.warning(f"Missing API key for on-chain source: {key_name}")

        self.api_keys_validated = True
        return True

    def check_safety_rails(self) -> None:
        """
        Check safety rails before allowing live trading.

        Raises:
            RuntimeError: If safety rails prevent live trading
        """
        # Check if dry run is enabled
        if self.dry_run:
            raise RuntimeError(
                "DRY RUN MODE ENABLED: Live trading is disabled. "
                "Remove 'dry_run: true' from config to enable live trading."
            )

        # Check if we're in live mode but API keys aren't validated
        if self.live_mode and not self.api_keys_validated:
            raise RuntimeError(
                "API KEYS NOT VALIDATED: Cannot proceed with live trading. "
                "Ensure all required API keys are properly configured."
            )

        # Check if we're in live mode but simulation is still enabled
        if self.live_mode and self.simulate:
            self.logger.warning(
                "Live mode enabled but simulation is still active. "
                "This may indicate a configuration issue."
            )

    def is_live_trading_allowed(self) -> bool:
        """
        Check if live trading is allowed based on safety rails.

        Returns:
            True if live trading is allowed, False otherwise
        """
        try:
            self.check_safety_rails()
            return self.live_mode and not self.simulate and not self.dry_run
        except RuntimeError:
            return False


    def initialize(self) -> None:
        """Initialize the order manager."""
        if self.initialized:
            self.logger.info("OrderManager already initialized")
            return

        self.logger.info("Initializing OrderManager")
        self.logger.info(f"Simulation mode: {self.simulate}")
        self.logger.info(f"Sandbox mode: {self.sandbox_mode}")
        self.logger.info(f"Maker fee: {self.maker_fee_bps} bps")
        self.logger.info(f"Taker fee: {self.taker_fee_bps} bps")

        self.initialized = True

    def set_data_engine(self, data_engine) -> None:
        """Set the data engine for getting mark prices.
        
        Args:
            data_engine: Data engine instance
        """
        self.data_engine = data_engine
        self.logger.info("Data engine set for order manager")

    def set_session_id(self, session_id: str) -> None:
        """Set the current session ID for order operations.
        
        Args:
            session_id: Session identifier
        """
        if not session_id:
            raise ValueError("session_id cannot be empty")
        self.current_session_id = session_id
        self.logger.debug(f"OrderManager session ID set to: {session_id}")

    def set_state_store(self, state_store) -> None:
        """Set the state store for session cash management.
        
        Args:
            state_store: State store instance
        """
        self.state_store = state_store
        self.logger.info("State store set for order manager")

    def get_order_price(self, symbol: str, order_type: OrderType, price: Optional[float] = None) -> Optional[float]:
        """Get appropriate price for an order using mark prices.
        
        Args:
            symbol: Trading symbol
            order_type: Type of order
            price: Explicit price if provided
            
        Returns:
            Order price or None if no valid price available
        """
        # If explicit price provided, validate it
        if price is not None:
            if price > 0 and validate_mark_price(price, symbol):
                return price
            else:
                self.logger.info(f"⏭️ SKIP {symbol} reason=price_out_of_range notional=$0.00 cash=$0.00")
                return None
        
        # For market orders, we need current mark price
        if order_type == OrderType.MARKET:
            if not self.data_engine:
                self.logger.info(f"⏭️ SKIP {symbol} reason=no_price notional=$0.00 cash=$0.00")
                return None
            
            mark_price = get_mark_price(
                symbol, 
                self.data_engine, 
                live_mode=self.live_mode
            )
            
            if mark_price and validate_mark_price(mark_price, symbol):
                return mark_price
            else:
                # Check if we have a data engine but no price (likely stale)
                if self.data_engine:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=stale_price notional=$0.00 cash=$0.00")
                else:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=no_price notional=$0.00 cash=$0.00")
                return None
        
        # For limit orders without explicit price, use mark price as reference
        elif order_type == OrderType.LIMIT and price is None:
            if not self.data_engine:
                self.logger.info(f"⏭️ SKIP {symbol} reason=no_price notional=$0.00 cash=$0.00")
                return None
            
            mark_price = get_mark_price(
                symbol, 
                self.data_engine, 
                live_mode=self.live_mode
            )
            
            if mark_price and validate_mark_price(mark_price, symbol):
                # Use mark price as default limit price
                return mark_price
            else:
                # Check if we have a data engine but no price (likely stale)
                if self.data_engine:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=stale_price notional=$0.00 cash=$0.00")
                else:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=no_price notional=$0.00 cash=$0.00")
                return None
        
        # For other order types, return the provided price or None
        return price if price and price > 0 else None

    def check_budget_constraints(
        self, 
        symbol: str, 
        side: OrderSide, 
        quantity: float, 
        price: float
    ) -> tuple[bool, float, str]:
        """Check budget constraints and adjust quantity if necessary.
        
        Args:
            symbol: Trading symbol
            side: Order side (buy/sell)
            quantity: Requested quantity
            price: Order price
            
        Returns:
            Tuple of (can_proceed, adjusted_quantity, skip_reason)
            - can_proceed: True if order can proceed
            - adjusted_quantity: Quantity after budget adjustment (0 if skipped)
            - skip_reason: Reason for skipping if can_proceed is False
        """
        if not self.state_store:
            self.logger.warning("No state store available for budget checking")
            return True, quantity, ""
        
        # Get current session cash
        session_cash = self.state_store.get_session_cash()
        
        # Calculate notional value
        notional = quantity * price
        
        # Check minimum notional (typically $10-20 for most exchanges)
        min_notional = 10.0  # Minimum notional value
        if notional < min_notional:
            self.logger.info(f"⏭️ SKIP {symbol} reason=min_notional notional=${notional:.2f} cash=${session_cash:.2f}")
            return False, 0.0, "min_notional"
        
        # Check precision (ensure quantity is valid lot size)
        # Simplified lot size check - assume 0.001 precision for most crypto pairs
        min_lot_size = 0.001
        if quantity < min_lot_size:
            self.logger.info(f"⏭️ SKIP {symbol} reason=precision_fail notional=${notional:.2f} cash=${session_cash:.2f}")
            return False, 0.0, "precision_fail"
        
        if side == OrderSide.BUY:
            # For buy orders, check if we have enough cash
            # Estimate fees (use taker fee as worst case)
            estimated_fees = notional * (self.taker_fee_bps / 10000)
            est_cost = notional + estimated_fees
            
            if est_cost > session_cash:
                # Try to shrink notional to fit
                max_affordable_notional = max(0, session_cash - estimated_fees)
                
                if max_affordable_notional <= 0:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=budget_exhausted notional=${notional:.2f} cash=${session_cash:.2f}")
                    return False, 0.0, "budget_exhausted"
                
                # Check if adjusted notional meets minimum requirements
                if max_affordable_notional < min_notional:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=min_notional notional=${max_affordable_notional:.2f} cash=${session_cash:.2f}")
                    return False, 0.0, "min_notional"
                
                # Recalculate quantity based on affordable notional
                adjusted_quantity = max_affordable_notional / price
                
                # Round down to lot size (simplified - assume 0.001 lot size)
                adjusted_quantity = int(adjusted_quantity * 1000) / 1000
                
                if adjusted_quantity <= 0:
                    self.logger.info(f"⏭️ SKIP {symbol} reason=budget_exhausted notional=${max_affordable_notional:.2f} cash=${session_cash:.2f}")
                    return False, 0.0, "budget_exhausted"
                
                self.logger.info(f"Budget constraint: reduced {symbol} buy quantity from {quantity:.4f} to {adjusted_quantity:.4f}")
                return True, adjusted_quantity, ""
            else:
                return True, quantity, ""
        else:
            # For sell orders, we're adding cash, so no constraint
            return True, quantity, ""

    def apply_fill_cash_impact(self, fill: Fill) -> bool:
        """Apply cash impact of a fill to the session.
        
        Args:
            fill: Fill information
            
        Returns:
            True if successful, False if error
        """
        if not self.state_store:
            self.logger.warning("No state store available for cash impact")
            return False
        
        if fill.quantity <= 0:
            # No fill, no cash impact
            return True
        
        notional = fill.quantity * fill.price
        
        if not self.current_session_id:
            raise RuntimeError("session_id not set - cannot process cash operations without valid session")

        if fill.side == OrderSide.BUY:
            # Debit cash for buy orders
            success = self.state_store.debit_cash(self.current_session_id, notional, fill.fees)
            if not success:
                self.logger.error(f"Failed to debit cash for buy order: {fill.order_id}")
                return False
        else:
            # Credit cash for sell orders
            success = self.state_store.credit_cash(self.current_session_id, notional, fill.fees)
            if not success:
                self.logger.error(f"Failed to credit cash for sell order: {fill.order_id}")
                return False
        
        self.logger.debug(f"Applied cash impact for {fill.side.value} order {fill.order_id}: ${notional:.2f}")
        return True

    def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        strategy: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[Order]:
        """Create a new order with mark price validation and budget constraints.

        Args:
            symbol: Trading symbol
            side: Order side (buy/sell)
            order_type: Order type
            quantity: Order quantity
            price: Order price (for limit orders)
            stop_price: Stop price (for stop orders)
            strategy: Strategy name
            metadata: Additional metadata

        Returns:
            Created order or None if price validation fails or budget constraints prevent order
        """
        if not self.initialized:
            self.initialize()

        # Get validated price for the order
        validated_price = self.get_order_price(symbol, order_type, price)
        
        if validated_price is None:
            # Price validation skip is already logged in get_order_price
            return None

        # Check budget constraints and adjust quantity if necessary
        can_proceed, adjusted_quantity, skip_reason = self.check_budget_constraints(
            symbol, side, quantity, validated_price
        )
        
        if not can_proceed:
            # Skip reason is already logged in check_budget_constraints with cash/notional info
            return None
        
        # Use adjusted quantity
        quantity = adjusted_quantity

        # Generate unique order ID
        self.order_counter += 1
        order_id = f"order_{self.order_counter}_{int(datetime.now().timestamp())}"

        # Create order with validated price and adjusted quantity
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=validated_price,
            stop_price=stop_price,
            strategy=strategy,
            metadata=metadata or {},
        )

        # Store order
        self.orders[order_id] = order

        self.logger.debug(
            f"Created order {order_id}: {side.value} {quantity} {symbol} @ {validated_price}"
        )

        return order

    def calculate_fees(
        self,
        quantity: float,
        price: float,
        order_type: OrderType,
        is_maker: bool = False,
    ) -> float:
        """Calculate trading fees.

        Args:
            quantity: Order quantity
            price: Order price
            order_type: Order type
            is_maker: Whether this is a maker order

        Returns:
            Calculated fees
        """
        # Determine fee rate
        if is_maker or order_type == OrderType.LIMIT:
            fee_bps = self.maker_fee_bps
        else:
            fee_bps = self.taker_fee_bps

        # Calculate fees
        notional_value = quantity * price
        fees = notional_value * (fee_bps / 10000)  # Convert bps to decimal

        return fees

    def simulate_fill(
        self,
        order: Order,
        current_price: float,
        market_data: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, float, float]:
        """Simulate order fill for paper trading.

        Args:
            order: Order to simulate
            current_price: Current market price
            market_data: Additional market data (optional)

        Returns:
            Tuple of (filled, fill_price, fees)
        """
        if not self.simulate and not self.sandbox_mode:
            # Real trading mode - would make actual exchange calls
            return False, 0.0, 0.0

        # Extract market data
        volatility = (
            market_data.get("volatility", self.volatility_factor)
            if market_data
            else self.volatility_factor
        )
        liquidity = (
            market_data.get("liquidity", self.liquidity_factor)
            if market_data
            else self.liquidity_factor
        )

        # Determine fill probability based on order type and market conditions
        fill_probability = self._calculate_fill_probability(
            order, current_price, volatility, liquidity
        )

        # Simulate fill
        filled = random.random() < fill_probability

        if not filled:
            return False, 0.0, 0.0

        # Calculate fill price with slippage
        fill_price = self._calculate_fill_price(order, current_price, volatility)

        # Calculate fees
        is_maker = order.order_type == OrderType.LIMIT and self._is_maker_order(
            order, current_price
        )
        fees = self.calculate_fees(
            order.quantity, fill_price, order.order_type, is_maker
        )

        return True, fill_price, fees

    def _calculate_fill_probability(
        self, order: Order, current_price: float, volatility: float, liquidity: float
    ) -> float:
        """Calculate fill probability based on order type and market conditions.

        Args:
            order: Order to evaluate
            current_price: Current market price
            volatility: Market volatility
            liquidity: Market liquidity

        Returns:
            Fill probability (0 to 1)
        """
        base_probability = liquidity

        if order.order_type == OrderType.MARKET:
            # Market orders have high fill probability
            return min(0.99, base_probability * 1.1)

        elif order.order_type == OrderType.LIMIT:
            # Limit orders depend on price vs current market
            if order.price is None:
                return 0.0

            price_ratio = order.price / current_price

            if order.side == OrderSide.BUY:
                # Buy limit: higher probability if price is above current
                if price_ratio >= 1.0:
                    return min(0.95, base_probability * 0.8)
                else:
                    # Below market - lower probability
                    return base_probability * (0.1 + 0.4 * price_ratio)
            else:
                # Sell limit: higher probability if price is below current
                if price_ratio <= 1.0:
                    return min(0.95, base_probability * 0.8)
                else:
                    # Above market - lower probability
                    return base_probability * (0.1 + 0.4 / price_ratio)

        elif order.order_type == OrderType.STOP:
            # Stop orders depend on stop price vs current price
            if order.stop_price is None:
                return 0.0

            if order.side == OrderSide.BUY:
                # Buy stop: triggers when price rises above stop
                if current_price >= order.stop_price:
                    return min(0.9, base_probability * 0.9)
                else:
                    return 0.0
            else:
                # Sell stop: triggers when price falls below stop
                if current_price <= order.stop_price:
                    return min(0.9, base_probability * 0.9)
                else:
                    return 0.0

        # Default probability
        return base_probability * 0.5

    def _calculate_fill_price(
        self, order: Order, current_price: float, volatility: float
    ) -> float:
        """Calculate fill price with slippage.

        Args:
            order: Order to evaluate
            current_price: Current market price
            volatility: Market volatility

        Returns:
            Fill price
        """
        if order.order_type == OrderType.MARKET:
            # Market orders have slippage
            slippage = random.uniform(0, self.slippage_bps / 10000)
            if order.side == OrderSide.BUY:
                return current_price * (1 + slippage)
            else:
                return current_price * (1 - slippage)

        elif order.order_type == OrderType.LIMIT:
            # Limit orders fill at order price (if favorable) or better
            if order.price is None:
                return current_price

            if order.side == OrderSide.BUY:
                # Buy limit: fill at order price or better (lower)
                return min(order.price, current_price * (1 - random.uniform(0, 0.001)))
            else:
                # Sell limit: fill at order price or better (higher)
                return max(order.price, current_price * (1 + random.uniform(0, 0.001)))

        elif order.order_type == OrderType.STOP:
            # Stop orders fill at market price when triggered
            slippage = random.uniform(0, self.slippage_bps / 10000)
            if order.side == OrderSide.BUY:
                return current_price * (1 + slippage)
            else:
                return current_price * (1 - slippage)

        # Default to current price
        return current_price

    def _is_maker_order(self, order: Order, current_price: float) -> bool:
        """Determine if order is a maker order.

        Args:
            order: Order to evaluate
            current_price: Current market price

        Returns:
            True if maker order, False if taker
        """
        if order.order_type != OrderType.LIMIT or order.price is None:
            return False

        if order.side == OrderSide.BUY:
            # Buy limit is maker if price is below current market
            return order.price < current_price
        else:
            # Sell limit is maker if price is above current market
            return order.price > current_price

    def execute_order(
        self,
        order: Order,
        current_price: float,
        market_data: Optional[dict[str, Any]] = None,
    ) -> Fill:
        """Execute an order and return fill information.

        Args:
            order: Order to execute
            current_price: Current market price
            market_data: Additional market data (optional)

        Returns:
            Fill information
        """
        # Simulate fill
        filled, fill_price, fees = self.simulate_fill(order, current_price, market_data)

        if filled:
            # Create fill
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=fill_price,
                fees=fees,
                timestamp=datetime.now(),
                strategy=order.strategy,
                metadata=order.metadata.copy(),
            )

            # Apply cash impact to session
            cash_success = self.apply_fill_cash_impact(fill)
            if not cash_success:
                self.logger.error(f"Failed to apply cash impact for order {order.id}")
                # Continue anyway - the fill happened, just log the error

            # Update order status
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.average_price = fill_price
            order.fees = fees

            # Store fill
            self.fills.append(fill)

            self.logger.info(
                f"Order {order.id} filled: {order.quantity} {order.symbol} @ {fill_price:.4f}"
            )

            return fill
        else:
            # Order not filled - check if it's due to exchange rejection
            # In live mode, this could be due to insufficient wallet balance
            if self.live_mode:
                notional = order.quantity * current_price
                session_cash = self.state_store.get_session_cash() if self.state_store else 0
                self.logger.info(f"⏭️ SKIP {order.symbol} reason=exchange_reject notional=${notional:.2f} cash=${session_cash:.2f}")
            
            # Order not filled
            order.status = OrderStatus.PENDING
            self.logger.debug(
                f"Order {order.id} not filled at current price {current_price:.4f}"
            )

            # Return empty fill
            return Fill(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                quantity=0.0,
                price=0.0,
                fees=0.0,
                timestamp=datetime.now(),
                strategy=order.strategy,
            )

    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get order status.

        Args:
            order_id: Order ID

        Returns:
            Order if found, None otherwise
        """
        return self.orders.get(order_id)

    def get_fills(self, order_id: Optional[str] = None) -> list[Fill]:
        """Get fills for an order or all fills.

        Args:
            order_id: Order ID (optional)

        Returns:
            List of fills
        """
        if order_id:
            return [fill for fill in self.fills if fill.order_id == order_id]
        return self.fills.copy()

    def get_order_summary(self) -> dict[str, Any]:
        """Get order manager summary.

        Returns:
            Order manager summary
        """
        total_orders = len(self.orders)
        filled_orders = len(
            [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        )
        total_fills = len(self.fills)
        total_fees = sum(fill.fees for fill in self.fills)

        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "pending_orders": total_orders - filled_orders,
            "total_fills": total_fills,
            "total_fees": total_fees,
            "simulation_mode": self.simulate,
            "sandbox_mode": self.sandbox_mode,
            "maker_fee_bps": self.maker_fee_bps,
            "taker_fee_bps": self.taker_fee_bps,
        }

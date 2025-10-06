"""
Order management system for cryptocurrency trading.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List, Dict
from decimal import Decimal

from ..core.logging_utils import LoggerMixin
from ..core.utils import get_mark_price, get_mark_price_with_provenance, validate_mark_price
from ..risk.risk_manager import ExitAction
from ..connectors import BaseConnector, FeeInfo
from .order_builder import OrderBuilder


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

    def __init__(self, config: Optional[dict[str, Any]] = None, session_id: Optional[str] = None):
        """Initialize the order manager.

        Args:
            config: Order management configuration (optional)
            session_id: Session identifier for state store operations (optional)
        """
        super().__init__()
        self.config = config or {}
        self.session_id = session_id
        self.initialized = False
        
        # Initialize stop model if risk config is available
        self.stop_model = None
        if "risk" in self.config:
            try:
                from crypto_mvp.risk.stop_models import StopModel
                from crypto_mvp.indicators.atr_service import ATRService
                
                # Create ATR service
                atr_config = self.config.get("risk", {}).get("sl_tp", {})
                atr_service = ATRService(atr_config)
                
                # Create stop model
                self.stop_model = StopModel(self.config, atr_service)
                self.logger.info("Stop model initialized with ATR service")
            except Exception as e:
                self.logger.warning(f"Failed to initialize stop model: {e}")
                self.stop_model = None

        # Fee configuration (in basis points)
        self.maker_fee_bps = self.config.get("maker_fee_bps", 10)
        
        # Cycle tracking
        self.cycle_id = None  # 0.1%
        self.taker_fee_bps = self.config.get("taker_fee_bps", 20)  # 0.2%
        
        # Connector for fee information
        self.connector: Optional[BaseConnector] = None

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
        # session_id is set via constructor or set_session_id method

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
        
        # Order builder for precision quantization
        self.order_builder = OrderBuilder()
    
    def set_connector(self, connector: BaseConnector) -> None:
        """Set the exchange connector for fee information.
        
        Args:
            connector: Exchange connector instance
        """
        self.connector = connector
        self.logger.info(f"Connector set to {connector.exchange_name}")
    
    def set_cycle_id(self, cycle_id: int) -> None:
        """Set the current cycle ID for price caching.
        
        Args:
            cycle_id: Current cycle ID
        """
        self.cycle_id = cycle_id
        self.logger.debug(f"OrderManager cycle_id set to {cycle_id}")
    
    def _validate_and_downgrade_order_type(self, order_type: OrderType, symbol: str) -> OrderType:
        """Validate order type against connector support and downgrade if necessary.
        
        Args:
            order_type: Requested order type
            symbol: Trading symbol
            
        Returns:
            Validated order type (possibly downgraded)
        """
        if not self.connector:
            # No connector available, use requested type
            return order_type
        
        try:
            supported_types = self.connector.get_supported_order_types()
            order_type_str = order_type.value.lower()
            
            # Check if the requested order type is supported
            if order_type_str in supported_types:
                return order_type
            
            # Order type not supported, try to downgrade
            downgrade_map = {
                OrderType.STOP_LIMIT: OrderType.LIMIT,    # Downgrade stop_limit to limit
                OrderType.STOP: OrderType.MARKET,         # Downgrade stop to market
                OrderType.TAKE_PROFIT: OrderType.LIMIT,   # Downgrade take_profit to limit
                OrderType.TAKE_PROFIT_LIMIT: OrderType.LIMIT,  # Downgrade take_profit_limit to limit
            }
            
            # Try downgrade
            if order_type in downgrade_map:
                downgraded = downgrade_map[order_type]
                downgraded_str = downgraded.value.lower()
                
                if downgraded_str in supported_types:
                    return downgraded
            
            # If no suitable downgrade found, fall back to market
            if "market" in supported_types:
                return OrderType.MARKET
            elif "limit" in supported_types:
                return OrderType.LIMIT
            else:
                # Last resort - return original type
                self.logger.error(f"No supported order types found for {symbol}, using requested type {order_type.value}")
                return order_type
                
        except Exception as e:
            self.logger.warning(f"Failed to validate order type for {symbol}: {e}, using requested type {order_type.value}")
            return order_type
        
        # Data engine for getting mark prices and ATR calculation (will be set by trading system)
        self.data_engine = None
        
        # State store for session cash management (will be set by trading system)
        self.state_store = None

    def calculate_target_notional(self, equity: float, entry_price: float, stop_price: float, cfg: dict[str, Any]) -> float:
        """Calculate target notional value based on risk-based sizing.
        
        Args:
            equity: Total equity available
            entry_price: Entry price for the trade
            stop_price: Stop loss price
            cfg: Configuration dictionary with sizing parameters
            
        Returns:
            Target notional value in dollars
        """
        # 1) Compute risk dollars
        base_risk_pct = self.config.get("execution", {}).get("risk_per_trade_pct", 0.01)
        
        # Check if risk-on mode is active
        risk_on_active = False
        if self.state_store and self.session_id and hasattr(self.state_store, 'get_session_metadata'):
            try:
                risk_on_active = self.state_store.get_session_metadata(
                    self.session_id, "risk_on_active", False
                )
            except AttributeError:
                risk_on_active = False
        
        if risk_on_active:
            risk_on_cfg = self.config.get("risk", {}).get("risk_on", {})
            base_risk_pct = risk_on_cfg.get("risk_per_trade_pct", base_risk_pct)
        
        risk_dollars = equity * base_risk_pct
        
        # 2) Compute stop_frac
        stop_frac = abs(entry_price - stop_price) / max(entry_price, 1e-12)
        if stop_frac < 1e-5:
            stop_frac = 1e-5  # Clamp to avoid infinite size
        
        # 3) Target notional
        target_notional = risk_dollars / stop_frac
        
        # Cap by per_symbol_cap_pct * equity and by session_cap_pct available room
        per_symbol_cap_pct = self.config.get("execution", {}).get("per_symbol_cap_pct", 0.15)
        per_symbol_cap = per_symbol_cap_pct * equity
        target_notional = min(target_notional, per_symbol_cap)
        
        # Check session cap available room
        if self.state_store and self.session_id:
            deployed_capital = self.state_store.get_session_deployed_capital(self.session_id)
            session_cap_pct = self.config.get("execution", {}).get("session_cap_pct", 0.60)
            session_cap = session_cap_pct * equity
            available_session_room = session_cap - deployed_capital
            target_notional = min(target_notional, max(0, available_session_room))
        
        # 4) Slicing logic
        min_slice = self.config.get("execution", {}).get("min_slice_notional", 25)
        default_slice = self.config.get("execution", {}).get("default_slice_notional", 50)
        max_slices = self.config.get("execution", {}).get("max_slices_per_order", 20)
        
        if target_notional < min_slice:
            # If target is smaller than min slice, take exactly 1 slice of min_slice
            target_notional = min_slice
            slices = 1
        else:
            # Calculate number of slices
            slices = int(target_notional / default_slice)
            if target_notional % default_slice > 0:
                slices += 1  # Round up
            slices = min(slices, max_slices)
        
        # Ensure first slice >= min_slice
        if slices == 1 and target_notional < min_slice:
            target_notional = min_slice
        
        # Logging
        self.logger.info(
            f"SIZER: entry=${entry_price:.4f}, stop=${stop_price:.4f}, stop_frac={stop_frac:.6f}, "
            f"risk$=${risk_dollars:.2f}, target_notional=${target_notional:.2f}, slices={slices}x${default_slice:.2f}"
        )
        
        return float(max(0.0, target_notional))

    def preflight_entry_check(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_price: Optional[float],
        tp_price: Optional[float],
        account_mode: str,
        symbol_info: Optional[dict[str, Any]] = None,
        position_qty: float = 0.0
    ) -> tuple[bool, str, Decimal, Decimal, Decimal, Decimal]:
        """Preflight entry validation with venue, SL/TP, and sizing checks.
        
        Args:
            symbol: Trading symbol
            side: Order side ("BUY" or "SELL")
            entry_price: Entry price
            stop_price: Stop loss price
            tp_price: Take profit price
            account_mode: Account mode ("spot" or "margin")
            symbol_info: Symbol information dict with tick_size, step_size, min_notional, supports_short
            position_qty: Current position quantity
            
        Returns:
            Tuple of (ok: bool, reason: str, adj_qty: Decimal, adj_price: Decimal, adj_stop: Decimal, adj_tp: Decimal)
        """
        # Default symbol info if not provided
        if symbol_info is None:
            symbol_info = self._get_default_symbol_info(symbol)
        
        # 1. Venue shorting gate - check global and symbol-specific short settings
        if side.upper() == "SELL" and position_qty == 0:
            # Check global short enabled setting
            global_short_enabled = self.config.get("risk", {}).get("short_enabled", False)
            
            # Check symbol-specific allow_short setting
            symbol_allow_short = self.config.get("symbols", {}).get(symbol, {}).get("allow_short", False)
            
            # Both global and symbol-specific settings must allow shorting
            if not (global_short_enabled and symbol_allow_short):
                if account_mode == "spot":
                    return False, "SELL on spot from flat not allowed (shorts disabled)", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
                else:  # margin
                    return False, "SELL from flat not allowed (shorts disabled)", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
            
            # Additional check for symbol technical support
            if not symbol_info.get("supports_short", False):
                return False, "Symbol does not support shorting", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
        
        # 2. Entry/SL validity
        if entry_price <= 0:
            return False, "Invalid entry price", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
        
        if stop_price is None or stop_price <= 0:
            return False, "Stop price required and must be > 0", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
        
        if stop_price == entry_price:
            return False, "Stop price cannot equal entry price", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
        
        # Compute stop fraction
        stop_frac = abs(entry_price - stop_price) / entry_price
        min_stop_frac = self.config.get("risk", {}).get("min_stop_frac", 0.001)  # Default 0.1%
        
        if stop_frac < min_stop_frac:
            return False, f"invalid stop distance (stop_frac={stop_frac:.4f})", Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
        
        # 3. Quantization
        tick_size = symbol_info.get("tick_size", 0.01)
        step_size = symbol_info.get("step_size", 0.001)
        
        # Round prices to tick size
        adj_price = Decimal(str(round(entry_price / tick_size) * tick_size))
        adj_stop = Decimal(str(round(stop_price / tick_size) * tick_size))
        adj_tp = Decimal(str(round(tp_price / tick_size) * tick_size)) if tp_price else Decimal('0')
        
        # 4. Min notional check (will be computed with target qty later)
        min_notional = symbol_info.get("min_notional", 10.0)
        
        # 5. Reduce-only sanity check
        # This is handled in the calling code - entries should never have reduce_only=True
        
        # Return success with adjusted values
        return True, "", Decimal('0'), adj_price, adj_stop, adj_tp

    def _get_default_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Get default symbol information for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with symbol information
        """
        # Default symbol info mapping
        symbol_info_map = {
            "BTC/USDT": {
                "tick_size": 0.01,
                "step_size": 0.001,
                "min_notional": 10.0,
                "supports_short": True
            },
            "ETH/USDT": {
                "tick_size": 0.01,
                "step_size": 0.001,
                "min_notional": 10.0,
                "supports_short": True
            },
            "BNB/USDT": {
                "tick_size": 0.01,
                "step_size": 0.001,
                "min_notional": 10.0,
                "supports_short": True
            },
            "ADA/USDT": {
                "tick_size": 0.0001,
                "step_size": 0.1,
                "min_notional": 10.0,
                "supports_short": True
            },
            "SOL/USDT": {
                "tick_size": 0.01,
                "step_size": 0.001,
                "min_notional": 10.0,
                "supports_short": True
            }
        }
        
        return symbol_info_map.get(symbol, {
            "tick_size": 0.01,
            "step_size": 0.001,
            "min_notional": 10.0,
            "supports_short": True
        })

    def execute_by_slices(
        self,
        symbol: str,
        side: OrderSide,
        target_notional: float,
        current_price: float,
        strategy: str = "unknown",
        is_pilot: bool = False,
        cfg: dict[str, Any] = None,
        gate_info: dict[str, Any] = None,
        stop_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        account_mode: str = "spot"
    ) -> dict[str, Any]:
        """Execute order by slices with caps and limits.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            target_notional: Target notional value
            current_price: Current market price
            strategy: Strategy name
            is_pilot: Whether this is a pilot trade
            cfg: Configuration dictionary
            gate_info: Gate information for telemetry (base, effective, score)
            stop_price: Stop loss price for preflight validation
            tp_price: Take profit price for preflight validation
            account_mode: Account mode ("spot" or "margin")
            
        Returns:
            Dictionary with execution results
        """
        if cfg is None:
            cfg = self.config.get("risk", {}).get("sizing", {})
        
        # Preflight entry validation
        if stop_price is not None:
            # Get current position quantity (simplified - in real implementation this would come from portfolio)
            position_qty = 0.0  # TODO: Get actual position quantity from portfolio
            
            # Get symbol info
            symbol_info = self._get_default_symbol_info(symbol)
            
            # Run preflight check
            ok, reason, adj_qty, adj_price, adj_stop, adj_tp = self.preflight_entry_check(
                symbol=symbol,
                side=side.value,
                entry_price=current_price,
                stop_price=stop_price,
                tp_price=tp_price,
                account_mode=account_mode,
                symbol_info=symbol_info,
                position_qty=position_qty
            )
            
            if not ok:
                tp_str = f"{tp_price:.4f}" if tp_price else "None"
                self.logger.info(f"PRECHECK FAIL {symbol} {side.value}: {reason} (entry={current_price:.4f}, stop={stop_price:.4f}, tp={tp_str})")
                return {
                    "executed_notional": 0.0,
                    "slices_executed": 0,
                    "successful_orders": [],
                    "target_notional": target_notional,
                    "execution_ratio": 0.0,
                    "precheck_failed": True,
                    "precheck_reason": reason
                }
            
            # Use adjusted prices if preflight passed
            current_price = float(adj_price)
            stop_price = float(adj_stop)
            if tp_price:
                tp_price = float(adj_tp)
        else:
            # No stop price provided, skipping preflight
            self.logger.debug(f"No stop price provided for {symbol}, skipping preflight validation")
            
        # Use new execution config parameters
        min_slice = self.config.get("execution", {}).get("min_slice_notional", 25)
        default_slice = self.config.get("execution", {}).get("default_slice_notional", 50)
        max_slices = self.config.get("execution", {}).get("max_slices_per_order", 20)
        per_symbol_cap_pct = self.config.get("execution", {}).get("per_symbol_cap_pct", 0.15)
        session_cap_pct = self.config.get("execution", {}).get("session_cap_pct", 0.60)
        
        # Get current equity and deployed amount
        if self.state_store and self.session_id:
            equity = self.state_store.get_session_equity(self.session_id)
            deployed_capital = self.state_store.get_session_deployed_capital(self.session_id)
        else:
            equity = 10000.0  # Fallback
            deployed_capital = 0.0  # Fallback
        
        # Calculate caps
        per_symbol_cap = per_symbol_cap_pct * equity
        session_cap = session_cap_pct * equity
        
        # Calculate planned slices based on new logic
        if target_notional < min_slice:
            planned_slices = 1
        else:
            planned_slices = int(target_notional / default_slice)
            if target_notional % default_slice > 0:
                planned_slices += 1  # Round up
            planned_slices = min(planned_slices, max_slices)
        
        self.logger.info(
            f"SLICER: target_notional=${target_notional:.2f}, min_slice=${min_slice:.2f}, "
            f"default_slice=${default_slice:.2f}, planned_slices={planned_slices}, "
            f"per_symbol_cap=${per_symbol_cap:.2f}, session_cap=${session_cap:.2f}"
        )
        
        executed = 0.0
        slices = 0
        successful_orders = []
        
        while executed < target_notional and slices < max_slices:
            # Determine slice size
            remaining = target_notional - executed
            
            # Use default_slice size, but ensure first slice meets min_slice requirement
            if slices == 0 and remaining < min_slice:
                slice_notional = min_slice
            else:
                slice_notional = min(default_slice, remaining)
            
            # Check per-symbol cap
            if executed + slice_notional > per_symbol_cap:
                self.logger.info(
                    f"SLICING HALT: {symbol} reason=per_symbol_cap (executed=${executed:.2f} + ${slice_notional:.2f} > cap=${per_symbol_cap:.2f})"
                )
                break
                
            # Check session cap
            available_session_room = session_cap - deployed_capital
            if slice_notional > available_session_room:
                self.logger.info(
                    f"SLICING HALT: {symbol} reason=session_cap (slice=${slice_notional:.2f} > available_room=${available_session_room:.2f})"
                )
                break
                
            # Create slice order
            slice_quantity = slice_notional / current_price
            
            # Create order for this slice
            order, error_reason = self.create_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=slice_quantity,
                strategy=strategy,
                metadata={
                    "slice": True,
                    "slice_number": slices + 1,
                    "is_pilot": is_pilot,
                    "reduce_only": False  # Entries should never be reduce-only
                }
            )
            
            if order:
                # Simulate order execution (in real implementation, this would be actual order placement)
                success = self._simulate_order_execution(order, current_price)
                
                if success:
                    executed += slice_notional
                    slices += 1
                    successful_orders.append(order)
                    self.logger.debug(f"Slice {slices} executed: ${slice_notional:.2f} notional")
                else:
                    self.logger.warning(f"Slice {slices + 1} failed, stopping execution")
                    break
            else:
                # Enhanced error handling with root cause analysis and safe fallback
                self._handle_slice_creation_failure(
                    symbol, side, slice_quantity, current_price, slice_notional, 
                    error_reason, slices + 1, executed, target_notional
                )
                break
        
        # Calculate stop fraction for telemetry
        stop_frac = 0.02  # Default 2% stop (will be calculated properly in real implementation)
        
        # Prepare gate information for telemetry
        gate_info = gate_info or {}
        base_gate = gate_info.get("base_gate", 0.65)
        effective_gate = gate_info.get("effective_gate", 0.65)
        score = gate_info.get("score", 0.0)
        
        # Calculate session cap percentage and used amount
        session_cap_pct = session_cap * 100  # Convert to percentage
        session_cap_amount = session_cap * equity
        
        # Emit ALLOC telemetry log
        self.logger.info(
            f"ALLOC: {symbol} target=${target_notional:.2f} executed=${executed:.2f} slices={slices} "
            f"min_slice=${min_slice:.2f} caps={{per_symbol:${per_symbol_cap:.2f}, session:{{max_pct:{session_cap_pct:.0f}%, used:${deployed_capital:.2f}}}}} "
            f"stop_frac={stop_frac:.3f} gate={{base:{base_gate:.2f}, eff:{effective_gate:.2f}, score:{score:.3f}}}"
        )
                
        return {
            "executed_notional": executed,
            "slices_executed": slices,
            "successful_orders": successful_orders,
            "target_notional": target_notional,
            "execution_ratio": executed / target_notional if target_notional > 0 else 0.0
        }

    def _simulate_order_execution(self, order: Order, current_price: float) -> bool:
        """Simulate order execution for testing purposes.
        
        Args:
            order: Order to execute
            current_price: Current market price
            
        Returns:
            True if execution successful, False otherwise
        """
        # In real implementation, this would place actual orders
        # For now, simulate with high success rate
        import random
        success_rate = 0.95  # 95% success rate
        return random.random() < success_rate

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
        self.session_id = session_id
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
            Order price rounded to tick size or None if no valid price available
        """
        # Get symbol info for tick size
        symbol_info = self._get_default_symbol_info(symbol)
        tick_size = symbol_info.get("tick_size", 0.01)
        
        # If explicit price provided, validate and round it
        if price is not None:
            if price > 0 and validate_mark_price(price, symbol):
                # Round to tick size using proper decimal arithmetic
                from decimal import Decimal, ROUND_HALF_UP
                price_decimal = Decimal(str(price))
                tick_decimal = Decimal(str(tick_size))
                rounded_price = float((price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick_decimal)
                return rounded_price
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
                live_mode=self.live_mode,
                cycle_id=getattr(self, 'cycle_id', None)
            )
            
            if mark_price and validate_mark_price(mark_price, symbol):
                # Round to tick size using proper decimal arithmetic
                from decimal import Decimal, ROUND_HALF_UP
                price_decimal = Decimal(str(mark_price))
                tick_decimal = Decimal(str(tick_size))
                rounded_price = float((price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick_decimal)
                return rounded_price
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
                live_mode=self.live_mode,
                cycle_id=getattr(self, 'cycle_id', None)
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
        # Use order builder for precision quantization
        target_notional = quantity * price
        
        # Get symbol rules from connector if available
        symbol_rules = self._get_symbol_rules(symbol)
        
        # Build quantized order
        order_data, error_reason = self.order_builder.build_order(
            symbol=symbol,
            raw_price=price,
            target_notional=target_notional,
            symbol_rules=symbol_rules,
            max_retries=1
        )
        
        if order_data is None:
            # Order builder failed
            if "precision" in error_reason.lower():
                return False, 0.0, "precision_fail"
            else:
                return False, 0.0, error_reason
        
        # Use quantized quantity from order builder
        quantity = order_data["quantity"]
        
        if not self.state_store:
            self.logger.warning("No state store available for budget checking")
            return True, quantity, ""
        
        # Get current session cash
        if not self.session_id:
            self.logger.warning("No session_id available for budget checking")
            return True, quantity, ""
        
        session_cash = self.state_store.get_session_cash(self.session_id)
        
        # Calculate notional value with rounded quantity
        notional = quantity * price
        
        # Check minimum notional (typically $10-20 for most exchanges)
        min_notional = 10.0  # Minimum notional value
        if notional < min_notional:
            self.logger.info(f"⏭️ SKIP {symbol} reason=min_notional notional=${notional:.2f} cash=${session_cash:.2f}")
            return False, 0.0, "min_notional"
        
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
    
    def _get_symbol_rules(self, symbol: str) -> Dict[str, Any]:
        """Get symbol trading rules for precision requirements.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Symbol rules dictionary
        """
        # Try to get rules from connector if available
        if self.connector and hasattr(self.connector, 'get_symbol_rules'):
            try:
                return self.connector.get_symbol_rules(symbol)
            except Exception as e:
                self.logger.warning(f"Failed to get symbol rules from connector for {symbol}: {e}")
        
        # Fall back to default rules
        return self._get_default_symbol_info(symbol)

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
        
        if not self.session_id:
            raise RuntimeError("session_id not set - cannot process cash operations without valid session")

        if fill.side == OrderSide.BUY:
            # Debit cash for buy orders
            success = self.state_store.debit_cash(self.session_id, notional, fill.fees)
            if not success:
                self.logger.error(f"Failed to debit cash for buy order: {fill.order_id}")
                return False
        else:
            # Credit cash for sell orders
            success = self.state_store.credit_cash(self.session_id, notional, fill.fees)
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
    ) -> tuple[Optional[Order], Optional[str]]:
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
            Tuple of (order, error_reason) where:
            - order: Created order or None if validation fails
            - error_reason: None if successful, or "REASON_CODE: human-readable message" if failed
        """
        if not self.initialized:
            self.initialize()

        # Check data provenance before allowing order creation
        if self.data_engine:
            try:
                _, provenance = get_mark_price_with_provenance(symbol, self.data_engine, self.live_mode)
                if provenance not in ["live"]:
                    self.logger.warning(f"🚫 BLOCKED ORDER: {symbol} - data provenance is '{provenance}', not 'live'")
                    return None, f"PROVENANCE_BLOCKED: Order blocked - data source is '{provenance}', only 'live' data allowed for trading"
            except Exception as e:
                self.logger.warning(f"Failed to check provenance for {symbol}: {e}")
                return None, f"PROVENANCE_CHECK_FAILED: Could not verify data provenance: {e}"

        # Validate order type against connector support
        validated_order_type = self._validate_and_downgrade_order_type(order_type, symbol)
        if validated_order_type != order_type:
            self.logger.warning(f"ORDER_TYPE_DOWNGRADE: {symbol} - {order_type.value} not supported, downgraded to {validated_order_type.value}")
        
        # Get validated price for the order
        validated_price = self.get_order_price(symbol, validated_order_type, price)
        
        if validated_price is None:
            # Determine specific price validation failure reason
            if price is not None and price <= 0:
                return None, "INVALID_PRICE: Price must be greater than 0"
            elif price is not None and not validate_mark_price(price, symbol):
                return None, "PRICE_OUT_OF_RANGE: Price is outside valid range for symbol"
            elif validated_order_type == OrderType.MARKET and not self.data_engine:
                return None, "NO_DATA_ENGINE: Data engine required for market orders"
            elif validated_order_type == OrderType.MARKET:
                return None, "STALE_PRICE: Market price is stale or unavailable"
            elif validated_order_type == OrderType.LIMIT and price is None:
                return None, "NO_PRICE: Limit orders require explicit price"
            else:
                return None, "PRICE_VALIDATION_FAILED: Price validation failed"

        # Check budget constraints and adjust quantity if necessary
        can_proceed, adjusted_quantity, skip_reason = self.check_budget_constraints(
            symbol, side, quantity, validated_price
        )
        
        if not can_proceed:
            # Convert skip reason to structured error message
            if skip_reason == "min_notional":
                return None, "MIN_NOTIONAL: Order value below minimum notional requirement"
            elif skip_reason == "precision_fail":
                return None, "PRECISION_FAIL: Quantity precision does not meet symbol requirements"
            elif skip_reason == "budget_exhausted":
                return None, "BUDGET_EXHAUSTED: Insufficient cash for order"
            else:
                return None, f"BUDGET_CONSTRAINT: {skip_reason}"
        
        # Use adjusted quantity
        quantity = adjusted_quantity

        # Additional validations
        # Check for reduce-only mismatch (entries should never be reduce-only, but exits can be)
        if metadata and metadata.get("reduce_only", False):
            # Allow reduce-only for exit orders (TP ladders, stop losses, etc.)
            if strategy in ["tp_ladder", "stop_loss", "take_profit"] or metadata.get("tp_ladder", False):
                pass  # Allow reduce-only for exit orders
            else:
                return None, "REDUCE_ONLY_MISMATCH: Entry orders cannot be reduce-only"

        # Check quantity validation
        if quantity <= 0:
            return None, "INVALID_QUANTITY: Quantity must be greater than 0"

        # Check symbol info for tick/step validation
        symbol_info = self._get_default_symbol_info(symbol)
        tick_size = symbol_info.get("tick_size", 0.01)
        step_size = symbol_info.get("step_size", 0.001)
        
        # Round quantity to step size using proper decimal arithmetic
        from decimal import Decimal, ROUND_HALF_UP
        quantity_decimal = Decimal(str(quantity))
        step_decimal = Decimal(str(step_size))
        rounded_quantity = float((quantity_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * step_decimal)
        
        # Ensure rounded quantity is still positive
        if rounded_quantity <= 0:
            return None, "INVALID_QUANTITY: Rounded quantity must be greater than 0"
        
        # Validate price tick size (should already be rounded by get_order_price)
        # Use tolerance-based comparison to handle floating-point precision issues
        price_remainder = abs(validated_price % tick_size)
        if price_remainder > 1e-10 and abs(price_remainder - tick_size) > 1e-10:
            return None, f"TICK_SIZE_FAIL: Price {validated_price} not aligned with tick size {tick_size}"
        
        # Validate quantity step size (should already be rounded)
        # Use tolerance-based comparison to handle floating-point precision issues
        quantity_remainder = abs(rounded_quantity % step_size)
        if quantity_remainder > 1e-10 and abs(quantity_remainder - step_size) > 1e-10:
            return None, f"STEP_SIZE_FAIL: Quantity {rounded_quantity} not aligned with step size {step_size}"

        # Generate unique order ID
        self.order_counter += 1
        order_id = f"order_{self.order_counter}_{int(datetime.now().timestamp())}"

        # Extract time_in_force from metadata if provided
        time_in_force = "GTC"  # Default
        if metadata and "time_in_force" in metadata:
            time_in_force = metadata["time_in_force"]

        # Create order with validated price and rounded quantity
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=validated_order_type,
            quantity=rounded_quantity,
            price=validated_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            strategy=strategy,
            metadata=metadata or {},
        )

        # Store order
        self.orders[order_id] = order

        self.logger.debug(
            f"Created order {order_id}: {side.value} {quantity} {symbol} @ {validated_price}"
        )

        return order, None

    def submit_order(self, order_id: str) -> bool:
        """Submit an order for execution.
        
        Args:
            order_id: Order ID to submit
            
        Returns:
            True if order was submitted successfully, False otherwise
        """
        if order_id not in self.orders:
            self.logger.error(f"Order {order_id} not found")
            return False
        
        order = self.orders[order_id]
        
        # In simulation mode, immediately execute the order
        if self.simulate:
            try:
                # Get current market price for execution
                if self.data_engine:
                    current_price = self.data_engine.get_ticker(order.symbol).get('price', order.price)
                else:
                    current_price = order.price
                
                # Execute the order
                fill = self.execute_order(order, current_price)
                
                if fill.quantity > 0:
                    self.logger.info(f"Order {order_id} submitted and filled: {fill.quantity} @ {fill.price}")
                    return True
                else:
                    self.logger.warning(f"Order {order_id} submitted but not filled")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Failed to execute order {order_id}: {e}")
                return False
        else:
            # In live mode, submit to exchange (placeholder for now)
            self.logger.info(f"Order {order_id} submitted to exchange (live mode)")
            return True

    def calculate_fees(
        self,
        quantity: float,
        price: float,
        order_type: OrderType,
        symbol: str,
        is_maker: bool = False,
    ) -> float:
        """Calculate trading fees using connector information.

        Args:
            quantity: Order quantity
            price: Order price
            order_type: Order type
            symbol: Trading symbol
            is_maker: Whether this is a maker order

        Returns:
            Calculated fees
        """
        # Try to get fee information from connector first
        if self.connector:
            try:
                fee_type = "maker" if is_maker or order_type == OrderType.LIMIT else "taker"
                fee_info = self.connector.get_fee_info(symbol, fee_type)
                
                # Use connector fee information
                fee_bps = fee_info.maker_fee_bps if is_maker else fee_info.taker_fee_bps
                self.logger.debug(f"Using connector fees for {symbol}: {fee_type}={fee_bps}bps")
                
            except Exception as e:
                self.logger.warning(f"Failed to get fee info from connector for {symbol}: {e}, using defaults")
                # Fall back to default fees
                fee_bps = self.maker_fee_bps if is_maker or order_type == OrderType.LIMIT else self.taker_fee_bps
        else:
            # Use default fee configuration
            fee_bps = self.maker_fee_bps if is_maker or order_type == OrderType.LIMIT else self.taker_fee_bps

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
            order.quantity, fill_price, order.order_type, order.symbol, is_maker
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
                session_cash = self.state_store.get_session_cash(self.session_id) if self.state_store and self.session_id else 0
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

    def auto_manage_exits(
        self, 
        portfolio: dict[str, Any], 
        risk_manager, 
        marks: dict[str, float]
    ) -> List[Order]:
        """Automatically manage exit orders based on risk manager suggestions.
        
        Args:
            portfolio: Portfolio dictionary with positions
            risk_manager: Risk manager instance with build_exit_actions method
            marks: Current market prices for symbols
            
        Returns:
            List of exit orders created
        """
        exit_orders = []
        
        try:
            # Get exit actions from risk manager
            exit_actions = risk_manager.build_exit_actions(portfolio, marks)
            
            if not exit_actions:
                self.logger.debug("No exit actions suggested by risk manager")
                return exit_orders
            
            self.logger.info(f"Processing {len(exit_actions)} exit actions from risk manager")
            
            for action in exit_actions:
                try:
                    # Determine order side based on position quantity
                    position = portfolio.get("positions", {}).get(action.symbol, {})
                    net_qty = position.get("quantity", 0)
                    
                    if net_qty > 0:
                        # Long position - need to sell to exit
                        side = OrderSide.SELL
                    elif net_qty < 0:
                        # Short position - need to buy to exit
                        side = OrderSide.BUY
                    else:
                        # No position - skip
                        self.logger.warning(f"No position found for {action.symbol}, skipping exit action")
                        continue
                    
                    # Get current price for the symbol
                    current_price = marks.get(action.symbol)
                    if not current_price or current_price <= 0:
                        self.logger.warning(f"No valid price for {action.symbol}, skipping exit action")
                        continue
                    
                    # Round price to tick size (simplified - assume 0.01 tick size for most crypto pairs)
                    tick_size = self._get_tick_size(action.symbol)
                    rounded_price = self._round_to_tick(action.price_hint or current_price, tick_size)
                    
                    # Create reduce-only IOC limit order
                    order, error_reason = self.create_order(
                        symbol=action.symbol,
                        side=side,
                        order_type=OrderType.LIMIT,
                        quantity=action.qty,
                        price=rounded_price,
                        strategy="exit_management",
                        metadata={
                            "reason": action.reason,
                            "reduce_only": True,
                            "time_in_force": "IOC",  # Immediate or Cancel
                            "exit_action": True
                        }
                    )
                    
                    if order:
                        exit_orders.append(order)
                        self.logger.info(
                            f"Created exit order {order.id}: {side.value} {action.qty} {action.symbol} @ {rounded_price:.6f} ({action.reason})"
                        )
                    else:
                        self.logger.warning(f"Failed to create exit order for {action.symbol}: {error_reason}")
                        
                except Exception as e:
                    self.logger.error(f"Error processing exit action for {action.symbol}: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error in auto_manage_exits: {e}")
            
        return exit_orders
    
    def _get_tick_size(self, symbol: str) -> float:
        """Get tick size for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Tick size for the symbol
        """
        # Simplified tick size mapping - in real implementation, this would come from exchange API
        tick_sizes = {
            "BTC/USDT": 0.01,
            "ETH/USDT": 0.01,
            "BNB/USDT": 0.01,
            "ADA/USDT": 0.0001,
            "SOL/USDT": 0.01,
        }
        
        # Default tick size
        return tick_sizes.get(symbol, 0.01)
    
    def _round_to_tick(self, price: float, tick_size: float) -> float:
        """Round price to tick size.
        
        Args:
            price: Price to round
            tick_size: Tick size
            
        Returns:
            Rounded price
        """
        if tick_size <= 0:
            return price
            
        return round(price / tick_size) * tick_size

    def _coerce_to_float(self, value: Any, field_name: str, default: float) -> Optional[float]:
        """Coerce a value to float with robust type handling.
        
        Args:
            value: Value to coerce (can be string, int, float, etc.)
            field_name: Name of the field for logging
            default: Default value if coercion fails
            
        Returns:
            Coerced float value or None if coercion fails
        """
        try:
            if value is None:
                return default
                
            # Already a float
            if isinstance(value, (int, float)):
                return float(value)
            
            # String handling
            if isinstance(value, str):
                value = value.strip()
                
                # Handle percentage strings (e.g., "5%", "0.5%")
                if value.endswith('%'):
                    percent_str = value[:-1]
                    percent_val = float(percent_str)
                    return percent_val / 100.0  # Convert percentage to fraction
                
                # Handle regular numeric strings
                return float(value)
            
            # Try direct conversion
            return float(value)
            
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Failed to coerce {field_name}='{value}' to float: {e}, using default {default}")
            return default

    def create_tp_ladder_orders(
        self,
        symbol: str,
        position_size: float,
        avg_cost: float,
        current_price: float,
        risk_manager,
        config: dict[str, Any]
    ) -> List[Order]:
        """Create take-profit ladder orders after entry fill.
        
        Args:
            symbol: Trading symbol
            position_size: Current position size (signed)
            avg_cost: Average cost of position
            current_price: Current market price
            risk_manager: Risk manager instance for ATR access
            config: Configuration dictionary
            
        Returns:
            List of TP ladder orders created
        """
        tp_orders = []
        
        try:
            # Get TP ladder configuration
            exit_cfg = config.get("risk", {}).get("exits", {})
            tp_ladders = exit_cfg.get("tp_ladders", [])
            min_qty_raw = exit_cfg.get("min_qty", 1e-9)
            
            # Type validation and coercion for min_qty
            min_qty = self._coerce_to_float(min_qty_raw, "min_qty", 1e-9)
            
            if not tp_ladders:
                self.logger.debug(f"No TP ladders configured for {symbol}")
                return tp_orders
            
            # Skip if position size is below minimum
            if abs(position_size) <= min_qty:
                self.logger.debug(f"Position size {position_size} below min_qty {min_qty}, skipping TP ladders")
                return tp_orders
            
            # Determine position side
            is_long = position_size > 0
            
            # Get 1R (risk unit) - try to get from strategy first, fallback to ATR
            one_r = self._get_risk_unit(symbol, avg_cost, risk_manager)
            
            if one_r <= 0:
                self.logger.warning(f"Could not determine 1R for {symbol}, skipping TP ladders")
                return tp_orders
            
            self.logger.info(f"Creating TP ladders for {symbol}: position={position_size:.6f}, avg_cost={avg_cost:.6f}, 1R={one_r:.6f}")
            
            # Create TP ladder orders
            for ladder in tp_ladders:
                # Initialize variables for error logging
                r_mult = None
                profit_pct = None
                
                try:
                    # Type validation and coercion for ladder values
                    # Support both old R-multiple format and new percentage format
                    r_mult_raw = ladder.get("r_mult", None)
                    profit_pct_raw = ladder.get("profit_pct", None)
                    pct_raw = ladder.get("pct", 0.25)
                    
                    pct = self._coerce_to_float(pct_raw, "pct", 0.25)
                    
                    # Skip this ladder if pct coercion failed
                    if pct is None:
                        self.logger.warning(f"Skipping TP ladder due to invalid pct value: {pct_raw}")
                        continue
                    
                    # Calculate target price based on format
                    if profit_pct_raw is not None:
                        # New percentage-based format: profit_pct is percentage profit from entry
                        profit_pct = self._coerce_to_float(profit_pct_raw, "profit_pct", 1.0)
                        if profit_pct is None:
                            self.logger.warning(f"Skipping TP ladder due to invalid profit_pct value: {profit_pct_raw}")
                            continue
                        
                        if is_long:
                            # LONG: target = avg_cost * (1 + profit_pct/100)
                            target_price = avg_cost * (1 + profit_pct / 100)
                            side = OrderSide.SELL
                        else:
                            # SHORT: target = avg_cost * (1 - profit_pct/100)
                            target_price = avg_cost * (1 - profit_pct / 100)
                            side = OrderSide.BUY
                    else:
                        # Legacy R-multiple format
                        r_mult = self._coerce_to_float(r_mult_raw, "r_mult", 1.0)
                        if r_mult is None:
                            self.logger.warning(f"Skipping TP ladder due to invalid r_mult value: {r_mult_raw}")
                            continue
                        
                        if is_long:
                            # LONG: target = avg_cost + r_mult * 1R
                            target_price = avg_cost + (r_mult * one_r)
                            side = OrderSide.SELL
                        else:
                            # SHORT: target = avg_cost - r_mult * 1R
                            target_price = avg_cost - (r_mult * one_r)
                            side = OrderSide.BUY
                    
                    # Round to tick size
                    tick_size = self._get_tick_size(symbol)
                    rounded_target = self._round_to_tick(target_price, tick_size)
                    
                    # Calculate quantity for this ladder
                    ladder_qty = abs(position_size) * pct
                    
                    # Skip if quantity is too small
                    if ladder_qty <= min_qty:
                        self.logger.debug(f"Ladder quantity {ladder_qty} below min_qty {min_qty}, skipping")
                        continue
                    
                    # Create GTC reduce-only limit order
                    order, error_reason = self.create_order(
                        symbol=symbol,
                        side=side,
                        order_type=OrderType.LIMIT,
                        quantity=ladder_qty,
                        price=rounded_target,
                        strategy="tp_ladder",
                        metadata={
                            "reason": f"tp_{r_mult}R_{pct*100:.0f}pct",
                            "reduce_only": True,
                            "time_in_force": "GTC",
                            "tp_ladder": True,
                            "r_mult": r_mult,
                            "pct": pct
                        }
                    )
                    
                    if order:
                        tp_orders.append(order)
                        # Format logging based on whether we used percentage or R-multiple
                        if profit_pct_raw is not None:
                            self.logger.info(
                                f"Created TP ladder order {order.id}: {side.value} {ladder_qty:.6f} {symbol} @ {rounded_target:.6f} (+{profit_pct:.1f}%, {pct*100:.0f}%)"
                            )
                        else:
                            self.logger.info(
                                f"Created TP ladder order {order.id}: {side.value} {ladder_qty:.6f} {symbol} @ {rounded_target:.6f} ({r_mult}R, {pct*100:.0f}%)"
                            )
                    else:
                        # Format error logging based on format used
                        if profit_pct_raw is not None:
                            self.logger.warning(f"Failed to create TP ladder order for {symbol} at +{profit_pct:.1f}%: {error_reason}")
                        else:
                            self.logger.warning(f"Failed to create TP ladder order for {symbol} at {r_mult}R: {error_reason}")
                        
                except Exception as e:
                    # Format error logging based on format used
                    if profit_pct_raw is not None:
                        self.logger.error(f"Error creating TP ladder for {symbol} at +{profit_pct:.1f}%: {e}")
                    else:
                        self.logger.error(f"Error creating TP ladder for {symbol} at {r_mult}R: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error in create_tp_ladder_orders for {symbol}: {e}")
            
        return tp_orders
    
    def _handle_slice_creation_failure(
        self,
        symbol: str,
        side: OrderSide,
        slice_quantity: float,
        current_price: float,
        slice_notional: float,
        error_reason: str,
        slice_number: int,
        executed: float,
        target_notional: float
    ) -> None:
        """Handle slice creation failure with root cause analysis and safe fallback.
        
        Args:
            symbol: Trading symbol
            side: Order side
            slice_quantity: Failed slice quantity
            current_price: Current market price
            slice_notional: Failed slice notional value
            error_reason: Error reason from create_order
            slice_number: Current slice number
            executed: Already executed notional
            target_notional: Target notional value
        """
        # Parse error reason to determine root cause
        error_type = self._parse_error_type(error_reason)
        
        # Log root cause analysis
        self.logger.warning(
            f"FAILED SLICE {slice_number} {symbol} {side.value}: {error_reason} "
            f"(qty={slice_quantity:.6f}, price={current_price:.4f}, notional=${slice_notional:.2f})"
        )
        
        # Attempt safe fallback for recoverable errors
        if error_type in ["MIN_NOTIONAL", "PRECISION_FAIL", "INVALID_QUANTITY"]:
            self._attempt_slice_fallback(
                symbol, side, slice_quantity, current_price, slice_notional, 
                error_type, slice_number, executed, target_notional
            )
        else:
            # Non-recoverable error - abort cleanly
            self.logger.warning(
                f"SLICING ABORT: {symbol} {side.value} - Non-recoverable error: {error_type} "
                f"(executed=${executed:.2f}/{target_notional:.2f}, {slice_number-1} slices completed)"
            )
    
    def _parse_error_type(self, error_reason: str) -> str:
        """Parse error reason to determine error type.
        
        Args:
            error_reason: Error reason string from create_order
            
        Returns:
            Error type string
        """
        if not error_reason:
            return "UNKNOWN"
        
        # Extract error type from structured error messages
        if ":" in error_reason:
            error_type = error_reason.split(":")[0]
        else:
            error_type = error_reason
        
        return error_type
    
    def _attempt_slice_fallback(
        self,
        symbol: str,
        side: OrderSide,
        original_quantity: float,
        current_price: float,
        original_notional: float,
        error_type: str,
        slice_number: int,
        executed: float,
        target_notional: float
    ) -> None:
        """Attempt safe fallback for recoverable slice creation failures.
        
        Args:
            symbol: Trading symbol
            side: Order side
            original_quantity: Original failed quantity
            current_price: Current market price
            original_notional: Original failed notional
            error_type: Type of error that occurred
            slice_number: Current slice number
            executed: Already executed notional
            target_notional: Target notional value
        """
        # Get symbol info for minimum requirements
        symbol_info = self._get_default_symbol_info(symbol)
        min_notional = symbol_info.get("min_notional", 10.0)
        step_size = symbol_info.get("step_size", 0.001)
        
        # Calculate minimum viable quantity and notional
        min_quantity = step_size  # Minimum quantity based on step size
        min_viable_notional = max(min_notional, min_quantity * current_price)
        
        # Only attempt fallback if we haven't executed anything yet (first slice)
        if slice_number == 1 and executed == 0.0:
            # Try with minimum viable notional
            fallback_quantity = min_viable_notional / current_price
            
            # Round to step size
            from decimal import Decimal, ROUND_UP
            quantity_decimal = Decimal(str(fallback_quantity))
            step_decimal = Decimal(str(step_size))
            rounded_quantity = float((quantity_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_UP) * step_decimal)
            
            fallback_notional = rounded_quantity * current_price
            
            self.logger.info(
                f"SLICE FALLBACK: {symbol} {side.value} - Attempting minimum viable slice "
                f"(qty={rounded_quantity:.6f}, notional=${fallback_notional:.2f})"
            )
            
            # Attempt to create order with minimum viable parameters
            fallback_order, fallback_error = self.create_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=rounded_quantity,
                strategy="sliced_entry",
                metadata={
                    "slice": True,
                    "slice_number": slice_number,
                    "is_fallback": True,
                    "original_error": error_type,
                    "reduce_only": False
                }
            )
            
            if fallback_order:
                # Simulate execution
                success = self._simulate_order_execution(fallback_order, current_price)
                if success:
                    self.logger.info(
                        f"SLICE FALLBACK SUCCESS: {symbol} {side.value} - Minimum viable slice executed "
                        f"(qty={rounded_quantity:.6f}, notional=${fallback_notional:.2f})"
                    )
                    return  # Success - fallback worked
                else:
                    self.logger.warning(
                        f"SLICE FALLBACK EXECUTION FAILED: {symbol} {side.value} - Minimum viable slice failed to execute"
                    )
            else:
                self.logger.warning(
                    f"SLICE FALLBACK CREATION FAILED: {symbol} {side.value} - {fallback_error}"
                )
        
        # Fallback failed or not applicable - abort cleanly
        self.logger.warning(
            f"SLICING ABORT: {symbol} {side.value} - Fallback failed or not applicable "
            f"(error={error_type}, executed=${executed:.2f}/{target_notional:.2f}, {slice_number-1} slices completed)"
        )
    
    def _get_risk_unit(self, symbol: str, avg_cost: float, risk_manager) -> float:
        """Get 1R (risk unit) for TP ladder calculation.
        
        Args:
            symbol: Trading symbol
            avg_cost: Average cost of position
            risk_manager: Risk manager instance
            
        Returns:
            1R value (risk unit)
        """
        try:
            # Try to get ATR from risk manager (reuse existing ATR accessor)
            atr = risk_manager._get_atr_for_symbol(symbol, avg_cost)
            
            if atr and atr > 0:
                # Use ATR as proxy for 1R
                return atr
            else:
                # Fallback: use 0.5% of price as 1R
                return avg_cost * 0.005
                
        except Exception as e:
            self.logger.debug(f"Error getting 1R for {symbol}: {e}")
            # Fallback: use 0.5% of price as 1R
            return avg_cost * 0.005

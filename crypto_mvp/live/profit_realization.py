"""
Profit Realization Engine - Lean State Machine for Exit Rules.

Encapsulates exit rules in a small engine that returns planned exit actions
without placing orders directly.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# ATR functionality is provided via parameter to plan_exits method

# Import Decimal helper
try:
    from ..src.crypto_mvp.core.money import to_dec, TWO, ZERO
except ImportError:
    # Fallback if import path differs
    def to_dec(value: Union[str, int, float, Decimal, None]) -> Decimal:
        """Convert to Decimal safely."""
        if value is None:
            return Decimal('0')
        elif isinstance(value, Decimal):
            return value
        else:
            return Decimal(str(value))
    
    TWO = Decimal('2')
    ZERO = Decimal('0')


class ExitActionType(Enum):
    """Types of exit actions."""
    TAKE_PROFIT = "tp"
    STOP_LOSS = "stop"
    TRAILING_STOP = "trail"
    CLOSE = "close"


@dataclass
class ExitAction:
    """Exit action data structure for profit realization."""
    
    type: ExitActionType
    symbol: str
    fraction: Decimal  # Fraction of position to exit (0.0 to 1.0)
    price: Optional[Decimal] = None  # Target price for the action
    prefer_maker: bool = True  # Prefer maker orders for better execution
    reason: str = ""  # Human-readable reason for the action
    
    def __post_init__(self):
        """Validate exit action data."""
        # Convert fraction to Decimal if needed
        if not isinstance(self.fraction, Decimal):
            self.fraction = to_dec(self.fraction)
        
        # Convert price to Decimal if needed
        if self.price is not None and not isinstance(self.price, Decimal):
            self.price = to_dec(self.price)
        
        if not (ZERO <= self.fraction <= Decimal('1.0')):
            raise ValueError(f"Fraction must be between 0.0 and 1.0, got {self.fraction}")
        
        if self.price is not None and self.price <= ZERO:
            raise ValueError(f"Price must be positive, got {self.price}")


@dataclass
class PositionState:
    """Position state tracking for profit realization."""
    
    symbol: str
    entry_price: Decimal
    quantity: Decimal
    side: str  # "long" or "short"
    entry_time: datetime
    current_price: Decimal
    
    # Risk management
    initial_stop: Optional[Decimal] = None
    current_stop: Optional[Decimal] = None
    
    # Take profit tracking
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    
    # Bars tracking for time-based stop
    bars_since_entry: int = 0
    
    # Peak tracking for trailing stops
    peak_price: Optional[Decimal] = None
    peak_time: Optional[datetime] = None
    
    # Position extras for storing additional state
    extras: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extras is None:
            self.extras = {}
        
        # Convert all numeric fields to Decimal
        self.entry_price = to_dec(self.entry_price)
        self.quantity = to_dec(self.quantity)
        self.current_price = to_dec(self.current_price)
        if self.initial_stop is not None:
            self.initial_stop = to_dec(self.initial_stop)
        if self.current_stop is not None:
            self.current_stop = to_dec(self.current_stop)
        if self.peak_price is not None:
            self.peak_price = to_dec(self.peak_price)
    
    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.side.lower() in ['long', 'buy', 'b']
    
    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.side.lower() in ['short', 'sell', 's']
    
    @property
    def holding_time_hours(self) -> float:
        """Get holding time in hours."""
        return (datetime.now() - self.entry_time).total_seconds() / 3600.0
    
    @property
    def unrealized_pnl(self) -> Decimal:
        """Calculate unrealized P&L."""
        if self.is_long:
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity
    
    @property
    def risk_unit(self) -> Decimal:
        """Calculate risk unit (R) from entry to initial stop."""
        if self.initial_stop is None:
            return ZERO
        
        if self.is_long:
            return abs(self.entry_price - self.initial_stop)
        else:
            return abs(self.initial_stop - self.entry_price)


class ProfitRealizationEngine:
    """
    Lean state machine for profit realization exit rules.
    
    Encapsulates exit rules and returns planned exit actions without
    placing orders directly. Pure planner with no I/O.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the profit realization engine.
        
        Args:
            config: Configuration dictionary containing realization settings
        """
        self.config = config.get("realization", {})
        
        # Validate configuration
        self._validate_config()
        
        # Extract configuration values
        self.enabled = self.config.get("enabled", False)
        self.take_profit_ladder = self.config.get("take_profit_ladder", [])
        self.trail_config = self.config.get("trail", {})
        self.time_stop_hours = self.config.get("time_stop_hours", 24)
        self.max_bars_in_trade = self.config.get("max_bars_in_trade", 48)  # Time-based exit
        
        # State tracking for positions
        self.position_states: Dict[str, PositionState] = {}
    
    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        if not self.config:
            raise ValueError("Realization configuration is required")
        
        take_profit_ladder = self.config.get("take_profit_ladder", [])
        if take_profit_ladder:
            total_pct = sum(step.get("pct", 0) for step in take_profit_ladder)
            if total_pct > 1.0:
                raise ValueError(f"Take profit ladder percentages sum to {total_pct:.1%}, must be ≤ 100%")
    
    def plan_exits(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        regime: str = "normal",
        atr_val: Optional[float] = None
    ) -> List[ExitAction]:
        """
        Plan exit actions for a position based on current market conditions.
        
        Args:
            position: Position data dictionary
            market: Market data dictionary (current price, etc.)
            regime: Market regime ("normal", "high_vol", etc.)
            atr_val: Current ATR value for the symbol
            
        Returns:
            List of planned exit actions
        """
        if not self.enabled:
            return []
        
        try:
            # Create or update position state
            position_state = self._get_or_create_position_state(position, market, atr_val)
            
            # Plan exit actions based on current state
            exit_actions = []
            
            # 1. Check take profit ladder
            tp_actions = self._plan_take_profit_actions(position_state, market)
            exit_actions.extend(tp_actions)
            
            # 2. Check stop loss updates (breakeven after TP1)
            stop_actions = self._plan_stop_loss_actions(position_state, market)
            exit_actions.extend(stop_actions)
            
            # 3. Check trailing stop (after TP2)
            trail_actions = self._plan_trailing_stop_actions(position_state, market, regime, atr_val)
            exit_actions.extend(trail_actions)
            
            # 4. Check time stop
            time_actions = self._plan_time_stop_actions(position_state, market)
            exit_actions.extend(time_actions)
            
            return exit_actions
            
        except Exception as e:
            # Return empty list on any error for safety
            return []
    
    def _get_or_create_position_state(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        atr_val: Optional[float]
    ) -> PositionState:
        """Get or create position state for tracking."""
        symbol = position.get("symbol", "unknown")
        
        # Check if we already have state for this position
        if symbol in self.position_states:
            # Update existing state
            state = self.position_states[symbol]
            state.current_price = to_dec(market.get("price", state.current_price))
            state.peak_price = self._update_peak_price(state)
            # Bars counter incremented in _plan_time_stop_actions
            return state
        
        # Create new position state
        entry_price = to_dec(position.get("entry_price", position.get("price", 0.0)))
        quantity = to_dec(position.get("quantity", position.get("size", 0.0)))
        side = position.get("side", "long")
        entry_time = position.get("entry_time", datetime.now())
        current_price = to_dec(market.get("price", entry_price))
        
        # Determine initial stop if not provided
        initial_stop = position.get("initial_stop")
        if initial_stop is None and atr_val and atr_val > 0:
            atr_dec = to_dec(atr_val)
            # Derive initial stop using 2*ATR
            if side.lower() in ['long', 'buy', 'b']:
                initial_stop = entry_price - (TWO * atr_dec)
            else:
                initial_stop = entry_price + (TWO * atr_dec)
        else:
            initial_stop = to_dec(initial_stop) if initial_stop is not None else None
        
        # Prepare extras with ATR value
        extras = position.get("extras", {}).copy()
        if atr_val and atr_val > 0:
            extras["atr_value"] = atr_val
            if initial_stop is not None:
                extras["initial_stop"] = initial_stop
        
        state = PositionState(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            side=side,
            entry_time=entry_time,
            current_price=current_price,
            initial_stop=initial_stop,
            current_stop=initial_stop,  # Start with initial stop
            peak_price=current_price,
            peak_time=datetime.now(),
            bars_since_entry=0,  # Initialize bars counter
            extras=extras
        )
        
        # Store state
        self.position_states[symbol] = state
        
        return state
    
    def _update_peak_price(self, state: PositionState) -> Optional[Decimal]:
        """Update peak price for trailing stop calculation."""
        if state.is_long and state.current_price > (state.peak_price or ZERO):
            state.peak_price = state.current_price
            state.peak_time = datetime.now()
            return state.peak_price
        elif state.is_short and state.current_price < (state.peak_price or Decimal('999999999')):
            state.peak_price = state.current_price
            state.peak_time = datetime.now()
            return state.peak_price
        
        return state.peak_price
    
    def _plan_take_profit_actions(self, state: PositionState, market: Dict[str, Any]) -> List[ExitAction]:
        """Plan take profit actions based on ladder configuration."""
        actions = []
        
        if not self.take_profit_ladder:
            return actions
        
        # Calculate current R multiple using ATR as risk unit
        # We need to get ATR from the position extras or calculate it
        atr_val = to_dec(state.extras.get("atr_value", 0.0))
        if atr_val <= ZERO:
            return actions
        
        # R multiple = (current_price - entry_price) / ATR for long
        # R multiple = (entry_price - current_price) / ATR for short
        if state.is_long:
            price_diff = state.current_price - state.entry_price
        else:
            price_diff = state.entry_price - state.current_price
        
        current_r = price_diff / atr_val
        
        # Check each take profit level
        for i, tp_step in enumerate(self.take_profit_ladder):
            r_target = to_dec(tp_step.get("r", 0))
            pct_to_sell = to_dec(tp_step.get("pct", 0))
            
            # Skip if already hit this TP level
            if i == 0 and state.tp1_hit:
                continue
            elif i == 1 and state.tp2_hit:
                continue
            elif i == 2 and state.tp3_hit:
                continue
            
            # Check if we've reached this R level
            if current_r >= r_target:
                # Calculate target price using ATR as risk unit
                if state.is_long:
                    target_price = state.entry_price + (r_target * atr_val)
                else:
                    target_price = state.entry_price - (r_target * atr_val)
                
                # Create take profit action
                action = ExitAction(
                    type=ExitActionType.TAKE_PROFIT,
                    symbol=state.symbol,
                    fraction=pct_to_sell,
                    price=target_price,
                    prefer_maker=True,
                    reason=f"Take profit {i+1} at {float(r_target)}R"
                )
                actions.append(action)
                
                # Mark TP as hit
                if i == 0:
                    state.tp1_hit = True
                elif i == 1:
                    state.tp2_hit = True
                elif i == 2:
                    state.tp3_hit = True
        
        return actions
    
    def _plan_stop_loss_actions(self, state: PositionState, market: Dict[str, Any]) -> List[ExitAction]:
        """
        Plan stop loss actions with progressive tightening.
        
        After TP1: Move to breakeven
        After TP2: Trail at entry + 0.5R for longs (entry - 0.5R for shorts)
        """
        actions = []
        
        # Get risk unit (R)
        risk_unit = state.risk_unit
        
        if state.tp2_hit:
            # After TP2: Trail at entry + 0.5R (more aggressive trailing)
            if state.is_long:
                new_stop = state.entry_price + (to_dec("0.5") * risk_unit)
            else:
                new_stop = state.entry_price - (to_dec("0.5") * risk_unit)
            
            # Only update if new stop is better than current
            if state.current_stop is None or (
                (state.is_long and new_stop > state.current_stop) or
                (state.is_short and new_stop < state.current_stop)
            ):
                action = ExitAction(
                    type=ExitActionType.STOP_LOSS,
                    symbol=state.symbol,
                    fraction=ZERO,  # No position exit, just stop update
                    price=new_stop,
                    prefer_maker=True,
                    reason=f"Trail stop to entry + 0.5R after TP2: {float(new_stop):.2f}"
                )
                actions.append(action)
                state.current_stop = new_stop
                
        elif state.tp1_hit and state.current_stop != state.entry_price:
            # After TP1: Move to breakeven
            action = ExitAction(
                type=ExitActionType.STOP_LOSS,
                symbol=state.symbol,
                fraction=ZERO,  # No position exit, just stop update
                price=state.entry_price,
                prefer_maker=True,
                reason="Move stop to breakeven after TP1"
            )
            actions.append(action)
            
            # Update state
            state.current_stop = state.entry_price
        
        return actions
    
    def _plan_trailing_stop_actions(
        self,
        state: PositionState,
        market: Dict[str, Any],
        regime: str,
        atr_val: Optional[Union[float, Decimal]]
    ) -> List[ExitAction]:
        """Plan trailing stop actions (chandelier after TP2)."""
        actions = []
        
        # Only activate trailing stop after TP2
        if not state.tp2_hit:
            return actions
        
        atr_dec = to_dec(atr_val) if atr_val is not None else ZERO
        if atr_dec <= ZERO:
            return actions
        
        # Choose ATR multiplier based on regime
        atr_mult = to_dec(self.trail_config.get("atr_mult_normal", 2.0))
        if regime == "high_vol":
            atr_mult = to_dec(self.trail_config.get("atr_mult_high_vol", 2.5))
        
        # Calculate trailing stop level
        if state.is_long and state.peak_price:
            trail_stop = state.peak_price - (atr_mult * atr_dec)
            # Only update if trailing stop is higher than current stop
            if state.current_stop is None or trail_stop > state.current_stop:
                action = ExitAction(
                    type=ExitActionType.TRAILING_STOP,
                    symbol=state.symbol,
                    fraction=ZERO,  # No position exit, just stop update
                    price=trail_stop,
                    prefer_maker=True,
                    reason=f"Chandelier trail at {float(atr_mult)}ATR"
                )
                actions.append(action)
                state.current_stop = trail_stop
        
        elif state.is_short and state.peak_price:
            trail_stop = state.peak_price + (atr_mult * atr_dec)
            # Only update if trailing stop is lower than current stop
            if state.current_stop is None or trail_stop < state.current_stop:
                action = ExitAction(
                    type=ExitActionType.TRAILING_STOP,
                    symbol=state.symbol,
                    fraction=ZERO,  # No position exit, just stop update
                    price=trail_stop,
                    prefer_maker=True,
                    reason=f"Chandelier trail at {float(atr_mult)}ATR"
                )
                actions.append(action)
                state.current_stop = trail_stop
        
        return actions
    
    def _plan_time_stop_actions(self, state: PositionState, market: Dict[str, Any]) -> List[ExitAction]:
        """
        Plan time stop actions based on bars in trade.
        
        If neither TP nor SL hits within max_bars_in_trade, close at market.
        This prevents positions from becoming "zombie" trades.
        """
        actions = []
        
        # Increment bars counter
        state.bars_since_entry += 1
        
        # Check bars-based time stop
        if state.bars_since_entry >= self.max_bars_in_trade and not state.tp1_hit:
            action = ExitAction(
                type=ExitActionType.CLOSE,
                symbol=state.symbol,
                fraction=Decimal('1.0'),  # Close entire position
                price=state.current_price,
                prefer_maker=False,  # Market order for time stops
                reason=f"Time stop: {state.bars_since_entry} bars without TP1 (max={self.max_bars_in_trade})"
            )
            actions.append(action)
            return actions
        
        # Also check hour-based time stop as fallback
        if state.holding_time_hours > self.time_stop_hours and not state.tp1_hit:
            action = ExitAction(
                type=ExitActionType.CLOSE,
                symbol=state.symbol,
                fraction=Decimal('1.0'),  # Close entire position
                price=state.current_price,
                prefer_maker=False,  # Market order for time stops
                reason=f"Time stop after {state.holding_time_hours:.1f}h without TP1"
            )
            actions.append(action)
        
        return actions
    
    def get_position_state(self, symbol: str) -> Optional[PositionState]:
        """Get current position state for a symbol."""
        return self.position_states.get(symbol)
    
    def clear_position_state(self, symbol: str) -> None:
        """Clear position state for a symbol (e.g., when position is closed)."""
        if symbol in self.position_states:
            del self.position_states[symbol]
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of all position states."""
        return {
            "enabled": self.enabled,
            "active_positions": len(self.position_states),
            "positions": {
                symbol: {
                    "symbol": state.symbol,
                    "side": state.side,
                    "entry_price": state.entry_price,
                    "current_price": state.current_price,
                    "unrealized_pnl": state.unrealized_pnl,
                    "holding_hours": state.holding_time_hours,
                    "tp1_hit": state.tp1_hit,
                    "tp2_hit": state.tp2_hit,
                    "tp3_hit": state.tp3_hit,
                    "current_stop": state.current_stop,
                    "peak_price": state.peak_price
                }
                for symbol, state in self.position_states.items()
            }
        }

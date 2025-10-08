"""
Bracket order management with Decimal precision.

This module provides bracket order functionality with:
- 3-rung take profit ladder
- Decimal-based price calculations
- BracketSpecError validation
- Monotonic TP level verification
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Union, Any
import logging

# Set decimal precision
getcontext().prec = 28

logger = logging.getLogger(__name__)


class BracketSpecError(Exception):
    """Raised when bracket order specifications are invalid."""
    pass


class BracketOrder:
    """Represents a bracket order with entry, stop loss, and take profit levels."""
    
    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        stop_loss: Union[float, Decimal],
        take_profit_levels: List[Union[float, Decimal]],
        strategy: str = "unknown",
        order_id: str = ""
    ):
        """
        Initialize bracket order.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            stop_loss: Stop loss price
            take_profit_levels: List of take profit levels (up to 3)
            strategy: Strategy name
            order_id: Order ID
            
        Raises:
            BracketSpecError: If bracket specifications are invalid
        """
        # Convert all inputs to Decimal
        self.entry_price = Decimal(str(entry_price))
        self.quantity = Decimal(str(quantity))
        self.stop_loss = Decimal(str(stop_loss))
        self.take_profit_levels = [Decimal(str(tp)) for tp in take_profit_levels]
        self.side = side.upper()
        self.symbol = symbol
        self.strategy = strategy
        self.order_id = order_id
        
        # Validate bracket specifications
        self._validate_bracket_specs()
        
        # Sort take profit levels to ensure monotonicity
        self._ensure_monotonic_tp_levels()
    
    def _validate_bracket_specs(self) -> None:
        """Validate bracket order specifications."""
        if self.side == "BUY":
            # Long: stop < entry < take_profit
            if not (self.stop_loss < self.entry_price):
                raise BracketSpecError(
                    f"Long bracket invalid: stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})"
                )
            
            for i, tp in enumerate(self.take_profit_levels):
                if not (self.entry_price < tp):
                    raise BracketSpecError(
                        f"Long bracket invalid: entry_price ({self.entry_price}) must be < take_profit[{i}] ({tp})"
                    )
                    
        elif self.side == "SELL":
            # Short: take_profit < entry < stop
            if not (self.entry_price < self.stop_loss):
                raise BracketSpecError(
                    f"Short bracket invalid: entry_price ({self.entry_price}) must be < stop_loss ({self.stop_loss})"
                )
            
            for i, tp in enumerate(self.take_profit_levels):
                if not (tp < self.entry_price):
                    raise BracketSpecError(
                        f"Short bracket invalid: take_profit[{i}] ({tp}) must be < entry_price ({self.entry_price})"
                    )
        else:
            raise BracketSpecError(f"Invalid side: {self.side}. Must be BUY or SELL")
    
    def _ensure_monotonic_tp_levels(self) -> None:
        """Ensure take profit levels are monotonic."""
        if not self.take_profit_levels:
            return
            
        if self.side == "BUY":
            # For long positions, TP levels should be increasing
            self.take_profit_levels.sort()
            for i in range(1, len(self.take_profit_levels)):
                if self.take_profit_levels[i] <= self.take_profit_levels[i-1]:
                    raise BracketSpecError(
                        f"Long TP levels must be strictly increasing: {self.take_profit_levels}"
                    )
        else:
            # For short positions, TP levels should be decreasing
            self.take_profit_levels.sort(reverse=True)
            for i in range(1, len(self.take_profit_levels)):
                if self.take_profit_levels[i] >= self.take_profit_levels[i-1]:
                    raise BracketSpecError(
                        f"Short TP levels must be strictly decreasing: {self.take_profit_levels}"
                    )
    
    def get_risk_reward_ratio(self) -> Decimal:
        """Calculate risk-reward ratio."""
        if not self.take_profit_levels:
            return Decimal('0')
        
        # Use the first (closest) TP level for R:R calculation
        tp = self.take_profit_levels[0]
        
        if self.side == "BUY":
            risk = self.entry_price - self.stop_loss
            reward = tp - self.entry_price
        else:
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - tp
        
        if risk <= 0:
            return Decimal('0')
        
        return reward / risk
    
    def get_position_value(self) -> Decimal:
        """Calculate total position value."""
        return self.entry_price * self.quantity
    
    def get_stop_loss_value(self) -> Decimal:
        """Calculate stop loss value."""
        return self.stop_loss * self.quantity
    
    def get_take_profit_values(self) -> List[Decimal]:
        """Calculate take profit values for each level."""
        return [tp * self.quantity for tp in self.take_profit_levels]
    
    def get_partial_quantities(self, ratios: Optional[List[Decimal]] = None) -> List[Decimal]:
        """
        Calculate partial quantities for each TP level.
        
        Args:
            ratios: List of ratios for each TP level (default: [0.4, 0.4, 0.2])
            
        Returns:
            List of quantities for each TP level
        """
        if ratios is None:
            ratios = [Decimal('0.4'), Decimal('0.4'), Decimal('0.2')]
        
        partial_qtys = []
        remaining_qty = self.quantity
        
        for i, ratio in enumerate(ratios):
            if i == len(ratios) - 1:
                # Last TP gets remaining quantity (handles rounding)
                partial_qtys.append(remaining_qty)
            else:
                qty = self.quantity * ratio
                partial_qtys.append(qty)
                remaining_qty -= qty
        
        logger.info(f"Created {len(partial_qtys)} TP levels with quantities: {[float(q) for q in partial_qtys]}")
        
        return partial_qtys
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert bracket order to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": float(self.entry_price),
            "quantity": float(self.quantity),
            "stop_loss": float(self.stop_loss),
            "take_profit_levels": [float(tp) for tp in self.take_profit_levels],
            "strategy": self.strategy,
            "order_id": self.order_id,
            "risk_reward_ratio": float(self.get_risk_reward_ratio())
        }


class BracketManager:
    """Manages bracket orders with Decimal precision."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize bracket manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.active_brackets: Dict[str, BracketOrder] = {}
        
        # Default TP ladder configuration - optimized for frequent profit realization
        # Rungs: [+0.6R, +1.2R, +2.0R] with partial sizes [40%, 40%, 20%]
        self.tp_ladder_r_multiples = [
            Decimal('0.6'),  # First TP at 0.6R (quick profit taking)
            Decimal('1.2'),  # Second TP at 1.2R (trend capture)
            Decimal('2.0')   # Third TP at 2.0R (runner)
        ]
        
        self.tp_ladder_ratios = [
            Decimal('0.4'),  # 40% at first TP
            Decimal('0.4'),  # 40% at second TP  
            Decimal('0.2')   # 20% at third TP (runner)
        ]
    
    def create_bracket_order(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        stop_loss: Union[float, Decimal],
        atr: Optional[Union[float, Decimal]] = None,
        risk_reward_ratio: Optional[Union[float, Decimal]] = None,
        strategy: str = "unknown",
        order_id: str = ""
    ) -> BracketOrder:
        """
        Create a bracket order with 3-rung TP ladder.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            stop_loss: Stop loss price
            atr: Average True Range for TP calculation
            risk_reward_ratio: Target risk-reward ratio
            strategy: Strategy name
            order_id: Order ID
            
        Returns:
            BracketOrder instance
            
        Raises:
            BracketSpecError: If bracket specifications are invalid
        """
        # Convert inputs to Decimal
        entry_decimal = Decimal(str(entry_price))
        quantity_decimal = Decimal(str(quantity))
        stop_decimal = Decimal(str(stop_loss))
        
        # Calculate take profit levels
        tp_levels = self._calculate_tp_ladder(
            entry_price=entry_decimal,
            stop_loss=stop_decimal,
            side=side,
            atr=Decimal(str(atr)) if atr is not None else None,
            risk_reward_ratio=Decimal(str(risk_reward_ratio)) if risk_reward_ratio is not None else None
        )
        
        # Create bracket order
        bracket = BracketOrder(
            symbol=symbol,
            side=side,
            entry_price=entry_decimal,
            quantity=quantity_decimal,
            stop_loss=stop_decimal,
            take_profit_levels=tp_levels,
            strategy=strategy,
            order_id=order_id
        )
        
        # Store active bracket
        if order_id:
            self.active_brackets[order_id] = bracket
        
        logger.info(f"Created bracket order {order_id}: {bracket.to_dict()}")
        
        return bracket
    
    def _calculate_tp_ladder(
        self,
        entry_price: Decimal,
        stop_loss: Decimal,
        side: str,
        atr: Optional[Decimal] = None,
        risk_reward_ratio: Optional[Decimal] = None
    ) -> List[Decimal]:
        """
        Calculate 3-rung take profit ladder optimized for frequent profit realization.
        
        Uses fixed R-multiples: [+0.6R, +1.2R, +2.0R] for better win rate and
        frequent equity growth.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: Order side (BUY/SELL)
            atr: Average True Range (unused, for compatibility)
            risk_reward_ratio: Target risk-reward ratio (unused, for compatibility)
            
        Returns:
            List of take profit levels at [0.6R, 1.2R, 2.0R]
        """
        # Calculate risk distance (1R)
        if side == "BUY":
            risk_distance = entry_price - stop_loss
        else:
            risk_distance = stop_loss - entry_price
        
        if risk_distance <= 0:
            raise BracketSpecError(f"Invalid risk distance: {risk_distance}")
        
        # Calculate TP levels using optimized R-multiples for frequent profit realization
        tp_levels = []
        
        for r_multiple in self.tp_ladder_r_multiples:
            if side == "BUY":
                tp = entry_price + (risk_distance * r_multiple)
            else:
                tp = entry_price - (risk_distance * r_multiple)
            
            tp_levels.append(tp)
        
        logger.info(f"Created 3 TP levels at {[float(r) for r in self.tp_ladder_r_multiples]}R: "
                   f"{[float(tp) for tp in tp_levels]}")
        
        return tp_levels
    
    def update_bracket_stop_loss(
        self,
        order_id: str,
        new_stop_loss: Union[float, Decimal]
    ) -> bool:
        """
        Update stop loss for existing bracket order.
        
        Args:
            order_id: Order ID
            new_stop_loss: New stop loss price
            
        Returns:
            True if update successful
        """
        if order_id not in self.active_brackets:
            logger.warning(f"Bracket order {order_id} not found")
            return False
        
        bracket = self.active_brackets[order_id]
        new_stop_decimal = Decimal(str(new_stop_loss))
        
        try:
            # Create new bracket with updated stop loss
            updated_bracket = BracketOrder(
                symbol=bracket.symbol,
                side=bracket.side,
                entry_price=bracket.entry_price,
                quantity=bracket.quantity,
                stop_loss=new_stop_decimal,
                take_profit_levels=bracket.take_profit_levels,
                strategy=bracket.strategy,
                order_id=order_id
            )
            
            self.active_brackets[order_id] = updated_bracket
            logger.info(f"Updated stop loss for bracket {order_id}: {new_stop_decimal}")
            return True
            
        except BracketSpecError as e:
            logger.error(f"Failed to update stop loss for bracket {order_id}: {e}")
            return False
    
    def close_bracket(self, order_id: str) -> Optional[BracketOrder]:
        """
        Close bracket order.
        
        Args:
            order_id: Order ID
            
        Returns:
            Closed bracket order or None if not found
        """
        if order_id in self.active_brackets:
            bracket = self.active_brackets.pop(order_id)
            logger.info(f"Closed bracket order {order_id}")
            return bracket
        
        logger.warning(f"Bracket order {order_id} not found for closing")
        return None
    
    def get_active_brackets(self) -> Dict[str, BracketOrder]:
        """Get all active bracket orders."""
        return self.active_brackets.copy()
    
    def validate_bracket_specs(
        self,
        side: str,
        entry_price: Union[float, Decimal],
        stop_loss: Union[float, Decimal],
        take_profit: Union[float, Decimal]
    ) -> bool:
        """
        Validate bracket specifications without creating order.
        
        Args:
            side: Order side (BUY/SELL)
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            
        Returns:
            True if specifications are valid
        """
        try:
            BracketOrder(
                symbol="VALIDATION",
                side=side,
                entry_price=entry_price,
                quantity=Decimal('1'),
                stop_loss=stop_loss,
                take_profit_levels=[take_profit],
                strategy="validation"
            )
            return True
        except BracketSpecError:
            return False


def create_bracket_order(
    symbol: str,
    side: str,
    entry_price: Union[float, Decimal],
    quantity: Union[float, Decimal],
    stop_loss: Union[float, Decimal],
    atr: Optional[Union[float, Decimal]] = None,
    risk_reward_ratio: Optional[Union[float, Decimal]] = None,
    strategy: str = "unknown"
) -> BracketOrder:
    """
    Convenience function to create bracket order.
    
    Args:
        symbol: Trading symbol
        side: Order side (BUY/SELL)
        entry_price: Entry price
        quantity: Order quantity
        stop_loss: Stop loss price
        atr: Average True Range
        risk_reward_ratio: Target risk-reward ratio
        strategy: Strategy name
        
    Returns:
        BracketOrder instance
    """
    manager = BracketManager()
    return manager.create_bracket_order(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        stop_loss=stop_loss,
        atr=atr,
        risk_reward_ratio=risk_reward_ratio,
        strategy=strategy
    )

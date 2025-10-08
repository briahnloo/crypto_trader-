"""
Pyramiding Logic - Adding to Winning Positions.

Allows adding to positions at favorable R-multiples with tighter trailing stops.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging

from ..core.money import to_dec, ZERO, ONE
from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class PyramidTracker(LoggerMixin):
    """
    Tracks pyramiding adds for positions.
    
    Pyramiding rules:
    - Max 2 adds per position (+3 total entries)
    - Add at +0.7R and +1.4R
    - Tighten trailing SL after each add
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize pyramid tracker.
        
        Args:
            config: Configuration dictionary
        """
        super().__init__()
        self.config = config or {}
        
        # Pyramiding configuration
        risk_on_config = self.config.get("risk", {}).get("risk_on", {})
        self.allow_pyramids = risk_on_config.get("allow_pyramids", True)
        self.max_adds = risk_on_config.get("max_adds", 2)
        self.add_triggers_r = [to_dec(r) for r in risk_on_config.get("add_triggers_r", [0.7, 1.4])]
        
        # Position tracking: symbol -> pyramid state
        self.pyramid_states: Dict[str, Dict[str, Any]] = {}
        
        logger.info(
            f"PyramidTracker initialized: allow_pyramids={self.allow_pyramids}, "
            f"max_adds={self.max_adds}, "
            f"add_triggers_r={[float(r) for r in self.add_triggers_r]}"
        )
    
    def can_add_to_position(
        self,
        symbol: str,
        entry_price: Decimal,
        current_price: Decimal,
        initial_stop: Decimal,
        current_r: Optional[Decimal] = None
    ) -> Tuple[bool, str, Optional[Decimal]]:
        """
        Check if we can add to a position based on R-multiple.
        
        Args:
            symbol: Trading symbol
            entry_price: Initial entry price
            current_price: Current market price
            initial_stop: Initial stop loss price
            current_r: Current R-multiple (optional, will calculate if not provided)
            
        Returns:
            Tuple of (can_add, reason, trigger_r)
        """
        if not self.allow_pyramids:
            return False, "pyramiding_disabled", None
        
        # Get or create pyramid state
        if symbol not in self.pyramid_states:
            self.pyramid_states[symbol] = {
                "entry_price": entry_price,
                "initial_stop": initial_stop,
                "adds_count": 0,
                "adds_at_r": [],
                "add_prices": [],
                "last_add_time": None
            }
        
        state = self.pyramid_states[symbol]
        
        # Check if we've reached max adds
        if state["adds_count"] >= self.max_adds:
            return False, f"max_adds_reached_{self.max_adds}", None
        
        # Calculate current R-multiple if not provided
        if current_r is None:
            risk_unit = abs(entry_price - initial_stop)
            if risk_unit == ZERO:
                return False, "invalid_risk_unit", None
            
            price_gain = current_price - entry_price  # For longs
            current_r = price_gain / risk_unit
        
        # Check which add trigger we've hit
        for i, trigger_r in enumerate(self.add_triggers_r):
            # Check if we haven't already added at this level
            if trigger_r not in state["adds_at_r"] and current_r >= trigger_r:
                # We can add at this level
                self.logger.info(
                    f"PYRAMID_TRIGGER: {symbol} at +{float(current_r):.2f}R "
                    f"(trigger={float(trigger_r):.1f}R, add #{state['adds_count'] + 1}/{self.max_adds})"
                )
                return True, f"add_at_{float(trigger_r):.1f}R", trigger_r
        
        # No trigger hit yet
        if state["adds_count"] == 0:
            reason = f"waiting_for_{float(self.add_triggers_r[0]):.1f}R"
        else:
            next_trigger_idx = state["adds_count"]
            if next_trigger_idx < len(self.add_triggers_r):
                reason = f"waiting_for_{float(self.add_triggers_r[next_trigger_idx]):.1f}R"
            else:
                reason = "max_adds_reached"
        
        return False, reason, None
    
    def record_add(
        self,
        symbol: str,
        add_price: Decimal,
        trigger_r: Decimal,
        add_quantity: Decimal
    ) -> None:
        """
        Record a pyramiding add.
        
        Args:
            symbol: Trading symbol
            add_price: Price of the add
            trigger_r: R-multiple that triggered the add
            add_quantity: Quantity added
        """
        if symbol not in self.pyramid_states:
            self.logger.warning(f"Cannot record add for {symbol} - no pyramid state")
            return
        
        state = self.pyramid_states[symbol]
        state["adds_count"] += 1
        state["adds_at_r"].append(trigger_r)
        state["add_prices"].append(add_price)
        state["last_add_time"] = datetime.now()
        
        self.logger.info(
            f"PYRAMID_ADD_RECORDED: {symbol} add #{state['adds_count']} "
            f"at {float(add_price):.4f} ({float(trigger_r):.1f}R), qty={float(add_quantity):.6f}"
        )
    
    def get_tightened_stop(
        self,
        symbol: str,
        entry_price: Decimal,
        initial_stop: Decimal,
        current_r: Decimal
    ) -> Decimal:
        """
        Get tightened trailing stop after pyramiding add.
        
        After each add, trail stop to previous R-level + 0.3R cushion.
        
        Args:
            symbol: Trading symbol
            entry_price: Initial entry price
            initial_stop: Initial stop loss
            current_r: Current R-multiple
            
        Returns:
            Tightened stop price as Decimal
        """
        if symbol not in self.pyramid_states:
            return initial_stop
        
        state = self.pyramid_states[symbol]
        
        if state["adds_count"] == 0:
            # No adds yet - use initial stop
            return initial_stop
        
        # Calculate risk unit
        risk_unit = abs(entry_price - initial_stop)
        
        # Trail stop to: entry + (last_add_r - 0.3R) * risk_unit
        # This locks in profit while giving room for pullbacks
        last_add_r = state["adds_at_r"][-1] if state["adds_at_r"] else ZERO
        cushion_r = to_dec("0.3")
        
        trail_r = max(ZERO, last_add_r - cushion_r)
        new_stop = entry_price + (trail_r * risk_unit)
        
        self.logger.info(
            f"PYRAMID_TRAIL_STOP: {symbol} trailing to entry+{float(trail_r):.1f}R = ${float(new_stop):.4f} "
            f"(after add #{state['adds_count']} at {float(last_add_r):.1f}R)"
        )
        
        return new_stop
    
    def clear_position(self, symbol: str) -> None:
        """
        Clear pyramid state for a symbol (when position closed).
        
        Args:
            symbol: Trading symbol
        """
        if symbol in self.pyramid_states:
            state = self.pyramid_states[symbol]
            self.logger.info(
                f"PYRAMID_CLEAR: {symbol} - had {state['adds_count']} adds at "
                f"R-levels {[float(r) for r in state['adds_at_r']]}"
            )
            del self.pyramid_states[symbol]
    
    def get_pyramid_summary(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get pyramid summary for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Pyramid state dictionary or None
        """
        if symbol not in self.pyramid_states:
            return None
        
        state = self.pyramid_states[symbol]
        return {
            "symbol": symbol,
            "entry_price": float(state["entry_price"]),
            "initial_stop": float(state["initial_stop"]),
            "adds_count": state["adds_count"],
            "adds_at_r": [float(r) for r in state["adds_at_r"]],
            "add_prices": [float(p) for p in state["add_prices"]],
            "max_adds": self.max_adds,
            "remaining_adds": self.max_adds - state["adds_count"]
        }
    
    def get_all_pyramid_states(self) -> Dict[str, Dict[str, Any]]:
        """Get all pyramid states."""
        return {
            symbol: self.get_pyramid_summary(symbol)
            for symbol in self.pyramid_states
        }


def can_pyramid_add(
    symbol: str,
    entry_price: float,
    current_price: float,
    initial_stop: float,
    config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Convenience function to check if pyramiding add is allowed.
    
    Args:
        symbol: Trading symbol
        entry_price: Initial entry price
        current_price: Current market price
        initial_stop: Initial stop loss
        config: Configuration dictionary
        
    Returns:
        Tuple of (can_add, reason)
    """
    tracker = PyramidTracker(config)
    can_add, reason, trigger_r = tracker.can_add_to_position(
        symbol=symbol,
        entry_price=to_dec(entry_price),
        current_price=to_dec(current_price),
        initial_stop=to_dec(initial_stop)
    )
    return can_add, reason


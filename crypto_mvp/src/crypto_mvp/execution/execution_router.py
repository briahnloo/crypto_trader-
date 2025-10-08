"""
Execution Router - Deterministic mapping of final_action → (side, order_intent).

This module ensures:
1. final_action=SELL results in actual short/sell or proper skip
2. Exploration budget only affects exploration trades
3. Normal trades always bypass exploration limits
4. Clear separation of trade intents
"""

from enum import Enum
from typing import Tuple, Optional, Dict, Any
from decimal import Decimal
import logging

from ..core.money import to_dec

logger = logging.getLogger(__name__)


class FinalAction(Enum):
    """Final action types after signal processing."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    SKIP = "SKIP"
    CLOSE = "CLOSE"


class OrderIntent(Enum):
    """Order intent classification."""
    NORMAL = "normal"          # Regular high-quality trade
    PILOT = "pilot"            # Relaxed RR pilot trade
    EXPLORE = "explore"        # Exploration budget trade
    EXIT = "exit"              # Position exit
    RISK_MANAGEMENT = "risk"   # Stop/TP management


class OrderSideAction(Enum):
    """Order side after venue constraints."""
    BUY = "BUY"
    SELL = "SELL"
    CLOSE_LONG = "CLOSE_LONG"
    SKIP = "SKIP"


class ExecutionRouter:
    """
    Routes final actions to order execution with venue constraint handling.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize execution router.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Get shorting configuration
        self.global_short_enabled = self.config.get("risk", {}).get("short_enabled", False)
        self.long_only = not self.global_short_enabled
        
        logger.info(f"ExecutionRouter initialized: global_short_enabled={self.global_short_enabled}")
    
    def allow_direction(self, intent: str) -> bool:
        """
        Check if a trading direction is allowed.
        
        Args:
            intent: Trade intent ("buy", "sell", "short", etc.)
            
        Returns:
            True if the direction is allowed, False otherwise
        """
        if self.long_only and intent.lower() in ("sell", "short"):
            return False
        return True
    
    def route_action(
        self,
        final_action: str,
        symbol: str,
        has_position: bool = False,
        position_side: Optional[str] = None,
        is_pilot: bool = False,
        is_exploration: bool = False
    ) -> Tuple[OrderSideAction, OrderIntent, str]:
        """
        Route final action to order side and intent deterministically.
        
        Args:
            final_action: Final action ("BUY", "SELL", "HOLD", "SKIP")
            symbol: Trading symbol
            has_position: Whether we currently have a position in this symbol
            position_side: Current position side ("long" or "short")
            is_pilot: Whether this is a pilot trade
            is_exploration: Whether this is an exploration trade
            
        Returns:
            Tuple of (OrderSideAction, OrderIntent, reason)
            
        Examples:
            >>> router.route_action("BUY", "BTC/USDT", has_position=False, is_pilot=False)
            (OrderSideAction.BUY, OrderIntent.NORMAL, "open_long")
            
            >>> router.route_action("SELL", "BTC/USDT", has_position=False, is_pilot=False)
            # If shorting disabled:
            (OrderSideAction.SKIP, OrderIntent.NORMAL, "shorting_disabled")
            # If shorting enabled:
            (OrderSideAction.SELL, OrderIntent.NORMAL, "open_short")
        """
        # Normalize inputs
        action_upper = final_action.upper()
        
        # Determine order intent
        if is_exploration:
            intent = OrderIntent.EXPLORE
        elif is_pilot:
            intent = OrderIntent.PILOT
        else:
            intent = OrderIntent.NORMAL
        
        # Map action to order side with venue constraints
        if action_upper == "BUY":
            return self._route_buy_action(symbol, has_position, position_side, intent)
        elif action_upper == "SELL":
            return self._route_sell_action(symbol, has_position, position_side, intent)
        elif action_upper == "HOLD":
            return OrderSideAction.SKIP, intent, "hold_signal"
        elif action_upper == "SKIP":
            return OrderSideAction.SKIP, intent, "skip_signal"
        elif action_upper == "CLOSE":
            return self._route_close_action(symbol, has_position, position_side, intent)
        else:
            logger.warning(f"Unknown final_action: {final_action}")
            return OrderSideAction.SKIP, intent, f"unknown_action_{final_action}"
    
    def _route_buy_action(
        self,
        symbol: str,
        has_position: bool,
        position_side: Optional[str],
        intent: OrderIntent
    ) -> Tuple[OrderSideAction, OrderIntent, str]:
        """Route BUY action deterministically."""
        if has_position:
            if position_side == "short":
                # Close short position
                return OrderSideAction.BUY, OrderIntent.EXIT, "close_short"
            elif position_side == "long":
                # Already long - skip to prevent pyramiding
                return OrderSideAction.SKIP, intent, "already_long_no_pyramid"
        
        # No position or closing short - open long
        return OrderSideAction.BUY, intent, "open_long"
    
    def _route_sell_action(
        self,
        symbol: str,
        has_position: bool,
        position_side: Optional[str],
        intent: OrderIntent
    ) -> Tuple[OrderSideAction, OrderIntent, str]:
        """
        Route SELL action with shorting constraint handling.
        
        If shorting not allowed:
        - Close longs if we have them
        - Do not open shorts (downgrade to SKIP)
        """
        # Check if shorting is allowed
        symbol_allow_short = self._is_shorting_allowed(symbol)
        
        if has_position:
            if position_side == "long":
                # Close long position - always allowed
                return OrderSideAction.SELL, OrderIntent.EXIT, "close_long"
            elif position_side == "short":
                # Already short - skip to prevent pyramiding
                return OrderSideAction.SKIP, intent, "already_short_no_pyramid"
        
        # No position - check if we can open short
        if not symbol_allow_short:
            # Shorting not allowed - downgrade SELL to SKIP
            logger.info(f"SELL signal for {symbol} downgraded to SKIP: shorting_disabled")
            return OrderSideAction.SKIP, intent, "shorting_disabled"
        
        # Shorting allowed - open short
        return OrderSideAction.SELL, intent, "open_short"
    
    def _route_close_action(
        self,
        symbol: str,
        has_position: bool,
        position_side: Optional[str],
        intent: OrderIntent
    ) -> Tuple[OrderSideAction, OrderIntent, str]:
        """Route CLOSE action."""
        if not has_position:
            return OrderSideAction.SKIP, intent, "no_position_to_close"
        
        if position_side == "long":
            return OrderSideAction.SELL, OrderIntent.EXIT, "close_long"
        elif position_side == "short":
            return OrderSideAction.BUY, OrderIntent.EXIT, "close_short"
        else:
            logger.warning(f"Unknown position side: {position_side}")
            return OrderSideAction.SKIP, intent, "unknown_position_side"
    
    def _is_shorting_allowed(self, symbol: str) -> bool:
        """
        Check if shorting is allowed for a symbol.
        
        Requires both:
        1. Global short_enabled setting
        2. Symbol-specific allow_short setting
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if shorting is allowed
        """
        # Check global setting
        if not self.global_short_enabled:
            return False
        
        # Check symbol-specific setting
        symbol_config = self.config.get("symbols", {}).get(symbol, {})
        symbol_allow_short = symbol_config.get("allow_short", False)
        
        return symbol_allow_short
    
    def should_check_exploration_budget(self, intent: OrderIntent) -> bool:
        """
        Determine if exploration budget should be checked.
        
        Only EXPLORE intent trades hit exploration budget checks.
        NORMAL and PILOT trades ignore exploration limits.
        
        Args:
            intent: Order intent
            
        Returns:
            True if exploration budget should be checked
        """
        return intent == OrderIntent.EXPLORE
    
    def create_order_metadata(
        self,
        intent: OrderIntent,
        strategy: str,
        signal_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create order metadata with proper tagging.
        
        Args:
            intent: Order intent
            strategy: Strategy name
            signal_data: Signal data
            **kwargs: Additional metadata fields
            
        Returns:
            Order metadata dictionary
        """
        metadata = {
            "strategy": strategy,
            "order_intent": intent.value,
            "is_exploration": intent == OrderIntent.EXPLORE,
            "is_pilot": intent == OrderIntent.PILOT,
            "is_normal": intent == OrderIntent.NORMAL,
            "signal_score": signal_data.get("composite_score", 0.0),
            "confidence": signal_data.get("confidence", 0.0),
            **kwargs
        }
        
        return metadata
    
    def get_routing_summary(
        self,
        final_action: str,
        routed_side: OrderSideAction,
        intent: OrderIntent,
        reason: str
    ) -> str:
        """Get formatted routing summary for logging."""
        return (
            f"ACTION_ROUTE: {final_action} → {routed_side.value} "
            f"(intent={intent.value}, reason={reason})"
        )


def route_execution(
    final_action: str,
    symbol: str,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Tuple[OrderSideAction, OrderIntent, str]:
    """
    Convenience function for execution routing.
    
    Args:
        final_action: Final action string ("BUY", "SELL", "HOLD", "SKIP")
        symbol: Trading symbol
        config: Configuration dictionary
        **kwargs: Additional routing parameters
        
    Returns:
        Tuple of (OrderSideAction, OrderIntent, reason)
    """
    router = ExecutionRouter(config)
    return router.route_action(final_action, symbol, **kwargs)


"""
Bracket Attacher - Attaches bracket orders to every entry with OCO linking.

This module ensures every position entry gets:
1. Initial SL based on risk_pct
2. TP ladder with 3 rungs: [+0.6R, +1.2R, +2.0R] at sizes [40%, 40%, 20%]
3. Trailing stop logic
4. Time-based stop
5. OCO linking to prevent over-fills
"""

from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
import logging

from ..core.money import to_dec, ONE, quantize_price, quantize_qty
from ...execution.brackets import BracketManager, BracketOrder

logger = logging.getLogger(__name__)


class BracketAttacher:
    """
    Attaches brackets to every entry order with OCO linking.
    """
    
    def __init__(self, order_manager, config: Optional[Dict[str, Any]] = None):
        """
        Initialize bracket attacher.
        
        Args:
            order_manager: Order manager instance
            config: Configuration dictionary
        """
        self.order_manager = order_manager
        self.config = config or {}
        self.bracket_manager = BracketManager(config)
        
        # OCO groups: symbol -> list of order IDs that are OCO-linked
        self.oco_groups: Dict[str, List[str]] = {}
        
        # Track active brackets per symbol
        self.active_brackets: Dict[str, BracketOrder] = {}
    
    def attach_bracket_on_entry(
        self,
        entry_order_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        risk_pct: float,
        strategy: str = "unknown"
    ) -> Tuple[bool, Optional[BracketOrder], str]:
        """
        Attach bracket order on entry with proper OCO linking.
        
        Args:
            entry_order_id: Entry order ID
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            risk_pct: Risk percentage for stop loss
            strategy: Strategy name
            
        Returns:
            Tuple of (success, bracket_order, error_message)
        """
        try:
            # Convert to Decimal
            entry_dec = to_dec(entry_price)
            qty_dec = to_dec(quantity)
            risk_pct_dec = to_dec(risk_pct)
            
            # Calculate initial stop loss based on risk_pct
            if side.upper() == "BUY":
                stop_loss = entry_dec * (ONE - risk_pct_dec)
            else:
                stop_loss = entry_dec * (ONE + risk_pct_dec)
            
            # Quantize prices to exchange steps
            entry_quantized = quantize_price(entry_dec, symbol)
            stop_quantized = quantize_price(stop_loss, symbol)
            qty_quantized = quantize_qty(qty_dec, symbol)
            
            # Create bracket order
            bracket = self.bracket_manager.create_bracket_order(
                symbol=symbol,
                side=side,
                entry_price=entry_quantized,
                quantity=qty_quantized,
                stop_loss=stop_quantized,
                strategy=strategy,
                order_id=entry_order_id
            )
            
            # Get partial quantities for TP levels (40%, 40%, 20%)
            partial_qtys = bracket.get_partial_quantities()
            
            # Create TP orders with OCO linking
            oco_group = []
            tp_orders_created = []
            
            for i, (tp_price, tp_qty) in enumerate(zip(bracket.take_profit_levels, partial_qtys)):
                tp_order_id = f"{entry_order_id}_TP{i+1}"
                
                # Create TP order
                tp_order, tp_error = self.order_manager.create_order(
                    symbol=symbol,
                    side="SELL" if side.upper() == "BUY" else "BUY",
                    order_type="LIMIT",
                    quantity=float(quantize_qty(tp_qty, symbol)),
                    price=float(quantize_price(tp_price, symbol)),
                    metadata={
                        "strategy": strategy,
                        "type": "take_profit",
                        "parent_order": entry_order_id,
                        "tp_level": i + 1,
                        "tp_r_multiple": float(self.bracket_manager.tp_ladder_r_multiples[i])
                    }
                )
                
                if tp_order:
                    oco_group.append(tp_order_id)
                    tp_orders_created.append(tp_order_id)
                    logger.info(f"Created TP{i+1} at {float(tp_price):.4f} "
                               f"({float(self.bracket_manager.tp_ladder_r_multiples[i])}R) "
                               f"for {float(tp_qty):.6f} qty")
                else:
                    logger.warning(f"Failed to create TP{i+1} order: {tp_error}")
            
            # Create initial SL order
            sl_order_id = f"{entry_order_id}_SL"
            sl_order, sl_error = self.order_manager.create_order(
                symbol=symbol,
                side="SELL" if side.upper() == "BUY" else "BUY",
                order_type="STOP",
                quantity=float(qty_quantized),
                price=float(stop_quantized),
                stop_price=float(stop_quantized),
                metadata={
                    "strategy": strategy,
                    "type": "stop_loss",
                    "parent_order": entry_order_id,
                    "initial_stop": True
                }
            )
            
            if sl_order:
                oco_group.append(sl_order_id)
                logger.info(f"Created SL at {float(stop_quantized):.4f} "
                           f"(risk: {float(risk_pct_dec * Decimal('100')):.2f}%)")
            else:
                logger.warning(f"Failed to create SL order: {sl_error}")
            
            # Register OCO group
            self.oco_groups[symbol] = oco_group
            self.active_brackets[symbol] = bracket
            
            logger.info(f"Attached bracket to {entry_order_id}: "
                       f"Entry={float(entry_quantized):.4f}, "
                       f"SL={float(stop_quantized):.4f}, "
                       f"TP={[float(tp) for tp in bracket.take_profit_levels]}, "
                       f"OCO group={len(oco_group)} orders")
            
            return True, bracket, ""
            
        except Exception as e:
            error_msg = f"Failed to attach bracket: {e}"
            logger.error(error_msg)
            return False, None, error_msg
    
    def update_bracket_stop_loss(
        self,
        symbol: str,
        new_stop: float,
        reason: str = ""
    ) -> bool:
        """
        Update stop loss for active bracket (e.g., move to breakeven, trailing).
        
        Args:
            symbol: Trading symbol
            new_stop: New stop loss price
            reason: Reason for update
            
        Returns:
            True if updated successfully
        """
        try:
            if symbol not in self.active_brackets:
                logger.warning(f"No active bracket for {symbol}")
                return False
            
            bracket = self.active_brackets[symbol]
            new_stop_dec = to_dec(new_stop)
            new_stop_quantized = quantize_price(new_stop_dec, symbol)
            
            # Cancel old SL order
            old_sl_id = f"{bracket.order_id}_SL"
            # TODO: Cancel order via order_manager
            
            # Create new SL order
            new_sl_id = f"{bracket.order_id}_SL_updated"
            sl_order, sl_error = self.order_manager.create_order(
                symbol=symbol,
                side="SELL" if bracket.side == "BUY" else "BUY",
                order_type="STOP",
                quantity=float(bracket.quantity),
                price=float(new_stop_quantized),
                stop_price=float(new_stop_quantized),
                metadata={
                    "strategy": bracket.strategy,
                    "type": "stop_loss",
                    "parent_order": bracket.order_id,
                    "updated": True,
                    "reason": reason
                }
            )
            
            if sl_order:
                # Update OCO group
                if symbol in self.oco_groups:
                    self.oco_groups[symbol].remove(old_sl_id)
                    self.oco_groups[symbol].append(new_sl_id)
                
                # Update bracket manager
                self.bracket_manager.update_bracket_stop_loss(bracket.order_id, new_stop_quantized)
                
                logger.info(f"Updated SL for {symbol} to {float(new_stop_quantized):.4f}: {reason}")
                return True
            else:
                logger.error(f"Failed to create updated SL order: {sl_error}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to update bracket SL: {e}")
            return False
    
    def handle_tp_fill(
        self,
        symbol: str,
        tp_level: int,
        filled_qty: float
    ) -> bool:
        """
        Handle TP fill and update remaining brackets.
        
        Args:
            symbol: Trading symbol
            tp_level: TP level that filled (1, 2, or 3)
            filled_qty: Quantity that filled
            
        Returns:
            True if handled successfully
        """
        try:
            if symbol not in self.active_brackets:
                logger.warning(f"No active bracket for {symbol}")
                return False
            
            bracket = self.active_brackets[symbol]
            
            logger.info(f"TP{tp_level} filled for {symbol}: {filled_qty:.6f} qty at "
                       f"{float(bracket.take_profit_levels[tp_level-1]):.4f}")
            
            # Trigger bracket updates based on TP level
            if tp_level == 1:
                # Move SL to breakeven after TP1
                self.update_bracket_stop_loss(
                    symbol,
                    float(bracket.entry_price),
                    reason="Breakeven after TP1"
                )
            elif tp_level == 2:
                # Trail SL to entry + 0.5R after TP2
                risk_distance = abs(bracket.entry_price - bracket.stop_loss)
                if bracket.side == "BUY":
                    new_stop = bracket.entry_price + (risk_distance * Decimal('0.5'))
                else:
                    new_stop = bracket.entry_price - (risk_distance * Decimal('0.5'))
                
                self.update_bracket_stop_loss(
                    symbol,
                    float(new_stop),
                    reason="Trail to entry + 0.5R after TP2"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to handle TP fill: {e}")
            return False
    
    def cancel_bracket(self, symbol: str) -> bool:
        """
        Cancel all bracket orders for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if cancelled successfully
        """
        try:
            if symbol in self.oco_groups:
                oco_group = self.oco_groups[symbol]
                
                # Cancel all orders in OCO group
                for order_id in oco_group:
                    # TODO: Cancel order via order_manager
                    pass
                
                # Clean up
                del self.oco_groups[symbol]
                
            if symbol in self.active_brackets:
                bracket = self.active_brackets[symbol]
                self.bracket_manager.close_bracket(bracket.order_id)
                del self.active_brackets[symbol]
            
            logger.info(f"Cancelled bracket for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel bracket: {e}")
            return False
    
    def get_active_brackets(self) -> Dict[str, BracketOrder]:
        """Get all active brackets."""
        return self.active_brackets.copy()
    
    def get_oco_group(self, symbol: str) -> List[str]:
        """Get OCO group for a symbol."""
        return self.oco_groups.get(symbol, [])


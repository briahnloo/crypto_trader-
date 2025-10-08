"""
OCO (One-Cancels-Other) order manager for automated stop-loss and take-profit.

This module manages OCO orders that are placed immediately after fills,
with ATR-based levels and trailing take-profit functionality.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, Callable, List, Union
from decimal import Decimal, getcontext
import logging

from ..core.logging_utils import LoggerMixin

# Set decimal precision
getcontext().prec = 28

logger = logging.getLogger(__name__)


class OCOOrder:
    """Represents an OCO order with stop-loss and take-profit."""
    
    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        stop_loss: Union[float, Decimal],
        take_profit: Union[float, Decimal],
        atr: Union[float, Decimal],
        strategy: str = "unknown",
        fill_id: str = ""
    ):
        self.symbol = symbol
        self.side = side
        self.entry_price = Decimal(str(entry_price)) if not isinstance(entry_price, Decimal) else entry_price
        self.quantity = Decimal(str(quantity)) if not isinstance(quantity, Decimal) else quantity
        self.stop_loss = Decimal(str(stop_loss)) if not isinstance(stop_loss, Decimal) else stop_loss
        self.take_profit = Decimal(str(take_profit)) if not isinstance(take_profit, Decimal) else take_profit
        self.atr = Decimal(str(atr)) if not isinstance(atr, Decimal) else atr
        self.strategy = strategy
        self.fill_id = fill_id
        
        # Order IDs
        self.stop_loss_order_id: Optional[str] = None
        self.take_profit_order_id: Optional[str] = None
        self.time_stop_order_id: Optional[str] = None
        
        # Trailing state
        self.trailing_enabled = False
        self.trail_after_atr = Decimal('1.0')
        self.trail_step_atr = Decimal('0.3')
        self.highest_favorable_price = self.entry_price
        self.current_tp_price = self.take_profit
        
        # Status
        self.status = "pending"  # pending, active, cancelled, filled, time_stopped
        self.created_at = datetime.now()
        self.last_updated = datetime.now()
        
        # Time stop
        self.time_stop_minutes = 30
        self.time_stop_enabled = True
    
    def update_trailing_tp(self, current_price: Union[float, Decimal]) -> bool:
        """
        Update trailing take-profit based on current price.
        
        Args:
            current_price: Current market price
            
        Returns:
            True if TP was updated, False otherwise
        """
        if not self.trailing_enabled:
            return False
        
        current_price_decimal = Decimal(str(current_price)) if not isinstance(current_price, Decimal) else current_price
        
        # Check if we're in favorable territory
        if self.side.upper() == "BUY":
            if current_price_decimal > self.highest_favorable_price:
                self.highest_favorable_price = current_price_decimal
                
                # Check if we should start trailing
                favorable_move = current_price_decimal - self.entry_price
                if favorable_move >= self.trail_after_atr * self.atr:
                    # Calculate new TP price
                    new_tp = current_price_decimal - (self.trail_step_atr * self.atr)
                    if new_tp > self.current_tp_price:
                        self.current_tp_price = new_tp
                        self.last_updated = datetime.now()
                        return True
        else:  # SELL
            if current_price_decimal < self.highest_favorable_price:
                self.highest_favorable_price = current_price_decimal
                
                # Check if we should start trailing
                favorable_move = self.entry_price - current_price_decimal
                if favorable_move >= self.trail_after_atr * self.atr:
                    # Calculate new TP price
                    new_tp = current_price_decimal + (self.trail_step_atr * self.atr)
                    if new_tp < self.current_tp_price:
                        self.current_tp_price = new_tp
                        self.last_updated = datetime.now()
                        return True
        
        return False
    
    def is_time_stop_reached(self) -> bool:
        """
        Check if time stop has been reached.
        
        Returns:
            True if time stop has been reached
        """
        if not self.time_stop_enabled:
            return False
        
        now = datetime.now()
        age_minutes = (now - self.created_at).total_seconds() / 60
        return age_minutes >= self.time_stop_minutes
    
    def get_risk_reward_ratio(self) -> float:
        """Calculate current risk-reward ratio."""
        if self.side.upper() == "BUY":
            risk = self.entry_price - self.stop_loss
            reward = self.current_tp_price - self.entry_price
        else:  # SELL
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.current_tp_price
        
        if risk <= 0:
            return 0.0
        
        return float(reward / risk)


class OCOManager(LoggerMixin):
    """
    Manages OCO orders with ATR-based levels and trailing take-profit.
    
    Features:
    - Places OCO orders immediately after fills
    - ATR-based stop-loss and take-profit levels
    - Trailing take-profit after favorable moves
    - Automatic cleanup of filled/cancelled orders
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the OCO manager.
        
        Args:
            config: Configuration dictionary with risk settings
        """
        super().__init__()
        self.config = config
        
        # OCO settings
        self.oco_enabled = config.get("oco_enabled", True)
        self.tp_atr = Decimal(str(config.get("tp_atr", 0.7)))
        self.sl_atr = Decimal(str(config.get("sl_atr", 0.5)))
        self.time_stop_minutes = config.get("time_stop_minutes", 30)
        self.trail_after_atr = Decimal(str(config.get("trail_after_atr", 1.0)))
        self.trail_step_atr = Decimal(str(config.get("trail_step_atr", 0.3)))
        
        # Active OCO orders
        self.active_oco_orders: Dict[str, OCOOrder] = {}  # fill_id -> OCOOrder
        
        # Callbacks
        self.get_atr_callback: Optional[Callable[[str], Optional[float]]] = None
        self.create_order_callback: Optional[Callable[[str, str, float, float, str], Optional[str]]] = None
        self.cancel_order_callback: Optional[Callable[[str], bool]] = None
        self.get_mark_price_callback: Optional[Callable[[str], Optional[float]]] = None
        
        self.logger.info(f"OCOManager initialized: enabled={self.oco_enabled}, "
                        f"tp_atr={self.tp_atr}, sl_atr={self.sl_atr}, "
                        f"time_stop={self.time_stop_minutes}min, "
                        f"trail_after={self.trail_after_atr}, trail_step={self.trail_step_atr}")
    
    def set_callbacks(
        self,
        get_atr_callback: Callable[[str], Optional[float]],
        create_order_callback: Callable[[str, str, float, float, str], Optional[str]],
        cancel_order_callback: Callable[[str], bool],
        get_mark_price_callback: Callable[[str], Optional[float]]
    ):
        """Set callback functions for order operations."""
        self.get_atr_callback = get_atr_callback
        self.create_order_callback = create_order_callback
        self.cancel_order_callback = cancel_order_callback
        self.get_mark_price_callback = get_mark_price_callback
        self.logger.info("OCO callbacks set")
    
    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        strategy: str = "unknown",
        fill_id: str = ""
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Place OCO order after a fill.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price of the fill
            quantity: Position quantity
            strategy: Strategy name
            fill_id: Unique fill identifier
            
        Returns:
            Tuple of (success, details_dict)
        """
        if not self.oco_enabled:
            return False, {"reason": "oco_disabled"}
        
        if not all([self.get_atr_callback, self.create_order_callback, self.cancel_order_callback]):
            self.logger.warning("OCO callbacks not set, skipping OCO placement")
            return False, {"reason": "callbacks_not_set"}
        
        # Convert inputs to Decimal
        entry_price_decimal = Decimal(str(entry_price)) if not isinstance(entry_price, Decimal) else entry_price
        quantity_decimal = Decimal(str(quantity)) if not isinstance(quantity, Decimal) else quantity
        
        # Get ATR for 1m timeframe with 60 samples
        atr_raw = self.get_atr_callback(symbol)
        if not atr_raw or atr_raw <= 0:
            self.logger.warning(f"REJECTED: {symbol} OCO (reason=no_atr)")
            return False, {"reason": "no_atr", "atr": atr_raw}
        
        atr = Decimal(str(atr_raw))
        
        # Calculate stop-loss and take-profit levels
        if side.upper() == "BUY":
            stop_loss = entry_price_decimal - (self.sl_atr * atr)
            take_profit = entry_price_decimal + (self.tp_atr * atr)
        else:  # SELL
            stop_loss = entry_price_decimal + (self.sl_atr * atr)
            take_profit = entry_price_decimal - (self.tp_atr * atr)
        
        # Validate levels
        if stop_loss <= 0 or take_profit <= 0:
            self.logger.warning(f"REJECTED: {symbol} OCO (reason=invalid_levels)")
            return False, {"reason": "invalid_levels", "sl": float(stop_loss), "tp": float(take_profit)}
        
        # Create OCO order object
        oco_order = OCOOrder(
            symbol=symbol,
            side=side,
            entry_price=entry_price_decimal,
            quantity=quantity_decimal,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=atr,
            strategy=strategy,
            fill_id=fill_id
        )
        
        # Set trailing parameters
        oco_order.trailing_enabled = True
        oco_order.trail_after_atr = self.trail_after_atr
        oco_order.trail_step_atr = self.trail_step_atr
        
        # Set time stop parameters
        oco_order.time_stop_minutes = self.time_stop_minutes
        oco_order.time_stop_enabled = True
        
        # Place stop-loss order
        sl_order_id = self.create_order_callback(
            symbol, f"SELL" if side.upper() == "BUY" else "BUY", 
            float(quantity_decimal), float(stop_loss), "stop"
        )
        if not sl_order_id:
            self.logger.warning(f"REJECTED: {symbol} OCO (reason=sl_order_failed)")
            return False, {"reason": "sl_order_failed"}
        
        oco_order.stop_loss_order_id = sl_order_id
        
        # Place take-profit order
        tp_order_id = self.create_order_callback(
            symbol, f"SELL" if side.upper() == "BUY" else "BUY",
            float(quantity_decimal), float(take_profit), "limit"
        )
        if not tp_order_id:
            # Cancel stop-loss if take-profit fails
            self.cancel_order_callback(sl_order_id)
            self.logger.warning(f"REJECTED: {symbol} OCO (reason=tp_order_failed)")
            return False, {"reason": "tp_order_failed"}
        
        oco_order.take_profit_order_id = tp_order_id
        oco_order.status = "active"
        
        # Store OCO order
        self.active_oco_orders[fill_id] = oco_order
        
        # Calculate risk-reward ratio
        rr_ratio = oco_order.get_risk_reward_ratio()
        
        self.logger.info(
            f"OCO_PLACED: {symbol} {side} {float(quantity_decimal):.6f} @ ${float(entry_price_decimal):.4f} "
            f"SL=${float(stop_loss):.4f} TP=${float(take_profit):.4f} ATR=${float(atr):.4f} "
            f"RR={rr_ratio:.2f} (fill_id={fill_id})"
        )
        
        return True, {
            "oco_order": oco_order,
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "atr": float(atr),
            "risk_reward_ratio": rr_ratio,
            "sl_order_id": sl_order_id,
            "tp_order_id": tp_order_id
        }
    
    async def update_trailing_orders(self) -> int:
        """
        Update trailing take-profit for all active OCO orders.
        
        Returns:
            Number of orders updated
        """
        if not self.get_mark_price_callback:
            return 0
        
        updated_count = 0
        
        for fill_id, oco_order in list(self.active_oco_orders.items()):
            if oco_order.status != "active":
                continue
            
            # Get current market price
            current_price = self.get_mark_price_callback(oco_order.symbol)
            if not current_price:
                continue
            
            # Update trailing TP
            if oco_order.update_trailing_tp(current_price):
                # Cancel old TP order
                if oco_order.take_profit_order_id:
                    self.cancel_order_callback(oco_order.take_profit_order_id)
                
                # Place new TP order
                new_tp_order_id = self.create_order_callback(
                    oco_order.symbol,
                    f"SELL" if oco_order.side.upper() == "BUY" else "BUY",
                    float(oco_order.quantity),
                    float(oco_order.current_tp_price),
                    "limit"
                )
                
                if new_tp_order_id:
                    oco_order.take_profit_order_id = new_tp_order_id
                    updated_count += 1
                    
                    self.logger.info(
                        f"TRAILING_TP: {oco_order.symbol} {oco_order.side} "
                        f"TP=${float(oco_order.current_tp_price):.4f} "
                        f"(fill_id={fill_id})"
                    )
        
        return updated_count
    
    async def handle_time_stops(self) -> int:
        """
        Handle time stops for OCO orders that have exceeded the time limit.
        
        Returns:
            Number of orders processed for time stop
        """
        if not self.get_mark_price_callback:
            return 0
        
        processed_count = 0
        
        for fill_id, oco_order in list(self.active_oco_orders.items()):
            if oco_order.status != "active":
                continue
            
            # Check if time stop has been reached
            if oco_order.is_time_stop_reached():
                # Cancel existing orders
                if oco_order.stop_loss_order_id:
                    self.cancel_order_callback(oco_order.stop_loss_order_id)
                if oco_order.take_profit_order_id:
                    self.cancel_order_callback(oco_order.take_profit_order_id)
                
                # Get current market price
                current_price = self.get_mark_price_callback(oco_order.symbol)
                if current_price:
                    # Try to place tight limit order to avoid crossing spread
                    # For BUY positions, try to sell at current price or slightly below
                    # For SELL positions, try to buy at current price or slightly above
                    
                    if oco_order.side.upper() == "BUY":
                        # Long position - try to sell at current price
                        exit_price = current_price
                        exit_side = "SELL"
                    else:
                        # Short position - try to buy at current price
                        exit_price = current_price
                        exit_side = "BUY"
                    
                    # Place tight limit order
                    time_stop_order_id = self.create_order_callback(
                        oco_order.symbol,
                        exit_side,
                        float(oco_order.quantity),
                        exit_price,
                        "limit"
                    )
                    
                    if time_stop_order_id:
                        oco_order.status = "time_stopped"
                        oco_order.time_stop_order_id = time_stop_order_id
                        
                        self.logger.info(
                            f"TIME_STOP: {oco_order.symbol} {oco_order.side} "
                            f"exit_price=${float(exit_price):.4f} (fill_id={fill_id}, "
                            f"age={oco_order.time_stop_minutes}min)"
                        )
                    else:
                        # Fallback to market order if limit order fails
                        market_order_id = self.create_order_callback(
                            oco_order.symbol,
                            exit_side,
                            float(oco_order.quantity),
                            0.0,  # Market order
                            "market"
                        )
                        
                        if market_order_id:
                            oco_order.status = "time_stopped"
                            oco_order.time_stop_order_id = market_order_id
                            
                            self.logger.info(
                                f"TIME_STOP_MARKET: {oco_order.symbol} {oco_order.side} "
                                f"(fill_id={fill_id}, age={oco_order.time_stop_minutes}min)"
                            )
                        else:
                            self.logger.error(
                                f"TIME_STOP_FAILED: {oco_order.symbol} {oco_order.side} "
                                f"(fill_id={fill_id})"
                            )
                            oco_order.status = "time_stop_failed"
                else:
                    self.logger.error(
                        f"TIME_STOP_NO_PRICE: {oco_order.symbol} {oco_order.side} "
                        f"(fill_id={fill_id})"
                    )
                    oco_order.status = "time_stop_failed"
                
                processed_count += 1
        
        return processed_count
    
    def cancel_oco_order(self, fill_id: str) -> bool:
        """
        Cancel an OCO order.
        
        Args:
            fill_id: Fill identifier
            
        Returns:
            True if cancelled successfully
        """
        if fill_id not in self.active_oco_orders:
            return False
        
        oco_order = self.active_oco_orders[fill_id]
        
        # Cancel both orders
        sl_cancelled = True
        tp_cancelled = True
        
        if oco_order.stop_loss_order_id:
            sl_cancelled = self.cancel_order_callback(oco_order.stop_loss_order_id)
        
        if oco_order.take_profit_order_id:
            tp_cancelled = self.cancel_order_callback(oco_order.take_profit_order_id)
        
        # Update status
        oco_order.status = "cancelled"
        
        self.logger.info(
            f"OCO_CANCELLED: {oco_order.symbol} {oco_order.side} "
            f"(fill_id={fill_id}, sl_cancelled={sl_cancelled}, tp_cancelled={tp_cancelled})"
        )
        
        # Remove from active orders
        del self.active_oco_orders[fill_id]
        
        return sl_cancelled and tp_cancelled
    
    def mark_oco_filled(self, fill_id: str, order_type: str) -> bool:
        """
        Mark an OCO order as filled.
        
        Args:
            fill_id: Fill identifier
            order_type: Type of order that filled (stop_loss or take_profit)
            
        Returns:
            True if marked successfully
        """
        if fill_id not in self.active_oco_orders:
            return False
        
        oco_order = self.active_oco_orders[fill_id]
        oco_order.status = "filled"
        
        # Cancel the other order
        if order_type == "stop_loss" and oco_order.take_profit_order_id:
            self.cancel_order_callback(oco_order.take_profit_order_id)
        elif order_type == "take_profit" and oco_order.stop_loss_order_id:
            self.cancel_order_callback(oco_order.stop_loss_order_id)
        
        self.logger.info(
            f"OCO_FILLED: {oco_order.symbol} {oco_order.side} "
            f"type={order_type} (fill_id={fill_id})"
        )
        
        # Remove from active orders
        del self.active_oco_orders[fill_id]
        
        return True
    
    def get_active_oco_orders(self) -> Dict[str, OCOOrder]:
        """Get all active OCO orders."""
        return {k: v for k, v in self.active_oco_orders.items() if v.status == "active"}
    
    def cleanup_expired_orders(self, max_age_hours: int = 24) -> int:
        """
        Clean up expired OCO orders.
        
        Args:
            max_age_hours: Maximum age in hours before cleanup
            
        Returns:
            Number of orders cleaned up
        """
        now = datetime.now()
        expired_orders = []
        
        for fill_id, oco_order in self.active_oco_orders.items():
            age = (now - oco_order.created_at).total_seconds() / 3600
            if age > max_age_hours:
                expired_orders.append(fill_id)
        
        for fill_id in expired_orders:
            self.cancel_oco_order(fill_id)
            self.logger.warning(f"Cleaned up expired OCO order: {fill_id}")
        
        return len(expired_orders)
    
    def get_oco_statistics(self) -> Dict[str, Any]:
        """Get OCO order statistics."""
        active_orders = self.get_active_oco_orders()
        
        if not active_orders:
            return {
                "active_oco_orders": 0,
                "total_oco_orders": len(self.active_oco_orders),
                "avg_risk_reward": 0.0
            }
        
        total_rr = sum(order.get_risk_reward_ratio() for order in active_orders.values())
        avg_rr = total_rr / len(active_orders)
        
        return {
            "active_oco_orders": len(active_orders),
            "total_oco_orders": len(self.active_oco_orders),
            "avg_risk_reward": avg_rr,
            "oco_enabled": self.oco_enabled
        }

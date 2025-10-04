"""
Post-only order router for maker-only trading.

This module implements post-only order routing that places limit orders
at the best bid/ask and cancels them if not filled within the specified
time window. This prevents crossing the spread and paying taker fees.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, Callable
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class PostOnlyOrderRouter(LoggerMixin):
    """
    Post-only order router that places limit orders at best bid/ask.
    
    Features:
    - Places longs at best bid, shorts at best ask
    - Waits for maker fills within time window
    - Cancels unfilled orders (no taker fallback)
    - Logs maker fill status and wait times
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the post-only order router.
        
        Args:
            config: Configuration dictionary with execution settings
        """
        super().__init__()
        self.config = config
        
        # Post-only settings
        self.post_only = config.get("post_only", True)
        self.max_wait_seconds = config.get("post_only_max_wait_seconds", 5)
        self.allow_taker_fallback = config.get("allow_taker_fallback", False)
        
        # Order tracking
        self.active_orders: Dict[str, Dict[str, Any]] = {}  # order_id -> order_info
        
        self.logger.info(f"PostOnlyOrderRouter initialized: post_only={self.post_only}, "
                        f"max_wait={self.max_wait_seconds}s, "
                        f"taker_fallback={self.allow_taker_fallback}")
    
    async def route_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        get_ticker_callback: Callable[[str], Optional[Dict[str, Any]]],
        create_order_callback: Callable[[str, str, float, float, str], Optional[str]],
        cancel_order_callback: Callable[[str], bool],
        check_fill_callback: Callable[[str], bool]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Route an order using post-only logic.
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            quantity: Order quantity
            get_ticker_callback: Function to get ticker data
            create_order_callback: Function to create orders
            cancel_order_callback: Function to cancel orders
            check_fill_callback: Function to check if order is filled
            
        Returns:
            Tuple of (success, details_dict)
        """
        if not self.post_only:
            # Post-only disabled, use market orders
            return await self._execute_market_order(
                symbol, side, quantity, create_order_callback
            )
        
        # Get current ticker data
        ticker_data = get_ticker_callback(symbol)
        if not ticker_data:
            self.logger.warning(f"REJECTED: {symbol} {side} (reason=no_ticker_data)")
            return False, {"reason": "no_ticker_data"}
        
        bid = ticker_data.get('bid')
        ask = ticker_data.get('ask')
        
        if not bid or not ask or bid <= 0 or ask <= 0:
            self.logger.warning(f"REJECTED: {symbol} {side} (reason=invalid_bid_ask)")
            return False, {"reason": "invalid_bid_ask", "bid": bid, "ask": ask}
        
        # Determine limit price based on side
        if side.upper() == "BUY":
            limit_price = bid  # Buy at best bid (maker)
            order_type = "limit_buy"
        else:
            limit_price = ask  # Sell at best ask (maker)
            order_type = "limit_sell"
        
        # Create limit order
        order_id = create_order_callback(symbol, side, quantity, limit_price, "limit")
        if not order_id:
            self.logger.warning(f"REJECTED: {symbol} {side} (reason=order_creation_failed)")
            return False, {"reason": "order_creation_failed"}
        
        # Track order
        order_info = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "limit_price": limit_price,
            "order_type": order_type,
            "created_at": datetime.now(),
            "status": "pending"
        }
        self.active_orders[order_id] = order_info
        
        self.logger.info(f"POST_ONLY: {symbol} {side} {quantity:.6f} @ ${limit_price:.4f} "
                        f"(order_id={order_id})")
        
        # Wait for fill with timeout
        fill_result = await self._wait_for_fill(
            order_id, symbol, side, quantity, limit_price,
            cancel_order_callback, check_fill_callback
        )
        
        # Clean up tracking
        if order_id in self.active_orders:
            del self.active_orders[order_id]
        
        return fill_result
    
    async def _wait_for_fill(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        limit_price: float,
        cancel_order_callback: Callable[[str], bool],
        check_fill_callback: Callable[[str], bool]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Wait for order to fill within the time window.
        
        Args:
            order_id: Order identifier
            symbol: Trading symbol
            side: Order side
            quantity: Order quantity
            limit_price: Limit price
            cancel_order_callback: Function to cancel orders
            check_fill_callback: Function to check fills
            
        Returns:
            Tuple of (success, details_dict)
        """
        start_time = time.time()
        end_time = start_time + self.max_wait_seconds
        
        self.logger.debug(f"Waiting for fill: {order_id} (max_wait={self.max_wait_seconds}s)")
        
        while time.time() < end_time:
            # Check if order is filled
            if check_fill_callback(order_id):
                wait_time = time.time() - start_time
                self.logger.info(f"MAKER_FILL: {symbol} {side} {quantity:.6f} @ ${limit_price:.4f} "
                               f"(order_id={order_id}, wait_time={wait_time:.2f}s)")
                
                return True, {
                    "maker_fill": True,
                    "wait_time_seconds": wait_time,
                    "final_status": "filled",
                    "order_id": order_id,
                    "limit_price": limit_price
                }
            
            # Small delay to avoid busy waiting
            await asyncio.sleep(0.1)
        
        # Timeout reached, cancel order
        wait_time = time.time() - start_time
        cancel_success = cancel_order_callback(order_id)
        
        if cancel_success:
            self.logger.info(f"ORDER_CANCELLED: {symbol} {side} {quantity:.6f} @ ${limit_price:.4f} "
                           f"(order_id={order_id}, wait_time={wait_time:.2f}s, reason=timeout)")
            
            if self.allow_taker_fallback:
                # Convert to market order (if enabled)
                return await self._execute_market_order_fallback(
                    symbol, side, quantity, order_id
                )
            else:
                # No taker fallback, order cancelled
                return False, {
                    "maker_fill": False,
                    "wait_time_seconds": wait_time,
                    "final_status": "cancelled_timeout",
                    "order_id": order_id,
                    "limit_price": limit_price,
                    "reason": "timeout_no_fallback"
                }
        else:
            self.logger.error(f"ORDER_CANCEL_FAILED: {symbol} {side} {quantity:.6f} @ ${limit_price:.4f} "
                            f"(order_id={order_id}, wait_time={wait_time:.2f}s)")
            
            return False, {
                "maker_fill": False,
                "wait_time_seconds": wait_time,
                "final_status": "cancel_failed",
                "order_id": order_id,
                "limit_price": limit_price,
                "reason": "cancel_failed"
            }
    
    async def _execute_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        create_order_callback: Callable[[str, str, float, float, str], Optional[str]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute a market order (when post-only is disabled).
        
        Args:
            symbol: Trading symbol
            side: Order side
            quantity: Order quantity
            create_order_callback: Function to create orders
            
        Returns:
            Tuple of (success, details_dict)
        """
        order_id = create_order_callback(symbol, side, quantity, 0.0, "market")
        if order_id:
            self.logger.info(f"MARKET_ORDER: {symbol} {side} {quantity:.6f} (order_id={order_id})")
            return True, {
                "maker_fill": False,
                "wait_time_seconds": 0.0,
                "final_status": "market_filled",
                "order_id": order_id,
                "order_type": "market"
            }
        else:
            return False, {
                "maker_fill": False,
                "wait_time_seconds": 0.0,
                "final_status": "market_failed",
                "reason": "order_creation_failed"
            }
    
    async def _execute_market_order_fallback(
        self,
        symbol: str,
        side: str,
        quantity: float,
        original_order_id: str
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute market order fallback after limit order timeout.
        
        Args:
            symbol: Trading symbol
            side: Order side
            quantity: Order quantity
            original_order_id: Original limit order ID
            
        Returns:
            Tuple of (success, details_dict)
        """
        self.logger.info(f"TAKER_FALLBACK: {symbol} {side} {quantity:.6f} "
                        f"(original_order_id={original_order_id})")
        
        # This would need to be implemented with actual order creation
        # For now, return failure since we don't have the callback
        return False, {
            "maker_fill": False,
            "wait_time_seconds": self.max_wait_seconds,
            "final_status": "fallback_failed",
            "original_order_id": original_order_id,
            "reason": "fallback_not_implemented"
        }
    
    def get_active_orders(self) -> Dict[str, Dict[str, Any]]:
        """Get currently active orders."""
        return self.active_orders.copy()
    
    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific order."""
        return self.active_orders.get(order_id)
    
    def cleanup_expired_orders(self, max_age_seconds: int = 300) -> int:
        """
        Clean up orders that have been active too long.
        
        Args:
            max_age_seconds: Maximum age for orders before cleanup
            
        Returns:
            Number of orders cleaned up
        """
        now = datetime.now()
        expired_orders = []
        
        for order_id, order_info in self.active_orders.items():
            age = (now - order_info["created_at"]).total_seconds()
            if age > max_age_seconds:
                expired_orders.append(order_id)
        
        for order_id in expired_orders:
            del self.active_orders[order_id]
            self.logger.warning(f"Cleaned up expired order: {order_id}")
        
        return len(expired_orders)

"""
Order builder with precision quantization for exchange compliance.

This module provides order building utilities that enforce exchange-specific
precision requirements and handle auto-quantization to prevent PRECISION_FAIL errors.
"""

import math
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

from ..core.logging_utils import LoggerMixin


class OrderBuilder(LoggerMixin):
    """
    Order builder with precision quantization and validation.
    
    Handles:
    - Price rounding to tick size
    - Quantity rounding to step size
    - Minimum quantity and notional validation
    - Auto-bumping to minimum notional when required
    """
    
    def __init__(self):
        """Initialize the order builder."""
        super().__init__()
    
    def build_order(
        self,
        symbol: str,
        raw_price: float,
        target_notional: float,
        symbol_rules: Dict[str, Any],
        per_trade_cap: Optional[float] = None,
        max_retries: int = 1
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Build a quantized order with precision compliance.
        
        Args:
            symbol: Trading symbol
            raw_price: Raw price from market data
            target_notional: Target notional value in dollars
            symbol_rules: Symbol trading rules (price_tick, qty_step, min_qty, min_notional)
            per_trade_cap: Maximum per-trade notional cap (optional)
            max_retries: Maximum number of retry attempts
            
        Returns:
            Tuple of (order_data, error_reason) where:
            - order_data: Dict with quantized price, quantity, and validation info
            - error_reason: None if successful, error message if failed
        """
        try:
            # Extract symbol rules
            price_tick = symbol_rules.get("price_tick", 0.01)
            qty_step = symbol_rules.get("qty_step", 0.001)
            min_qty = symbol_rules.get("min_qty", 0.001)
            min_notional = symbol_rules.get("min_notional", 10.0)
            
            # Validate inputs
            if raw_price <= 0:
                return None, "Invalid price: must be greater than 0"
            
            if target_notional <= 0:
                return None, "Invalid target notional: must be greater than 0"
            
            # Check per-trade cap if provided
            if per_trade_cap and target_notional > per_trade_cap:
                return None, f"Target notional ${target_notional:.2f} exceeds per-trade cap ${per_trade_cap:.2f}"
            
            # Attempt to build order with retries
            for attempt in range(max_retries + 1):
                try:
                    order_data = self._build_quantized_order(
                        symbol=symbol,
                        raw_price=raw_price,
                        target_notional=target_notional,
                        price_tick=price_tick,
                        qty_step=qty_step,
                        min_qty=min_qty,
                        min_notional=min_notional,
                        attempt=attempt
                    )
                    
                    if order_data:
                        return order_data, None
                    
                except Exception as e:
                    self.logger.warning(f"Order build attempt {attempt + 1} failed: {e}")
                    if attempt == max_retries:
                        return None, f"Order build failed after {max_retries + 1} attempts: {e}"
            
            return None, f"Order build failed after {max_retries + 1} attempts"
            
        except Exception as e:
            self.logger.error(f"Order builder error for {symbol}: {e}")
            return None, f"Order builder error: {e}"
    
    def _build_quantized_order(
        self,
        symbol: str,
        raw_price: float,
        target_notional: float,
        price_tick: float,
        qty_step: float,
        min_qty: float,
        min_notional: float,
        attempt: int
    ) -> Optional[Dict[str, Any]]:
        """Build a single quantized order attempt.
        
        Args:
            symbol: Trading symbol
            raw_price: Raw price from market data
            target_notional: Target notional value
            price_tick: Price tick size
            qty_step: Quantity step size
            min_qty: Minimum quantity
            min_notional: Minimum notional
            attempt: Attempt number (for retry logic)
            
        Returns:
            Order data dictionary or None if failed
        """
        # Step 1: Round price to tick size
        quantized_price = self._round_to_tick(raw_price, price_tick)
        
        # Step 2: Calculate raw quantity from target notional
        qty_raw = target_notional / quantized_price
        
        # Step 3: Round quantity down to step size (conservative approach)
        quantized_qty = self._round_down_to_step(qty_raw, qty_step)
        
        # Step 4: Check minimum quantity constraint
        if quantized_qty < min_qty:
            # Try bumping to minimum quantity
            quantized_qty = min_qty
            
            # Check if this creates a notional that's too large
            bumped_notional = quantized_qty * quantized_price
            if attempt == 0:  # Only on first attempt
                # Try with bumped notional
                return self._build_quantized_order(
                    symbol, raw_price, bumped_notional, price_tick, qty_step, min_qty, min_notional, attempt + 1
                )
            else:
                # On retry, accept the minimum quantity
                pass
        
        # Step 5: Check minimum notional constraint
        final_notional = quantized_qty * quantized_price
        if final_notional < min_notional:
            # Try bumping to minimum notional
            bumped_target_notional = min_notional
            
            if attempt == 0:  # Only on first attempt
                # Try with bumped notional
                return self._build_quantized_order(
                    symbol, raw_price, bumped_target_notional, price_tick, qty_step, min_qty, min_notional, attempt + 1
                )
            else:
                # On retry, accept the minimum notional
                quantized_qty = min_notional / quantized_price
                quantized_qty = self._round_down_to_step(quantized_qty, qty_step)
                final_notional = quantized_qty * quantized_price
        
        # Step 6: Final validation
        if quantized_qty < min_qty:
            return None  # Still below minimum quantity
        
        if final_notional < min_notional:
            return None  # Still below minimum notional
        
        # Step 7: Log quantization details
        self.logger.info(
            f"ORDER_QUANTIZE: tick={price_tick}, step={qty_step}, min_qty={min_qty}, min_notional={min_notional}, "
            f"in: price={raw_price:.8f}, qty_raw={qty_raw:.8f}, out: price={quantized_price:.8f}, qty={quantized_qty:.8f}"
        )
        
        return {
            "symbol": symbol,
            "price": quantized_price,
            "quantity": quantized_qty,
            "notional": final_notional,
            "original_price": raw_price,
            "original_target_notional": target_notional,
            "price_tick": price_tick,
            "qty_step": qty_step,
            "min_qty": min_qty,
            "min_notional": min_notional,
            "attempt": attempt
        }
    
    def _round_to_tick(self, price: float, tick_size: float) -> float:
        """Round price to tick size.
        
        Args:
            price: Raw price
            tick_size: Minimum price increment
            
        Returns:
            Price rounded to tick size
        """
        if tick_size <= 0:
            return price
        
        # Use Decimal for precise arithmetic
        price_decimal = Decimal(str(price))
        tick_decimal = Decimal(str(tick_size))
        
        # Round to nearest tick
        rounded = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick_decimal
        
        return float(rounded)
    
    def _round_down_to_step(self, quantity: float, step_size: float) -> float:
        """Round quantity down to step size (conservative approach).
        
        Args:
            quantity: Raw quantity
            step_size: Minimum quantity increment
            
        Returns:
            Quantity rounded down to step size
        """
        if step_size <= 0:
            return quantity
        
        # Use Decimal for precise arithmetic
        qty_decimal = Decimal(str(quantity))
        step_decimal = Decimal(str(step_size))
        
        # Round down to step size
        rounded = (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_decimal
        
        return float(rounded)
    
    def validate_order_precision(
        self,
        symbol: str,
        price: float,
        quantity: float,
        symbol_rules: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """Validate that order meets precision requirements.
        
        Args:
            symbol: Trading symbol
            price: Order price
            quantity: Order quantity
            symbol_rules: Symbol trading rules
            
        Returns:
            Tuple of (is_valid, error_reason)
        """
        try:
            price_tick = symbol_rules.get("price_tick", 0.01)
            qty_step = symbol_rules.get("qty_step", 0.001)
            min_qty = symbol_rules.get("min_qty", 0.001)
            min_notional = symbol_rules.get("min_notional", 10.0)
            
            # Check price tick alignment
            if not self._is_aligned_to_tick(price, price_tick):
                return False, f"Price {price} not aligned to tick size {price_tick}"
            
            # Check quantity step alignment
            if not self._is_aligned_to_step(quantity, qty_step):
                return False, f"Quantity {quantity} not aligned to step size {qty_step}"
            
            # Check minimum quantity
            if quantity < min_qty:
                return False, f"Quantity {quantity} below minimum {min_qty}"
            
            # Check minimum notional
            notional = price * quantity
            if notional < min_notional:
                return False, f"Notional ${notional:.2f} below minimum ${min_notional:.2f}"
            
            return True, None
            
        except Exception as e:
            return False, f"Validation error: {e}"
    
    def _is_aligned_to_tick(self, price: float, tick_size: float) -> bool:
        """Check if price is aligned to tick size.
        
        Args:
            price: Price to check
            tick_size: Tick size
            
        Returns:
            True if aligned, False otherwise
        """
        if tick_size <= 0:
            return True
        
        # Use tolerance for floating-point comparison
        remainder = abs(price % tick_size)
        return remainder < 1e-6 or abs(remainder - tick_size) < 1e-6
    
    def _is_aligned_to_step(self, quantity: float, step_size: float) -> bool:
        """Check if quantity is aligned to step size.
        
        Args:
            quantity: Quantity to check
            step_size: Step size
            
        Returns:
            True if aligned, False otherwise
        """
        if step_size <= 0:
            return True
        
        # Use tolerance for floating-point comparison
        remainder = abs(quantity % step_size)
        return remainder < 1e-6 or abs(remainder - step_size) < 1e-6

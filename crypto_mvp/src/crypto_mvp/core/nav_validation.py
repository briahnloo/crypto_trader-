"""
NAV (Net Asset Value) validation system.

This module provides functionality to rebuild portfolio state from TradeLedger events
using a PricingSnapshot and validate it against computed equity.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from .logging_utils import LoggerMixin
from .decimal_money import to_decimal, quantize_currency, safe_multiply, safe_divide
from .pricing_snapshot import PricingSnapshot


class NAVValidationResult:
    """Result of NAV validation."""
    
    def __init__(self, is_valid: bool, difference: float, tolerance: float, 
                 rebuilt_cash: float, rebuilt_positions_value: float, 
                 rebuilt_realized_pnl: float, rebuilt_equity: float,
                 computed_equity: float, error_message: Optional[str] = None):
        self.is_valid = is_valid
        self.difference = difference
        self.tolerance = tolerance
        self.rebuilt_cash = rebuilt_cash
        self.rebuilt_positions_value = rebuilt_positions_value
        self.rebuilt_realized_pnl = rebuilt_realized_pnl
        self.rebuilt_equity = rebuilt_equity
        self.computed_equity = computed_equity
        self.error_message = error_message


class NAVRebuilder(LoggerMixin):
    """
    Rebuilds portfolio state from TradeLedger events using a PricingSnapshot.
    
    This class processes trade events chronologically to reconstruct:
    - Cash balance
    - Position quantities and values
    - Realized P&L
    - Total equity
    """
    
    def __init__(self, initial_cash: float = 0.0):
        """Initialize the NAV rebuilder.
        
        Args:
            initial_cash: Starting cash balance
        """
        super().__init__()
        self.initial_cash = to_decimal(initial_cash)
        
    def rebuild_from_ledger(
        self, 
        trades: List[Dict[str, Any]], 
        pricing_snapshot: PricingSnapshot,
        initial_cash: Optional[float] = None
    ) -> Tuple[float, Dict[str, Dict[str, Any]], float, float]:
        """
        Rebuild portfolio state from trade ledger events.
        
        Args:
            trades: List of trade events from TradeLedger
            pricing_snapshot: PricingSnapshot to use for position valuation
            initial_cash: Starting cash balance (overrides constructor value)
            
        Returns:
            Tuple of (cash_balance, positions, realized_pnl, total_equity)
        """
        self.logger.info(f"NAV_REBUILD_START: Starting rebuild with {len(trades)} trades")
        # Start with initial cash
        cash = to_decimal(initial_cash) if initial_cash is not None else self.initial_cash
        
        # Track positions by symbol
        positions = {}  # symbol -> {quantity, entry_price, total_cost, realized_pnl}
        
        # Track realized P&L
        total_realized_pnl = to_decimal(0.0)
        
        # Process trades chronologically
        sorted_trades = sorted(trades, key=lambda t: t.get('executed_at', ''))
        self.logger.info(f"NAV_REBUILD: Processing {len(sorted_trades)} trades")
        
        for i, trade in enumerate(sorted_trades):
            self.logger.info(f"NAV_REBUILD: Trade {i+1}: {trade.get('symbol', 'unknown')} {trade.get('side', 'unknown')} {trade.get('quantity', 0)} @ {trade.get('fill_price', 0)}")
            self.logger.info(f"NAV_REBUILD: Trade {i+1} full data: {trade}")
            try:
                symbol = trade.get('symbol', '')
                side = trade.get('side', '').lower()
                quantity = to_decimal(trade.get('quantity', 0.0))
                fill_price = to_decimal(trade.get('fill_price', 0.0))
                fees = to_decimal(trade.get('fees', 0.0))
                
                self.logger.info(f"NAV_REBUILD: Parsed - symbol='{symbol}' side='{side}' quantity={quantity} fill_price={fill_price} fees={fees}")
                
                if not symbol or quantity == 0 or fill_price == 0:
                    continue
                
                # Calculate notional value
                notional_value = safe_multiply(abs(quantity), fill_price)
                
                # Update cash balance
                if side == 'buy':
                    # Buying: reduce cash by notional value + fees
                    total_cost = notional_value + fees
                    cash -= total_cost
                elif side == 'sell':
                    # Selling: increase cash by notional value, reduce by fees
                    cash += notional_value - fees
                else:
                    self.logger.warning(f"Unknown trade side: {side}")
                    continue
                
                # Update position
                if symbol not in positions:
                    positions[symbol] = {
                        'quantity': to_decimal(0.0),
                        'entry_price': to_decimal(0.0),
                        'total_cost': to_decimal(0.0),
                        'realized_pnl': to_decimal(0.0)
                    }
                
                pos = positions[symbol]
                current_quantity = pos['quantity']
                current_entry_price = pos['entry_price']
                current_total_cost = pos['total_cost']
                
                if side == 'buy':
                    # Adding to position
                    new_quantity = current_quantity + quantity
                    if new_quantity != 0:
                        # Calculate weighted average entry price (notional value only, no fees)
                        new_total_notional = current_total_cost + notional_value
                        new_entry_price = safe_divide(new_total_notional, new_quantity)
                        
                        pos['quantity'] = new_quantity
                        pos['entry_price'] = new_entry_price
                        pos['total_cost'] = new_total_notional
                    else:
                        # Position closed
                        pos['quantity'] = to_decimal(0.0)
                        pos['entry_price'] = to_decimal(0.0)
                        pos['total_cost'] = to_decimal(0.0)
                        
                elif side == 'sell':
                    # Reducing position
                    new_quantity = current_quantity - quantity
                    
                    if current_quantity != 0:
                        # Calculate realized P&L for this trade
                        # P&L = (sell_price - entry_price) * quantity
                        trade_pnl = safe_multiply(fill_price - current_entry_price, quantity)
                        pos['realized_pnl'] += trade_pnl
                        total_realized_pnl += trade_pnl
                        
                        # Update total cost (reduce by notional value of sold quantity)
                        pos['total_cost'] -= notional_value
                    
                    if new_quantity != 0:
                        # Position remains open
                        pos['quantity'] = new_quantity
                        # Keep entry price for remaining position
                    else:
                        # Position closed
                        pos['quantity'] = to_decimal(0.0)
                        pos['entry_price'] = to_decimal(0.0)
                        pos['total_cost'] = to_decimal(0.0)
                
            except Exception as e:
                self.logger.error(f"Error processing trade {trade.get('trade_id', 'unknown')}: {e}")
                continue
        
        # Calculate current position values using pricing snapshot
        total_positions_value = to_decimal(0.0)
        self.logger.info(f"NAV_REBUILD: Processing {len(positions)} positions")
        for symbol, pos in positions.items():
            quantity = pos['quantity']
            self.logger.info(f"NAV_REBUILD: Symbol={symbol} quantity={quantity}")
            if quantity != 0:
                # Get current price from snapshot
                price_data = pricing_snapshot.get_mark_price(symbol)
                if price_data is not None:
                    # Handle both PriceData object and float return types
                    if hasattr(price_data, 'price'):
                        current_price = to_decimal(price_data.price)
                    else:
                        current_price = to_decimal(price_data)
                    
                    position_value = safe_multiply(quantity, current_price)
                    total_positions_value += position_value
                    
                    # Update position with current value
                    pos['current_price'] = current_price
                    pos['value'] = position_value
                    
                    self.logger.info(f"NAV_REBUILD: {symbol} qty={quantity} price={current_price} value={position_value}")
                else:
                    self.logger.warning(f"NAV_REBUILD: No price available for {symbol} in snapshot")
                    pos['current_price'] = to_decimal(0.0)
                    pos['value'] = to_decimal(0.0)
        
        # Calculate total equity
        # Match the computed equity calculation: total_equity = cash + positions_value + realized_pnl
        total_equity = cash + total_positions_value + total_realized_pnl
        
        # Convert back to float for compatibility
        return (
            float(quantize_currency(cash, "USDT")),
            {symbol: {k: float(v) if isinstance(v, Decimal) else v for k, v in pos.items()} 
             for symbol, pos in positions.items()},
            float(quantize_currency(total_realized_pnl, "USDT")),
            float(quantize_currency(total_equity, "USDT"))
        )


class NAVValidator(LoggerMixin):
    """
    Validates NAV consistency by rebuilding from TradeLedger and comparing with computed equity.
    """
    
    def __init__(self, tolerance: float = 1.00):
        """Initialize the NAV validator.
        
        Args:
            tolerance: Maximum allowed difference between rebuilt and computed equity
        """
        super().__init__()
        self.tolerance = tolerance
        self.rebuilder = NAVRebuilder()
        
    def validate_nav(
        self,
        trades: List[Dict[str, Any]],
        pricing_snapshot: PricingSnapshot,
        computed_equity: float,
        initial_cash: float = 0.0
    ) -> NAVValidationResult:
        """
        Validate NAV by rebuilding from TradeLedger and comparing with computed equity.
        
        Args:
            trades: List of trade events from TradeLedger
            pricing_snapshot: PricingSnapshot to use for position valuation
            computed_equity: The computed equity to validate against
            initial_cash: Starting cash balance
            
        Returns:
            NAVValidationResult with validation details
        """
        self.logger.info(f"NAV_VALIDATOR_START: Starting validation with {len(trades)} trades")
        try:
            # Rebuild portfolio from ledger
            self.logger.info(f"NAV_VALIDATOR_CALL: Calling rebuilder with {len(trades)} trades")
            self.logger.info(f"NAV_VALIDATOR_CALL: initial_cash={initial_cash}")
            self.logger.info(f"NAV_VALIDATOR_CALL: pricing_snapshot={pricing_snapshot}")
            self.rebuilder.initial_cash = initial_cash
            rebuilt_cash, rebuilt_positions, rebuilt_realized_pnl, rebuilt_equity = \
                self.rebuilder.rebuild_from_ledger(trades, pricing_snapshot, initial_cash)
            self.logger.info(f"NAV_VALIDATOR_CALL: Rebuilder returned cash={rebuilt_cash} equity={rebuilt_equity}")
            
            # Calculate positions value
            rebuilt_positions_value = sum(pos.get('value', 0.0) for pos in rebuilt_positions.values())
            
            # Calculate difference
            difference = abs(rebuilt_equity - computed_equity)
            
            # Determine if valid
            is_valid = difference <= self.tolerance
            
            # Create result
            result = NAVValidationResult(
                is_valid=is_valid,
                difference=difference,
                tolerance=self.tolerance,
                rebuilt_cash=rebuilt_cash,
                rebuilt_positions_value=rebuilt_positions_value,
                rebuilt_realized_pnl=rebuilt_realized_pnl,
                rebuilt_equity=rebuilt_equity,
                computed_equity=computed_equity,
                error_message=None if is_valid else f"NAV validation failed: difference ${difference:.4f} > tolerance ${self.tolerance:.4f}"
            )
            
            # Log validation result
            if is_valid:
                self.logger.debug(
                    f"NAV_VALIDATION_PASS: rebuilt=${rebuilt_equity:.2f} "
                    f"computed=${computed_equity:.2f} diff=${difference:.4f} "
                    f"tolerance=${self.tolerance:.4f}"
                )
            else:
                self.logger.error(
                    f"NAV_VALIDATION_FAIL: rebuilt=${rebuilt_equity:.2f} "
                    f"computed=${computed_equity:.2f} diff=${difference:.4f} "
                    f"tolerance=${self.tolerance:.4f}"
                )
            
            return result
            
        except Exception as e:
            error_msg = f"NAV validation error: {e}"
            self.logger.error(error_msg)
            
            return NAVValidationResult(
                is_valid=False,
                difference=float('inf'),
                tolerance=self.tolerance,
                rebuilt_cash=0.0,
                rebuilt_positions_value=0.0,
                rebuilt_realized_pnl=0.0,
                rebuilt_equity=0.0,
                computed_equity=computed_equity,
                error_message=error_msg
            )

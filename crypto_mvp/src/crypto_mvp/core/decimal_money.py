"""
Decimal-only money math with deterministic quantization.

This module provides utilities for precise financial calculations using decimal.Decimal
to avoid floating-point precision errors that can cause pennies→dollars drift.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext
from typing import Union, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Set high precision for decimal calculations
getcontext().prec = 28

# Precision map for different asset types
PrecisionMap = {
    "USDT": 2,      # 2 decimal places for USD
    "USD": 2,       # 2 decimal places for USD
    "BTC_qty": 8,   # 8 decimal places for BTC quantity
    "ETH_qty": 8,   # 8 decimal places for ETH quantity
    "default_qty": 8,  # Default quantity precision
    "default_currency": 2,  # Default currency precision
}

def to_decimal(value: Union[str, int, float, Decimal]) -> Decimal:
    """
    Convert any numeric value to Decimal.
    
    Args:
        value: Value to convert (str, int, float, or Decimal)
        
    Returns:
        Decimal representation of the value
    """
    if isinstance(value, Decimal):
        return value
    elif isinstance(value, (int, float)):
        return Decimal(str(value))
    elif isinstance(value, str):
        return Decimal(value)
    else:
        raise TypeError(f"Cannot convert {type(value)} to Decimal")

def quantize_currency(value: Decimal, currency: str = "USDT") -> Decimal:
    """
    Quantize a currency value to the appropriate precision.
    
    Args:
        value: Decimal value to quantize
        currency: Currency code (default: "USDT")
        
    Returns:
        Quantized Decimal value
    """
    precision = PrecisionMap.get(currency, PrecisionMap["default_currency"])
    quantizer = Decimal('0.' + '0' * precision)
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)

def quantize_quantity(value: Decimal, symbol: str = None) -> Decimal:
    """
    Quantize a quantity value to the appropriate precision based on symbol.
    
    Args:
        value: Decimal value to quantize
        symbol: Trading symbol (e.g., "BTC/USDT") to determine precision
        
    Returns:
        Quantized Decimal value
    """
    if symbol:
        if "BTC" in symbol.upper():
            precision = PrecisionMap["BTC_qty"]
        elif "ETH" in symbol.upper():
            precision = PrecisionMap["ETH_qty"]
        else:
            precision = PrecisionMap["default_qty"]
    else:
        precision = PrecisionMap["default_qty"]
    
    quantizer = Decimal('0.' + '0' * precision)
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)

def calculate_notional(quantity: Decimal, price: Decimal) -> Decimal:
    """
    Calculate notional value (quantity * price) using decimal arithmetic.
    
    Args:
        quantity: Decimal quantity
        price: Decimal price
        
    Returns:
        Decimal notional value
    """
    return quantity * price

def calculate_fees(notional: Decimal, fee_rate: Decimal) -> Decimal:
    """
    Calculate fees using decimal arithmetic.
    
    Args:
        notional: Decimal notional value
        fee_rate: Decimal fee rate (e.g., 0.001 for 0.1%)
        
    Returns:
        Decimal fee amount
    """
    return notional * fee_rate

def calculate_pnl(quantity: Decimal, entry_price: Decimal, current_price: Decimal) -> Decimal:
    """
    Calculate P&L using decimal arithmetic.
    
    Args:
        quantity: Decimal quantity
        entry_price: Decimal entry price
        current_price: Decimal current price
        
    Returns:
        Decimal P&L value
    """
    return quantity * (current_price - entry_price)

def calculate_position_value(quantity: Decimal, current_price: Decimal) -> Decimal:
    """
    Calculate position value using decimal arithmetic.
    
    Args:
        quantity: Decimal quantity
        current_price: Decimal current price
        
    Returns:
        Decimal position value
    """
    return quantity * current_price

def format_currency(value: Decimal, currency: str = "USDT", show_symbol: bool = True) -> str:
    """
    Format a decimal value as currency string.
    
    Args:
        value: Decimal value to format
        currency: Currency code
        show_symbol: Whether to include currency symbol
        
    Returns:
        Formatted currency string
    """
    precision = PrecisionMap.get(currency, PrecisionMap["default_currency"])
    formatted = f"{value:,.{precision}f}"
    
    if show_symbol:
        return f"{currency} {formatted}"
    else:
        return formatted

def format_quantity(value: Decimal, symbol: str = None) -> str:
    """
    Format a decimal quantity as string.
    
    Args:
        value: Decimal value to format
        symbol: Trading symbol to determine precision
        
    Returns:
        Formatted quantity string
    """
    if symbol:
        if "BTC" in symbol.upper():
            precision = PrecisionMap["BTC_qty"]
        elif "ETH" in symbol.upper():
            precision = PrecisionMap["ETH_qty"]
        else:
            precision = PrecisionMap["default_qty"]
    else:
        precision = PrecisionMap["default_qty"]
    
    return f"{value:,.{precision}f}"

def safe_divide(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal('0')) -> Decimal:
    """
    Safely divide two decimals, returning default if denominator is zero.
    
    Args:
        numerator: Decimal numerator
        denominator: Decimal denominator
        default: Default value if division by zero
        
    Returns:
        Decimal result or default
    """
    if denominator == 0:
        logger.warning(f"Division by zero: {numerator} / {denominator}, returning {default}")
        return default
    return numerator / denominator

def safe_multiply(a: Decimal, b: Decimal) -> Decimal:
    """
    Safely multiply two decimals with overflow protection.
    
    Args:
        a: First decimal value
        b: Second decimal value
        
    Returns:
        Decimal result
    """
    try:
        return a * b
    except Exception as e:
        logger.error(f"Multiplication overflow: {a} * {b}, error: {e}")
        return Decimal('0')

def validate_decimal_precision(value: Decimal, expected_precision: int, context: str = "") -> bool:
    """
    Validate that a decimal value has the expected precision.
    
    Args:
        value: Decimal value to validate
        expected_precision: Expected number of decimal places
        context: Context string for logging
        
    Returns:
        True if precision is correct, False otherwise
    """
    # Convert to string and check decimal places
    value_str = str(value)
    if '.' in value_str:
        decimal_places = len(value_str.split('.')[1])
        if decimal_places > expected_precision:
            logger.warning(f"Precision validation failed in {context}: {value} has {decimal_places} decimal places, expected {expected_precision}")
            return False
    return True

def convert_float_to_decimal_safe(value: float, context: str = "") -> Decimal:
    """
    Safely convert float to Decimal, handling potential precision issues.
    
    Args:
        value: Float value to convert
        context: Context string for logging
        
    Returns:
        Decimal representation
    """
    try:
        # Convert to string first to avoid floating point precision issues
        return Decimal(str(value))
    except Exception as e:
        logger.error(f"Failed to convert float to Decimal in {context}: {value}, error: {e}")
        return Decimal('0')

def round_to_precision(value: Decimal, precision: int, rounding: str = "HALF_UP") -> Decimal:
    """
    Round a decimal value to specified precision.
    
    Args:
        value: Decimal value to round
        precision: Number of decimal places
        rounding: Rounding mode ("HALF_UP", "DOWN", etc.)
        
    Returns:
        Rounded Decimal value
    """
    quantizer = Decimal('0.' + '0' * precision)
    
    if rounding.upper() == "HALF_UP":
        return value.quantize(quantizer, rounding=ROUND_HALF_UP)
    elif rounding.upper() == "DOWN":
        return value.quantize(quantizer, rounding=ROUND_DOWN)
    else:
        return value.quantize(quantizer, rounding=ROUND_HALF_UP)

def sum_decimals(values: list[Decimal]) -> Decimal:
    """
    Sum a list of decimal values safely.
    
    Args:
        values: List of Decimal values
        
    Returns:
        Sum as Decimal
    """
    if not values:
        return Decimal('0')
    
    result = Decimal('0')
    for value in values:
        result += to_decimal(value)
    
    return result

def max_decimal(values: list[Decimal]) -> Decimal:
    """
    Find maximum value in a list of decimals.
    
    Args:
        values: List of Decimal values
        
    Returns:
        Maximum Decimal value
    """
    if not values:
        return Decimal('0')
    
    return max(to_decimal(v) for v in values)

def min_decimal(values: list[Decimal]) -> Decimal:
    """
    Find minimum value in a list of decimals.
    
    Args:
        values: List of Decimal values
        
    Returns:
        Minimum Decimal value
    """
    if not values:
        return Decimal('0')
    
    return min(to_decimal(v) for v in values)

def abs_decimal(value: Decimal) -> Decimal:
    """
    Get absolute value of a decimal.
    
    Args:
        value: Decimal value
        
    Returns:
        Absolute value as Decimal
    """
    return abs(to_decimal(value))

def is_positive(value: Decimal) -> bool:
    """
    Check if a decimal value is positive.
    
    Args:
        value: Decimal value
        
    Returns:
        True if positive, False otherwise
    """
    return to_decimal(value) > 0

def is_negative(value: Decimal) -> bool:
    """
    Check if a decimal value is negative.
    
    Args:
        value: Decimal value
        
    Returns:
        True if negative, False otherwise
    """
    return to_decimal(value) < 0

def is_zero(value: Decimal) -> bool:
    """
    Check if a decimal value is zero.
    
    Args:
        value: Decimal value
        
    Returns:
        True if zero, False otherwise
    """
    return to_decimal(value) == 0

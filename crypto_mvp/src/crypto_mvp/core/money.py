"""
Safe Decimal-based money handling for accounting paths.

This module provides helpers to eliminate float/Decimal mixing in financial calculations,
ensuring consistent precision across all accounting operations.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext
from typing import Dict, Union

# Set precision to 28 decimal places for financial calculations
getcontext().prec = 28

# Common Decimal constants
ZERO = Decimal("0")
ONE = Decimal("1")

# Money quantization to 2 decimal places (cents)
MONEY_Q = Decimal("0.01")


def D(x) -> Decimal:
    """
    Convert any numeric type to Decimal safely.
    
    Args:
        x: Value to convert (int, float, str, or Decimal)
        
    Returns:
        Decimal representation of the input
        
    Examples:
        >>> D(100)
        Decimal('100')
        >>> D(99.99)
        Decimal('99.99')
        >>> D("123.45")
        Decimal('123.45')
    """
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int, str)):
        return Decimal(str(x))
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(str(x))


def q_money(x: Decimal) -> Decimal:
    """
    Quantize a Decimal to money precision (2 decimal places).
    
    Args:
        x: Decimal value to quantize
        
    Returns:
        Decimal quantized to cents with ROUND_HALF_UP
        
    Examples:
        >>> q_money(D("123.456"))
        Decimal('123.46')
        >>> q_money(D("99.994"))
        Decimal('99.99')
    """
    return D(x).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def ensure_decimal(*values) -> bool:
    """
    Check that all values are Decimal instances.
    
    Args:
        *values: Variable number of values to check
        
    Returns:
        True if all values are Decimal, False otherwise
        
    Raises:
        ValueError: If any value is not a Decimal (when used with assert)
    """
    return all(isinstance(v, Decimal) for v in values)


def safe_add(*values) -> Decimal:
    """
    Safely add multiple values after converting to Decimal.
    
    Args:
        *values: Variable number of values to add
        
    Returns:
        Sum of all values as Decimal
    """
    return sum((D(v) for v in values), start=Decimal("0"))


def safe_subtract(a, b) -> Decimal:
    """
    Safely subtract b from a after converting to Decimal.
    
    Args:
        a: Minuend
        b: Subtrahend
        
    Returns:
        a - b as Decimal
    """
    return D(a) - D(b)


def safe_multiply(a, b) -> Decimal:
    """
    Safely multiply two values after converting to Decimal.
    
    Args:
        a: First multiplicand
        b: Second multiplicand
        
    Returns:
        a * b as Decimal
    """
    return D(a) * D(b)


def safe_divide(a, b) -> Decimal:
    """
    Safely divide a by b after converting to Decimal.
    
    Args:
        a: Numerator
        b: Denominator
        
    Returns:
        a / b as Decimal
        
    Raises:
        ZeroDivisionError: If b is zero
    """
    if D(b) == Decimal("0"):
        raise ZeroDivisionError("Division by zero")
    return D(a) / D(b)


# Aliases for compatibility with existing code
def to_dec(x) -> Decimal:
    """
    Alias for D() - convert to Decimal.
    Provided for compatibility with existing code.
    """
    return D(x)


def quantize_price(price: Union[Decimal, float, int, str], symbol: str = "") -> Decimal:
    """
    Quantize price to appropriate precision.
    
    Args:
        price: Price value to quantize
        symbol: Trading symbol (optional, for symbol-specific precision)
        
    Returns:
        Quantized price as Decimal
    """
    # Default to 2 decimal places for prices
    # This can be customized per symbol if needed
    price_d = D(price)
    
    # Use symbol-specific steps if available
    if symbol:
        steps = get_exchange_steps(symbol)
        return price_d.quantize(steps["price_step"], rounding=ROUND_HALF_UP)
    
    # Default: 2 decimal places for prices
    return price_d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quantize_qty(quantity: Union[Decimal, float, int, str], symbol: str = "") -> Decimal:
    """
    Quantize quantity to appropriate precision.
    
    Args:
        quantity: Quantity value to quantize
        symbol: Trading symbol (optional, for symbol-specific precision)
        
    Returns:
        Quantized quantity as Decimal
    """
    qty_d = D(quantity)
    
    # Use symbol-specific steps if available
    if symbol:
        steps = get_exchange_steps(symbol)
        return qty_d.quantize(steps["qty_step"], rounding=ROUND_DOWN)
    
    # Default: 6 decimal places for quantities
    return qty_d.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


def get_exchange_steps(symbol: str) -> Dict[str, Decimal]:
    """
    Get exchange step sizes for a given symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Dictionary with price_step and qty_step as Decimals
    """
    # Default steps - can be customized per symbol
    # These are typical for major crypto exchanges
    
    # Symbol-specific overrides
    symbol_steps = {
        "BTC/USDT": {"price_step": Decimal("0.01"), "qty_step": Decimal("0.00001")},
        "BTC-USD": {"price_step": Decimal("0.01"), "qty_step": Decimal("0.00001")},
        "ETH/USDT": {"price_step": Decimal("0.01"), "qty_step": Decimal("0.0001")},
        "ETH-USD": {"price_step": Decimal("0.01"), "qty_step": Decimal("0.0001")},
        "SOL/USDT": {"price_step": Decimal("0.001"), "qty_step": Decimal("0.001")},
        "SOL-USD": {"price_step": Decimal("0.001"), "qty_step": Decimal("0.001")},
        "ADA/USDT": {"price_step": Decimal("0.0001"), "qty_step": Decimal("0.1")},
        "ADA-USD": {"price_step": Decimal("0.0001"), "qty_step": Decimal("0.1")},
        "DOGE/USDT": {"price_step": Decimal("0.00001"), "qty_step": Decimal("1")},
        "DOGE-USD": {"price_step": Decimal("0.00001"), "qty_step": Decimal("1")},
        "XRP/USDT": {"price_step": Decimal("0.0001"), "qty_step": Decimal("0.1")},
        "XRP-USD": {"price_step": Decimal("0.0001"), "qty_step": Decimal("0.1")},
    }
    
    # Return symbol-specific steps or defaults
    return symbol_steps.get(
        symbol,
        {"price_step": Decimal("0.01"), "qty_step": Decimal("0.000001")}
    )

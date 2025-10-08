"""
Enhanced money helper for Decimal-only monetary math with exchange step quantization.

This module provides:
- to_dec(x): Convert any numeric to Decimal with single precision context
- Exchange-specific quantization maps (price_step, qty_step, notional_step)
- Safe Decimal operations for all monetary calculations

Usage:
    from crypto_mvp.core.money import to_dec, quantize_price, quantize_qty
    
    price = to_dec(100.50)
    qty = to_dec("0.001")
    notional = price * qty  # Always Decimal * Decimal
    
    # Quantize to exchange steps
    final_price = quantize_price(price, "BTC/USDT")
    final_qty = quantize_qty(qty, "BTC/USDT")
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext
from typing import Union, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Set global precision for all Decimal operations
getcontext().prec = 28

# Exchange step sizes per symbol (can be updated from exchange info)
EXCHANGE_STEPS = {
    "BTC/USDT": {
        "price_step": Decimal("0.01"),      # $0.01 tick size
        "qty_step": Decimal("0.00001"),     # 5 decimal places
        "notional_step": Decimal("0.01"),   # $0.01 minimum
        "min_notional": Decimal("10.00")    # $10 minimum order
    },
    "ETH/USDT": {
        "price_step": Decimal("0.01"),
        "qty_step": Decimal("0.0001"),      # 4 decimal places
        "notional_step": Decimal("0.01"),
        "min_notional": Decimal("10.00")
    },
    "ADA/USDT": {
        "price_step": Decimal("0.0001"),    # $0.0001 tick size
        "qty_step": Decimal("0.1"),         # 1 decimal place
        "notional_step": Decimal("0.01"),
        "min_notional": Decimal("10.00")
    },
    "SOL/USDT": {
        "price_step": Decimal("0.01"),
        "qty_step": Decimal("0.01"),
        "notional_step": Decimal("0.01"),
        "min_notional": Decimal("10.00")
    },
    "DEFAULT": {
        "price_step": Decimal("0.01"),
        "qty_step": Decimal("0.00001"),
        "notional_step": Decimal("0.01"),
        "min_notional": Decimal("10.00")
    }
}


def to_dec(value: Union[str, int, float, Decimal, None]) -> Decimal:
    """
    Convert any numeric value to Decimal with single precision context.
    
    This is the ONLY function that should be used to convert to Decimal
    to ensure consistent precision handling across the codebase.
    
    Args:
        value: Value to convert (str, int, float, Decimal, or None)
        
    Returns:
        Decimal representation of the value (Decimal('0') for None)
        
    Examples:
        >>> to_dec(100.5)
        Decimal('100.5')
        >>> to_dec("0.005")
        Decimal('0.005')
        >>> to_dec(None)
        Decimal('0')
    """
    if value is None:
        return Decimal('0')
    elif isinstance(value, Decimal):
        return value
    elif isinstance(value, (int, float)):
        return Decimal(str(value))
    elif isinstance(value, str):
        try:
            return Decimal(value)
        except Exception as e:
            logger.error(f"Failed to convert string '{value}' to Decimal: {e}")
            return Decimal('0')
    else:
        logger.warning(f"Unexpected type {type(value)} for to_dec, attempting conversion")
        return Decimal(str(value))


def get_exchange_steps(symbol: str) -> Dict[str, Decimal]:
    """
    Get exchange step sizes for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        
    Returns:
        Dictionary with price_step, qty_step, notional_step, min_notional
    """
    # Normalize symbol format
    normalized = symbol.replace("-", "/").upper()
    return EXCHANGE_STEPS.get(normalized, EXCHANGE_STEPS["DEFAULT"])


def quantize_price(price: Union[float, Decimal, str], symbol: str) -> Decimal:
    """
    Quantize price to exchange tick size.
    
    Args:
        price: Price value to quantize
        symbol: Trading symbol
        
    Returns:
        Quantized price as Decimal
        
    Example:
        >>> quantize_price(100.523, "BTC/USDT")
        Decimal('100.52')  # Rounded to $0.01 tick
    """
    price_dec = to_dec(price)
    steps = get_exchange_steps(symbol)
    price_step = steps["price_step"]
    
    # Quantize to nearest tick
    return (price_dec / price_step).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * price_step


def quantize_qty(quantity: Union[float, Decimal, str], symbol: str) -> Decimal:
    """
    Quantize quantity to exchange lot size.
    
    Args:
        quantity: Quantity value to quantize
        symbol: Trading symbol
        
    Returns:
        Quantized quantity as Decimal
        
    Example:
        >>> quantize_qty(0.123456, "BTC/USDT")
        Decimal('0.12346')  # Rounded to 5 decimals
    """
    qty_dec = to_dec(quantity)
    steps = get_exchange_steps(symbol)
    qty_step = steps["qty_step"]
    
    # Quantize to nearest lot size
    return (qty_dec / qty_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * qty_step


def quantize_notional(notional: Union[float, Decimal, str], symbol: str) -> Decimal:
    """
    Quantize notional value to exchange minimum.
    
    Args:
        notional: Notional value to quantize
        symbol: Trading symbol
        
    Returns:
        Quantized notional as Decimal
    """
    notional_dec = to_dec(notional)
    steps = get_exchange_steps(symbol)
    notional_step = steps["notional_step"]
    
    return (notional_dec / notional_step).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * notional_step


def validate_order_size(
    price: Union[float, Decimal, str],
    quantity: Union[float, Decimal, str],
    symbol: str
) -> tuple[bool, str]:
    """
    Validate order meets exchange minimums.
    
    Args:
        price: Order price
        quantity: Order quantity
        symbol: Trading symbol
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    price_dec = to_dec(price)
    qty_dec = to_dec(quantity)
    steps = get_exchange_steps(symbol)
    
    if price_dec <= 0:
        return False, f"Price must be positive: {price_dec}"
    
    if qty_dec <= 0:
        return False, f"Quantity must be positive: {qty_dec}"
    
    notional = price_dec * qty_dec
    min_notional = steps["min_notional"]
    
    if notional < min_notional:
        return False, f"Notional ${notional} below minimum ${min_notional}"
    
    return True, ""


def calculate_position_size_from_risk(
    entry_price: Union[float, Decimal, str],
    stop_loss: Union[float, Decimal, str],
    risk_amount: Union[float, Decimal, str],
    symbol: str
) -> Decimal:
    """
    Calculate position size based on risk amount.
    
    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        risk_amount: Dollar amount to risk
        symbol: Trading symbol
        
    Returns:
        Position size as Decimal
        
    Example:
        >>> calculate_position_size_from_risk(100, 95, 50, "BTC/USDT")
        Decimal('10.00000')  # Risk $50 with $5 stop = 10 units
    """
    entry_dec = to_dec(entry_price)
    stop_dec = to_dec(stop_loss)
    risk_dec = to_dec(risk_amount)
    
    risk_per_unit = abs(entry_dec - stop_dec)
    
    if risk_per_unit == 0:
        logger.error("Risk per unit is zero, cannot calculate position size")
        return Decimal('0')
    
    position_size = risk_dec / risk_per_unit
    
    # Quantize to exchange lot size
    return quantize_qty(position_size, symbol)


def calculate_tp_ladder(
    entry_price: Union[float, Decimal, str],
    stop_loss: Union[float, Decimal, str],
    side: str,
    symbol: str,
    reward_ratios: Optional[list[Union[float, Decimal, str]]] = None
) -> list[Decimal]:
    """
    Calculate take profit ladder levels using Decimal.
    
    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        side: Position side ("long"/"buy" or "short"/"sell")
        symbol: Trading symbol
        reward_ratios: List of reward:risk ratios (default: [1.0, 1.5, 2.0])
        
    Returns:
        List of take profit prices as Decimal
        
    Example:
        >>> calculate_tp_ladder(100, 95, "buy", "BTC/USDT")
        [Decimal('105.00'), Decimal('107.50'), Decimal('110.00')]
    """
    entry_dec = to_dec(entry_price)
    stop_dec = to_dec(stop_loss)
    
    # Default reward ratios: 1R, 1.5R, 2R
    if reward_ratios is None:
        ratios = [to_dec("1.0"), to_dec("1.5"), to_dec("2.0")]
    else:
        ratios = [to_dec(r) for r in reward_ratios]
    
    # Calculate risk distance
    risk_distance = abs(entry_dec - stop_dec)
    
    # Calculate TP levels
    tp_levels = []
    is_long = side.lower() in ['long', 'buy', 'b']
    
    for ratio in ratios:
        reward_distance = risk_distance * ratio
        
        if is_long:
            tp_price = entry_dec + reward_distance
        else:
            tp_price = entry_dec - reward_distance
        
        # Quantize to exchange tick size
        tp_quantized = quantize_price(tp_price, symbol)
        tp_levels.append(tp_quantized)
    
    logger.info(f"Created {len(tp_levels)} TP levels for {symbol}: {[float(tp) for tp in tp_levels]}")
    
    return tp_levels


def calculate_sl_level(
    entry_price: Union[float, Decimal, str],
    atr: Union[float, Decimal, str],
    side: str,
    symbol: str,
    atr_multiplier: Union[float, Decimal, str] = "2.0"
) -> Decimal:
    """
    Calculate stop loss level using ATR-based approach.
    
    Args:
        entry_price: Entry price
        atr: Average True Range value
        side: Position side ("long"/"buy" or "short"/"sell")
        symbol: Trading symbol
        atr_multiplier: ATR multiplier (default: 2.0)
        
    Returns:
        Stop loss price as Decimal
        
    Example:
        >>> calculate_sl_level(100, 2.5, "buy", "BTC/USDT", "2.0")
        Decimal('95.00')  # Entry - (2.0 * 2.5)
    """
    entry_dec = to_dec(entry_price)
    atr_dec = to_dec(atr)
    mult_dec = to_dec(atr_multiplier)
    
    is_long = side.lower() in ['long', 'buy', 'b']
    
    stop_distance = atr_dec * mult_dec
    
    if is_long:
        sl_price = entry_dec - stop_distance
    else:
        sl_price = entry_dec + stop_distance
    
    # Quantize to exchange tick size
    sl_quantized = quantize_price(sl_price, symbol)
    
    logger.info(f"Created SL level for {symbol} at {float(sl_quantized)}")
    
    return sl_quantized


def calculate_trailing_stop(
    peak_price: Union[float, Decimal, str],
    atr: Union[float, Decimal, str],
    side: str,
    symbol: str,
    atr_multiplier: Union[float, Decimal, str] = "2.0"
) -> Decimal:
    """
    Calculate trailing stop (Chandelier) using peak price and ATR.
    
    Args:
        peak_price: Peak price since position opened
        atr: Average True Range value
        side: Position side ("long"/"buy" or "short"/"sell")
        symbol: Trading symbol
        atr_multiplier: ATR multiplier (default: 2.0)
        
    Returns:
        Trailing stop price as Decimal
    """
    peak_dec = to_dec(peak_price)
    atr_dec = to_dec(atr)
    mult_dec = to_dec(atr_multiplier)
    
    is_long = side.lower() in ['long', 'buy', 'b']
    
    trail_distance = atr_dec * mult_dec
    
    if is_long:
        trail_price = peak_dec - trail_distance
    else:
        trail_price = peak_dec + trail_distance
    
    # Quantize to exchange tick size
    return quantize_price(trail_price, symbol)


# Convenience constants as Decimal
ZERO = Decimal('0')
ONE = Decimal('1')
TWO = Decimal('2')
HALF = Decimal('0.5')

# Common percentages as Decimal
PCT_1 = Decimal('0.01')      # 1%
PCT_2 = Decimal('0.02')      # 2%
PCT_5 = Decimal('0.05')      # 5%
PCT_10 = Decimal('0.10')     # 10%
PCT_50 = Decimal('0.50')     # 50%
PCT_100 = Decimal('1.00')    # 100%

# Fee rates as Decimal
FEE_MAKER_BPS = Decimal('0.0001')   # 1 bps
FEE_TAKER_BPS = Decimal('0.0002')   # 2 bps


# Re-export common functions from decimal_money for compatibility
from .decimal_money import (
    format_currency,
    format_quantity,
    safe_divide,
    safe_multiply,
    sum_decimals,
    abs_decimal,
    is_positive,
    is_negative,
    is_zero
)

__all__ = [
    # Core conversion
    'to_dec',
    
    # Quantization
    'quantize_price',
    'quantize_qty',
    'quantize_notional',
    'get_exchange_steps',
    
    # Validation
    'validate_order_size',
    
    # Calculations
    'calculate_position_size_from_risk',
    'calculate_tp_ladder',
    'calculate_sl_level',
    'calculate_trailing_stop',
    
    # Constants
    'ZERO', 'ONE', 'TWO', 'HALF',
    'PCT_1', 'PCT_2', 'PCT_5', 'PCT_10', 'PCT_50', 'PCT_100',
    'FEE_MAKER_BPS', 'FEE_TAKER_BPS',
    
    # Re-exported
    'format_currency',
    'format_quantity',
    'safe_divide',
    'safe_multiply',
    'sum_decimals',
    'abs_decimal',
    'is_positive',
    'is_negative',
    'is_zero'
]


"""
Market pricing and ATR accessor for crypto trading bot.

This module provides hardened executable pricing with retry logic
and ATR calculation for risk management.
"""

from typing import Optional, Dict
import logging
import time

logger = logging.getLogger(__name__)

# Cache for ATR values per symbol per cycle
_atr_cache: Dict[str, float] = {}


def get_executable_price(symbol: str) -> Optional[float]:
    """
    Get executable price with retry logic and fallback sources.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        
    Returns:
        Executable price or None if not available
    """
    # Try primary source: best bid/ask
    price = _get_primary_price(symbol)
    if price and price > 0:
        return price
    
    # Try secondary source: last trade
    price = _get_secondary_price(symbol)
    if price and price > 0:
        return price
    
    # Retry once with fresh fetch (not cached)
    logger.debug(f"Retrying price fetch for {symbol}")
    time.sleep(0.1)  # Small delay to avoid rate limiting
    
    # Try primary again
    price = _get_primary_price(symbol, use_cache=False)
    if price and price > 0:
        return price
    
    # Try secondary again
    price = _get_secondary_price(symbol, use_cache=False)
    if price and price > 0:
        return price
    
    logger.warning(f"No executable price available for {symbol}")
    return None


def _get_primary_price(symbol: str, use_cache: bool = True) -> Optional[float]:
    """
    Get price from primary source (best bid/ask).
    
    In a real implementation, this would connect to your primary exchange API.
    """
    # Mock implementation - in reality this would call exchange API
    mock_prices = {
        "BTC/USDT": 50000.0,
        "ETH/USDT": 3000.0,
        "BNB/USDT": 300.0,
        "ADA/USDT": 0.5,
        "SOL/USDT": 100.0,
        "DOT/USDT": 7.0,
        "LINK/USDT": 15.0,
        "UNI/USDT": 6.0
    }
    
    # Simulate occasional failures for testing
    import random
    if random.random() < 0.1:  # 10% failure rate
        return None
    
    return mock_prices.get(symbol)


def _get_secondary_price(symbol: str, use_cache: bool = True) -> Optional[float]:
    """
    Get price from secondary source (last trade).
    
    In a real implementation, this would connect to a backup data source.
    """
    # Mock implementation - slightly different prices to simulate spread
    mock_prices = {
        "BTC/USDT": 49995.0,
        "ETH/USDT": 2998.0,
        "BNB/USDT": 299.5,
        "ADA/USDT": 0.499,
        "SOL/USDT": 99.8,
        "DOT/USDT": 6.95,
        "LINK/USDT": 14.95,
        "UNI/USDT": 5.95
    }
    
    # Simulate occasional failures for testing
    import random
    if random.random() < 0.15:  # 15% failure rate
        return None
    
    return mock_prices.get(symbol)


def get_atr(symbol: str, lookback: int = 14) -> Optional[float]:
    """
    Get Average True Range (ATR) for a symbol.
    
    Args:
        symbol: Trading symbol
        lookback: Number of periods for ATR calculation
        
    Returns:
        ATR value or None if not available
    """
    # Check cache first
    cache_key = f"{symbol}_{lookback}"
    if cache_key in _atr_cache:
        return _atr_cache[cache_key]
    
    # Calculate ATR from OHLCV data
    atr_value = _calculate_atr(symbol, lookback)
    
    if atr_value and atr_value > 0:
        # Cache the result
        _atr_cache[cache_key] = atr_value
        return atr_value
    
    return None


def _calculate_atr(symbol: str, lookback: int) -> Optional[float]:
    """
    Calculate ATR from OHLCV data.
    
    In a real implementation, this would fetch historical data
    and calculate the ATR using the standard formula.
    """
    # Mock ATR values based on symbol volatility
    mock_atr = {
        "BTC/USDT": 1500.0,  # ~3% of price
        "ETH/USDT": 90.0,    # ~3% of price
        "BNB/USDT": 9.0,     # ~3% of price
        "ADA/USDT": 0.015,   # ~3% of price
        "SOL/USDT": 3.0,     # ~3% of price
        "DOT/USDT": 0.21,    # ~3% of price
        "LINK/USDT": 0.45,   # ~3% of price
        "UNI/USDT": 0.18,    # ~3% of price
    }
    
    # Simulate occasional missing ATR data
    import random
    if random.random() < 0.2:  # 20% chance of missing ATR
        return None
    
    return mock_atr.get(symbol)


def clear_atr_cache():
    """Clear ATR cache (call at start of each cycle)."""
    global _atr_cache
    _atr_cache.clear()


def get_mark_price(symbol: str) -> Optional[float]:
    """
    Get mark price for portfolio valuation.
    
    This is a simpler version that doesn't need retry logic
    since it's used for valuation, not execution.
    """
    return _get_primary_price(symbol)


def validate_price(price: Optional[float], symbol: str) -> bool:
    """
    Validate that a price is reasonable for a symbol.
    
    Args:
        price: Price to validate
        symbol: Symbol for context
        
    Returns:
        True if price is valid
    """
    if price is None or price <= 0:
        return False
    
    # Basic sanity checks based on symbol
    price_ranges = {
        "BTC/USDT": (10000.0, 100000.0),
        "ETH/USDT": (500.0, 10000.0),
        "BNB/USDT": (50.0, 1000.0),
        "ADA/USDT": (0.1, 10.0),
        "SOL/USDT": (10.0, 500.0),
        "DOT/USDT": (1.0, 50.0),
        "LINK/USDT": (2.0, 100.0),
        "UNI/USDT": (1.0, 50.0),
    }
    
    min_price, max_price = price_ranges.get(symbol, (0.01, 1000000.0))
    
    if price < min_price or price > max_price:
        logger.warning(f"Price {price} for {symbol} outside expected range [{min_price}, {max_price}]")
        return False
    
    return True

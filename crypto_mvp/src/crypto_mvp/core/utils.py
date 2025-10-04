"""
Utility functions for the Crypto MVP application.
"""

import asyncio
import random
import re
import time
from decimal import ROUND_DOWN, Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Union, Optional
from contextlib import contextmanager

import aiohttp
import requests
from loguru import logger

# Cycle-local cache for debounced mark price logging
_logged_mark_prices_this_cycle: set = set()


# Canonical symbol mapping
CANONICAL_SYMBOLS = {
    # Binance format (already canonical)
    "BTC/USDT": "BTC/USDT",
    "ETH/USDT": "ETH/USDT",
    "BNB/USDT": "BNB/USDT",
    "ADA/USDT": "ADA/USDT",
    "SOL/USDT": "SOL/USDT",
    
    # Coinbase format
    "BTC-USD": "BTC/USDT",
    "ETH-USD": "ETH/USDT",
    "BNB-USD": "BNB/USDT",
    "ADA-USD": "ADA/USDT",
    "SOL-USD": "SOL/USDT",
    
    # Alternative formats
    "BTCUSDT": "BTC/USDT",
    "ETHUSDT": "ETH/USDT",
    "BNBUSDT": "BNB/USDT",
    "ADAUSDT": "ADA/USDT",
    "SOLUSDT": "SOL/USDT",
}

# Price sanity bands
PRICE_SANITY_BANDS = {
    "BTC": {"min": 5000, "max": 500000},
    "ETH": {"min": 100, "max": 20000},
    "SOL": {"min": 1, "max": 1000},
    "ADA": {"min": 0.01, "max": 10},
    "BNB": {"min": 10, "max": 2000},
}


def to_canonical(symbol: str) -> str:
    """
    Convert any symbol format to canonical format (e.g., BTC/USDT).
    
    Args:
        symbol: Symbol in any format (e.g., BTC-USD, BTCUSDT, BTC/USDT)
    
    Returns:
        Canonical symbol format (e.g., BTC/USDT)
    """
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    
    # Normalize to uppercase for lookup
    normalized = symbol.upper().strip()
    
    # Check if already canonical
    if normalized in CANONICAL_SYMBOLS:
        return CANONICAL_SYMBOLS[normalized]
    
    # Try to construct canonical format if not in mapping
    # Handle formats like BTC-USD -> BTC/USDT
    if '-' in normalized:
        base, quote = normalized.split('-', 1)
        if quote in ['USD', 'USDT']:
            return f"{base}/USDT"
    
    # Handle formats like BTCUSDT -> BTC/USDT
    if 'USDT' in normalized and '/' not in normalized:
        base = normalized.replace('USDT', '')
        return f"{base}/USDT"
    
    # If no conversion found, return as-is (assume already canonical)
    return normalized


def get_version() -> str:
    """Get the application version.

    Returns:
        Version string
    """
    return "0.1.0"


def validate_config(config: dict[str, Any]) -> bool:
    """Validate configuration dictionary.

    Args:
        config: Configuration dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    required_sections = ["app", "exchanges", "trading", "strategies"]

    for section in required_sections:
        if section not in config:
            return False

    return True


def format_currency(
    amount: Union[float, Decimal, str], currency: str = "USD", precision: int = 2
) -> str:
    """Format amount as currency.

    Args:
        amount: Amount to format
        currency: Currency symbol
        precision: Decimal precision

    Returns:
        Formatted currency string
    """
    if isinstance(amount, str):
        amount = float(amount)

    if isinstance(amount, float):
        amount = Decimal(str(amount))

    # Round down to avoid rounding errors
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    return f"{currency} {amount:,.{precision}f}"


def format_percentage(value: Union[float, Decimal, str], precision: int = 2) -> str:
    """Format value as percentage.

    Args:
        value: Value to format (0.1 = 10%)
        precision: Decimal precision

    Returns:
        Formatted percentage string
    """
    if isinstance(value, str):
        value = float(value)

    if isinstance(value, float):
        value = Decimal(str(value))

    percentage = value * 100
    return f"{percentage:.{precision}f}%"


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Float value or default
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Integer value or default
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def clean_symbol(symbol: str) -> str:
    """Clean and normalize trading symbol.

    Args:
        symbol: Trading symbol to clean

    Returns:
        Cleaned symbol
    """
    # Remove spaces and convert to uppercase
    symbol = symbol.strip().upper()

    # Replace common separators with forward slash
    symbol = re.sub(r"[-_]", "/", symbol)

    return symbol


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change between two values.

    Args:
        old_value: Original value
        new_value: New value

    Returns:
        Percentage change (0.1 = 10% increase)
    """
    if old_value == 0:
        return 0.0

    return (new_value - old_value) / old_value


def calculate_compound_return(returns: list[float]) -> float:
    """Calculate compound return from a list of returns.

    Args:
        returns: List of returns (0.1 = 10%)

    Returns:
        Compound return
    """
    if not returns:
        return 0.0

    compound = 1.0
    for ret in returns:
        compound *= 1 + ret

    return compound - 1


def ensure_directory(path: Union[str, Path]) -> Path:
    """Ensure directory exists.

    Args:
        path: Directory path

    Returns:
        Path object
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string to maximum length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated

    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


def is_valid_email(email: str) -> bool:
    """Check if email address is valid.

    Args:
        email: Email address to validate

    Returns:
        True if valid, False otherwise
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def generate_trade_id() -> str:
    """Generate a unique trade ID.

    Returns:
        Unique trade ID
    """
    timestamp = int(time.time() * 1000)
    random_part = random.randint(1000, 9999)
    return f"TRADE_{timestamp}_{random_part}"


def retry_sync(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
    backoff_factor: float = 1.0,
) -> Callable:
    """
    Decorator for synchronous functions with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        exceptions: Tuple of exceptions to catch and retry
        backoff_factor: Factor to multiply delay by on each retry

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"Function {func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise e

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base**attempt) * backoff_factor,
                        max_delay,
                    )

                    # Add jitter if enabled
                    if jitter:
                        jitter_amount = delay * 0.1 * random.random()
                        delay += jitter_amount

                    logger.warning(
                        f"Function {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    time.sleep(delay)

            # This should never be reached, but just in case
            raise last_exception

        return wrapper

    return decorator


def retry_async(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
    backoff_factor: float = 1.0,
) -> Callable:
    """
    Decorator for asynchronous functions with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        exceptions: Tuple of exceptions to catch and retry
        backoff_factor: Factor to multiply delay by on each retry

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"Async function {func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise e

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base**attempt) * backoff_factor,
                        max_delay,
                    )

                    # Add jitter if enabled
                    if jitter:
                        jitter_amount = delay * 0.1 * random.random()
                        delay += jitter_amount

                    logger.warning(
                        f"Async function {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    await asyncio.sleep(delay)

            # This should never be reached, but just in case
            raise last_exception

        return wrapper

    return decorator


class RateLimiter:
    """Rate limiter for API calls with per-exchange limits."""

    def __init__(self, calls_per_second: float = 1.0, burst_size: int = 10):
        """
        Initialize rate limiter.

        Args:
            calls_per_second: Maximum calls per second
            burst_size: Maximum burst size
        """
        self.calls_per_second = calls_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token for making an API call."""
        async with self._lock:
            now = time.time()
            time_passed = now - self.last_update

            # Add tokens based on time passed
            self.tokens = min(
                self.burst_size, self.tokens + time_passed * self.calls_per_second
            )
            self.last_update = now

            # Wait if no tokens available
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.calls_per_second
                await asyncio.sleep(wait_time)
                self.tokens = 0

            # Consume a token
            self.tokens -= 1


def get_connector_exceptions() -> tuple:
    """
    Get common exceptions that should trigger retries for connectors.

    Returns:
        Tuple of exception types
    """
    return (
        aiohttp.ClientError,
        aiohttp.ClientTimeout,
        aiohttp.ServerTimeoutError,
        aiohttp.ClientConnectionError,
        requests.exceptions.RequestException,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
        ConnectionError,
        TimeoutError,
        OSError,
    )


def get_ccxt_exceptions() -> tuple:
    """
    Get CCXT-specific exceptions that should trigger retries.

    Returns:
        Tuple of exception types
    """
    try:
        import ccxt

        return (
            ccxt.NetworkError,
            ccxt.ExchangeNotAvailable,
            ccxt.RequestTimeout,
            ccxt.DDoSProtection,
            ccxt.RateLimitExceeded,
            ccxt.ExchangeError,
        )
    except ImportError:
        return ()


def create_retry_config(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    backoff_factor: float = 1.0,
) -> dict[str, Any]:
    """
    Create a standardized retry configuration for connectors.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        backoff_factor: Factor to multiply delay by on each retry

    Returns:
        Retry configuration dictionary
    """
    return {
        "max_retries": max_retries,
        "base_delay": base_delay,
        "max_delay": max_delay,
        "exponential_base": exponential_base,
        "jitter": jitter,
        "backoff_factor": backoff_factor,
        "exceptions": get_connector_exceptions() + get_ccxt_exceptions(),
    }


def get_mark_price(
    symbol: str, 
    data_engine, 
    live_mode: bool = False,
    max_age_seconds: int = 30
) -> Optional[float]:
    """
    Get mark price for a symbol with fallback chain and canonical symbol support.
    Uses data engine's mark price source priority system.
    
    Args:
        symbol: Trading symbol in any format (e.g., 'BTC/USDT', 'BTC-USD', 'BTCUSDT')
        data_engine: Data engine instance
        live_mode: Whether in live trading mode (affects staleness check)
        max_age_seconds: Maximum age of ticker data in live mode (default 30s)
    
    Returns:
        Mark price as float, or None if no valid price found
    """
    if not data_engine:
        logger.warning(f"No data engine provided for {symbol}")
        return None
    
    try:
        # Convert to canonical symbol
        canonical_symbol = to_canonical(symbol)
        logger.debug(f"Converted {symbol} to canonical {canonical_symbol}")
        
        # Check if we have a cached mark price from previous cycle
        if hasattr(data_engine, 'mark_price_history') and canonical_symbol in data_engine.mark_price_history:
            cached_price = data_engine.mark_price_history[canonical_symbol]
            cached_source = data_engine.mark_source_history.get(canonical_symbol, "unknown")
            
            # Validate cached price
            if validate_mark_price(cached_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, cached_price, cached_source, cached=True)
                return float(cached_price)
        
        # Get fresh ticker data using data engine's priority system
        ticker_data = data_engine.get_ticker(canonical_symbol)
        
        if not ticker_data:
            logger.warning(f"No ticker data available for {canonical_symbol}")
            return None
        
        # Check for stale data in live mode
        if live_mode:
            timestamp = ticker_data.get('timestamp')
            if timestamp:
                try:
                    from datetime import datetime, timezone
                    if isinstance(timestamp, str):
                        # Parse ISO timestamp
                        ticker_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    else:
                        ticker_time = timestamp
                    
                    # Check if timestamp is timezone-aware
                    if ticker_time.tzinfo is None:
                        ticker_time = ticker_time.replace(tzinfo=timezone.utc)
                    
                    age_seconds = (datetime.now(timezone.utc) - ticker_time).total_seconds()
                    if age_seconds > max_age_seconds:
                        logger.warning(f"Stale ticker data for {canonical_symbol}: {age_seconds:.1f}s old")
                        return None
                        
                except Exception as e:
                    logger.warning(f"Could not parse timestamp for {canonical_symbol}: {e}")
                    # Continue with fallback chain
        
        # Mark price source priority: exchange ticker.last → mid(bid/ask) → OHLCV close → coingecko
        mark_price = None
        source_name = "unknown"
        
        # Step 1: Try 'last' price field (highest priority)
        if ticker_data.get('last') and ticker_data['last'] > 0:
            mark_price = ticker_data['last']
            source_name = "ticker_last"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price)
        
        # Step 2: Try 'price' field (fallback)
        if ticker_data.get('price') and ticker_data['price'] > 0:
            mark_price = ticker_data['price']
            source_name = "ticker_price"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price)
        
        # Step 3: Try mid of best bid/ask
        bid = ticker_data.get('bid')
        ask = ticker_data.get('ask')
        if bid and ask and bid > 0 and ask > 0:
            mark_price = (bid + ask) / 2
            source_name = "bid_ask_mid"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price)
        
        # Step 4: Try last OHLCV close
        try:
            ohlcv_data = data_engine.get_ohlcv(canonical_symbol, "1h", 1)
            if ohlcv_data and len(ohlcv_data) > 0:
                close_price = ohlcv_data[0].get('close')
                if close_price and close_price > 0:
                    mark_price = close_price
                    source_name = "ohlcv_close"
                    if validate_mark_price(mark_price, canonical_symbol):
                        log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                        return float(mark_price)
        except Exception as e:
            logger.warning(f"Failed to get OHLCV data for {canonical_symbol}: {e}")
        
        # No valid price found
        logger.warning(f"No valid mark price found for {canonical_symbol}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting mark price for {symbol}: {e}")
        return None


def validate_mark_price(price: Optional[float], symbol: str) -> bool:
    """
    Validate that a mark price is reasonable using sanity bands.
    
    Args:
        price: Price to validate
        symbol: Trading symbol for context (can be canonical or any format)
    
    Returns:
        True if price is valid, False otherwise
    """
    if price is None:
        return False
    
    if price <= 0:
        logger.warning(f"Invalid mark price for {symbol}: {price} (must be > 0)")
        return False
    
    # Convert to canonical symbol for lookup
    canonical_symbol = to_canonical(symbol)
    
    # Extract base asset from canonical symbol (e.g., BTC from BTC/USDT)
    base_asset = canonical_symbol.split('/')[0]
    
    # Check sanity bands
    if base_asset in PRICE_SANITY_BANDS:
        min_price = PRICE_SANITY_BANDS[base_asset]["min"]
        max_price = PRICE_SANITY_BANDS[base_asset]["max"]
        
        if price < min_price or price > max_price:
            logger.warning(f"Price out of sanity band for {symbol}: {price} (expected {min_price}-{max_price})")
            return False
    
    return True


@contextmanager
def start_cycle_logging():
    """
    Context manager to reset debounced mark price logging for a new cycle.
    
    Usage:
        with start_cycle_logging():
            # All mark price logging in this block will be debounced
            get_mark_price(...)
    """
    global _logged_mark_prices_this_cycle
    # Reset the cache for new cycle
    _logged_mark_prices_this_cycle.clear()
    try:
        yield
    finally:
        # Clean up after cycle
        _logged_mark_prices_this_cycle.clear()


def _should_log_mark_price(symbol: str, price: float, source: str) -> bool:
    """
    Check if mark price should be logged (debounced within cycle).
    
    Args:
        symbol: Trading symbol
        price: Mark price
        source: Price source
        
    Returns:
        True if should log, False if should suppress (already logged this cycle)
    """
    global _logged_mark_prices_this_cycle
    
    # Create cache key
    cache_key = (symbol, round(price, 2), source)
    
    if cache_key in _logged_mark_prices_this_cycle:
        return False  # Already logged this cycle
    
    # Add to cache and allow logging
    _logged_mark_prices_this_cycle.add(cache_key)
    return True


def log_mark_price_debounced(symbol: str, price: float, source: str, cached: bool = False) -> None:
    """
    Log mark price with debouncing to prevent spam within a cycle.
    
    Args:
        symbol: Trading symbol
        price: Mark price
        source: Price source
        cached: Whether this is a cached price
    """
    if _should_log_mark_price(symbol, price, source):
        cache_indicator = " (cached)" if cached else ""
        logger.info(f"mark_src={source} mark={price:.2f}{cache_indicator}")
    else:
        # Still log at debug level to avoid spam but maintain traceability
        logger.debug(f"mark_src={source} mark={price:.2f} (cached, suppressed)")

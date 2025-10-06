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
import time
from loguru import logger

# Cycle-local cache for debounced mark price logging
_logged_mark_prices_this_cycle: set = set()

# Rate limiting for mark price logging
_mark_price_log_state: dict = {}  # (symbol, source) -> {"last_log_time": timestamp, "last_price": price}
_mark_price_log_threshold_seconds = 30  # Minimum seconds between logs for same symbol/source
_mark_price_change_threshold_bps = 10  # Minimum change in basis points to log (0.1%)

# Global cycle price cache instance
_cycle_price_cache = None


class CyclePriceCache:
    """
    Unified price cache for a single trading cycle.
    
    Stores price data for each symbol per cycle to avoid duplicate remote fetches.
    Cache key: (cycle_id, canonical_symbol)
    Cache value: {bid, ask, mid, src, ts}
    """
    
    def __init__(self):
        self._cache = {}  # (cycle_id, symbol) -> price_data
        
    def get(self, cycle_id: int, symbol: str) -> Optional[dict]:
        """Get cached price data for a symbol in a cycle.
        
        Args:
            cycle_id: Trading cycle ID
            symbol: Canonical symbol (e.g., 'BTC/USDT')
            
        Returns:
            Price data dict or None if not cached
        """
        cache_key = (cycle_id, symbol)
        return self._cache.get(cache_key)
    
    def set(self, cycle_id: int, symbol: str, price_data: dict) -> None:
        """Cache price data for a symbol in a cycle.
        
        Args:
            cycle_id: Trading cycle ID
            symbol: Canonical symbol (e.g., 'BTC/USDT')
            price_data: Dict with keys: bid, ask, mid, src, ts
        """
        cache_key = (cycle_id, symbol)
        self._cache[cache_key] = price_data.copy()
        
    def clear_cycle(self, cycle_id: int) -> None:
        """Clear all cached data for a specific cycle.
        
        Args:
            cycle_id: Trading cycle ID to clear
        """
        keys_to_remove = [key for key in self._cache.keys() if key[0] == cycle_id]
        for key in keys_to_remove:
            del self._cache[key]
            
    def clear_all(self) -> None:
        """Clear all cached data."""
        self._cache.clear()


def get_cycle_price_cache() -> CyclePriceCache:
    """Get the global cycle price cache instance."""
    global _cycle_price_cache
    if _cycle_price_cache is None:
        _cycle_price_cache = CyclePriceCache()
    return _cycle_price_cache


def clear_cycle_price_cache(cycle_id: Optional[int] = None) -> None:
    """Clear the cycle price cache.
    
    Args:
        cycle_id: If provided, clear only data for this cycle. If None, clear all.
    """
    cache = get_cycle_price_cache()
    if cycle_id is not None:
        cache.clear_cycle(cycle_id)
    else:
        cache.clear_all()


def _fetch_and_cache_price_data(
    cycle_id: int, 
    symbol: str, 
    data_engine, 
    live_mode: bool = False, 
    max_age_seconds: int = 30
) -> Optional[dict]:
    """
    Fetch price data from data engine and cache it for the cycle.
    
    Args:
        cycle_id: Current trading cycle ID
        symbol: Trading symbol (will be canonicalized)
        data_engine: Data engine instance
        live_mode: Whether in live trading mode
        max_age_seconds: Maximum age of data in live mode
        
    Returns:
        Price data dict with keys: bid, ask, mid, src, ts, or None if fetch failed
    """
    cache = get_cycle_price_cache()
    canonical_symbol = to_canonical(symbol)
    
    # Check cache first
    cached_data = cache.get(cycle_id, canonical_symbol)
    if cached_data:
        logger.debug(f"PRICE_CACHE_HIT: symbol={canonical_symbol}, mid={cached_data['mid']:.4f}, ts={cached_data['ts']}")
        return cached_data
    
    # Cache miss - fetch fresh data
    logger.debug(f"PRICE_CACHE_MISS: symbol={canonical_symbol} - fetching fresh data")
    
    try:
        # Get fresh ticker data
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
                        ticker_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    elif isinstance(timestamp, (int, float)):
                        if timestamp > 1e10:  # Milliseconds
                            ticker_time = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                        else:  # Seconds
                            ticker_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    else:
                        ticker_time = timestamp
                    
                    if hasattr(ticker_time, 'tzinfo') and ticker_time.tzinfo is None:
                        ticker_time = ticker_time.replace(tzinfo=timezone.utc)
                    
                    age_seconds = (datetime.now(timezone.utc) - ticker_time).total_seconds()
                    if age_seconds > max_age_seconds:
                        logger.warning(f"Stale ticker data for {canonical_symbol}: {age_seconds:.1f}s old")
                        return None
                        
                except Exception as e:
                    logger.warning(f"Could not parse timestamp for {canonical_symbol}: {e}")
                    # Continue with fallback - don't reject data due to timestamp parsing issues
        
        # Extract price data
        bid = ticker_data.get('bid', 0.0)
        ask = ticker_data.get('ask', 0.0)
        last_price = ticker_data.get('last', 0.0)
        price_field = ticker_data.get('price', 0.0)
        from datetime import datetime
        timestamp = ticker_data.get('timestamp', datetime.now().isoformat())
        
        # Determine source and calculate mid price
        mid_price = None
        source = "unknown"
        
        # Get source from provenance if available
        if 'provenance' in ticker_data:
            provenance = ticker_data.get('provenance', {})
            if isinstance(provenance, dict):
                source = provenance.get('source', 'unknown')
            else:
                source = str(provenance)
        
        # Calculate mid price using priority order
        if bid and ask and bid > 0 and ask > 0:
            mid_price = (bid + ask) / 2
            if source == "unknown":
                source = "bid_ask_mid"
            else:
                source = f"{source}_mid"
        elif last_price and last_price > 0:
            mid_price = last_price
            if source == "unknown":
                source = "ticker_last"
        elif price_field and price_field > 0:
            mid_price = price_field
            if source == "unknown":
                source = "ticker_price"
        
        # Validate the mid price
        if mid_price and validate_mark_price(mid_price, canonical_symbol):
            # Cache the price data
            price_data = {
                'bid': bid,
                'ask': ask,
                'mid': mid_price,
                'src': source,
                'ts': timestamp
            }
            
            cache.set(cycle_id, canonical_symbol, price_data)
            logger.debug(f"PRICE_CACHE_STORED: symbol={canonical_symbol}, mid={mid_price:.4f}, src={source}")
            
            return price_data
        else:
            logger.warning(f"Invalid price data for {canonical_symbol}: mid={mid_price}, bid={bid}, ask={ask}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching price data for {canonical_symbol}: {e}")
        return None


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
    max_age_seconds: int = 30,
    cycle_id: Optional[int] = None
) -> Optional[float]:
    """
    Get mark price for a symbol using unified cycle price cache.
    
    Args:
        symbol: Trading symbol in any format (e.g., 'BTC/USDT', 'BTC-USD', 'BTCUSDT')
        data_engine: Data engine instance
        live_mode: Whether in live trading mode (affects staleness check)
        max_age_seconds: Maximum age of ticker data in live mode (default 30s)
        cycle_id: Current trading cycle ID (required for caching)
    
    Returns:
        Mark price as float, or None if no valid price found
    """
    if not data_engine:
        logger.warning(f"No data engine provided for {symbol}")
        return None
    
    if cycle_id is None:
        logger.warning(f"No cycle_id provided for {symbol} - cannot use cache")
        return None
    
    try:
        # Fetch price data using unified cache
        price_data = _fetch_and_cache_price_data(
            cycle_id=cycle_id,
            symbol=symbol,
            data_engine=data_engine,
            live_mode=live_mode,
            max_age_seconds=max_age_seconds
        )
        
        if price_data:
            # Log cache hit for subsequent calls
            cache = get_cycle_price_cache()
            cached_data = cache.get(cycle_id, to_canonical(symbol))
            if cached_data:
                logger.debug(f"PRICE_CACHE_HIT: symbol={to_canonical(symbol)}, mid={price_data['mid']:.4f}, ts={price_data['ts']}")
            
            return float(price_data['mid'])
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error getting mark price for {symbol}: {e}")
        return None


def get_mark_price_with_provenance(
    symbol: str, 
    data_engine=None, 
    live_mode: bool = False, 
    max_age_seconds: int = 30
) -> tuple[Optional[float], str]:
    """
    Get mark price for a symbol with provenance information.
    
    Args:
        symbol: Trading symbol in any format (e.g., 'BTC/USDT', 'BTC-USD', 'BTCUSDT')
        data_engine: Data engine instance
        live_mode: Whether in live trading mode (affects staleness check)
        max_age_seconds: Maximum age of ticker data in live mode (default 30s)
    
    Returns:
        Tuple of (mark_price, provenance) where:
        - mark_price: Price as float, or None if no valid price found
        - provenance: "live", "mock", "delayed", or "unknown"
    """
    if not data_engine:
        logger.warning(f"No data engine provided for {symbol}")
        return None, "unknown"
    
    try:
        # Convert to canonical symbol
        canonical_symbol = to_canonical(symbol)
        logger.debug(f"Converted {symbol} to canonical {canonical_symbol}")
        
        # Get ticker data with provenance information
        ticker_data = data_engine.get_ticker(canonical_symbol)
        
        if not ticker_data:
            logger.warning(f"No ticker data available for {canonical_symbol}")
            return None, "unknown"
        
        # Check provenance from ticker data
        provenance = ticker_data.get('provenance', 'unknown')
        
        # Check for stale data in live mode
        if live_mode and provenance == "live":
            timestamp = ticker_data.get('timestamp')
            if timestamp:
                try:
                    from datetime import datetime, timezone
                    if isinstance(timestamp, str):
                        ticker_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    elif isinstance(timestamp, (int, float)):
                        if timestamp > 1e10:  # Milliseconds
                            ticker_time = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                        else:  # Seconds
                            ticker_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    else:
                        ticker_time = timestamp
                    
                    if hasattr(ticker_time, 'tzinfo') and ticker_time.tzinfo is None:
                        ticker_time = ticker_time.replace(tzinfo=timezone.utc)
                    
                    age_seconds = (datetime.now(timezone.utc) - ticker_time).total_seconds()
                    if age_seconds > max_age_seconds:
                        logger.warning(f"Stale ticker data for {canonical_symbol}: {age_seconds:.1f}s old")
                        return None, "delayed"
                        
                except Exception as e:
                    logger.warning(f"Could not parse timestamp for {canonical_symbol}: {e}")
        
        # Mark price source priority: mid(bid/ask) → last → price → OHLCV close
        mark_price = None
        source_name = "unknown"
        
        # Step 1: Try mid of best bid/ask (highest priority for entry)
        bid = ticker_data.get('bid')
        ask = ticker_data.get('ask')
        
        if bid and ask and bid > 0 and ask > 0:
            mark_price = (bid + ask) / 2
            source_name = "bid_ask_mid"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price), provenance
        
        # Step 2: Try 'last' price field
        last_price = ticker_data.get('last')
        if last_price and last_price > 0:
            mark_price = last_price
            source_name = "last"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price), provenance
        
        # Step 3: Try 'price' field
        price = ticker_data.get('price')
        if price and price > 0:
            mark_price = price
            source_name = "price"
            if validate_mark_price(mark_price, canonical_symbol):
                log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                return float(mark_price), provenance
        
        # Step 4: Try OHLCV close price
        ohlcv = ticker_data.get('ohlcv')
        if ohlcv and len(ohlcv) >= 4:
            close_price = ohlcv[3]  # Close is typically index 3 in OHLCV
            if close_price and close_price > 0:
                mark_price = close_price
                source_name = "ohlcv_close"
                if validate_mark_price(mark_price, canonical_symbol):
                    log_mark_price_debounced(canonical_symbol, mark_price, source_name)
                    return float(mark_price), provenance
        
        # No valid price found
        logger.warning(f"No valid price found for {canonical_symbol} from any source")
        return None, provenance
        
    except Exception as e:
        logger.error(f"Error getting mark price for {symbol}: {e}")
        return None, "unknown"


def get_exit_value(
    symbol: str,
    side: str,
    data_engine,
    live_mode: bool = False,
    max_age_seconds: int = 30,
    cycle_id: Optional[int] = None
) -> Optional[float]:
    """
    Get realistic exit value for a position based on side using unified cycle price cache.
    
    For realistic exit decisions:
    - Long positions (buy) → use bid price (what you can actually sell at)
    - Short positions (sell) → use ask price (what you can actually buy back at)
    - Fallback to mid price if bid/ask unavailable
    
    Args:
        symbol: Trading symbol in any format
        side: Position side ('long', 'buy', 'sell', 'short') or quantity sign
        data_engine: Data engine instance
        live_mode: Whether in live trading mode
        max_age_seconds: Maximum age of ticker data in live mode
        cycle_id: Current trading cycle ID (required for caching)
    
    Returns:
        Exit value as float, or None if no valid price found
    """
    if not data_engine:
        logger.warning(f"No data engine provided for {symbol}")
        return None
    
    if cycle_id is None:
        logger.warning(f"No cycle_id provided for {symbol} - cannot use cache")
        return None
    
    try:
        # Fetch price data using unified cache
        price_data = _fetch_and_cache_price_data(
            cycle_id=cycle_id,
            symbol=symbol,
            data_engine=data_engine,
            live_mode=live_mode,
            max_age_seconds=max_age_seconds
        )
        
        if price_data:
            canonical_symbol = to_canonical(symbol)
            logger.debug(f"Getting exit value for {symbol} (canonical: {canonical_symbol}), side: {side}")
            
            # Determine position side
            is_long = False
            if isinstance(side, str):
                side_lower = side.lower()
                is_long = side_lower in ['long', 'buy', 'b']
            elif isinstance(side, (int, float)):
                is_long = side > 0
            
            # Get bid and ask prices from cached data
            bid = price_data.get('bid', 0.0)
            ask = price_data.get('ask', 0.0)
            
            # Choose appropriate exit price based on position side
            exit_value = None
            source_name = "unknown"
            
            if is_long:
                # Long position: use bid price (what you can sell at)
                if bid and bid > 0:
                    exit_value = bid
                    source_name = "bid"
                    logger.debug(f"Exit value for long position: {exit_value} (bid)")
                else:
                    # Fallback to mid price
                    if ask and ask > 0:
                        exit_value = (bid + ask) / 2 if bid and bid > 0 else ask
                        source_name = "ask_fallback"
                        logger.debug(f"Exit value for long position: {exit_value} (ask fallback)")
                    else:
                        # Fallback to mark price
                        exit_value = get_mark_price(symbol, data_engine, live_mode, max_age_seconds, cycle_id)
                        source_name = "mark_price_fallback"
                        logger.debug(f"Exit value for long position: {exit_value} (mark price fallback)")
            else:
                # Short position: use ask price (what you can buy back at)
                if ask and ask > 0:
                    exit_value = ask
                    source_name = "ask"
                    logger.debug(f"Exit value for short position: {exit_value} (ask)")
                else:
                    # Fallback to mid price
                    if bid and bid > 0:
                        exit_value = (bid + ask) / 2 if ask and ask > 0 else bid
                        source_name = "bid_fallback"
                        logger.debug(f"Exit value for short position: {exit_value} (bid fallback)")
                    else:
                        # Fallback to mark price
                        exit_value = get_mark_price(symbol, data_engine, live_mode, max_age_seconds, cycle_id)
                        source_name = "mark_price_fallback"
                        logger.debug(f"Exit value for short position: {exit_value} (mark price fallback)")
            
            # Validate the exit value
            if exit_value and exit_value > 0:
                validation_result = validate_mark_price(exit_value, canonical_symbol)
                if validation_result:
                    logger.info(f"Exit value for {canonical_symbol} ({side}): {exit_value} from {source_name}")
                    return float(exit_value)
            
            logger.warning(f"No valid exit value found for {canonical_symbol} ({side})")
            return None
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error getting exit value for {symbol} ({side}): {e}")
        return None


def get_entry_price(
    symbol: str, 
    data_engine, 
    live_mode: bool = False,
    max_age_seconds: int = 30,
    cycle_id: Optional[int] = None
) -> Optional[float]:
    """
    Get entry price for a symbol using unified cycle price cache.
    Implements the exact source order: bid/ask mid → last → None.
    
    Args:
        symbol: Trading symbol in any format
        data_engine: Data engine instance
        live_mode: Whether in live trading mode
        max_age_seconds: Maximum age of ticker data in live mode
        cycle_id: Current trading cycle ID (required for caching)
    
    Returns:
        Entry price as float, or None if no valid price found
    """
    if not data_engine:
        logger.warning(f"No data engine provided for {symbol}")
        return None
    
    if cycle_id is None:
        logger.warning(f"No cycle_id provided for {symbol} - cannot use cache")
        return None
    
    try:
        # Fetch price data using unified cache
        price_data = _fetch_and_cache_price_data(
            cycle_id=cycle_id,
            symbol=symbol,
            data_engine=data_engine,
            live_mode=live_mode,
            max_age_seconds=max_age_seconds
        )
        
        if price_data:
            canonical_symbol = to_canonical(symbol)
            
            # Entry price source order: bid/ask mid → last → None
            entry_price = None
            source_name = "unknown"
            
            # Step 1: Try bid/ask mid (highest priority)
            bid = price_data.get('bid', 0.0)
            ask = price_data.get('ask', 0.0)
            if bid and ask and bid > 0 and ask > 0:
                entry_price = (bid + ask) / 2
                source_name = "bid_ask_mid"
                if validate_mark_price(entry_price, canonical_symbol):
                    logger.debug(f"Entry price for {canonical_symbol}: ${entry_price:.4f} (source: {source_name})")
                    return float(entry_price)
            
            # Step 2: Try last price from original ticker data
            # We need to get the last price from the original ticker data since it's not in our cache
            try:
                ticker_data = data_engine.get_ticker(canonical_symbol)
                if ticker_data and ticker_data.get('last') and ticker_data['last'] > 0:
                    entry_price = ticker_data['last']
                    source_name = "ticker_last"
                    if validate_mark_price(entry_price, canonical_symbol):
                        logger.debug(f"Entry price for {canonical_symbol}: ${entry_price:.4f} (source: {source_name})")
                        return float(entry_price)
            except Exception as e:
                logger.debug(f"Could not get last price for {canonical_symbol}: {e}")
            
            # No valid entry price found
            logger.warning(f"No valid entry price found for {canonical_symbol} (bid={bid}, ask={ask})")
            return None
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error getting entry price for {symbol}: {e}")
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
    Check if mark price should be logged (debounced within cycle + rate limited).
    
    Args:
        symbol: Trading symbol
        price: Mark price
        source: Price source
        
    Returns:
        True if should log, False if should suppress
    """
    global _logged_mark_prices_this_cycle, _mark_price_log_state
    
    # First check cycle-level debouncing (existing logic)
    cache_key = (symbol, round(price, 2), source)
    if cache_key in _logged_mark_prices_this_cycle:
        return False  # Already logged this cycle
    
    # Check rate limiting across cycles
    rate_limit_key = (symbol, source)
    current_time = time.time()
    
    if rate_limit_key in _mark_price_log_state:
        state = _mark_price_log_state[rate_limit_key]
        last_log_time = state["last_log_time"]
        last_price = state["last_price"]
        
        # Check if enough time has passed
        time_since_last_log = current_time - last_log_time
        if time_since_last_log < _mark_price_log_threshold_seconds:
            # Check if price has changed significantly
            if last_price > 0:
                price_change_bps = abs(price - last_price) / last_price * 10000  # Convert to basis points
                if price_change_bps < _mark_price_change_threshold_bps:
                    return False  # Price hasn't changed enough, suppress logging
    
    # Allow logging - update both caches
    _logged_mark_prices_this_cycle.add(cache_key)
    _mark_price_log_state[rate_limit_key] = {
        "last_log_time": current_time,
        "last_price": price
    }
    
    return True


def log_mark_price_debounced(symbol: str, price: float, source: str, cached: bool = False) -> None:
    """
    Log mark price with debouncing and rate limiting to prevent spam.
    
    Args:
        symbol: Trading symbol
        price: Mark price
        source: Price source
        cached: Whether this is a cached price
    """
    if _should_log_mark_price(symbol, price, source):
        cache_indicator = " (cached)" if cached else ""
        logger.info(f"mark_src={source} mark={price:.2f} for {symbol}{cache_indicator}")
    else:
        # Only log suppressed messages at DEBUG level if it's a significant change or first time
        # This prevents spam while maintaining some traceability
        rate_limit_key = (symbol, source)
        if rate_limit_key not in _mark_price_log_state:
            # First time seeing this symbol/source, log at DEBUG
            logger.debug(f"mark_src={source} mark={price:.2f} for {symbol} (cached, suppressed)")
        # Otherwise, completely suppress to avoid spam

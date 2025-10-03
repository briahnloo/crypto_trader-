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
from typing import Any, Callable, Union

import aiohttp
import requests
from loguru import logger


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

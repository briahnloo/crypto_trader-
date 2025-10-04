"""
Logging utilities for the Crypto MVP application.
"""

import logging
import sys
try:
    import logging.handlers
except ImportError:
    logging.handlers = None
from pathlib import Path
from typing import Any, Optional

from loguru import logger


def get_logger(name: str, config: dict[str, Any]) -> logging.Logger:
    """Get a logger instance configured according to the provided config.

    Args:
        name: Logger name (typically module or class name)
        config: Logging configuration dictionary

    Returns:
        Configured logger instance

    Example:
        >>> config = {
        ...     'level': 'INFO',
        ...     'file': 'logs/crypto_mvp.log',
        ...     'rotation': '1 week',
        ...     'retention': '1 month',
        ...     'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ... }
        >>> logger = get_logger('trading', config)
        >>> logger.info('Trading started')
    """
    # Create logger
    logger_instance = logging.getLogger(name)

    # Clear any existing handlers
    logger_instance.handlers.clear()

    # Set level
    level = config.get("level", "INFO").upper()
    logger_instance.setLevel(getattr(logging, level, logging.INFO))

    # Create formatter
    format_string = config.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    formatter = logging.Formatter(format_string)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level, logging.INFO))
    console_handler.setFormatter(formatter)
    logger_instance.addHandler(console_handler)

    # File handler (if log file is specified)
    log_file = config.get("file")
    if log_file:
        log_path = Path(log_file)

        # Create log directory if it doesn't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Parse rotation settings
        rotation = config.get("rotation", "1 week")
        retention = config.get("retention", "1 month")

        # Create rotating file handler
        file_handler = _create_rotating_file_handler(
            log_path, rotation, retention, formatter
        )
        file_handler.setLevel(getattr(logging, level, logging.INFO))
        logger_instance.addHandler(file_handler)

    # Prevent propagation to root logger
    logger_instance.propagate = False

    return logger_instance


def _create_rotating_file_handler(
    log_path: Path, rotation: str, retention: str, formatter: logging.Formatter
) -> logging.Handler:
    """Create a rotating file handler based on configuration.

    Args:
        log_path: Path to the log file
        rotation: Rotation period (e.g., '1 week', '1 day', '1 hour')
        retention: Retention period (e.g., '1 month', '1 week')
        formatter: Log formatter

    Returns:
        Configured rotating file handler
    """
    # Parse rotation period
    rotation_parts = rotation.split()
    if len(rotation_parts) == 2:
        rotation_count = int(rotation_parts[0])
        rotation_unit = rotation_parts[1].lower()

        # Map units to when values
        when_map = {
            "second": "S",
            "minute": "M",
            "hour": "H",
            "day": "D",
            "week": "W0",  # Monday
            "month": "MIDNIGHT",
        }

        when = when_map.get(rotation_unit, "D")
        interval = rotation_count
    else:
        # Default to daily rotation
        when = "D"
        interval = 1

    # Parse retention period
    retention_parts = retention.split()
    if len(retention_parts) == 2:
        retention_count = int(retention_parts[0])
        retention_unit = retention_parts[1].lower()

        # Convert to backup count (approximate)
        if retention_unit == "second":
            backup_count = retention_count
        elif retention_unit == "minute":
            backup_count = retention_count * 60
        elif retention_unit == "hour":
            backup_count = retention_count * 60 * 60
        elif retention_unit == "day":
            backup_count = retention_count
        elif retention_unit == "week":
            backup_count = retention_count * 7
        elif retention_unit == "month":
            backup_count = retention_count * 30
        else:
            backup_count = 30  # Default to 30 days
    else:
        backup_count = 30  # Default to 30 days

    # Create handler
    if logging.handlers is None:
        # Fallback to basic FileHandler if handlers module is not available
        handler = logging.FileHandler(log_path)
    else:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_path),
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding="utf-8",
    )

    handler.setFormatter(formatter)
    return handler


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_size: str = "10MB",
    backup_count: int = 5,
    format_string: Optional[str] = None,
) -> None:
    """Setup application logging using loguru.

    Args:
        level: Logging level
        log_file: Path to log file
        max_size: Maximum log file size
        backup_count: Number of backup files to keep
        format_string: Custom format string
    """
    # Remove default handler
    logger.remove()

    # Default format
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )

    # Console handler
    logger.add(sys.stdout, format=format_string, level=level, colorize=True)

    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_file,
            format=format_string,
            level=level,
            rotation=max_size,
            retention=backup_count,
            compression="zip",
        )

    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_logger_legacy(name: str) -> logging.Logger:
    """Get a logger instance (legacy method for backward compatibility).

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class LoggerMixin:
    """Mixin class to add logging capabilities to any class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger: Optional[logging.Logger] = None

    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        if not hasattr(self, "_logger") or self._logger is None:
            # Try to get config from the instance if available
            config = getattr(self, "config", {})
            logging_config = config.get("logging", {})

            if logging_config:
                self._logger = get_logger(self.__class__.__name__, logging_config)
            else:
                # Fallback to basic logger
                self._logger = logging.getLogger(self.__class__.__name__)

        return self._logger

    def set_logger_config(self, config: dict[str, Any]) -> None:
        """Set logging configuration for this instance.

        Args:
            config: Logging configuration dictionary
        """
        self._logger = get_logger(self.__class__.__name__, config)


class StructuredLogger:
    """Structured logger for consistent log formatting across the application."""

    def __init__(self, name: str, config: dict[str, Any]):
        """Initialize structured logger.

        Args:
            name: Logger name
            config: Logging configuration
        """
        self.logger = get_logger(name, config)
        self.name = name

    def info(self, message: str, **kwargs) -> None:
        """Log info message with optional structured data.

        Args:
            message: Log message
            **kwargs: Additional structured data
        """
        if kwargs:
            structured_data = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.info(f"{message} | {structured_data}")
        else:
            self.logger.info(message)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message with optional structured data.

        Args:
            message: Log message
            **kwargs: Additional structured data
        """
        if kwargs:
            structured_data = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.warning(f"{message} | {structured_data}")
        else:
            self.logger.warning(message)

    def error(self, message: str, **kwargs) -> None:
        """Log error message with optional structured data.

        Args:
            message: Log message
            **kwargs: Additional structured data
        """
        if kwargs:
            structured_data = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.error(f"{message} | {structured_data}")
        else:
            self.logger.error(message)

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message with optional structured data.

        Args:
            message: Log message
            **kwargs: Additional structured data
        """
        if kwargs:
            structured_data = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.debug(f"{message} | {structured_data}")
        else:
            self.logger.debug(message)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message with optional structured data.

        Args:
            message: Log message
            **kwargs: Additional structured data
        """
        if kwargs:
            structured_data = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.critical(f"{message} | {structured_data}")
        else:
            self.logger.critical(message)


def create_performance_logger(config: dict[str, Any]) -> StructuredLogger:
    """Create a performance-specific logger.

    Args:
        config: Logging configuration

    Returns:
        Structured logger for performance metrics
    """
    performance_config = config.copy()
    performance_config["file"] = config.get("performance", {}).get(
        "file", "logs/performance.log"
    )
    performance_config["level"] = config.get("performance", {}).get("level", "INFO")

    return StructuredLogger("performance", performance_config)


def create_trading_logger(config: dict[str, Any]) -> StructuredLogger:
    """Create a trading-specific logger.

    Args:
        config: Logging configuration

    Returns:
        Structured logger for trading events
    """
    trading_config = config.copy()
    trading_config["file"] = "logs/trading.log"
    trading_config["level"] = config.get("modules", {}).get("trading", "INFO")

    return StructuredLogger("trading", trading_config)


def create_risk_logger(config: dict[str, Any]) -> StructuredLogger:
    """Create a risk management-specific logger.

    Args:
        config: Logging configuration

    Returns:
        Structured logger for risk events
    """
    risk_config = config.copy()
    risk_config["file"] = "logs/risk.log"
    risk_config["level"] = config.get("modules", {}).get("risk", "INFO")

    return StructuredLogger("risk", risk_config)


def create_execution_logger(config: dict[str, Any]) -> StructuredLogger:
    """Create an execution-specific logger.

    Args:
        config: Logging configuration

    Returns:
        Structured logger for execution events
    """
    execution_config = config.copy()
    execution_config["file"] = "logs/execution.log"
    execution_config["level"] = config.get("modules", {}).get("execution", "INFO")

    return StructuredLogger("execution", execution_config)

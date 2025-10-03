"""
Crypto MVP - A comprehensive cryptocurrency trading MVP.

This package provides multiple trading strategies, data sources, and risk management
capabilities for cryptocurrency trading.
"""

__version__ = "0.1.0"
__author__ = "Crypto MVP Team"
__email__ = "team@cryptomvp.com"

from .core.config_manager import ConfigManager
from .core.logging_utils import setup_logging
from .core.utils import get_version, validate_config

__all__ = [
    "ConfigManager",
    "setup_logging",
    "get_version",
    "validate_config",
]

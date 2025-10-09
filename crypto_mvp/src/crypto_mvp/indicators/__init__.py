"""
Technical indicators for cryptocurrency analysis.
"""

from .technical_calculator import TechnicalCalculator, get_calculator

# Lazy imports to avoid pandas/numpy compatibility issues
def get_advanced_indicators():
    """Lazy load AdvancedIndicators to avoid pandas import issues."""
    from .advanced import AdvancedIndicators
    return AdvancedIndicators

def safe_atr(*args, **kwargs):
    """Lazy load safe_atr function."""
    from .indicators import safe_atr as _safe_atr
    return _safe_atr(*args, **kwargs)

def validate_ohlcv_inputs(*args, **kwargs):
    """Lazy load validate_ohlcv_inputs function."""
    from .indicators import validate_ohlcv_inputs as _validate
    return _validate(*args, **kwargs)

__all__ = [
    "TechnicalCalculator",
    "get_calculator",
    "get_advanced_indicators",
    "safe_atr",
    "validate_ohlcv_inputs",
]

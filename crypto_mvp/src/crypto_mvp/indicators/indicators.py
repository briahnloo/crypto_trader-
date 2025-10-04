"""
Core technical indicators with resilience for mock data scenarios.
"""

import hashlib
import random
from typing import List, Optional, Union

import numpy as np
import pandas as pd

from ..core.logging_utils import LoggerMixin


def safe_atr(
    high: Union[List[float], np.ndarray, pd.Series],
    low: Union[List[float], np.ndarray, pd.Series],
    close: Union[List[float], np.ndarray, pd.Series],
    period: int = 14,
    symbol: Optional[str] = None,
    logger: Optional[LoggerMixin] = None
) -> Optional[float]:
    """Calculate ATR with resilience for mock data scenarios.
    
    This function ensures ATR can always be calculated even with insufficient
    or problematic OHLCV data by synthesizing missing data when necessary.
    
    Args:
        high: High prices (list, array, or series)
        low: Low prices (list, array, or series) 
        close: Close prices (list, array, or series)
        period: ATR period (default 14)
        symbol: Trading symbol for deterministic synthesis (optional)
        logger: Logger instance for debugging (optional)
        
    Returns:
        ATR value as float, or None if absolutely no data available
    """
    if logger is None:
        logger = LoggerMixin()
        
    try:
        # Convert inputs to numpy arrays and validate
        high_arr = np.array(high, dtype=float)
        low_arr = np.array(low, dtype=float)
        close_arr = np.array(close, dtype=float)
        
        # Remove any NaN values
        valid_mask = ~(np.isnan(high_arr) | np.isnan(low_arr) | np.isnan(close_arr))
        if not np.any(valid_mask):
            logger.warning("No valid OHLCV data available for ATR calculation")
            return None
            
        high_arr = high_arr[valid_mask]
        low_arr = low_arr[valid_mask]
        close_arr = close_arr[valid_mask]
        
        # Check if we have enough data for ATR calculation
        if len(high_arr) >= period + 1:
            # Sufficient data - calculate normal ATR
            return _calculate_standard_atr(high_arr, low_arr, close_arr, period, logger)
        
        elif len(close_arr) > 0:
            # Insufficient data but have close prices - synthesize missing data
            logger.info(f"Synthesizing OHLCV data for ATR calculation (have {len(close_arr)} bars, need {period + 1})")
            return _synthesize_and_calculate_atr(high_arr, low_arr, close_arr, period, symbol, logger)
        
        else:
            # No data at all
            logger.warning("No close prices available for ATR synthesis")
            return None
            
    except Exception as e:
        logger.error(f"Error in safe_atr calculation: {e}")
        return None


def _calculate_standard_atr(
    high: np.ndarray,
    low: np.ndarray, 
    close: np.ndarray,
    period: int,
    logger: LoggerMixin
) -> float:
    """Calculate standard ATR using Wilder's smoothing."""
    try:
        # Calculate True Range (TR)
        high_low = high - low
        high_close_prev = np.abs(high - np.roll(close, 1))
        low_close_prev = np.abs(low - np.roll(close, 1))
        
        # First bar has no previous close, so use high-low
        high_close_prev[0] = high_low[0]
        low_close_prev[0] = high_low[0]
        
        # True Range is the maximum of the three
        true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
        
        # Calculate ATR using Wilder's smoothing (exponential moving average)
        atr_series = pd.Series(true_range).ewm(alpha=1.0/period, adjust=False).mean()
        atr_value = float(atr_series.iloc[-1])
        
        logger.debug(f"Calculated standard ATR: {atr_value:.6f} for {len(high)} periods")
        return atr_value
        
    except Exception as e:
        logger.error(f"Error in standard ATR calculation: {e}")
        raise


def _synthesize_and_calculate_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int,
    symbol: Optional[str],
    logger: LoggerMixin
) -> float:
    """Synthesize missing OHLCV data and calculate ATR."""
    try:
        # Use the latest close price as base
        latest_close = float(close[-1])
        
        # Create deterministic seed from symbol if available
        if symbol:
            seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
        else:
            rng = random.Random(42)  # Default seed
        
        # Synthesize enough bars to reach period + 1
        needed_bars = (period + 1) - len(close)
        logger.debug(f"Synthesizing {needed_bars} bars around latest close: {latest_close}")
        
        # Start with existing data
        synth_high = high.tolist() if len(high) > 0 else []
        synth_low = low.tolist() if len(low) > 0 else []
        synth_close = close.tolist()
        
        # Synthesize additional bars using random walk around latest close
        current_price = latest_close
        
        for i in range(needed_bars):
            # Generate small random walk movement (±0.3% per bar)
            movement = rng.gauss(0, 0.003)  # 0.3% standard deviation
            current_price *= (1 + movement)
            
            # Generate OHLC around current price
            # Open-close range: ±0.2%
            open_close_range = current_price * 0.002
            open_price = current_price + rng.uniform(-open_close_range, open_close_range)
            
            # High-low envelope: ±0.4-0.6%
            hl_envelope = current_price * rng.uniform(0.004, 0.006)
            high_price = current_price + hl_envelope
            low_price = current_price - hl_envelope
            
            # Ensure logical consistency
            high_price = max(high_price, open_price, current_price)
            low_price = min(low_price, open_price, current_price)
            
            synth_high.append(high_price)
            synth_low.append(low_price)
            synth_close.append(current_price)
        
        # Convert to numpy arrays and calculate ATR
        synth_high_arr = np.array(synth_high)
        synth_low_arr = np.array(synth_low)
        synth_close_arr = np.array(synth_close)
        
        logger.debug(f"Synthesized OHLCV data: {len(synth_close_arr)} bars")
        
        # Calculate ATR on synthesized data
        atr_value = _calculate_standard_atr(synth_high_arr, synth_low_arr, synth_close_arr, period, logger)
        
        logger.info(f"Synthesized ATR: {atr_value:.6f} for {symbol or 'unknown'}")
        return atr_value
        
    except Exception as e:
        logger.error(f"Error in ATR synthesis: {e}")
        raise


def validate_ohlcv_inputs(
    high: Union[List, np.ndarray, pd.Series],
    low: Union[List, np.ndarray, pd.Series], 
    close: Union[List, np.ndarray, pd.Series]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate and clean OHLCV inputs.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        
    Returns:
        Tuple of cleaned numpy arrays
        
    Raises:
        ValueError: If inputs are invalid
    """
    # Convert to numpy arrays
    high_arr = np.array(high, dtype=float)
    low_arr = np.array(low, dtype=float)
    close_arr = np.array(close, dtype=float)
    
    # Check lengths
    if len(high_arr) != len(low_arr) or len(high_arr) != len(close_arr):
        raise ValueError("High, low, and close arrays must have the same length")
    
    if len(high_arr) == 0:
        raise ValueError("Input arrays cannot be empty")
    
    # Remove NaN values
    valid_mask = ~(np.isnan(high_arr) | np.isnan(low_arr) | np.isnan(close_arr))
    if not np.any(valid_mask):
        raise ValueError("No valid data after removing NaN values")
    
    high_clean = high_arr[valid_mask]
    low_clean = low_arr[valid_mask]
    close_clean = close_arr[valid_mask]
    
    # Check logical consistency
    if np.any(high_clean < low_clean):
        raise ValueError("High prices cannot be less than low prices")
    
    return high_clean, low_clean, close_clean

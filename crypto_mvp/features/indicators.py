"""
Minimal ATR utility for trailing logic.

This module provides a simple ATR function with minimal footprint.
Pure function implementation that doesn't require complex logging setup.
"""

import numpy as np
import pandas as pd
from typing import Union, List, Optional


def atr(
    series_high: Union[List[float], np.ndarray, pd.Series],
    series_low: Union[List[float], np.ndarray, pd.Series], 
    series_close: Union[List[float], np.ndarray, pd.Series],
    n: int = 14
) -> Optional[float]:
    """
    Calculate Average True Range (ATR) for trailing logic.
    
    Pure function implementation with minimal footprint.
    Handles data validation and edge cases without external dependencies.
    
    Args:
        series_high: High prices series
        series_low: Low prices series
        series_close: Close prices series
        n: ATR period (default 14)
        
    Returns:
        ATR value as float, or None if calculation fails
        
    Examples:
        >>> high = [100, 102, 101, 103, 105]
        >>> low = [99, 100, 100, 102, 103]
        >>> close = [101, 101, 102, 104, 104]
        >>> atr_value = atr(high, low, close, n=14)
        >>> print(f"ATR: {atr_value:.4f}")
    """
    try:
        # Convert inputs to numpy arrays and validate
        high_arr = np.array(series_high, dtype=float)
        low_arr = np.array(series_low, dtype=float)
        close_arr = np.array(series_close, dtype=float)
        
        # Remove any NaN values
        valid_mask = ~(np.isnan(high_arr) | np.isnan(low_arr) | np.isnan(close_arr))
        if not np.any(valid_mask):
            return None
            
        high_arr = high_arr[valid_mask]
        low_arr = low_arr[valid_mask]
        close_arr = close_arr[valid_mask]
        
        # Check if we have enough data
        if len(high_arr) < 2:
            return None
        
        # Calculate True Range (TR)
        high_low = high_arr - low_arr
        high_close_prev = np.abs(high_arr - np.roll(close_arr, 1))
        low_close_prev = np.abs(low_arr - np.roll(close_arr, 1))
        
        # First bar has no previous close, so use high-low
        high_close_prev[0] = high_low[0]
        low_close_prev[0] = high_low[0]
        
        # True Range is the maximum of the three
        true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
        
        # Calculate ATR using Wilder's smoothing (exponential moving average)
        # For minimal data, use simple average
        if len(true_range) < n:
            atr_value = np.mean(true_range)
        else:
            # Use exponential moving average for sufficient data
            alpha = 1.0 / n
            atr_series = pd.Series(true_range).ewm(alpha=alpha, adjust=False).mean()
            atr_value = float(atr_series.iloc[-1])
        
        # Validate result
        if pd.isna(atr_value) or atr_value <= 0:
            return None
            
        return float(atr_value)
        
    except Exception:
        # Return None on any error for minimal footprint
        return None

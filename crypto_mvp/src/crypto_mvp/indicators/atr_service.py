"""
ATR (Average True Range) service for computing real ATR values from candle data.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from crypto_mvp.core.logging_utils import LoggerMixin


class ATRService(LoggerMixin):
    """
    Service for computing ATR values from OHLCV candle data.
    
    Features:
    - Real ATR computation from last N candles
    - Fallback handling when candles unavailable
    - Caching for performance
    - Comprehensive logging
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the ATR service.
        
        Args:
            config: Configuration dictionary with ATR settings
        """
        super().__init__()
        self.config = config or {}
        
        # ATR parameters
        self.atr_period = self.config.get("atr_period", 14)
        self.cache = {}  # Simple cache for ATR values
        
        self.logger.info(f"ATRService initialized with period={self.atr_period}")
    
    def get_atr(
        self, 
        symbol: str, 
        data_engine: Optional[Any] = None,
        period: Optional[int] = None
    ) -> Optional[float]:
        """
        Get ATR value for a symbol.
        
        Args:
            symbol: Trading symbol
            data_engine: Data engine instance for fetching candles
            period: ATR period (overrides default)
            
        Returns:
            ATR value or None if unavailable
        """
        if period is None:
            period = self.atr_period
        
        # Try to get real ATR from data engine (don't use cache for fresh data)
        atr_value = self._compute_atr_from_candles(symbol, data_engine, period)
        
        if atr_value is not None:
            self.logger.debug(f"ATR for {symbol} (period={period}): {atr_value:.6f}")
        else:
            self.logger.debug(f"ATR unavailable for {symbol} (period={period})")
            
        return atr_value
    
    def _compute_atr_from_candles(
        self, 
        symbol: str, 
        data_engine: Optional[Any], 
        period: int
    ) -> Optional[float]:
        """
        Compute ATR from OHLCV candle data.
        
        Args:
            symbol: Trading symbol
            data_engine: Data engine instance
            period: ATR period
            
        Returns:
            ATR value or None if computation fails
        """
        if not data_engine:
            return None
            
        try:
            # Get OHLCV data - need at least period + 1 candles for ATR
            candles = data_engine.get_ohlcv(symbol, limit=period + 10)
            
            if not candles or len(candles) < period + 1:
                self.logger.debug(f"Insufficient candles for ATR: {len(candles) if candles else 0} < {period + 1}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Ensure we have numeric data
            for col in ['high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Remove any rows with NaN values
            df = df.dropna(subset=['high', 'low', 'close'])
            
            if len(df) < period + 1:
                self.logger.debug(f"Insufficient valid candles for ATR: {len(df)} < {period + 1}")
                return None
            
            # Calculate True Range (TR)
            high = df['high']
            low = df['low']
            close = df['close']
            
            # True Range is the maximum of:
            # 1. High - Low
            # 2. |High - Previous Close|
            # 3. |Low - Previous Close|
            high_low = high - low
            high_close_prev = np.abs(high - close.shift(1))
            low_close_prev = np.abs(low - close.shift(1))
            
            true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
            
            # Calculate ATR using Wilder's smoothing (exponential moving average)
            atr = true_range.ewm(alpha=1.0/period, adjust=False).mean()
            
            # Return the most recent ATR value
            atr_value = atr.iloc[-1]
            
            if pd.isna(atr_value) or atr_value <= 0:
                self.logger.debug(f"Invalid ATR value: {atr_value}")
                return None
                
            return float(atr_value)
            
        except Exception as e:
            self.logger.error(f"Error computing ATR for {symbol}: {e}")
            return None
    
    def clear_cache(self, symbol: Optional[str] = None):
        """Clear ATR cache.
        
        Args:
            symbol: Specific symbol to clear, or None to clear all
        """
        if symbol:
            # Clear cache for specific symbol
            keys_to_remove = [key for key in self.cache.keys() if key.startswith(f"{symbol}_")]
            for key in keys_to_remove:
                del self.cache[key]
            self.logger.debug(f"Cleared ATR cache for {symbol}")
        else:
            # Clear all cache
            self.cache.clear()
            self.logger.debug("Cleared all ATR cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            "cache_size": len(self.cache),
            "cached_symbols": list(set(key.split('_')[0] for key in self.cache.keys())),
            "cache_keys": list(self.cache.keys())
        }

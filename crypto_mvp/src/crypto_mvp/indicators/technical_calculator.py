"""
Real technical indicator calculations using actual OHLCV data.

This module provides efficient technical indicator calculations using numpy
and proper financial formulas, NOT random/mock data.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class TechnicalCalculator:
    """Calculate technical indicators from real OHLCV data."""
    
    def __init__(self):
        """Initialize the technical calculator."""
        self.cache = {}  # Cache for calculated indicators
        self.cache_ttl = 60  # Cache TTL in seconds
    
    def calculate_rsi(self, closes: np.ndarray, period: int = 14) -> Optional[float]:
        """
        Calculate RSI (Relative Strength Index) from closing prices.
        
        Args:
            closes: Array of closing prices (most recent last)
            period: RSI period (default 14)
            
        Returns:
            RSI value (0-100) or None if insufficient data
        """
        if len(closes) < period + 1:
            return None
        
        # Calculate price changes
        deltas = np.diff(closes)
        
        # Separate gains and losses
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # Calculate average gains and losses using EMA
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return float(rsi)
    
    def calculate_macd(
        self, 
        closes: np.ndarray, 
        fast: int = 12, 
        slow: int = 26, 
        signal: int = 9
    ) -> Optional[Dict[str, float]]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            closes: Array of closing prices (most recent last)
            fast: Fast EMA period (default 12)
            slow: Slow EMA period (default 26)
            signal: Signal line EMA period (default 9)
            
        Returns:
            Dictionary with macd, signal, histogram or None if insufficient data
        """
        if len(closes) < slow + signal:
            return None
        
        # Calculate EMAs
        ema_fast = self._calculate_ema(closes, fast)
        ema_slow = self._calculate_ema(closes, slow)
        
        if ema_fast is None or ema_slow is None:
            return None
        
        # MACD line
        macd_line = ema_fast - ema_slow
        
        # Signal line (EMA of MACD)
        macd_values = []
        for i in range(len(closes) - slow + 1):
            subset_closes = closes[:slow + i]
            fast_ema = self._calculate_ema(subset_closes, fast)
            slow_ema = self._calculate_ema(subset_closes, slow)
            if fast_ema is not None and slow_ema is not None:
                macd_values.append(fast_ema - slow_ema)
        
        if len(macd_values) < signal:
            return None
        
        signal_line = self._calculate_ema(np.array(macd_values), signal)
        
        if signal_line is None:
            return None
        
        # Histogram
        histogram = macd_line - signal_line
        
        return {
            "macd": float(macd_line),
            "signal": float(signal_line),
            "histogram": float(histogram)
        }
    
    def calculate_bollinger_bands(
        self, 
        closes: np.ndarray, 
        period: int = 20, 
        std_dev: float = 2.0
    ) -> Optional[Dict[str, float]]:
        """
        Calculate Bollinger Bands.
        
        Args:
            closes: Array of closing prices (most recent last)
            period: Moving average period (default 20)
            std_dev: Number of standard deviations (default 2.0)
            
        Returns:
            Dictionary with upper, middle, lower bands or None
        """
        if len(closes) < period:
            return None
        
        # Calculate SMA (middle band)
        sma = np.mean(closes[-period:])
        
        # Calculate standard deviation
        std = np.std(closes[-period:])
        
        # Calculate bands
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)
        
        return {
            "upper": float(upper_band),
            "middle": float(sma),
            "lower": float(lower_band),
            "current_price": float(closes[-1]),
            "percent_b": float((closes[-1] - lower_band) / (upper_band - lower_band)) if upper_band != lower_band else 0.5
        }
    
    def calculate_williams_r(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Optional[float]:
        """
        Calculate Williams %R.
        
        Args:
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of closing prices
            period: Lookback period (default 14)
            
        Returns:
            Williams %R value (-100 to 0) or None
        """
        if len(closes) < period or len(highs) < period or len(lows) < period:
            return None
        
        # Get highest high and lowest low over period
        highest_high = np.max(highs[-period:])
        lowest_low = np.min(lows[-period:])
        
        if highest_high == lowest_low:
            return -50.0  # Neutral
        
        # Calculate Williams %R
        williams_r = -100 * ((highest_high - closes[-1]) / (highest_high - lowest_low))
        
        return float(williams_r)
    
    def calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Optional[float]:
        """
        Calculate ATR (Average True Range).
        
        Args:
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of closing prices
            period: ATR period (default 14)
            
        Returns:
            ATR value or None
        """
        if len(closes) < period + 1:
            return None
        
        # Calculate True Range
        tr_list = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr = max(high_low, high_close, low_close)
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return None
        
        # Calculate ATR (simple moving average of TR)
        atr = np.mean(tr_list[-period:])
        
        return float(atr)
    
    def calculate_atr_with_fallback(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """
        Calculate ATR with bootstrap fallback for warmup periods.
        
        This solves the "insufficient_data_warmup" blocker by providing
        an ATR estimate even when we don't have enough candles.
        
        Args:
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of close prices
            period: ATR period (default 14)
            
        Returns:
            ATR value (never None - always returns a fallback)
        """
        # Try real ATR calculation first
        if len(closes) >= period + 1:
            atr = self.calculate_atr(highs, lows, closes, period)
            if atr is not None and atr > 0:
                return atr
        
        # Bootstrap ATR from recent volatility (warmup fallback)
        if len(closes) >= 5:
            recent_closes = closes[-min(20, len(closes)):]
            if len(recent_closes) >= 2:
                # Calculate log returns volatility
                returns = np.diff(np.log(recent_closes + 1e-10))
                sigma = np.std(returns)
                
                # Bootstrap ATR: k * sigma * price (k=1.4 empirical from crypto markets)
                bootstrap_atr = 1.4 * sigma * float(closes[-1])
                min_atr = 0.01 * float(closes[-1])  # Min 1% of price
                
                return max(bootstrap_atr, min_atr)
        
        # Final fallback: 2% of current price (conservative estimate)
        return 0.02 * float(closes[-1])
    
    def calculate_sma(self, values: np.ndarray, period: int) -> Optional[float]:
        """
        Calculate Simple Moving Average.
        
        Args:
            values: Array of values
            period: SMA period
            
        Returns:
            SMA value or None
        """
        if len(values) < period:
            return None
        
        return float(np.mean(values[-period:]))
    
    def calculate_ema(self, values: np.ndarray, period: int) -> Optional[float]:
        """
        Calculate Exponential Moving Average.
        
        Args:
            values: Array of values
            period: EMA period
            
        Returns:
            EMA value or None
        """
        return self._calculate_ema(values, period)
    
    def _calculate_ema(self, values: np.ndarray, period: int) -> Optional[float]:
        """
        Internal EMA calculation.
        
        Args:
            values: Array of values
            period: EMA period
            
        Returns:
            EMA value or None
        """
        if len(values) < period:
            return None
        
        # Calculate multiplier
        multiplier = 2 / (period + 1)
        
        # Initialize EMA with SMA
        ema = np.mean(values[:period])
        
        # Calculate EMA for remaining values
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema
        
        return float(ema)
    
    def calculate_volume_ratio(self, volumes: np.ndarray, period: int = 20) -> Optional[float]:
        """
        Calculate volume ratio (current volume / average volume).
        
        Args:
            volumes: Array of volume values
            period: Period for average (default 20)
            
        Returns:
            Volume ratio or None
        """
        if len(volumes) < period:
            return None
        
        avg_volume = np.mean(volumes[-period:-1])  # Exclude current
        if avg_volume == 0:
            return 1.0
        
        current_volume = volumes[-1]
        ratio = current_volume / avg_volume
        
        return float(ratio)
    
    def detect_support_resistance(
        self, 
        highs: np.ndarray, 
        lows: np.ndarray, 
        closes: np.ndarray,
        lookback: int = 20
    ) -> Dict[str, float]:
        """
        Detect support and resistance levels.
        
        Args:
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of closing prices
            lookback: Lookback period
            
        Returns:
            Dictionary with support, resistance, and current price
        """
        if len(closes) < lookback:
            # Not enough data, use recent high/low
            resistance = float(np.max(highs[-min(len(highs), 5):]))
            support = float(np.min(lows[-min(len(lows), 5):]))
        else:
            # Find recent high and low
            resistance = float(np.max(highs[-lookback:]))
            support = float(np.min(lows[-lookback:]))
        
        current = float(closes[-1])
        
        return {
            "support": support,
            "resistance": resistance,
            "current": current,
            "distance_to_resistance": (resistance - current) / current if current > 0 else 0,
            "distance_to_support": (current - support) / current if current > 0 else 0
        }
    
    def calculate_volatility(self, closes: np.ndarray, period: int = 20) -> Optional[float]:
        """
        Calculate price volatility (standard deviation of returns).
        
        Args:
            closes: Array of closing prices
            period: Period for calculation
            
        Returns:
            Volatility (annualized) or None
        """
        if len(closes) < period + 1:
            return None
        
        # Calculate returns
        returns = np.diff(closes[-period-1:]) / closes[-period-1:-1]
        
        # Calculate standard deviation
        volatility = np.std(returns)
        
        # Annualize (assuming 1h candles, ~8760 hours per year)
        annualized = volatility * np.sqrt(8760)
        
        return float(annualized)
    
    def parse_ohlcv(self, ohlcv_data: List[List]) -> Dict[str, np.ndarray]:
        """
        Parse OHLCV data into numpy arrays.
        
        Args:
            ohlcv_data: List of [timestamp, open, high, low, close, volume] OR list of dicts
            
        Returns:
            Dictionary with numpy arrays for each component
        """
        if not ohlcv_data or len(ohlcv_data) == 0:
            return {
                "timestamps": np.array([]),
                "opens": np.array([]),
                "highs": np.array([]),
                "lows": np.array([]),
                "closes": np.array([]),
                "volumes": np.array([])
            }
        
        # Handle different OHLCV formats
        first_item = ohlcv_data[0]
        
        # Case 1: List of dictionaries (common API format)
        if isinstance(first_item, dict):
            timestamps = []
            opens = []
            highs = []
            lows = []
            closes = []
            volumes = []
            
            for candle in ohlcv_data:
                timestamps.append(float(candle.get('timestamp', candle.get('time', 0))))
                opens.append(float(candle.get('open', 0)))
                highs.append(float(candle.get('high', 0)))
                lows.append(float(candle.get('low', 0)))
                closes.append(float(candle.get('close', 0)))
                volumes.append(float(candle.get('volume', 0)))
            
            return {
                "timestamps": np.array(timestamps),
                "opens": np.array(opens),
                "highs": np.array(highs),
                "lows": np.array(lows),
                "closes": np.array(closes),
                "volumes": np.array(volumes)
            }
        
        # Case 2: List of lists/tuples (expected format)
        if not isinstance(first_item, (list, tuple)):
            raise ValueError(f"Invalid OHLCV format: expected list of lists or dicts, got {type(first_item)}")
        
        if len(first_item) < 6:
            raise ValueError(f"Invalid OHLCV format: expected 6 columns, got {len(first_item)}")
        
        # Convert to numpy array (now validated as 2D)
        try:
            data = np.array(ohlcv_data, dtype=float)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Failed to convert OHLCV to numpy array: {e}")
        
        # Ensure 2D shape
        if data.ndim != 2:
            raise ValueError(f"OHLCV data must be 2D, got {data.ndim}D with shape {data.shape}")
        
        return {
            "timestamps": data[:, 0],
            "opens": data[:, 1],
            "highs": data[:, 2],
            "lows": data[:, 3],
            "closes": data[:, 4],
            "volumes": data[:, 5]
        }


# Global instance for easy access
_calculator = TechnicalCalculator()


def get_calculator() -> TechnicalCalculator:
    """Get the global technical calculator instance."""
    return _calculator


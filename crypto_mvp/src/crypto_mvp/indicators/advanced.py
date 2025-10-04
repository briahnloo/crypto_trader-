"""
Advanced technical indicators for cryptocurrency analysis.
"""

import warnings
from typing import Optional, Union

import numpy as np
import pandas as pd

from ..core.logging_utils import LoggerMixin


def _validate_ohlcv_data(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: Optional[pd.Series] = None,
) -> None:
    """Validate OHLCV data for indicators.

    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        volume: Volume series (optional)

    Raises:
        ValueError: If data is invalid
    """
    if len(high) != len(low) or len(high) != len(close):
        raise ValueError("High, low, and close series must have the same length")

    if volume is not None and len(high) != len(volume):
        raise ValueError("Volume series must have the same length as price series")

    if len(high) == 0:
        raise ValueError("Input series cannot be empty")

    if high.isna().all() or low.isna().all() or close.isna().all():
        raise ValueError("Input series cannot be all NaN")

    # Check for logical consistency
    if (high < low).any():
        raise ValueError("High prices cannot be less than low prices")

    if (high < close).any() or (low > close).any():
        warnings.warn("Some close prices are outside high-low range", UserWarning)


def ichimoku_cloud(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_span_b_period: int = 52,
) -> dict[str, pd.Series]:
    """Calculate Ichimoku Cloud indicators.

    The Ichimoku Cloud is a comprehensive technical analysis system that provides
    support/resistance levels, trend direction, momentum, and trading signals.

    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        tenkan_period: Tenkan-sen (conversion line) period (default: 9)
        kijun_period: Kijun-sen (base line) period (default: 26)
        senkou_span_b_period: Senkou Span B period (default: 52)

    Returns:
        Dictionary containing:
        - tenkan_sen: Conversion line
        - kijun_sen: Base line
        - senkou_span_a: Leading span A
        - senkou_span_b: Leading span B
        - chikou_span: Lagging span
        - cloud_top: Upper cloud boundary
        - cloud_bottom: Lower cloud boundary

    Raises:
        ValueError: If input data is invalid or insufficient
    """
    # Input validation
    _validate_ohlcv_data(high, low, close)

    if len(high) < senkou_span_b_period:
        raise ValueError(
            f"Insufficient data: need at least {senkou_span_b_period} periods"
        )

    if tenkan_period <= 0 or kijun_period <= 0 or senkou_span_b_period <= 0:
        raise ValueError("All periods must be positive")

    # Convert to pandas Series if needed
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)

    # Tenkan-sen (Conversion Line)
    tenkan_high = high.rolling(window=tenkan_period, min_periods=1).max()
    tenkan_low = low.rolling(window=tenkan_period, min_periods=1).min()
    tenkan_sen = (tenkan_high + tenkan_low) / 2

    # Kijun-sen (Base Line)
    kijun_high = high.rolling(window=kijun_period, min_periods=1).max()
    kijun_low = low.rolling(window=kijun_period, min_periods=1).min()
    kijun_sen = (kijun_high + kijun_low) / 2

    # Senkou Span A (Leading Span A)
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun_period)

    # Senkou Span B (Leading Span B)
    senkou_span_b_high = high.rolling(window=senkou_span_b_period, min_periods=1).max()
    senkou_span_b_low = low.rolling(window=senkou_span_b_period, min_periods=1).min()
    senkou_span_b = ((senkou_span_b_high + senkou_span_b_low) / 2).shift(kijun_period)

    # Chikou Span (Lagging Span)
    chikou_span = close.shift(-kijun_period)

    # Cloud boundaries
    cloud_top = pd.concat([senkou_span_a, senkou_span_b], axis=1).max(axis=1)
    cloud_bottom = pd.concat([senkou_span_a, senkou_span_b], axis=1).min(axis=1)

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_span_a": senkou_span_a,
        "senkou_span_b": senkou_span_b,
        "chikou_span": chikou_span,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
    }


def volume_profile(
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    price_levels: int = 20,
    min_volume_threshold: float = 0.01,
) -> dict[str, Union[pd.Series, list[float]]]:
    """Calculate Volume Profile indicators.

    Volume Profile shows the distribution of trading volume at different price levels,
    helping identify significant support/resistance levels and value areas.

    Args:
        high: High prices series
        low: Low prices series
        volume: Volume series
        price_levels: Number of price levels to analyze (default: 20)
        min_volume_threshold: Minimum volume threshold as fraction of total volume (default: 0.01)

    Returns:
        Dictionary containing:
        - volume_at_price: Volume distribution at each price level
        - price_levels: Price levels array
        - poc: Point of Control (price level with highest volume)
        - value_area_high: Upper boundary of value area (70% volume)
        - value_area_low: Lower boundary of value area (70% volume)
        - vah: Value Area High
        - val: Value Area Low

    Raises:
        ValueError: If input data is invalid
    """
    # Input validation
    _validate_ohlcv_data(high, low, pd.Series([0] * len(high)), volume)

    if price_levels <= 0:
        raise ValueError("Price levels must be positive")

    if not (0 <= min_volume_threshold <= 1):
        raise ValueError("Volume threshold must be between 0 and 1")

    # Convert to pandas Series
    high = pd.Series(high)
    low = pd.Series(low)
    volume = pd.Series(volume)

    # Calculate price range
    min_price = low.min()
    max_price = high.max()
    price_range = max_price - min_price

    if price_range == 0:
        # All prices are the same
        price_levels_array = np.array([min_price])
        volume_at_price = np.array([volume.sum()])
    else:
        # Create price levels
        price_levels_array = np.linspace(min_price, max_price, price_levels)
        volume_at_price = np.zeros(price_levels)

        # Distribute volume across price levels
        for i in range(len(high)):
            if not (
                pd.isna(high.iloc[i]) or pd.isna(low.iloc[i]) or pd.isna(volume.iloc[i])
            ):
                # Find price levels that this bar contributes to
                bar_min = low.iloc[i]
                bar_max = high.iloc[i]
                bar_volume = volume.iloc[i]

                # Find overlapping price levels
                overlapping_levels = np.where(
                    (price_levels_array >= bar_min) & (price_levels_array <= bar_max)
                )[0]

                if len(overlapping_levels) > 0:
                    # Distribute volume equally across overlapping levels
                    volume_per_level = bar_volume / len(overlapping_levels)
                    volume_at_price[overlapping_levels] += volume_per_level

    # Find Point of Control (POC)
    poc_index = np.argmax(volume_at_price)
    poc = price_levels_array[poc_index]

    # Calculate Value Area (70% of volume)
    total_volume = np.sum(volume_at_price)
    target_volume = total_volume * 0.7

    # Sort by volume to find value area
    sorted_indices = np.argsort(volume_at_price)[::-1]
    cumulative_volume = 0
    value_area_indices = []

    for idx in sorted_indices:
        cumulative_volume += volume_at_price[idx]
        value_area_indices.append(idx)
        if cumulative_volume >= target_volume:
            break

    value_area_indices = np.array(value_area_indices)
    value_area_prices = price_levels_array[value_area_indices]

    vah = np.max(value_area_prices) if len(value_area_prices) > 0 else poc
    val = np.min(value_area_prices) if len(value_area_prices) > 0 else poc

    return {
        "volume_at_price": pd.Series(volume_at_price, index=price_levels_array),
        "price_levels": price_levels_array.tolist(),
        "poc": poc,
        "value_area_high": vah,
        "value_area_low": val,
        "vah": vah,
        "val": val,
    }


def market_facilitation_index(
    high: pd.Series, low: pd.Series, volume: pd.Series
) -> pd.Series:
    """Calculate Market Facilitation Index (MFI).

    The Market Facilitation Index measures the efficiency of price movement
    relative to volume. It helps identify whether price movement is supported
    by volume or if it's just noise.

    Args:
        high: High prices series
        low: Low prices series
        volume: Volume series

    Returns:
        Market Facilitation Index series

    Raises:
        ValueError: If input data is invalid
    """
    # Input validation
    _validate_ohlcv_data(high, low, pd.Series([0] * len(high)), volume)

    # Convert to pandas Series
    high = pd.Series(high)
    low = pd.Series(low)
    volume = pd.Series(volume)

    # Calculate price range
    price_range = high - low

    # Avoid division by zero
    volume_safe = volume.replace(0, np.nan)

    # Market Facilitation Index = Price Range / Volume
    mfi = price_range / volume_safe

    # Handle NaN values (when volume is 0)
    mfi = mfi.fillna(0)

    return mfi


def williams_r(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Calculate Williams %R oscillator.

    Williams %R is a momentum indicator that measures overbought/oversold conditions.
    It oscillates between -100 and 0, with values near -100 indicating oversold
    conditions and values near 0 indicating overbought conditions.

    Args:
        high: High prices series
        low: Low prices series
        close: Close prices series
        period: Lookback period (default: 14)

    Returns:
        Williams %R series (values between -100 and 0)

    Raises:
        ValueError: If input data is invalid or insufficient
    """
    # Input validation
    _validate_ohlcv_data(high, low, close)

    if period <= 0:
        raise ValueError("Period must be positive")

    if len(high) < period:
        raise ValueError(f"Insufficient data: need at least {period} periods")

    # Convert to pandas Series
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)

    # Calculate highest high and lowest low over the period
    highest_high = high.rolling(window=period, min_periods=1).max()
    lowest_low = low.rolling(window=period, min_periods=1).min()

    # Calculate Williams %R
    # Formula: -100 * (Highest High - Close) / (Highest High - Lowest Low)
    price_range = highest_high - lowest_low

    # Avoid division by zero
    price_range_safe = price_range.replace(0, np.nan)

    williams_r = -100 * (highest_high - close) / price_range_safe

    # Handle NaN values (when price range is 0)
    williams_r = williams_r.fillna(-50)  # Neutral value when range is 0

    return williams_r


class AdvancedIndicators(LoggerMixin):
    """Advanced technical indicators calculator with logging support."""

    def __init__(self):
        """Initialize the advanced indicators calculator."""
        super().__init__()

    def calculate_ichimoku_cloud(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_span_b_period: int = 52,
    ) -> dict[str, pd.Series]:
        """Calculate Ichimoku Cloud with logging."""
        try:
            result = ichimoku_cloud(
                high, low, close, tenkan_period, kijun_period, senkou_span_b_period
            )
            self.logger.debug(f"Calculated Ichimoku Cloud for {len(high)} periods")
            return result
        except Exception as e:
            self.logger.error(f"Failed to calculate Ichimoku Cloud: {e}")
            raise

    def calculate_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """Calculate Average True Range (ATR) indicator.

        Args:
            high: High prices series
            low: Low prices series
            close: Close prices series
            period: ATR period (default 14)

        Returns:
            ATR values as pandas Series
        """
        try:
            _validate_ohlcv_data(high, low, close)

            # Calculate True Range (TR)
            high_low = high - low
            high_close_prev = np.abs(high - close.shift(1))
            low_close_prev = np.abs(low - close.shift(1))
            
            # True Range is the maximum of:
            # 1. High - Low
            # 2. |High - Previous Close|
            # 3. |Low - Previous Close|
            true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
            
            # Calculate ATR using Wilder's smoothing (exponential moving average)
            atr = true_range.ewm(alpha=1.0/period, adjust=False).mean()
            
            self.logger.debug(f"Calculated ATR for {len(high)} periods with {period}-period smoothing")
            return atr
        except Exception as e:
            self.logger.error(f"Failed to calculate ATR: {e}")
            raise

    def calculate_volume_profile(
        self,
        high: pd.Series,
        low: pd.Series,
        volume: pd.Series,
        price_levels: int = 20,
        min_volume_threshold: float = 0.01,
    ) -> dict[str, Union[pd.Series, list[float]]]:
        """Calculate Volume Profile with logging."""
        try:
            result = volume_profile(
                high, low, volume, price_levels, min_volume_threshold
            )
            self.logger.debug(
                f"Calculated Volume Profile for {len(high)} periods with {price_levels} levels"
            )
            return result
        except Exception as e:
            self.logger.error(f"Failed to calculate Volume Profile: {e}")
            raise

    def calculate_market_facilitation_index(
        self, high: pd.Series, low: pd.Series, volume: pd.Series
    ) -> pd.Series:
        """Calculate Market Facilitation Index with logging."""
        try:
            result = market_facilitation_index(high, low, volume)
            self.logger.debug(
                f"Calculated Market Facilitation Index for {len(high)} periods"
            )
            return result
        except Exception as e:
            self.logger.error(f"Failed to calculate Market Facilitation Index: {e}")
            raise

    def calculate_williams_r(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
    ) -> pd.Series:
        """Calculate Williams %R with logging."""
        try:
            result = williams_r(high, low, close, period)
            self.logger.debug(
                f"Calculated Williams %R for {len(high)} periods with period {period}"
            )
            return result
        except Exception as e:
            self.logger.error(f"Failed to calculate Williams %R: {e}")
            raise

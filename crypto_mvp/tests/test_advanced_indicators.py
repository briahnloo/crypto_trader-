"""
Unit tests for advanced technical indicators.
"""


import numpy as np
import pandas as pd
import pytest

from src.crypto_mvp.indicators.advanced import (
    AdvancedIndicators,
    ichimoku_cloud,
    market_facilitation_index,
    volume_profile,
    williams_r,
)


class TestAdvancedIndicators:
    """Test cases for advanced technical indicators."""

    @pytest.fixture
    def synthetic_ohlcv_data(self):
        """Create synthetic OHLCV data for testing."""
        np.random.seed(42)  # For reproducible tests

        # Generate realistic price data
        n_periods = 100
        base_price = 50000

        # Generate price movements with trend and noise
        trend = np.linspace(0, 0.1, n_periods)  # 10% upward trend
        noise = np.random.normal(0, 0.02, n_periods)  # 2% daily volatility
        price_changes = trend + noise

        # Calculate cumulative prices
        close_prices = base_price * (1 + price_changes).cumprod()

        # Generate high/low prices around close
        daily_ranges = np.random.uniform(
            0.005, 0.03, n_periods
        )  # 0.5% to 3% daily range
        high_prices = close_prices * (1 + daily_ranges / 2)
        low_prices = close_prices * (1 - daily_ranges / 2)

        # Generate volume data
        base_volume = 1000000
        volume_multiplier = np.random.uniform(0.5, 2.0, n_periods)
        volumes = base_volume * volume_multiplier

        return {
            "high": pd.Series(high_prices),
            "low": pd.Series(low_prices),
            "close": pd.Series(close_prices),
            "volume": pd.Series(volumes),
        }

    def test_ichimoku_cloud_basic(self, synthetic_ohlcv_data):
        """Test basic Ichimoku Cloud calculation."""
        data = synthetic_ohlcv_data

        result = ichimoku_cloud(data["high"], data["low"], data["close"])

        # Check that all required keys are present
        expected_keys = [
            "tenkan_sen",
            "kijun_sen",
            "senkou_span_a",
            "senkou_span_b",
            "chikou_span",
            "cloud_top",
            "cloud_bottom",
        ]
        assert all(key in result for key in expected_keys)

        # Check that all results are pandas Series
        for key in expected_keys:
            assert isinstance(result[key], pd.Series)
            assert len(result[key]) == len(data["high"])

        # Check that values are reasonable
        assert result["tenkan_sen"].notna().any()
        assert result["kijun_sen"].notna().any()
        assert result["cloud_top"].notna().any()
        assert result["cloud_bottom"].notna().any()

        # Cloud top should be >= cloud bottom
        valid_mask = result["cloud_top"].notna() & result["cloud_bottom"].notna()
        assert (
            result["cloud_top"][valid_mask] >= result["cloud_bottom"][valid_mask]
        ).all()

    def test_ichimoku_cloud_insufficient_data(self):
        """Test Ichimoku Cloud with insufficient data."""
        high = pd.Series([50000, 51000, 52000])
        low = pd.Series([49000, 50000, 51000])
        close = pd.Series([49500, 50500, 51500])

        with pytest.raises(ValueError, match="Insufficient data"):
            ichimoku_cloud(high, low, close, senkou_span_b_period=52)

    def test_ichimoku_cloud_invalid_periods(self, synthetic_ohlcv_data):
        """Test Ichimoku Cloud with invalid periods."""
        data = synthetic_ohlcv_data

        with pytest.raises(ValueError, match="All periods must be positive"):
            ichimoku_cloud(data["high"], data["low"], data["close"], tenkan_period=0)

    def test_volume_profile_basic(self, synthetic_ohlcv_data):
        """Test basic Volume Profile calculation."""
        data = synthetic_ohlcv_data

        result = volume_profile(data["high"], data["low"], data["volume"])

        # Check that all required keys are present
        expected_keys = [
            "volume_at_price",
            "price_levels",
            "poc",
            "value_area_high",
            "value_area_low",
            "vah",
            "val",
        ]
        assert all(key in result for key in expected_keys)

        # Check data types
        assert isinstance(result["volume_at_price"], pd.Series)
        assert isinstance(result["price_levels"], list)
        assert isinstance(result["poc"], (int, float))
        assert isinstance(result["vah"], (int, float))
        assert isinstance(result["val"], (int, float))

        # Check that POC is within price range
        min_price = data["low"].min()
        max_price = data["high"].max()
        assert min_price <= result["poc"] <= max_price

        # Check that value area boundaries are reasonable
        assert result["val"] <= result["vah"]
        assert min_price <= result["val"] <= max_price
        assert min_price <= result["vah"] <= max_price

        # Check that volume distribution is reasonable
        volume_sum = result["volume_at_price"].sum()
        assert volume_sum > 0  # Should have some volume distributed

    def test_volume_profile_custom_levels(self, synthetic_ohlcv_data):
        """Test Volume Profile with custom price levels."""
        data = synthetic_ohlcv_data

        result = volume_profile(
            data["high"], data["low"], data["volume"], price_levels=10
        )

        assert len(result["price_levels"]) == 10
        assert len(result["volume_at_price"]) == 10

    def test_volume_profile_single_price(self):
        """Test Volume Profile with single price level."""
        high = pd.Series([50000, 50000, 50000])
        low = pd.Series([50000, 50000, 50000])
        volume = pd.Series([1000, 2000, 3000])

        result = volume_profile(high, low, volume)

        assert result["poc"] == 50000
        assert result["vah"] == 50000
        assert result["val"] == 50000
        assert result["volume_at_price"].sum() == 6000

    def test_market_facilitation_index_basic(self, synthetic_ohlcv_data):
        """Test basic Market Facilitation Index calculation."""
        data = synthetic_ohlcv_data

        result = market_facilitation_index(data["high"], data["low"], data["volume"])

        # Check that result is a pandas Series
        assert isinstance(result, pd.Series)
        assert len(result) == len(data["high"])

        # Check that values are non-negative (price range / volume)
        assert (result >= 0).all()

        # Check that NaN values are handled (when volume is 0)
        assert not result.isna().any()

    def test_market_facilitation_index_zero_volume(self):
        """Test Market Facilitation Index with zero volume."""
        high = pd.Series([50000, 51000, 52000])
        low = pd.Series([49000, 50000, 51000])
        volume = pd.Series([1000, 0, 2000])  # Zero volume in middle

        result = market_facilitation_index(high, low, volume)

        # Should handle zero volume gracefully
        assert not result.isna().any()
        assert result.iloc[1] == 0  # Zero volume should result in 0 MFI

    def test_williams_r_basic(self, synthetic_ohlcv_data):
        """Test basic Williams %R calculation."""
        data = synthetic_ohlcv_data

        result = williams_r(data["high"], data["low"], data["close"], period=14)

        # Check that result is a pandas Series
        assert isinstance(result, pd.Series)
        assert len(result) == len(data["high"])

        # Check that values are between -100 and 0
        valid_values = result.dropna()
        assert (valid_values >= -100).all()
        assert (valid_values <= 0).all()

        # Check that we have some valid values
        assert len(valid_values) > 0

    def test_williams_r_different_periods(self, synthetic_ohlcv_data):
        """Test Williams %R with different periods."""
        data = synthetic_ohlcv_data

        result_14 = williams_r(data["high"], data["low"], data["close"], period=14)
        result_21 = williams_r(data["high"], data["low"], data["close"], period=21)

        # Both should have same length
        assert len(result_14) == len(result_21)

        # Values should be different due to different periods
        assert not result_14.equals(result_21)

    def test_williams_r_insufficient_data(self):
        """Test Williams %R with insufficient data."""
        high = pd.Series([50000, 51000])
        low = pd.Series([49000, 50000])
        close = pd.Series([49500, 50500])

        with pytest.raises(ValueError, match="Insufficient data"):
            williams_r(high, low, close, period=14)

    def test_williams_r_invalid_period(self, synthetic_ohlcv_data):
        """Test Williams %R with invalid period."""
        data = synthetic_ohlcv_data

        with pytest.raises(ValueError, match="Period must be positive"):
            williams_r(data["high"], data["low"], data["close"], period=0)

    def test_williams_r_constant_prices(self):
        """Test Williams %R with constant prices."""
        high = pd.Series([50000] * 20)
        low = pd.Series([50000] * 20)
        close = pd.Series([50000] * 20)

        result = williams_r(high, low, close, period=14)

        # Should handle constant prices gracefully
        assert not result.isna().any()
        assert (result == -50).all()  # Neutral value when range is 0

    def test_advanced_indicators_class(self, synthetic_ohlcv_data):
        """Test AdvancedIndicators class methods."""
        data = synthetic_ohlcv_data
        indicators = AdvancedIndicators()

        # Test Ichimoku Cloud
        ichimoku_result = indicators.calculate_ichimoku_cloud(
            data["high"], data["low"], data["close"]
        )
        assert "tenkan_sen" in ichimoku_result

        # Test Volume Profile
        volume_result = indicators.calculate_volume_profile(
            data["high"], data["low"], data["volume"]
        )
        assert "poc" in volume_result

        # Test Market Facilitation Index
        mfi_result = indicators.calculate_market_facilitation_index(
            data["high"], data["low"], data["volume"]
        )
        assert isinstance(mfi_result, pd.Series)

        # Test Williams %R
        williams_result = indicators.calculate_williams_r(
            data["high"], data["low"], data["close"]
        )
        assert isinstance(williams_result, pd.Series)

    def test_input_validation_errors(self):
        """Test input validation for all indicators."""
        # Test with mismatched lengths
        high = pd.Series([50000, 51000])
        low = pd.Series([49000, 50000, 51000])  # Different length
        close = pd.Series([49500, 50500])
        volume = pd.Series([1000, 2000])

        with pytest.raises(ValueError, match="same length"):
            ichimoku_cloud(high, low, close)

        with pytest.raises(ValueError, match="same length"):
            volume_profile(high, low, volume)

        with pytest.raises(ValueError, match="same length"):
            market_facilitation_index(high, low, volume)

        with pytest.raises(ValueError, match="same length"):
            williams_r(high, low, close)

        # Test with empty data
        empty_series = pd.Series([], dtype=float)

        with pytest.raises(ValueError, match="cannot be empty"):
            ichimoku_cloud(empty_series, empty_series, empty_series)

    def test_edge_cases(self):
        """Test edge cases for all indicators."""
        # Test with single data point
        high = pd.Series([50000])
        low = pd.Series([49000])
        close = pd.Series([49500])
        volume = pd.Series([1000])

        # These should work with single data point
        mfi_result = market_facilitation_index(high, low, volume)
        assert len(mfi_result) == 1

        # Test with NaN values
        high_with_nan = pd.Series([50000, np.nan, 52000])
        low_with_nan = pd.Series([49000, np.nan, 51000])
        close_with_nan = pd.Series([49500, np.nan, 51500])
        volume_with_nan = pd.Series([1000, np.nan, 2000])

        # Should handle NaN values gracefully
        mfi_result = market_facilitation_index(
            high_with_nan, low_with_nan, volume_with_nan
        )
        assert len(mfi_result) == 3

        williams_result = williams_r(
            high_with_nan, low_with_nan, close_with_nan, period=1
        )
        assert len(williams_result) == 3


if __name__ == "__main__":
    pytest.main([__file__])

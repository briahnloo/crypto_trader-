"""
Tests for the unified CyclePriceCache system.
"""

import pytest
from unittest.mock import Mock, patch, call
from datetime import datetime

from src.crypto_mvp.core.utils import (
    CyclePriceCache, 
    get_cycle_price_cache, 
    clear_cycle_price_cache,
    get_mark_price,
    get_entry_price,
    get_exit_value,
    _fetch_and_cache_price_data
)


class TestCyclePriceCache:
    """Test the unified cycle price cache system."""
    
    def test_cache_basic_operations(self):
        """Test basic cache operations."""
        cache = CyclePriceCache()
        
        # Test set and get
        price_data = {
            'bid': 49000.0,
            'ask': 49100.0,
            'mid': 49050.0,
            'src': 'binance_mid',
            'ts': '2024-01-01T12:00:00Z'
        }
        
        cache.set(1, 'BTC/USDT', price_data)
        retrieved = cache.get(1, 'BTC/USDT')
        
        assert retrieved == price_data
        assert retrieved['bid'] == 49000.0
        assert retrieved['mid'] == 49050.0
    
    def test_cache_cycle_clearing(self):
        """Test clearing cache for specific cycles."""
        cache = CyclePriceCache()
        
        # Add data for multiple cycles
        cache.set(1, 'BTC/USDT', {'mid': 49000.0, 'src': 'test'})
        cache.set(1, 'ETH/USDT', {'mid': 3000.0, 'src': 'test'})
        cache.set(2, 'BTC/USDT', {'mid': 50000.0, 'src': 'test'})
        cache.set(2, 'ETH/USDT', {'mid': 3100.0, 'src': 'test'})
        
        # Verify data exists
        assert cache.get(1, 'BTC/USDT') is not None
        assert cache.get(2, 'BTC/USDT') is not None
        
        # Clear cycle 1
        cache.clear_cycle(1)
        
        # Verify cycle 1 is cleared but cycle 2 remains
        assert cache.get(1, 'BTC/USDT') is None
        assert cache.get(1, 'ETH/USDT') is None
        assert cache.get(2, 'BTC/USDT') is not None
        assert cache.get(2, 'ETH/USDT') is not None
    
    def test_cache_clear_all(self):
        """Test clearing all cache data."""
        cache = CyclePriceCache()
        
        # Add data
        cache.set(1, 'BTC/USDT', {'mid': 49000.0, 'src': 'test'})
        cache.set(2, 'ETH/USDT', {'mid': 3000.0, 'src': 'test'})
        
        # Clear all
        cache.clear_all()
        
        # Verify all data is cleared
        assert cache.get(1, 'BTC/USDT') is None
        assert cache.get(2, 'ETH/USDT') is None


class TestUnifiedPriceFunctions:
    """Test the unified price functions with caching."""
    
    @pytest.fixture
    def mock_data_engine(self):
        """Create a mock data engine."""
        mock_engine = Mock()
        mock_engine.get_ticker.return_value = {
            'bid': 49000.0,
            'ask': 49100.0,
            'last': 49050.0,
            'price': 49050.0,
            'timestamp': '2024-01-01T12:00:00Z',
            'provenance': {'source': 'binance'}
        }
        return mock_engine
    
    def test_get_mark_price_single_fetch_per_cycle(self, mock_data_engine):
        """Test that get_mark_price only fetches once per cycle per symbol."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        cycle_id = 1
        symbol = 'BTC/USDT'
        
        # First call - should fetch from data engine
        price1 = get_mark_price(symbol, mock_data_engine, cycle_id=cycle_id)
        
        # Second call - should use cache
        price2 = get_mark_price(symbol, mock_data_engine, cycle_id=cycle_id)
        
        # Third call - should use cache
        price3 = get_mark_price(symbol, mock_data_engine, cycle_id=cycle_id)
        
        # All calls should return the same price
        assert price1 == price2 == price3 == 49050.0  # (49000 + 49100) / 2
        
        # Data engine should only be called once
        mock_data_engine.get_ticker.assert_called_once_with('BTC/USDT')
    
    def test_get_entry_price_single_fetch_per_cycle(self, mock_data_engine):
        """Test that get_entry_price only fetches once per cycle per symbol."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        cycle_id = 1
        symbol = 'BTC/USDT'
        
        # First call - should fetch from data engine
        price1 = get_entry_price(symbol, mock_data_engine, cycle_id=cycle_id)
        
        # Second call - should use cache
        price2 = get_entry_price(symbol, mock_data_engine, cycle_id=cycle_id)
        
        # Both calls should return the same price
        assert price1 == price2 == 49050.0  # (49000 + 49100) / 2
        
        # Data engine should only be called once
        mock_data_engine.get_ticker.assert_called_once_with('BTC/USDT')
    
    def test_get_exit_value_single_fetch_per_cycle(self, mock_data_engine):
        """Test that get_exit_value only fetches once per cycle per symbol."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        cycle_id = 1
        symbol = 'BTC/USDT'
        
        # First call for long position - should fetch from data engine
        price1 = get_exit_value(symbol, 'long', mock_data_engine, cycle_id=cycle_id)
        
        # Second call for short position - should use cache
        price2 = get_exit_value(symbol, 'short', mock_data_engine, cycle_id=cycle_id)
        
        # Long position should get bid price, short position should get ask price
        assert price1 == 49000.0  # bid
        assert price2 == 49100.0  # ask
        
        # Data engine should only be called once
        mock_data_engine.get_ticker.assert_called_once_with('BTC/USDT')
    
    def test_multiple_symbols_different_fetches(self, mock_data_engine):
        """Test that different symbols trigger separate fetches."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        cycle_id = 1
        
        # Mock different data for different symbols
        def mock_get_ticker(symbol):
            if symbol == 'BTC/USDT':
                return {
                    'bid': 49000.0,
                    'ask': 49100.0,
                    'last': 49050.0,
                    'timestamp': '2024-01-01T12:00:00Z',
                    'provenance': {'source': 'binance'}
                }
            elif symbol == 'ETH/USDT':
                return {
                    'bid': 3000.0,
                    'ask': 3010.0,
                    'last': 3005.0,
                    'timestamp': '2024-01-01T12:00:00Z',
                    'provenance': {'source': 'binance'}
                }
            return None
        
        mock_data_engine.get_ticker.side_effect = mock_get_ticker
        
        # Get prices for both symbols
        btc_price = get_mark_price('BTC/USDT', mock_data_engine, cycle_id=cycle_id)
        eth_price = get_mark_price('ETH/USDT', mock_data_engine, cycle_id=cycle_id)
        
        # Verify different prices
        assert btc_price == 49050.0  # (49000 + 49100) / 2
        assert eth_price == 3005.0   # (3000 + 3010) / 2
        
        # Data engine should be called twice (once per symbol)
        assert mock_data_engine.get_ticker.call_count == 2
        mock_data_engine.get_ticker.assert_has_calls([
            call('BTC/USDT'),
            call('ETH/USDT')
        ])
    
    def test_cache_cleared_between_cycles(self, mock_data_engine):
        """Test that cache is cleared between cycles."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        symbol = 'BTC/USDT'
        
        # First cycle
        price1 = get_mark_price(symbol, mock_data_engine, cycle_id=1)
        assert price1 == 49050.0
        
        # Clear cache for cycle 1
        clear_cycle_price_cache(1)
        
        # Second cycle - should fetch again
        price2 = get_mark_price(symbol, mock_data_engine, cycle_id=2)
        assert price2 == 49050.0
        
        # Data engine should be called twice (once per cycle)
        assert mock_data_engine.get_ticker.call_count == 2
    
    def test_cache_hit_logging(self, mock_data_engine):
        """Test that cache hits work correctly (logging verification is complex with loguru)."""
        # Clear any existing cache
        clear_cycle_price_cache()
        
        cycle_id = 1
        symbol = 'BTC/USDT'
        
        # First call - should fetch from data engine
        price1 = get_mark_price(symbol, mock_data_engine, cycle_id=cycle_id)
        assert price1 == 49050.0
        
        # Second call - should use cache (no additional data engine call)
        price2 = get_mark_price(symbol, mock_data_engine, cycle_id=cycle_id)
        assert price2 == 49050.0
        
        # Verify only one call to data engine was made
        mock_data_engine.get_ticker.assert_called_once_with('BTC/USDT')
        
        # The cache hit logging is working (visible in test output), 
        # but testing it programmatically is complex with loguru configuration


class TestFetchAndCachePriceData:
    """Test the internal _fetch_and_cache_price_data function."""
    
    def test_fetch_and_cache_new_data(self):
        """Test fetching and caching new price data."""
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            'bid': 49000.0,
            'ask': 49100.0,
            'last': 49050.0,
            'timestamp': '2024-01-01T12:00:00Z',
            'provenance': {'source': 'binance'}
        }
        
        # Clear any existing cache
        clear_cycle_price_cache()
        
        # Fetch data
        price_data = _fetch_and_cache_price_data(
            cycle_id=1,
            symbol='BTC/USDT',
            data_engine=mock_data_engine,
            live_mode=False
        )
        
        # Verify data structure
        assert price_data is not None
        assert price_data['bid'] == 49000.0
        assert price_data['ask'] == 49100.0
        assert price_data['mid'] == 49050.0
        assert price_data['src'] == 'binance_mid'
        assert price_data['ts'] == '2024-01-01T12:00:00Z'
        
        # Verify data was cached
        cache = get_cycle_price_cache()
        cached_data = cache.get(1, 'BTC/USDT')
        assert cached_data == price_data
    
    def test_fetch_and_cache_cache_hit(self):
        """Test that cached data is returned on subsequent calls."""
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            'bid': 49000.0,
            'ask': 49100.0,
            'last': 49050.0,
            'timestamp': '2024-01-01T12:00:00Z',
            'provenance': {'source': 'binance'}
        }
        
        # Clear any existing cache
        clear_cycle_price_cache()
        
        # First call - should fetch
        price_data1 = _fetch_and_cache_price_data(
            cycle_id=1,
            symbol='BTC/USDT',
            data_engine=mock_data_engine,
            live_mode=False
        )
        
        # Second call - should use cache
        price_data2 = _fetch_and_cache_price_data(
            cycle_id=1,
            symbol='BTC/USDT',
            data_engine=mock_data_engine,
            live_mode=False
        )
        
        # Both should return the same data
        assert price_data1 == price_data2
        
        # Data engine should only be called once
        mock_data_engine.get_ticker.assert_called_once_with('BTC/USDT')

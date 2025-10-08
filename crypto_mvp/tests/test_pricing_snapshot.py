"""
Unit tests for pricing snapshot system.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.crypto_mvp.core.pricing_snapshot import (
    PricingSnapshot,
    PriceData,
    create_pricing_snapshot,
    clear_pricing_snapshot,
    get_current_pricing_snapshot,
    is_fresh_price_fetching_disabled
)
from src.crypto_mvp.core.utils import get_mark_price, get_entry_price, get_exit_value


class TestPricingSnapshot:
    """Test the PricingSnapshot class."""
    
    def test_pricing_snapshot_creation(self):
        """Test creating a pricing snapshot."""
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50000.0,
                    source="binance",
                    timestamp="2024-01-01T12:00:00Z",
                    bid=49950.0,
                    ask=50050.0,
                    mid=50000.0
                )
            }
        )
        
        assert snapshot.id == 1
        assert len(snapshot.by_symbol) == 1
        assert "BTC/USDT" in snapshot.by_symbol
    
    def test_get_mark_price(self):
        """Test getting mark price from snapshot."""
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50000.0,
                    source="binance",
                    timestamp="2024-01-01T12:00:00Z",
                    bid=49950.0,
                    ask=50050.0,
                    mid=50000.0
                )
            }
        )
        
        # Test hit
        price = snapshot.get_mark_price("BTC/USDT")
        assert price == 50000.0
        assert snapshot.hits == 1
        assert snapshot.misses == 0
        
        # Test miss
        price = snapshot.get_mark_price("ETH/USDT")
        assert price is None
        assert snapshot.hits == 1
        assert snapshot.misses == 1
    
    def test_get_entry_price(self):
        """Test getting entry price from snapshot."""
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50000.0,
                    source="binance",
                    timestamp="2024-01-01T12:00:00Z",
                    bid=49950.0,
                    ask=50050.0,
                    mid=50000.0
                )
            }
        )
        
        # Test with mid price available
        price = snapshot.get_entry_price("BTC/USDT")
        assert price == 50000.0  # Should use mid price
        
        # Test with no mid price (fallback to price)
        snapshot.by_symbol["BTC/USDT"].mid = None
        price = snapshot.get_entry_price("BTC/USDT")
        assert price == 50000.0  # Should fallback to price
    
    def test_get_exit_value(self):
        """Test getting exit value from snapshot."""
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50000.0,
                    source="binance",
                    timestamp="2024-01-01T12:00:00Z",
                    bid=49950.0,
                    ask=50050.0,
                    mid=50000.0
                )
            }
        )
        
        # Test long position (should use bid)
        price = snapshot.get_exit_value("BTC/USDT", "long")
        assert price == 49950.0
        
        # Test short position (should use ask)
        price = snapshot.get_exit_value("BTC/USDT", "short")
        assert price == 50050.0
        
        # Test with no bid/ask (fallback to mid)
        snapshot.by_symbol["BTC/USDT"].bid = None
        snapshot.by_symbol["BTC/USDT"].ask = None
        price = snapshot.get_exit_value("BTC/USDT", "long")
        assert price == 50000.0  # Should fallback to mid
    
    def test_get_pricing_context(self):
        """Test getting pricing context."""
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50000.0,
                    source="binance",
                    timestamp="2024-01-01T12:00:00Z"
                )
            }
        )
        
        # Make some calls to generate hits/misses
        snapshot.get_mark_price("BTC/USDT")  # hit
        snapshot.get_mark_price("ETH/USDT")  # miss
        
        context = snapshot.get_pricing_context()
        assert context["id"] == 1
        assert context["hits"] == 1
        assert context["misses"] == 1
        assert context["symbol_count"] == 1
        assert "staleness_ms" in context


class TestPricingSnapshotManager:
    """Test the pricing snapshot manager."""
    
    def setup_method(self):
        """Clear snapshot before each test."""
        clear_pricing_snapshot()
    
    def test_create_snapshot(self):
        """Test creating a pricing snapshot."""
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "bid": 49950.0,
            "ask": 50050.0,
            "mid": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        snapshot = create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        assert snapshot.id == 1
        assert "BTC/USDT" in snapshot.by_symbol
        assert snapshot.by_symbol["BTC/USDT"].price == 50000.0
        assert is_fresh_price_fetching_disabled()  # Should be disabled after creation
    
    def test_get_current_snapshot(self):
        """Test getting current snapshot."""
        # Initially no snapshot
        assert get_current_pricing_snapshot() is None
        
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        snapshot = create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # Should now have snapshot
        current = get_current_pricing_snapshot()
        assert current is not None
        assert current.id == 1
    
    def test_clear_snapshot(self):
        """Test clearing snapshot."""
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        assert get_current_pricing_snapshot() is not None
        assert is_fresh_price_fetching_disabled()
        
        # Clear snapshot
        clear_pricing_snapshot()
        
        assert get_current_pricing_snapshot() is None
        assert not is_fresh_price_fetching_disabled()


class TestPricingFunctionsWithSnapshot:
    """Test pricing functions with snapshot system."""
    
    def setup_method(self):
        """Clear snapshot before each test."""
        clear_pricing_snapshot()
    
    def test_get_mark_price_with_snapshot(self):
        """Test get_mark_price with snapshot."""
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "bid": 49950.0,
            "ask": 50050.0,
            "mid": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # Test with snapshot
        price = get_mark_price("BTC/USDT", mock_data_engine, cycle_id=1)
        assert price == 50000.0
        
        # Test miss
        price = get_mark_price("ETH/USDT", mock_data_engine, cycle_id=1)
        assert price is None
    
    def test_get_entry_price_with_snapshot(self):
        """Test get_entry_price with snapshot."""
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "bid": 49950.0,
            "ask": 50050.0,
            "mid": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # Test with snapshot
        price = get_entry_price("BTC/USDT", mock_data_engine, cycle_id=1)
        assert price == 50000.0  # Should use mid price
    
    def test_get_exit_value_with_snapshot(self):
        """Test get_exit_value with snapshot."""
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "bid": 49950.0,
            "ask": 50050.0,
            "mid": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # Test long position
        price = get_exit_value("BTC/USDT", "long", mock_data_engine, cycle_id=1)
        assert price == 49950.0  # Should use bid
        
        # Test short position
        price = get_exit_value("BTC/USDT", "short", mock_data_engine, cycle_id=1)
        assert price == 50050.0  # Should use ask
    
    def test_identical_values_with_same_snapshot(self):
        """Test that values computed in Steps 2-4 are identical when re-run with the same snapshot."""
        # Create snapshot
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "bid": 49950.0,
            "ask": 50050.0,
            "mid": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # First run - Step 2 (signals)
        mark_price_1 = get_mark_price("BTC/USDT", mock_data_engine, cycle_id=1)
        entry_price_1 = get_entry_price("BTC/USDT", mock_data_engine, cycle_id=1)
        exit_value_long_1 = get_exit_value("BTC/USDT", "long", mock_data_engine, cycle_id=1)
        exit_value_short_1 = get_exit_value("BTC/USDT", "short", mock_data_engine, cycle_id=1)
        
        # Second run - Step 3 (execution)
        mark_price_2 = get_mark_price("BTC/USDT", mock_data_engine, cycle_id=1)
        entry_price_2 = get_entry_price("BTC/USDT", mock_data_engine, cycle_id=1)
        exit_value_long_2 = get_exit_value("BTC/USDT", "long", mock_data_engine, cycle_id=1)
        exit_value_short_2 = get_exit_value("BTC/USDT", "short", mock_data_engine, cycle_id=1)
        
        # Third run - Step 4 (portfolio update)
        mark_price_3 = get_mark_price("BTC/USDT", mock_data_engine, cycle_id=1)
        entry_price_3 = get_entry_price("BTC/USDT", mock_data_engine, cycle_id=1)
        exit_value_long_3 = get_exit_value("BTC/USDT", "long", mock_data_engine, cycle_id=1)
        exit_value_short_3 = get_exit_value("BTC/USDT", "short", mock_data_engine, cycle_id=1)
        
        # All values should be identical across all runs
        assert mark_price_1 == mark_price_2 == mark_price_3 == 50000.0
        assert entry_price_1 == entry_price_2 == entry_price_3 == 50000.0
        assert exit_value_long_1 == exit_value_long_2 == exit_value_long_3 == 49950.0
        assert exit_value_short_1 == exit_value_short_2 == exit_value_short_3 == 50050.0
    
    def test_error_without_cycle_id(self):
        """Test that pricing functions error without cycle_id."""
        mock_data_engine = Mock()
        
        # Should error without cycle_id
        price = get_mark_price("BTC/USDT", mock_data_engine)
        assert price is None
        
        price = get_entry_price("BTC/USDT", mock_data_engine)
        assert price is None
        
        price = get_exit_value("BTC/USDT", "long", mock_data_engine)
        assert price is None
    
    def test_error_after_snapshot_creation(self):
        """Test that pricing functions error after snapshot creation when no snapshot exists."""
        # Create and clear snapshot to simulate post-snapshot state
        mock_data_engine = Mock()
        mock_data_engine.get_ticker.return_value = {
            "price": 50000.0,
            "timestamp": "2024-01-01T12:00:00Z",
            "provenance": {"source": "binance"}
        }
        
        create_pricing_snapshot(
            cycle_id=1,
            symbols=["BTC/USDT"],
            data_engine=mock_data_engine
        )
        
        # Clear snapshot but keep fresh price fetching disabled
        clear_pricing_snapshot()
        
        # Should error because fresh price fetching is disabled but no snapshot exists
        price = get_mark_price("BTC/USDT", mock_data_engine, cycle_id=1)
        assert price is None


if __name__ == "__main__":
    pytest.main([__file__])

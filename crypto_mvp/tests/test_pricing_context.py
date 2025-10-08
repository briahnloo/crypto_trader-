"""
Tests for pricing context functionality.

This module tests:
- PricingContext creation and management
- PricingContextError handling
- Cycle ID threading through pricing functions
- Hit/miss counter functionality
"""

import pytest
from unittest.mock import Mock, patch
from decimal import Decimal

# Import the modules we're testing
from src.crypto_mvp.core.utils import (
    PricingContext, PricingContextError, 
    get_mark_price, get_exit_value,
    set_pricing_context, clear_pricing_context, get_pricing_context
)


class TestPricingContext:
    """Test pricing context functionality."""
    
    def test_pricing_context_creation(self):
        """Test creating a pricing context."""
        context = PricingContext(cycle_id=123, timestamp=1000.0)
        
        assert context.cycle_id == 123
        assert context.timestamp == 1000.0
        assert context.staleness_ms == 0
        assert context.hit_count == 0
        assert context.miss_count == 0
        assert context.error_count == 0
        assert not context._logged_error
    
    def test_pricing_context_records(self):
        """Test recording hits, misses, and errors."""
        context = PricingContext(cycle_id=123)
        
        # Record some activity
        context.record_hit()
        context.record_hit()
        context.record_miss()
        context.record_error()
        
        assert context.hit_count == 2
        assert context.miss_count == 1
        assert context.error_count == 1
    
    def test_pricing_context_error_logging(self):
        """Test error logging (once per cycle)."""
        context = PricingContext(cycle_id=123)
        
        # First call should allow logging
        assert context.should_log_error() is True
        
        # Second call should not allow logging
        assert context.should_log_error() is False
        
        # Third call should still not allow logging
        assert context.should_log_error() is False
    
    def test_pricing_context_stats(self):
        """Test getting pricing context statistics."""
        context = PricingContext(cycle_id=123)
        
        # Add some activity
        context.record_hit()
        context.record_hit()
        context.record_miss()
        context.record_error()
        context.update_staleness(150)
        
        stats = context.get_stats()
        
        assert stats["cycle_id"] == 123
        assert stats["hit_count"] == 2
        assert stats["miss_count"] == 1
        assert stats["error_count"] == 1
        assert stats["staleness_ms"] == 150
        assert stats["hit_rate_pct"] == 50.0  # 2 hits out of 4 total requests


class TestPricingContextManagement:
    """Test pricing context management functions."""
    
    def test_set_get_clear_pricing_context(self):
        """Test setting, getting, and clearing pricing context."""
        # Initially no context
        assert get_pricing_context() is None
        
        # Set context
        context = set_pricing_context(456)
        assert context.cycle_id == 456
        assert get_pricing_context() is context
        
        # Clear context
        clear_pricing_context()
        assert get_pricing_context() is None
    
    def test_set_pricing_context_creates_new_instance(self):
        """Test that set_pricing_context creates a new instance."""
        context1 = set_pricing_context(123)
        context2 = set_pricing_context(456)
        
        assert context1 is not context2
        assert context1.cycle_id == 123
        assert context2.cycle_id == 456
        assert get_pricing_context() is context2


class TestPricingContextError:
    """Test PricingContextError functionality."""
    
    def test_pricing_context_error_creation(self):
        """Test creating a PricingContextError."""
        error = PricingContextError("No valid pricing context for cycle 123")
        assert str(error) == "No valid pricing context for cycle 123"
        assert isinstance(error, Exception)


class TestPricingFunctionsWithContext:
    """Test pricing functions with pricing context."""
    
    def setup_method(self):
        """Set up test environment."""
        clear_pricing_context()
    
    def teardown_method(self):
        """Clean up test environment."""
        clear_pricing_context()
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_get_mark_price_without_context_raises_error(self, mock_snapshot):
        """Test that get_mark_price raises PricingContextError without context."""
        mock_snapshot.return_value = None
        
        with pytest.raises(PricingContextError, match="No valid pricing context for cycle 123"):
            get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=123
            )
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_get_mark_price_with_wrong_context_raises_error(self, mock_snapshot):
        """Test that get_mark_price raises PricingContextError with wrong context."""
        mock_snapshot.return_value = None
        
        # Set context for cycle 456
        set_pricing_context(456)
        
        with pytest.raises(PricingContextError, match="No valid pricing context for cycle 123"):
            get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=123
            )
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_get_mark_price_with_correct_context_succeeds(self, mock_snapshot):
        """Test that get_mark_price succeeds with correct context."""
        mock_snapshot.return_value = None
        
        # Set context for cycle 123
        context = set_pricing_context(123)
        
        result = get_mark_price(
            symbol="BTC/USDT",
            data_engine=Mock(),
            cycle_id=123
        )
        
        assert result is None  # No snapshot available
        assert context.error_count == 1  # Should record error
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_get_exit_value_without_context_raises_error(self, mock_snapshot):
        """Test that get_exit_value raises PricingContextError without context."""
        mock_snapshot.return_value = None
        
        with pytest.raises(PricingContextError, match="No valid pricing context for cycle 123"):
            get_exit_value(
                symbol="BTC/USDT",
                side="long",
                data_engine=Mock(),
                cycle_id=123
            )
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_get_exit_value_with_correct_context_succeeds(self, mock_snapshot):
        """Test that get_exit_value succeeds with correct context."""
        mock_snapshot.return_value = None
        
        # Set context for cycle 123
        context = set_pricing_context(123)
        
        result = get_exit_value(
            symbol="BTC/USDT",
            side="long",
            data_engine=Mock(),
            cycle_id=123
        )
        
        assert result is None  # No snapshot available
        assert context.error_count == 1  # Should record error
    
    @patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot')
    def test_pricing_context_tracks_hits_and_misses(self, mock_snapshot):
        """Test that pricing context tracks hits and misses correctly."""
        # Mock snapshot with some data
        mock_snapshot_instance = Mock()
        mock_snapshot_instance.get_mark_price.return_value = 50000.0
        mock_snapshot.return_value = mock_snapshot_instance
        
        # Set context for cycle 123
        context = set_pricing_context(123)
        
        # Mock the to_canonical function
        with patch('src.crypto_mvp.core.utils.to_canonical', return_value="BTC/USDT"):
            result = get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=123
            )
        
        assert result == 50000.0
        assert context.hit_count == 1
        assert context.miss_count == 0
        assert context.error_count == 0


class TestCycleIdThreading:
    """Test that cycle_id is properly threaded through the system."""
    
    def test_cycle_id_keyword_only_requirement(self):
        """Test that cycle_id is required as keyword-only argument."""
        # This should work (keyword argument) - but fail due to no context
        with pytest.raises(PricingContextError):
            get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=123
            )
        
        # This should fail (positional argument) - TypeError due to keyword-only
        with pytest.raises(TypeError):
            get_mark_price(
                "BTC/USDT",
                Mock(),
                123  # This should fail because cycle_id is keyword-only
            )
    
    def test_cycle_id_validation_in_functions(self):
        """Test that cycle_id is validated in pricing functions."""
        # Set context for cycle 123
        context = set_pricing_context(123)
        
        # Test with correct cycle_id
        with patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot', return_value=None):
            result = get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=123
            )
            assert result is None  # No snapshot
            assert context.error_count == 1
        
        # Test with wrong cycle_id
        with pytest.raises(PricingContextError):
            get_mark_price(
                symbol="BTC/USDT",
                data_engine=Mock(),
                cycle_id=456  # Wrong cycle_id
            )


class TestIntegrationScenarios:
    """Test integration scenarios with pricing context."""
    
    def test_full_cycle_simulation(self):
        """Test a full cycle simulation with pricing context."""
        # Start cycle 100
        context = set_pricing_context(100)
        
        # Simulate some pricing operations
        with patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot', return_value=None):
            # These should all record errors since no snapshot
            get_mark_price("BTC/USDT", Mock(), cycle_id=100)
            get_mark_price("ETH/USDT", Mock(), cycle_id=100)
            get_exit_value("BTC/USDT", "long", Mock(), cycle_id=100)
        
        # Check context stats
        stats = context.get_stats()
        assert stats["cycle_id"] == 100
        assert stats["error_count"] == 3
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0
        
        # Start new cycle 101
        new_context = set_pricing_context(101)
        
        # Old cycle operations should fail
        with pytest.raises(PricingContextError):
            get_mark_price("BTC/USDT", Mock(), cycle_id=100)
        
        # New cycle operations should work
        with patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot', return_value=None):
            get_mark_price("BTC/USDT", Mock(), cycle_id=101)
        
        assert new_context.error_count == 1
        assert context.error_count == 3  # Unchanged
    
    def test_error_logging_once_per_cycle(self):
        """Test that errors are logged only once per cycle."""
        context = set_pricing_context(200)
        
        # First error should be logged
        with patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot', return_value=None):
            assert context.should_log_error() is True
            get_mark_price("BTC/USDT", Mock(), cycle_id=200)
        
        # Subsequent errors in same cycle should not be logged
        with patch('src.crypto_mvp.core.utils.get_current_pricing_snapshot', return_value=None):
            assert context.should_log_error() is False
            get_mark_price("ETH/USDT", Mock(), cycle_id=200)
        
        # New cycle should allow logging again
        new_context = set_pricing_context(201)
        assert new_context.should_log_error() is True

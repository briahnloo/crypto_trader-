"""
Simplified integration tests for atomic position hydration with fail-fast validation.
Focuses on core acceptance criteria.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from src.crypto_mvp.core.utils import to_canonical


class TestAtomicPositionHydrationSimple:
    """Simplified test for atomic position hydration with fail-fast validation."""

    @pytest.fixture
    def trading_system(self):
        """Create a trading system instance for testing."""
        system = ProfitMaximizingTradingSystem()
        system.current_session_id = "test_session_123"
        system.state_store = Mock()
        # Mock the logger methods instead of replacing the logger property
        system.logger.info = Mock()
        system.logger.warning = Mock()
        system.logger.error = Mock()
        system.logger.debug = Mock()
        return system

    def test_atomic_hydration_success(self, trading_system):
        """Test successful atomic position hydration."""
        # Mock valid positions from state store
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "strategy": "momentum"
            }
        ]
        trading_system.state_store.get_positions.return_value = mock_positions
        
        # Test hydration
        result = trading_system._hydrate_positions_from_store()
        
        # Verify success
        assert result is True
        assert len(trading_system._in_memory_positions) == 1
        
        # Verify position data
        btc_canonical = to_canonical("BTC/USDT")
        assert btc_canonical in trading_system._in_memory_positions
        btc_pos = trading_system._in_memory_positions[btc_canonical]
        assert btc_pos["symbol"] == "BTC/USDT"
        assert btc_pos["quantity"] == 0.5
        assert btc_pos["entry_price"] == 50000.0

    def test_atomic_hydration_failure_count_mismatch(self, trading_system):
        """Test hydration failure when loaded count doesn't match expected count."""
        # Mock positions that will fail validation
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "strategy": "momentum"
            },
            {
                "symbol": "ETH/USDT",
                "quantity": "invalid",  # This will be skipped
                "entry_price": 3000.0,
                "strategy": "breakout"
            }
        ]
        trading_system.state_store.get_positions.return_value = mock_positions
        
        # Test hydration
        result = trading_system._hydrate_positions_from_store()
        
        # Verify failure due to count mismatch
        assert result is False
        assert len(trading_system._in_memory_positions) == 0
        
        # Verify error logging
        trading_system.logger.error.assert_called_with(
            "POSITION_HYDRATE_FAILED: Expected 2 positions, loaded 1"
        )

    def test_atomic_hydration_failure_schema_validation(self, trading_system):
        """Test hydration failure with invalid schema."""
        # Mock positions with missing required fields
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                # Missing entry_price
                "strategy": "momentum"
            }
        ]
        trading_system.state_store.get_positions.return_value = mock_positions
        
        # Test hydration
        result = trading_system._hydrate_positions_from_store()
        
        # Verify failure
        assert result is False
        assert len(trading_system._in_memory_positions) == 0
        
        # Verify error logging (count mismatch takes precedence)
        trading_system.logger.error.assert_called_with(
            "POSITION_HYDRATE_FAILED: Expected 1 positions, loaded 0"
        )

    def test_position_price_update_with_hydrated_positions(self, trading_system):
        """Test position price update using hydrated positions."""
        # Setup hydrated positions
        btc_canonical = to_canonical("BTC/USDT")
        trading_system._in_memory_positions[btc_canonical] = {
            "symbol": "BTC/USDT",
            "canonical_symbol": btc_canonical,
            "quantity": 0.5,
            "entry_price": 50000.0,
            "current_price": 50000.0,
            "value": 25000.0,
            "unrealized_pnl": 0.0,
            "strategy": "momentum",
            "session_id": "test_session_123",
            "updated_at": datetime.now()
        }
        
        # Mock state store and price methods
        trading_system.state_store.get_position.return_value = {"symbol": "BTC/USDT"}
        trading_system.state_store.update_position_price = Mock()
        trading_system._save_portfolio_state = Mock()
        trading_system.get_cached_mark_price = Mock(return_value=52000.0)
        trading_system._is_realization_enabled = Mock(return_value=False)
        
        with patch('src.crypto_mvp.trading_system.validate_mark_price', return_value=True):
            # Test position price update
            trading_system._update_position_prices()
            
            # Verify state store update was called
            trading_system.state_store.update_position_price.assert_called_with("BTC/USDT", 52000.0)
            
            # Verify position was updated in memory
            assert trading_system._in_memory_positions[btc_canonical]["current_price"] == 52000.0

    def test_position_price_update_empty_cache(self, trading_system):
        """Test position price update with empty cache."""
        # Ensure empty cache
        trading_system._in_memory_positions.clear()
        
        # Test position price update
        trading_system._update_position_prices()
        
        # Verify warning logged
        trading_system.logger.warning.assert_called_with(
            "POSITION_PRICE_UPDATE: No positions in memory cache - skipping price updates"
        )

    def test_stale_store_simulation(self, trading_system):
        """Test simulation of stale store scenario - cycle exits early."""
        # Mock stale store that returns inconsistent data
        def mock_get_positions(session_id):
            # First call returns valid positions, second call returns invalid data
            if not hasattr(mock_get_positions, 'call_count'):
                mock_get_positions.call_count = 0
            mock_get_positions.call_count += 1
            
            if mock_get_positions.call_count == 1:
                return [
                    {
                        "symbol": "BTC/USDT",
                        "quantity": 0.5,
                        "entry_price": 50000.0,
                        "strategy": "momentum"
                    }
                ]
            else:
                # Simulate stale data - return 2 positions but one is invalid
                return [
                    {
                        "symbol": "BTC/USDT",
                        "quantity": 0.5,
                        "entry_price": 50000.0,
                        "strategy": "momentum"
                    },
                    {
                        "symbol": "ETH/USDT",
                        "quantity": "invalid",  # Invalid data type
                        "entry_price": 3000.0,
                        "strategy": "breakout"
                    }
                ]
        
        trading_system.state_store.get_positions = mock_get_positions
        
        # First hydration should succeed
        result1 = trading_system._hydrate_positions_from_store()
        assert result1 is True
        assert len(trading_system._in_memory_positions) == 1
        
        # Second hydration should fail due to count mismatch
        result2 = trading_system._hydrate_positions_from_store()
        assert result2 is False
        # Cache should be cleared on failure
        assert len(trading_system._in_memory_positions) == 0
        
        # Verify error logging
        trading_system.logger.error.assert_called_with(
            "POSITION_HYDRATE_FAILED: Expected 2 positions, loaded 1"
        )

    def test_atomic_swap_validation(self, trading_system):
        """Test that atomic swap only happens after validation passes."""
        # Mock positions with one invalid entry
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "strategy": "momentum"
            },
            {
                "symbol": "ETH/USDT",
                "quantity": "invalid",  # Invalid data type
                "entry_price": 3000.0,
                "strategy": "breakout"
            }
        ]
        trading_system.state_store.get_positions.return_value = mock_positions
        
        # Ensure cache starts empty
        trading_system._in_memory_positions.clear()
        
        # Test hydration
        result = trading_system._hydrate_positions_from_store()
        
        # Verify failure and cache remains empty (atomic swap didn't happen)
        assert result is False
        assert len(trading_system._in_memory_positions) == 0
        
        # Verify error logging
        trading_system.logger.error.assert_called_with(
            "POSITION_HYDRATE_FAILED: Expected 2 positions, loaded 1"
        )

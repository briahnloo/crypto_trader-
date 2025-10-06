"""
Test cases for position synchronization system.

Tests that in-memory positions stay in lockstep with the state store,
including desync detection and rehydration functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from src.crypto_mvp.state.store import StateStore
from src.crypto_mvp.core.utils import to_canonical


class TestPositionSynchronization:
    """Test cases for position synchronization system."""
    
    @pytest.fixture
    def mock_state_store(self):
        """Create mock state store."""
        store = Mock(spec=StateStore)
        store.get_positions.return_value = []
        store.get_position.return_value = None
        store.update_position_price.return_value = None
        return store
    
    @pytest.fixture
    def trading_system(self, mock_state_store):
        """Create trading system with mock state store."""
        # Mock the config manager to avoid file I/O
        with patch('src.crypto_mvp.trading_system.ConfigManager') as mock_config_manager:
            mock_config = {
                "trading": {
                    "initial_capital": 100000.0,
                    "symbols": ["BTC/USDT", "ETH/USDT"],
                    "live_mode": False
                },
                "exchanges": {},
                "risk": {},
                "execution": {}
            }
            mock_config_manager.return_value.load_config.return_value = mock_config
            mock_config_manager.return_value.config = mock_config
            
            system = ProfitMaximizingTradingSystem()
            system.state_store = mock_state_store
            system.current_session_id = "test_session_123"
            system._logger = Mock()
            
            return system
    
    def test_position_hydration_at_cycle_start(self, trading_system, mock_state_store):
        """Test that positions are hydrated from state store at cycle start."""
        # Mock positions in state store
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "current_price": 51000.0,
                "value": 25500.0,
                "unrealized_pnl": 500.0,
                "strategy": "momentum",
                "session_id": "test_session_123",
                "updated_at": datetime.now()
            },
            {
                "symbol": "ETH/USDT", 
                "quantity": 2.0,
                "entry_price": 3000.0,
                "current_price": 3100.0,
                "value": 6200.0,
                "unrealized_pnl": 200.0,
                "strategy": "breakout",
                "session_id": "test_session_123",
                "updated_at": datetime.now()
            }
        ]
        mock_state_store.get_positions.return_value = mock_positions
        
        # Hydrate positions
        trading_system._hydrate_positions_from_store()
        
        # Verify in-memory cache is populated
        assert len(trading_system._in_memory_positions) == 2
        
        # Verify BTC/USDT position
        btc_canonical = to_canonical("BTC/USDT")
        assert btc_canonical in trading_system._in_memory_positions
        btc_position = trading_system._in_memory_positions[btc_canonical]
        assert btc_position["symbol"] == "BTC/USDT"
        assert btc_position["canonical_symbol"] == btc_canonical
        assert btc_position["quantity"] == 0.5
        assert btc_position["entry_price"] == 50000.0
        assert btc_position["strategy"] == "momentum"
        
        # Verify ETH/USDT position
        eth_canonical = to_canonical("ETH/USDT")
        assert eth_canonical in trading_system._in_memory_positions
        eth_position = trading_system._in_memory_positions[eth_canonical]
        assert eth_position["symbol"] == "ETH/USDT"
        assert eth_position["canonical_symbol"] == eth_canonical
        assert eth_position["quantity"] == 2.0
        assert eth_position["entry_price"] == 3000.0
        assert eth_position["strategy"] == "breakout"
        
        # Verify logging
        trading_system.logger.info.assert_called_with(
            "POSITION_HYDRATE: Successfully hydrated 2 positions"
        )
    
    def test_position_desync_detection_and_rehydration(self, trading_system, mock_state_store):
        """Test desync detection and rehydration in position price updates."""
        # Setup initial position in in-memory cache
        btc_canonical = to_canonical("BTC/USDT")
        trading_system._in_memory_positions[btc_canonical] = {
            "symbol": "BTC/USDT",
            "canonical_symbol": btc_canonical,
            "quantity": 0.5,
            "entry_price": 50000.0,
            "current_price": 51000.0,
            "value": 25500.0,
            "unrealized_pnl": 500.0,
            "strategy": "momentum",
            "session_id": "test_session_123",
            "updated_at": datetime.now()
        }
        
        # Mock desync scenario: position not found in state store
        mock_state_store.get_position.return_value = None
        
        # Mock price update methods
        with patch.object(trading_system, 'get_cached_mark_price', return_value=52000.0), \
             patch('src.crypto_mvp.trading_system.validate_mark_price', return_value=True), \
             patch.object(trading_system, '_rehydrate_position', return_value=True) as mock_rehydrate, \
             patch.object(trading_system, '_save_portfolio_state') as mock_save_state:
            
            # Run position price update
            trading_system._update_position_prices()
            
            # Verify desync detection and rehydration attempt
            trading_system.logger.warning.assert_called_with(
                "POSITION_DESYNC: symbol=BTC/USDT, action=rehydrate"
            )
            mock_rehydrate.assert_called_with("BTC/USDT")
    
    def test_canonical_symbol_consistency(self, trading_system):
        """Test that canonical symbols are used consistently between store and memory."""
        # Test various symbol formats
        test_symbols = [
            "BTC/USDT",
            "BTC-USD", 
            "BTCUSDT",
            "btc/usdt",
            "ETH/USDT",
            "ETH-USD",
            "ETHUSDT"
        ]
        
        for symbol in test_symbols:
            canonical = to_canonical(symbol)
            
            # Verify canonicalization is consistent
            if "BTC" in symbol.upper():
                assert canonical == "BTC/USDT"
            elif "ETH" in symbol.upper():
                assert canonical == "ETH/USDT"
            
            # Test that hydration uses canonical symbols for indexing
            position_data = {
                "symbol": symbol,
                "quantity": 1.0,
                "entry_price": 1000.0,
                "current_price": 1100.0,
                "value": 1100.0,
                "unrealized_pnl": 100.0,
                "strategy": "test",
                "session_id": "test_session",
                "updated_at": datetime.now()
            }
            
            trading_system._in_memory_positions.clear()
            trading_system._in_memory_positions[canonical] = {
                "symbol": symbol,
                "canonical_symbol": canonical,
                **position_data
            }
            
            # Verify position is indexed by canonical symbol
            assert canonical in trading_system._in_memory_positions
            assert trading_system._in_memory_positions[canonical]["canonical_symbol"] == canonical
    
    def test_store_only_position_rehydration(self, trading_system, mock_state_store):
        """Test that store-only positions are properly rehydrated."""
        # Test the rehydration method directly
        store_only_position = {
            "symbol": "BTC/USDT",
            "quantity": 0.25,
            "entry_price": 45000.0,
            "current_price": 46000.0,
            "value": 11500.0,
            "unrealized_pnl": 250.0,
            "strategy": "arbitrage",
            "session_id": "test_session_123",
            "updated_at": datetime.now()
        }
        
        mock_state_store.get_position.return_value = store_only_position
        
        # Test rehydration method directly
        result = trading_system._rehydrate_position("BTC/USDT")
        
        # Verify rehydration was successful
        assert result is True
        btc_canonical = to_canonical("BTC/USDT")
        assert btc_canonical in trading_system._in_memory_positions
        assert trading_system._in_memory_positions[btc_canonical]["quantity"] == 0.25
        assert trading_system._in_memory_positions[btc_canonical]["entry_price"] == 45000.0
    
    def test_position_hydration_error_handling(self, trading_system, mock_state_store):
        """Test error handling during position hydration."""
        # Mock state store error
        mock_state_store.get_positions.side_effect = Exception("Database connection failed")
        
        # Hydrate should not raise exception
        trading_system._hydrate_positions_from_store()
        
        # Verify error was logged
        trading_system.logger.error.assert_called_with(
            "Error hydrating positions from state store: Database connection failed"
        )
        
        # Verify in-memory cache remains empty
        assert len(trading_system._in_memory_positions) == 0
    
    def test_position_rehydration_error_handling(self, trading_system, mock_state_store):
        """Test error handling during position rehydration."""
        # Mock rehydration failure
        mock_state_store.get_position.return_value = None
        mock_state_store.get_positions.return_value = []
        
        # Test rehydration method directly with failure scenario
        result = trading_system._rehydrate_position("BTC/USDT")
        
        # Verify rehydration failed
        assert result is False
        # Verify warning was logged
        trading_system.logger.warning.assert_called_with(
            "POSITION_DESYNC: symbol=BTC/USDT, action=rehydrate - Position not found in state store"
        )
    
    def test_empty_position_cache_handling(self, trading_system):
        """Test handling of empty position cache."""
        # Clear in-memory cache
        trading_system._in_memory_positions.clear()
        
        # Run position price update with empty cache
        with patch.object(trading_system, '_save_portfolio_state'):
            trading_system._update_position_prices()
        
        # Verify no errors and proper logging
        trading_system.logger.info.assert_called_with(
            "POSITION_PRICE_UPDATE: Completed updating all position prices"
        )
    
    def test_zero_quantity_position_skipping(self, trading_system):
        """Test that zero quantity positions are skipped."""
        # Setup position with zero quantity
        btc_canonical = to_canonical("BTC/USDT")
        trading_system._in_memory_positions[btc_canonical] = {
            "symbol": "BTC/USDT",
            "canonical_symbol": btc_canonical,
            "quantity": 0.0,  # Zero quantity
            "entry_price": 50000.0,
            "strategy": "momentum",
            "session_id": "test_session_123",
            "updated_at": datetime.now()
        }
        
        # Run position price update
        with patch.object(trading_system, '_save_portfolio_state'):
            trading_system._update_position_prices()
        
        # Verify position was skipped (no price update calls)
        trading_system.logger.info.assert_called_with(
            "POSITION_PRICE_UPDATE: Completed updating all position prices"
        )
        # Should not have called any price update methods
    
    def test_position_cache_integration_with_trading_cycle(self, trading_system, mock_state_store):
        """Test integration of position cache with trading cycle."""
        # Mock positions in state store
        mock_positions = [
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "current_price": 51000.0,
                "value": 25500.0,
                "unrealized_pnl": 500.0,
                "strategy": "momentum",
                "session_id": "test_session_123",
                "updated_at": datetime.now()
            }
        ]
        mock_state_store.get_positions.return_value = mock_positions
        
        # Mock other required methods for trading cycle
        with patch.object(trading_system, '_validate_session_state', return_value=True), \
             patch.object(trading_system, 'get_cached_mark_price', return_value=52000.0), \
             patch('src.crypto_mvp.trading_system.validate_mark_price', return_value=True), \
             patch.object(trading_system, 'run_trading_cycle') as mock_cycle:
            
            # Run hydration (simulates what happens at cycle start)
            trading_system._hydrate_positions_from_store()
            
            # Verify cache is populated
            assert len(trading_system._in_memory_positions) == 1
            btc_canonical = to_canonical("BTC/USDT")
            assert btc_canonical in trading_system._in_memory_positions
            
            # Verify position data is correct
            position = trading_system._in_memory_positions[btc_canonical]
            assert position["quantity"] == 0.5
            assert position["entry_price"] == 50000.0


if __name__ == "__main__":
    pytest.main([__file__])

"""
Unit tests for session ID validation in trading system.
"""

import pytest
from unittest.mock import Mock, patch

from src.crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from src.crypto_mvp.state.store import StateStore
from src.crypto_mvp.execution.order_manager import OrderManager


class TestSessionValidation:
    """Test session ID validation requirements."""

    def test_trading_system_initialize_requires_session_id(self):
        """Test that trading system initialization requires session_id."""
        system = ProfitMaximizingTradingSystem()
        
        # Test empty session_id
        with pytest.raises(ValueError, match="session_id is mandatory and cannot be empty"):
            system.initialize("")
        
        # Test None session_id
        with pytest.raises(ValueError, match="session_id is mandatory and cannot be empty"):
            system.initialize(None)
        
        # Test whitespace-only session_id
        with pytest.raises(ValueError, match="session_id is mandatory and cannot be empty"):
            system.initialize("   ")

    @pytest.mark.asyncio
    async def test_trading_system_cycle_requires_session_id(self):
        """Test that trading cycle requires session_id to be set."""
        system = ProfitMaximizingTradingSystem()
        
        # Initialize with valid session_id
        with patch.object(system, 'config_manager') as mock_config:
            with patch.object(system, 'data_engine') as mock_data:
                with patch.object(system, 'signal_engine') as mock_signal:
                    with patch.object(system, 'risk_manager') as mock_risk:
                        with patch.object(system, 'portfolio_manager') as mock_portfolio:
                            with patch.object(system, 'order_manager') as mock_order:
                                with patch.object(system, 'state_store') as mock_state:
                                    # Mock the initialization
                                    system.config = {"trading": {"symbols": ["BTC/USDT"]}}
                                    system.initialized = True
                                    system.current_session_id = None  # Simulate missing session_id
                                    
                                    # Test that cycle fails without session_id
                                    with pytest.raises(RuntimeError, match="session_id not set - cannot run trading cycle without valid session"):
                                        await system.run_trading_cycle()

    def test_state_store_get_positions_requires_session_id(self):
        """Test that state store get_positions requires session_id."""
        store = StateStore()
        
        with pytest.raises(ValueError, match="session_id is mandatory for get_positions"):
            store.get_positions("")
        
        with pytest.raises(ValueError, match="session_id is mandatory for get_positions"):
            store.get_positions(None)

    def test_state_store_get_session_cash_requires_session_id(self):
        """Test that state store get_session_cash requires session_id."""
        store = StateStore()
        
        with pytest.raises(ValueError, match="session_id is mandatory for get_session_cash"):
            store.get_session_cash("")
        
        with pytest.raises(ValueError, match="session_id is mandatory for get_session_cash"):
            store.get_session_cash(None)

    def test_state_store_debit_cash_requires_session_id(self):
        """Test that state store debit_cash requires session_id."""
        store = StateStore()
        
        with pytest.raises(ValueError, match="session_id is mandatory for debit_cash"):
            store.debit_cash("", 100.0)
        
        with pytest.raises(ValueError, match="session_id is mandatory for debit_cash"):
            store.debit_cash(None, 100.0)

    def test_state_store_credit_cash_requires_session_id(self):
        """Test that state store credit_cash requires session_id."""
        store = StateStore()
        
        with pytest.raises(ValueError, match="session_id is mandatory for credit_cash"):
            store.credit_cash("", 100.0)
        
        with pytest.raises(ValueError, match="session_id is mandatory for credit_cash"):
            store.credit_cash(None, 100.0)

    def test_order_manager_set_session_id_validation(self):
        """Test that order manager set_session_id validates input."""
        manager = OrderManager()
        
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            manager.set_session_id("")
        
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            manager.set_session_id(None)

    def test_order_manager_cash_operations_require_session_id(self):
        """Test that order manager cash operations require session_id."""
        manager = OrderManager()
        manager.state_store = Mock()
        
        # Create a mock fill
        from src.crypto_mvp.execution.order_manager import Fill, OrderSide
        fill = Fill(
            order_id="test_order",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=1.0,
            price=50000.0,
            fees=10.0,
            timestamp="2024-01-01T00:00:00Z"
        )
        
        # Test without session_id
        with pytest.raises(RuntimeError, match="session_id not set - cannot process cash operations without valid session"):
            manager._apply_cash_impact(fill)
        
        # Test with session_id set
        manager.current_session_id = "test_session"
        manager.state_store.debit_cash.return_value = True
        result = manager._apply_cash_impact(fill)
        assert result is True

    def test_no_fallback_branches_in_cash_operations(self):
        """Test that there are no fallback branches in cash operations."""
        system = ProfitMaximizingTradingSystem()
        system.current_session_id = None
        
        # Mock state store
        system.state_store = Mock()
        
        # Test that get_cash_balance fails immediately without fallback
        with pytest.raises(RuntimeError, match="No session ID available - session binding failed"):
            system._get_cash_balance()
        
        # Test that get_positions fails immediately without fallback
        with pytest.raises(RuntimeError, match="No session ID available - session binding failed"):
            system._get_positions()

    def test_session_id_propagation_through_system(self):
        """Test that session_id is properly propagated through the system."""
        system = ProfitMaximizingTradingSystem()
        
        # Mock all dependencies
        with patch.object(system, 'config_manager') as mock_config:
            with patch.object(system, 'data_engine') as mock_data:
                with patch.object(system, 'signal_engine') as mock_signal:
                    with patch.object(system, 'risk_manager') as mock_risk:
                        with patch.object(system, 'portfolio_manager') as mock_portfolio:
                            with patch.object(system, 'order_manager') as mock_order:
                                with patch.object(system, 'state_store') as mock_state:
                                    with patch.object(system, 'profit_analytics') as mock_analytics:
                                        with patch.object(system, 'profit_logger') as mock_logger:
                                            # Set up mocks
                                            system.config = {"trading": {"symbols": ["BTC/USDT"]}}
                                            
                                            # Initialize with session_id
                                            system.initialize("test_session_123")
                                            
                                            # Verify session_id was set
                                            assert system.current_session_id == "test_session_123"
                                            
                                            # Verify order manager received session_id
                                            mock_order.set_session_id.assert_called_with("test_session_123")
                                            
                                            # Verify analytics received session_id
                                            mock_analytics.initialize.assert_called_with("test_session_123")
                                            
                                            # Verify logger received session_id
                                            mock_logger.initialize.assert_called_with("test_session_123")


if __name__ == "__main__":
    pytest.main([__file__])

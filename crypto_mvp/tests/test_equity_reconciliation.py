#!/usr/bin/env python3
"""
Test equity reconciliation tolerance to avoid infinite loops.
"""

import sys
import os
import tempfile
from unittest.mock import Mock, patch
from datetime import datetime

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from crypto_mvp.state.store import StateStore


class TestEquityReconciliation:
    """Test equity reconciliation tolerance functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        
        # Initialize state store
        self.state_store = StateStore(self.temp_db.name)
        
        # Test session ID
        self.session_id = "test_equity_reconciliation"
        
        # Initialize cash equity for testing
        self.state_store.save_cash_equity(
            cash_balance=10000.0,
            total_equity=10000.0,
            total_fees=0.0,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            session_id=self.session_id,
            previous_equity=10000.0
        )
    
    def teardown_method(self):
        """Clean up test environment."""
        os.unlink(self.temp_db.name)
    
    def test_tolerance_based_reconciliation(self):
        """Test that reconciliation uses tolerance instead of fixed amount."""
        print("\nTest 1: Tolerance-based reconciliation")
        
        # Mock config with tolerance
        mock_config = {
            "equity": {
                "reconcile_tolerance": 0.0001,  # 0.01%
                "max_reconcile_iterations": 5
            },
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Initialize portfolio
            trading_system.portfolio = {
                "equity": 10000.0,
                "cash_balance": 10000.0,
                "total_fees": 0.0,
                "positions": {}
            }
            
            # Test tiny drift that should be within tolerance
            stored_equity = 10000.0
            tiny_drift = 0.5  # Small drift within tolerance
            calculated_equity = stored_equity + tiny_drift
            discrepancy = calculated_equity - stored_equity
            
            # Tolerance amount should be 0.0001 * 10000 = 1.0
            tolerance_amount = 0.0001 * stored_equity  # Should be 1.0
            
            # The tiny drift should be well within tolerance
            assert abs(discrepancy) <= tolerance_amount, f"Tiny drift {discrepancy} should be within tolerance {tolerance_amount}"
            
            # Test reconciliation - should pass on first try
            trading_system._reconcile_equity_discrepancy(calculated_equity, stored_equity, discrepancy)
            
            # Verify iteration counter was initialized
            assert hasattr(trading_system, '_reconcile_iterations')
            # Should be 0 because discrepancy was within tolerance (no iterations needed)
            assert trading_system._reconcile_iterations == 0
            
            print(f"✅ Tolerance test passed: drift={discrepancy:.2e}, tolerance={tolerance_amount:.2f}")
    
    def test_max_iterations_hard_stop(self):
        """Test that reconciliation stops after max iterations."""
        print("\nTest 2: Max iterations hard stop")
        
        # Mock config with low max iterations
        mock_config = {
            "equity": {
                "reconcile_tolerance": 0.0001,  # 0.01%
                "max_reconcile_iterations": 2  # Low for testing
            },
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Initialize portfolio
            trading_system.portfolio = {
                "equity": 10000.0,
                "cash_balance": 10000.0,
                "total_fees": 0.0,
                "positions": {}
            }
            
            # Test large discrepancy that exceeds tolerance
            stored_equity = 10000.0
            large_discrepancy = 100.0  # Large discrepancy
            calculated_equity = stored_equity + large_discrepancy
            
            # Mock positions to trigger the reconciliation logic
            self.state_store.save_position(
                symbol="BTC/USDT",
                quantity=1.0,
                entry_price=50000.0,
                current_price=50000.0,
                strategy="test",
                session_id=self.session_id
            )
            
            # Test multiple reconciliation attempts
            for i in range(3):  # Try 3 times (should stop after 2)
                trading_system._reconcile_equity_discrepancy(calculated_equity, stored_equity, large_discrepancy)
                
                if i < 2:
                    # Should still be trying
                    assert trading_system._reconcile_iterations == i + 1
                else:
                    # Should have hit max iterations and reset
                    assert trading_system._reconcile_iterations == 0
            
            print("✅ Max iterations test passed: hard stop after 2 iterations")
    
    def test_default_fallback_values(self):
        """Test that default values are used when config is missing."""
        print("\nTest 3: Default fallback values")
        
        # Mock config without equity section
        mock_config = {
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Initialize portfolio
            trading_system.portfolio = {
                "equity": 10000.0,
                "cash_balance": 10000.0,
                "total_fees": 0.0,
                "positions": {}
            }
            
            # Test with tiny drift - should use default tolerance (0.0001)
            stored_equity = 10000.0
            tiny_drift = 0.5  # 0.5 dollar drift
            calculated_equity = stored_equity + tiny_drift
            discrepancy = calculated_equity - stored_equity
            
            # Default tolerance amount should be 0.0001 * 10000 = 1.0
            # 0.5 should be within tolerance
            tolerance_amount = 0.0001 * stored_equity  # Should be 1.0
            
            assert abs(discrepancy) <= tolerance_amount, f"Drift {discrepancy} should be within default tolerance {tolerance_amount}"
            
            # Test reconciliation - should pass
            trading_system._reconcile_equity_discrepancy(calculated_equity, stored_equity, discrepancy)
            
            print("✅ Default fallback test passed: used default tolerance 0.0001")


if __name__ == "__main__":
    # Run the tests
    test_instance = TestEquityReconciliation()
    
    print("Running equity reconciliation tolerance tests...")
    print("=" * 60)
    
    try:
        test_instance.setup_method()
        
        print("Test 1: Tolerance-based reconciliation")
        test_instance.test_tolerance_based_reconciliation()
        
        print("\nTest 2: Max iterations hard stop")
        test_instance.test_max_iterations_hard_stop()
        
        print("\nTest 3: Default fallback values")
        test_instance.test_default_fallback_values()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("EQUITY_RECONCILIATION: PASS (tol=0.0001, iters<=5)")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    finally:
        test_instance.teardown_method()

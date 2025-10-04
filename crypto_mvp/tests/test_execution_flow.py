#!/usr/bin/env python3
"""
Test execution flow for crypto trading bot.

This module tests the execution engine with hardened pricing,
risk-based position sizing, and proper rejection handling.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from portfolio.ledger import create_empty_ledger, Fill
from portfolio.snapshot import snapshot_from_ledger
from execution.engine import ExecutionEngine
from src.crypto_mvp.ui_panels import trades_this_cycle, positions_count, validate_counters_consistency


class TestExecutionFlow:
    """Test execution flow with various scenarios."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.initial_cash = 10000.0
        self.ledger = create_empty_ledger(self.initial_cash)
        
        # Mock mark price callback
        self.mock_mark_price = Mock(return_value=50000.0)
        self.execution_engine = ExecutionEngine(self.mock_mark_price)
        
        # Mock pricing functions at the execution engine level
        self.patcher_get_executable_price = patch('execution.engine.get_executable_price')
        self.patcher_get_atr = patch('execution.engine.get_atr')
        self.patcher_sl_tp_defaults = patch('execution.engine.sl_tp_defaults')
        self.patcher_size_for_risk = patch('execution.engine.size_for_risk')
        
        self.mock_get_executable_price = self.patcher_get_executable_price.start()
        self.mock_get_atr = self.patcher_get_atr.start()
        self.mock_sl_tp_defaults = self.patcher_sl_tp_defaults.start()
        self.mock_size_for_risk = self.patcher_size_for_risk.start()
        
        # Default mock returns
        self.mock_get_executable_price.return_value = 50000.0
        self.mock_get_atr.return_value = 1500.0
        self.mock_sl_tp_defaults.return_value = (47750.0, 54230.0, {"mode": "atr", "rr": 1.88, "risk": 2250.0})
        self.mock_size_for_risk.return_value = 0.002
        
    def teardown_method(self):
        """Clean up test fixtures."""
        self.patcher_get_executable_price.stop()
        self.patcher_get_atr.stop()
        self.patcher_sl_tp_defaults.stop()
        self.patcher_size_for_risk.stop()
    
    def test_trade_with_none_price_rejected(self):
        """Test that trade with None price is rejected; no fills appended; counters stay zero."""
        # Arrange
        self.mock_get_executable_price.return_value = None
        
        # Create snapshot for equity calculation
        marks = {"BTC/USDT": 50000.0}
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        # Act
        updated_ledger, success = self.execution_engine.execute_trade(
            ledger=self.ledger,
            symbol="BTC/USDT",
            side="BUY",
            strategy="test",
            snapshot=snapshot
        )
        
        # Assert
        assert not success, "Trade should be rejected for None price"
        assert updated_ledger == self.ledger, "Ledger should be unchanged"
        
        # Check no fills were committed
        committed_fills = self.execution_engine.get_committed_fills()
        assert len(committed_fills) == 0, "No fills should be committed"
        
        # Check counters stay zero
        assert trades_this_cycle(committed_fills) == 0, "Trade count should be zero"
        assert positions_count(snapshot) == 0, "Position count should be zero"
        
        # Verify pricing function was called
        self.mock_get_executable_price.assert_called_once_with("BTC/USDT")
    
    def test_trade_with_zero_price_rejected(self):
        """Test that trade with zero price is rejected."""
        # Arrange
        self.mock_get_executable_price.return_value = 0.0
        
        marks = {"BTC/USDT": 50000.0}
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        # Act
        updated_ledger, success = self.execution_engine.execute_trade(
            ledger=self.ledger,
            symbol="BTC/USDT",
            side="BUY",
            strategy="test",
            snapshot=snapshot
        )
        
        # Assert
        assert not success, "Trade should be rejected for zero price"
        assert updated_ledger == self.ledger, "Ledger should be unchanged"
        
        committed_fills = self.execution_engine.get_committed_fills()
        assert len(committed_fills) == 0, "No fills should be committed"
    
    def test_trade_with_zero_quantity_rejected(self):
        """Test that trade with zero quantity is rejected."""
        # Arrange
        self.mock_size_for_risk.return_value = 0.0  # Zero quantity
        
        marks = {"BTC/USDT": 50000.0}
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        # Act
        updated_ledger, success = self.execution_engine.execute_trade(
            ledger=self.ledger,
            symbol="BTC/USDT",
            side="BUY",
            strategy="test",
            snapshot=snapshot
        )
        
        # Assert
        assert not success, "Trade should be rejected for zero quantity"
        assert updated_ledger == self.ledger, "Ledger should be unchanged"
        
        committed_fills = self.execution_engine.get_committed_fills()
        assert len(committed_fills) == 0, "No fills should be committed"
    
    def test_valid_buy_changes_cash_leaves_equity_unchanged(self):
        """Test that valid BUY changes cash, leaves equity ≈ same (±fees), positions_count==1."""
        # Arrange
        entry_price = 50000.0
        quantity = 0.002
        fees = 2.50
        
        self.mock_get_executable_price.return_value = entry_price
        self.mock_size_for_risk.return_value = quantity
        
        marks = {"BTC/USDT": entry_price}
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        # Act
        updated_ledger, success = self.execution_engine.execute_trade(
            ledger=self.ledger,
            symbol="BTC/USDT",
            side="BUY",
            strategy="test",
            fees=fees,
            snapshot=snapshot
        )
        
        # Assert
        assert success, "Valid trade should succeed"
        
        # Check cash changed correctly
        expected_cash_change = -(quantity * entry_price + fees)  # BUY: -notional - fees
        expected_cash = self.initial_cash + expected_cash_change
        assert abs(updated_ledger.cash - expected_cash) < 1e-6, f"Cash should change by {expected_cash_change}"
        
        # Check equity approximately unchanged (only fees affect it)
        expected_equity_change = -fees
        expected_equity = self.initial_cash + expected_equity_change
        assert abs(updated_ledger.equity - expected_equity) < 1e-6, f"Equity should change by {expected_equity_change}"
        
        # Check position was created
        assert "BTC/USDT" in updated_ledger.positions, "BTC/USDT position should be created"
        position = updated_ledger.positions["BTC/USDT"]
        assert abs(position.qty - quantity) < 1e-8, f"Position quantity should be {quantity}"
        assert abs(position.avg_cost - entry_price) < 1e-8, f"Average cost should be {entry_price}"
        
        # Check counters
        committed_fills = self.execution_engine.get_committed_fills()
        assert trades_this_cycle(committed_fills) == 1, "Trade count should be 1"
        
        # Create new snapshot to check position count
        new_snapshot = snapshot_from_ledger(updated_ledger, marks)
        assert positions_count(new_snapshot) == 1, "Position count should be 1"
        
        # Validate counter consistency
        assert validate_counters_consistency(new_snapshot, committed_fills, updated_ledger), "Counters should be consistent"
    
    def test_multiple_trades_accumulate_correctly(self):
        """Test that multiple trades accumulate correctly in counters."""
        # Arrange
        entry_price = 50000.0
        quantity = 0.001
        fees = 1.25
        
        # Ensure mocks return valid values for all calls
        self.mock_get_executable_price.return_value = entry_price
        self.mock_size_for_risk.return_value = quantity
        self.mock_sl_tp_defaults.return_value = (47750.0, 54230.0, {"mode": "atr", "rr": 1.88, "risk": 2250.0})
        
        marks = {"BTC/USDT": entry_price}
        
        # Act - Execute multiple trades
        current_ledger = self.ledger
        for i in range(3):
            # Reset mocks before each trade to ensure they return valid values
            self.mock_get_executable_price.return_value = entry_price
            self.mock_size_for_risk.return_value = quantity
            self.mock_sl_tp_defaults.return_value = (47750.0, 54230.0, {"mode": "atr", "rr": 1.88, "risk": 2250.0})
            
            snapshot = snapshot_from_ledger(current_ledger, marks)
            current_ledger, success = self.execution_engine.execute_trade(
                ledger=current_ledger,
                symbol="BTC/USDT",
                side="BUY",
                strategy="test",
                fees=fees,
                snapshot=snapshot
            )
            assert success, f"Trade {i+1} should succeed"
        
        # Assert
        committed_fills = self.execution_engine.get_committed_fills()
        assert trades_this_cycle(committed_fills) == 3, "Should have 3 trades"
        assert len(current_ledger.fills) == 3, "Ledger should have 3 fills"
        
        # Check position accumulated correctly
        position = current_ledger.positions["BTC/USDT"]
        expected_quantity = quantity * 3
        assert abs(position.qty - expected_quantity) < 1e-8, f"Position should accumulate to {expected_quantity}"
        
        # Check cash decreased by total cost
        expected_total_cost = expected_quantity * entry_price + fees * 3
        expected_cash = self.initial_cash - expected_total_cost
        assert abs(current_ledger.cash - expected_cash) < 1e-6, f"Cash should decrease by {expected_total_cost}"
    
    def test_apply_fill_invariant_violation_rolls_back(self):
        """Test that apply_fill invariant violation rolls back changes."""
        # Arrange - Mock apply_fill to raise an exception
        with patch('execution.engine.apply_fill') as mock_apply_fill:
            mock_apply_fill.side_effect = ValueError("Invariant violation")
            
            marks = {"BTC/USDT": 50000.0}
            snapshot = snapshot_from_ledger(self.ledger, marks)
            
            # Act
            updated_ledger, success = self.execution_engine.execute_trade(
                ledger=self.ledger,
                symbol="BTC/USDT",
                side="BUY",
                strategy="test",
                snapshot=snapshot
            )
            
            # Assert
            assert not success, "Trade should fail due to invariant violation"
            assert updated_ledger == self.ledger, "Ledger should be unchanged (rolled back)"
            
            committed_fills = self.execution_engine.get_committed_fills()
            assert len(committed_fills) == 0, "No fills should be committed"
    
    def test_execution_engine_reset_cycle(self):
        """Test that execution engine reset_cycle clears committed fills."""
        # Arrange - Execute a trade first
        marks = {"BTC/USDT": 50000.0}
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        updated_ledger, success = self.execution_engine.execute_trade(
            ledger=self.ledger,
            symbol="BTC/USDT",
            side="BUY",
            strategy="test",
            snapshot=snapshot
        )
        assert success, "First trade should succeed"
        
        # Act - Reset cycle
        self.execution_engine.reset_cycle()
        
        # Assert
        committed_fills = self.execution_engine.get_committed_fills()
        assert len(committed_fills) == 0, "Committed fills should be cleared after reset"
        
        # But ledger should still have the fills
        assert len(updated_ledger.fills) == 1, "Ledger should still have fills"


if __name__ == "__main__":
    # Run tests
    test_instance = TestExecutionFlow()
    
    print("Running execution flow tests...")
    
    test_instance.setup_method()
    
    try:
        test_instance.test_trade_with_none_price_rejected()
        print("✓ Test 1 PASSED: Trade with None price rejected")
        
        test_instance.test_trade_with_zero_price_rejected()
        print("✓ Test 2 PASSED: Trade with zero price rejected")
        
        test_instance.test_trade_with_zero_quantity_rejected()
        print("✓ Test 3 PASSED: Trade with zero quantity rejected")
        
        test_instance.test_valid_buy_changes_cash_leaves_equity_unchanged()
        print("✓ Test 4 PASSED: Valid BUY changes cash correctly")
        
        test_instance.test_multiple_trades_accumulate_correctly()
        print("✓ Test 5 PASSED: Multiple trades accumulate correctly")
        
        test_instance.test_apply_fill_invariant_violation_rolls_back()
        print("✓ Test 6 PASSED: Invariant violation rolls back")
        
        test_instance.test_execution_engine_reset_cycle()
        print("✓ Test 7 PASSED: Execution engine reset cycle works")
        
        print("\n🎉 All execution flow tests passed!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        test_instance.teardown_method()

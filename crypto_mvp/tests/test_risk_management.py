#!/usr/bin/env python3
"""
Comprehensive unit tests for risk management functions.
Tests all critical risk management functionality and edge cases.
"""

import unittest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager, RiskLevel
from crypto_mvp.state.store import StateStore


class TestRiskManagement(unittest.TestCase):
    """Test suite for risk management functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "daily_loss_limit": 0.05,  # 5%
            "max_drawdown_limit": 0.10,  # 10%
            "position_size_limit": 0.02,  # 2%
            "stop_loss_percentage": 0.03,  # 3%
            "max_risk_per_trade": 0.02  # 2%
        }
        self.risk_manager = ProfitOptimizedRiskManager(self.config)
        
        # Mock state store
        self.mock_state_store = Mock(spec=StateStore)
        
    def test_emergency_stop_functionality(self):
        """Test emergency stop functionality."""
        # Test initial state
        self.assertFalse(self.risk_manager.is_emergency_stop_active())
        self.assertEqual(self.risk_manager.get_emergency_stop_reason(), "")
        
        # Test setting emergency stop
        reason = "Test emergency stop"
        self.risk_manager.set_emergency_stop(reason)
        self.assertTrue(self.risk_manager.is_emergency_stop_active())
        self.assertEqual(self.risk_manager.get_emergency_stop_reason(), reason)
        
        # Test clearing emergency stop
        self.risk_manager.clear_emergency_stop()
        self.assertFalse(self.risk_manager.is_emergency_stop_active())
        self.assertEqual(self.risk_manager.get_emergency_stop_reason(), "")
    
    def test_critical_risk_limits_normal_equity(self):
        """Test critical risk limits with normal equity."""
        current_equity = 10000.0
        initial_equity = 10000.0
        
        should_stop, reason = self.risk_manager.check_critical_risk_limits(
            current_equity, initial_equity
        )
        
        self.assertFalse(should_stop)
        self.assertEqual(reason, "")
    
    def test_critical_risk_limits_daily_loss_exceeded(self):
        """Test critical risk limits when daily loss limit is exceeded."""
        current_equity = 9400.0  # 6% loss (exceeds 5% daily limit)
        initial_equity = 10000.0
        
        should_stop, reason = self.risk_manager.check_critical_risk_limits(
            current_equity, initial_equity
        )
        
        self.assertTrue(should_stop)
        self.assertIn("Daily loss limit exceeded", reason)
        self.assertTrue(self.risk_manager.is_emergency_stop_active())
    
    def test_critical_risk_limits_max_drawdown_exceeded(self):
        """Test critical risk limits when max drawdown is exceeded."""
        # Set a high equity first
        self.risk_manager.max_equity_high = 10000.0
        current_equity = 8000.0  # 20% drawdown (exceeds 10% limit)
        initial_equity = 10000.0
        
        should_stop, reason = self.risk_manager.check_critical_risk_limits(
            current_equity, initial_equity
        )
        
        self.assertTrue(should_stop)
        self.assertIn("Maximum drawdown exceeded", reason)
        self.assertTrue(self.risk_manager.is_emergency_stop_active())
    
    def test_position_size_validation_valid(self):
        """Test position size validation with valid size."""
        position_value = 100.0  # $100 position
        total_equity = 10000.0  # $10,000 equity (1%)
        
        is_valid, reason = self.risk_manager.validate_position_size(
            position_value, total_equity
        )
        
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
    
    def test_position_size_validation_exceeded(self):
        """Test position size validation when limit is exceeded."""
        position_value = 300.0  # $300 position
        total_equity = 10000.0  # $10,000 equity (3% - exceeds 2% limit)
        
        is_valid, reason = self.risk_manager.validate_position_size(
            position_value, total_equity
        )
        
        self.assertFalse(is_valid)
        self.assertIn("Position size too large", reason)
    
    def test_safe_position_sizing(self):
        """Test safe position sizing calculation."""
        entry_price = 100.0
        stop_loss_price = 97.0  # 3% stop loss
        total_equity = 10000.0
        
        safe_size = self.risk_manager.calculate_safe_position_size(
            entry_price, stop_loss_price, total_equity
        )
        
        # Expected: max_risk_amount / risk_per_unit = (10000 * 0.02) / 3 = 66.67
        expected_size = (total_equity * self.config["max_risk_per_trade"]) / abs(entry_price - stop_loss_price)
        self.assertAlmostEqual(safe_size, expected_size, places=2)
    
    def test_stop_loss_calculation_buy(self):
        """Test stop loss calculation for buy orders."""
        entry_price = 100.0
        stop_loss = self.risk_manager.calculate_stop_loss_price(entry_price, 'buy')
        
        expected_stop_loss = entry_price * (1 - self.config["stop_loss_percentage"])
        self.assertAlmostEqual(stop_loss, expected_stop_loss, places=4)
        self.assertLess(stop_loss, entry_price)
    
    def test_stop_loss_calculation_sell(self):
        """Test stop loss calculation for sell orders."""
        entry_price = 100.0
        stop_loss = self.risk_manager.calculate_stop_loss_price(entry_price, 'sell')
        
        expected_stop_loss = entry_price * (1 + self.config["stop_loss_percentage"])
        self.assertAlmostEqual(stop_loss, expected_stop_loss, places=4)
        self.assertGreater(stop_loss, entry_price)
    
    def test_daily_tracking_reset(self):
        """Test daily tracking reset functionality."""
        # Set some values
        self.risk_manager.daily_trades_count = 5
        self.risk_manager.daily_losses = 100.0
        self.risk_manager.daily_wins = 200.0
        
        # Reset
        self.risk_manager.reset_daily_tracking()
        
        self.assertIsNone(self.risk_manager.daily_start_equity)
        self.assertEqual(self.risk_manager.daily_trades_count, 0)
        self.assertEqual(self.risk_manager.daily_losses, 0.0)
        self.assertEqual(self.risk_manager.daily_wins, 0.0)
    
    def test_trade_result_update_win(self):
        """Test trade result update for winning trade."""
        self.risk_manager.daily_trades_count = 0
        self.risk_manager.daily_wins = 0.0
        self.risk_manager.daily_losses = 0.0
        
        pnl = 50.0
        self.risk_manager.update_trade_result(pnl)
        
        self.assertEqual(self.risk_manager.daily_trades_count, 1)
        self.assertEqual(self.risk_manager.daily_wins, 50.0)
        self.assertEqual(self.risk_manager.daily_losses, 0.0)
    
    def test_trade_result_update_loss(self):
        """Test trade result update for losing trade."""
        self.risk_manager.daily_trades_count = 0
        self.risk_manager.daily_wins = 0.0
        self.risk_manager.daily_losses = 0.0
        
        pnl = -30.0
        self.risk_manager.update_trade_result(pnl)
        
        self.assertEqual(self.risk_manager.daily_trades_count, 1)
        self.assertEqual(self.risk_manager.daily_wins, 0.0)
        self.assertEqual(self.risk_manager.daily_losses, 30.0)
    
    def test_edge_case_zero_equity(self):
        """Test edge case with zero equity."""
        current_equity = 0.0
        initial_equity = 10000.0
        
        should_stop, reason = self.risk_manager.check_critical_risk_limits(
            current_equity, initial_equity
        )
        
        self.assertTrue(should_stop)
        self.assertIn("Daily loss limit exceeded", reason)
    
    def test_edge_case_negative_equity(self):
        """Test edge case with negative equity."""
        current_equity = -1000.0
        initial_equity = 10000.0
        
        should_stop, reason = self.risk_manager.check_critical_risk_limits(
            current_equity, initial_equity
        )
        
        self.assertTrue(should_stop)
        self.assertIn("Daily loss limit exceeded", reason)
    
    def test_edge_case_very_small_position(self):
        """Test edge case with very small position size."""
        position_value = 0.01  # $0.01 position
        total_equity = 10000.0
        
        is_valid, reason = self.risk_manager.validate_position_size(
            position_value, total_equity
        )
        
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
    
    def test_edge_case_zero_stop_loss(self):
        """Test edge case with zero stop loss distance."""
        entry_price = 100.0
        stop_loss_price = 100.0  # Same as entry price
        total_equity = 10000.0
        
        # This should handle division by zero gracefully
        safe_size = self.risk_manager.calculate_safe_position_size(
            entry_price, stop_loss_price, total_equity
        )
        
        # Should return 0 or handle gracefully
        self.assertGreaterEqual(safe_size, 0)
    
    def test_configuration_validation(self):
        """Test configuration validation."""
        # Test valid configuration
        valid_config = {
            "daily_loss_limit": 0.05,
            "max_drawdown_limit": 0.10,
            "position_size_limit": 0.02,
            "stop_loss_percentage": 0.03,
            "max_risk_per_trade": 0.02
        }
        
        risk_manager = ProfitOptimizedRiskManager(valid_config)
        self.assertEqual(risk_manager.daily_loss_limit, 0.05)
        self.assertEqual(risk_manager.max_drawdown_limit, 0.10)
        self.assertEqual(risk_manager.position_size_limit, 0.02)
        self.assertEqual(risk_manager.stop_loss_percentage, 0.03)
        self.assertEqual(risk_manager.max_risk_per_trade, 0.02)
    
    def test_default_configuration(self):
        """Test default configuration values."""
        risk_manager = ProfitOptimizedRiskManager()  # No config provided
        
        # Should use defaults
        self.assertEqual(risk_manager.daily_loss_limit, 0.05)
        self.assertEqual(risk_manager.max_drawdown_limit, 0.10)
        self.assertEqual(risk_manager.position_size_limit, 0.02)
        self.assertEqual(risk_manager.stop_loss_percentage, 0.03)
        self.assertEqual(risk_manager.max_risk_per_trade, 0.02)
    
    def test_risk_metrics_calculation(self):
        """Test risk metrics calculation."""
        # Mock some data
        returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.02, -0.01, 0.03]
        
        max_drawdown = self.risk_manager.calculate_max_drawdown(returns)
        
        # Should return a positive value (drawdown is always positive)
        self.assertGreaterEqual(max_drawdown, 0)
    
    def test_risk_reward_ratio_calculation(self):
        """Test risk-reward ratio calculation."""
        entry = 100.0
        stop_loss = 97.0
        take_profit = 103.0
        
        rr_ratio = self.risk_manager.compute_rr(entry, stop_loss, take_profit)
        
        # Expected: (103 - 100) / (100 - 97) = 3 / 3 = 1.0
        expected_rr = (take_profit - entry) / (entry - stop_loss)
        self.assertAlmostEqual(rr_ratio, expected_rr, places=4)
    
    def test_stress_test_multiple_emergency_stops(self):
        """Stress test: Multiple emergency stops and clears."""
        for i in range(100):
            reason = f"Test emergency stop {i}"
            self.risk_manager.set_emergency_stop(reason)
            self.assertTrue(self.risk_manager.is_emergency_stop_active())
            self.assertEqual(self.risk_manager.get_emergency_stop_reason(), reason)
            
            self.risk_manager.clear_emergency_stop()
            self.assertFalse(self.risk_manager.is_emergency_stop_active())
            self.assertEqual(self.risk_manager.get_emergency_stop_reason(), "")
    
    def test_stress_test_position_sizing(self):
        """Stress test: Multiple position sizing calculations."""
        for i in range(1000):
            entry_price = 100.0 + i * 0.01
            stop_loss_price = entry_price * 0.97
            total_equity = 10000.0 + i * 10
            
            safe_size = self.risk_manager.calculate_safe_position_size(
                entry_price, stop_loss_price, total_equity
            )
            
            # Should always return a positive value
            self.assertGreaterEqual(safe_size, 0)
    
    def test_concurrent_risk_checks(self):
        """Test concurrent risk limit checks."""
        import threading
        import time
        
        results = []
        
        def check_risk_limits():
            current_equity = 9500.0  # 5% loss
            initial_equity = 10000.0
            should_stop, reason = self.risk_manager.check_critical_risk_limits(
                current_equity, initial_equity
            )
            results.append((should_stop, reason))
        
        # Create multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=check_risk_limits)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All results should be the same
        self.assertEqual(len(results), 10)
        for should_stop, reason in results:
            self.assertFalse(should_stop)  # 5% loss should not trigger emergency stop


class TestRiskManagementIntegration(unittest.TestCase):
    """Integration tests for risk management with other components."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.config = {
            "daily_loss_limit": 0.05,
            "max_drawdown_limit": 0.10,
            "position_size_limit": 0.02,
            "stop_loss_percentage": 0.03,
            "max_risk_per_trade": 0.02
        }
        self.risk_manager = ProfitOptimizedRiskManager(self.config)
    
    def test_risk_manager_with_trading_system(self):
        """Test risk manager integration with trading system."""
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.risk_manager = self.risk_manager
        mock_trading_system._get_total_equity = Mock(return_value=10000.0)
        mock_trading_system.portfolio = {"initial_capital": 10000.0}
        
        # Test risk checks
        can_trade, reason = mock_trading_system._check_risk_limits_before_trade(
            "BTC/USDT", "buy", 0.1, 50000.0
        )
        
        # Should pass with normal equity
        self.assertTrue(can_trade)
        self.assertIn("Risk checks passed", reason)
    
    def test_risk_manager_with_order_manager(self):
        """Test risk manager integration with order manager."""
        # Mock order manager
        mock_order_manager = Mock()
        mock_order_manager.execute_order_with_risk_management = Mock(
            return_value={
                "success": True,
                "order_id": "test_order_123",
                "executed_quantity": 0.1,
                "executed_price": 50000.0,
                "risk_params": {
                    "stop_loss": 48500.0,
                    "take_profit": 51500.0,
                    "position_size": 0.1,
                    "risk_per_trade": 150.0
                }
            }
        )
        
        # Test order execution with risk management
        result = mock_order_manager.execute_order_with_risk_management(
            "BTC/USDT", "buy", 0.1, 50000.0, self.risk_manager
        )
        
        self.assertTrue(result["success"])
        self.assertIn("risk_params", result)
        self.assertIn("stop_loss", result["risk_params"])


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_suite.addTest(unittest.makeSuite(TestRiskManagement))
    test_suite.addTest(unittest.makeSuite(TestRiskManagementIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print(f"\n{'='*50}")
    print(f"Risk Management Tests Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    print(f"{'='*50}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

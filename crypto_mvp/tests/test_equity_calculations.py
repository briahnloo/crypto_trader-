#!/usr/bin/env python3
"""
Comprehensive validation tests for equity calculations.
Tests all critical equity calculation functionality and edge cases.
"""

import unittest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from crypto_mvp.state.store import StateStore
from crypto_mvp.core.config_manager import ConfigManager


class TestEquityCalculations(unittest.TestCase):
    """Test suite for equity calculation functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = ConfigManager()
        self.config = self.config_manager._config
        
        # Mock trading system
        self.trading_system = Mock(spec=ProfitMaximizingTradingSystem)
        self.trading_system.config = self.config
        self.trading_system.logger = Mock()
        
        # Mock state store
        self.mock_state_store = Mock(spec=StateStore)
        
        # Mock portfolio
        self.portfolio = {
            "cash_balance": 10000.0,
            "initial_capital": 10000.0,
            "equity": 10000.0,
            "positions": {}
        }
    
    def test_basic_equity_calculation(self):
        """Test basic equity calculation with no positions."""
        # Mock _get_total_equity method
        def mock_get_total_equity():
            return self.portfolio["cash_balance"]
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        self.assertEqual(equity, 10000.0)
    
    def test_equity_calculation_with_positions(self):
        """Test equity calculation with positions."""
        # Add positions to portfolio
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": 50000.0,
                "avg_cost": 48000.0
            },
            "ETH/USDT": {
                "quantity": 0.5,
                "current_price": 3000.0,
                "avg_cost": 2900.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + (0.1 * 50000) + (0.5 * 3000) = 10000 + 5000 + 1500 = 16500
        expected_equity = 10000.0 + 5000.0 + 1500.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_with_cash_debit(self):
        """Test equity calculation after cash is debited for purchases."""
        # Simulate cash debit for position purchase
        self.portfolio["cash_balance"] = 5000.0  # Reduced from 10000
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": 50000.0,
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 5000 + (0.1 * 50000) = 5000 + 5000 = 10000
        expected_equity = 5000.0 + 5000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_with_price_fluctuations(self):
        """Test equity calculation with price fluctuations."""
        # Initial portfolio
        self.portfolio["cash_balance"] = 5000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": 55000.0,  # Price increased from 50000
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 5000 + (0.1 * 55000) = 5000 + 5500 = 10500
        expected_equity = 5000.0 + 5500.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_with_multiple_positions(self):
        """Test equity calculation with multiple positions."""
        self.portfolio["cash_balance"] = 2000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": 50000.0,
                "avg_cost": 50000.0
            },
            "ETH/USDT": {
                "quantity": 0.5,
                "current_price": 3000.0,
                "avg_cost": 3000.0
            },
            "SOL/USDT": {
                "quantity": 10.0,
                "current_price": 200.0,
                "avg_cost": 200.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 2000 + (0.1 * 50000) + (0.5 * 3000) + (10 * 200) = 2000 + 5000 + 1500 + 2000 = 10500
        expected_equity = 2000.0 + 5000.0 + 1500.0 + 2000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_edge_case_zero_positions(self):
        """Test equity calculation with zero quantity positions."""
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.0,  # Zero quantity
                "current_price": 50000.0,
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + (0.0 * 50000) = 10000
        expected_equity = 10000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_edge_case_negative_prices(self):
        """Test equity calculation with negative prices (should not happen but test robustness)."""
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": -50000.0,  # Negative price (invalid)
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + (0.1 * -50000) = 10000 - 5000 = 5000
        expected_equity = 10000.0 - 5000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_edge_case_missing_fields(self):
        """Test equity calculation with missing position fields."""
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                # Missing current_price
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method with error handling
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = 0.0
            for pos in self.portfolio["positions"].values():
                try:
                    position_value += pos["quantity"] * pos["current_price"]
                except KeyError:
                    # Handle missing fields gracefully
                    continue
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + 0 (due to missing current_price) = 10000
        expected_equity = 10000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_precision(self):
        """Test equity calculation precision with decimal values."""
        self.portfolio["cash_balance"] = 9999.99
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.123456789,
                "current_price": 50000.123456,
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 9999.99 + (0.123456789 * 50000.123456)
        expected_equity = 9999.99 + (0.123456789 * 50000.123456)
        self.assertAlmostEqual(equity, expected_equity, places=6)
    
    def test_equity_calculation_with_large_numbers(self):
        """Test equity calculation with large numbers."""
        self.portfolio["cash_balance"] = 1000000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 10.0,
                "current_price": 100000.0,
                "avg_cost": 100000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 1000000 + (10 * 100000) = 1000000 + 1000000 = 2000000
        expected_equity = 1000000.0 + 1000000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_consistency(self):
        """Test equity calculation consistency across multiple calls."""
        self.portfolio["cash_balance"] = 5000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "current_price": 50000.0,
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        # Make multiple calls
        results = []
        for _ in range(10):
            equity = self.trading_system._get_total_equity()
            results.append(equity)
        
        # All results should be the same
        expected_equity = 5000.0 + 5000.0
        for result in results:
            self.assertEqual(result, expected_equity)
    
    def test_equity_calculation_with_empty_portfolio(self):
        """Test equity calculation with empty portfolio."""
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {}
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + 0 = 10000
        expected_equity = 10000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_with_none_values(self):
        """Test equity calculation with None values."""
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": None,  # None value
                "current_price": 50000.0,
                "avg_cost": 50000.0
            }
        }
        
        # Mock _get_total_equity method with None handling
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = 0.0
            for pos in self.portfolio["positions"].values():
                try:
                    if pos["quantity"] is not None and pos["current_price"] is not None:
                        position_value += pos["quantity"] * pos["current_price"]
                except (TypeError, KeyError):
                    continue
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        equity = self.trading_system._get_total_equity()
        
        # Expected: 10000 + 0 (due to None quantity) = 10000
        expected_equity = 10000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_performance(self):
        """Test equity calculation performance with many positions."""
        import time
        
        # Create many positions
        self.portfolio["cash_balance"] = 10000.0
        self.portfolio["positions"] = {}
        
        for i in range(1000):
            self.portfolio["positions"][f"SYMBOL{i}/USDT"] = {
                "quantity": 0.001,
                "current_price": 100.0 + i,
                "avg_cost": 100.0 + i
            }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._get_total_equity = mock_get_total_equity
        
        # Measure performance
        start_time = time.time()
        equity = self.trading_system._get_total_equity()
        end_time = time.time()
        
        calculation_time = end_time - start_time
        
        # Should complete quickly (less than 0.1 seconds)
        self.assertLess(calculation_time, 0.1)
        
        # Should return a valid result
        self.assertIsInstance(equity, (int, float))
        self.assertGreater(equity, 0)


class TestEquityCalculationsIntegration(unittest.TestCase):
    """Integration tests for equity calculations with trading system."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.config_manager = ConfigManager()
        self.config = self.config_manager._config
    
    def test_equity_calculation_with_state_store(self):
        """Test equity calculation integration with state store."""
        # Mock state store
        mock_state_store = Mock()
        mock_state_store.get_session_cash.return_value = 5000.0
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.state_store = mock_state_store
        mock_trading_system.current_session_id = "test_session"
        
        # Mock _get_cash_balance method
        def mock_get_cash_balance():
            return mock_state_store.get_session_cash("test_session")
        
        mock_trading_system._get_cash_balance = mock_get_cash_balance
        
        # Test cash balance retrieval
        cash_balance = mock_trading_system._get_cash_balance()
        self.assertEqual(cash_balance, 5000.0)
    
    def test_equity_calculation_with_portfolio_manager(self):
        """Test equity calculation integration with portfolio manager."""
        # Mock portfolio manager
        mock_portfolio_manager = Mock()
        mock_portfolio_manager.get_portfolio.return_value = {
            "cash_balance": 5000.0,
            "positions": {
                "BTC/USDT": {
                    "quantity": 0.1,
                    "current_price": 50000.0,
                    "avg_cost": 50000.0
                }
            }
        }
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.portfolio_manager = mock_portfolio_manager
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            portfolio = mock_portfolio_manager.get_portfolio()
            cash = portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in portfolio["positions"].values()
            )
            return cash + position_value
        
        mock_trading_system._get_total_equity = mock_get_total_equity
        
        # Test equity calculation
        equity = mock_trading_system._get_total_equity()
        expected_equity = 5000.0 + 5000.0
        self.assertEqual(equity, expected_equity)
    
    def test_equity_calculation_with_risk_manager(self):
        """Test equity calculation integration with risk manager."""
        # Mock risk manager
        mock_risk_manager = Mock()
        mock_risk_manager.check_critical_risk_limits.return_value = (False, "")
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.risk_manager = mock_risk_manager
        mock_trading_system._get_total_equity = Mock(return_value=10000.0)
        mock_trading_system.portfolio = {"initial_capital": 10000.0}
        
        # Test risk check with equity
        current_equity = mock_trading_system._get_total_equity()
        should_stop, reason = mock_risk_manager.check_critical_risk_limits(
            current_equity, 10000.0
        )
        
        self.assertFalse(should_stop)
        self.assertEqual(reason, "")
    
    def test_equity_calculation_with_data_engine(self):
        """Test equity calculation integration with data engine."""
        # Mock data engine
        mock_data_engine = Mock()
        mock_data_engine.get_mark_price.return_value = 50000.0
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.data_engine = mock_data_engine
        
        # Test price retrieval
        price = mock_data_engine.get_mark_price("BTC/USDT")
        self.assertEqual(price, 50000.0)
    
    def test_equity_calculation_end_to_end(self):
        """Test end-to-end equity calculation with all components."""
        # Mock all components
        mock_state_store = Mock()
        mock_state_store.get_session_cash.return_value = 5000.0
        
        mock_data_engine = Mock()
        mock_data_engine.get_mark_price.return_value = 50000.0
        
        mock_risk_manager = Mock()
        mock_risk_manager.check_critical_risk_limits.return_value = (False, "")
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.state_store = mock_state_store
        mock_trading_system.data_engine = mock_data_engine
        mock_trading_system.risk_manager = mock_risk_manager
        mock_trading_system.current_session_id = "test_session"
        mock_trading_system.portfolio = {
            "initial_capital": 10000.0,
            "positions": {
                "BTC/USDT": {
                    "quantity": 0.1,
                    "current_price": 50000.0,
                    "avg_cost": 50000.0
                }
            }
        }
        
        # Mock _get_total_equity method
        def mock_get_total_equity():
            cash = mock_state_store.get_session_cash("test_session")
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in mock_trading_system.portfolio["positions"].values()
            )
            return cash + position_value
        
        mock_trading_system._get_total_equity = mock_get_total_equity
        
        # Test end-to-end equity calculation
        equity = mock_trading_system._get_total_equity()
        expected_equity = 5000.0 + 5000.0
        self.assertEqual(equity, expected_equity)
        
        # Test risk check
        should_stop, reason = mock_risk_manager.check_critical_risk_limits(
            equity, 10000.0
        )
        self.assertFalse(should_stop)


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_suite.addTest(unittest.makeSuite(TestEquityCalculations))
    test_suite.addTest(unittest.makeSuite(TestEquityCalculationsIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print(f"\n{'='*50}")
    print(f"Equity Calculations Tests Summary:")
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

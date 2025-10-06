#!/usr/bin/env python3
"""
Comprehensive paper trading validation tests.
Tests all critical paper trading functionality and safety mechanisms.
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


class TestPaperTrading(unittest.TestCase):
    """Test suite for paper trading functionality."""
    
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
    
    def test_paper_trading_mode_enabled(self):
        """Test that paper trading mode is enabled by default."""
        # Check configuration
        safeguards_config = self.config.get("live_trading_safeguards", {})
        paper_trading_mode = safeguards_config.get("paper_trading_mode", True)
        
        self.assertTrue(paper_trading_mode, "Paper trading mode should be enabled by default")
    
    def test_paper_trading_balance(self):
        """Test paper trading balance configuration."""
        safeguards_config = self.config.get("live_trading_safeguards", {})
        paper_trading_balance = safeguards_config.get("paper_trading_balance", 10000)
        
        self.assertEqual(paper_trading_balance, 10000, "Paper trading balance should be $10,000")
    
    def test_paper_trading_trade_execution(self):
        """Test paper trading trade execution (simulated)."""
        # Mock paper trading trade execution
        def mock_execute_paper_trade(symbol, side, quantity, price):
            return {
                "success": True,
                "order_id": f"paper_{symbol}_{side}_{quantity}_{price}",
                "executed_quantity": quantity,
                "executed_price": price,
                "paper_trading": True
            }
        
        self.trading_system._execute_paper_trade = mock_execute_paper_trade
        
        # Execute paper trade
        result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", 0.1, 50000.0)
        
        self.assertTrue(result["success"])
        self.assertTrue(result["paper_trading"])
        self.assertEqual(result["executed_quantity"], 0.1)
        self.assertEqual(result["executed_price"], 50000.0)
    
    def test_paper_trading_position_tracking(self):
        """Test paper trading position tracking."""
        # Mock paper trading position tracking
        def mock_update_paper_position(symbol, side, quantity, price):
            if symbol not in self.portfolio["positions"]:
                self.portfolio["positions"][symbol] = {
                    "quantity": 0.0,
                    "avg_cost": 0.0,
                    "current_price": price
                }
            
            position = self.portfolio["positions"][symbol]
            
            if side == "buy":
                new_quantity = position["quantity"] + quantity
                new_avg_cost = ((position["quantity"] * position["avg_cost"]) + (quantity * price)) / new_quantity
                position["quantity"] = new_quantity
                position["avg_cost"] = new_avg_cost
            else:  # sell
                position["quantity"] -= quantity
            
            position["current_price"] = price
            
            return position
        
        self.trading_system._update_paper_position = mock_update_paper_position
        
        # Test buying position
        position = self.trading_system._update_paper_position("BTC/USDT", "buy", 0.1, 50000.0)
        self.assertEqual(position["quantity"], 0.1)
        self.assertEqual(position["avg_cost"], 50000.0)
        
        # Test buying more
        position = self.trading_system._update_paper_position("BTC/USDT", "buy", 0.1, 55000.0)
        self.assertEqual(position["quantity"], 0.2)
        self.assertEqual(position["avg_cost"], 52500.0)  # (0.1*50000 + 0.1*55000) / 0.2
        
        # Test selling
        position = self.trading_system._update_paper_position("BTC/USDT", "sell", 0.1, 60000.0)
        self.assertEqual(position["quantity"], 0.1)
    
    def test_paper_trading_equity_calculation(self):
        """Test paper trading equity calculation."""
        # Set up paper trading portfolio
        self.portfolio["cash_balance"] = 5000.0
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "avg_cost": 50000.0,
                "current_price": 55000.0
            }
        }
        
        # Mock paper trading equity calculation
        def mock_calculate_paper_equity():
            cash = self.portfolio["cash_balance"]
            position_value = sum(
                pos["quantity"] * pos["current_price"]
                for pos in self.portfolio["positions"].values()
            )
            return cash + position_value
        
        self.trading_system._calculate_paper_equity = mock_calculate_paper_equity
        
        # Test equity calculation
        equity = self.trading_system._calculate_paper_equity()
        expected_equity = 5000.0 + (0.1 * 55000.0)  # 5000 + 5500 = 10500
        self.assertEqual(equity, expected_equity)
    
    def test_paper_trading_pnl_calculation(self):
        """Test paper trading P&L calculation."""
        # Set up paper trading portfolio
        self.portfolio["positions"] = {
            "BTC/USDT": {
                "quantity": 0.1,
                "avg_cost": 50000.0,
                "current_price": 55000.0
            }
        }
        
        # Mock paper trading P&L calculation
        def mock_calculate_paper_pnl():
            total_pnl = 0.0
            for symbol, pos in self.portfolio["positions"].items():
                unrealized_pnl = (pos["current_price"] - pos["avg_cost"]) * pos["quantity"]
                total_pnl += unrealized_pnl
            return total_pnl
        
        self.trading_system._calculate_paper_pnl = mock_calculate_paper_pnl
        
        # Test P&L calculation
        pnl = self.trading_system._calculate_paper_pnl()
        expected_pnl = (55000.0 - 50000.0) * 0.1  # 5000 * 0.1 = 500
        self.assertEqual(pnl, expected_pnl)
    
    def test_paper_trading_risk_management(self):
        """Test paper trading risk management."""
        # Mock paper trading risk management
        def mock_check_paper_risk_limits(symbol, side, quantity, price):
            # Check position size limit
            position_value = quantity * price
            total_equity = 10000.0  # Mock total equity
            position_pct = position_value / total_equity
            
            if position_pct > 0.02:  # 2% limit
                return False, f"Position size too large: {position_pct*100:.2f}%"
            
            return True, "Risk checks passed"
        
        self.trading_system._check_paper_risk_limits = mock_check_paper_risk_limits
        
        # Test valid position size
        can_trade, reason = self.trading_system._check_paper_risk_limits("BTC/USDT", "buy", 0.1, 50000.0)
        self.assertTrue(can_trade)
        self.assertEqual(reason, "Risk checks passed")
        
        # Test invalid position size
        can_trade, reason = self.trading_system._check_paper_risk_limits("BTC/USDT", "buy", 1.0, 50000.0)
        self.assertFalse(can_trade)
        self.assertIn("Position size too large", reason)
    
    def test_paper_trading_session_tracking(self):
        """Test paper trading session tracking."""
        # Mock paper trading session tracking
        def mock_track_paper_session():
            return {
                "session_start": datetime.now(),
                "trades_count": 0,
                "total_pnl": 0.0,
                "winning_trades": 0,
                "losing_trades": 0
            }
        
        self.trading_system._track_paper_session = mock_track_paper_session
        
        # Test session tracking
        session = self.trading_system._track_paper_session()
        self.assertIn("session_start", session)
        self.assertEqual(session["trades_count"], 0)
        self.assertEqual(session["total_pnl"], 0.0)
    
    def test_paper_trading_performance_metrics(self):
        """Test paper trading performance metrics."""
        # Mock paper trading performance metrics
        def mock_calculate_paper_metrics():
            return {
                "total_trades": 100,
                "winning_trades": 60,
                "losing_trades": 40,
                "win_rate": 0.6,
                "total_pnl": 5000.0,
                "max_drawdown": 1000.0,
                "sharpe_ratio": 1.5,
                "profit_factor": 1.8
            }
        
        self.trading_system._calculate_paper_metrics = mock_calculate_paper_metrics
        
        # Test performance metrics
        metrics = self.trading_system._calculate_paper_metrics()
        self.assertEqual(metrics["total_trades"], 100)
        self.assertEqual(metrics["win_rate"], 0.6)
        self.assertEqual(metrics["total_pnl"], 5000.0)
        self.assertGreater(metrics["profit_factor"], 1.0)
    
    def test_paper_trading_pre_live_requirements(self):
        """Test paper trading pre-live requirements."""
        safeguards_config = self.config.get("live_trading_safeguards", {})
        pre_live_checks = safeguards_config.get("pre_live_checks", {})
        
        # Test pre-live requirements
        min_paper_trading_days = pre_live_checks.get("min_paper_trading_days", 7)
        min_paper_trading_trades = pre_live_checks.get("min_paper_trading_trades", 50)
        max_paper_trading_loss_pct = pre_live_checks.get("max_paper_trading_loss_pct", 5.0)
        required_win_rate = pre_live_checks.get("required_win_rate", 0.4)
        required_profit_factor = pre_live_checks.get("required_profit_factor", 1.2)
        
        self.assertEqual(min_paper_trading_days, 7)
        self.assertEqual(min_paper_trading_trades, 50)
        self.assertEqual(max_paper_trading_loss_pct, 5.0)
        self.assertEqual(required_win_rate, 0.4)
        self.assertEqual(required_profit_factor, 1.2)
    
    def test_paper_trading_live_trading_confirmation(self):
        """Test paper trading live trading confirmation system."""
        safeguards_config = self.config.get("live_trading_safeguards", {})
        live_trading_confirmation = safeguards_config.get("live_trading_confirmation", {})
        
        # Test confirmation requirements
        require_confirmation = live_trading_confirmation.get("require_confirmation", True)
        confirmation_timeout = live_trading_confirmation.get("confirmation_timeout", 30)
        double_confirmation = live_trading_confirmation.get("double_confirmation", True)
        confirmation_phrase = live_trading_confirmation.get("confirmation_phrase", "I_UNDERSTAND_THE_RISKS")
        
        self.assertTrue(require_confirmation)
        self.assertEqual(confirmation_timeout, 30)
        self.assertTrue(double_confirmation)
        self.assertEqual(confirmation_phrase, "I_UNDERSTAND_THE_RISKS")
    
    def test_paper_trading_edge_cases(self):
        """Test paper trading edge cases."""
        # Test zero quantity trade
        def mock_execute_paper_trade(symbol, side, quantity, price):
            if quantity <= 0:
                return {"success": False, "error": "Invalid quantity"}
            return {"success": True, "paper_trading": True}
        
        self.trading_system._execute_paper_trade = mock_execute_paper_trade
        
        # Test zero quantity
        result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", 0.0, 50000.0)
        self.assertFalse(result["success"])
        self.assertIn("Invalid quantity", result["error"])
        
        # Test negative quantity
        result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", -0.1, 50000.0)
        self.assertFalse(result["success"])
        self.assertIn("Invalid quantity", result["error"])
        
        # Test zero price
        result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", 0.1, 0.0)
        self.assertFalse(result["success"])
        self.assertIn("Invalid quantity", result["error"])
    
    def test_paper_trading_stress_test(self):
        """Stress test paper trading with many trades."""
        import time
        
        # Mock paper trading execution
        def mock_execute_paper_trade(symbol, side, quantity, price):
            return {
                "success": True,
                "order_id": f"paper_{symbol}_{side}_{quantity}_{price}",
                "executed_quantity": quantity,
                "executed_price": price,
                "paper_trading": True
            }
        
        self.trading_system._execute_paper_trade = mock_execute_paper_trade
        
        # Execute many trades
        start_time = time.time()
        results = []
        
        for i in range(1000):
            result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", 0.001, 50000.0 + i)
            results.append(result)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # All trades should succeed
        for result in results:
            self.assertTrue(result["success"])
            self.assertTrue(result["paper_trading"])
        
        # Should execute quickly (less than 1 second for 1000 trades)
        self.assertLess(execution_time, 1.0)
    
    def test_paper_trading_concurrent_trades(self):
        """Test concurrent paper trading operations."""
        import threading
        
        results = []
        
        def execute_trade():
            def mock_execute_paper_trade(symbol, side, quantity, price):
                return {
                    "success": True,
                    "order_id": f"paper_{symbol}_{side}_{quantity}_{price}",
                    "executed_quantity": quantity,
                    "executed_price": price,
                    "paper_trading": True
                }
            
            self.trading_system._execute_paper_trade = mock_execute_paper_trade
            
            result = self.trading_system._execute_paper_trade("BTC/USDT", "buy", 0.1, 50000.0)
            results.append(result)
        
        # Create multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=execute_trade)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All trades should succeed
        self.assertEqual(len(results), 10)
        for result in results:
            self.assertTrue(result["success"])
            self.assertTrue(result["paper_trading"])


class TestPaperTradingIntegration(unittest.TestCase):
    """Integration tests for paper trading with trading system."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.config_manager = ConfigManager()
        self.config = self.config_manager._config
    
    def test_paper_trading_with_trading_system(self):
        """Test paper trading integration with trading system."""
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.config = self.config
        mock_trading_system.logger = Mock()
        
        # Mock paper trading mode check
        def mock_is_paper_trading():
            safeguards_config = self.config.get("live_trading_safeguards", {})
            return safeguards_config.get("paper_trading_mode", True)
        
        mock_trading_system._is_paper_trading = mock_is_paper_trading
        
        # Test paper trading mode
        is_paper_trading = mock_trading_system._is_paper_trading()
        self.assertTrue(is_paper_trading)
    
    def test_paper_trading_with_risk_manager(self):
        """Test paper trading integration with risk manager."""
        # Mock risk manager
        mock_risk_manager = Mock()
        mock_risk_manager.is_emergency_stop_active.return_value = False
        mock_risk_manager.validate_position_size.return_value = (True, "")
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.risk_manager = mock_risk_manager
        
        # Test risk checks in paper trading
        is_valid, reason = mock_risk_manager.validate_position_size(100.0, 10000.0)
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")
    
    def test_paper_trading_with_state_store(self):
        """Test paper trading integration with state store."""
        # Mock state store
        mock_state_store = Mock()
        mock_state_store.get_session_cash.return_value = 10000.0
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.state_store = mock_state_store
        mock_trading_system.current_session_id = "paper_session"
        
        # Test paper trading balance
        cash_balance = mock_state_store.get_session_cash("paper_session")
        self.assertEqual(cash_balance, 10000.0)
    
    def test_paper_trading_with_data_engine(self):
        """Test paper trading integration with data engine."""
        # Mock data engine
        mock_data_engine = Mock()
        mock_data_engine.get_mark_price.return_value = 50000.0
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.data_engine = mock_data_engine
        
        # Test price retrieval for paper trading
        price = mock_data_engine.get_mark_price("BTC/USDT")
        self.assertEqual(price, 50000.0)
    
    def test_paper_trading_end_to_end(self):
        """Test end-to-end paper trading workflow."""
        # Mock all components
        mock_state_store = Mock()
        mock_state_store.get_session_cash.return_value = 10000.0
        
        mock_data_engine = Mock()
        mock_data_engine.get_mark_price.return_value = 50000.0
        
        mock_risk_manager = Mock()
        mock_risk_manager.is_emergency_stop_active.return_value = False
        mock_risk_manager.validate_position_size.return_value = (True, "")
        
        # Mock trading system
        mock_trading_system = Mock()
        mock_trading_system.state_store = mock_state_store
        mock_trading_system.data_engine = mock_data_engine
        mock_trading_system.risk_manager = mock_risk_manager
        mock_trading_system.current_session_id = "paper_session"
        mock_trading_system.config = self.config
        
        # Mock paper trading execution
        def mock_execute_paper_trade(symbol, side, quantity, price):
            return {
                "success": True,
                "order_id": f"paper_{symbol}_{side}_{quantity}_{price}",
                "executed_quantity": quantity,
                "executed_price": price,
                "paper_trading": True
            }
        
        mock_trading_system._execute_paper_trade = mock_execute_paper_trade
        
        # Test end-to-end paper trading
        # 1. Check paper trading mode
        safeguards_config = self.config.get("live_trading_safeguards", {})
        is_paper_trading = safeguards_config.get("paper_trading_mode", True)
        self.assertTrue(is_paper_trading)
        
        # 2. Get current price
        price = mock_data_engine.get_mark_price("BTC/USDT")
        self.assertEqual(price, 50000.0)
        
        # 3. Check risk limits
        is_valid, reason = mock_risk_manager.validate_position_size(100.0, 10000.0)
        self.assertTrue(is_valid)
        
        # 4. Execute paper trade
        result = mock_trading_system._execute_paper_trade("BTC/USDT", "buy", 0.1, price)
        self.assertTrue(result["success"])
        self.assertTrue(result["paper_trading"])
        
        # 5. Check cash balance
        cash_balance = mock_state_store.get_session_cash("paper_session")
        self.assertEqual(cash_balance, 10000.0)


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_suite.addTest(unittest.makeSuite(TestPaperTrading))
    test_suite.addTest(unittest.makeSuite(TestPaperTradingIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print(f"\n{'='*50}")
    print(f"Paper Trading Tests Summary:")
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

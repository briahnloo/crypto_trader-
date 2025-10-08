"""
Test volume calculation accuracy in analytics.

This test verifies that volume calculations correctly sum absolute fill notional values
and that trade counts and average trade sizes are calculated properly.
"""

import unittest
import tempfile
import os
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock

from src.crypto_mvp.analytics.trade_ledger import TradeLedger
from src.crypto_mvp.analytics.profit_analytics import ProfitAnalytics


class TestVolumeCalculation(unittest.TestCase):
    """Test volume calculation accuracy and consistency."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        self.temp_db_path = temp_db.name
        
        # Initialize trade ledger
        self.trade_ledger = TradeLedger(self.temp_db_path)
        
        # Initialize profit analytics
        self.profit_analytics = ProfitAnalytics()
        self.profit_analytics.trade_ledger = self.trade_ledger
        self.profit_analytics.session_id = "test_session"
        
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)
    
    def test_volume_calculation_450_plus_1000_equals_1450(self):
        """Test that $450 + $1,000 buys report $1,450 volume."""
        # Create two buy trades with specific notional values
        trades = [
            {
                "trade_id": "test_buy_1",
                "session_id": "test_session",
                "symbol": "BTC/USDT",
                "side": "buy",
                "quantity": 0.009,  # $450 / $50,000 = 0.009 BTC
                "fill_price": 50000.0,
                "notional_value": 450.0,  # $450
                "fees": 0.90,  # 20bps of $450
                "strategy": "test",
                "executed_at": datetime.now().isoformat(),
                "metadata": {}
            },
            {
                "trade_id": "test_buy_2", 
                "session_id": "test_session",
                "symbol": "BTC/USDT",
                "side": "buy",
                "quantity": 0.02,  # $1,000 / $50,000 = 0.02 BTC
                "fill_price": 50000.0,
                "notional_value": 1000.0,  # $1,000
                "fees": 2.00,  # 20bps of $1,000
                "strategy": "test",
                "executed_at": datetime.now().isoformat(),
                "metadata": {}
            }
        ]
        
        # Commit trades to ledger
        for trade in trades:
            success = self.trade_ledger.commit_fill(
                trade_id=trade["trade_id"],
                session_id=trade["session_id"],
                symbol=trade["symbol"],
                side=trade["side"],
                quantity=trade["quantity"],
                fill_price=trade["fill_price"],
                fees=trade["fees"],
                strategy=trade["strategy"]
            )
            self.assertTrue(success, f"Failed to commit trade {trade['trade_id']}")
        
        # Get metrics from ledger
        metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
        
        # Verify volume calculation
        expected_volume = 450.0 + 1000.0  # $1,450
        actual_volume = metrics["total_volume"]
        
        self.assertAlmostEqual(
            actual_volume, expected_volume, places=2,
            msg=f"Expected volume ${expected_volume}, got ${actual_volume}"
        )
        
        # Verify trade count
        expected_trade_count = 2
        actual_trade_count = metrics["trade_count"]
        
        self.assertEqual(
            actual_trade_count, expected_trade_count,
            msg=f"Expected trade count {expected_trade_count}, got {actual_trade_count}"
        )
        
        # Verify average trade size
        expected_avg_trade_size = expected_volume / expected_trade_count  # $725
        actual_avg_trade_size = metrics["avg_trade_size"]
        
        self.assertAlmostEqual(
            actual_avg_trade_size, expected_avg_trade_size, places=2,
            msg=f"Expected avg trade size ${expected_avg_trade_size}, got ${actual_avg_trade_size}"
        )
        
        # Verify total fees
        expected_total_fees = 0.90 + 2.00  # $2.90
        actual_total_fees = metrics["total_fees"]
        
        self.assertAlmostEqual(
            actual_total_fees, expected_total_fees, places=2,
            msg=f"Expected total fees ${expected_total_fees}, got ${actual_total_fees}"
        )
    
    def test_volume_calculation_with_mixed_buy_sell(self):
        """Test volume calculation with mixed buy and sell trades."""
        # Create mixed trades
        trades = [
            {
                "trade_id": "test_buy",
                "session_id": "test_session",
                "symbol": "BTC/USDT",
                "side": "buy",
                "quantity": 0.01,
                "fill_price": 50000.0,
                "notional_value": 500.0,  # $500
                "fees": 1.00,
                "strategy": "test",
                "executed_at": datetime.now().isoformat(),
                "metadata": {}
            },
            {
                "trade_id": "test_sell",
                "session_id": "test_session", 
                "symbol": "BTC/USDT",
                "side": "sell",
                "quantity": 0.01,
                "fill_price": 51000.0,
                "notional_value": 510.0,  # $510
                "fees": 1.02,
                "strategy": "test",
                "executed_at": datetime.now().isoformat(),
                "metadata": {}
            }
        ]
        
        # Commit trades to ledger
        for trade in trades:
            success = self.trade_ledger.commit_fill(
                trade_id=trade["trade_id"],
                session_id=trade["session_id"],
                symbol=trade["symbol"],
                side=trade["side"],
                quantity=trade["quantity"],
                fill_price=trade["fill_price"],
                fees=trade["fees"],
                strategy=trade["strategy"]
            )
            self.assertTrue(success, f"Failed to commit trade {trade['trade_id']}")
        
        # Get metrics from ledger
        metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
        
        # Verify volume calculation (should sum absolute notional values)
        expected_volume = 500.0 + 510.0  # $1,010
        actual_volume = metrics["total_volume"]
        
        self.assertAlmostEqual(
            actual_volume, expected_volume, places=2,
            msg=f"Expected volume ${expected_volume}, got ${actual_volume}"
        )
        
        # Verify trade count
        self.assertEqual(metrics["trade_count"], 2)
        
        # Verify buy/sell counts
        self.assertEqual(metrics["buy_trades"], 1)
        self.assertEqual(metrics["sell_trades"], 1)
    
    def test_volume_calculation_with_reduce_only_exits(self):
        """Test that reduce-only exits are excluded from volume calculation."""
        # Create new exposure trade
        new_exposure_trade = {
            "trade_id": "test_buy",
            "session_id": "test_session",
            "symbol": "BTC/USDT",
            "side": "buy",
            "quantity": 0.01,
            "fill_price": 50000.0,
            "notional_value": 500.0,  # $500
            "fees": 1.00,
            "strategy": "test",
            "executed_at": datetime.now().isoformat(),
            "metadata": {}
        }
        
        # Create reduce-only exit trade
        reduce_only_trade = {
            "trade_id": "test_sell_exit",
            "session_id": "test_session",
            "symbol": "BTC/USDT", 
            "side": "sell",
            "quantity": 0.01,
            "fill_price": 51000.0,
            "notional_value": 510.0,  # $510
            "fees": 1.02,
            "strategy": "test",
            "executed_at": datetime.now().isoformat(),
            "exit_reason": "STOP_LOSS"  # Mark as reduce-only exit
        }
        
        # Commit trades to ledger
        for trade in [new_exposure_trade, reduce_only_trade]:
            success = self.trade_ledger.commit_fill(
                trade_id=trade["trade_id"],
                session_id=trade["session_id"],
                symbol=trade["symbol"],
                side=trade["side"],
                quantity=trade["quantity"],
                fill_price=trade["fill_price"],
                fees=trade["fees"],
                strategy=trade["strategy"],
                exit_reason=trade.get("exit_reason")
            )
            self.assertTrue(success, f"Failed to commit trade {trade['trade_id']}")
        
        # Get metrics from ledger
        metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
        
        # Verify volume calculation (should only include new exposure, exclude reduce-only)
        expected_volume = 500.0  # Only the buy trade, not the reduce-only sell
        actual_volume = metrics["total_volume"]
        
        self.assertAlmostEqual(
            actual_volume, expected_volume, places=2,
            msg=f"Expected volume ${expected_volume} (new exposure only), got ${actual_volume}"
        )
        
        # Verify trade count (should include all trades)
        self.assertEqual(metrics["trade_count"], 2)
        
        # Verify fees (should include all trades)
        expected_total_fees = 1.00 + 1.02  # $2.02
        actual_total_fees = metrics["total_fees"]
        
        self.assertAlmostEqual(
            actual_total_fees, expected_total_fees, places=2,
            msg=f"Expected total fees ${expected_total_fees}, got ${actual_total_fees}"
        )
    
    def test_division_by_zero_guard(self):
        """Test that division by zero is properly guarded."""
        # Get metrics with no trades
        metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
        
        # Verify all metrics are zero and no division by zero errors
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["trade_count"], 0)
        self.assertEqual(metrics["total_volume"], 0.0)
        self.assertEqual(metrics["avg_trade_size"], 0.0)
        self.assertEqual(metrics["total_fees"], 0.0)
        self.assertEqual(metrics["buy_trades"], 0)
        self.assertEqual(metrics["sell_trades"], 0)
    
    def test_trade_ledger_volume_calculation_regression(self):
        """Test that TradeLedger correctly calculates volume for the regression case."""
        # Create trades that match the regression test case: $450 + $1,000 buys
        trades = [
            {
                "trade_id": "test_buy_1",
                "session_id": "test_session",
                "symbol": "BTC/USDT",
                "side": "buy",
                "quantity": 0.009,  # $450 at $50k
                "fill_price": 50000.0,
                "fees": 0.90,
                "strategy": "test"
            },
            {
                "trade_id": "test_buy_2",
                "session_id": "test_session",
                "symbol": "BTC/USDT",
                "side": "buy", 
                "quantity": 0.02,   # $1,000 at $50k
                "fill_price": 50000.0,
                "fees": 2.00,
                "strategy": "test"
            }
        ]
        
        # Commit trades to ledger
        for trade in trades:
            success = self.trade_ledger.commit_fill(
                trade_id=trade["trade_id"],
                session_id=trade["session_id"],
                symbol=trade["symbol"],
                side=trade["side"],
                quantity=trade["quantity"],
                fill_price=trade["fill_price"],
                fees=trade["fees"],
                strategy=trade["strategy"]
            )
            self.assertTrue(success, f"Failed to commit trade {trade['trade_id']}")
        
        # Get metrics from trade ledger
        metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
        
        # Verify volume calculation - should be $450 + $1,000 = $1,450
        expected_volume = 450.0 + 1000.0  # $1,450
        actual_volume = metrics["total_volume"]
        
        self.assertAlmostEqual(
            actual_volume, expected_volume, places=2,
            msg=f"Expected volume ${expected_volume}, got ${actual_volume}"
        )
        
        # Verify trade count
        self.assertEqual(metrics["trade_count"], 2)
        
        # Verify average trade size
        expected_avg_size = expected_volume / 2  # $725
        actual_avg_size = metrics["avg_trade_size"]
        
        self.assertAlmostEqual(
            actual_avg_size, expected_avg_size, places=2,
            msg=f"Expected avg trade size ${expected_avg_size}, got ${actual_avg_size}"
        )


if __name__ == "__main__":
    unittest.main()

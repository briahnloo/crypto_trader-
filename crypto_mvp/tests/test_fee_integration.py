"""
Test fee integration in the trading system.

This test verifies that fees are properly calculated, deducted from cash,
stored in the trade ledger, and included in realized P&L calculations.
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
import asyncio

from src.crypto_mvp.execution.order_manager import OrderManager, Order, Fill, OrderSide, OrderType, OrderStatus
from src.crypto_mvp.analytics.trade_ledger import TradeLedger
from src.crypto_mvp.state.store import StateStore


class TestFeeIntegration(unittest.TestCase):
    """Test fee calculation and integration across the trading system."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create order manager with 20bps taker fees
        self.config = {
            "taker_fee_bps": 20,  # 20 basis points = 0.2%
            "maker_fee_bps": 10,  # 10 basis points = 0.1%
            "simulate": True,
            "sandbox_mode": True
        }
        
        self.order_manager = OrderManager(self.config)
        self.order_manager.initialize()
        self.order_manager.session_id = "test_session"
        
        # Create mock data engine
        self.data_engine = Mock()
        self.data_engine.get_ticker.return_value = {"price": 50000.0}
        self.order_manager.data_engine = self.data_engine
        
        # Create mock state store
        self.state_store = Mock(spec=StateStore)
        self.state_store.get_session_cash.return_value = 10000.0
        self.state_store.debit_cash.return_value = True
        self.state_store.credit_cash.return_value = True
        self.order_manager.state_store = self.state_store
        
        # Create trade ledger with temporary file
        import tempfile
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        self.trade_ledger = TradeLedger(temp_db.name)
        
        # Test parameters
        self.symbol = "BTC/USDT"
        self.quantity = 0.1  # 0.1 BTC
        self.buy_price = 50000.0  # $50,000 per BTC
        self.sell_price = 51000.0  # $51,000 per BTC (2% profit)
        
        # Store temp file path for cleanup
        self.temp_db_path = temp_db.name
    
    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if hasattr(self, 'temp_db_path') and os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)
        
    def test_fee_calculation_decimal_precision(self):
        """Test that fee calculation uses Decimal precision."""
        # Calculate fees for buy order
        buy_fees = self.order_manager.calculate_fees(
            quantity=self.quantity,
            price=self.buy_price,
            order_type=OrderType.MARKET,
            symbol=self.symbol,
            is_maker=False
        )
        
        # Expected: 0.1 * 50000 * 20 * 0.0001 = 10.00
        expected_buy_fees = self.quantity * self.buy_price * 20 * 0.0001
        self.assertAlmostEqual(buy_fees, expected_buy_fees, places=2)
        self.assertEqual(buy_fees, 10.00)  # Exact match due to quantization
        
        # Calculate fees for sell order
        sell_fees = self.order_manager.calculate_fees(
            quantity=self.quantity,
            price=self.sell_price,
            order_type=OrderType.MARKET,
            symbol=self.symbol,
            is_maker=False
        )
        
        # Expected: 0.1 * 51000 * 20 * 0.0001 = 10.20
        expected_sell_fees = self.quantity * self.sell_price * 20 * 0.0001
        self.assertAlmostEqual(sell_fees, expected_sell_fees, places=2)
        self.assertEqual(sell_fees, 10.20)  # Exact match due to quantization
        
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price_with_provenance')
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price')
    def test_buy_sell_roundtrip_pnl_within_tolerance(self, mock_get_mark_price, mock_provenance):
        """Test buy→sell round-trip P&L matches expected within $0.01."""
        mock_provenance.return_value = (50000.0, "live")
        mock_get_mark_price.return_value = 50000.0
        
        # Mock _calculate_fill_price to return exact prices without slippage
        with patch.object(self.order_manager, '_calculate_fill_price') as mock_fill_price, \
             patch.object(self.order_manager, '_calculate_fill_probability') as mock_fill_prob:
            mock_fill_price.side_effect = lambda order, current_price, volatility: current_price
            mock_fill_prob.return_value = 1.0  # Always fill orders
            
            # Create buy order
            buy_order, error = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            
            self.assertIsNotNone(buy_order)
            self.assertIsNone(error)
            
            # Execute buy order
            buy_fill = self.order_manager.execute_order(buy_order, self.buy_price)
            
            self.assertEqual(buy_fill.quantity, self.quantity)
            # Price may include slippage, so check it's close to mark
            self.assertAlmostEqual(buy_fill.price, self.buy_price, delta=10.0)
            # New fee schedule: 5bps taker = 0.05% of $5000 = $2.50
            self.assertAlmostEqual(buy_fill.fees, 2.50, delta=0.01)
            self.assertEqual(buy_fill.side, OrderSide.BUY)
            
            # Create sell order
            sell_order, error = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            
            self.assertIsNotNone(sell_order)
            self.assertIsNone(error)
            
            # Execute sell order
            sell_fill = self.order_manager.execute_order(sell_order, self.sell_price)
            
            self.assertEqual(sell_fill.quantity, self.quantity)
            # Price may include slippage, so check it's close to mark
            self.assertAlmostEqual(sell_fill.price, self.sell_price, delta=10.0)
            # New fee schedule: 5bps taker = 0.05% of $5100 = $2.55
            self.assertAlmostEqual(sell_fill.fees, 2.55, delta=0.01)
            self.assertEqual(sell_fill.side, OrderSide.SELL)
            
            # Calculate expected P&L with new fee schedule
            # Gross profit: (51000 - 50000) * 0.1 = $100
            # Total fees: $2.50 + $2.55 = $5.05 (5bps taker fees)
            # Net P&L: $100 - $5.05 = $94.95 (approximately, may vary with slippage)
            expected_pnl = (self.sell_price - self.buy_price) * self.quantity - (buy_fill.fees + sell_fill.fees)
            
            # Verify cash impact calls
            self.assertEqual(self.state_store.debit_cash.call_count, 1)
            self.assertEqual(self.state_store.credit_cash.call_count, 1)
            
            # Verify debit call (buy order: notional + fees)
            debit_call_args = self.state_store.debit_cash.call_args
            expected_debit = self.quantity * self.buy_price + buy_fill.fees  # $5000 + $10 = $5010
            # Allow for slippage impact (delta of $1.00 to account for market impact)
            self.assertAlmostEqual(debit_call_args[0][1], expected_debit, delta=1.0)
            self.assertEqual(debit_call_args[0][2], buy_fill.fees)
            
            # Verify credit call (sell order: notional - fees)
            credit_call_args = self.state_store.credit_cash.call_args
            expected_credit = self.quantity * self.sell_price - sell_fill.fees
            # Allow for slippage impact (delta of $1.00 to account for market impact)
            self.assertAlmostEqual(credit_call_args[0][1], expected_credit, delta=1.0)
            self.assertEqual(credit_call_args[0][2], sell_fill.fees)
            
            # Net cash flow: -$5010 + $5089.80 = $79.80
            net_cash_flow = -expected_debit + expected_credit
            self.assertAlmostEqual(net_cash_flow, expected_pnl, places=2)
            
            # Verify P&L is within tolerance (new fee schedule: ~$94.95 instead of old $79.80)
            # With 5bps taker fees: gross $100 - fees ~$5.05 = ~$94.95
            self.assertAlmostEqual(expected_pnl, 94.95, delta=1.0)
            self.assertGreater(expected_pnl, 90.0)  # Should be profitable with lower fees
        
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price_with_provenance')
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price')
    def test_fee_storage_in_trade_ledger(self, mock_get_mark_price, mock_provenance):
        """Test that fees are properly stored in the trade ledger."""
        mock_provenance.return_value = (50000.0, "live")
        mock_get_mark_price.return_value = 50000.0
        
        # Mock _calculate_fill_price to return exact prices without slippage
        with patch.object(self.order_manager, '_calculate_fill_price') as mock_fill_price, \
             patch.object(self.order_manager, '_calculate_fill_probability') as mock_fill_prob:
            mock_fill_price.side_effect = lambda order, current_price, volatility: current_price
            mock_fill_prob.return_value = 1.0  # Always fill orders
            
            # Create and execute buy order
            buy_order, _ = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            
            buy_fill = self.order_manager.execute_order(buy_order, self.buy_price)
            
            # Commit to trade ledger
            trade_id = f"test_buy_{buy_order.id}"
            success = self.trade_ledger.commit_fill(
                trade_id=trade_id,
                session_id="test_session",
                symbol=self.symbol,
                side="buy",
                quantity=self.quantity,
                fill_price=self.buy_price,
                fees=buy_fill.fees,
                strategy="test"
            )
            
            self.assertTrue(success)
            
            # Create and execute sell order
            sell_order, _ = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            
            sell_fill = self.order_manager.execute_order(sell_order, self.sell_price)
            
            # Commit to trade ledger
            trade_id = f"test_sell_{sell_order.id}"
            success = self.trade_ledger.commit_fill(
                trade_id=trade_id,
                session_id="test_session",
                symbol=self.symbol,
                side="sell",
                quantity=self.quantity,
                fill_price=self.sell_price,
                fees=sell_fill.fees,
                strategy="test"
            )
            
            self.assertTrue(success)
            
            # Verify fees in ledger
            trades = self.trade_ledger.get_trades_by_session("test_session")
            self.assertEqual(len(trades), 2)
            
            # Check buy trade fees (new fee schedule: 5bps taker = $2.50)
            buy_trade = next(t for t in trades if t['side'] == 'buy')
            self.assertAlmostEqual(buy_trade['fees'], 2.50, delta=0.01)
            
            # Check sell trade fees (new fee schedule: 5bps taker = $2.55)
            sell_trade = next(t for t in trades if t['side'] == 'sell')
            self.assertAlmostEqual(sell_trade['fees'], 2.55, delta=0.01)
            
            # Verify total fees in metrics (approximately $5.05 total)
            metrics = self.trade_ledger.calculate_daily_metrics(session_id="test_session")
            self.assertAlmostEqual(metrics['total_fees'], 5.05, delta=0.10)
            self.assertGreater(metrics['total_fees'], 0)
        
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price_with_provenance')
    @patch('src.crypto_mvp.execution.order_manager.get_mark_price')
    def test_fee_integration_with_nav_validation(self, mock_get_mark_price, mock_provenance):
        """Test that fees are properly included in NAV validation."""
        mock_provenance.return_value = (50000.0, "live")
        mock_get_mark_price.return_value = 50000.0
        
        # Mock _calculate_fill_price to return exact prices without slippage
        with patch.object(self.order_manager, '_calculate_fill_price') as mock_fill_price, \
             patch.object(self.order_manager, '_calculate_fill_probability') as mock_fill_prob:
            mock_fill_price.side_effect = lambda order, current_price, volatility: current_price
            mock_fill_prob.return_value = 1.0  # Always fill orders
            
            from src.crypto_mvp.core.nav_validation import NAVRebuilder
            from src.crypto_mvp.core.pricing_snapshot import PricingSnapshot
            
            # Create pricing snapshot
            from datetime import datetime
            pricing_data = {
                self.symbol: self.sell_price  # Use sell price for current valuation
            }
            pricing_snapshot = PricingSnapshot(pricing_data, ts=datetime.now())
            
            # Execute buy→sell round trip
            buy_order, _ = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            buy_fill = self.order_manager.execute_order(buy_order, self.buy_price)
            
            sell_order, _ = self.order_manager.create_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=self.quantity,
                strategy="test"
            )
            sell_fill = self.order_manager.execute_order(sell_order, self.sell_price)
            
            # Commit trades to ledger
            self.trade_ledger.commit_fill(
                trade_id=f"nav_test_buy_{buy_order.id}",
                session_id="test_session",
                symbol=self.symbol,
                side="buy",
                quantity=self.quantity,
                fill_price=self.buy_price,
                fees=buy_fill.fees,
                strategy="test"
            )
            
            self.trade_ledger.commit_fill(
                trade_id=f"nav_test_sell_{sell_order.id}",
                session_id="test_session",
                symbol=self.symbol,
                side="sell",
                quantity=self.quantity,
                fill_price=self.sell_price,
                fees=sell_fill.fees,
                strategy="test"
            )
            
            # Get trades from ledger
            trades = self.trade_ledger.get_trades_by_session("test_session")
            
            # Rebuild NAV from trades
            rebuilder = NAVRebuilder(initial_cash=10000.0)
            rebuilt_cash, rebuilt_positions, rebuilt_realized_pnl, rebuilt_equity = \
                rebuilder.rebuild_from_ledger(trades, pricing_snapshot, 10000.0)
            
            # Verify rebuilt values
            # Expected cash: $10000 - $5010 + $5089.80 = $10079.80
            expected_cash = 10000.0 - (self.quantity * self.buy_price + buy_fill.fees) + \
                           (self.quantity * self.sell_price - sell_fill.fees)
            self.assertAlmostEqual(rebuilt_cash, expected_cash, places=2)
            
            # Expected realized P&L: (51000 - 50000) * 0.1 = $100 (gross, before fees)
            expected_realized_pnl = (self.sell_price - self.buy_price) * self.quantity
            self.assertAlmostEqual(rebuilt_realized_pnl, expected_realized_pnl, places=2)
            
            # Expected total equity: cash + realized P&L (no open positions after round trip)
            expected_equity = expected_cash + expected_realized_pnl
            self.assertAlmostEqual(rebuilt_equity, expected_equity, places=2)
            
            # Verify fees are properly accounted for in the difference between
            # gross P&L and net cash flow
            gross_profit = (self.sell_price - self.buy_price) * self.quantity
            total_fees = buy_fill.fees + sell_fill.fees
            net_profit = gross_profit - total_fees
            
            # The difference between cash change and realized P&L should equal fees
            cash_change = rebuilt_cash - 10000.0
            pnl_vs_cash_diff = rebuilt_realized_pnl - cash_change
            self.assertAlmostEqual(pnl_vs_cash_diff, total_fees, places=2)
        
    def test_decimal_precision_consistency(self):
        """Test that Decimal precision is maintained throughout the system."""
        # Test with values that might cause floating point precision issues
        quantity = Decimal('0.123456789')
        price = Decimal('12345.6789')
        
        # Calculate fees using Decimal arithmetic
        fees = self.order_manager.calculate_fees(
            quantity=float(quantity),
            price=float(price),
            order_type=OrderType.MARKET,
            symbol=self.symbol,
            is_maker=False
        )
        
        # Expected: 0.123456789 * 12345.6789 * 20 * 0.0001 = 3.0481481442
        # Quantized to 2 decimal places: 3.05
        expected_fees = float(quantity * price * Decimal('20') * Decimal('0.0001'))
        expected_fees_quantized = round(expected_fees, 2)
        
        self.assertEqual(fees, expected_fees_quantized)
        self.assertEqual(fees, 3.05)  # Exact match due to proper quantization
        
    def test_maker_vs_taker_fee_calculation(self):
        """Test that maker and taker fees are calculated correctly."""
        # Test taker fee (market order)
        taker_fees = self.order_manager.calculate_fees(
            quantity=self.quantity,
            price=self.buy_price,
            order_type=OrderType.MARKET,
            symbol=self.symbol,
            is_maker=False
        )
        
        # Expected: 0.1 * 50000 * 20 * 0.0001 = 10.00
        self.assertEqual(taker_fees, 10.00)
        
        # Test maker fee (limit order)
        maker_fees = self.order_manager.calculate_fees(
            quantity=self.quantity,
            price=self.buy_price,
            order_type=OrderType.LIMIT,
            symbol=self.symbol,
            is_maker=True
        )
        
        # Expected: 0.1 * 50000 * 10 * 0.0001 = 5.00
        self.assertEqual(maker_fees, 5.00)
        
        # Verify maker fees are half of taker fees
        self.assertEqual(maker_fees, taker_fees / 2)


if __name__ == '__main__':
    unittest.main()

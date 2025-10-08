"""
Unit tests for NAV validation system.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from crypto_mvp.core.nav_validation import NAVRebuilder, NAVValidator, NAVValidationResult
from crypto_mvp.core.pricing_snapshot import PricingSnapshot


class TestNAVRebuilder:
    """Test NAV rebuilder functionality."""
    
    def test_rebuild_empty_trades(self):
        """Test rebuilding with no trades."""
        rebuilder = NAVRebuilder(initial_cash=10000.0)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.return_value = None
        
        cash, positions, realized_pnl, equity = rebuilder.rebuild_from_ledger(
            trades=[],
            pricing_snapshot=pricing_snapshot,
            initial_cash=10000.0
        )
        
        assert cash == 10000.0
        assert positions == {}
        assert realized_pnl == 0.0
        assert equity == 10000.0
    
    def test_rebuild_single_buy_trade(self):
        """Test rebuilding with a single buy trade."""
        rebuilder = NAVRebuilder(initial_cash=10000.0)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.return_value = 50000.0
        
        trades = [{
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.1,
            'fill_price': 50000.0,
            'fees': 10.0,
            'executed_at': '2025-01-01T00:00:00Z'
        }]
        
        cash, positions, realized_pnl, equity = rebuilder.rebuild_from_ledger(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            initial_cash=10000.0
        )
        
        # Expected: 10000 - (0.1 * 50000) - 10 = 4990
        assert abs(cash - 4990.0) < 0.01
        assert 'BTC/USDT' in positions
        assert abs(positions['BTC/USDT']['quantity'] - 0.1) < 0.001
        assert abs(positions['BTC/USDT']['entry_price'] - 50000.0) < 0.01
        assert realized_pnl == 0.0
        # Equity = cash + position_value = 4990 + (0.1 * 50000) = 9990
        assert abs(equity - 9990.0) < 0.01
    
    def test_rebuild_buy_and_sell_trade(self):
        """Test rebuilding with buy and sell trades."""
        rebuilder = NAVRebuilder(initial_cash=10000.0)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.return_value = 51000.0
        
        trades = [
            {
                'symbol': 'BTC/USDT',
                'side': 'buy',
                'quantity': 0.1,
                'fill_price': 50000.0,
                'fees': 10.0,
                'executed_at': '2025-01-01T00:00:00Z'
            },
            {
                'symbol': 'BTC/USDT',
                'side': 'sell',
                'quantity': 0.05,
                'fill_price': 51000.0,
                'fees': 5.0,
                'executed_at': '2025-01-01T01:00:00Z'
            }
        ]
        
        cash, positions, realized_pnl, equity = rebuilder.rebuild_from_ledger(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            initial_cash=10000.0
        )
        
        # Buy: 10000 - (0.1 * 50000) - 10 = 4990
        # Sell: 4990 + (0.05 * 51000) - 5 = 4990 + 2550 - 5 = 7535
        expected_cash = 7535.0
        assert abs(cash - expected_cash) < 0.01
        
        # Remaining position: 0.1 - 0.05 = 0.05 BTC
        assert 'BTC/USDT' in positions
        assert abs(positions['BTC/USDT']['quantity'] - 0.05) < 0.001
        
        # Realized P&L: (51000 - 50000) * 0.05 = 50
        assert abs(realized_pnl - 50.0) < 0.01
        
        # Equity = cash + position_value = 7535 + (0.05 * 51000) = 10085
        # Note: realized P&L is already reflected in cash balance
        expected_equity = 10085.0
        assert abs(equity - expected_equity) < 0.01
    
    def test_rebuild_multiple_symbols(self):
        """Test rebuilding with multiple symbols."""
        rebuilder = NAVRebuilder(initial_cash=10000.0)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        
        def mock_get_mark_price(symbol, cycle_id=None):
            if symbol == 'BTC/USDT':
                return 50000.0
            elif symbol == 'ETH/USDT':
                return 3000.0
            return None
        
        pricing_snapshot.get_mark_price.side_effect = mock_get_mark_price
        
        trades = [
            {
                'symbol': 'BTC/USDT',
                'side': 'buy',
                'quantity': 0.1,
                'fill_price': 50000.0,
                'fees': 10.0,
                'executed_at': '2025-01-01T00:00:00Z'
            },
            {
                'symbol': 'ETH/USDT',
                'side': 'buy',
                'quantity': 1.0,
                'fill_price': 3000.0,
                'fees': 3.0,
                'executed_at': '2025-01-01T01:00:00Z'
            }
        ]
        
        cash, positions, realized_pnl, equity = rebuilder.rebuild_from_ledger(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            initial_cash=10000.0
        )
        
        # Expected cash: 10000 - (0.1 * 50000) - 10 - (1.0 * 3000) - 3 = 1987
        expected_cash = 1987.0
        assert abs(cash - expected_cash) < 0.01
        
        # Should have both positions
        assert 'BTC/USDT' in positions
        assert 'ETH/USDT' in positions
        assert abs(positions['BTC/USDT']['quantity'] - 0.1) < 0.001
        assert abs(positions['ETH/USDT']['quantity'] - 1.0) < 0.001
        
        # Equity = cash + BTC_value + ETH_value = 1987 + 5000 + 3000 = 9987
        expected_equity = 9987.0
        assert abs(equity - expected_equity) < 0.01


class TestNAVValidator:
    """Test NAV validator functionality."""
    
    def test_validate_nav_pass(self):
        """Test NAV validation that passes."""
        validator = NAVValidator(tolerance=0.01)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.return_value = 50000.0
        
        trades = [{
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.1,
            'fill_price': 50000.0,
            'fees': 10.0,
            'executed_at': '2025-01-01T00:00:00Z'
        }]
        
        # Computed equity should match rebuilt equity
        computed_equity = 9990.0  # 4990 cash + 5000 position value
        
        result = validator.validate_nav(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            computed_equity=computed_equity,
            initial_cash=10000.0
        )
        
        assert result.is_valid
        assert result.difference <= validator.tolerance
        assert result.error_message is None
    
    def test_validate_nav_fail(self):
        """Test NAV validation that fails."""
        validator = NAVValidator(tolerance=0.01)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.return_value = 50000.0
        
        trades = [{
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.1,
            'fill_price': 50000.0,
            'fees': 10.0,
            'executed_at': '2025-01-01T00:00:00Z'
        }]
        
        # Computed equity that doesn't match rebuilt equity
        computed_equity = 10000.0  # Should be ~9990
        
        result = validator.validate_nav(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            computed_equity=computed_equity,
            initial_cash=10000.0
        )
        
        assert not result.is_valid
        assert result.difference > validator.tolerance
        assert result.error_message is not None
        assert "NAV validation failed" in result.error_message
    
    def test_validate_nav_with_error(self):
        """Test NAV validation with error."""
        validator = NAVValidator(tolerance=0.01)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        pricing_snapshot.get_mark_price.side_effect = Exception("Price error")
        
        trades = [{
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.1,
            'fill_price': 50000.0,
            'fees': 10.0,
            'executed_at': '2025-01-01T00:00:00Z'
        }]
        
        result = validator.validate_nav(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            computed_equity=10000.0,
            initial_cash=10000.0
        )
        
        assert not result.is_valid
        assert result.error_message is not None
        assert "NAV validation error" in result.error_message


class TestRandomTradeStreamPrecision:
    """Test NAV validation with random trade streams to ensure precision."""
    
    def test_random_trade_stream_precision(self):
        """Test that random trade streams reproduce NAV exactly with frozen prices."""
        import random
        
        # Set up random seed for reproducibility
        random.seed(42)
        
        validator = NAVValidator(tolerance=0.01)
        pricing_snapshot = Mock(spec=PricingSnapshot)
        
        # Mock prices that won't change during the test
        def mock_get_mark_price(symbol, cycle_id=None):
            if symbol == 'BTC/USDT':
                return 50000.0
            elif symbol == 'ETH/USDT':
                return 3000.0
            return None
        
        pricing_snapshot.get_mark_price.side_effect = mock_get_mark_price
        
        # Generate random trades
        trades = []
        initial_cash = 100000.0
        current_cash = initial_cash
        
        # Simulate 100 random trades
        for i in range(100):
            symbol = random.choice(['BTC/USDT', 'ETH/USDT'])
            side = random.choice(['buy', 'sell'])
            
            if symbol == 'BTC/USDT':
                price = 50000.0
                max_quantity = 0.1
            else:
                price = 3000.0
                max_quantity = 10.0
            
            quantity = random.uniform(0.001, max_quantity)
            fees = quantity * price * 0.001  # 0.1% fee
            
            # Check if we have enough cash for buy orders
            if side == 'buy':
                cost = quantity * price + fees
                if cost > current_cash:
                    continue  # Skip this trade
                current_cash -= cost
            else:
                # For sell orders, we need to have the position
                # This is simplified - in reality we'd track positions
                current_cash += quantity * price - fees
            
            trades.append({
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'fill_price': price,
                'fees': fees,
                'executed_at': f'2025-01-01T{i:02d}:00:00Z'
            })
        
        # Calculate expected equity by rebuilding
        rebuilder = NAVRebuilder(initial_cash=initial_cash)
        rebuilt_cash, rebuilt_positions, rebuilt_realized_pnl, rebuilt_equity = \
            rebuilder.rebuild_from_ledger(trades, pricing_snapshot, initial_cash)
        
        # Validate that rebuilt equity matches itself (should be exact)
        result = validator.validate_nav(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            computed_equity=rebuilt_equity,  # Use rebuilt equity as "computed"
            initial_cash=initial_cash
        )
        
        # Should pass with exact match
        assert result.is_valid
        assert result.difference < 0.001  # Should be very close to zero
        assert result.rebuilt_equity == pytest.approx(result.computed_equity, abs=0.001)

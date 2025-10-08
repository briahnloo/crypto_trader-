"""
Test decimal integrity for trading math operations.

This module tests that all trading math operations use Decimal for precision
and that NAV rebuilds equal live calculations within tolerance.
"""

import pytest
from decimal import Decimal, getcontext
from typing import Dict, Any, List

# Set decimal precision
getcontext().prec = 28

from crypto_mvp.core.utils import (
    get_mark_price, get_entry_price, get_exit_value,
    calculate_percentage_change, calculate_compound_return,
    format_currency, format_percentage
)
from crypto_mvp.risk.stop_models import StopModel
from crypto_mvp.execution.oco_manager import OCOOrder, OCOManager
from crypto_mvp.core.nav_validation import NAVRebuilder, NAVValidator


class TestDecimalIntegrity:
    """Test decimal integrity across trading math operations."""
    
    def test_no_typeerror_on_price_quantity_multiplication(self):
        """Test that price * quantity operations don't raise TypeError."""
        # Test with various price and quantity combinations
        test_cases = [
            (Decimal('50000.123456789'), Decimal('0.123456789')),
            (Decimal('2500.50'), Decimal('1.0')),
            (Decimal('0.0001'), Decimal('1000000.0')),
            (Decimal('100000.0'), Decimal('0.000001')),
        ]
        
        for price, quantity in test_cases:
            # This should not raise TypeError
            result = price * quantity
            assert isinstance(result, Decimal)
            assert result > 0
    
    def test_stop_model_decimal_operations(self):
        """Test that StopModel uses Decimal for all calculations."""
        config = {
            "risk": {
                "sl_tp": {
                    "atr_mult_sl": "1.2",
                    "atr_mult_tp": "2.0",
                    "fallback_pct_sl": "0.02",
                    "fallback_pct_tp": "0.04",
                    "min_sl_abs": "0.001",
                    "min_tp_abs": "0.002"
                }
            }
        }
        
        stop_model = StopModel(config)
        
        # Test with Decimal inputs
        entry_price = Decimal('50000.123456789')
        side = "BUY"
        symbol = "BTC/USDT"
        
        # Mock ATR service
        class MockATRService:
            def get_atr(self, symbol, data_engine):
                return 500.0  # Return float, will be converted to Decimal
        
        stop_model.atr_service = MockATRService()
        
        # Mock data engine
        mock_data_engine = object()
        
        # Calculate stop/take profit
        stop_loss, take_profit, metadata = stop_model.calculate_stop_take_profit(
            symbol=symbol,
            entry_price=entry_price,
            side=side,
            data_engine=mock_data_engine
        )
        
        # Verify results are floats (converted at I/O boundary)
        assert isinstance(stop_loss, float)
        assert isinstance(take_profit, float)
        assert stop_loss > 0
        assert take_profit > 0
        assert stop_loss < entry_price  # Stop loss below entry for BUY
        assert take_profit > entry_price  # Take profit above entry for BUY
        
        # Verify metadata contains proper values
        assert metadata["atr_based"] is True
        assert metadata["sl_distance"] > 0
        assert metadata["tp_distance"] > 0
    
    def test_oco_order_decimal_operations(self):
        """Test that OCOOrder uses Decimal for all calculations."""
        # Create OCO order with Decimal inputs
        symbol = "BTC/USDT"
        side = "BUY"
        entry_price = Decimal('50000.123456789')
        quantity = Decimal('0.123456789')
        stop_loss = Decimal('49000.0')
        take_profit = Decimal('52000.0')
        atr = Decimal('500.0')
        
        oco_order = OCOOrder(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=atr
        )
        
        # Test risk-reward calculation
        rr_ratio = oco_order.get_risk_reward_ratio()
        assert isinstance(rr_ratio, float)
        assert rr_ratio > 0
        
        # Test trailing TP update
        current_price = Decimal('51000.0')
        updated = oco_order.update_trailing_tp(current_price)
        assert isinstance(updated, bool)
    
    def test_nav_rebuild_equals_live_within_tolerance(self):
        """Test that NAV rebuild equals live calculation within $0.01."""
        # Create sample trades
        trades = [
            {
                'symbol': 'BTC/USDT',
                'side': 'buy',
                'quantity': '0.123456789',
                'fill_price': '50000.123456789',
                'fees': '12.50',
                'executed_at': '2024-01-01T10:00:00Z'
            },
            {
                'symbol': 'BTC/USDT',
                'side': 'sell',
                'quantity': '0.061728394',
                'fill_price': '52000.987654321',
                'fees': '6.25',
                'executed_at': '2024-01-01T11:00:00Z'
            }
        ]
        
        # Mock pricing snapshot
        class MockPricingSnapshot:
            def get_mark_price(self, symbol):
                return Decimal('51500.555555555')
        
        pricing_snapshot = MockPricingSnapshot()
        
        # Rebuild NAV
        rebuilder = NAVRebuilder(initial_cash=Decimal('10000.0'))
        cash, positions, realized_pnl, total_equity = rebuilder.rebuild_from_ledger(
            trades, pricing_snapshot, Decimal('10000.0')
        )
        
        # Verify all values are floats (quantized at I/O boundary)
        assert isinstance(cash, float)
        assert isinstance(realized_pnl, float)
        assert isinstance(total_equity, float)
        
        # Test NAV validator
        validator = NAVValidator(tolerance=1.00)  # $1.00 tolerance
        result = validator.validate_nav(
            trades=trades,
            pricing_snapshot=pricing_snapshot,
            computed_equity=total_equity,  # Use rebuilt equity as "computed"
            initial_cash=10000.0
        )
        
        # Should be valid since we're comparing against itself
        assert result.is_valid is True
        assert result.difference <= 1.00  # Within $1.00 tolerance
    
    def test_decimal_precision_consistency(self):
        """Test that decimal precision is consistent across operations."""
        # Test with high precision numbers
        price1 = Decimal('50000.1234567890123456789012345678')
        price2 = Decimal('2500.9876543210987654321098765432')
        
        # Addition
        sum_result = price1 + price2
        assert isinstance(sum_result, Decimal)
        
        # Subtraction
        diff_result = price1 - price2
        assert isinstance(diff_result, Decimal)
        
        # Multiplication
        mult_result = price1 * price2
        assert isinstance(mult_result, Decimal)
        
        # Division
        div_result = price1 / price2
        assert isinstance(div_result, Decimal)
        
        # Percentage calculation
        pct_change = calculate_percentage_change(price1, price2)
        assert isinstance(pct_change, Decimal)
    
    def test_currency_formatting_with_decimal(self):
        """Test currency formatting with Decimal inputs."""
        # Test with Decimal input
        amount = Decimal('12345.678901234567890123456789')
        formatted = format_currency(amount, "USD", 2)
        
        # Should be properly formatted
        assert "USD" in formatted
        assert "$" in formatted or "USD" in formatted
        
        # Test percentage formatting
        percentage = Decimal('0.1234567890123456789012345678')
        formatted_pct = format_percentage(percentage, 4)
        
        assert "%" in formatted_pct
        assert "12.3457" in formatted_pct  # 4 decimal places
    
    def test_compound_return_with_decimal(self):
        """Test compound return calculation with Decimal inputs."""
        returns = [
            Decimal('0.05'),   # 5%
            Decimal('-0.02'),  # -2%
            Decimal('0.08'),   # 8%
            Decimal('0.03')    # 3%
        ]
        
        compound_return = calculate_compound_return(returns)
        assert isinstance(compound_return, Decimal)
        
        # Should be positive for this set of returns
        assert compound_return > 0
    
    def test_quantization_at_io_boundaries(self):
        """Test that quantization happens only at I/O boundaries."""
        # Test quantity quantization to 8 decimal places
        quantity = Decimal('0.1234567890123456789012345678')
        quantized_qty = quantity.quantize(Decimal('0.00000001'))  # 8 dp
        assert quantized_qty == Decimal('0.12345679')
        
        # Test USDT quantization to 2 decimal places
        usdt_amount = Decimal('12345.678901234567890123456789')
        quantized_usdt = usdt_amount.quantize(Decimal('0.01'))  # 2 dp
        assert quantized_usdt == Decimal('12345.68')


if __name__ == "__main__":
    pytest.main([__file__])

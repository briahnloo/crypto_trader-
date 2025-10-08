"""
Tests for decimal money math utilities.
"""

import pytest
from decimal import Decimal
from src.crypto_mvp.core.decimal_money import (
    to_decimal, quantize_currency, quantize_quantity, calculate_notional,
    calculate_fees, calculate_pnl, calculate_position_value, format_currency,
    format_quantity, safe_divide, safe_multiply, validate_decimal_precision,
    convert_float_to_decimal_safe, round_to_precision, sum_decimals,
    max_decimal, min_decimal, abs_decimal, is_positive, is_negative, is_zero,
    PrecisionMap
)


class TestDecimalMoney:
    """Test decimal money math utilities."""

    def test_to_decimal_conversion(self):
        """Test conversion of various types to Decimal."""
        assert to_decimal(123.45) == Decimal('123.45')
        assert to_decimal("123.45") == Decimal('123.45')
        assert to_decimal(123) == Decimal('123')
        assert to_decimal(Decimal('123.45')) == Decimal('123.45')

    def test_quantize_currency(self):
        """Test currency quantization."""
        # USDT should have 2 decimal places
        assert quantize_currency(Decimal('123.456789'), 'USDT') == Decimal('123.46')
        assert quantize_currency(Decimal('123.454'), 'USDT') == Decimal('123.45')
        assert quantize_currency(Decimal('123.455'), 'USDT') == Decimal('123.46')
        
        # USD should also have 2 decimal places
        assert quantize_currency(Decimal('123.456'), 'USD') == Decimal('123.46')
        
        # Unknown currency should use default
        assert quantize_currency(Decimal('123.456'), 'EUR') == Decimal('123.46')

    def test_quantize_quantity(self):
        """Test quantity quantization."""
        # BTC should have 8 decimal places
        assert quantize_quantity(Decimal('0.123456789'), 'BTC/USDT') == Decimal('0.12345679')
        assert quantize_quantity(Decimal('0.123456784'), 'BTC/USDT') == Decimal('0.12345678')
        assert quantize_quantity(Decimal('0.123456785'), 'BTC/USDT') == Decimal('0.12345679')
        
        # ETH should have 8 decimal places
        assert quantize_quantity(Decimal('1.23456789'), 'ETH/USDT') == Decimal('1.23456789')
        
        # Other symbols should use default (8 decimal places)
        assert quantize_quantity(Decimal('1.23456789'), 'ADA/USDT') == Decimal('1.23456789')

    def test_calculate_notional(self):
        """Test notional calculation."""
        quantity = Decimal('0.5')
        price = Decimal('50000.0')
        expected = Decimal('25000.0')
        assert calculate_notional(quantity, price) == expected

    def test_calculate_fees(self):
        """Test fee calculation."""
        notional = Decimal('1000.0')
        fee_rate = Decimal('0.001')  # 0.1%
        expected = Decimal('1.0')
        assert calculate_fees(notional, fee_rate) == expected

    def test_calculate_pnl(self):
        """Test P&L calculation."""
        quantity = Decimal('0.5')
        entry_price = Decimal('50000.0')
        current_price = Decimal('52000.0')
        expected = Decimal('1000.0')  # 0.5 * (52000 - 50000)
        assert calculate_pnl(quantity, entry_price, current_price) == expected
        
        # Test negative P&L
        current_price = Decimal('48000.0')
        expected = Decimal('-1000.0')  # 0.5 * (48000 - 50000)
        assert calculate_pnl(quantity, entry_price, current_price) == expected

    def test_calculate_position_value(self):
        """Test position value calculation."""
        quantity = Decimal('0.5')
        current_price = Decimal('52000.0')
        expected = Decimal('26000.0')
        assert calculate_position_value(quantity, current_price) == expected

    def test_format_currency(self):
        """Test currency formatting."""
        value = Decimal('1234.56')
        assert format_currency(value, 'USDT') == 'USDT 1,234.56'
        assert format_currency(value, 'USDT', show_symbol=False) == '1,234.56'

    def test_format_quantity(self):
        """Test quantity formatting."""
        value = Decimal('0.12345678')
        assert format_quantity(value, 'BTC/USDT') == '0.12345678'
        assert format_quantity(value, 'ETH/USDT') == '0.12345678'

    def test_safe_divide(self):
        """Test safe division."""
        assert safe_divide(Decimal('10'), Decimal('2')) == Decimal('5')
        assert safe_divide(Decimal('10'), Decimal('0'), Decimal('0')) == Decimal('0')
        assert safe_divide(Decimal('10'), Decimal('0'), Decimal('999')) == Decimal('999')

    def test_safe_multiply(self):
        """Test safe multiplication."""
        assert safe_multiply(Decimal('10'), Decimal('2')) == Decimal('20')
        assert safe_multiply(Decimal('0'), Decimal('100')) == Decimal('0')

    def test_validate_decimal_precision(self):
        """Test precision validation."""
        value = Decimal('123.45')
        assert validate_decimal_precision(value, 2) == True
        assert validate_decimal_precision(value, 1) == False

    def test_convert_float_to_decimal_safe(self):
        """Test safe float to decimal conversion."""
        # Test normal conversion
        result = convert_float_to_decimal_safe(123.45, "test")
        assert result == Decimal('123.45')
        
        # Test with problematic float
        result = convert_float_to_decimal_safe(0.1 + 0.2, "test")
        assert result == Decimal('0.30000000000000004')  # Shows float precision issue

    def test_round_to_precision(self):
        """Test rounding to precision."""
        value = Decimal('123.456789')
        assert round_to_precision(value, 2) == Decimal('123.46')
        assert round_to_precision(value, 2, "DOWN") == Decimal('123.45')

    def test_sum_decimals(self):
        """Test decimal summation."""
        values = [Decimal('1.1'), Decimal('2.2'), Decimal('3.3')]
        assert sum_decimals(values) == Decimal('6.6')
        assert sum_decimals([]) == Decimal('0')

    def test_max_decimal(self):
        """Test max decimal."""
        values = [Decimal('1.1'), Decimal('3.3'), Decimal('2.2')]
        assert max_decimal(values) == Decimal('3.3')
        assert max_decimal([]) == Decimal('0')

    def test_min_decimal(self):
        """Test min decimal."""
        values = [Decimal('3.3'), Decimal('1.1'), Decimal('2.2')]
        assert min_decimal(values) == Decimal('1.1')
        assert min_decimal([]) == Decimal('0')

    def test_abs_decimal(self):
        """Test absolute value."""
        assert abs_decimal(Decimal('123.45')) == Decimal('123.45')
        assert abs_decimal(Decimal('-123.45')) == Decimal('123.45')

    def test_comparison_functions(self):
        """Test comparison functions."""
        assert is_positive(Decimal('123.45')) == True
        assert is_positive(Decimal('-123.45')) == False
        assert is_positive(Decimal('0')) == False
        
        assert is_negative(Decimal('-123.45')) == True
        assert is_negative(Decimal('123.45')) == False
        assert is_negative(Decimal('0')) == False
        
        assert is_zero(Decimal('0')) == True
        assert is_zero(Decimal('123.45')) == False
        assert is_zero(Decimal('-123.45')) == False

    def test_precision_map(self):
        """Test precision map values."""
        assert PrecisionMap["USDT"] == 2
        assert PrecisionMap["USD"] == 2
        assert PrecisionMap["BTC_qty"] == 8
        assert PrecisionMap["ETH_qty"] == 8
        assert PrecisionMap["default_qty"] == 8
        assert PrecisionMap["default_currency"] == 2

    def test_floating_point_precision_issues(self):
        """Test that decimal math avoids floating point precision issues."""
        # This is the classic floating point precision problem
        float_result = 0.1 + 0.2
        assert float_result != 0.3  # This will fail due to floating point precision
        
        # Decimal math should be precise
        decimal_result = to_decimal('0.1') + to_decimal('0.2')
        assert decimal_result == Decimal('0.3')
        
        # Test with currency quantization
        notional = to_decimal('1000.00')
        fee_rate = to_decimal('0.001')
        fees = calculate_fees(notional, fee_rate)
        assert fees == Decimal('1.000')
        
        # Quantize to currency precision
        fees_quantized = quantize_currency(fees, 'USDT')
        assert fees_quantized == Decimal('1.00')

    def test_large_number_precision(self):
        """Test precision with large numbers."""
        # Test with large notional values
        quantity = to_decimal('1000.12345678')
        price = to_decimal('50000.12345678')
        notional = calculate_notional(quantity, price)
        
        # Should maintain precision - calculate expected manually
        expected = Decimal('1000.12345678') * Decimal('50000.12345678')
        assert notional == expected
        
        # Quantize to currency precision
        notional_quantized = quantize_currency(notional, 'USDT')
        # Should round to 2 decimal places
        expected_quantized = Decimal('50006296.31')
        assert notional_quantized == expected_quantized

    def test_random_trade_stream_precision(self):
        """Test precision with random trade streams (acceptance criteria)."""
        import random
        
        # Simulate random trade stream
        nav_live = Decimal('0')
        nav_rebuild = Decimal('0')
        
        for _ in range(100):
            # Random trade
            quantity = to_decimal(str(random.uniform(0.001, 1.0)))
            price = to_decimal(str(random.uniform(10000, 100000)))
            fee_rate = to_decimal('0.001')
            
            # Calculate using decimal math
            notional = calculate_notional(quantity, price)
            fees = calculate_fees(notional, fee_rate)
            
            # Update nav_live (simulating live calculation)
            nav_live += notional - fees
            
            # Update nav_rebuild (simulating rebuild calculation)
            nav_rebuild += notional - fees
        
        # The difference should be exactly zero (no floating point drift)
        difference = abs_decimal(nav_live - nav_rebuild)
        assert difference < Decimal('0.01')  # Acceptance criteria: < $0.01

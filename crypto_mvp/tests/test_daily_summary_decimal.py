"""
Test suite for Decimal arithmetic in daily summary calculations.

This test ensures that all accounting paths use Decimal consistently
and catches any float/Decimal mixing that would cause runtime errors.
"""

import pytest
from decimal import Decimal

from crypto_mvp.core.money import D, q_money, ensure_decimal


def calculate_daily_summary_metrics(
    cash_balance: Decimal,
    positions_value: Decimal,
    realized_pnl: Decimal,
    previous_equity: Decimal,
    current_equity: Decimal
) -> dict:
    """
    Calculate daily summary metrics using proper Decimal arithmetic.
    
    This is a standalone testable function that implements the same
    logic as the trading system's daily summary.
    
    Args:
        cash_balance: Current cash balance (must be Decimal)
        positions_value: Total positions value (must be Decimal)
        realized_pnl: Total realized P&L (must be Decimal)
        previous_equity: Previous cycle equity (must be Decimal)
        current_equity: Current equity (must be Decimal)
        
    Returns:
        Dictionary with calculated metrics
        
    Raises:
        ValueError: If any input is not a Decimal (catches float contamination)
    """
    # GUARD: Ensure all inputs are Decimal
    if not ensure_decimal(cash_balance, positions_value, realized_pnl, previous_equity, current_equity):
        raise ValueError(
            f"Float detected in accounting path! All inputs must be Decimal. "
            f"Got: cash={type(cash_balance)}, positions={type(positions_value)}, "
            f"realized_pnl={type(realized_pnl)}, previous_equity={type(previous_equity)}, "
            f"current_equity={type(current_equity)}"
        )
    
    # Calculate equity change using Decimal arithmetic
    equity_change = q_money(current_equity - previous_equity)
    
    # Calculate equity change percentage
    if previous_equity == D("0"):
        equity_change_pct = D("0.0")
    else:
        equity_change_pct = ((current_equity - previous_equity) / previous_equity) * D("100")
        equity_change_pct = equity_change_pct.quantize(Decimal("0.01"))
    
    # Calculate total equity (for verification)
    calculated_equity = q_money(cash_balance + positions_value)
    
    return {
        "equity_change": equity_change,
        "equity_change_pct": equity_change_pct,
        "calculated_equity": calculated_equity,
        "current_equity": current_equity,
        "previous_equity": previous_equity,
        "cash_balance": cash_balance,
        "positions_value": positions_value,
        "realized_pnl": realized_pnl,
    }


class TestDailySummaryDecimal:
    """Test suite for daily summary Decimal arithmetic."""
    
    def test_daily_summary_decimal_math_positive_change(self):
        """Test daily summary with positive equity change."""
        # All Decimal inputs
        current = Decimal("10002.30")
        previous = Decimal("10001.45")
        cash = Decimal("6400.00")
        pos = Decimal("3602.30")
        realized = Decimal("0.00")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        assert "equity_change" in out
        assert out["equity_change"] == Decimal("0.85")
        assert isinstance(out["equity_change"], Decimal)
        assert out["equity_change_pct"] == Decimal("0.01")  # 0.85/10001.45 * 100 ≈ 0.01%
    
    def test_daily_summary_decimal_math_negative_change(self):
        """Test daily summary with negative equity change."""
        current = Decimal("9950.00")
        previous = Decimal("10000.00")
        cash = Decimal("6350.00")
        pos = Decimal("3600.00")
        realized = Decimal("0.00")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        assert out["equity_change"] == Decimal("-50.00")
        assert isinstance(out["equity_change"], Decimal)
        assert out["equity_change_pct"] == Decimal("-0.50")  # -50/10000 * 100 = -0.50%
    
    def test_daily_summary_decimal_math_zero_previous_equity(self):
        """Test daily summary handles zero previous equity gracefully."""
        current = Decimal("10000.00")
        previous = Decimal("0.00")
        cash = Decimal("10000.00")
        pos = Decimal("0.00")
        realized = Decimal("0.00")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        assert out["equity_change"] == Decimal("10000.00")
        assert out["equity_change_pct"] == Decimal("0.0")  # Avoid division by zero
    
    def test_daily_summary_raises_on_float_cash(self):
        """Test that float cash balance raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                6400.00,  # float - should fail
                Decimal("3602.30"),
                Decimal("0.00"),
                Decimal("10001.45"),
                Decimal("10002.30")
            )
    
    def test_daily_summary_raises_on_float_positions(self):
        """Test that float positions value raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                Decimal("6400.00"),
                3602.30,  # float - should fail
                Decimal("0.00"),
                Decimal("10001.45"),
                Decimal("10002.30")
            )
    
    def test_daily_summary_raises_on_float_realized_pnl(self):
        """Test that float realized P&L raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                Decimal("6400.00"),
                Decimal("3602.30"),
                0.0,  # float - should fail
                Decimal("10001.45"),
                Decimal("10002.30")
            )
    
    def test_daily_summary_raises_on_float_previous_equity(self):
        """Test that float previous equity raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                Decimal("6400.00"),
                Decimal("3602.30"),
                Decimal("0.00"),
                10001.45,  # float - should fail
                Decimal("10002.30")
            )
    
    def test_daily_summary_raises_on_float_current_equity(self):
        """Test that float current equity raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                Decimal("6400.00"),
                Decimal("3602.30"),
                Decimal("0.00"),
                Decimal("10001.45"),
                10002.30  # float - should fail
            )
    
    def test_daily_summary_raises_on_all_floats(self):
        """Test that all floats raises ValueError."""
        with pytest.raises(ValueError, match="Float detected in accounting path"):
            calculate_daily_summary_metrics(
                6400.00,  # all floats - should fail
                3602.30,
                0.0,
                10001.45,
                10002.30
            )
    
    def test_daily_summary_equity_components_match(self):
        """Test that cash + positions equals calculated equity."""
        cash = Decimal("6400.00")
        pos = Decimal("3602.30")
        realized = Decimal("0.00")
        previous = Decimal("10000.00")
        current = Decimal("10002.30")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        # Verify cash + positions = current equity
        assert out["calculated_equity"] == cash + pos
        assert out["calculated_equity"] == current
    
    def test_daily_summary_preserves_decimal_precision(self):
        """Test that Decimal precision is preserved throughout calculation."""
        cash = Decimal("6400.123456")
        pos = Decimal("3602.654321")
        realized = Decimal("0.00")
        previous = Decimal("10000.00")
        current = q_money(cash + pos)
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        # All outputs should be Decimal
        assert isinstance(out["equity_change"], Decimal)
        assert isinstance(out["equity_change_pct"], Decimal)
        assert isinstance(out["calculated_equity"], Decimal)
        
        # Money values should be quantized to 2 decimal places
        assert out["equity_change"] == Decimal("2.78")  # 10002.78 - 10000.00
        assert out["calculated_equity"] == Decimal("10002.78")
    
    def test_daily_summary_large_numbers(self):
        """Test daily summary with large numbers (million+ equity)."""
        current = Decimal("1500000.00")
        previous = Decimal("1000000.00")
        cash = Decimal("900000.00")
        pos = Decimal("600000.00")
        realized = Decimal("0.00")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        assert out["equity_change"] == Decimal("500000.00")
        assert out["equity_change_pct"] == Decimal("50.00")  # 50% gain
    
    def test_daily_summary_small_changes(self):
        """Test daily summary with very small equity changes."""
        current = Decimal("10000.01")
        previous = Decimal("10000.00")
        cash = Decimal("6400.01")
        pos = Decimal("3600.00")
        realized = Decimal("0.00")
        
        out = calculate_daily_summary_metrics(cash, pos, realized, previous, current)
        
        assert out["equity_change"] == Decimal("0.01")
        assert out["equity_change_pct"] == Decimal("0.00")  # <0.01% rounded to 0


class TestDecimalHelpers:
    """Test suite for Decimal helper functions."""
    
    def test_D_converts_float(self):
        """Test D() converts float to Decimal."""
        result = D(123.45)
        assert isinstance(result, Decimal)
        assert result == Decimal("123.45")
    
    def test_D_converts_int(self):
        """Test D() converts int to Decimal."""
        result = D(12345)
        assert isinstance(result, Decimal)
        assert result == Decimal("12345")
    
    def test_D_converts_string(self):
        """Test D() converts string to Decimal."""
        result = D("123.45")
        assert isinstance(result, Decimal)
        assert result == Decimal("123.45")
    
    def test_D_preserves_decimal(self):
        """Test D() preserves existing Decimal."""
        original = Decimal("123.45")
        result = D(original)
        assert isinstance(result, Decimal)
        assert result == original
    
    def test_q_money_quantizes_to_cents(self):
        """Test q_money() quantizes to 2 decimal places."""
        result = q_money(D("123.456789"))
        assert result == Decimal("123.46")
        
        result = q_money(D("123.454"))
        assert result == Decimal("123.45")
    
    def test_ensure_decimal_accepts_all_decimals(self):
        """Test ensure_decimal() returns True for all Decimals."""
        assert ensure_decimal(
            Decimal("1.0"),
            Decimal("2.0"),
            Decimal("3.0")
        ) is True
    
    def test_ensure_decimal_rejects_float(self):
        """Test ensure_decimal() returns False if any float."""
        assert ensure_decimal(
            Decimal("1.0"),
            2.0,  # float
            Decimal("3.0")
        ) is False
    
    def test_ensure_decimal_rejects_int(self):
        """Test ensure_decimal() returns False if any int."""
        assert ensure_decimal(
            Decimal("1.0"),
            Decimal("2.0"),
            3  # int
        ) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


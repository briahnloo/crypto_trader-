"""
Tests for bracket order and exit strategy integrity with Decimal precision.

This module tests:
- 3-rung TP ladder functionality
- Chandelier exit calculations
- Time-based exit strategies
- Monotonic level verification
- BracketSpecError validation
- Decimal precision consistency
"""

import pytest
from decimal import Decimal, getcontext, ROUND_HALF_UP
from datetime import datetime, timedelta
from unittest.mock import Mock

# Set global decimal precision for tests
getcontext().prec = 28

# Import the modules we're testing
from execution.brackets import (
    BracketOrder, BracketManager, BracketSpecError, create_bracket_order
)
from risk.exits import (
    ChandelierExit, TimeExit, ExitManager, ExitSpecError,
    create_chandelier_exit, create_time_exit
)


class TestBracketOrderIntegrity:
    """Test bracket order functionality with Decimal precision."""
    
    def test_long_bracket_validation(self):
        """Test long bracket validation: stop < entry < take_profit."""
        # Valid long bracket
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),  # stop < entry
            take_profit_levels=[Decimal('51000'), Decimal('52000'), Decimal('53000')],  # entry < tp
            strategy="test"
        )
        
        assert bracket.side == "BUY"
        assert bracket.entry_price == Decimal('50000')
        assert bracket.stop_loss == Decimal('49000')
        assert len(bracket.take_profit_levels) == 3
    
    def test_short_bracket_validation(self):
        """Test short bracket validation: take_profit < entry < stop."""
        # Valid short bracket
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('51000'),  # entry < stop
            take_profit_levels=[Decimal('49000'), Decimal('48000'), Decimal('47000')],  # tp < entry
            strategy="test"
        )
        
        assert bracket.side == "SELL"
        assert bracket.entry_price == Decimal('50000')
        assert bracket.stop_loss == Decimal('51000')
        assert len(bracket.take_profit_levels) == 3
    
    def test_long_bracket_invalid_stop_loss(self):
        """Test long bracket with invalid stop loss."""
        with pytest.raises(BracketSpecError, match="stop_loss.*must be < entry_price"):
            BracketOrder(
                symbol="BTC/USDT",
                side="BUY",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                stop_loss=Decimal('51000'),  # Invalid: stop > entry for long
                take_profit_levels=[Decimal('52000')],
                strategy="test"
            )
    
    def test_short_bracket_invalid_stop_loss(self):
        """Test short bracket with invalid stop loss."""
        with pytest.raises(BracketSpecError, match="entry_price.*must be < stop_loss"):
            BracketOrder(
                symbol="BTC/USDT",
                side="SELL",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                stop_loss=Decimal('49000'),  # Invalid: stop < entry for short
                take_profit_levels=[Decimal('48000')],
                strategy="test"
            )
    
    def test_long_bracket_invalid_take_profit(self):
        """Test long bracket with invalid take profit."""
        with pytest.raises(BracketSpecError, match="entry_price.*must be < take_profit"):
            BracketOrder(
                symbol="BTC/USDT",
                side="BUY",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                stop_loss=Decimal('49000'),
                take_profit_levels=[Decimal('49000')],  # Invalid: tp <= entry for long
                strategy="test"
            )
    
    def test_short_bracket_invalid_take_profit(self):
        """Test short bracket with invalid take profit."""
        with pytest.raises(BracketSpecError, match="take_profit.*must be < entry_price"):
            BracketOrder(
                symbol="BTC/USDT",
                side="SELL",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                stop_loss=Decimal('51000'),
                take_profit_levels=[Decimal('51000')],  # Invalid: tp >= entry for short
                strategy="test"
            )
    
    def test_monotonic_tp_levels_long(self):
        """Test monotonic TP levels for long positions."""
        # Valid increasing TP levels
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            take_profit_levels=[Decimal('51000'), Decimal('52000'), Decimal('53000')],
            strategy="test"
        )
        
        assert bracket.take_profit_levels[0] < bracket.take_profit_levels[1]
        assert bracket.take_profit_levels[1] < bracket.take_profit_levels[2]
    
    def test_monotonic_tp_levels_short(self):
        """Test monotonic TP levels for short positions."""
        # Valid decreasing TP levels
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('51000'),
            take_profit_levels=[Decimal('49000'), Decimal('48000'), Decimal('47000')],
            strategy="test"
        )
        
        assert bracket.take_profit_levels[0] > bracket.take_profit_levels[1]
        assert bracket.take_profit_levels[1] > bracket.take_profit_levels[2]
    
    def test_non_monotonic_tp_levels_long(self):
        """Test non-monotonic TP levels for long positions are automatically sorted."""
        # The bracket order automatically sorts TP levels, so this should succeed
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            take_profit_levels=[Decimal('52000'), Decimal('51000'), Decimal('53000')],  # Not increasing initially
            strategy="test"
        )
        
        # After sorting, levels should be increasing
        assert bracket.take_profit_levels[0] < bracket.take_profit_levels[1]
        assert bracket.take_profit_levels[1] < bracket.take_profit_levels[2]
        assert bracket.take_profit_levels == [Decimal('51000'), Decimal('52000'), Decimal('53000')]
    
    def test_non_monotonic_tp_levels_short(self):
        """Test non-monotonic TP levels for short positions are automatically sorted."""
        # The bracket order automatically sorts TP levels, so this should succeed
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('51000'),
            take_profit_levels=[Decimal('48000'), Decimal('49000'), Decimal('47000')],  # Not decreasing initially
            strategy="test"
        )
        
        # After sorting, levels should be decreasing
        assert bracket.take_profit_levels[0] > bracket.take_profit_levels[1]
        assert bracket.take_profit_levels[1] > bracket.take_profit_levels[2]
        assert bracket.take_profit_levels == [Decimal('49000'), Decimal('48000'), Decimal('47000')]
    
    def test_risk_reward_ratio_calculation(self):
        """Test risk-reward ratio calculation."""
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            take_profit_levels=[Decimal('51000')],
            strategy="test"
        )
        
        # Risk = 50000 - 49000 = 1000
        # Reward = 51000 - 50000 = 1000
        # R:R = 1000 / 1000 = 1.0
        expected_rr = Decimal('1.0')
        assert bracket.get_risk_reward_ratio() == expected_rr
    
    def test_position_value_calculation(self):
        """Test position value calculation."""
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            take_profit_levels=[Decimal('51000')],
            strategy="test"
        )
        
        expected_value = Decimal('50000') * Decimal('0.1')  # 5000
        assert bracket.get_position_value() == expected_value
    
    def test_decimal_precision_consistency(self):
        """Test that all calculations maintain Decimal precision."""
        bracket = BracketOrder(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000.123456789'),
            quantity=Decimal('0.123456789'),
            stop_loss=Decimal('49000.987654321'),
            take_profit_levels=[Decimal('51000.111111111')],
            strategy="test"
        )
        
        # All internal values should be Decimal
        assert isinstance(bracket.entry_price, Decimal)
        assert isinstance(bracket.quantity, Decimal)
        assert isinstance(bracket.stop_loss, Decimal)
        assert isinstance(bracket.take_profit_levels[0], Decimal)
        assert isinstance(bracket.get_risk_reward_ratio(), Decimal)
        assert isinstance(bracket.get_position_value(), Decimal)


class TestBracketManagerIntegrity:
    """Test bracket manager functionality."""
    
    def test_create_bracket_order_with_atr(self):
        """Test creating bracket order with ATR."""
        manager = BracketManager()
        
        bracket = manager.create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            atr=Decimal('1000'),
            strategy="test",
            order_id="test_order_1"
        )
        
        assert bracket.symbol == "BTC/USDT"
        assert bracket.side == "BUY"
        assert len(bracket.take_profit_levels) == 3
        assert "test_order_1" in manager.active_brackets
    
    def test_create_bracket_order_with_rr_ratio(self):
        """Test creating bracket order with risk-reward ratio."""
        manager = BracketManager()
        
        bracket = manager.create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            risk_reward_ratio=Decimal('2.0'),
            strategy="test",
            order_id="test_order_2"
        )
        
        assert bracket.symbol == "BTC/USDT"
        assert bracket.side == "BUY"
        assert len(bracket.take_profit_levels) == 3
        
        # Check that TP levels are properly spaced
        tp_levels = bracket.take_profit_levels
        assert tp_levels[0] > bracket.entry_price
        assert tp_levels[1] > tp_levels[0]
        assert tp_levels[2] > tp_levels[1]
    
    def test_update_bracket_stop_loss(self):
        """Test updating bracket stop loss."""
        manager = BracketManager()
        
        # Create initial bracket
        bracket = manager.create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            strategy="test",
            order_id="test_order_3"
        )
        
        # Update stop loss
        success = manager.update_bracket_stop_loss("test_order_3", Decimal('49500'))
        assert success
        
        updated_bracket = manager.active_brackets["test_order_3"]
        assert updated_bracket.stop_loss == Decimal('49500')
    
    def test_close_bracket(self):
        """Test closing bracket order."""
        manager = BracketManager()
        
        # Create bracket
        bracket = manager.create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            strategy="test",
            order_id="test_order_4"
        )
        
        assert "test_order_4" in manager.active_brackets
        
        # Close bracket
        closed_bracket = manager.close_bracket("test_order_4")
        assert closed_bracket is not None
        assert "test_order_4" not in manager.active_brackets
    
    def test_validate_bracket_specs(self):
        """Test bracket specification validation."""
        manager = BracketManager()
        
        # Valid long bracket
        assert manager.validate_bracket_specs(
            side="BUY",
            entry_price=Decimal('50000'),
            stop_loss=Decimal('49000'),
            take_profit=Decimal('51000')
        )
        
        # Invalid long bracket
        assert not manager.validate_bracket_specs(
            side="BUY",
            entry_price=Decimal('50000'),
            stop_loss=Decimal('51000'),  # Invalid: stop > entry
            take_profit=Decimal('52000')
        )


class TestChandelierExitIntegrity:
    """Test chandelier exit functionality with Decimal precision."""
    
    def test_long_chandelier_exit(self):
        """Test chandelier exit for long positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        assert exit_strategy.side == "BUY"
        assert exit_strategy.entry_price == Decimal('50000')
        assert exit_strategy.atr == Decimal('1000')
        assert exit_strategy.highest_price == Decimal('50000')
        
        # Initial exit level should be below entry
        initial_exit = exit_strategy.get_exit_level()
        assert initial_exit < exit_strategy.entry_price
    
    def test_short_chandelier_exit(self):
        """Test chandelier exit for short positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        assert exit_strategy.side == "SELL"
        assert exit_strategy.entry_price == Decimal('50000')
        assert exit_strategy.atr == Decimal('1000')
        assert exit_strategy.lowest_price == Decimal('50000')
        
        # Initial exit level should be above entry
        initial_exit = exit_strategy.get_exit_level()
        assert initial_exit > exit_strategy.entry_price
    
    def test_chandelier_exit_price_update_long(self):
        """Test chandelier exit price update for long positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        initial_exit = exit_strategy.get_exit_level()
        
        # Update with higher price
        updated = exit_strategy.update_price(Decimal('51000'))
        assert updated
        assert exit_strategy.highest_price == Decimal('51000')
        
        new_exit = exit_strategy.get_exit_level()
        assert new_exit > initial_exit  # Exit level should move up
        
        # Update with lower price (should not change exit level)
        updated = exit_strategy.update_price(Decimal('50500'))
        assert not updated
        assert exit_strategy.highest_price == Decimal('51000')  # Should remain unchanged
    
    def test_chandelier_exit_price_update_short(self):
        """Test chandelier exit price update for short positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        initial_exit = exit_strategy.get_exit_level()
        
        # Update with lower price
        updated = exit_strategy.update_price(Decimal('49000'))
        assert updated
        assert exit_strategy.lowest_price == Decimal('49000')
        
        new_exit = exit_strategy.get_exit_level()
        assert new_exit < initial_exit  # Exit level should move down
        
        # Update with higher price (should not change exit level)
        updated = exit_strategy.update_price(Decimal('49500'))
        assert not updated
        assert exit_strategy.lowest_price == Decimal('49000')  # Should remain unchanged
    
    def test_chandelier_exit_conditions_long(self):
        """Test chandelier exit conditions for long positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        # Price above exit level should not trigger exit
        assert not exit_strategy.should_exit(Decimal('51000'))
        
        # Price at exit level should trigger exit
        exit_level = exit_strategy.get_exit_level()
        assert exit_strategy.should_exit(exit_level)
        
        # Price below exit level should trigger exit
        assert exit_strategy.should_exit(exit_level - Decimal('100'))
    
    def test_chandelier_exit_conditions_short(self):
        """Test chandelier exit conditions for short positions."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            atr_multiplier=Decimal('3.0'),
            strategy="test"
        )
        
        # Price below exit level should not trigger exit
        assert not exit_strategy.should_exit(Decimal('49000'))
        
        # Price at exit level should trigger exit
        exit_level = exit_strategy.get_exit_level()
        assert exit_strategy.should_exit(exit_level)
        
        # Price above exit level should trigger exit
        assert exit_strategy.should_exit(exit_level + Decimal('100'))
    
    def test_chandelier_exit_validation(self):
        """Test chandelier exit validation."""
        # Valid exit
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test"
        )
        assert exit_strategy.symbol == "BTC/USDT"
        
        # Invalid ATR
        with pytest.raises(ExitSpecError, match="ATR must be positive"):
            ChandelierExit(
                symbol="BTC/USDT",
                side="BUY",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                atr=Decimal('0'),  # Invalid
                strategy="test"
            )
        
        # Invalid quantity
        with pytest.raises(ExitSpecError, match="Quantity must be positive"):
            ChandelierExit(
                symbol="BTC/USDT",
                side="BUY",
                entry_price=Decimal('50000'),
                quantity=Decimal('0'),  # Invalid
                atr=Decimal('1000'),
                strategy="test"
            )
    
    def test_decimal_precision_consistency_chandelier(self):
        """Test that chandelier exit maintains Decimal precision."""
        exit_strategy = ChandelierExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000.123456789'),
            quantity=Decimal('0.123456789'),
            atr=Decimal('1000.987654321'),
            atr_multiplier=Decimal('3.141592653'),
            strategy="test"
        )
        
        # All internal values should be Decimal
        assert isinstance(exit_strategy.entry_price, Decimal)
        assert isinstance(exit_strategy.quantity, Decimal)
        assert isinstance(exit_strategy.atr, Decimal)
        assert isinstance(exit_strategy.atr_multiplier, Decimal)
        assert isinstance(exit_strategy.get_exit_level(), Decimal)
        assert isinstance(exit_strategy.get_trailing_distance(), Decimal)


class TestTimeExitIntegrity:
    """Test time-based exit functionality with Decimal precision."""
    
    def test_time_exit_creation(self):
        """Test time exit creation."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(minutes=30)
        
        exit_strategy = TimeExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_time=exit_time,
            strategy="test"
        )
        
        assert exit_strategy.symbol == "BTC/USDT"
        assert exit_strategy.side == "BUY"
        assert exit_strategy.entry_time == entry_time
        assert exit_strategy.exit_time == exit_time
    
    def test_time_exit_conditions(self):
        """Test time exit conditions."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(minutes=30)
        
        exit_strategy = TimeExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_time=exit_time,
            strategy="test"
        )
        
        # Before exit time should not trigger exit
        assert not exit_strategy.should_exit(entry_time + timedelta(minutes=15))
        
        # At exit time should trigger exit
        assert exit_strategy.should_exit(exit_time)
        
        # After exit time should trigger exit
        assert exit_strategy.should_exit(exit_time + timedelta(minutes=1))
    
    def test_time_exit_validation(self):
        """Test time exit validation."""
        entry_time = datetime.now()
        
        # Valid exit
        exit_strategy = TimeExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_time=entry_time + timedelta(minutes=30),
            strategy="test"
        )
        assert exit_strategy.symbol == "BTC/USDT"
        
        # Invalid exit time (before entry time)
        with pytest.raises(ExitSpecError, match="Exit time must be after entry time"):
            TimeExit(
                symbol="BTC/USDT",
                side="BUY",
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                entry_time=entry_time,
                exit_time=entry_time - timedelta(minutes=30),  # Invalid
                strategy="test"
            )
    
    def test_time_remaining_calculation(self):
        """Test time remaining calculation."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(minutes=30)
        
        exit_strategy = TimeExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_time=exit_time,
            strategy="test"
        )
        
        # Check time remaining
        time_remaining = exit_strategy.get_time_remaining(entry_time + timedelta(minutes=10))
        expected_remaining = timedelta(minutes=20)
        assert abs((time_remaining - expected_remaining).total_seconds()) < 1  # Allow 1 second tolerance
    
    def test_decimal_precision_consistency_time(self):
        """Test that time exit maintains Decimal precision."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(minutes=30)
        
        exit_strategy = TimeExit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000.123456789'),
            quantity=Decimal('0.123456789'),
            entry_time=entry_time,
            exit_time=exit_time,
            strategy="test"
        )
        
        # Price and quantity should be Decimal
        assert isinstance(exit_strategy.entry_price, Decimal)
        assert isinstance(exit_strategy.quantity, Decimal)


class TestExitManagerIntegrity:
    """Test exit manager functionality."""
    
    def test_create_chandelier_exit(self):
        """Test creating chandelier exit through manager."""
        manager = ExitManager()
        
        exit_strategy = manager.create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test",
            exit_id="test_exit_1"
        )
        
        assert exit_strategy.symbol == "BTC/USDT"
        assert "test_exit_1" in manager.active_exits
    
    def test_create_time_exit(self):
        """Test creating time exit through manager."""
        manager = ExitManager()
        
        entry_time = datetime.now()
        exit_strategy = manager.create_time_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_minutes=30,
            strategy="test",
            exit_id="test_exit_2"
        )
        
        assert exit_strategy.symbol == "BTC/USDT"
        assert "test_exit_2" in manager.active_exits
    
    def test_update_chandelier_price(self):
        """Test updating chandelier exit price through manager."""
        manager = ExitManager()
        
        # Create chandelier exit
        exit_strategy = manager.create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test",
            exit_id="test_exit_3"
        )
        
        # Update price
        updated = manager.update_chandelier_price("test_exit_3", Decimal('51000'))
        assert updated
        
        # Check that exit level was updated
        updated_exit = manager.active_exits["test_exit_3"]
        assert updated_exit.highest_price == Decimal('51000')
    
    def test_check_exit_conditions(self):
        """Test checking exit conditions through manager."""
        manager = ExitManager()
        
        # Create chandelier exit
        exit_strategy = manager.create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test",
            exit_id="test_exit_4"
        )
        
        # Check exit conditions
        exit_level = exit_strategy.get_exit_level()
        should_exit = manager.check_exit_conditions("test_exit_4", exit_level)
        assert should_exit
    
    def test_close_exit(self):
        """Test closing exit strategy through manager."""
        manager = ExitManager()
        
        # Create exit
        exit_strategy = manager.create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test",
            exit_id="test_exit_5"
        )
        
        assert "test_exit_5" in manager.active_exits
        
        # Close exit
        closed_exit = manager.close_exit("test_exit_5")
        assert closed_exit is not None
        assert "test_exit_5" not in manager.active_exits


class TestConvenienceFunctions:
    """Test convenience functions for creating bracket orders and exits."""
    
    def test_create_bracket_order_function(self):
        """Test create_bracket_order convenience function."""
        bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        assert bracket.symbol == "BTC/USDT"
        assert bracket.side == "BUY"
        assert len(bracket.take_profit_levels) == 3
    
    def test_create_chandelier_exit_function(self):
        """Test create_chandelier_exit convenience function."""
        exit_strategy = create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        assert exit_strategy.symbol == "BTC/USDT"
        assert exit_strategy.side == "BUY"
        assert exit_strategy.atr == Decimal('1000')
    
    def test_create_time_exit_function(self):
        """Test create_time_exit convenience function."""
        entry_time = datetime.now()
        
        exit_strategy = create_time_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_minutes=30,
            strategy="test"
        )
        
        assert exit_strategy.symbol == "BTC/USDT"
        assert exit_strategy.side == "BUY"
        assert exit_strategy.entry_time == entry_time


class TestIntegrationScenarios:
    """Test integration scenarios combining bracket orders and exit strategies."""
    
    def test_bracket_with_chandelier_exit(self):
        """Test bracket order with chandelier exit."""
        # Create bracket order
        bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        # Create chandelier exit
        exit_strategy = create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        # Both should be valid
        assert bracket.symbol == exit_strategy.symbol
        assert bracket.side == exit_strategy.side
        assert bracket.entry_price == exit_strategy.entry_price
        assert bracket.quantity == exit_strategy.quantity
    
    def test_bracket_with_time_exit(self):
        """Test bracket order with time exit."""
        # Create bracket order
        bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            strategy="test"
        )
        
        # Create time exit
        entry_time = datetime.now()
        exit_strategy = create_time_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=entry_time,
            exit_minutes=30,
            strategy="test"
        )
        
        # Both should be valid
        assert bracket.symbol == exit_strategy.symbol
        assert bracket.side == exit_strategy.side
        assert bracket.entry_price == exit_strategy.entry_price
        assert bracket.quantity == exit_strategy.quantity
    
    def test_monotonic_levels_verification(self):
        """Test that all levels are monotonic across different scenarios."""
        # Test long bracket with 3 TP levels
        long_bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('49000'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        # Verify monotonic TP levels for long
        tp_levels = long_bracket.take_profit_levels
        assert tp_levels[0] < tp_levels[1] < tp_levels[2]
        assert tp_levels[0] > long_bracket.entry_price
        
        # Test short bracket with 3 TP levels
        short_bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="SELL",
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            stop_loss=Decimal('51000'),
            atr=Decimal('1000'),
            strategy="test"
        )
        
        # Verify monotonic TP levels for short
        tp_levels = short_bracket.take_profit_levels
        assert tp_levels[0] > tp_levels[1] > tp_levels[2]
        assert tp_levels[0] < short_bracket.entry_price
    
    def test_no_type_errors_with_decimal_operations(self):
        """Test that no TypeError occurs with Decimal operations."""
        # Test bracket order calculations
        bracket = create_bracket_order(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000.123456789'),
            quantity=Decimal('0.123456789'),
            stop_loss=Decimal('49000.987654321'),
            atr=Decimal('1000.111111111'),
            strategy="test"
        )
        
        # These operations should not raise TypeError
        position_value = bracket.get_position_value()
        risk_reward = bracket.get_risk_reward_ratio()
        tp_values = bracket.get_take_profit_values()
        
        assert isinstance(position_value, Decimal)
        assert isinstance(risk_reward, Decimal)
        assert all(isinstance(tp_val, Decimal) for tp_val in tp_values)
        
        # Test chandelier exit calculations
        exit_strategy = create_chandelier_exit(
            symbol="BTC/USDT",
            side="BUY",
            entry_price=Decimal('50000.123456789'),
            quantity=Decimal('0.123456789'),
            atr=Decimal('1000.111111111'),
            strategy="test"
        )
        
        # These operations should not raise TypeError
        exit_level = exit_strategy.get_exit_level()
        trailing_distance = exit_strategy.get_trailing_distance()
        
        assert isinstance(exit_level, Decimal)
        assert isinstance(trailing_distance, Decimal)

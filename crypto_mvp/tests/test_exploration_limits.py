"""
Tests for exploration limits functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from src.crypto_mvp.trading_system import ProfitMaximizingTradingSystem


class TestExplorationLimits:
    """Test exploration limits functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = {
            "risk": {
                "exploration": {
                    "enabled": True,
                    "budget_pct_per_day": 0.03,  # 3% of equity per day
                    "max_forced_per_day": 2,     # Max 2 forced pilots per day
                    "min_score": 0.30,
                    "size_mult_vs_normal": 0.5,
                    "tighter_stop_mult": 0.7
                }
            },
            "trading": {
                "live_mode": False
            }
        }
        
        # Mock components
        self.data_engine = Mock()
        self.risk_manager = Mock()
        self.order_manager = Mock()
        self.state_store = Mock()
        self.portfolio_manager = Mock()
        self.multi_strategy_executor = Mock()
        
        # Create trading system
        self.trading_system = ProfitMaximizingTradingSystem()
        # Set config directly since constructor expects a file path
        self.trading_system.config = self.config
        self.trading_system.data_engine = self.data_engine
        self.trading_system.risk_manager = self.risk_manager
        self.trading_system.order_manager = self.order_manager
        self.trading_system.state_store = self.state_store
        self.trading_system.portfolio_manager = self.portfolio_manager
        self.trading_system.multi_strategy_executor = self.multi_strategy_executor
        self.trading_system.current_session_id = "test_session"
        self.trading_system.cycle_count = 1
        
        # Mock equity calculation
        self.trading_system._get_total_equity = Mock(return_value=10000.0)  # $10,000 equity
        
        # Mock state store responses - default values
        self.exploration_used_notional_today = 0.0
        self.exploration_forced_count_today = 0
        self.halt_new_entries_today = False
        
        def mock_get_session_metadata(session_id, key, default):
            if key == "exploration_used_notional_today":
                return self.exploration_used_notional_today
            elif key == "exploration_forced_count_today":
                return self.exploration_forced_count_today
            elif key == "halt_new_entries_today":
                return self.halt_new_entries_today
            return default
        
        self.state_store.get_session_metadata = mock_get_session_metadata

    def test_can_explore_enabled_and_within_limits(self):
        """Test can_explore returns True when exploration is enabled and within limits."""
        # Test with small order value
        result = self.trading_system.can_explore(100.0)
        assert result is True
        
        # Test with larger order value but still within budget
        exploration_budget = 10000.0 * 0.03  # $300
        result = self.trading_system.can_explore(200.0)
        assert result is True

    def test_can_explore_disabled(self):
        """Test can_explore returns False when exploration is disabled."""
        self.config["risk"]["exploration"]["enabled"] = False
        
        result = self.trading_system.can_explore(100.0)
        assert result is False

    def test_can_explore_exceeds_count_limit(self):
        """Test can_explore returns False when max forced count is reached."""
        # Set count to max limit
        self.exploration_forced_count_today = 2  # At max limit
        
        result = self.trading_system.can_explore(100.0)
        assert result is False

    def test_can_explore_exceeds_budget_limit(self):
        """Test can_explore returns False when budget is exhausted."""
        exploration_budget = 10000.0 * 0.03  # $300
        # Set used notional to exceed budget
        self.exploration_used_notional_today = exploration_budget + 10.0  # Exceed budget
        
        result = self.trading_system.can_explore(100.0)
        assert result is False

    def test_can_explore_insufficient_budget_for_order(self):
        """Test can_explore returns False when order value exceeds remaining budget."""
        exploration_budget = 10000.0 * 0.03  # $300
        used_notional = 200.0  # $200 already used
        remaining_budget = exploration_budget - used_notional  # $100 remaining
        
        self.exploration_used_notional_today = used_notional
        
        # Order value exceeds remaining budget
        result = self.trading_system.can_explore(150.0)  # Need $150 but only have $100
        assert result is False
        
        # Order value within remaining budget
        result = self.trading_system.can_explore(50.0)  # Need $50 and have $100
        assert result is True

    def test_can_explore_no_state_store(self):
        """Test can_explore returns False when state store is not available."""
        self.trading_system.state_store = None
        
        result = self.trading_system.can_explore(100.0)
        assert result is False

    def test_can_explore_no_session_id(self):
        """Test can_explore returns False when session ID is not available."""
        self.trading_system.current_session_id = None
        
        result = self.trading_system.can_explore(100.0)
        assert result is False

    @patch('src.crypto_mvp.trading_system.get_entry_price')
    @patch('src.crypto_mvp.trading_system.get_mark_price')
    def test_exploration_trade_blocked_by_limits(self, mock_get_mark_price, mock_get_entry_price):
        """Test that exploration trade is blocked when limits are reached."""
        # Mock price data
        mock_get_entry_price.return_value = 50000.0  # BTC price
        mock_get_mark_price.return_value = 50000.0
        
        # Mock signals
        signals = {
            "BTC/USDT": {
                "composite_score": 0.35,
                "metadata": {
                    "normalization": {
                        "normalized_composite_score": 0.35
                    }
                }
            }
        }
        
        # Set exploration limits to be exceeded
        self.exploration_forced_count_today = 2  # At max limit
        
        # Mock order manager
        self.order_manager.calculate_target_notional.return_value = 100.0
        
        # Test exploration trade execution
        result = self.trading_system._execute_exploration_trade(signals, 1000.0)
        
        # Should return None because limits are exceeded
        assert result is None

    @patch('src.crypto_mvp.trading_system.get_entry_price')
    @patch('src.crypto_mvp.trading_system.get_mark_price')
    def test_regular_trade_blocked_by_exploration_limits(self, mock_get_mark_price, mock_get_entry_price):
        """Test that regular trades are blocked when exploration limits are reached."""
        # Mock price data
        mock_get_entry_price.return_value = 50000.0
        mock_get_mark_price.return_value = 50000.0
        
        # Mock signals
        signals = {
            "BTC/USDT": {
                "composite_score": 0.65,
                "metadata": {
                    "normalization": {
                        "normalized_composite_score": 0.65
                    }
                }
            }
        }
        
        # Set exploration limits to be exceeded
        self.exploration_forced_count_today = 2  # At max limit
        
        # Mock risk manager
        self.risk_manager.derive_sl_tp.return_value = {
            "stop_loss": 49000.0,
            "take_profit": 51000.0,
            "source": "atr_based"
        }
        self.risk_manager.compute_rr.return_value = 2.0
        
        # Mock order manager
        self.order_manager.calculate_target_notional.return_value = 100.0
        
        # Test regular trade execution (async method)
        import asyncio
        result = asyncio.run(self.trading_system._execute_profit_optimized_trades(signals))
        
        # Should not execute any trades due to exploration limits
        assert result["trades_executed"] == 0
        assert len(result["trades"]) == 0

    @patch('src.crypto_mvp.trading_system.get_entry_price')
    @patch('src.crypto_mvp.trading_system.get_mark_price')
    def test_pilot_trade_blocked_by_exploration_limits(self, mock_get_mark_price, mock_get_entry_price):
        """Test that pilot trades are blocked when exploration limits are reached."""
        # Mock price data
        mock_get_entry_price.return_value = 50000.0
        mock_get_mark_price.return_value = 50000.0
        
        # Mock signals
        signals = {
            "BTC/USDT": {
                "composite_score": 0.55,
                "metadata": {
                    "normalization": {
                        "normalized_composite_score": 0.55
                    }
                }
            }
        }
        
        # Set exploration limits to be exceeded
        self.exploration_forced_count_today = 2  # At max limit
        
        # Mock risk manager
        self.risk_manager.derive_sl_tp.return_value = {
            "stop_loss": 49000.0,
            "take_profit": 51000.0,
            "source": "atr_based"
        }
        self.risk_manager.compute_rr.return_value = 1.7  # Above pilot threshold
        
        # Mock order manager
        self.order_manager.calculate_target_notional.return_value = 100.0
        
        # Test pilot trade execution
        result = self.trading_system._execute_pilot_trade(signals, 1000.0)
        
        # Should return None because limits are exceeded
        assert result is None

    def test_two_forced_pilots_hit_max_third_blocked(self):
        """Test that two forced pilots hit the max and the third is blocked."""
        # Test the can_explore function directly with different count scenarios
        
        # First two calls should succeed (count < max)
        self.exploration_forced_count_today = 0
        result1 = self.trading_system.can_explore(100.0)
        assert result1 is True
        
        self.exploration_forced_count_today = 1
        result2 = self.trading_system.can_explore(100.0)
        assert result2 is True
        
        # Third call should be blocked (count >= max)
        self.exploration_forced_count_today = 2  # At max limit
        result3 = self.trading_system.can_explore(100.0)
        assert result3 is False
        
        # Verify that the limit is enforced
        assert self.exploration_forced_count_today == 2

    def test_logging_format_fixed(self):
        """Test that logging format never shows used=$450/$300 format."""
        # This test ensures the logging format is fixed
        # The actual logging happens in the exploration trade execution
        # We'll verify that the can_explore method logs properly formatted messages
        
        with patch('src.crypto_mvp.trading_system.ProfitMaximizingTradingSystem.logger') as mock_logger:
            # Test budget exhausted case
            exploration_budget = 10000.0 * 0.03  # $300
            self.exploration_used_notional_today = exploration_budget + 10.0
            
            result = self.trading_system.can_explore(100.0)
            assert result is False
            
            # Verify logging format is correct (no used=$450/$300 format)
            mock_logger.info.assert_called()
            logged_messages = [call.args[0] for call in mock_logger.info.call_args_list]
            for message in logged_messages:
                # Ensure no message contains the problematic format
                assert "used=$" not in message or "/$" not in message

    def test_exploration_budget_calculation(self):
        """Test exploration budget calculation."""
        # Test with different equity values
        test_cases = [
            (10000.0, 0.03, 300.0),  # $10k equity, 3% budget = $300
            (5000.0, 0.03, 150.0),   # $5k equity, 3% budget = $150
            (20000.0, 0.05, 1000.0), # $20k equity, 5% budget = $1000
        ]
        
        for equity, budget_pct, expected_budget in test_cases:
            self.trading_system._get_total_equity = Mock(return_value=equity)
            self.config["risk"]["exploration"]["budget_pct_per_day"] = budget_pct
            
            # Create new trading system with updated config
            trading_system = ProfitMaximizingTradingSystem()
            trading_system.config = self.config
            trading_system._get_total_equity = Mock(return_value=equity)
            trading_system.state_store = self.state_store
            trading_system.current_session_id = "test_session"
            
            # Set up mock state store for the new trading system
            def mock_get_session_metadata_new(session_id, key, default):
                if key == "exploration_used_notional_today":
                    return expected_budget + 1.0  # Exceed budget
                elif key == "exploration_forced_count_today":
                    return 0
                elif key == "halt_new_entries_today":
                    return False
                return default
            
            trading_system.state_store.get_session_metadata = mock_get_session_metadata_new
            
            # Test can_explore with budget limit
            
            result = trading_system.can_explore(100.0)
            assert result is False

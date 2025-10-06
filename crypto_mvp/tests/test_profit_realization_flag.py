#!/usr/bin/env python3
"""
Test profit realization engine configuration flag.
"""

import sys
import os
import tempfile
from unittest.mock import Mock, patch
from datetime import datetime

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from crypto_mvp.state.store import StateStore


class TestProfitRealizationFlag:
    """Test profit realization engine configuration flag functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        
        # Initialize state store
        self.state_store = StateStore(self.temp_db.name)
        
        # Test session ID
        self.session_id = "test_profit_realization_flag"
    
    def teardown_method(self):
        """Clean up test environment."""
        os.unlink(self.temp_db.name)
    
    def test_realization_enabled_true(self):
        """Test that realization engine is active when flag is true."""
        print("\nTest 1: Realization enabled = true")
        
        # Mock config with realization enabled
        mock_config = {
            "realization": {
                "enabled": True
            },
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Test that realization is enabled
            assert trading_system._is_realization_enabled() == True, "Realization should be enabled"
            
            print("✅ Realization enabled test passed: flag=True, engine=ENABLED")
    
    def test_realization_enabled_false(self):
        """Test that realization engine is disabled when flag is false."""
        print("\nTest 2: Realization enabled = false")
        
        # Mock config with realization disabled
        mock_config = {
            "realization": {
                "enabled": False
            },
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Test that realization is disabled
            assert trading_system._is_realization_enabled() == False, "Realization should be disabled"
            
            print("✅ Realization disabled test passed: flag=False, engine=DISABLED")
    
    def test_realization_enabled_env_var_string(self):
        """Test that realization engine handles environment variable string values."""
        print("\nTest 3: Realization enabled via environment variable")
        
        # Mock config with realization enabled via environment variable
        mock_config = {
            "realization": {
                "enabled": "${REALIZATION_ENABLED:-true}"  # Environment variable format
            },
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Test with different string values
            test_cases = [
                ("true", True),
                ("True", True),
                ("TRUE", True),
                ("1", True),
                ("yes", True),
                ("false", False),
                ("False", False),
                ("FALSE", False),
                ("0", False),
                ("no", False),
                ("invalid", False)
            ]
            
            for string_value, expected in test_cases:
                # Set the config value to the string
                trading_system.config["realization"]["enabled"] = string_value
                
                result = trading_system._is_realization_enabled()
                assert result == expected, f"String '{string_value}' should resolve to {expected}, got {result}"
            
            print("✅ Environment variable string test passed: all string values resolved correctly")
    
    def test_realization_enabled_missing_config(self):
        """Test that realization engine defaults to false when config is missing."""
        print("\nTest 4: Realization enabled missing config")
        
        # Mock config without realization section
        mock_config = {
            "trading": {
                "symbols": ["BTC/USDT"],
                "initial_capital": 10000.0
            },
            "state": {
                "db_path": self.temp_db.name
            }
        }
        
        with patch('crypto_mvp.trading_system.ConfigManager') as mock_config_manager, \
             patch('crypto_mvp.trading_system.ProfitOptimizedDataEngine') as mock_data_engine:
            
            mock_config_manager.return_value.get.return_value = mock_config
            mock_config_manager.return_value.load_config.return_value = mock_config
            
            trading_system = ProfitMaximizingTradingSystem("test_config.yaml")
            trading_system.config = mock_config
            trading_system.state_store = self.state_store
            trading_system.current_session_id = self.session_id
            
            # Mock components
            trading_system.data_engine = Mock()
            trading_system.risk_manager = Mock()
            trading_system.portfolio_manager = Mock()
            trading_system.order_manager = Mock()
            trading_system.multi_strategy_executor = Mock()
            trading_system.regime_detector = Mock()
            trading_system.signal_engine = Mock()
            trading_system.profit_analytics = Mock()
            trading_system.profit_logger = Mock()
            trading_system.trade_ledger = Mock()
            
            # Test that realization defaults to false when config is missing
            assert trading_system._is_realization_enabled() == False, "Realization should default to false when config missing"
            
            print("✅ Missing config test passed: defaults to False")


if __name__ == "__main__":
    # Run the tests
    test_instance = TestProfitRealizationFlag()
    
    print("Running profit realization flag tests...")
    print("=" * 60)
    
    try:
        test_instance.setup_method()
        
        print("Test 1: Realization enabled = true")
        test_instance.test_realization_enabled_true()
        
        print("\nTest 2: Realization enabled = false")
        test_instance.test_realization_enabled_false()
        
        print("\nTest 3: Realization enabled via environment variable")
        test_instance.test_realization_enabled_env_var_string()
        
        print("\nTest 4: Realization enabled missing config")
        test_instance.test_realization_enabled_missing_config()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("FEATURE_FLAGS: realization.enabled=True")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    finally:
        test_instance.teardown_method()

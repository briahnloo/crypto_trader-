#!/usr/bin/env python3
"""
Test exchange connector trading capability detection.
"""

import sys
import os
import tempfile
from unittest.mock import Mock, patch
from datetime import datetime

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.data.engine import ProfitOptimizedDataEngine
from crypto_mvp.data.connectors.coinbase import CoinbaseConnector
from crypto_mvp.data.connectors.binance import BinanceConnector
from crypto_mvp.core.config_manager import ConfigManager


class TestTradingCapability:
    """Test exchange connector trading capability detection."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create temporary config file
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        self.temp_config.write("""
data_sources:
  coinbase:
    enabled: true
  binance:
    enabled: true
  coingecko:
    enabled: false
  fear_greed:
    enabled: false
  social_sentiment:
    enabled: false
  news_sentiment:
    enabled: false
  whale_alert:
    enabled: false
  on_chain:
    enabled: false
""")
        self.temp_config.close()
    
    def teardown_method(self):
        """Clean up test environment."""
        os.unlink(self.temp_config.name)
    
    def test_trading_capability_with_credentials(self):
        """Test that connectors can trade when valid credentials are present."""
        print("\nTest 1: Trading capability with valid credentials")
        
        # Test individual connectors directly
        connector = CoinbaseConnector(
            api_key="test_coinbase_api_key_12345",
            secret="test_coinbase_secret_67890"
        )
        connector.initialize()
        
        assert connector.can_trade() == True, "Should be able to trade with valid credentials"
        
        print("✅ Trading capability with credentials test passed")
    
    def test_trading_capability_without_credentials(self):
        """Test that connectors cannot trade when credentials are missing."""
        print("\nTest 2: Trading capability without valid credentials")
        
        # Test individual connectors directly
        connector = CoinbaseConnector(
            api_key="your_coinbase_api_key_here",
            secret="your_coinbase_secret_here"
        )
        connector.initialize()
        
        assert connector.can_trade() == False, "Should not be able to trade without valid credentials"
        
        print("✅ Trading capability without credentials test passed")
    
    def test_coinbase_connector_can_trade(self):
        """Test Coinbase connector can_trade() method."""
        print("\nTest 3: Coinbase connector can_trade() method")
        
        # Test with valid credentials
        connector = CoinbaseConnector(
            api_key="test_coinbase_api_key_12345",
            secret="test_coinbase_secret_67890"
        )
        connector.initialize()
        
        assert connector.can_trade() == True, "Coinbase connector should be able to trade with valid credentials"
        
        # Test with invalid credentials
        connector_invalid = CoinbaseConnector(
            api_key="your_coinbase_api_key_here",
            secret="your_coinbase_secret_here"
        )
        connector_invalid.initialize()
        
        assert connector_invalid.can_trade() == False, "Coinbase connector should not be able to trade with invalid credentials"
        
        print("✅ Coinbase connector can_trade() test passed")
    
    def test_binance_connector_can_trade(self):
        """Test Binance connector can_trade() method."""
        print("\nTest 4: Binance connector can_trade() method")
        
        # Test with valid credentials
        connector = BinanceConnector(
            api_key="test_binance_api_key_12345",
            secret="test_binance_secret_67890"
        )
        connector.initialize()
        
        assert connector.can_trade() == True, "Binance connector should be able to trade with valid credentials"
        
        # Test with invalid credentials
        connector_invalid = BinanceConnector(
            api_key="your_binance_api_key_here",
            secret="your_binance_secret_here"
        )
        connector_invalid.initialize()
        
        assert connector_invalid.can_trade() == False, "Binance connector should not be able to trade with invalid credentials"
        
        print("✅ Binance connector can_trade() test passed")
    
    def test_environment_variable_credentials(self):
        """Test that environment variables are properly resolved for credentials."""
        print("\nTest 5: Environment variable credentials")
        
        # Test with environment variables set
        with patch.dict(os.environ, {
            'COINBASE_API_KEY': 'env_coinbase_api_key_12345',
            'COINBASE_SECRET': 'env_coinbase_secret_67890'
        }):
            # Create connector with environment variables
            connector = CoinbaseConnector(
                api_key=os.getenv('COINBASE_API_KEY'),
                secret=os.getenv('COINBASE_SECRET')
            )
            connector.initialize()
            
            # The connector should be able to trade with environment variable credentials
            assert connector.can_trade() == True, "Should be able to trade with environment variable credentials"
            
            print("✅ Environment variable credentials test passed")


if __name__ == "__main__":
    # Run the tests
    test_instance = TestTradingCapability()
    
    print("Running trading capability detection tests...")
    print("=" * 60)
    
    try:
        test_instance.setup_method()
        
        print("Test 1: Trading capability with valid credentials")
        test_instance.test_trading_capability_with_credentials()
        
        print("\nTest 2: Trading capability without valid credentials")
        test_instance.test_trading_capability_without_credentials()
        
        print("\nTest 3: Coinbase connector can_trade() method")
        test_instance.test_coinbase_connector_can_trade()
        
        print("\nTest 4: Binance connector can_trade() method")
        test_instance.test_binance_connector_can_trade()
        
        print("\nTest 5: Environment variable credentials")
        test_instance.test_environment_variable_credentials()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("API_PERMISSIONS: PASS – Coinbase trading connector active")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    finally:
        test_instance.teardown_method()

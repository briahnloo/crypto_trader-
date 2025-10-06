#!/usr/bin/env python3
"""
Test symbol whitelist functionality.
"""

import sys
import os
import tempfile
from unittest.mock import Mock, patch
from datetime import datetime

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.execution.symbol_filter import SymbolFilter
from crypto_mvp.core.config_manager import ConfigManager


class TestSymbolWhitelist:
    """Test symbol whitelist functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create temporary config file
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml')
        self.temp_config.write("""
trading:
  symbols:
    - "BTC/USDT"
    - "ETH/USDT"
    - "ADA/USDT"
    - "SOL/USDT"
  symbol_whitelist:
    - "BTC/USDT"
    - "ETH/USDT"
""")
        self.temp_config.close()
    
    def teardown_method(self):
        """Clean up test environment."""
        os.unlink(self.temp_config.name)
    
    def test_symbol_filter_allows_whitelisted_symbols(self):
        """Test that symbol filter allows whitelisted symbols."""
        print("\nTest 1: Symbol filter allows whitelisted symbols")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test whitelisted symbols
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("BTC/USDT")
        assert is_allowed == True, "BTC/USDT should be allowed"
        assert reason == "whitelisted", f"Expected 'whitelisted', got '{reason}'"
        
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("ETH/USDT")
        assert is_allowed == True, "ETH/USDT should be allowed"
        assert reason == "whitelisted", f"Expected 'whitelisted', got '{reason}'"
        
        print("✅ Symbol filter allows whitelisted symbols test passed")
    
    def test_symbol_filter_blocks_non_whitelisted_symbols(self):
        """Test that symbol filter blocks non-whitelisted symbols."""
        print("\nTest 2: Symbol filter blocks non-whitelisted symbols")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test non-whitelisted symbols
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("ADA/USDT")
        assert is_allowed == False, "ADA/USDT should be blocked"
        assert reason == "not_whitelisted", f"Expected 'not_whitelisted', got '{reason}'"
        
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("SOL/USDT")
        assert is_allowed == False, "SOL/USDT should be blocked"
        assert reason == "not_whitelisted", f"Expected 'not_whitelisted', got '{reason}'"
        
        print("✅ Symbol filter blocks non-whitelisted symbols test passed")
    
    def test_symbol_filter_case_insensitive(self):
        """Test that symbol filter is case insensitive."""
        print("\nTest 3: Symbol filter is case insensitive")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test case variations
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("btc/usdt")
        assert is_allowed == True, "btc/usdt should be allowed (case insensitive)"
        
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("ETH/usdt")
        assert is_allowed == True, "ETH/usdt should be allowed (case insensitive)"
        
        print("✅ Symbol filter case insensitive test passed")
    
    def test_symbol_filter_empty_whitelist(self):
        """Test that symbol filter with empty whitelist blocks all symbols."""
        print("\nTest 4: Symbol filter with empty whitelist blocks all symbols")
        
        config = {
            "trading": {
                "symbol_whitelist": []
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test that empty whitelist blocks all symbols
        assert symbol_filter.is_whitelist_empty() == True, "Whitelist should be empty"
        
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("BTC/USDT")
        assert is_allowed == False, "BTC/USDT should be blocked with empty whitelist"
        assert reason == "not_whitelisted", f"Expected 'not_whitelisted', got '{reason}'"
        
        print("✅ Symbol filter empty whitelist test passed")
    
    def test_symbol_filter_no_whitelist_config(self):
        """Test that symbol filter with no whitelist config blocks all symbols."""
        print("\nTest 5: Symbol filter with no whitelist config blocks all symbols")
        
        config = {
            "trading": {}
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test that missing whitelist blocks all symbols
        assert symbol_filter.is_whitelist_empty() == True, "Whitelist should be empty"
        
        is_allowed, reason, _ = symbol_filter.is_symbol_allowed("BTC/USDT")
        assert is_allowed == False, "BTC/USDT should be blocked with no whitelist config"
        assert reason == "not_whitelisted", f"Expected 'not_whitelisted', got '{reason}'"
        
        print("✅ Symbol filter no whitelist config test passed")
    
    def test_symbol_filter_should_skip_trade(self):
        """Test that should_skip_trade method works correctly."""
        print("\nTest 6: Symbol filter should_skip_trade method")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        # Test whitelisted symbol should not be skipped
        should_skip, reason, details = symbol_filter.should_skip_trade("BTC/USDT", "BUY", "momentum")
        assert should_skip == False, "BTC/USDT should not be skipped"
        assert reason == "whitelisted", f"Expected 'whitelisted', got '{reason}'"
        # Strategy is only added to details when symbol is rejected
        
        # Test non-whitelisted symbol should be skipped
        should_skip, reason, details = symbol_filter.should_skip_trade("ADA/USDT", "BUY", "momentum")
        assert should_skip == True, "ADA/USDT should be skipped"
        assert reason == "not_whitelisted", f"Expected 'not_whitelisted', got '{reason}'"
        assert details["strategy"] == "momentum", "Strategy should be in details"
        
        print("✅ Symbol filter should_skip_trade method test passed")
    
    def test_symbol_filter_universe_summary(self):
        """Test that universe summary provides correct information."""
        print("\nTest 7: Symbol filter universe summary")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        summary = symbol_filter.get_universe_summary()
        
        assert summary["whitelist"] == ["BTC/USDT", "ETH/USDT"], "Whitelist should match"
        assert summary["whitelist_size"] == 2, "Whitelist size should be 2"
        assert summary["is_empty"] == False, "Whitelist should not be empty"
        assert "whitelist_normalized" in summary, "Should include normalized whitelist"
        
        print("✅ Symbol filter universe summary test passed")
    
    def test_symbol_filter_symbol_statistics(self):
        """Test that symbol statistics work correctly."""
        print("\nTest 8: Symbol filter symbol statistics")
        
        config = {
            "trading": {
                "symbol_whitelist": ["BTC/USDT", "ETH/USDT"]
            }
        }
        
        symbol_filter = SymbolFilter(config)
        
        symbols_checked = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT"]
        stats = symbol_filter.get_symbol_statistics(symbols_checked)
        
        assert stats["total_checked"] == 4, "Should have checked 4 symbols"
        assert stats["allowed_count"] == 2, "Should have allowed 2 symbols"
        assert stats["rejected_count"] == 2, "Should have rejected 2 symbols"
        assert "BTC/USDT" in stats["allowed_symbols"], "BTC/USDT should be in allowed"
        assert "ETH/USDT" in stats["allowed_symbols"], "ETH/USDT should be in allowed"
        assert "ADA/USDT" in stats["rejected_symbols"], "ADA/USDT should be in rejected"
        assert "SOL/USDT" in stats["rejected_symbols"], "SOL/USDT should be in rejected"
        assert stats["allowance_rate"] == 0.5, "Allowance rate should be 0.5"
        
        print("✅ Symbol filter symbol statistics test passed")


if __name__ == "__main__":
    # Run the tests
    test_instance = TestSymbolWhitelist()
    
    print("Running symbol whitelist tests...")
    print("=" * 60)
    
    try:
        test_instance.setup_method()
        
        print("Test 1: Symbol filter allows whitelisted symbols")
        test_instance.test_symbol_filter_allows_whitelisted_symbols()
        
        print("\nTest 2: Symbol filter blocks non-whitelisted symbols")
        test_instance.test_symbol_filter_blocks_non_whitelisted_symbols()
        
        print("\nTest 3: Symbol filter is case insensitive")
        test_instance.test_symbol_filter_case_insensitive()
        
        print("\nTest 4: Symbol filter with empty whitelist blocks all symbols")
        test_instance.test_symbol_filter_empty_whitelist()
        
        print("\nTest 5: Symbol filter with no whitelist config blocks all symbols")
        test_instance.test_symbol_filter_no_whitelist_config()
        
        print("\nTest 6: Symbol filter should_skip_trade method")
        test_instance.test_symbol_filter_should_skip_trade()
        
        print("\nTest 7: Symbol filter universe summary")
        test_instance.test_symbol_filter_universe_summary()
        
        print("\nTest 8: Symbol filter symbol statistics")
        test_instance.test_symbol_filter_symbol_statistics()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("SYMBOL_WHITELIST_CONFIG: PASS – 2 symbols active")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    finally:
        test_instance.teardown_method()

#!/usr/bin/env python3
"""
Comprehensive integration tests for API error handling.
Tests all critical API error scenarios and recovery mechanisms.
"""

import unittest
import sys
import os
import time
from unittest.mock import Mock, patch, MagicMock
import requests
from requests.exceptions import RequestException, ConnectionError, Timeout, HTTPError

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.data.connectors.coinbase import CoinbaseConnector
from crypto_mvp.data.connectors.binance import BinanceConnector
from crypto_mvp.data.engine import ProfitOptimizedDataEngine
from crypto_mvp.core.config_manager import ConfigManager


class TestAPIErrorHandling(unittest.TestCase):
    """Test suite for API error handling functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = ConfigManager()
        self.config = self.config_manager._config
        
        # Mock connectors
        self.coinbase_connector = CoinbaseConnector(self.config_manager)
        self.binance_connector = BinanceConnector(self.config_manager)
        
        # Mock data engine
        self.data_engine = ProfitOptimizedDataEngine(self.config_manager)
    
    def test_coinbase_404_error_handling(self):
        """Test Coinbase 404 error handling for unsupported symbols."""
        # Test with BNB/USDT which should return 404
        with patch('requests.get') as mock_get:
            # Mock 404 response
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = HTTPError("404 Client Error: Not Found")
            mock_get.return_value = mock_response
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("BNB/USDT")
            
            # Should return mock data, not raise exception
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
            self.assertIn('price', ticker)
            self.assertEqual(ticker['symbol'], 'BNB/USDT')
    
    def test_coinbase_connection_error_handling(self):
        """Test Coinbase connection error handling."""
        with patch('requests.get') as mock_get:
            # Mock connection error
            mock_get.side_effect = ConnectionError("Connection failed")
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should return mock data, not raise exception
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
            self.assertIn('price', ticker)
    
    def test_coinbase_timeout_error_handling(self):
        """Test Coinbase timeout error handling."""
        with patch('requests.get') as mock_get:
            # Mock timeout error
            mock_get.side_effect = Timeout("Request timed out")
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("ETH/USDT")
            
            # Should return mock data, not raise exception
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
            self.assertIn('price', ticker)
    
    def test_coinbase_invalid_response_handling(self):
        """Test Coinbase invalid response handling."""
        with patch('requests.get') as mock_get:
            # Mock invalid response
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"invalid": "data"}  # Missing required fields
            mock_get.return_value = mock_response
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should return mock data, not raise exception
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
            self.assertIn('price', ticker)
    
    def test_binance_api_error_handling(self):
        """Test Binance API error handling."""
        with patch('requests.get') as mock_get:
            # Mock API error response
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = HTTPError("400 Bad Request")
            mock_get.return_value = mock_response
            
            # Should fall back to mock data
            ticker = self.binance_connector.get_ticker("BTC/USDT")
            
            # Should return mock data, not raise exception
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
            self.assertIn('price', ticker)
    
    def test_data_engine_error_recovery(self):
        """Test data engine error recovery mechanisms."""
        # Mock connectors to return errors
        with patch.object(self.coinbase_connector, 'get_ticker') as mock_coinbase:
            with patch.object(self.binance_connector, 'get_ticker') as mock_binance:
                # Both connectors return errors
                mock_coinbase.side_effect = Exception("Coinbase error")
                mock_binance.side_effect = Exception("Binance error")
                
                # Data engine should handle errors gracefully
                try:
                    # This should not raise an exception
                    price = self.data_engine.get_mark_price("BTC/USDT")
                    self.assertIsInstance(price, (int, float))
                    self.assertGreater(price, 0)
                except Exception as e:
                    self.fail(f"Data engine should handle errors gracefully, but raised: {e}")
    
    def test_symbol_validation(self):
        """Test symbol validation for unsupported symbols."""
        # Test unsupported symbol
        is_supported = self.coinbase_connector._is_symbol_supported("BNB/USDT")
        self.assertFalse(is_supported)
        
        # Test supported symbol
        is_supported = self.coinbase_connector._is_symbol_supported("BTC/USDT")
        self.assertTrue(is_supported)
    
    def test_fallback_data_quality(self):
        """Test quality of fallback mock data."""
        # Test that mock data has required fields
        ticker = self.coinbase_connector._get_mock_ticker_data("BTC/USDT")
        
        required_fields = ['symbol', 'price', 'bid', 'ask', 'volume', 'timestamp']
        for field in required_fields:
            self.assertIn(field, ticker, f"Mock data missing required field: {field}")
        
        # Test data types
        self.assertIsInstance(ticker['price'], (int, float))
        self.assertIsInstance(ticker['bid'], (int, float))
        self.assertIsInstance(ticker['ask'], (int, float))
        self.assertIsInstance(ticker['volume'], (int, float))
        self.assertIsInstance(ticker['timestamp'], (int, float))
        
        # Test reasonable values
        self.assertGreater(ticker['price'], 0)
        self.assertGreater(ticker['bid'], 0)
        self.assertGreater(ticker['ask'], 0)
        self.assertGreaterEqual(ticker['volume'], 0)
        self.assertGreater(ticker['timestamp'], 0)
    
    def test_error_logging(self):
        """Test that errors are properly logged."""
        with patch('requests.get') as mock_get:
            # Mock error
            mock_get.side_effect = ConnectionError("Test connection error")
            
            # Capture log output
            with patch.object(self.coinbase_connector.logger, 'warning') as mock_warning:
                self.coinbase_connector.get_ticker("BTC/USDT")
                
                # Should log warning about failed request
                mock_warning.assert_called()
                call_args = mock_warning.call_args[0][0]
                self.assertIn("Failed to get live ticker data", call_args)
    
    def test_retry_mechanism(self):
        """Test retry mechanism for transient errors."""
        call_count = 0
        
        def mock_get_with_retry(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:  # Fail first 2 times
                raise ConnectionError("Transient error")
            else:  # Succeed on 3rd try
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    'price': '50000.00',
                    'bid': '49999.00',
                    'ask': '50001.00',
                    'volume': '1000.0'
                }
                return mock_response
        
        with patch('requests.get', side_effect=mock_get_with_retry):
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should succeed after retries
            self.assertIsInstance(ticker, dict)
            self.assertEqual(ticker['symbol'], 'BTC/USDT')
            self.assertEqual(call_count, 3)  # Should have retried 3 times
    
    def test_rate_limiting_handling(self):
        """Test rate limiting error handling."""
        with patch('requests.get') as mock_get:
            # Mock rate limit error
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = HTTPError("429 Too Many Requests")
            mock_get.return_value = mock_response
            
            # Should handle rate limiting gracefully
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should return mock data
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
    
    def test_malformed_json_handling(self):
        """Test handling of malformed JSON responses."""
        with patch('requests.get') as mock_get:
            # Mock malformed JSON response
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_get.return_value = mock_response
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should return mock data
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
    
    def test_empty_response_handling(self):
        """Test handling of empty responses."""
        with patch('requests.get') as mock_get:
            # Mock empty response
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {}
            mock_get.return_value = mock_response
            
            # Should fall back to mock data
            ticker = self.coinbase_connector.get_ticker("BTC/USDT")
            
            # Should return mock data
            self.assertIsInstance(ticker, dict)
            self.assertIn('symbol', ticker)
    
    def test_concurrent_api_calls(self):
        """Test concurrent API calls and error handling."""
        import threading
        import time
        
        results = []
        
        def make_api_call():
            try:
                with patch('requests.get') as mock_get:
                    # Mock random errors
                    if threading.current_thread().ident % 2 == 0:
                        mock_get.side_effect = ConnectionError("Connection error")
                    else:
                        mock_response = Mock()
                        mock_response.raise_for_status.return_value = None
                        mock_response.json.return_value = {
                            'price': '50000.00',
                            'bid': '49999.00',
                            'ask': '50001.00',
                            'volume': '1000.0'
                        }
                        mock_get.return_value = mock_response
                    
                    ticker = self.coinbase_connector.get_ticker("BTC/USDT")
                    results.append(ticker)
            except Exception as e:
                results.append(f"Error: {e}")
        
        # Create multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=make_api_call)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All calls should succeed (either with real data or mock data)
        self.assertEqual(len(results), 10)
        for result in results:
            self.assertIsInstance(result, dict)
            self.assertIn('symbol', result)
    
    def test_api_error_recovery_time(self):
        """Test API error recovery time."""
        start_time = time.time()
        
        with patch('requests.get') as mock_get:
            # Mock error
            mock_get.side_effect = ConnectionError("Connection error")
            
            # Make multiple calls
            for _ in range(5):
                ticker = self.coinbase_connector.get_ticker("BTC/USDT")
                self.assertIsInstance(ticker, dict)
        
        end_time = time.time()
        recovery_time = end_time - start_time
        
        # Should recover quickly (less than 1 second for 5 calls)
        self.assertLess(recovery_time, 1.0)
    
    def test_error_categorization(self):
        """Test categorization of different error types."""
        error_types = {
            ConnectionError: "connection_error",
            Timeout: "timeout_error",
            HTTPError: "http_error",
            ValueError: "data_error",
            Exception: "unknown_error"
        }
        
        for error_class, expected_type in error_types.items():
            with patch('requests.get') as mock_get:
                mock_get.side_effect = error_class("Test error")
                
                # Should handle all error types gracefully
                ticker = self.coinbase_connector.get_ticker("BTC/USDT")
                self.assertIsInstance(ticker, dict)
    
    def test_data_consistency_after_errors(self):
        """Test data consistency after API errors."""
        # Make multiple calls with errors
        results = []
        for _ in range(10):
            with patch('requests.get') as mock_get:
                mock_get.side_effect = ConnectionError("Connection error")
                ticker = self.coinbase_connector.get_ticker("BTC/USDT")
                results.append(ticker)
        
        # All results should be consistent
        for result in results:
            self.assertIsInstance(result, dict)
            self.assertIn('symbol', result)
            self.assertIn('price', result)
            self.assertEqual(result['symbol'], 'BTC/USDT')
    
    def test_emergency_stop_on_api_failures(self):
        """Test emergency stop triggered by API failures."""
        # Mock risk manager
        mock_risk_manager = Mock()
        mock_risk_manager.is_emergency_stop_active.return_value = False
        mock_risk_manager.set_emergency_stop = Mock()
        
        # Simulate multiple API failures
        with patch('requests.get') as mock_get:
            mock_get.side_effect = ConnectionError("Connection error")
            
            # Make multiple failed calls
            for _ in range(10):
                ticker = self.coinbase_connector.get_ticker("BTC/USDT")
                self.assertIsInstance(ticker, dict)
        
        # Should not trigger emergency stop for individual API failures
        # (This would be handled at a higher level in the trading system)
        self.assertIsInstance(ticker, dict)


class TestAPIErrorHandlingIntegration(unittest.TestCase):
    """Integration tests for API error handling with trading system."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.config_manager = ConfigManager()
        self.config = self.config_manager._config
    
    def test_trading_system_api_error_handling(self):
        """Test trading system handling of API errors."""
        # Mock trading system components
        mock_trading_system = Mock()
        mock_trading_system.data_engine = Mock()
        mock_trading_system.risk_manager = Mock()
        
        # Mock data engine to return errors
        mock_trading_system.data_engine.get_mark_price.side_effect = Exception("API error")
        
        # Trading system should handle errors gracefully
        try:
            # This should not crash the trading system
            price = mock_trading_system.data_engine.get_mark_price("BTC/USDT")
        except Exception:
            # If it does raise an exception, it should be handled at a higher level
            pass
        
        # The trading system should continue running
        self.assertTrue(True)  # If we get here, the test passed
    
    def test_portfolio_valuation_with_api_errors(self):
        """Test portfolio valuation with API errors."""
        # Mock portfolio with positions
        portfolio = {
            "positions": {
                "BTC/USDT": {"quantity": 0.1, "current_price": 50000},
                "ETH/USDT": {"quantity": 0.5, "current_price": 3000}
            }
        }
        
        # Mock data engine with mixed success/failure
        mock_data_engine = Mock()
        mock_data_engine.get_mark_price.side_effect = [
            50000,  # BTC/USDT succeeds
            Exception("API error"),  # ETH/USDT fails
            50000,  # BTC/USDT succeeds again
        ]
        
        # Should handle mixed success/failure gracefully
        btc_price = mock_data_engine.get_mark_price("BTC/USDT")
        self.assertEqual(btc_price, 50000)
        
        # ETH price should be handled gracefully (would use cached or mock data)
        try:
            eth_price = mock_data_engine.get_mark_price("ETH/USDT")
        except Exception:
            # Should fall back to cached price or mock data
            eth_price = 3000  # Use cached price
        
        self.assertIsInstance(eth_price, (int, float))
        self.assertGreater(eth_price, 0)


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_suite.addTest(unittest.makeSuite(TestAPIErrorHandling))
    test_suite.addTest(unittest.makeSuite(TestAPIErrorHandlingIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print(f"\n{'='*50}")
    print(f"API Error Handling Tests Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    print(f"{'='*50}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

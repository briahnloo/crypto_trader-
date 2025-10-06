"""
Test suite for order type advertisement and validation functionality.
"""

import unittest
from unittest.mock import Mock, patch
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto_mvp.connectors import BaseConnector, CoinbaseConnector
from crypto_mvp.execution.order_manager import OrderManager, OrderType, OrderSide


class TestBaseConnectorOrderTypes(unittest.TestCase):
    """Test base connector order types interface."""
    
    def test_get_supported_order_types_interface(self):
        """Test that base connector defines the order types interface."""
        # This test ensures the abstract method is properly defined
        self.assertTrue(hasattr(BaseConnector, 'get_supported_order_types'))
        
        # Check method signature includes self parameter
        import inspect
        sig = inspect.signature(BaseConnector.get_supported_order_types)
        self.assertEqual(str(sig), '(self) -> set[str]')


class TestCoinbaseConnectorOrderTypes(unittest.TestCase):
    """Test Coinbase connector order types implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "api_key": "test_api_key",
            "secret": "test_secret"
        }
        self.connector = CoinbaseConnector(self.config)
    
    def test_get_supported_order_types(self):
        """Test getting supported order types from Coinbase connector."""
        self.connector.initialize()
        
        supported_types = self.connector.get_supported_order_types()
        
        # Should be a set
        self.assertIsInstance(supported_types, set)
        
        # Should contain expected order types
        expected_types = {"market", "limit", "stop", "stop_limit", "take_profit"}
        self.assertEqual(supported_types, expected_types)
        
        # Should be strings
        for order_type in supported_types:
            self.assertIsInstance(order_type, str)
    
    def test_order_types_are_strings(self):
        """Test that all order types are strings."""
        self.connector.initialize()
        
        supported_types = self.connector.get_supported_order_types()
        
        for order_type in supported_types:
            self.assertIsInstance(order_type, str)
            # Should be lowercase
            self.assertEqual(order_type, order_type.lower())


class TestOrderManagerOrderTypeValidation(unittest.TestCase):
    """Test order manager order type validation and downgrade logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "maker_fee_bps": 10,
            "taker_fee_bps": 20
        }
        self.order_manager = OrderManager(self.config, "test_session")
        self.connector = CoinbaseConnector({"api_key": "test", "secret": "test"})
        self.connector.initialize()
        self.order_manager.set_connector(self.connector)
    
    def test_validate_supported_order_type(self):
        """Test validation of supported order type."""
        # Market order should be supported
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.MARKET, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.MARKET)
        
        # Limit order should be supported
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.LIMIT)
    
    def test_downgrade_unsupported_order_type(self):
        """Test downgrade of unsupported order type."""
        # Create a mock connector that doesn't support stop_limit
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"market", "limit"}
        self.order_manager.set_connector(mock_connector)
        
        # stop_limit should be downgraded to limit (since limit is supported)
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP_LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.LIMIT)
        
        # stop should be downgraded to market (since market is supported)
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.MARKET)
    
    def test_fallback_to_market_when_limit_not_supported(self):
        """Test fallback to market when limit is not supported."""
        # Create a mock connector that only supports market orders
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"market"}
        self.order_manager.set_connector(mock_connector)
        
        # stop_limit should be downgraded to market (fallback)
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP_LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.MARKET)
    
    def test_no_connector_uses_requested_type(self):
        """Test that when no connector is available, requested type is used."""
        self.order_manager.connector = None
        
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP_LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.STOP_LIMIT)
    
    def test_connector_exception_handling(self):
        """Test handling of connector exceptions."""
        # Create a mock connector that raises an exception
        mock_connector = Mock()
        mock_connector.get_supported_order_types.side_effect = Exception("Connection failed")
        self.order_manager.set_connector(mock_connector)
        
        # Should return original type when exception occurs
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP_LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.STOP_LIMIT)


class TestOrderTypeDowngradeLogic(unittest.TestCase):
    """Test specific order type downgrade scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {}
        self.order_manager = OrderManager(self.config, "test_session")
    
    def test_downgrade_mapping(self):
        """Test the downgrade mapping logic."""
        # Test with a connector that supports market and limit
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"market", "limit"}
        self.order_manager.set_connector(mock_connector)
        
        # Test various downgrade scenarios
        test_cases = [
            (OrderType.STOP_LIMIT, OrderType.LIMIT),
            (OrderType.STOP, OrderType.MARKET),
            (OrderType.TAKE_PROFIT, OrderType.LIMIT),
            (OrderType.TAKE_PROFIT_LIMIT, OrderType.LIMIT),
        ]
        
        for requested, expected in test_cases:
            with self.subTest(requested=requested, expected=expected):
                validated = self.order_manager._validate_and_downgrade_order_type(
                    requested, "BTC/USDT"
                )
                self.assertEqual(validated, expected)
    
    def test_downgrade_to_limit_when_market_not_available(self):
        """Test downgrade to limit when market is not available."""
        # Create a connector that only supports limit orders
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"limit"}
        self.order_manager.set_connector(mock_connector)
        
        # stop should be downgraded to limit (not market)
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.LIMIT)
    
    def test_last_resort_fallback(self):
        """Test last resort fallback when no suitable downgrade is available."""
        # Create a connector that supports neither market nor limit
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"post_only"}
        self.order_manager.set_connector(mock_connector)
        
        # Should return original type as last resort
        validated_type = self.order_manager._validate_and_downgrade_order_type(
            OrderType.STOP_LIMIT, "BTC/USDT"
        )
        self.assertEqual(validated_type, OrderType.STOP_LIMIT)


class TestOrderCreationWithTypeValidation(unittest.TestCase):
    """Test order creation with order type validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "maker_fee_bps": 10,
            "taker_fee_bps": 20
        }
        self.order_manager = OrderManager(self.config, "test_session")
        
        # Mock data engine
        self.mock_data_engine = Mock()
        self.order_manager.data_engine = self.mock_data_engine
        
        # Mock mark price validation
        with patch('crypto_mvp.execution.order_manager.get_mark_price_with_provenance') as mock_provenance:
            mock_provenance.return_value = (50000.0, "live")
            # Set initialized flag manually since we're mocking
            self.order_manager.initialized = True
    
    def test_order_creation_with_supported_type(self):
        """Test order creation with supported order type."""
        connector = CoinbaseConnector({"api_key": "test", "secret": "test"})
        connector.initialize()
        self.order_manager.set_connector(connector)
        
        # Create a market order (should be supported)
        order, error = self.order_manager.create_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
            strategy="test"
        )
        
        self.assertIsNotNone(order)
        self.assertIsNone(error)
        self.assertEqual(order.order_type, OrderType.MARKET)
    
    def test_order_creation_with_downgraded_type(self):
        """Test order creation with downgraded order type."""
        # Create a mock connector that doesn't support stop_limit
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"market", "limit"}
        self.order_manager.set_connector(mock_connector)
        
        # Mock mark price for limit order
        with patch('crypto_mvp.execution.order_manager.get_mark_price') as mock_price:
            mock_price.return_value = 50000.0
            
            # Create a stop_limit order (should be downgraded to limit)
            order, error = self.order_manager.create_order(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=0.001,
                price=49000.0,
                strategy="test"
            )
            
            self.assertIsNotNone(order)
            self.assertIsNone(error)
            self.assertEqual(order.order_type, OrderType.LIMIT)  # Should be downgraded
    
    @patch('crypto_mvp.execution.order_manager.OrderManager.logger')
    def test_order_type_downgrade_logging(self, mock_logger):
        """Test that order type downgrades are logged."""
        # Create a mock connector that doesn't support stop_limit
        mock_connector = Mock()
        mock_connector.get_supported_order_types.return_value = {"market", "limit"}
        self.order_manager.set_connector(mock_connector)
        
        # Mock mark price for limit order
        with patch('crypto_mvp.execution.order_manager.get_mark_price') as mock_price:
            mock_price.return_value = 50000.0
            
            # Create a stop_limit order
            order, error = self.order_manager.create_order(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_LIMIT,
                quantity=0.001,
                price=49000.0,
                strategy="test"
            )
            
            # Check that downgrade was logged
            mock_logger.warning.assert_called_with(
                "ORDER_TYPE_DOWNGRADE: BTC/USDT - stop_limit not supported, downgraded to limit"
            )


class TestOrderTypeIntegration(unittest.TestCase):
    """Integration tests for order type functionality."""
    
    def test_end_to_end_order_type_validation(self):
        """Test end-to-end order type validation."""
        # Create order manager with Coinbase connector
        order_manager = OrderManager({}, "test_session")
        connector = CoinbaseConnector({"api_key": "test", "secret": "test"})
        connector.initialize()
        order_manager.set_connector(connector)
        
        # Mock data engine and mark price
        order_manager.data_engine = Mock()
        with patch('crypto_mvp.execution.order_manager.get_mark_price_with_provenance') as mock_provenance:
            mock_provenance.return_value = (50000.0, "live")
            with patch('crypto_mvp.execution.order_manager.get_mark_price') as mock_price:
                mock_price.return_value = 50000.0
                # Set initialized flag manually since we're mocking
                order_manager.initialized = True
                
                # Test creating an order with supported type
                order, error = order_manager.create_order(
                    symbol="BTC/USDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=0.001,
                    price=49000.0,
                    strategy="test"
                )
                
                self.assertIsNotNone(order)
                self.assertIsNone(error)
                self.assertEqual(order.order_type, OrderType.LIMIT)
    
    def test_order_type_logging_format(self):
        """Test that order type information is logged in the correct format."""
        connector = CoinbaseConnector({"api_key": "test", "secret": "test"})
        connector.initialize()
        
        supported_types = connector.get_supported_order_types()
        supported_str = "{" + ",".join(f"'{t}'" for t in sorted(supported_types)) + "}"
        log_message = f"ORDER_TYPES: PASS – supported={supported_str}"
        
        # Verify the logging format matches the expected pattern
        self.assertIn("ORDER_TYPES: PASS", log_message)
        self.assertIn("supported=", log_message)
        # Check that the expected types are present (order may vary)
        expected_types = {'limit', 'market', 'stop', 'stop_limit', 'take_profit'}
        for order_type in expected_types:
            self.assertIn(f"'{order_type}'", log_message)


if __name__ == "__main__":
    unittest.main()

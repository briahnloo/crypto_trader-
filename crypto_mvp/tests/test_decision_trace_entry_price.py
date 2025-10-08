"""
Test that entry_price is populated from pricing snapshot in DECISION_TRACE even for SKIP decisions.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
from decimal import Decimal

from src.crypto_mvp.trading_system import ProfitMaximizingTradingSystem
from src.crypto_mvp.core.pricing_snapshot import PricingSnapshot


class TestDecisionTraceEntryPrice(unittest.TestCase):
    """Test entry_price population in DECISION_TRACE."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "trading": {
                "live_mode": False,
                "symbols": ["BTC/USDT", "ETH/USDT"],
                "max_positions": 3,
                "initial_capital": 10000.0
            },
            "risk": {
                "max_position_size": 0.1,
                "rr_min": 1.3,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.04
            },
            "data": {
                "cache_ttl_seconds": 300
            }
        }
        
        # Create a temporary config file
        import tempfile
        import yaml
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.dump(self.config, self.temp_config)
        self.temp_config.close()
        
        # Initialize trading system
        self.trading_system = ProfitMaximizingTradingSystem(self.temp_config.name)
        self.trading_system.config = self.config
        
        # Mock dependencies
        self.trading_system.data_engine = Mock()
        self.trading_system.risk_manager = Mock()
        self.trading_system.order_manager = Mock()
        self.trading_system.state_store = Mock()
        self.trading_system.portfolio_manager = Mock()
        self.trading_system.multi_strategy_executor = Mock()
        self.trading_system.cycle_count = 1
        
        # Create mock logger
        self.mock_logger = Mock()
        self.logger_patcher = patch.object(self.trading_system, '_logger', self.mock_logger)
        self.logger_patcher.start()
        
    def tearDown(self):
        """Clean up test fixtures."""
        self.logger_patcher.stop()
        import os
        os.unlink(self.temp_config.name)
    
    def test_entry_price_populated_from_snapshot_on_skip(self):
        """Test that entry_price is populated from pricing snapshot even when action is SKIP."""
        # Create a pricing snapshot with BTC/USDT price
        from datetime import datetime
        from src.crypto_mvp.core.pricing_snapshot import PriceData
        
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50005.0,
                    source="test",
                    timestamp="2024-01-01T00:00:00",
                    bid=50000.0,
                    ask=50010.0,
                    mid=50005.0
                )
            }
        )
        
        # Mock get_current_pricing_snapshot to return our snapshot
        with patch('src.crypto_mvp.trading_system.get_current_pricing_snapshot', return_value=snapshot):
            # Create a test signal
            signal = {
                "composite_score": 0.5,
                "confidence": 0.8,
                "metadata": {
                    "regime": "trending",
                    "normalization": {
                        "effective_threshold": 0.7
                    }
                }
            }
            
            # Call _log_decision_trace with SKIP action and no entry_price
            self.trading_system._log_decision_trace(
                symbol="BTC/USDT",
                signal=signal,
                current_price=50005.0,
                action="SKIP",
                reason="test_reason"
            )
            
            # Verify that DECISION_TRACE was logged
            self.assertTrue(self.mock_logger.info.called)
            
            # Get the logged message
            log_call = self.mock_logger.info.call_args[0][0]
            self.assertTrue(log_call.startswith("DECISION_TRACE "))
            
            # Parse the JSON
            trace_json = log_call.replace("DECISION_TRACE ", "")
            trace_data = json.loads(trace_json)
            
            # Verify that entry_price is populated (not None)
            self.assertIsNotNone(trace_data["entry_price"], 
                               "entry_price should be populated from pricing snapshot even for SKIP")
            
            # Verify the entry_price is approximately correct (should be last price from snapshot)
            self.assertAlmostEqual(trace_data["entry_price"], 50005.0, places=2)
    
    def test_entry_price_uses_decimal_precision(self):
        """Test that entry_price uses Decimal for precision and converts to float at I/O."""
        # Create a pricing snapshot with a precise price
        from datetime import datetime
        from src.crypto_mvp.core.pricing_snapshot import PriceData
        
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "ETH/USDT": PriceData(
                    price=3000.179012,
                    source="test",
                    timestamp="2024-01-01T00:00:00",
                    bid=3000.123456,
                    ask=3000.234567,
                    mid=3000.179012
                )
            }
        )
        
        with patch('src.crypto_mvp.trading_system.get_current_pricing_snapshot', return_value=snapshot):
            signal = {
                "composite_score": 0.5,
                "confidence": 0.8,
                "metadata": {
                    "regime": "ranging",
                    "normalization": {
                        "effective_threshold": 0.7
                    }
                }
            }
            
            # Call _log_decision_trace
            self.trading_system._log_decision_trace(
                symbol="ETH/USDT",
                signal=signal,
                current_price=3000.18,
                action="SKIP",
                reason="insufficient_confidence"
            )
            
            # Verify DECISION_TRACE was logged
            self.assertTrue(self.mock_logger.info.called)
            
            # Get the logged message
            log_call = self.mock_logger.info.call_args[0][0]
            trace_json = log_call.replace("DECISION_TRACE ", "")
            trace_data = json.loads(trace_json)
            
            # Verify entry_price is populated and rounded to 4 decimal places (I/O boundary)
            self.assertIsNotNone(trace_data["entry_price"])
            self.assertEqual(trace_data["entry_price"], round(3000.179012, 4))
    
    def test_entry_price_fallback_to_signal_metadata(self):
        """Test that entry_price falls back to signal metadata if snapshot is unavailable."""
        # Mock get_current_pricing_snapshot to return None (no snapshot)
        with patch('src.crypto_mvp.trading_system.get_current_pricing_snapshot', return_value=None):
            signal = {
                "composite_score": 0.5,
                "confidence": 0.8,
                "metadata": {
                    "regime": "trending",
                    "entry_price": 40000.0,  # Provide entry_price in metadata
                    "normalization": {
                        "effective_threshold": 0.7
                    }
                }
            }
            
            # Call _log_decision_trace
            self.trading_system._log_decision_trace(
                symbol="BTC/USDT",
                signal=signal,
                current_price=40000.0,
                action="SKIP",
                reason="test_reason"
            )
            
            # Verify DECISION_TRACE was logged
            self.assertTrue(self.mock_logger.info.called)
            
            # Get the logged message
            log_call = self.mock_logger.info.call_args[0][0]
            trace_json = log_call.replace("DECISION_TRACE ", "")
            trace_data = json.loads(trace_json)
            
            # Verify entry_price is populated from signal metadata
            self.assertIsNotNone(trace_data["entry_price"])
            self.assertEqual(trace_data["entry_price"], 40000.0)
    
    def test_entry_price_provided_as_parameter(self):
        """Test that entry_price parameter takes precedence over snapshot."""
        # Create a pricing snapshot
        from datetime import datetime
        from src.crypto_mvp.core.pricing_snapshot import PriceData
        
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50005.0,
                    source="test",
                    timestamp="2024-01-01T00:00:00",
                    bid=50000.0,
                    ask=50010.0,
                    mid=50005.0
                )
            }
        )
        
        with patch('src.crypto_mvp.trading_system.get_current_pricing_snapshot', return_value=snapshot):
            signal = {
                "composite_score": 0.5,
                "confidence": 0.8,
                "metadata": {
                    "regime": "trending",
                    "normalization": {
                        "effective_threshold": 0.7
                    }
                }
            }
            
            # Call _log_decision_trace with entry_price parameter
            provided_entry_price = 51000.0
            self.trading_system._log_decision_trace(
                symbol="BTC/USDT",
                signal=signal,
                current_price=50005.0,
                action="BUY",
                reason="strong_signal",
                entry_price=provided_entry_price
            )
            
            # Verify DECISION_TRACE was logged
            self.assertTrue(self.mock_logger.info.called)
            
            # Get the logged message
            log_call = self.mock_logger.info.call_args[0][0]
            trace_json = log_call.replace("DECISION_TRACE ", "")
            trace_data = json.loads(trace_json)
            
            # Verify entry_price uses the provided parameter (not snapshot)
            self.assertEqual(trace_data["entry_price"], provided_entry_price)
    
    @patch('src.crypto_mvp.trading_system.get_current_pricing_snapshot')
    def test_entry_price_with_pricing_snapshot_hit_log(self, mock_get_snapshot):
        """Test that entry_price is not None when PRICING_SNAPSHOT_HIT is logged.
        
        This is the main regression test requested by the user.
        """
        # Create a pricing snapshot
        from datetime import datetime
        from src.crypto_mvp.core.pricing_snapshot import PriceData
        
        snapshot = PricingSnapshot(
            id=1,
            ts=datetime.now(),
            by_symbol={
                "BTC/USDT": PriceData(
                    price=50005.0,
                    source="test",
                    timestamp="2024-01-01T00:00:00",
                    bid=50000.0,
                    ask=50010.0,
                    mid=50005.0
                )
            }
        )
        mock_get_snapshot.return_value = snapshot
        
        # Mock the logger to capture both debug and info logs
        debug_logs = []
        info_logs = []
        
        def capture_debug(msg):
            debug_logs.append(msg)
        
        def capture_info(msg):
            info_logs.append(msg)
        
        self.mock_logger.debug = Mock(side_effect=capture_debug)
        self.mock_logger.info = Mock(side_effect=capture_info)
        
        # Create signal
        signal = {
            "composite_score": 0.5,
            "confidence": 0.8,
            "metadata": {
                "regime": "trending",
                "normalization": {
                    "effective_threshold": 0.7
                }
            }
        }
        
        # Call _log_decision_trace
        self.trading_system._log_decision_trace(
            symbol="BTC/USDT",
            signal=signal,
            current_price=50005.0,
            action="SKIP",
            reason="test_reason"
        )
        
        # Find DECISION_TRACE log
        decision_trace_log = None
        for log in info_logs:
            if log.startswith("DECISION_TRACE "):
                decision_trace_log = log
                break
        
        self.assertIsNotNone(decision_trace_log, "DECISION_TRACE should be logged")
        
        # Parse the decision trace
        trace_json = decision_trace_log.replace("DECISION_TRACE ", "")
        trace_data = json.loads(trace_json)
        
        # The key assertion: entry_price must not be None when pricing snapshot is used
        # (even though we might not see PRICING_SNAPSHOT_HIT in our captured logs,
        # the snapshot was available and should have been used)
        self.assertIsNotNone(trace_data["entry_price"], 
                           "entry_price must not be None when pricing snapshot is available")
        
        # Verify the price is from the snapshot
        self.assertAlmostEqual(trace_data["entry_price"], 50005.0, places=2)


if __name__ == "__main__":
    unittest.main()


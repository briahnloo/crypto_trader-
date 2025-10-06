"""
Tests for the decision trace system.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime
import json


class TestDecisionTrace:
    """Test the decision trace system."""
    
    def _create_mock_trading_system(self):
        """Create a mock trading system for testing."""
        class MockTradingSystem:
            def __init__(self):
                self.logger = Mock()
                self.current_session_id = "test_session_123"
                self.cycle_count = 1
            
            def _determine_winning_subsignal(self, signal: dict) -> tuple[str, float]:
                """Determine the winning sub-signal from composite signal data."""
                try:
                    individual_signals = signal.get("individual_signals", {})
                    
                    if not individual_signals:
                        # No individual signals, composite gates the action
                        return "composite", signal.get("composite_score", 0.0)
                    
                    # Find the sub-signal with the highest weighted contribution
                    best_subsignal = None
                    best_score = 0.0
                    best_contribution = 0.0
                    
                    for name, subsignal in individual_signals.items():
                        if "error" in subsignal:
                            continue  # Skip failed signals
                            
                        raw_score = subsignal.get("score", 0.0)
                        confidence = subsignal.get("confidence", 0.0)
                        
                        # Calculate weighted contribution (score * confidence)
                        contribution = abs(raw_score) * confidence
                        
                        if contribution > best_contribution:
                            best_contribution = contribution
                            best_subsignal = name
                            best_score = raw_score
                    
                    if best_subsignal:
                        return best_subsignal, best_score
                    else:
                        # Fallback to composite if no valid sub-signals
                        return "composite", signal.get("composite_score", 0.0)
                        
                except Exception as e:
                    self.logger.warning(f"Failed to determine winning sub-signal: {e}")
                    return "composite", signal.get("composite_score", 0.0)
            
            def _log_decision_trace(self, symbol: str, signal: dict, current_price: float, 
                                   action: str, reason: str, entry_price: float = None, 
                                   stop_loss: float = None, take_profit: float = None, 
                                   size: float = None, winning_subsignal: str = None, 
                                   winning_score: float = None) -> None:
                """Log structured decision trace for a symbol."""
                try:
                    # Extract data from signal
                    composite_score = signal.get("composite_score", 0.0)
                    confidence = signal.get("confidence", 0.0)
                    regime = signal.get("metadata", {}).get("regime", "unknown")
                    effective_threshold = signal.get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.0)
                    
                    # Determine winning sub-signal if not provided
                    if winning_subsignal is None:
                        winning_subsignal, winning_score = self._determine_winning_subsignal(signal)
                    
                    # Create decision trace
                    decision_trace = {
                        "symbol": symbol,
                        "regime": regime,
                        "composite_score": round(composite_score, 4),
                        "threshold": round(effective_threshold, 4),
                        "confidence": round(confidence, 4),
                        "winning_subsignal": winning_subsignal,
                        "winning_score": round(winning_score, 4) if winning_score is not None else None,
                        "final_action": action,
                        "reason": reason,
                        "entry_price": round(entry_price, 4) if entry_price else None,
                        "stop_loss": round(stop_loss, 4) if stop_loss else None,
                        "take_profit": round(take_profit, 4) if take_profit else None,
                        "size": round(size, 6) if size else None
                    }
                    
                    # Log as structured JSON
                    trace_json = json.dumps(decision_trace, separators=(',', ':'))
                    self.logger.info(f"DECISION_TRACE {trace_json}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to log decision trace for {symbol}: {e}")
        
        return MockTradingSystem()
    
    def test_determine_winning_subsignal_with_individual_signals(self):
        """Test determining winning sub-signal from individual signals."""
        trading_system = self._create_mock_trading_system()
        
        # Create a composite signal with individual signals
        signal = {
            "composite_score": 0.75,
            "confidence": 0.8,
            "individual_signals": {
                "momentum": {
                    "score": 0.6,
                    "confidence": 0.7
                },
                "breakout": {
                    "score": 0.8,
                    "confidence": 0.9  # Highest contribution: 0.8 * 0.9 = 0.72
                },
                "arbitrage": {
                    "score": 0.5,
                    "confidence": 0.6
                }
            },
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.5
                }
            }
        }
        
        winning_subsignal, winning_score = trading_system._determine_winning_subsignal(signal)
        
        assert winning_subsignal == "breakout"
        assert winning_score == 0.8
    
    def test_determine_winning_subsignal_with_failed_signals(self):
        """Test determining winning sub-signal when some signals have errors."""
        trading_system = self._create_mock_trading_system()
        
        signal = {
            "composite_score": 0.6,
            "confidence": 0.7,
            "individual_signals": {
                "momentum": {
                    "score": 0.7,
                    "confidence": 0.8  # Highest contribution: 0.7 * 0.8 = 0.56
                },
                "breakout": {
                    "error": "Failed to analyze"
                },
                "arbitrage": {
                    "score": 0.5,
                    "confidence": 0.6
                }
            },
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.4
                }
            }
        }
        
        winning_subsignal, winning_score = trading_system._determine_winning_subsignal(signal)
        
        assert winning_subsignal == "momentum"
        assert winning_score == 0.7
    
    def test_determine_winning_subsignal_no_individual_signals(self):
        """Test determining winning sub-signal when no individual signals exist."""
        trading_system = self._create_mock_trading_system()
        
        signal = {
            "composite_score": 0.75,
            "confidence": 0.8,
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.5
                }
            }
        }
        
        winning_subsignal, winning_score = trading_system._determine_winning_subsignal(signal)
        
        assert winning_subsignal == "composite"
        assert winning_score == 0.75
    
    def test_log_decision_trace_with_winning_subsignal(self):
        """Test logging decision trace with winning sub-signal information."""
        trading_system = self._create_mock_trading_system()
        
        signal = {
            "composite_score": 0.75,
            "confidence": 0.8,
            "individual_signals": {
                "momentum": {
                    "score": 0.7,
                    "confidence": 0.8
                },
                "breakout": {
                    "score": 0.8,
                    "confidence": 0.9
                }
            },
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.5
                }
            }
        }
        
        # Log decision trace
        trading_system._log_decision_trace(
            symbol="BTC/USDT",
            signal=signal,
            current_price=50000.0,
            action="BUY",
            reason="executed",
            entry_price=50000.0,
            stop_loss=48000.0,
            take_profit=52000.0,
            size=0.1
        )
        
        # Verify the log was called
        assert trading_system.logger.info.called
        
        # Get the logged message
        log_call = trading_system.logger.info.call_args[0][0]
        assert log_call.startswith("DECISION_TRACE ")
        
        # Parse the JSON
        trace_json = log_call.replace("DECISION_TRACE ", "")
        trace_data = json.loads(trace_json)
        
        # Verify the trace contains all required fields
        assert trace_data["symbol"] == "BTC/USDT"
        assert trace_data["regime"] == "bull"
        assert trace_data["composite_score"] == 0.75
        assert trace_data["threshold"] == 0.5
        assert trace_data["confidence"] == 0.8
        assert trace_data["winning_subsignal"] == "breakout"  # Highest contribution
        assert trace_data["winning_score"] == 0.8
        assert trace_data["final_action"] == "BUY"
        assert trace_data["reason"] == "executed"
        assert trace_data["entry_price"] == 50000.0
        assert trace_data["stop_loss"] == 48000.0
        assert trace_data["take_profit"] == 52000.0
        assert trace_data["size"] == 0.1
    
    def test_log_decision_trace_execution_failure(self):
        """Test logging decision trace for execution failure."""
        trading_system = self._create_mock_trading_system()
        
        signal = {
            "composite_score": 0.75,
            "confidence": 0.8,
            "individual_signals": {
                "momentum": {
                    "score": 0.7,
                    "confidence": 0.8
                }
            },
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.5
                }
            }
        }
        
        # Log decision trace for execution failure
        trading_system._log_decision_trace(
            symbol="BTC/USDT",
            signal=signal,
            current_price=50000.0,
            action="SKIP",
            reason="execution_rejected:PRECISION_FAIL"
        )
        
        # Verify the log was called
        assert trading_system.logger.info.called
        
        # Get the logged message
        log_call = trading_system.logger.info.call_args[0][0]
        assert log_call.startswith("DECISION_TRACE ")
        
        # Parse the JSON
        trace_json = log_call.replace("DECISION_TRACE ", "")
        trace_data = json.loads(trace_json)
        
        # Verify the trace shows execution failure
        assert trace_data["symbol"] == "BTC/USDT"
        assert trace_data["winning_subsignal"] == "momentum"
        assert trace_data["winning_score"] == 0.7
        assert trace_data["final_action"] == "SKIP"
        assert trace_data["reason"] == "execution_rejected:PRECISION_FAIL"
        assert trace_data["entry_price"] is None
        assert trace_data["stop_loss"] is None
        assert trace_data["take_profit"] is None
        assert trace_data["size"] is None
    
    def test_log_decision_trace_composite_gates_action(self):
        """Test logging decision trace when composite gates the action."""
        trading_system = self._create_mock_trading_system()
        
        signal = {
            "composite_score": 0.75,
            "confidence": 0.8,
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.5
                }
            }
        }
        
        # Log decision trace with composite gating
        trading_system._log_decision_trace(
            symbol="BTC/USDT",
            signal=signal,
            current_price=50000.0,
            action="BUY",
            reason="executed",
            winning_subsignal="composite",  # Explicitly set
            winning_score=0.75
        )
        
        # Verify the log was called
        assert trading_system.logger.info.called
        
        # Get the logged message
        log_call = trading_system.logger.info.call_args[0][0]
        assert log_call.startswith("DECISION_TRACE ")
        
        # Parse the JSON
        trace_json = log_call.replace("DECISION_TRACE ", "")
        trace_data = json.loads(trace_json)
        
        # Verify the trace shows composite gating
        assert trace_data["symbol"] == "BTC/USDT"
        assert trace_data["winning_subsignal"] == "composite"
        assert trace_data["winning_score"] == 0.75
        assert trace_data["final_action"] == "BUY"
        assert trace_data["reason"] == "executed"
    
    def test_btc_composite_wins_execution_fails(self):
        """Test BTC case: composite wins, execution fails; trace shows winning_subsignal='momentum', reason='execution_rejected:PRECISION_FAIL'."""
        trading_system = self._create_mock_trading_system()
        
        # Create a composite signal where composite gates the action
        signal = {
            "composite_score": 0.85,  # Above threshold
            "confidence": 0.9,
            "individual_signals": {
                "momentum": {
                    "score": 0.6,
                    "confidence": 0.7  # Highest contribution: 0.6 * 0.7 = 0.42
                },
                "breakout": {
                    "score": 0.5,
                    "confidence": 0.6  # Contribution: 0.5 * 0.6 = 0.30
                }
            },
            "metadata": {
                "regime": "bull",
                "normalization": {
                    "effective_threshold": 0.6  # Composite score 0.85 > 0.6, so composite gates
                }
            }
        }
        
        # Log the decision trace for execution failure
        trading_system._log_decision_trace(
            symbol="BTC/USDT",
            signal=signal,
            current_price=50000.0,
            action="SKIP",
            reason="execution_rejected:PRECISION_FAIL"
        )
        
        # Verify the log was called
        assert trading_system.logger.info.called
        
        # Get the logged message
        log_call = trading_system.logger.info.call_args[0][0]
        assert log_call.startswith("DECISION_TRACE ")
        
        # Parse the JSON
        trace_json = log_call.replace("DECISION_TRACE ", "")
        trace_data = json.loads(trace_json)
        
        # Verify the trace shows the correct winning sub-signal and execution failure
        assert trace_data["symbol"] == "BTC/USDT"
        assert trace_data["winning_subsignal"] == "momentum"  # Highest contributing sub-signal
        assert trace_data["winning_score"] == 0.6
        assert trace_data["final_action"] == "SKIP"
        assert trace_data["reason"] == "execution_rejected:PRECISION_FAIL"

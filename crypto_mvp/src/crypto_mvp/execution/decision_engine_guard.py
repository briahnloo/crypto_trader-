"""
Decision engine guard for L2 mid price validation.

This module enforces strict requirements for decision-making:
- Top-of-book mid prices from same venue as execution
- Quote age validation (max 200ms)
- Best bid/ask availability validation
- Venue consistency checks
"""

import time
from typing import Optional, Dict, Any, Tuple
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class DecisionEngineGuard(LoggerMixin):
    """
    Guards decision engine with strict L2 mid price validation.
    
    Features:
    - Top-of-book mid price validation
    - Quote age enforcement (max 200ms)
    - Best bid/ask availability checks
    - Venue consistency validation
    - Stale tick detection and logging
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the decision engine guard.
        
        Args:
            config: Configuration dictionary with market_data settings
        """
        super().__init__()
        self.config = config
        
        # Market data settings
        market_data_config = config.get("market_data", {})
        self.require_l2_mid = market_data_config.get("require_l2_mid", True)
        self.max_quote_age_ms = market_data_config.get("max_quote_age_ms", 200)
        
        self.logger.info(f"DecisionEngineGuard initialized: require_l2_mid={self.require_l2_mid}, "
                        f"max_quote_age_ms={self.max_quote_age_ms}")
    
    def validate_decision_data(
        self,
        symbol: str,
        ticker_data: Optional[Dict[str, Any]],
        execution_venue: str = "default"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate decision data for trading decisions.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data with bid/ask and venue info
            execution_venue: Venue where execution will occur
            
        Returns:
            Tuple of (is_valid, reason, details_dict)
        """
        if not self.require_l2_mid:
            return True, "l2_mid_not_required", {"require_l2_mid": False}
        
        # Check if ticker data is available
        if not ticker_data:
            reason = "no_ticker_data"
            details = {
                "ticker_data": None,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason})")
            return False, reason, details
        
        # Validate ticker data structure
        required_fields = ["bid", "ask", "timestamp", "venue"]
        missing_fields = [field for field in required_fields if field not in ticker_data]
        if missing_fields:
            reason = "invalid_ticker_structure"
            details = {
                "missing_fields": missing_fields,
                "ticker_data": ticker_data,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, missing={missing_fields})")
            return False, reason, details
        
        bid = ticker_data.get("bid")
        ask = ticker_data.get("ask")
        timestamp = ticker_data.get("timestamp")
        venue = ticker_data.get("venue")
        
        # Validate bid/ask values
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
            reason = "invalid_bid_ask_values"
            details = {
                "bid": bid,
                "ask": ask,
                "bid_type": type(bid),
                "ask_type": type(ask),
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, bid={bid}, ask={ask})")
            return False, reason, details
        
        if bid <= 0 or ask <= 0:
            reason = "non_positive_bid_ask"
            details = {
                "bid": bid,
                "ask": ask,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, bid={bid}, ask={ask})")
            return False, reason, details
        
        if ask <= bid:
            reason = "ask_not_greater_than_bid"
            details = {
                "bid": bid,
                "ask": ask,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, bid={bid}, ask={ask})")
            return False, reason, details
        
        # Check venue consistency
        if venue != execution_venue:
            reason = "venue_mismatch"
            details = {
                "ticker_venue": venue,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, ticker_venue={venue}, execution_venue={execution_venue})")
            return False, reason, details
        
        # Check quote age
        quote_age_ms = self._get_quote_age_ms(timestamp)
        if quote_age_ms is None:
            reason = "invalid_timestamp"
            details = {
                "timestamp": timestamp,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, timestamp={timestamp})")
            return False, reason, details
        
        if quote_age_ms > self.max_quote_age_ms:
            reason = "stale_quote"
            details = {
                "quote_age_ms": quote_age_ms,
                "max_quote_age_ms": self.max_quote_age_ms,
                "timestamp": timestamp,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=decision_guard_{reason}, age={quote_age_ms}ms, max={self.max_quote_age_ms}ms)")
            return False, reason, details
        
        # Calculate L2 mid price
        l2_mid = (bid + ask) / 2
        
        # All checks passed
        details = {
            "l2_mid": l2_mid,
            "bid": bid,
            "ask": ask,
            "quote_age_ms": quote_age_ms,
            "venue": venue,
            "execution_venue": execution_venue,
            "stale_tick": False
        }
        
        self.logger.info(f"DECISION_DATA_OK: {symbol} l2_mid=${l2_mid:.4f} venue={venue} age={quote_age_ms}ms")
        return True, "valid", details
    
    def _get_quote_age_ms(self, timestamp: Any) -> Optional[float]:
        """
        Calculate quote age in milliseconds.
        
        Args:
            timestamp: Timestamp in various formats (Unix timestamp, datetime, etc.)
            
        Returns:
            Age in milliseconds or None if invalid
        """
        try:
            current_time = time.time()
            
            if isinstance(timestamp, (int, float)):
                # Unix timestamp (seconds)
                if timestamp > 1e10:  # Milliseconds timestamp
                    timestamp = timestamp / 1000
                quote_time = timestamp
            elif isinstance(timestamp, str):
                # Try to parse as ISO format or other common formats
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    quote_time = dt.timestamp()
                except ValueError:
                    # Try Unix timestamp as string
                    quote_time = float(timestamp)
                    if quote_time > 1e10:  # Milliseconds timestamp
                        quote_time = quote_time / 1000
            else:
                return None
            
            age_seconds = current_time - quote_time
            age_ms = age_seconds * 1000
            
            # Sanity check: age should be reasonable (not negative, not too old)
            if age_ms < 0 or age_ms > 3600000:  # More than 1 hour is suspicious
                return None
            
            return age_ms
            
        except (ValueError, TypeError, AttributeError) as e:
            self.logger.debug(f"Failed to parse timestamp {timestamp}: {e}")
            return None
    
    def get_decision_summary(
        self,
        symbol: str,
        ticker_data: Optional[Dict[str, Any]],
        execution_venue: str = "default"
    ) -> Dict[str, Any]:
        """
        Get decision data summary for a symbol.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data
            execution_venue: Execution venue
            
        Returns:
            Summary dictionary
        """
        if not ticker_data:
            return {
                "symbol": symbol,
                "status": "no_data",
                "l2_mid": None,
                "quote_age_ms": None,
                "venue": None,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
        
        try:
            bid = ticker_data.get("bid", 0)
            ask = ticker_data.get("ask", 0)
            timestamp = ticker_data.get("timestamp")
            venue = ticker_data.get("venue")
            
            if bid > 0 and ask > 0 and ask > bid:
                l2_mid = (bid + ask) / 2
                quote_age_ms = self._get_quote_age_ms(timestamp)
                venue_match = venue == execution_venue
                
                return {
                    "symbol": symbol,
                    "status": "valid" if venue_match and quote_age_ms and quote_age_ms <= self.max_quote_age_ms else "invalid",
                    "l2_mid": l2_mid,
                    "quote_age_ms": quote_age_ms,
                    "venue": venue,
                    "execution_venue": execution_venue,
                    "venue_match": venue_match,
                    "stale_tick": not (quote_age_ms and quote_age_ms <= self.max_quote_age_ms)
                }
            else:
                return {
                    "symbol": symbol,
                    "status": "invalid_data",
                    "l2_mid": None,
                    "quote_age_ms": None,
                    "venue": venue,
                    "execution_venue": execution_venue,
                    "stale_tick": True
                }
        except Exception as e:
            return {
                "symbol": symbol,
                "status": "error",
                "error": str(e),
                "l2_mid": None,
                "quote_age_ms": None,
                "venue": None,
                "execution_venue": execution_venue,
                "stale_tick": True
            }
    
    def validate_ticker_data(self, ticker_data: Dict[str, Any], execution_venue: str = "default") -> Tuple[bool, str]:
        """
        Validate ticker data structure and values for decision engine.
        
        Args:
            ticker_data: Ticker data to validate
            execution_venue: Execution venue
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(ticker_data, dict):
            return False, "ticker_data must be a dictionary"
        
        required_fields = ["bid", "ask", "timestamp", "venue"]
        for field in required_fields:
            if field not in ticker_data:
                return False, f"missing required field: {field}"
        
        bid = ticker_data["bid"]
        ask = ticker_data["ask"]
        venue = ticker_data["venue"]
        
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
            return False, "bid and ask must be numeric"
        
        if bid <= 0 or ask <= 0:
            return False, "bid and ask must be positive"
        
        if ask <= bid:
            return False, "ask must be greater than bid"
        
        if venue != execution_venue:
            return False, f"venue mismatch: ticker_venue={venue}, execution_venue={execution_venue}"
        
        return True, "valid"

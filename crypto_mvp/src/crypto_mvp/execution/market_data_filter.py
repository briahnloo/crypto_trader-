"""
Market data freshness and spread filter for trading decisions.

This module enforces market data quality requirements:
- Maximum spread in basis points
- Maximum quote age in milliseconds
- Validates ticker data before allowing trades
"""

import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class MarketDataFilter(LoggerMixin):
    """
    Filters trades based on market data quality.
    
    Enforces:
    - Maximum spread in basis points
    - Maximum quote age in milliseconds
    - Valid ticker data structure
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the market data filter.
        
        Args:
            config: Configuration dictionary with market_data settings
        """
        super().__init__()
        self.config = config
        
        # Market data settings
        market_data_config = config.get("market_data", {})
        self.max_spread_bps = market_data_config.get("max_spread_bps", 3)
        self.max_quote_age_ms = market_data_config.get("max_quote_age_ms", 200)
        
        self.logger.info(f"MarketDataFilter initialized: max_spread_bps={self.max_spread_bps}, "
                        f"max_quote_age_ms={self.max_quote_age_ms}")
    
    def should_skip_trade(
        self,
        symbol: str,
        ticker_data: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if trade should be skipped based on market data quality.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data with bid, ask, and timestamp
            
        Returns:
            Tuple of (should_skip, reason, details_dict)
        """
        # Check if ticker data is available
        if not ticker_data:
            reason = "no_ticker_data"
            details = {"ticker_data": None}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason})")
            return True, reason, details
        
        # Validate ticker data structure
        required_fields = ["bid", "ask", "timestamp"]
        missing_fields = [field for field in required_fields if field not in ticker_data]
        if missing_fields:
            reason = "invalid_ticker_structure"
            details = {"missing_fields": missing_fields, "ticker_data": ticker_data}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, missing={missing_fields})")
            return True, reason, details
        
        bid = ticker_data.get("bid")
        ask = ticker_data.get("ask")
        timestamp = ticker_data.get("timestamp")
        
        # Validate bid/ask values
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
            reason = "invalid_bid_ask_values"
            details = {"bid": bid, "ask": ask, "bid_type": type(bid), "ask_type": type(ask)}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, bid={bid}, ask={ask})")
            return True, reason, details
        
        if bid <= 0 or ask <= 0:
            reason = "non_positive_bid_ask"
            details = {"bid": bid, "ask": ask}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, bid={bid}, ask={ask})")
            return True, reason, details
        
        if ask <= bid:
            reason = "ask_not_greater_than_bid"
            details = {"bid": bid, "ask": ask}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, bid={bid}, ask={ask})")
            return True, reason, details
        
        # Check quote age
        quote_age_ms = self._get_quote_age_ms(timestamp)
        if quote_age_ms is None:
            reason = "invalid_timestamp"
            details = {"timestamp": timestamp}
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, timestamp={timestamp})")
            return True, reason, details
        
        if quote_age_ms > self.max_quote_age_ms:
            reason = "stale_quote"
            details = {
                "quote_age_ms": quote_age_ms,
                "max_quote_age_ms": self.max_quote_age_ms,
                "timestamp": timestamp
            }
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, age={quote_age_ms}ms, max={self.max_quote_age_ms}ms)")
            return True, reason, details
        
        # Calculate spread
        mid_price = (bid + ask) / 2
        spread_bps = ((ask - bid) / mid_price) * 10000  # Convert to basis points
        
        if spread_bps > self.max_spread_bps:
            reason = "spread_too_wide"
            details = {
                "spread_bps": spread_bps,
                "max_spread_bps": self.max_spread_bps,
                "bid": bid,
                "ask": ask,
                "mid_price": mid_price
            }
            self.logger.warning(f"REJECTED: {symbol} (reason={reason}, spread={spread_bps:.2f}bps, max={self.max_spread_bps}bps)")
            return True, reason, details
        
        # All checks passed
        details = {
            "spread_bps": spread_bps,
            "quote_age_ms": quote_age_ms,
            "bid": bid,
            "ask": ask,
            "mid_price": mid_price,
            "timestamp": timestamp
        }
        
        self.logger.info(f"MARKET_DATA_OK: {symbol} spread={spread_bps:.2f}bps age={quote_age_ms}ms")
        return False, "passed", details
    
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
            elif isinstance(timestamp, datetime):
                # Datetime object
                quote_time = timestamp.timestamp()
            elif isinstance(timestamp, str):
                # Try to parse as ISO format or other common formats
                try:
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
    
    def get_market_data_summary(self, symbol: str, ticker_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get market data summary for a symbol.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data
            
        Returns:
            Summary dictionary
        """
        if not ticker_data:
            return {
                "symbol": symbol,
                "status": "no_data",
                "spread_bps": None,
                "quote_age_ms": None,
                "bid": None,
                "ask": None
            }
        
        try:
            bid = ticker_data.get("bid", 0)
            ask = ticker_data.get("ask", 0)
            timestamp = ticker_data.get("timestamp")
            
            if bid > 0 and ask > 0 and ask > bid:
                mid_price = (bid + ask) / 2
                spread_bps = ((ask - bid) / mid_price) * 10000
                quote_age_ms = self._get_quote_age_ms(timestamp)
                
                return {
                    "symbol": symbol,
                    "status": "valid",
                    "spread_bps": spread_bps,
                    "quote_age_ms": quote_age_ms,
                    "bid": bid,
                    "ask": ask,
                    "mid_price": mid_price,
                    "timestamp": timestamp
                }
            else:
                return {
                    "symbol": symbol,
                    "status": "invalid_data",
                    "spread_bps": None,
                    "quote_age_ms": None,
                    "bid": bid,
                    "ask": ask
                }
        except Exception as e:
            return {
                "symbol": symbol,
                "status": "error",
                "error": str(e),
                "spread_bps": None,
                "quote_age_ms": None
            }
    
    def validate_ticker_data(self, ticker_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate ticker data structure and values.
        
        Args:
            ticker_data: Ticker data to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(ticker_data, dict):
            return False, "ticker_data must be a dictionary"
        
        required_fields = ["bid", "ask", "timestamp"]
        for field in required_fields:
            if field not in ticker_data:
                return False, f"missing required field: {field}"
        
        bid = ticker_data["bid"]
        ask = ticker_data["ask"]
        
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
            return False, "bid and ask must be numeric"
        
        if bid <= 0 or ask <= 0:
            return False, "bid and ask must be positive"
        
        if ask <= bid:
            return False, "ask must be greater than bid"
        
        return True, "valid"

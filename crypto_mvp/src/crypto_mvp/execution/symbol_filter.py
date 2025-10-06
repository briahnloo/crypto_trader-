"""
Symbol whitelist filter for trading universe management.

This module enforces a symbol whitelist to ensure only liquid trading pairs
are traded, with comprehensive logging of skip reasons for non-whitelisted symbols.
"""

from typing import List, Optional, Dict, Any, Tuple
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class SymbolFilter(LoggerMixin):
    """
    Filters trades based on symbol whitelist.
    
    Features:
    - Symbol whitelist enforcement
    - Comprehensive logging of skip reasons
    - Case-insensitive symbol matching
    - Universe management and statistics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the symbol filter.
        
        Args:
            config: Configuration dictionary with universe settings
        """
        super().__init__()
        self.config = config
        
        # Symbol whitelist settings
        trading_config = config.get("trading", {})
        self.whitelist = trading_config.get("symbol_whitelist", [])
        
        # Normalize whitelist symbols (uppercase for consistent matching)
        self.whitelist_normalized = [symbol.upper() for symbol in self.whitelist]
        
        self.logger.info(f"SymbolFilter initialized: whitelist={self.whitelist}")
    
    def is_symbol_allowed(self, symbol: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if a symbol is allowed for trading.
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            Tuple of (is_allowed, reason, details_dict)
        """
        if not symbol:
            reason = "empty_symbol"
            details = {"symbol": symbol, "whitelist": self.whitelist}
            self.logger.warning(f"REJECTED: {symbol} (reason=symbol_filter_{reason})")
            return False, reason, details
        
        # Normalize symbol for comparison
        symbol_normalized = symbol.upper()
        
        if symbol_normalized in self.whitelist_normalized:
            reason = "whitelisted"
            details = {
                "symbol": symbol,
                "symbol_normalized": symbol_normalized,
                "whitelist": self.whitelist,
                "whitelist_normalized": self.whitelist_normalized
            }
            self.logger.info(f"ALLOWED: {symbol} (reason=symbol_filter_{reason})")
            return True, reason, details
        else:
            reason = "not_whitelisted"
            details = {
                "symbol": symbol,
                "symbol_normalized": symbol_normalized,
                "whitelist": self.whitelist,
                "whitelist_normalized": self.whitelist_normalized
            }
            self.logger.warning(f"REJECTED: {symbol} (reason=symbol_filter_{reason})")
            return False, reason, details
    
    def should_skip_trade(
        self,
        symbol: str,
        side: str = "UNKNOWN",
        strategy: str = "unknown"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if trade should be skipped based on symbol whitelist.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            strategy: Strategy name
            
        Returns:
            Tuple of (should_skip, reason, details_dict)
        """
        is_allowed, reason, details = self.is_symbol_allowed(symbol)
        
        if is_allowed:
            return False, reason, details
        else:
            # Add additional context for skip decision
            skip_details = {
                **details,
                "side": side,
                "strategy": strategy,
                "skip_reason": f"symbol_filter_{reason}"
            }
            return True, reason, skip_details
    
    def get_whitelist(self) -> List[str]:
        """Get the current symbol whitelist."""
        return self.whitelist.copy()
    
    def get_whitelist_normalized(self) -> List[str]:
        """Get the normalized symbol whitelist."""
        return self.whitelist_normalized.copy()
    
    def is_whitelist_empty(self) -> bool:
        """Check if the whitelist is empty."""
        return len(self.whitelist) == 0
    
    def get_whitelist_size(self) -> int:
        """Get the number of symbols in the whitelist."""
        return len(self.whitelist)
    
    def get_universe_summary(self) -> Dict[str, Any]:
        """Get universe summary information."""
        return {
            "whitelist": self.whitelist,
            "whitelist_normalized": self.whitelist_normalized,
            "whitelist_size": len(self.whitelist),
            "is_empty": len(self.whitelist) == 0
        }
    
    def validate_symbol(self, symbol: str) -> Tuple[bool, str]:
        """
        Validate a symbol format.
        
        Args:
            symbol: Symbol to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not symbol:
            return False, "symbol cannot be empty"
        
        if not isinstance(symbol, str):
            return False, "symbol must be a string"
        
        # Basic format validation (should contain / for trading pairs)
        if "/" not in symbol:
            return False, "symbol should be in format BASE/QUOTE (e.g., BTC/USDT)"
        
        parts = symbol.split("/")
        if len(parts) != 2:
            return False, "symbol should have exactly one '/' separator"
        
        base, quote = parts
        if not base or not quote:
            return False, "both base and quote currencies must be non-empty"
        
        return True, "valid"
    
    def get_symbol_statistics(self, symbols_checked: List[str]) -> Dict[str, Any]:
        """
        Get statistics about symbol filtering.
        
        Args:
            symbols_checked: List of symbols that were checked
            
        Returns:
            Statistics dictionary
        """
        if not symbols_checked:
            return {
                "total_checked": 0,
                "allowed_count": 0,
                "rejected_count": 0,
                "allowed_symbols": [],
                "rejected_symbols": []
            }
        
        allowed_symbols = []
        rejected_symbols = []
        
        for symbol in symbols_checked:
            is_allowed, _, _ = self.is_symbol_allowed(symbol)
            if is_allowed:
                allowed_symbols.append(symbol)
            else:
                rejected_symbols.append(symbol)
        
        return {
            "total_checked": len(symbols_checked),
            "allowed_count": len(allowed_symbols),
            "rejected_count": len(rejected_symbols),
            "allowed_symbols": allowed_symbols,
            "rejected_symbols": rejected_symbols,
            "allowance_rate": len(allowed_symbols) / len(symbols_checked) if symbols_checked else 0.0
        }

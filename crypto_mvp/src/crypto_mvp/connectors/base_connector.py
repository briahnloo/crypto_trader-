"""
Base connector interface for exchange connections.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..core.logging_utils import LoggerMixin


@dataclass
class FeeInfo:
    """Fee information for a symbol."""
    symbol: str
    maker_fee_bps: float
    taker_fee_bps: float
    exchange: str
    last_updated: Optional[str] = None


class BaseConnector(ABC, LoggerMixin):
    """
    Base connector interface for exchange connections.
    
    All exchange connectors must implement this interface to provide
    consistent fee information and trading capabilities.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the connector.
        
        Args:
            config: Configuration dictionary for the connector
        """
        super().__init__()
        self.config = config
        self.exchange_name = config.get("name", "unknown")
        self.initialized = False
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the connector.
        
        Returns:
            True if initialization successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_fee_info(self, symbol: str, taker_or_maker: str = "taker") -> FeeInfo:
        """Get fee information for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            taker_or_maker: "taker" or "maker" to specify fee type
            
        Returns:
            FeeInfo object with fee details
            
        Raises:
            NotImplementedError: If connector doesn't support fee info
            ValueError: If symbol or fee type is invalid
        """
        pass
    
    @abstractmethod
    def get_supported_order_types(self) -> set[str]:
        """Get supported order types for this exchange.
        
        Returns:
            Set of supported order type strings (e.g., {"market", "limit", "stop_limit"})
            
        Raises:
            NotImplementedError: If connector doesn't support order type info
        """
        pass
    
    def get_exchange_fees(self) -> Dict[str, FeeInfo]:
        """Get exchange-wide fee information.
        
        Returns:
            Dictionary mapping symbols to FeeInfo objects
        """
        # Default implementation - can be overridden by connectors
        return {}
    
    def is_initialized(self) -> bool:
        """Check if connector is initialized.
        
        Returns:
            True if initialized, False otherwise
        """
        return self.initialized
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate symbol format.
        
        Args:
            symbol: Trading symbol to validate
            
        Returns:
            True if symbol format is valid, False otherwise
        """
        return "/" in symbol or "-" in symbol
    
    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format.
        
        Args:
            symbol: Trading symbol to normalize
            
        Returns:
            Normalized symbol
        """
        return symbol.replace("-", "/").upper()

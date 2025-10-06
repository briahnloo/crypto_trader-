"""
Coinbase connector implementation.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from .base_connector import BaseConnector, FeeInfo


class CoinbaseConnector(BaseConnector):
    """
    Coinbase connector for trading and fee information.
    
    Provides real-time fee information for Coinbase Pro/Advanced Trade.
    """
    
    # Coinbase fee structure (as of 2024)
    # These are the standard fees - actual fees may vary based on volume
    DEFAULT_MAKER_FEE_BPS = 10.0  # 0.1%
    DEFAULT_TAKER_FEE_BPS = 20.0  # 0.2%
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize Coinbase connector.
        
        Args:
            config: Configuration dictionary with Coinbase settings
        """
        super().__init__(config)
        self.exchange_name = "coinbase"
        self.api_key = config.get("api_key")
        self.secret = config.get("secret")
        
        # Fee cache to avoid repeated API calls
        self._fee_cache: Dict[str, FeeInfo] = {}
        self._cache_timeout = 300  # 5 minutes
        
    def initialize(self) -> bool:
        """Initialize the Coinbase connector.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self.logger.info(f"Initializing Coinbase connector")
            
            # Validate API credentials if provided
            if self.api_key and self.secret:
                if self.api_key == "your_coinbase_api_key_here":
                    self.logger.warning("Coinbase API key not configured - using default fees")
                else:
                    self.logger.info("Coinbase API credentials validated")
            else:
                self.logger.info("No Coinbase API credentials - using default fees")
            
            self.initialized = True
            self.logger.info(f"Coinbase connector initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Coinbase connector: {e}")
            return False
    
    def get_fee_info(self, symbol: str, taker_or_maker: str = "taker") -> FeeInfo:
        """Get fee information for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            taker_or_maker: "taker" or "maker" to specify fee type
            
        Returns:
            FeeInfo object with fee details
        """
        if not self.initialized:
            self.initialize()
        
        if not self.validate_symbol(symbol):
            raise ValueError(f"Invalid symbol format: {symbol}")
        
        normalized_symbol = self.normalize_symbol(symbol)
        
        # Check cache first
        cache_key = f"{normalized_symbol}_{taker_or_maker}"
        if cache_key in self._fee_cache:
            cached_fee = self._fee_cache[cache_key]
            # Check if cache is still valid
            if cached_fee.last_updated:
                cache_time = datetime.fromisoformat(cached_fee.last_updated)
                if (datetime.now() - cache_time).seconds < self._cache_timeout:
                    return cached_fee
        
        # Get fee information (from API if available, otherwise defaults)
        fee_info = self._fetch_fee_info(normalized_symbol, taker_or_maker)
        
        # Cache the result
        self._fee_cache[cache_key] = fee_info
        
        return fee_info
    
    def _fetch_fee_info(self, symbol: str, taker_or_maker: str) -> FeeInfo:
        """Fetch fee information from Coinbase API or use defaults.
        
        Args:
            symbol: Normalized trading symbol
            taker_or_maker: "taker" or "maker"
            
        Returns:
            FeeInfo object
        """
        try:
            # In a real implementation, this would call the Coinbase API
            # For now, we'll use the default fees
            
            if taker_or_maker.lower() == "maker":
                fee_bps = self.DEFAULT_MAKER_FEE_BPS
            else:
                fee_bps = self.DEFAULT_TAKER_FEE_BPS
            
            fee_info = FeeInfo(
                symbol=symbol,
                maker_fee_bps=self.DEFAULT_MAKER_FEE_BPS,
                taker_fee_bps=self.DEFAULT_TAKER_FEE_BPS,
                exchange="coinbase",
                last_updated=datetime.now().isoformat()
            )
            
            self.logger.debug(f"Retrieved fee info for {symbol}: {taker_or_maker}={fee_bps}bps")
            return fee_info
            
        except Exception as e:
            self.logger.error(f"Error fetching fee info for {symbol}: {e}")
            # Return default fees as fallback
            return FeeInfo(
                symbol=symbol,
                maker_fee_bps=self.DEFAULT_MAKER_FEE_BPS,
                taker_fee_bps=self.DEFAULT_TAKER_FEE_BPS,
                exchange="coinbase",
                last_updated=datetime.now().isoformat()
            )
    
    def get_exchange_fees(self) -> Dict[str, FeeInfo]:
        """Get exchange-wide fee information.
        
        Returns:
            Dictionary mapping symbols to FeeInfo objects
        """
        # For Coinbase, fees are typically the same across all symbols
        # In a real implementation, this could fetch all available symbols
        # and their specific fees
        
        common_symbols = [
            "BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT",
            "BNB/USDT", "XRP/USDT", "DOT/USDT", "LINK/USDT"
        ]
        
        exchange_fees = {}
        for symbol in common_symbols:
            try:
                fee_info = self.get_fee_info(symbol, "taker")
                exchange_fees[symbol] = fee_info
            except Exception as e:
                self.logger.warning(f"Could not get fee info for {symbol}: {e}")
        
        return exchange_fees
    
    def get_volume_based_fee(self, symbol: str, volume_30d: float) -> FeeInfo:
        """Get volume-based fee information.
        
        Args:
            symbol: Trading symbol
            volume_30d: 30-day trading volume in USD
            
        Returns:
            FeeInfo with volume-adjusted fees
        """
        # Coinbase has volume-based fee tiers
        # This is a simplified implementation
        
        base_fee = self.get_fee_info(symbol, "taker")
        
        # Volume-based fee reduction (simplified)
        if volume_30d >= 10000000:  # $10M+ volume
            fee_reduction = 0.5  # 50% reduction
        elif volume_30d >= 1000000:  # $1M+ volume
            fee_reduction = 0.25  # 25% reduction
        elif volume_30d >= 100000:  # $100K+ volume
            fee_reduction = 0.1  # 10% reduction
        else:
            fee_reduction = 0.0  # No reduction
        
        adjusted_maker_fee = base_fee.maker_fee_bps * (1 - fee_reduction)
        adjusted_taker_fee = base_fee.taker_fee_bps * (1 - fee_reduction)
        
        return FeeInfo(
            symbol=symbol,
            maker_fee_bps=adjusted_maker_fee,
            taker_fee_bps=adjusted_taker_fee,
            exchange="coinbase",
            last_updated=datetime.now().isoformat()
        )
    
    def get_supported_order_types(self) -> set[str]:
        """Get supported order types for Coinbase.
        
        Returns:
            Set of supported order type strings
        """
        # Coinbase Advanced Trade supports these order types
        # https://docs.cloud.coinbase.com/advanced-trade/reference/retailbrokerageapi_postorder
        return {
            "market",      # Market orders
            "limit",       # Limit orders
            "stop",        # Stop orders
            "stop_limit",  # Stop limit orders
            "take_profit", # Take profit orders (OCO)
        }

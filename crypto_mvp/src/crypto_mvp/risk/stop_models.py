"""
Stop Loss and Take Profit models with ATR-based calculation and safe fallbacks.
"""

import math
from typing import Optional, Dict, Any, Tuple, Union
from decimal import Decimal, getcontext
from crypto_mvp.core.logging_utils import LoggerMixin
from crypto_mvp.indicators.atr_service import ATRService

# Set decimal precision
getcontext().prec = 28


class StopModel(LoggerMixin):
    """
    Stop Loss and Take Profit calculation with ATR-based distance and fallbacks.
    
    Features:
    - ATR-based SL/TP distance calculation
    - Safe fallback to percent-based when ATR unavailable
    - Tick-size rounding for all prices
    - Comprehensive logging with fallback notifications
    - Ensures SL/TP never equal entry price
    """
    
    def __init__(self, config: Dict[str, Any], atr_service: Optional[ATRService] = None):
        """Initialize the stop model.
        
        Args:
            config: Configuration dictionary with stop model settings
            atr_service: ATR service instance
        """
        super().__init__()
        self.config = config
        self.atr_service = atr_service
        
        # Get SL/TP configuration
        sl_tp_config = config.get("risk", {}).get("sl_tp", {})
        
        # ATR multipliers
        self.atr_mult_sl = Decimal(str(sl_tp_config.get("atr_mult_sl", 1.2)))
        self.atr_mult_tp = Decimal(str(sl_tp_config.get("atr_mult_tp", 2.0)))
        
        # Fallback percentages - use fallback_stop_frac from risk config if available
        risk_config = config.get("risk", {})
        fallback_stop_frac = Decimal(str(risk_config.get("fallback_stop_frac", 0.005)))  # 0.5% default
        
        self.fallback_pct_sl = Decimal(str(sl_tp_config.get("fallback_pct_sl", fallback_stop_frac)))
        self.fallback_pct_tp = Decimal(str(sl_tp_config.get("fallback_pct_tp", fallback_stop_frac * 2)))  # 2x for TP
        
        # Absolute guardrails for small-price assets
        self.min_sl_abs = Decimal(str(sl_tp_config.get("min_sl_abs", 0.001)))
        self.min_tp_abs = Decimal(str(sl_tp_config.get("min_tp_abs", 0.002)))
        
        # Track fallback usage per symbol per cycle
        self._fallback_logged = set()
        
        self.logger.info(f"StopModel initialized: ATR_multipliers=({self.atr_mult_sl}, {self.atr_mult_tp}), "
                        f"fallback_pct=({self.fallback_pct_sl:.1%}, {self.fallback_pct_tp:.1%})")
    
    def calculate_stop_take_profit(
        self,
        symbol: str,
        entry_price: Union[float, Decimal],
        side: str,
        data_engine: Optional[Any] = None,
        symbol_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        """
        Calculate stop loss and take profit prices.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            side: Order side ("BUY" or "SELL")
            data_engine: Data engine for ATR calculation
            symbol_info: Symbol information with tick_size, etc.
            
        Returns:
            Tuple of (stop_loss, take_profit, metadata)
        """
        entry_decimal = Decimal(str(entry_price)) if not isinstance(entry_price, Decimal) else entry_price
        
        if entry_decimal <= 0:
            self.logger.warning(f"Invalid entry price for {symbol}: {entry_decimal}")
            return None, None, {"error": "invalid_entry_price"}
        
        # Get symbol info with defaults
        if symbol_info is None:
            symbol_info = self._get_default_symbol_info(symbol)
        
        tick_size = Decimal(str(symbol_info.get("tick_size", 0.01)))
        
        # Try to get ATR-based distances
        sl_distance, tp_distance, atr_value = self._get_atr_based_distances(
            symbol, entry_decimal, data_engine
        )
        
        # Calculate SL/TP prices
        if side.upper() == "BUY":
            stop_loss = entry_decimal - sl_distance
            take_profit = entry_decimal + tp_distance
        else:  # SELL
            stop_loss = entry_decimal + sl_distance
            take_profit = entry_decimal - tp_distance
        
        # Ensure SL/TP are never equal to entry
        if abs(stop_loss - entry_decimal) < tick_size:
            stop_loss = entry_decimal + (tick_size if side.upper() == "SELL" else -tick_size)
        
        if abs(take_profit - entry_decimal) < tick_size:
            take_profit = entry_decimal + (tick_size if side.upper() == "BUY" else -tick_size)
        
        # Round to tick size
        stop_loss = self._round_to_tick(stop_loss, tick_size)
        take_profit = self._round_to_tick(take_profit, tick_size)
        
        # Prepare metadata
        metadata = {
            "atr_value": float(atr_value) if atr_value is not None else None,
            "atr_based": atr_value is not None,
            "sl_distance": float(sl_distance),
            "tp_distance": float(tp_distance),
            "tick_size": float(tick_size),
            "fallback_used": atr_value is None
        }
        
        return float(stop_loss), float(take_profit), metadata
    
    def _get_atr_based_distances(
        self,
        symbol: str,
        entry_price: Decimal,
        data_engine: Optional[Any]
    ) -> Tuple[Decimal, Decimal, Optional[Decimal]]:
        """
        Get ATR-based stop loss and take profit distances.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            data_engine: Data engine for ATR calculation
            
        Returns:
            Tuple of (sl_distance, tp_distance, atr_value)
        """
        atr_value = None
        
        # Try to get ATR from service
        if self.atr_service and data_engine:
            atr_raw = self.atr_service.get_atr(symbol, data_engine)
            atr_value = Decimal(str(atr_raw)) if atr_raw is not None else None
        
        if atr_value is not None and atr_value > 0:
            # Use ATR-based distances
            sl_distance = atr_value * self.atr_mult_sl
            tp_distance = atr_value * self.atr_mult_tp
            
            self.logger.debug(f"ATR-based distances for {symbol}: SL={sl_distance:.6f}, TP={tp_distance:.6f} (ATR={atr_value:.6f})")
            
            return sl_distance, tp_distance, atr_value
        else:
            # Fallback to percent-based distances
            sl_distance = entry_price * self.fallback_pct_sl
            tp_distance = entry_price * self.fallback_pct_tp
            
            # Apply absolute minimums for small-price assets
            sl_distance = max(sl_distance, self.min_sl_abs)
            tp_distance = max(tp_distance, self.min_tp_abs)
            
            # Log fallback usage once per symbol per cycle
            fallback_key = f"{symbol}_{self.fallback_pct_sl:.4f}"
            if fallback_key not in self._fallback_logged:
                self.logger.info(f"STOP FALLBACK {symbol}: using percent stop {self.fallback_pct_sl:.4%} (ATR unavailable)")
                self._fallback_logged.add(fallback_key)
            
            self.logger.debug(f"Fallback distances for {symbol}: SL={sl_distance:.6f}, TP={tp_distance:.6f} (percent-based)")
            
            return sl_distance, tp_distance, None
    
    def _get_default_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get default symbol information.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with symbol information
        """
        symbol_info_map = {
            "BTC/USDT": {
                "tick_size": Decimal('0.01'),
                "step_size": Decimal('0.001'),
                "min_notional": Decimal('10.0'),
                "supports_short": True
            },
            "ETH/USDT": {
                "tick_size": Decimal('0.01'),
                "step_size": Decimal('0.001'),
                "min_notional": Decimal('10.0'),
                "supports_short": True
            },
            "BNB/USDT": {
                "tick_size": Decimal('0.01'),
                "step_size": Decimal('0.001'),
                "min_notional": Decimal('10.0'),
                "supports_short": True
            },
            "ADA/USDT": {
                "tick_size": Decimal('0.0001'),
                "step_size": Decimal('0.1'),
                "min_notional": Decimal('10.0'),
                "supports_short": True
            },
            "SOL/USDT": {
                "tick_size": Decimal('0.01'),
                "step_size": Decimal('0.001'),
                "min_notional": Decimal('10.0'),
                "supports_short": True
            }
        }
        
        return symbol_info_map.get(symbol, {
            "tick_size": Decimal('0.01'),
            "step_size": Decimal('0.001'),
            "min_notional": Decimal('10.0'),
            "supports_short": True
        })
    
    def _round_to_tick(self, price: Decimal, tick_size: Decimal) -> Decimal:
        """Round price to tick size.
        
        Args:
            price: Price to round
            tick_size: Tick size
            
        Returns:
            Rounded price
        """
        if tick_size <= 0:
            return price
        
        return (price / tick_size).quantize(Decimal('1')) * tick_size
    
    def reset_fallback_logging(self):
        """Reset fallback logging for new cycle."""
        self._fallback_logged.clear()
        self.logger.debug("Reset fallback logging for new cycle")
    
    def get_fallback_stats(self) -> Dict[str, Any]:
        """Get fallback usage statistics.
        
        Returns:
            Dictionary with fallback statistics
        """
        return {
            "fallback_logged_count": len(self._fallback_logged),
            "fallback_symbols": list(self._fallback_logged),
            "atr_multipliers": {"sl": float(self.atr_mult_sl), "tp": float(self.atr_mult_tp)},
            "fallback_percentages": {"sl": float(self.fallback_pct_sl), "tp": float(self.fallback_pct_tp)}
        }

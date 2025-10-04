"""
Risk-per-trade sizing calculator for position sizing based on stop-loss distance.

This module calculates position size based on:
- Risk budget (percentage of equity)
- Current stop-loss distance from OCO orders
- Cap on maximum position size (never increase exposure)
"""

import math
from typing import Optional, Dict, Any, Tuple
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class RiskSizingCalculator(LoggerMixin):
    """
    Calculates position size based on risk-per-trade and stop-loss distance.
    
    Features:
    - Risk budget calculation (percentage of equity)
    - Stop-loss distance from OCO orders
    - Position size capping (never increase exposure)
    - Comprehensive logging of sizing decisions
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the risk sizing calculator.
        
        Args:
            config: Configuration dictionary with risk settings
        """
        super().__init__()
        self.config = config
        
        # Risk sizing settings
        risk_config = config.get("risk", {})
        self.risk_per_trade_pct = risk_config.get("risk_per_trade_pct", 0.10)
        self.allow_upsize = risk_config.get("allow_upsize", False)
        
        self.logger.info(f"RiskSizingCalculator initialized: risk_per_trade_pct={self.risk_per_trade_pct}%, "
                        f"allow_upsize={self.allow_upsize}")
    
    def calculate_position_size(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        equity: float,
        current_default_size: float,
        oco_manager: Optional[Any] = None
    ) -> Tuple[float, str, Dict[str, Any]]:
        """
        Calculate position size based on risk-per-trade and stop-loss distance.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price for the trade
            equity: Current portfolio equity
            current_default_size: Current default position size
            oco_manager: OCO manager instance to get stop-loss distance
            
        Returns:
            Tuple of (position_size, reason, details_dict)
        """
        # Calculate risk budget
        risk_budget = equity * (self.risk_per_trade_pct / 100.0)
        
        # Get stop-loss distance from OCO orders
        sl_distance = self._get_stop_loss_distance(symbol, side, entry_price, oco_manager)
        
        if sl_distance is None or sl_distance <= 0 or math.isnan(sl_distance):
            reason = "no_valid_sl_distance"
            details = {
                "risk_budget": risk_budget,
                "sl_distance": sl_distance,
                "current_default_size": current_default_size,
                "calculated_size": 0.0,
                "applied_size": 0.0
            }
            self.logger.warning(f"REJECTED: {symbol} {side} (reason=risk_sizing_{reason})")
            return 0.0, reason, details
        
        # Calculate position size based on risk budget and stop-loss distance
        calculated_size = risk_budget / sl_distance
        
        # Apply size cap if not allowing upsize
        if not self.allow_upsize and calculated_size > current_default_size:
            applied_size = current_default_size
            reason = "capped_at_current_size"
        else:
            applied_size = calculated_size
            reason = "risk_based_size"
        
        details = {
            "risk_budget": risk_budget,
            "sl_distance": sl_distance,
            "current_default_size": current_default_size,
            "calculated_size": calculated_size,
            "applied_size": applied_size,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "allow_upsize": self.allow_upsize
        }
        
        self.logger.info(
            f"RISK_SIZING: {symbol} {side} calc_size={calculated_size:.6f} "
            f"applied_size={applied_size:.6f} reason={reason} "
            f"risk_budget=${risk_budget:.2f} sl_distance=${sl_distance:.4f}"
        )
        
        return applied_size, reason, details
    
    def _get_stop_loss_distance(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        oco_manager: Optional[Any]
    ) -> Optional[float]:
        """
        Get stop-loss distance from OCO orders.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            oco_manager: OCO manager instance
            
        Returns:
            Stop-loss distance or None if not available
        """
        if not oco_manager:
            return None
        
        try:
            # Get active OCO orders for this symbol
            active_orders = oco_manager.get_active_oco_orders()
            
            # Find OCO order for this symbol and side
            for fill_id, oco_order in active_orders.items():
                if oco_order.symbol == symbol and oco_order.side == side:
                    # Calculate stop-loss distance
                    if side.upper() == "BUY":
                        sl_distance = entry_price - oco_order.stop_loss
                    else:  # SELL
                        sl_distance = oco_order.stop_loss - entry_price
                    
                    # Ensure positive distance
                    if sl_distance > 0:
                        return sl_distance
            
            # No active OCO order found, return None
            return None
            
        except Exception as e:
            self.logger.warning(f"Failed to get stop-loss distance for {symbol}: {e}")
            return None
    
    def get_risk_sizing_summary(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        equity: float,
        current_default_size: float,
        oco_manager: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Get risk sizing summary for a symbol.
        
        Args:
            symbol: Trading symbol
            side: Order side
            entry_price: Entry price
            equity: Portfolio equity
            current_default_size: Current default size
            oco_manager: OCO manager instance
            
        Returns:
            Summary dictionary
        """
        risk_budget = equity * (self.risk_per_trade_pct / 100.0)
        sl_distance = self._get_stop_loss_distance(symbol, side, entry_price, oco_manager)
        
        if sl_distance and sl_distance > 0 and not math.isnan(sl_distance):
            calculated_size = risk_budget / sl_distance
            applied_size = min(calculated_size, current_default_size) if not self.allow_upsize else calculated_size
            status = "valid"
        else:
            calculated_size = 0.0
            applied_size = 0.0
            status = "no_sl_distance"
        
        return {
            "symbol": symbol,
            "side": side,
            "status": status,
            "risk_budget": risk_budget,
            "sl_distance": sl_distance,
            "calculated_size": calculated_size,
            "applied_size": applied_size,
            "current_default_size": current_default_size,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "allow_upsize": self.allow_upsize
        }
    
    def validate_risk_sizing(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        equity: float,
        current_default_size: float,
        oco_manager: Optional[Any] = None
    ) -> Tuple[bool, str]:
        """
        Validate if risk sizing can be calculated.
        
        Args:
            symbol: Trading symbol
            side: Order side
            entry_price: Entry price
            equity: Portfolio equity
            current_default_size: Current default size
            oco_manager: OCO manager instance
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if equity <= 0:
            return False, "equity must be positive"
        
        if entry_price <= 0:
            return False, "entry_price must be positive"
        
        if current_default_size <= 0:
            return False, "current_default_size must be positive"
        
        sl_distance = self._get_stop_loss_distance(symbol, side, entry_price, oco_manager)
        if not sl_distance or sl_distance <= 0 or math.isnan(sl_distance):
            return False, "no valid stop-loss distance available"
        
        return True, "valid"

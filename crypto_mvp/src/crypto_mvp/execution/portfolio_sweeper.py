"""
Portfolio sweeper for managing OCO orders and protective exits.

This module runs each cycle to:
1. Attach OCO orders to positions missing them
2. Tighten TP/SL when ATR shrinks by >50% since entry
3. Flatten positions with unrealized P&L < -0.6*SL distance (slippage shock)
"""

import math
from typing import Optional, Dict, Any, List, Tuple, Callable
import logging
from datetime import datetime

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class PortfolioSweeper(LoggerMixin):
    """
    Portfolio sweeper for managing OCO orders and protective exits.
    
    Features:
    - Attach OCO to positions missing them
    - Tighten TP/SL when ATR shrinks by >50%
    - Protective exits for slippage shock
    - Comprehensive logging of all actions
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the portfolio sweeper.
        
        Args:
            config: Configuration dictionary with risk settings
        """
        super().__init__()
        self.config = config
        
        # Risk settings
        risk_config = config.get("risk", {})
        self.oco_enabled = risk_config.get("oco_enabled", True)
        self.tp_atr = risk_config.get("tp_atr", 0.7)
        self.sl_atr = risk_config.get("sl_atr", 0.5)
        self.atr_shrink_threshold = 0.5  # 50% ATR shrink threshold
        self.slippage_shock_threshold = 0.6  # -0.6 * SL distance threshold
        
        # Callbacks for external functions
        self.get_positions_callback: Optional[Callable[[], List[Dict[str, Any]]]] = None
        self.get_oco_orders_callback: Optional[Callable[[], Dict[str, Any]]] = None
        self.get_atr_callback: Optional[Callable[[str], Optional[float]]] = None
        self.get_mark_price_callback: Optional[Callable[[str], Optional[float]]] = None
        self.create_oco_callback: Optional[Callable[[str, str, float, float, float, float, str], Optional[str]]] = None
        self.update_oco_callback: Optional[Callable[[str, float, float], bool]] = None
        self.flatten_position_callback: Optional[Callable[[str, str, float], bool]] = None
        
        self.logger.info(f"PortfolioSweeper initialized: oco_enabled={self.oco_enabled}, "
                        f"tp_atr={self.tp_atr}, sl_atr={self.sl_atr}, "
                        f"atr_shrink_threshold={self.atr_shrink_threshold}, "
                        f"slippage_shock_threshold={self.slippage_shock_threshold}")
    
    def set_callbacks(
        self,
        get_positions_callback: Callable[[], List[Dict[str, Any]]],
        get_oco_orders_callback: Callable[[], Dict[str, Any]],
        get_atr_callback: Callable[[str], Optional[float]],
        get_mark_price_callback: Callable[[str], Optional[float]],
        create_oco_callback: Callable[[str, str, float, float, float, float, str], Optional[str]],
        update_oco_callback: Callable[[str, float, float], bool],
        flatten_position_callback: Callable[[str, str, float], bool]
    ):
        """Set callback functions for external operations."""
        self.get_positions_callback = get_positions_callback
        self.get_oco_orders_callback = get_oco_orders_callback
        self.get_atr_callback = get_atr_callback
        self.get_mark_price_callback = get_mark_price_callback
        self.create_oco_callback = create_oco_callback
        self.update_oco_callback = update_oco_callback
        self.flatten_position_callback = flatten_position_callback
        self.logger.info("Portfolio sweeper callbacks set")
    
    def sweep_portfolio(self) -> Dict[str, Any]:
        """
        Perform portfolio sweep operations.
        
        Returns:
            Dictionary with sweep results and statistics
        """
        if not self._validate_callbacks():
            return {"error": "Missing required callbacks", "actions_taken": 0}
        
        sweep_results = {
            "timestamp": datetime.now(),
            "oco_attached": 0,
            "oco_updated": 0,
            "protective_exits": 0,
            "errors": 0,
            "actions_taken": 0,
            "details": []
        }
        
        try:
            # Get current positions and OCO orders
            positions = self.get_positions_callback()
            oco_orders = self.get_oco_orders_callback()
            
            if not positions:
                self.logger.info("No positions found for portfolio sweep")
                return sweep_results
            
            self.logger.info(f"Portfolio sweep: {len(positions)} positions, {len(oco_orders)} OCO orders")
            
            # Process each position
            for position in positions:
                try:
                    result = self._process_position(position, oco_orders)
                    if result:
                        sweep_results["details"].append(result)
                        sweep_results["actions_taken"] += 1
                        
                        if result["action"] == "oco_attached":
                            sweep_results["oco_attached"] += 1
                        elif result["action"] == "oco_updated":
                            sweep_results["oco_updated"] += 1
                        elif result["action"] == "protective_exit":
                            sweep_results["protective_exits"] += 1
                        elif result["action"] == "error":
                            sweep_results["errors"] += 1
                            
                except Exception as e:
                    self.logger.error(f"Error processing position {position.get('symbol', 'unknown')}: {e}")
                    sweep_results["errors"] += 1
                    sweep_results["actions_taken"] += 1
                    sweep_results["details"].append({
                        "symbol": position.get("symbol", "unknown"),
                        "action": "error",
                        "error": str(e)
                    })
            
            # Log summary
            self.logger.info(
                f"Portfolio sweep completed: {sweep_results['oco_attached']} OCO attached, "
                f"{sweep_results['oco_updated']} OCO updated, "
                f"{sweep_results['protective_exits']} protective exits, "
                f"{sweep_results['errors']} errors"
            )
            
        except Exception as e:
            self.logger.error(f"Portfolio sweep failed: {e}")
            sweep_results["error"] = str(e)
        
        return sweep_results
    
    def _process_position(
        self,
        position: Dict[str, Any],
        oco_orders: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Process a single position for sweep operations.
        
        Args:
            position: Position dictionary
            oco_orders: Dictionary of active OCO orders
            
        Returns:
            Result dictionary or None if no action taken
        """
        symbol = position.get("symbol")
        if not symbol:
            return None
        
        # Check for protective exit first (highest priority)
        protective_result = self._check_protective_exit(position)
        if protective_result:
            return protective_result
        
        # Check if position has OCO order
        has_oco = self._position_has_oco(symbol, oco_orders)
        
        if not has_oco and self.oco_enabled:
            # Attach OCO to position missing it
            return self._attach_oco_to_position(position)
        elif has_oco:
            # Check if OCO needs tightening due to ATR shrink
            return self._check_oco_tightening(position, oco_orders)
        
        return None
    
    def _check_protective_exit(self, position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check if position needs protective exit due to slippage shock.
        
        Args:
            position: Position dictionary
            
        Returns:
            Result dictionary if protective exit needed, None otherwise
        """
        symbol = position.get("symbol")
        quantity = position.get("quantity", 0)
        avg_cost = position.get("avg_cost", 0)
        
        if not symbol or quantity == 0 or avg_cost == 0:
            return None
        
        # Get current mark price
        current_price = self.get_mark_price_callback(symbol)
        if not current_price:
            return None
        
        # Calculate unrealized P&L
        if quantity > 0:  # Long position
            unrealized_pnl = (current_price - avg_cost) * quantity
        else:  # Short position
            unrealized_pnl = (avg_cost - current_price) * abs(quantity)
        
        # Get current ATR for SL distance calculation
        current_atr = self.get_atr_callback(symbol)
        if not current_atr:
            return None
        
        # Calculate SL distance (0.5 * ATR as per config)
        sl_distance = self.sl_atr * current_atr
        
        # Check slippage shock condition: unrealized P&L < -0.6 * SL distance
        slippage_threshold = -self.slippage_shock_threshold * sl_distance
        
        if unrealized_pnl < slippage_threshold:
            # Execute protective exit
            side = "SELL" if quantity > 0 else "BUY"
            success = self.flatten_position_callback(symbol, side, abs(quantity))
            
            if success:
                self.logger.warning(
                    f"PROTECTIVE_EXIT: {symbol} {side} {abs(quantity)} "
                    f"unrealized_pnl=${unrealized_pnl:.2f} < threshold=${slippage_threshold:.2f} "
                    f"(sl_distance=${sl_distance:.4f})"
                )
                
                return {
                    "symbol": symbol,
                    "action": "protective_exit",
                    "side": side,
                    "quantity": abs(quantity),
                    "unrealized_pnl": unrealized_pnl,
                    "slippage_threshold": slippage_threshold,
                    "sl_distance": sl_distance,
                    "current_price": current_price,
                    "avg_cost": avg_cost
                }
            else:
                self.logger.error(f"Failed to execute protective exit for {symbol}")
                return {
                    "symbol": symbol,
                    "action": "error",
                    "error": "Failed to execute protective exit"
                }
        
        return None
    
    def _attach_oco_to_position(self, position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attach OCO order to position missing it.
        
        Args:
            position: Position dictionary
            
        Returns:
            Result dictionary if OCO attached, None otherwise
        """
        symbol = position.get("symbol")
        quantity = position.get("quantity", 0)
        avg_cost = position.get("avg_cost", 0)
        
        if not symbol or quantity == 0 or avg_cost == 0:
            return None
        
        # Get current ATR
        current_atr = self.get_atr_callback(symbol)
        if not current_atr:
            self.logger.warning(f"No ATR available for {symbol}, skipping OCO attachment")
            return None
        
        # Determine side and calculate TP/SL levels
        if quantity > 0:  # Long position
            side = "BUY"
            tp_price = avg_cost + (self.tp_atr * current_atr)
            sl_price = avg_cost - (self.sl_atr * current_atr)
        else:  # Short position
            side = "SELL"
            tp_price = avg_cost - (self.tp_atr * current_atr)
            sl_price = avg_cost + (self.sl_atr * current_atr)
        
        # Create OCO order
        oco_id = self.create_oco_callback(
            symbol, side, abs(quantity), avg_cost, sl_price, tp_price, current_atr
        )
        
        if oco_id:
            self.logger.info(
                f"OCO_ATTACHED: {symbol} {side} {abs(quantity)} "
                f"entry=${avg_cost:.4f} tp=${tp_price:.4f} sl=${sl_price:.4f} "
                f"atr=${current_atr:.4f}"
            )
            
            return {
                "symbol": symbol,
                "action": "oco_attached",
                "side": side,
                "quantity": abs(quantity),
                "entry_price": avg_cost,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "atr": current_atr,
                "oco_id": oco_id
            }
        else:
            self.logger.error(f"Failed to create OCO order for {symbol}")
            return {
                "symbol": symbol,
                "action": "error",
                "error": "Failed to create OCO order"
            }
    
    def _check_oco_tightening(
        self,
        position: Dict[str, Any],
        oco_orders: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if OCO order needs tightening due to ATR shrink.
        
        Args:
            position: Position dictionary
            oco_orders: Dictionary of active OCO orders
            
        Returns:
            Result dictionary if OCO updated, None otherwise
        """
        symbol = position.get("symbol")
        if not symbol:
            return None
        
        # Find OCO order for this position
        oco_order = self._find_oco_for_position(symbol, oco_orders)
        if not oco_order:
            return None
        
        # Get current ATR
        current_atr = self.get_atr_callback(symbol)
        if not current_atr:
            return None
        
        # Get entry ATR from OCO order
        entry_atr = oco_order.get("atr", 0)
        if entry_atr <= 0:
            return None
        
        # Check if ATR shrunk by >50%
        atr_shrink_ratio = (entry_atr - current_atr) / entry_atr
        
        if atr_shrink_ratio > self.atr_shrink_threshold:
            # Calculate new TP/SL levels with current ATR
            entry_price = oco_order.get("entry_price", 0)
            if entry_price <= 0:
                return None
            
            side = oco_order.get("side", "")
            if side.upper() == "BUY":
                new_tp_price = entry_price + (self.tp_atr * current_atr)
                new_sl_price = entry_price - (self.sl_atr * current_atr)
            else:  # SELL
                new_tp_price = entry_price - (self.tp_atr * current_atr)
                new_sl_price = entry_price + (self.sl_atr * current_atr)
            
            # Update OCO order
            success = self.update_oco_callback(oco_order.get("id", ""), new_tp_price, new_sl_price)
            
            if success:
                self.logger.info(
                    f"OCO_TIGHTENED: {symbol} {side} "
                    f"atr_shrink={atr_shrink_ratio:.1%} "
                    f"entry_atr=${entry_atr:.4f} current_atr=${current_atr:.4f} "
                    f"new_tp=${new_tp_price:.4f} new_sl=${new_sl_price:.4f}"
                )
                
                return {
                    "symbol": symbol,
                    "action": "oco_updated",
                    "side": side,
                    "atr_shrink_ratio": atr_shrink_ratio,
                    "entry_atr": entry_atr,
                    "current_atr": current_atr,
                    "old_tp_price": oco_order.get("tp_price"),
                    "old_sl_price": oco_order.get("sl_price"),
                    "new_tp_price": new_tp_price,
                    "new_sl_price": new_sl_price,
                    "oco_id": oco_order.get("id")
                }
            else:
                self.logger.error(f"Failed to update OCO order for {symbol}")
                return {
                    "symbol": symbol,
                    "action": "error",
                    "error": "Failed to update OCO order"
                }
        
        return None
    
    def _position_has_oco(self, symbol: str, oco_orders: Dict[str, Any]) -> bool:
        """Check if position has an active OCO order."""
        for oco_id, oco_order in oco_orders.items():
            if oco_order.get("symbol") == symbol and oco_order.get("status") == "active":
                return True
        return False
    
    def _find_oco_for_position(self, symbol: str, oco_orders: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find OCO order for a specific position."""
        for oco_id, oco_order in oco_orders.items():
            if oco_order.get("symbol") == symbol and oco_order.get("status") == "active":
                return oco_order
        return None
    
    def _validate_callbacks(self) -> bool:
        """Validate that all required callbacks are set."""
        required_callbacks = [
            self.get_positions_callback,
            self.get_oco_orders_callback,
            self.get_atr_callback,
            self.get_mark_price_callback,
            self.create_oco_callback,
            self.update_oco_callback,
            self.flatten_position_callback
        ]
        
        if not all(required_callbacks):
            self.logger.error("Missing required callbacks for portfolio sweeper")
            return False
        
        return True
    
    def get_sweep_summary(self) -> Dict[str, Any]:
        """Get summary of portfolio sweeper configuration."""
        return {
            "oco_enabled": self.oco_enabled,
            "tp_atr": self.tp_atr,
            "sl_atr": self.sl_atr,
            "atr_shrink_threshold": self.atr_shrink_threshold,
            "slippage_shock_threshold": self.slippage_shock_threshold,
            "callbacks_set": self._validate_callbacks()
        }

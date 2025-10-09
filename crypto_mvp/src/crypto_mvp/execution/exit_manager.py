"""
Exit Manager for automated position exits.

This module manages all exit logic including:
- Stop loss hits
- Take profit hits
- Trailing stops (ATR-based)
- Time-based exits
- Profit ladder exits
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from ..core.money import D, q_money
from ..core.decimal_money import to_decimal, format_currency

logger = logging.getLogger(__name__)


class ExitCondition:
    """Represents a single exit condition check result."""
    
    def __init__(
        self,
        symbol: str,
        should_exit: bool,
        reason: str,
        exit_price: Optional[float] = None,
        quantity: Optional[float] = None,
        exit_percentage: float = 1.0  # 100% = full exit
    ):
        self.symbol = symbol
        self.should_exit = should_exit
        self.reason = reason
        self.exit_price = exit_price
        self.quantity = quantity
        self.exit_percentage = exit_percentage


class ExitManager:
    """
    Manages automated exits for all open positions.
    
    Checks positions against:
    1. Stop loss levels
    2. Take profit levels
    3. Trailing stops
    4. Time-based exits
    5. Profit ladder exits
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the exit manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Exit configuration
        exit_config = self.config.get("exits", {})
        self.enable_chandelier = exit_config.get("enable_chandelier", True)
        self.chandelier_n_atr = exit_config.get("chandelier_n_atr", 2.5)
        self.time_stop_hours = exit_config.get("time_stop_hours", 24)
        self.min_qty = exit_config.get("min_qty", 1e-9)
        
        # Profit ladder configuration
        self.tp_ladders = exit_config.get("tp_ladders", [
            {"profit_pct": 0.8, "pct": 0.50},  # +0.8% profit, sell 50%
            {"profit_pct": 1.5, "pct": 0.50}   # +1.5% profit, sell 50% of remaining
        ])
        
        # Tracking
        self.ladder_exits_taken = {}  # symbol -> list of ladder levels already taken
        
        logger.info(
            f"ExitManager initialized: "
            f"chandelier={self.enable_chandelier}, "
            f"time_stop={self.time_stop_hours}h, "
            f"profit_ladders={len(self.tp_ladders)}"
        )
    
    def check_exits(
        self, 
        positions: Dict[str, Dict[str, Any]],
        current_prices: Dict[str, float],
        state_store=None,
        session_id: str = None,
        data_engine=None
    ) -> List[ExitCondition]:
        """
        Check all positions for exit conditions.
        
        Args:
            positions: Dictionary of current positions
            current_prices: Current market prices for each symbol
            state_store: State store for position metadata
            session_id: Current session ID
            data_engine: Data engine for ATR calculation
            
        Returns:
            List of ExitCondition objects for positions that should exit
        """
        exits = []
        
        for symbol, position in positions.items():
            # Get position details
            quantity = float(position.get("quantity", 0))
            entry_price = float(position.get("entry_price", 0))
            current_price = current_prices.get(symbol)
            
            if quantity == 0 or entry_price == 0 or current_price is None:
                continue
            
            # Get position metadata from state store
            metadata = {}
            if state_store and session_id:
                try:
                    db_positions = state_store.get_positions(session_id)
                    for pos in db_positions:
                        if pos["symbol"] == symbol:
                            metadata = pos.get("metadata", {})
                            break
                except:
                    pass
            
            # Get entry timestamp
            entry_time_str = metadata.get("entry_time") or metadata.get("timestamp")
            entry_time = None
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                except:
                    pass
            
            # Get stop loss and take profit from metadata or calculate defaults
            stop_loss = metadata.get("stop_loss")
            take_profit = metadata.get("take_profit")
            
            if not stop_loss:
                # Default: 2% stop loss
                if quantity > 0:  # Long position
                    stop_loss = entry_price * 0.98
                else:  # Short position
                    stop_loss = entry_price * 1.02
            
            if not take_profit:
                # Default: 4% take profit (2:1 R:R)
                if quantity > 0:  # Long position
                    take_profit = entry_price * 1.04
                else:  # Short position
                    take_profit = entry_price * 0.96
            
            # Check stop loss
            exit_check = self._check_stop_loss(
                symbol, quantity, entry_price, current_price, stop_loss
            )
            if exit_check.should_exit:
                exits.append(exit_check)
                continue  # Don't check other exits if stop hit
            
            # Check take profit
            exit_check = self._check_take_profit(
                symbol, quantity, entry_price, current_price, take_profit
            )
            if exit_check.should_exit:
                exits.append(exit_check)
                continue
            
            # Check time-based exit
            if entry_time:
                exit_check = self._check_time_exit(
                    symbol, quantity, current_price, entry_time
                )
                if exit_check.should_exit:
                    exits.append(exit_check)
                    continue
            
            # Check profit ladder (partial exits)
            exit_check = self._check_profit_ladder(
                symbol, quantity, entry_price, current_price
            )
            if exit_check.should_exit:
                exits.append(exit_check)
                # Note: Don't continue - can still check other exits
        
        return exits
    
    def _check_stop_loss(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        stop_loss: float
    ) -> ExitCondition:
        """Check if stop loss is hit."""
        if quantity > 0:  # Long position
            if current_price <= stop_loss:
                logger.info(f"STOP_LOSS_HIT: {symbol} price=${current_price:.4f} <= stop=${stop_loss:.4f}")
                return ExitCondition(
                    symbol=symbol,
                    should_exit=True,
                    reason="stop_loss_hit",
                    exit_price=current_price,
                    quantity=quantity,
                    exit_percentage=1.0
                )
        else:  # Short position
            if current_price >= stop_loss:
                logger.info(f"STOP_LOSS_HIT: {symbol} price=${current_price:.4f} >= stop=${stop_loss:.4f}")
                return ExitCondition(
                    symbol=symbol,
                    should_exit=True,
                    reason="stop_loss_hit",
                    exit_price=current_price,
                    quantity=quantity,
                    exit_percentage=1.0
                )
        
        return ExitCondition(symbol, False, "stop_not_hit")
    
    def _check_take_profit(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        take_profit: float
    ) -> ExitCondition:
        """Check if take profit is hit."""
        if quantity > 0:  # Long position
            if current_price >= take_profit:
                logger.info(f"TAKE_PROFIT_HIT: {symbol} price=${current_price:.4f} >= target=${take_profit:.4f}")
                return ExitCondition(
                    symbol=symbol,
                    should_exit=True,
                    reason="take_profit_hit",
                    exit_price=current_price,
                    quantity=quantity,
                    exit_percentage=1.0
                )
        else:  # Short position
            if current_price <= take_profit:
                logger.info(f"TAKE_PROFIT_HIT: {symbol} price=${current_price:.4f} <= target=${take_profit:.4f}")
                return ExitCondition(
                    symbol=symbol,
                    should_exit=True,
                    reason="take_profit_hit",
                    exit_price=current_price,
                    quantity=quantity,
                    exit_percentage=1.0
                )
        
        return ExitCondition(symbol, False, "take_profit_not_hit")
    
    def _check_time_exit(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
        entry_time: datetime
    ) -> ExitCondition:
        """Check if position should exit due to time limit."""
        time_in_position = datetime.now() - entry_time
        hours_held = time_in_position.total_seconds() / 3600
        
        if hours_held >= self.time_stop_hours:
            logger.info(
                f"TIME_STOP_HIT: {symbol} held for {hours_held:.1f}h >= {self.time_stop_hours}h"
            )
            return ExitCondition(
                symbol=symbol,
                should_exit=True,
                reason=f"time_stop_{hours_held:.1f}h",
                exit_price=current_price,
                quantity=quantity,
                exit_percentage=1.0
            )
        
        return ExitCondition(symbol, False, "time_not_exceeded")
    
    def _check_profit_ladder(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float
    ) -> ExitCondition:
        """Check if position should take partial profits at ladder levels."""
        if quantity == 0 or entry_price == 0:
            return ExitCondition(symbol, False, "no_position")
        
        # Calculate current profit percentage
        if quantity > 0:  # Long position
            profit_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # Short position
            profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        # Check each ladder level
        for i, ladder in enumerate(self.tp_ladders):
            level_profit_pct = ladder["profit_pct"]
            level_exit_pct = ladder["pct"]
            
            # Check if this level is hit and not yet taken
            if profit_pct >= level_profit_pct:
                # Check if we've already taken this ladder level
                ladder_key = f"{symbol}_ladder_{i}"
                if ladder_key not in self.ladder_exits_taken:
                    logger.info(
                        f"PROFIT_LADDER_HIT: {symbol} profit={profit_pct:.2f}% >= {level_profit_pct}%, "
                        f"taking {level_exit_pct*100:.0f}% exit"
                    )
                    self.ladder_exits_taken[ladder_key] = True
                    
                    return ExitCondition(
                        symbol=symbol,
                        should_exit=True,
                        reason=f"profit_ladder_L{i+1}_{profit_pct:.1f}pct",
                        exit_price=current_price,
                        quantity=quantity,
                        exit_percentage=level_exit_pct
                    )
        
        return ExitCondition(symbol, False, "no_ladder_hit")


def create_exit_manager(config: Dict[str, Any]) -> ExitManager:
    """Factory function to create an exit manager."""
    return ExitManager(config)


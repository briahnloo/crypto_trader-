"""
Atomic trade ledger for crypto trading bot.

This module provides dataclasses and functions for atomic trade processing
with invariant validation and rollback capabilities.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    """Represents a single trade fill."""
    symbol: str
    side: str  # "BUY" or "SELL"
    qty: float
    price: float
    fees: float
    ts: datetime
    sl: Optional[float] = None
    tp: Optional[float] = None
    strategy: str = "unknown"
    meta: dict = None
    
    def __post_init__(self):
        if self.meta is None:
            self.meta = {}
    
    @property
    def notional(self) -> float:
        """Calculate the notional value of this fill."""
        return abs(self.qty) * self.price
    
    @property
    def total_cost(self) -> float:
        """Calculate total cost including fees."""
        if self.side == "BUY":
            return self.notional + self.fees
        else:  # SELL
            return self.fees  # Only fees, we receive notional


@dataclass
class Position:
    """Represents a position in a symbol."""
    symbol: str
    qty: float
    avg_cost: float
    
    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.qty > 0
    
    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.qty < 0
    
    @property
    def is_flat(self) -> bool:
        """Check if position is flat (zero quantity)."""
        return abs(self.qty) < 1e-8


@dataclass
class Ledger:
    """Represents the complete trading ledger state."""
    fills: List[Fill]
    positions: Dict[str, Position]
    cash: float
    equity: float
    
    def __post_init__(self):
        if self.fills is None:
            self.fills = []
        if self.positions is None:
            self.positions = {}


def apply_fill(
    ledger: Ledger, 
    fill: Fill, 
    get_mark_price: Callable[[str], Optional[float]] = None
) -> Ledger:
    """
    Atomically apply a fill to the ledger with invariant validation.
    
    Args:
        ledger: Current ledger state
        fill: Fill to apply
        get_mark_price: Callback to get current mark price for a symbol
        
    Returns:
        Updated ledger with fill applied
        
    Raises:
        ValueError: If fill validation fails or invariant is violated
    """
    # Step 1: Validate fill
    if fill.price <= 0:
        raise ValueError(f"Invalid fill price: {fill.price}")
    
    if fill.qty <= 0:
        raise ValueError(f"Invalid fill quantity: {fill.qty}")
    
    if fill.side not in ["BUY", "SELL"]:
        raise ValueError(f"Invalid fill side: {fill.side}")
    
    # Step 2: Capture original state for rollback
    original_cash = ledger.cash
    original_equity = ledger.equity
    original_positions = ledger.positions.copy()
    
    try:
        # Step 3: Calculate cash impact
        if fill.side == "BUY":
            cash_impact = -(fill.notional + fill.fees)
        else:  # SELL
            cash_impact = fill.notional - fill.fees
        
        new_cash = original_cash + cash_impact
        
        # Step 4: Check sufficient cash for BUY orders
        if fill.side == "BUY" and new_cash < 0:
            raise ValueError(f"Insufficient cash: need ${fill.total_cost:.2f}, have ${original_cash:.2f}")
        
        # Step 5: Update position
        symbol = fill.symbol
        current_position = ledger.positions.get(symbol, Position(symbol=symbol, qty=0.0, avg_cost=0.0))
        
        if fill.side == "BUY":
            # Add to position
            if current_position.is_flat:
                # New position
                new_qty = fill.qty
                new_avg_cost = fill.price
            else:
                # Existing position - weighted average
                total_qty = current_position.qty + fill.qty
                total_cost = (current_position.qty * current_position.avg_cost) + (fill.qty * fill.price)
                new_qty = total_qty
                new_avg_cost = total_cost / total_qty if total_qty != 0 else 0.0
        else:  # SELL
            # Reduce position and realize P&L
            if current_position.is_flat or current_position.qty < fill.qty:
                raise ValueError(f"Cannot sell {fill.qty} of {symbol}, only have {current_position.qty}")
            
            # Calculate realized P&L
            realized_pnl = (fill.price - current_position.avg_cost) * fill.qty
            
            new_qty = current_position.qty - fill.qty
            new_avg_cost = current_position.avg_cost  # Keep same average cost for remaining position
            
            # Add realized P&L to cash
            new_cash += realized_pnl
        
        # Step 6: Create updated positions dict
        new_positions = ledger.positions.copy()
        if abs(new_qty) < 1e-8:
            # Position is flat, remove it
            new_positions.pop(symbol, None)
        else:
            new_positions[symbol] = Position(symbol=symbol, qty=new_qty, avg_cost=new_avg_cost)
        
        # Step 7: Create updated ledger
        new_fills = ledger.fills + [fill]
        new_ledger = Ledger(
            fills=new_fills,
            positions=new_positions,
            cash=new_cash,
            equity=0.0  # Will be calculated by invariant check
        )
        
        # Step 8: Invariant validation with epsilon tolerance
        if get_mark_price:
            try:
                # Calculate new equity using mark prices
                position_values = 0.0
                for pos in new_positions.values():
                    mark_price = get_mark_price(pos.symbol)
                    if mark_price and mark_price > 0:
                        position_values += pos.qty * mark_price
                
                new_equity = new_cash + position_values
                old_equity = original_equity
                
                # Calculate expected equity change
                if fill.side == "BUY":
                    expected_change = -fill.fees  # Only fees affect equity
                else:  # SELL
                    realized_pnl = (fill.price - current_position.avg_cost) * fill.qty
                    expected_change = realized_pnl - fill.fees
                
                # Invariant: abs(new_equity - old_equity - expected_change) < epsilon
                epsilon = 1e-6
                actual_change = new_equity - old_equity
                invariant_error = abs(actual_change - expected_change)
                
                if invariant_error > epsilon:
                    error_msg = (
                        f"Invariant violation: actual_change=${actual_change:.6f}, "
                        f"expected_change=${expected_change:.6f}, error=${invariant_error:.6f} > epsilon=${epsilon}"
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                # Update equity in the ledger
                new_ledger = replace(new_ledger, equity=new_equity)
                
                logger.debug(
                    f"Fill applied successfully: {fill.symbol} {fill.side} {fill.qty} @ ${fill.price:.4f}, "
                    f"cash: ${original_cash:.2f} -> ${new_cash:.2f}, equity: ${old_equity:.2f} -> ${new_equity:.2f}"
                )
                
            except Exception as e:
                logger.error(f"Invariant validation failed: {e}")
                raise ValueError(f"Invariant validation failed: {e}")
        
        return new_ledger
        
    except Exception as e:
        # Step 9: Rollback on any failure
        logger.warning(f"Rolling back fill application due to error: {e}")
        raise ValueError(f"Failed to apply fill: {e}")


def create_empty_ledger(initial_cash: float) -> Ledger:
    """Create an empty ledger with initial cash."""
    return Ledger(
        fills=[],
        positions={},
        cash=initial_cash,
        equity=initial_cash
    )


def get_session_fills(ledger: Ledger, session_id: str, date: Optional[str] = None) -> List[Fill]:
    """Get fills for a specific session and optionally date."""
    session_fills = []
    
    for fill in ledger.fills:
        # Check if fill belongs to session (assuming session_id is in meta)
        fill_session = fill.meta.get("session_id")
        if fill_session == session_id:
            # If date specified, check fill date
            if date is None:
                session_fills.append(fill)
            else:
                fill_date = fill.ts.date().isoformat()
                if fill_date == date:
                    session_fills.append(fill)
    
    return session_fills


def calculate_session_metrics(ledger: Ledger, session_id: str, date: Optional[str] = None) -> dict:
    """Calculate metrics for a session."""
    fills = get_session_fills(ledger, session_id, date)
    
    if not fills:
        return {
            "total_trades": 0,
            "total_volume": 0.0,
            "total_fees": 0.0,
            "total_notional": 0.0,
            "buy_trades": 0,
            "sell_trades": 0,
            "symbols_traded": [],
            "strategies_used": []
        }
    
    total_trades = len(fills)
    total_volume = sum(abs(fill.qty) for fill in fills)
    total_fees = sum(fill.fees for fill in fills)
    total_notional = sum(fill.notional for fill in fills)
    buy_trades = sum(1 for fill in fills if fill.side == "BUY")
    sell_trades = sum(1 for fill in fills if fill.side == "SELL")
    symbols_traded = list(set(fill.symbol for fill in fills))
    strategies_used = list(set(fill.strategy for fill in fills))
    
    return {
        "total_trades": total_trades,
        "total_volume": total_volume,
        "total_fees": total_fees,
        "total_notional": total_notional,
        "buy_trades": buy_trades,
        "sell_trades": sell_trades,
        "symbols_traded": symbols_traded,
        "strategies_used": strategies_used
    }

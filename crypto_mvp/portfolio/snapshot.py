"""
Portfolio snapshot for crypto trading bot.

This module provides a single source of truth for portfolio state
that all UI panels can read from consistently.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
import logging

from portfolio.ledger import Ledger, Position

logger = logging.getLogger(__name__)


@dataclass
class PortfolioSnapshot:
    """Single source of truth for portfolio state."""
    ts: datetime
    cash: float
    positions: Dict[str, Position]
    marks: Dict[str, float]
    equity: float
    unrealized_pnl: float
    priced_positions: int
    
    @property
    def position_count(self) -> int:
        """Count of positions with non-zero quantity."""
        return len([p for p in self.positions.values() if abs(p.qty) > 1e-8])
    
    @property
    def total_position_value(self) -> float:
        """Total value of all positions at current marks."""
        return sum(p.qty * self.marks.get(p.symbol, 0.0) for p in self.positions.values())
    
    @property
    def long_value(self) -> float:
        """Total value of long positions."""
        return sum(p.qty * self.marks.get(p.symbol, 0.0) 
                  for p in self.positions.values() if p.qty > 0)
    
    @property
    def short_value(self) -> float:
        """Total value of short positions."""
        return sum(p.qty * self.marks.get(p.symbol, 0.0) 
                  for p in self.positions.values() if p.qty < 0)
    
    def get_position_pnl(self, symbol: str) -> float:
        """Get unrealized P&L for a specific position."""
        if symbol not in self.positions:
            return 0.0
        
        position = self.positions[symbol]
        mark_price = self.marks.get(symbol, 0.0)
        
        if mark_price <= 0:
            return 0.0
        
        return (mark_price - position.avg_cost) * position.qty
    
    def get_position_value(self, symbol: str) -> float:
        """Get current value for a specific position."""
        if symbol not in self.positions:
            return 0.0
        
        position = self.positions[symbol]
        mark_price = self.marks.get(symbol, 0.0)
        
        return position.qty * mark_price


def snapshot_from_ledger(
    ledger: Ledger, 
    marks: Dict[str, float],
    timestamp: Optional[datetime] = None
) -> PortfolioSnapshot:
    """
    Create a portfolio snapshot from ledger and mark prices.
    
    Args:
        ledger: Current ledger state
        marks: Current mark prices for symbols
        timestamp: Snapshot timestamp (defaults to now)
        
    Returns:
        Portfolio snapshot with calculated metrics
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    # Filter out positions with zero quantity
    active_positions = {
        symbol: pos for symbol, pos in ledger.positions.items() 
        if abs(pos.qty) > 1e-8
    }
    
    # Calculate equity: cash + sum(qty * mark_price)
    position_values = 0.0
    for symbol, position in active_positions.items():
        mark_price = marks.get(symbol, 0.0)
        if mark_price > 0:
            position_values += position.qty * mark_price
    
    equity = ledger.cash + position_values
    
    # Calculate unrealized P&L: sum((mark_price - avg_cost) * qty)
    unrealized_pnl = 0.0
    priced_positions = 0
    
    for symbol, position in active_positions.items():
        mark_price = marks.get(symbol, 0.0)
        if mark_price > 0:
            position_pnl = (mark_price - position.avg_cost) * position.qty
            unrealized_pnl += position_pnl
            priced_positions += 1
    
    return PortfolioSnapshot(
        ts=timestamp,
        cash=ledger.cash,
        positions=active_positions,
        marks=marks,
        equity=equity,
        unrealized_pnl=unrealized_pnl,
        priced_positions=priced_positions
    )


def create_empty_snapshot(
    initial_cash: float, 
    timestamp: Optional[datetime] = None
) -> PortfolioSnapshot:
    """Create an empty portfolio snapshot."""
    if timestamp is None:
        timestamp = datetime.now()
    
    return PortfolioSnapshot(
        ts=timestamp,
        cash=initial_cash,
        positions={},
        marks={},
        equity=initial_cash,
        unrealized_pnl=0.0,
        priced_positions=0
    )


def format_position_summary(snapshot: PortfolioSnapshot) -> str:
    """Format a summary of positions for logging."""
    if not snapshot.positions:
        return "No positions"
    
    lines = []
    for symbol, position in snapshot.positions.items():
        mark_price = snapshot.marks.get(symbol, 0.0)
        value = snapshot.get_position_value(symbol)
        pnl = snapshot.get_position_pnl(symbol)
        
        lines.append(
            f"{symbol}: qty={position.qty:.6f} @ ${mark_price:.4f} "
            f"avg_cost=${position.avg_cost:.4f} value=${value:.2f} pnl=${pnl:.2f}"
        )
    
    return "; ".join(lines)


def format_equity_summary(snapshot: PortfolioSnapshot) -> str:
    """Format equity summary for logging."""
    return (
        f"equity=${snapshot.equity:.2f} cash=${snapshot.cash:.2f} "
        f"long_val=${snapshot.long_value:.2f} short_val=${snapshot.short_value:.2f} "
        f"positions={snapshot.position_count}"
    )

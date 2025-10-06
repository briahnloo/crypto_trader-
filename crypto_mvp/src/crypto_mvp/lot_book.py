"""
Minimal FIFO LotBook for realized P&L calculation on partial exits.

This module provides a simple LotBook class that tracks lots (position entries)
and calculates realized P&L using FIFO (First In, First Out) methodology
when positions are partially or fully closed.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from .core.logging_utils import LoggerMixin


@dataclass
class Lot:
    """Represents a single lot (position entry) in the lot book."""
    
    symbol: str
    quantity: float
    price: float
    fee: float
    timestamp: datetime
    lot_id: str
    
    def __post_init__(self):
        """Validate lot data after initialization."""
        if self.quantity <= 0:
            raise ValueError(f"Lot quantity must be positive, got {self.quantity}")
        if self.price <= 0:
            raise ValueError(f"Lot price must be positive, got {self.price}")
        if self.fee < 0:
            raise ValueError(f"Lot fee cannot be negative, got {self.fee}")


@dataclass
class ConsumptionResult:
    """Result of consuming lots from the lot book."""
    
    realized_pnl: float
    total_fees: float
    consumed_lots: List[Tuple[Lot, float]]  # (lot, consumed_quantity)
    remaining_quantity: float  # If consumption was partial


class LotBook(LoggerMixin):
    """
    Minimal FIFO LotBook for tracking position lots and calculating realized P&L.
    
    This class provides a simple interface for:
    - Adding lots when entering positions
    - Consuming lots when exiting positions (FIFO order)
    - Calculating realized P&L including fees
    
    Features:
    - FIFO (First In, First Out) lot consumption
    - Fee tracking and inclusion in P&L calculations
    - Partial exit support
    - In-memory storage (can be extended to persist)
    """
    
    def __init__(self):
        """Initialize the LotBook."""
        super().__init__()
        self.lots: Dict[str, List[Lot]] = {}  # symbol -> list of lots (FIFO order)
        self._next_lot_id = 1
    
    def add_lot(
        self, 
        symbol: str, 
        quantity: float, 
        price: float, 
        fee: float = 0.0, 
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Add a new lot to the lot book.
        
        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            quantity: Quantity of the position (must be positive)
            price: Entry price per unit
            fee: Trading fees paid (default 0.0)
            timestamp: When the lot was created (defaults to now)
            
        Returns:
            lot_id: Unique identifier for the lot
            
        Raises:
            ValueError: If quantity or price are invalid
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        lot_id = f"{symbol}_{self._next_lot_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        self._next_lot_id += 1
        
        lot = Lot(
            symbol=symbol,
            quantity=quantity,
            price=price,
            fee=fee,
            timestamp=timestamp,
            lot_id=lot_id
        )
        
        # Add to the lot book (FIFO order - new lots go to the end)
        if symbol not in self.lots:
            self.lots[symbol] = []
        self.lots[symbol].append(lot)
        
        self.logger.debug(
            f"Added lot {lot_id}: {quantity:.6f} {symbol} @ ${price:.4f} "
            f"(fee=${fee:.4f})"
        )
        
        return lot_id
    
    def consume(
        self, 
        symbol: str, 
        quantity: float, 
        fill_price: float, 
        fee: float = 0.0
    ) -> ConsumptionResult:
        """
        Consume lots from the lot book using FIFO order.
        
        Args:
            symbol: Trading symbol to consume lots for
            quantity: Quantity to consume (must be positive)
            fill_price: Price per unit at which the position is being closed
            fee: Trading fees paid for this exit (default 0.0)
            
        Returns:
            ConsumptionResult with realized P&L and consumption details
            
        Raises:
            ValueError: If quantity is invalid or insufficient lots available
        """
        if quantity <= 0:
            raise ValueError(f"Consumption quantity must be positive, got {quantity}")
        
        if symbol not in self.lots or not self.lots[symbol]:
            raise ValueError(f"No lots available for symbol {symbol}")
        
        # Calculate total available quantity
        total_available = sum(lot.quantity for lot in self.lots[symbol])
        if quantity > total_available:
            raise ValueError(
                f"Insufficient lots: trying to consume {quantity:.6f} but only "
                f"{total_available:.6f} available for {symbol}"
            )
        
        # FIFO consumption - consume from oldest lots first
        remaining_to_consume = quantity
        consumed_lots = []
        total_realized_pnl = 0.0
        total_fees = 0.0  # Track all fees separately
        
        # Process lots in FIFO order (oldest first)
        lots_to_remove = []
        for i, lot in enumerate(self.lots[symbol]):
            if remaining_to_consume <= 0:
                break
            
            # Calculate how much of this lot to consume
            consume_from_lot = min(remaining_to_consume, lot.quantity)
            
            # Calculate realized P&L for this portion
            # P&L = (exit_price - entry_price) * quantity - entry_fees
            entry_cost = lot.price * consume_from_lot
            exit_proceeds = fill_price * consume_from_lot
            lot_fee_portion = (lot.fee * consume_from_lot) / lot.quantity
            
            lot_realized_pnl = exit_proceeds - entry_cost - lot_fee_portion
            total_realized_pnl += lot_realized_pnl
            total_fees += lot_fee_portion
            
            # Track consumption (only if actually consumed)
            if consume_from_lot > 1e-8:  # Use small epsilon for floating point comparison
                consumed_lots.append((lot, consume_from_lot))
            
            # Update lot quantity
            lot.quantity -= consume_from_lot
            lot.fee -= lot_fee_portion
            
            # Mark lot for removal if fully consumed
            if lot.quantity <= 1e-8:  # Use small epsilon for floating point comparison
                lots_to_remove.append(i)
            
            remaining_to_consume -= consume_from_lot
            
            self.logger.debug(
                f"Consumed {consume_from_lot:.6f} from lot {lot.lot_id}: "
                f"P&L=${lot_realized_pnl:.4f} (entry=${lot.price:.4f}, "
                f"exit=${fill_price:.4f})"
            )
        
        # Remove fully consumed lots (in reverse order to maintain indices)
        for i in reversed(lots_to_remove):
            removed_lot = self.lots[symbol].pop(i)
            self.logger.debug(f"Removed fully consumed lot {removed_lot.lot_id}")
        
        # Clean up empty symbol entries
        if not self.lots[symbol]:
            del self.lots[symbol]
        
        # Add exit fee to total fees
        total_fees += fee
        
        result = ConsumptionResult(
            realized_pnl=total_realized_pnl,
            total_fees=total_fees,
            consumed_lots=consumed_lots,
            remaining_quantity=remaining_to_consume
        )
        
        self.logger.info(
            f"Consumed {quantity:.6f} {symbol} @ ${fill_price:.4f}: "
            f"realized_pnl=${total_realized_pnl:.4f}, fees=${total_fees:.4f}"
        )
        
        return result
    
    def get_available_quantity(self, symbol: str) -> float:
        """
        Get total available quantity for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Total available quantity across all lots for the symbol
        """
        if symbol not in self.lots:
            return 0.0
        
        return sum(lot.quantity for lot in self.lots[symbol])
    
    def get_lots(self, symbol: str) -> List[Lot]:
        """
        Get all lots for a symbol (in FIFO order).
        
        Args:
            symbol: Trading symbol
            
        Returns:
            List of lots in FIFO order (oldest first)
        """
        if symbol not in self.lots:
            return []
        
        return self.lots[symbol].copy()
    
    def get_total_cost_basis(self, symbol: str) -> float:
        """
        Get total cost basis for all lots of a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Total cost basis (quantity * price + fees) for all lots
        """
        if symbol not in self.lots:
            return 0.0
        
        total_cost = 0.0
        for lot in self.lots[symbol]:
            total_cost += (lot.quantity * lot.price) + lot.fee
        
        return total_cost
    
    def get_weighted_average_price(self, symbol: str) -> float:
        """
        Get weighted average price for all lots of a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Weighted average price across all lots
        """
        if symbol not in self.lots or not self.lots[symbol]:
            return 0.0
        
        total_quantity = 0.0
        total_value = 0.0
        
        for lot in self.lots[symbol]:
            total_quantity += lot.quantity
            total_value += lot.quantity * lot.price
        
        if total_quantity <= 0:
            return 0.0
        
        return total_value / total_quantity
    
    def clear_symbol(self, symbol: str) -> int:
        """
        Clear all lots for a symbol.
        
        Args:
            symbol: Trading symbol to clear
            
        Returns:
            Number of lots cleared
        """
        if symbol not in self.lots:
            return 0
        
        lot_count = len(self.lots[symbol])
        del self.lots[symbol]
        
        self.logger.info(f"Cleared {lot_count} lots for symbol {symbol}")
        return lot_count
    
    def clear_all(self) -> int:
        """
        Clear all lots from the lot book.
        
        Returns:
            Total number of lots cleared
        """
        total_lots = sum(len(lots) for lots in self.lots.values())
        self.lots.clear()
        
        self.logger.info(f"Cleared all {total_lots} lots from lot book")
        return total_lots
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the lot book state.
        
        Returns:
            Dictionary with lot book summary information
        """
        summary = {
            "total_symbols": len(self.lots),
            "total_lots": sum(len(lots) for lots in self.lots.values()),
            "symbols": {}
        }
        
        for symbol, lots in self.lots.items():
            total_quantity = sum(lot.quantity for lot in lots)
            total_cost = sum((lot.quantity * lot.price) + lot.fee for lot in lots)
            avg_price = total_cost / total_quantity if total_quantity > 0 else 0.0
            
            summary["symbols"][symbol] = {
                "lot_count": len(lots),
                "total_quantity": total_quantity,
                "total_cost": total_cost,
                "weighted_avg_price": avg_price
            }
        
        return summary

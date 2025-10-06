"""
Transactional portfolio mutations with staged state validation.

This module provides a PortfolioTransaction context manager that allows
portfolio changes to be staged and validated before committing to the
persistent state store.
"""

import copy
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from ..core.logging_utils import LoggerMixin
from .portfolio import AdvancedPortfolioManager


@dataclass
class StagedCash:
    """Staged cash balance changes."""
    delta: float = 0.0
    fees: float = 0.0


@dataclass
class StagedPosition:
    """Staged position changes."""
    symbol: str
    quantity_delta: float = 0.0
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    strategy: Optional[str] = None


@dataclass
class StagedLotBook:
    """Staged lot book changes."""
    symbol: str
    lots_to_add: List[Dict[str, Any]] = field(default_factory=list)
    lots_to_remove: List[str] = field(default_factory=list)  # lot_ids
    lots_to_update: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # lot_id -> updates


@dataclass
class StagedRealizedPnl:
    """Staged realized P&L changes."""
    delta: float = 0.0


class PortfolioTransaction(LoggerMixin):
    """
    Context manager for transactional portfolio mutations.
    
    Stages all portfolio changes (cash, positions, lotbook) and validates
    only the final staged state before committing atomically.
    """
    
    def __init__(
        self,
        state_store,
        portfolio_manager: AdvancedPortfolioManager,
        previous_equity: float,
        session_id: str,
        validation_epsilon: Optional[float] = None
    ):
        """Initialize the portfolio transaction.
        
        Args:
            state_store: StateStore instance for persistence
            portfolio_manager: PortfolioManager instance
            previous_equity: Previous cycle's equity for validation
            session_id: Session identifier
            validation_epsilon: Custom validation epsilon (auto-calculated if None)
        """
        super().__init__()
        self.state_store = state_store
        self.portfolio_manager = portfolio_manager
        self.previous_equity = previous_equity
        self.session_id = session_id
        
        # Calculate validation epsilon: max(1.00, 0.0001 * previous_equity)
        if validation_epsilon is None:
            self.validation_epsilon = max(1.00, 0.0001 * previous_equity)
        else:
            self.validation_epsilon = validation_epsilon
        
        # Staged changes
        self.staged_cash = StagedCash()
        self.staged_positions: Dict[str, StagedPosition] = {}
        self.staged_lotbooks: Dict[str, StagedLotBook] = {}
        self.staged_realized_pnl = StagedRealizedPnl()
        
        # Current state snapshots (for rollback)
        self.current_cash_equity = None
        self.current_positions = None
        self.current_lotbooks = None
        
        self.committed = False
        self.rolled_back = False
    
    def __enter__(self):
        """Enter the transaction context."""
        self.logger.debug(f"Starting portfolio transaction with ε=${self.validation_epsilon:.2f}")
        self._snapshot_current_state()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the transaction context."""
        if exc_type is not None:
            # Exception occurred, rollback
            self._rollback()
            return False
        
        if not self.committed:
            # No exception but not committed, rollback
            self._rollback()
        
        return False
    
    def _snapshot_current_state(self) -> None:
        """Snapshot current state for potential rollback."""
        try:
            # Get current cash/equity
            self.current_cash_equity = self.state_store.get_latest_cash_equity(self.session_id)
            
            # Get current positions
            self.current_positions = self.state_store.get_positions(self.session_id)
            
            # Get current lotbooks
            self.current_lotbooks = self.state_store.snapshot_all_lotbooks(self.session_id)
            
            self.logger.debug("Snapshotted current portfolio state for transaction")
            
        except Exception as e:
            self.logger.error(f"Failed to snapshot current state: {e}")
            raise
    
    def stage_cash_delta(self, delta: float, fees: float = 0.0) -> None:
        """Stage cash balance change.
        
        Args:
            delta: Cash delta (positive for credit, negative for debit)
            fees: Additional fees
        """
        self.staged_cash.delta += delta
        self.staged_cash.fees += fees
        
        self.logger.debug(f"Staged cash delta: ${delta:.2f} (fees: ${fees:.2f})")
    
    def stage_position_delta(
        self,
        symbol: str,
        quantity_delta: float,
        entry_price: Optional[float] = None,
        current_price: Optional[float] = None,
        strategy: Optional[str] = None
    ) -> None:
        """Stage position quantity change.
        
        Args:
            symbol: Trading symbol
            quantity_delta: Quantity change (positive for buy, negative for sell)
            entry_price: Entry price (for new positions)
            current_price: Current market price
            strategy: Strategy name
        """
        if symbol not in self.staged_positions:
            self.staged_positions[symbol] = StagedPosition(symbol=symbol)
        
        position = self.staged_positions[symbol]
        position.quantity_delta += quantity_delta
        
        # Update other fields if provided
        if entry_price is not None:
            position.entry_price = entry_price
        if current_price is not None:
            position.current_price = current_price
        if strategy is not None:
            position.strategy = strategy
        
        self.logger.debug(f"Staged position delta: {symbol} {quantity_delta:+.6f}")
    
    def stage_lot_add(
        self,
        symbol: str,
        lot_data: Dict[str, Any]
    ) -> None:
        """Stage lot addition to lotbook.
        
        Args:
            symbol: Trading symbol
            lot_data: Lot data dictionary
        """
        if symbol not in self.staged_lotbooks:
            self.staged_lotbooks[symbol] = StagedLotBook(symbol=symbol)
        
        self.staged_lotbooks[symbol].lots_to_add.append(lot_data)
        
        self.logger.debug(f"Staged lot add: {symbol} {lot_data.get('quantity', 0):.6f}")
    
    def stage_lot_remove(self, symbol: str, lot_id: str) -> None:
        """Stage lot removal from lotbook.
        
        Args:
            symbol: Trading symbol
            lot_id: Lot identifier to remove
        """
        if symbol not in self.staged_lotbooks:
            self.staged_lotbooks[symbol] = StagedLotBook(symbol=symbol)
        
        self.staged_lotbooks[symbol].lots_to_remove.append(lot_id)
        
        self.logger.debug(f"Staged lot remove: {symbol} {lot_id}")
    
    def stage_lot_update(
        self,
        symbol: str,
        lot_id: str,
        updates: Dict[str, Any]
    ) -> None:
        """Stage lot update in lotbook.
        
        Args:
            symbol: Trading symbol
            lot_id: Lot identifier to update
            updates: Dictionary of updates to apply
        """
        if symbol not in self.staged_lotbooks:
            self.staged_lotbooks[symbol] = StagedLotBook(symbol=symbol)
        
        if lot_id not in self.staged_lotbooks[symbol].lots_to_update:
            self.staged_lotbooks[symbol].lots_to_update[lot_id] = {}
        
        self.staged_lotbooks[symbol].lots_to_update[lot_id].update(updates)
        
        self.logger.debug(f"Staged lot update: {symbol} {lot_id}")
    
    def stage_realized_pnl_delta(self, delta: float) -> None:
        """Stage realized P&L change.
        
        Args:
            delta: Realized P&L delta
        """
        self.staged_realized_pnl.delta += delta
        
        self.logger.debug(f"Staged realized P&L delta: ${delta:.2f}")
    
    def _compute_staged_total(self, mark_prices: Dict[str, float]) -> float:
        """Compute total portfolio value from staged state.
        
        Args:
            mark_prices: Current mark prices for all symbols
            
        Returns:
            Total portfolio value (cash + positions + realized P&L)
        """
        # Start with current cash balance + staged cash delta
        current_cash = self.current_cash_equity["cash_balance"] if self.current_cash_equity else 0.0
        staged_cash = current_cash + self.staged_cash.delta - self.staged_cash.fees
        
        # Add staged realized P&L
        current_realized_pnl = self.current_cash_equity.get("total_realized_pnl", 0.0) if self.current_cash_equity else 0.0
        staged_realized_pnl = current_realized_pnl + self.staged_realized_pnl.delta
        
        # Compute staged positions value
        staged_positions_value = 0.0
        
        # Process each symbol with staged changes
        all_symbols = set(self.staged_positions.keys())
        for pos in self.current_positions or []:
            all_symbols.add(pos["symbol"])
        
        for symbol in all_symbols:
            # Get current position
            current_qty = 0.0
            current_entry_price = 0.0
            for pos in self.current_positions or []:
                if pos["symbol"] == symbol:
                    current_qty = pos["quantity"]
                    current_entry_price = pos["entry_price"]
                    break
            
            # Apply staged changes
            staged_qty = current_qty
            if symbol in self.staged_positions:
                staged_qty += self.staged_positions[symbol].quantity_delta
            
            # Use mark price for valuation
            mark_price = mark_prices.get(symbol, current_entry_price)
            if mark_price <= 0:
                mark_price = current_entry_price
            
            # Add to total positions value
            staged_positions_value += staged_qty * mark_price
        
        # Total staged portfolio value
        staged_total = staged_cash + staged_positions_value + staged_realized_pnl
        
        return staged_total
    
    def _validate_staged_state(self, mark_prices: Dict[str, float]) -> Tuple[bool, float]:
        """Validate the final staged state against previous equity.
        
        Args:
            mark_prices: Current mark prices for all symbols
            
        Returns:
            Tuple of (is_valid, staged_total)
        """
        staged_total = self._compute_staged_total(mark_prices)
        
        # Validate: |staged_total - previous_equity| <= validation_epsilon
        delta = abs(staged_total - self.previous_equity)
        is_valid = delta <= self.validation_epsilon
        
        if not is_valid:
            self.logger.warning(
                f"PORTFOLIO_DISCARD: validation_failed Δ=${delta:.2f}, ε=${self.validation_epsilon:.2f}"
            )
        else:
            self.logger.debug(
                f"Portfolio validation passed: staged_total=${staged_total:.2f}, "
                f"previous_equity=${self.previous_equity:.2f}, Δ=${delta:.2f}, ε=${self.validation_epsilon:.2f}"
            )
        
        return is_valid, staged_total
    
    def commit(self, mark_prices: Dict[str, float]) -> bool:
        """Commit staged changes to persistent state.
        
        Args:
            mark_prices: Current mark prices for all symbols
            
        Returns:
            True if committed successfully, False if validation failed
        """
        if self.committed:
            self.logger.warning("Transaction already committed")
            return True
        
        if self.rolled_back:
            self.logger.error("Cannot commit rolled back transaction")
            return False
        
        # Validate staged state
        is_valid, staged_total = self._validate_staged_state(mark_prices)
        
        if not is_valid:
            return False
        
        try:
            # Commit cash/equity changes
            self._commit_cash_equity(staged_total)
            
            # Commit position changes
            self._commit_positions(mark_prices)
            
            # Commit lotbook changes
            self._commit_lotbooks()
            
            self.committed = True
            
            # Log successful commit
            self.logger.info(
                f"PORTFOLIO_COMMIT: cash=${staged_total:.2f}, "
                f"positions=${self._compute_positions_value(mark_prices):.2f}, "
                f"total=${staged_total:.2f} (Δ=${staged_total - self.previous_equity:.2f}, ε=${self.validation_epsilon:.2f})"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to commit portfolio transaction: {e}")
            self._rollback()
            raise
    
    def _commit_cash_equity(self, staged_total: float) -> None:
        """Commit cash and equity changes."""
        current_cash = self.current_cash_equity["cash_balance"] if self.current_cash_equity else 0.0
        new_cash = current_cash + self.staged_cash.delta - self.staged_cash.fees
        
        current_fees = self.current_cash_equity.get("total_fees", 0.0) if self.current_cash_equity else 0.0
        new_fees = current_fees + self.staged_cash.fees
        
        current_realized_pnl = self.current_cash_equity.get("total_realized_pnl", 0.0) if self.current_cash_equity else 0.0
        new_realized_pnl = current_realized_pnl + self.staged_realized_pnl.delta
        
        current_unrealized_pnl = self.current_cash_equity.get("total_unrealized_pnl", 0.0) if self.current_cash_equity else 0.0
        
        self.state_store.save_cash_equity(
            cash_balance=new_cash,
            total_equity=staged_total,
            total_fees=new_fees,
            total_realized_pnl=new_realized_pnl,
            total_unrealized_pnl=current_unrealized_pnl,
            session_id=self.session_id,
            previous_equity=self.previous_equity
        )
    
    def _commit_positions(self, mark_prices: Dict[str, float]) -> None:
        """Commit position changes."""
        # Process each symbol with staged changes
        all_symbols = set(self.staged_positions.keys())
        for pos in self.current_positions or []:
            all_symbols.add(pos["symbol"])
        
        for symbol in all_symbols:
            # Get current position
            current_qty = 0.0
            current_entry_price = 0.0
            current_strategy = "unknown"
            
            for pos in self.current_positions or []:
                if pos["symbol"] == symbol:
                    current_qty = pos["quantity"]
                    current_entry_price = pos["entry_price"]
                    current_strategy = pos["strategy"]
                    break
            
            # Apply staged changes
            new_qty = current_qty
            new_entry_price = current_entry_price
            new_strategy = current_strategy
            
            if symbol in self.staged_positions:
                staged = self.staged_positions[symbol]
                new_qty += staged.quantity_delta
                
                if staged.entry_price is not None:
                    new_entry_price = staged.entry_price
                if staged.strategy is not None:
                    new_strategy = staged.strategy
            
            # Get current market price
            current_price = mark_prices.get(symbol, new_entry_price)
            
            # Update or remove position
            if abs(new_qty) < 1e-8:  # Essentially zero
                if current_qty != 0:  # Only remove if there was a position
                    self.state_store.remove_position(symbol, current_strategy)
            else:
                self.state_store.save_position(
                    symbol=symbol,
                    quantity=new_qty,
                    entry_price=new_entry_price,
                    current_price=current_price,
                    strategy=new_strategy,
                    session_id=self.session_id
                )
    
    def _commit_lotbooks(self) -> None:
        """Commit lotbook changes."""
        for symbol, staged_lotbook in self.staged_lotbooks.items():
            # Get current lotbook
            current_lots = self.current_lotbooks.get(symbol, [])
            
            # Apply staged changes
            new_lots = copy.deepcopy(current_lots)
            
            # Remove lots
            for lot_id in staged_lotbook.lots_to_remove:
                new_lots = [lot for lot in new_lots if lot.get("lot_id") != lot_id]
            
            # Update lots
            for lot_id, updates in staged_lotbook.lots_to_update.items():
                for lot in new_lots:
                    if lot.get("lot_id") == lot_id:
                        lot.update(updates)
                        break
            
            # Add new lots
            new_lots.extend(staged_lotbook.lots_to_add)
            
            # Save updated lotbook
            if new_lots != current_lots:
                self.state_store.set_lotbook(symbol, new_lots, self.session_id)
    
    def _compute_positions_value(self, mark_prices: Dict[str, float]) -> float:
        """Compute total positions value."""
        total_value = 0.0
        
        for symbol in set(self.staged_positions.keys()):
            # Get current position
            current_qty = 0.0
            for pos in self.current_positions or []:
                if pos["symbol"] == symbol:
                    current_qty = pos["quantity"]
                    break
            
            # Apply staged changes
            staged_qty = current_qty
            if symbol in self.staged_positions:
                staged_qty += self.staged_positions[symbol].quantity_delta
            
            # Use mark price
            mark_price = mark_prices.get(symbol, 0.0)
            total_value += staged_qty * mark_price
        
        return total_value
    
    def _rollback(self) -> None:
        """Rollback all staged changes."""
        if self.rolled_back:
            return
        
        self.logger.debug("Rolling back portfolio transaction")
        
        # Clear all staged changes
        self.staged_cash = StagedCash()
        self.staged_positions.clear()
        self.staged_lotbooks.clear()
        self.staged_realized_pnl = StagedRealizedPnl()
        
        self.rolled_back = True
        self.logger.debug("Portfolio transaction rolled back")


@contextmanager
def portfolio_transaction(
    state_store,
    portfolio_manager: AdvancedPortfolioManager,
    previous_equity: float,
    session_id: str,
    validation_epsilon: Optional[float] = None
):
    """Context manager factory for portfolio transactions.
    
    Args:
        state_store: StateStore instance
        portfolio_manager: PortfolioManager instance
        previous_equity: Previous cycle's equity
        session_id: Session identifier
        validation_epsilon: Custom validation epsilon
        
    Yields:
        PortfolioTransaction instance
    """
    transaction = PortfolioTransaction(
        state_store=state_store,
        portfolio_manager=portfolio_manager,
        previous_equity=previous_equity,
        session_id=session_id,
        validation_epsilon=validation_epsilon
    )
    
    with transaction:
        yield transaction

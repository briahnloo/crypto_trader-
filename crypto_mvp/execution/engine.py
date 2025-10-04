"""
Atomic execution engine for crypto trading bot.

This module provides atomic trade execution with hardened pricing,
risk-based position sizing, and SL/TP calculation.
"""

from datetime import datetime
from typing import List, Optional, Callable, Dict, Any
import logging

from portfolio.ledger import Ledger, Fill, apply_fill
from portfolio.snapshot import PortfolioSnapshot
from market.prices import get_executable_price, get_atr, clear_atr_cache
from risk.sltp import sl_tp_defaults, get_sl_tp_summary
from risk.position_sizing import size_for_risk, get_position_size_summary

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Atomic execution engine for trades."""
    
    def __init__(self, get_mark_price_callback: Callable[[str], Optional[float]]):
        """
        Initialize execution engine.
        
        Args:
            get_mark_price_callback: Function to get current mark price for validation
        """
        self.get_mark_price_callback = get_mark_price_callback
        self.committed_fills: List[Fill] = []
    
    def reset_cycle(self):
        """Reset committed fills for new cycle and clear ATR cache."""
        self.committed_fills = []
        clear_atr_cache()
    
    def executable_price(self, symbol: str, max_attempts: int = 2) -> Optional[float]:
        """
        Fetch best executable price with retry logic.
        
        Args:
            symbol: Symbol to get price for
            max_attempts: Maximum number of attempts
            
        Returns:
            Executable price or None if not available
        """
        # Use the hardened pricing function
        return get_executable_price(symbol)
    
    def execute_trade(
        self,
        ledger: Ledger,
        symbol: str,
        side: str,
        strategy: str = "unknown",
        fees: float = 0.0,
        meta: Optional[Dict[str, Any]] = None,
        snapshot: Optional[PortfolioSnapshot] = None
    ) -> tuple[Ledger, bool]:
        """
        Atomically execute a trade with risk-based position sizing.
        
        Args:
            ledger: Current ledger state
            symbol: Symbol to trade
            side: "BUY" or "SELL"
            strategy: Strategy name
            fees: Trading fees
            meta: Additional metadata
            snapshot: Current portfolio snapshot for equity calculation
            
        Returns:
            Tuple of (updated_ledger, success)
        """
        if meta is None:
            meta = {}
        
        # Step 1: Log PLANNED trade
        logger.info(f"PLANNED: {symbol} {side} @ market price, strategy={strategy}")
        
        # Step 2: Get executable price
        entry = get_executable_price(symbol)
        if not entry:
            logger.warning(f"REJECTED: {symbol} {side} (reason=no_price)")
            return ledger, False
        
        # Step 3: Get ATR for SL/TP calculation
        atr = get_atr(symbol)
        
        # Step 4: Calculate SL/TP
        try:
            sl, tp, sl_tp_meta = sl_tp_defaults(
                symbol=symbol,
                entry=entry,
                side=side,
                atr=atr
            )
        except Exception as e:
            logger.warning(f"REJECTED: {symbol} {side} (reason=sl_tp_error: {e})")
            return ledger, False
        
        # Step 5: Calculate risk-based position size
        if snapshot:
            equity = snapshot.equity
        else:
            # Fallback to ledger equity if no snapshot
            equity = ledger.cash + sum(pos.qty * entry for pos in ledger.positions.values())
        
        qty = size_for_risk(
            equity=equity,
            entry=entry,
            sl=sl
        )
        
        if qty <= 0:
            logger.warning(f"REJECTED: {symbol} {side} (reason=size=0)")
            return ledger, False
        
        # Step 6: Create fill with calculated values
        fill_meta = {
            **meta,
            "atr_mode": sl_tp_meta["mode"],
            "risk": sl_tp_meta["risk"],
            "rr": sl_tp_meta["rr"]
        }
        
        fill = Fill(
            symbol=symbol,
            side=side,
            qty=qty,
            price=entry,
            fees=fees,
            ts=datetime.now(),
            sl=sl,
            tp=tp,
            strategy=strategy,
            meta=fill_meta
        )
        
        # Step 7: Apply fill atomically
        try:
            updated_ledger = apply_fill(
                ledger=ledger,
                fill=fill,
                get_mark_price=self.get_mark_price_callback
            )
            
            # Step 8: Log EXECUTED trade with SL/TP info
            sl_tp_summary = get_sl_tp_summary(sl, tp, sl_tp_meta)
            position_summary = get_position_size_summary(qty, entry, sl, tp, side, equity)
            
            logger.info(
                f"EXECUTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} "
                f"fees=${fees:.2f} strategy={strategy} {sl_tp_summary} {position_summary}"
            )
            
            # Step 9: Add to committed fills
            self.committed_fills.append(fill)
            
            return updated_ledger, True
            
        except ValueError as e:
            # Step 10: Log REJECTED trade
            logger.warning(f"REJECTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} (reason=invariant: {e})")
            return ledger, False
        
        except Exception as e:
            # Step 11: Log REJECTED trade for unexpected errors
            logger.error(f"REJECTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} (reason=error: {e})")
            return ledger, False
    
    def get_committed_fills(self) -> List[Fill]:
        """Get list of fills committed in current cycle."""
        return self.committed_fills.copy()
    
    def get_cycle_metrics(self) -> Dict[str, Any]:
        """Get execution metrics for current cycle."""
        if not self.committed_fills:
            return {
                "trades_executed": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "symbols_traded": [],
                "strategies_used": []
            }
        
        return {
            "trades_executed": len(self.committed_fills),
            "total_volume": sum(abs(fill.qty) for fill in self.committed_fills),
            "total_fees": sum(fill.fees for fill in self.committed_fills),
            "total_notional": sum(fill.notional for fill in self.committed_fills),
            "symbols_traded": list(set(fill.symbol for fill in self.committed_fills)),
            "strategies_used": list(set(fill.strategy for fill in self.committed_fills))
        }


def create_execution_engine(get_mark_price_callback: Callable[[str], Optional[float]]) -> ExecutionEngine:
    """Create an execution engine instance."""
    return ExecutionEngine(get_mark_price_callback)

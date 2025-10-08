"""
Comprehensive P&L logger - one glance tells you where $ comes from.

Per-trade line: symbol, side, notional, fill price, fee, R multiple, realized P&L $, cumulative P&L.
Per-cycle: cash, positions_value, realized_pnl, total_equity, plus unrealized_pnl.
P&L from exits: TP/SL/Trail events with size and price.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from ..core.logging_utils import LoggerMixin
from ..core.decimal_money import to_decimal, format_currency, format_quantity


class PnLLogger(LoggerMixin):
    """Comprehensive P&L logging for complete trade attribution."""

    def __init__(self):
        super().__init__()
        self.cumulative_realized_pnl = Decimal("0.0")
        self.trade_count = 0
        
    def reset_session(self):
        """Reset session-level tracking."""
        self.cumulative_realized_pnl = Decimal("0.0")
        self.trade_count = 0
        
    def log_trade_execution(
        self,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        notional: float,
        fee: float,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        realized_pnl: float = 0.0,
        trade_type: str = "ENTRY",
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None
    ) -> None:
        """
        Log per-trade execution with complete P&L breakdown.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Fill quantity
            fill_price: Execution price
            notional: Total $ amount
            fee: Transaction fee
            entry_price: Entry price for position (for R calculation)
            stop_price: Stop loss price (for R calculation)
            realized_pnl: Realized P&L from this trade
            trade_type: ENTRY, EXIT, ADD (for pyramiding)
            reason: Trade reason/trigger
            metadata: Additional metadata
        """
        self.trade_count += 1
        
        # Update cumulative P&L
        realized_pnl_dec = to_decimal(realized_pnl)
        self.cumulative_realized_pnl += realized_pnl_dec
        
        # Calculate R multiple if we have entry and stop
        r_multiple = "N/A"
        if entry_price and stop_price and trade_type in ["EXIT", "PARTIAL_EXIT"]:
            risk_per_share = abs(entry_price - stop_price)
            if risk_per_share > 0:
                pnl_per_share = fill_price - entry_price if side == "SELL" else entry_price - fill_price
                r_multiple = f"{pnl_per_share / risk_per_share:+.2f}R"
        
        # Format trade line
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Build log line with all critical info
        log_parts = [
            f"📊 TRADE #{self.trade_count}",
            f"│ {timestamp}",
            f"│ {trade_type:10s}",
            f"│ {symbol:12s}",
            f"│ {side:4s}",
            f"│ qty={format_quantity(quantity):12s}",
            f"│ fill=${fill_price:10.4f}",
            f"│ notional=${notional:10.2f}",
            f"│ fee=${fee:6.2f}",
            f"│ R={r_multiple:8s}",
            f"│ realized_pnl=${realized_pnl:+10.2f}",
            f"│ cumulative_pnl=${float(self.cumulative_realized_pnl):+10.2f}",
        ]
        
        if reason:
            log_parts.append(f"│ reason={reason}")
            
        self.logger.info(" ".join(log_parts))
        
        # Log metadata if provided
        if metadata:
            meta_str = ", ".join([f"{k}={v}" for k, v in metadata.items()])
            self.logger.debug(f"    └─ metadata: {meta_str}")
    
    def log_exit_event(
        self,
        symbol: str,
        exit_type: str,
        quantity: float,
        exit_price: float,
        entry_price: float,
        stop_price: Optional[float],
        realized_pnl: float,
        reason: str = ""
    ) -> None:
        """
        Log exit event (TP/SL/Trail) with P&L attribution.
        
        Args:
            symbol: Trading symbol
            exit_type: TP1, TP2, TP3, SL, TRAIL_STOP, TIME_STOP
            quantity: Quantity exited
            exit_price: Exit price
            entry_price: Original entry price
            stop_price: Stop loss price (for R calculation)
            realized_pnl: Realized P&L from exit
            reason: Exit reason/trigger
        """
        # Calculate R multiple
        r_multiple = "N/A"
        if stop_price:
            risk_per_share = abs(entry_price - stop_price)
            if risk_per_share > 0:
                pnl_per_share = exit_price - entry_price
                r_multiple = f"{pnl_per_share / risk_per_share:+.2f}R"
        
        # Calculate percentage gain
        pct_gain = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        log_line = (
            f"💰 EXIT: {exit_type:12s} │ {timestamp} │ {symbol:12s} │ "
            f"qty={format_quantity(quantity):12s} │ "
            f"entry=${entry_price:.4f} │ exit=${exit_price:.4f} │ "
            f"{pct_gain:+.2f}% │ R={r_multiple:8s} │ "
            f"realized_pnl=${realized_pnl:+10.2f}"
        )
        
        if reason:
            log_line += f" │ {reason}"
            
        self.logger.info(log_line)
    
    def log_cycle_pnl_summary(
        self,
        cycle_id: int,
        cash: float,
        positions_value: float,
        realized_pnl: float,
        unrealized_pnl: float,
        total_equity: float,
        positions: dict[str, dict[str, Any]],
        equity_change: float = 0.0
    ) -> None:
        """
        Log per-cycle P&L breakdown showing cash, positions, and equity composition.
        
        Args:
            cycle_id: Cycle number
            cash: Cash balance
            positions_value: Total value of open positions
            realized_pnl: Session realized P&L
            unrealized_pnl: Current unrealized P&L from open positions
            total_equity: Total equity (cash + positions_value)
            positions: Dictionary of open positions by symbol
            equity_change: Equity change from previous cycle
        """
        self.logger.info("═" * 100)
        self.logger.info(f"📈 CYCLE #{cycle_id} P&L SUMMARY")
        self.logger.info("═" * 100)
        
        # Equity composition
        self.logger.info("")
        self.logger.info("💰 EQUITY COMPOSITION:")
        self.logger.info(f"    Total Equity:     ${total_equity:12,.2f}  (cash + positions)")
        self.logger.info(f"    Cash Balance:     ${cash:12,.2f}  ({cash/total_equity*100:.1f}%)")
        self.logger.info(f"    Positions Value:  ${positions_value:12,.2f}  ({positions_value/total_equity*100:.1f}%)")
        
        if abs(equity_change) > 0.01:
            self.logger.info(f"    Equity Change:    ${equity_change:+12,.2f}  ({equity_change/total_equity*100:+.2f}%)")
        
        # P&L breakdown
        self.logger.info("")
        self.logger.info("💵 P&L BREAKDOWN:")
        self.logger.info(f"    Realized P&L:     ${realized_pnl:+12,.2f}  (locked in from closed trades)")
        self.logger.info(f"    Unrealized P&L:   ${unrealized_pnl:+12,.2f}  (mark-to-market from open positions)")
        self.logger.info(f"    Total P&L:        ${realized_pnl + unrealized_pnl:+12,.2f}")
        
        # Highlight where $ came from
        self.logger.info("")
        if abs(equity_change) > 0.01:
            if abs(realized_pnl) > 0.01:
                self.logger.info(f"💡 WHERE $ CAME FROM THIS CYCLE:")
                self.logger.info(f"    • Realized trades:  ${realized_pnl:+.2f}")
            if abs(unrealized_pnl) > 0.01:
                self.logger.info(f"    • Price movement:   ${unrealized_pnl:+.2f} (unrealized)")
        
        # Open positions detail
        if positions:
            self.logger.info("")
            self.logger.info(f"📊 OPEN POSITIONS ({len(positions)}):")
            for symbol, pos in positions.items():
                qty = pos.get("quantity", 0)
                if abs(qty) > 1e-8:
                    entry = pos.get("entry_price", 0)
                    current = pos.get("current_price", 0)
                    pos_value = pos.get("value", 0)
                    pos_pnl = pos.get("unrealized_pnl", 0)
                    pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
                    
                    self.logger.info(
                        f"    {symbol:12s} │ qty={format_quantity(qty):12s} │ "
                        f"entry=${entry:.4f} │ mark=${current:.4f} │ "
                        f"value=${pos_value:10.2f} │ unrealized_pnl=${pos_pnl:+10.2f} ({pnl_pct:+.2f}%)"
                    )
        else:
            self.logger.info("")
            self.logger.info("📊 OPEN POSITIONS: None")
        
        self.logger.info("═" * 100)
    
    def log_pnl_from_exits_section(
        self,
        cycle_id: int,
        exits: list[dict[str, Any]]
    ) -> None:
        """
        Log dedicated section showing P&L from TP/SL/Trail events.
        
        Args:
            cycle_id: Cycle number
            exits: List of exit events with details
        """
        if not exits:
            return
            
        self.logger.info("")
        self.logger.info("─" * 100)
        self.logger.info(f"💎 P&L FROM EXITS (Cycle #{cycle_id})")
        self.logger.info("─" * 100)
        
        total_exit_pnl = 0.0
        for exit_event in exits:
            symbol = exit_event.get("symbol", "UNKNOWN")
            exit_type = exit_event.get("exit_type", "UNKNOWN")
            quantity = exit_event.get("quantity", 0)
            exit_price = exit_event.get("exit_price", 0)
            entry_price = exit_event.get("entry_price", 0)
            pnl = exit_event.get("realized_pnl", 0)
            r_mult = exit_event.get("r_multiple", "N/A")
            
            pct_gain = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
            total_exit_pnl += pnl
            
            self.logger.info(
                f"  {exit_type:12s} │ {symbol:12s} │ "
                f"qty={format_quantity(quantity):10s} │ "
                f"${entry_price:.4f} → ${exit_price:.4f} ({pct_gain:+.2f}%) │ "
                f"R={r_mult:8s} │ P&L=${pnl:+10.2f}"
            )
        
        self.logger.info("─" * 100)
        self.logger.info(f"💰 TOTAL EXIT P&L: ${total_exit_pnl:+.2f}")
        self.logger.info("─" * 100)


# Global singleton instance
_pnl_logger = None


def get_pnl_logger() -> PnLLogger:
    """Get the global PnL logger instance."""
    global _pnl_logger
    if _pnl_logger is None:
        _pnl_logger = PnLLogger()
    return _pnl_logger


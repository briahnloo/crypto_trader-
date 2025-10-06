"""
Trade ledger for persistent recording of all executed trades.
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging_utils import LoggerMixin


class TradeLedger(LoggerMixin):
    """
    Persistent trade ledger that records all fills with complete trade information.
    
    This ledger ensures that all executed trades are immediately committed to persistent
    storage and can be queried for daily summaries and analytics.
    """
    
    def __init__(self, db_path: str = "trade_ledger.db"):
        """Initialize the trade ledger.
        
        Args:
            db_path: Path to SQLite database file
        """
        super().__init__()
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize the SQLite database with required tables."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create trades table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id TEXT UNIQUE NOT NULL,
                        session_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        fill_price REAL NOT NULL,
                        fees REAL NOT NULL,
                        notional_value REAL NOT NULL,
                        strategy TEXT NOT NULL,
                        exit_reason TEXT,
                        executed_at TIMESTAMP NOT NULL,
                        date TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes for efficient querying
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trades_session_date 
                    ON trades(session_id, date)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trades_executed_at 
                    ON trades(executed_at)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trades_symbol 
                    ON trades(symbol)
                """)
                
                # Run migrations for existing databases
                self._run_migrations(cursor)
                
                conn.commit()
                self.logger.info(f"Trade ledger database initialized at {self.db_path}")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize trade ledger database: {e}")
            raise
    
    def _run_migrations(self, cursor) -> None:
        """Run database migrations for schema updates."""
        try:
            # Check if exit_reason column exists
            cursor.execute("PRAGMA table_info(trades)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'exit_reason' not in columns:
                self.logger.info("Adding exit_reason column to trades table")
                cursor.execute("ALTER TABLE trades ADD COLUMN exit_reason TEXT")
                self.logger.info("Successfully added exit_reason column")
            else:
                self.logger.debug("exit_reason column already exists")
                
        except Exception as e:
            self.logger.error(f"Failed to run migrations: {e}")
            raise
    
    def commit_fill(
        self,
        trade_id: str,
        session_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        fees: float,
        strategy: str = "unknown",
        exit_reason: Optional[str] = None,
        executed_at: Optional[datetime] = None
    ) -> bool:
        """Commit a fill to the trade ledger.
        
        Args:
            trade_id: Unique trade identifier
            session_id: Session identifier
            symbol: Trading symbol
            side: Trade side (buy/sell)
            quantity: Trade quantity
            fill_price: Fill price
            fees: Trading fees
            strategy: Strategy name
            exit_reason: Exit reason for exit orders (optional)
            executed_at: Execution timestamp (defaults to now)
            
        Returns:
            True if successfully committed, False otherwise
        """
        if executed_at is None:
            executed_at = datetime.now(timezone.utc)
        
        # Calculate notional value
        notional_value = abs(quantity) * fill_price
        
        # Get date for partitioning
        trade_date = executed_at.date().isoformat()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if exit_reason column exists
                cursor.execute("PRAGMA table_info(trades)")
                columns = [row[1] for row in cursor.fetchall()]
                has_exit_reason = 'exit_reason' in columns
                
                if has_exit_reason:
                    # Insert trade record with exit_reason
                    cursor.execute("""
                        INSERT OR REPLACE INTO trades (
                            trade_id, session_id, symbol, side, quantity, fill_price,
                            fees, notional_value, strategy, exit_reason, executed_at, date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id, session_id, symbol, side, quantity, fill_price,
                        fees, notional_value, strategy, exit_reason, executed_at.isoformat(), trade_date
                    ))
                else:
                    # Fallback: insert without exit_reason column
                    self.logger.warning("exit_reason column missing, inserting without exit_reason")
                    cursor.execute("""
                        INSERT OR REPLACE INTO trades (
                            trade_id, session_id, symbol, side, quantity, fill_price,
                            fees, notional_value, strategy, executed_at, date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id, session_id, symbol, side, quantity, fill_price,
                        fees, notional_value, strategy, executed_at.isoformat(), trade_date
                    ))
                
                conn.commit()
                
                self.logger.debug(
                    f"Committed fill to ledger: {symbol} {side} {quantity:.6f} @ ${fill_price:.4f} "
                    f"fees=${fees:.4f} notional=${notional_value:.2f}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to commit fill to ledger: {e}")
            return False
    
    def get_trades_by_session_and_date(
        self, 
        session_id: str, 
        date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get trades for a specific session and optionally filtered by date.
        
        Args:
            session_id: Session identifier
            date: Date filter (YYYY-MM-DD format), None for all dates
            
        Returns:
            List of trade records
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # Enable column access by name
                cursor = conn.cursor()
                
                if date:
                    cursor.execute("""
                        SELECT * FROM trades 
                        WHERE session_id = ? AND date = ?
                        ORDER BY executed_at ASC
                    """, (session_id, date))
                else:
                    cursor.execute("""
                        SELECT * FROM trades 
                        WHERE session_id = ?
                        ORDER BY executed_at ASC
                    """, (session_id,))
                
                rows = cursor.fetchall()
                
                # Convert rows to dictionaries
                trades = []
                for row in rows:
                    trade = dict(row)
                    # Parse executed_at timestamp
                    if trade['executed_at']:
                        trade['executed_at'] = datetime.fromisoformat(
                            trade['executed_at'].replace('Z', '+00:00')
                        )
                    trades.append(trade)
                
                return trades
                
        except Exception as e:
            self.logger.error(f"Failed to query trades from ledger: {e}")
            return []
    
    def get_daily_trades(
        self, 
        session_id: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Get all trades for a specific session and date.
        
        Args:
            session_id: Session identifier
            date: Date in YYYY-MM-DD format
            
        Returns:
            List of trade records for the date
        """
        return self.get_trades_by_session_and_date(session_id, date)
    
    def get_trades_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all trades for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of trade records for the session
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE session_id = ? 
                    ORDER BY executed_at DESC
                """, (session_id,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            self.logger.error(f"Failed to get trades by session: {e}")
            return []
    
    def get_trades_by_date(self, date: str) -> List[Dict[str, Any]]:
        """Get all trades for a date.
        
        Args:
            date: Date in YYYY-MM-DD format
            
        Returns:
            List of trade records for the date
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM trades 
                    WHERE date = ? 
                    ORDER BY executed_at DESC
                """, (date,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            self.logger.error(f"Failed to get trades by date: {e}")
            return []
    
    def get_all_trades(self) -> List[Dict[str, Any]]:
        """Get all trades.
        
        Returns:
            List of all trade records
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM trades 
                    ORDER BY executed_at DESC
                """)
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            self.logger.error(f"Failed to get all trades: {e}")
            return []
    
    def calculate_daily_metrics(
        self, 
        date: str = None, 
        session_id: str = None
    ) -> Dict[str, Any]:
        """Calculate daily trading metrics from ledger.
        
        Args:
            date: Date in YYYY-MM-DD format (None for all dates)
            session_id: Session identifier (None for all sessions)
            
        Returns:
            Dictionary with daily metrics
        """
        if date and session_id:
            # Get trades for specific date and session
            trades = self.get_daily_trades(session_id, date)
        elif session_id:
            # Get all trades for session (all dates)
            trades = self.get_trades_by_session(session_id)
        elif date:
            # Get all trades for date (all sessions)
            trades = self.get_trades_by_date(date)
        else:
            # Get all trades
            trades = self.get_all_trades()
        
        # Filter out invalid trades (qty <= 0, price <= 0, or not committed)
        valid_trades = []
        for trade in trades:
            quantity = trade.get('quantity', 0)
            fill_price = trade.get('fill_price', 0)
            # All trades in ledger are committed by definition
            committed = True
            
            # Skip invalid trades
            if quantity <= 0 or fill_price <= 0 or not committed:
                continue
                
            valid_trades.append(trade)
        
        if not valid_trades:
            return {
                "total_trades": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "buy_trades": 0,
                "sell_trades": 0,
                "symbols_traded": [],
                "strategies_used": [],
                "win_rate": 0.0,  # Would need P&L calculation
                "avg_trade_size": 0.0,
                "largest_trade": 0.0,
                "smallest_trade": 0.0,
                "date": date,
                "session_id": session_id
            }
        
        # Calculate metrics using only valid trades
        total_trades = len(valid_trades)
        
        # Separate new exposure trades (non-reduce-only) from all trades
        new_exposure_trades = []
        for trade in valid_trades:
            # Check if this is a reduce-only exit (from metadata or exit_reason)
            is_reduce_only = (
                trade.get('exit_reason') is not None or  # Has exit reason
                trade.get('metadata', {}).get('reduce_only', False) or  # Marked as reduce-only
                trade.get('metadata', {}).get('exit_action', False)  # Marked as exit action
            )
            
            if not is_reduce_only:
                new_exposure_trades.append(trade)
        
        # Volume and notional: only count new exposure (exclude reduce-only exits)
        total_volume = sum(abs(trade['quantity']) for trade in new_exposure_trades)
        total_notional = sum(trade['notional_value'] for trade in new_exposure_trades)
        
        # Fees: count from all fills (including reduce-only exits)
        total_fees = sum(trade['fees'] for trade in valid_trades)
        
        buy_trades = len([t for t in valid_trades if t['side'].lower() == 'buy'])
        sell_trades = len([t for t in valid_trades if t['side'].lower() == 'sell'])
        
        symbols_traded = list(set(trade['symbol'] for trade in valid_trades))
        strategies_used = list(set(trade['strategy'] for trade in valid_trades))
        
        trade_sizes = [abs(trade['quantity']) for trade in valid_trades]
        avg_trade_size = sum(trade_sizes) / len(trade_sizes) if trade_sizes else 0.0
        largest_trade = max(trade_sizes) if trade_sizes else 0.0
        smallest_trade = min(trade_sizes) if trade_sizes else 0.0
        
        return {
            "total_trades": total_trades,
            "total_volume": total_volume,
            "total_fees": total_fees,
            "total_notional": total_notional,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "symbols_traded": symbols_traded,
            "strategies_used": strategies_used,
            "win_rate": 0.0,  # Would need P&L calculation from positions
            "avg_trade_size": avg_trade_size,
            "largest_trade": largest_trade,
            "smallest_trade": smallest_trade,
            "date": date,
            "session_id": session_id
        }
    
    def get_session_summary(
        self, 
        session_id: str
    ) -> Dict[str, Any]:
        """Get summary statistics for an entire session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary with session summary
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Get session statistics
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_trades,
                        SUM(ABS(quantity)) as total_volume,
                        SUM(fees) as total_fees,
                        SUM(notional_value) as total_notional,
                        MIN(executed_at) as first_trade,
                        MAX(executed_at) as last_trade,
                        COUNT(DISTINCT symbol) as symbols_traded,
                        COUNT(DISTINCT strategy) as strategies_used,
                        COUNT(DISTINCT date) as trading_days
                    FROM trades 
                    WHERE session_id = ?
                """, (session_id,))
                
                row = cursor.fetchone()
                
                if row and row['total_trades'] > 0:
                    return {
                        "session_id": session_id,
                        "total_trades": row['total_trades'],
                        "total_volume": row['total_volume'] or 0.0,
                        "total_fees": row['total_fees'] or 0.0,
                        "total_notional": row['total_notional'] or 0.0,
                        "first_trade": row['first_trade'],
                        "last_trade": row['last_trade'],
                        "symbols_traded": row['symbols_traded'],
                        "strategies_used": row['strategies_used'],
                        "trading_days": row['trading_days']
                    }
                else:
                    return {
                        "session_id": session_id,
                        "total_trades": 0,
                        "total_volume": 0.0,
                        "total_fees": 0.0,
                        "total_notional": 0.0,
                        "first_trade": None,
                        "last_trade": None,
                        "symbols_traded": 0,
                        "strategies_used": 0,
                        "trading_days": 0
                    }
                    
        except Exception as e:
            self.logger.error(f"Failed to get session summary: {e}")
            return {
                "session_id": session_id,
                "total_trades": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "first_trade": None,
                "last_trade": None,
                "symbols_traded": 0,
                "strategies_used": 0,
                "trading_days": 0
            }
    
    def cleanup_old_trades(self, days_to_keep: int = 90) -> int:
        """Clean up old trade records to manage database size.
        
        Args:
            days_to_keep: Number of days of trades to keep
            
        Returns:
            Number of records deleted
        """
        try:
            cutoff_date = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days_to_keep)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM trades 
                    WHERE executed_at < ?
                """, (cutoff_date.isoformat(),))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                self.logger.info(f"Cleaned up {deleted_count} old trade records")
                return deleted_count
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup old trades: {e}")
            return 0
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics.
        
        Returns:
            Dictionary with database statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get table info
                cursor.execute("SELECT COUNT(*) FROM trades")
                total_trades = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT session_id) FROM trades")
                total_sessions = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT date) FROM trades")
                total_days = cursor.fetchone()[0]
                
                cursor.execute("SELECT MIN(executed_at), MAX(executed_at) FROM trades")
                date_range = cursor.fetchone()
                
                return {
                    "total_trades": total_trades,
                    "total_sessions": total_sessions,
                    "total_days": total_days,
                    "date_range": date_range,
                    "database_path": self.db_path
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            return {"error": str(e)}

"""
Persistent state store for trading system using SQLite3.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.logging_utils import LoggerMixin


class StateStore(LoggerMixin):
    """
    Persistent state store for trading system data using SQLite3.
    
    Stores positions, trades, and cash/equity information across system restarts.
    """

    def __init__(self, db_path: str = "trading_state.db"):
        """Initialize the state store.
        
        Args:
            db_path: Path to SQLite database file
        """
        super().__init__()
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None
        self.initialized = False
        
        # Ensure the directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Initialize the database and create tables if they don't exist."""
        if self.initialized:
            self.logger.info("StateStore already initialized")
            return

        try:
            self.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self.connection.row_factory = sqlite3.Row  # Enable dict-like access
            
            # Create tables
            self._create_tables()
            
            self.initialized = True
            self.logger.info(f"StateStore initialized with database: {self.db_path}")

        except Exception as e:
            self.logger.error(f"Failed to initialize StateStore: {e}")
            raise

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        cursor = self.connection.cursor()
        
        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                strategy TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, strategy)
            )
        """)
        
        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fees REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                strategy TEXT NOT NULL,
                trade_id TEXT UNIQUE,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Cash/Equity table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cash_equity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cash_balance REAL NOT NULL,
                total_equity REAL NOT NULL,
                total_fees REAL NOT NULL,
                total_realized_pnl REAL NOT NULL,
                total_unrealized_pnl REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Portfolio snapshots table (for historical tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_equity REAL NOT NULL,
                cash_balance REAL NOT NULL,
                total_positions_value REAL NOT NULL,
                total_unrealized_pnl REAL NOT NULL,
                position_count INTEGER NOT NULL,
                snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_at ON portfolio_snapshots(snapshot_at)")
        
        self.connection.commit()
        self.logger.debug("Database tables created successfully")

    def save_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        strategy: str
    ) -> None:
        """Save or update a position.
        
        Args:
            symbol: Trading symbol
            quantity: Position quantity (positive for long, negative for short)
            entry_price: Entry price of the position
            current_price: Current market price
            strategy: Strategy that created the position
        """
        if not self.initialized:
            self.initialize()
        
        unrealized_pnl = (current_price - entry_price) * quantity
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO positions 
            (symbol, quantity, entry_price, current_price, unrealized_pnl, strategy, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (symbol, quantity, entry_price, current_price, unrealized_pnl, strategy))
        
        self.connection.commit()
        self.logger.debug(f"Saved position: {symbol} {quantity} @ {entry_price}")

    def update_position_price(self, symbol: str, current_price: float) -> None:
        """Update the current price of a position.
        
        Args:
            symbol: Trading symbol
            current_price: New current market price
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            UPDATE positions 
            SET current_price = ?, 
                unrealized_pnl = (current_price - entry_price) * quantity,
                updated_at = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """, (current_price, symbol))
        
        self.connection.commit()
        self.logger.debug(f"Updated position price: {symbol} @ {current_price}")

    def remove_position(self, symbol: str, strategy: str) -> None:
        """Remove a position from the store.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy that created the position
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM positions WHERE symbol = ? AND strategy = ?", (symbol, strategy))
        
        self.connection.commit()
        self.logger.debug(f"Removed position: {symbol} (strategy: {strategy})")

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all current positions.
        
        Returns:
            List of position dictionaries
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM positions ORDER BY symbol")
        
        positions = []
        for row in cursor.fetchall():
            positions.append(dict(row))
        
        return positions

    def get_position(self, symbol: str, strategy: str) -> Optional[Dict[str, Any]]:
        """Get a specific position.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy that created the position
            
        Returns:
            Position dictionary or None if not found
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT * FROM positions WHERE symbol = ? AND strategy = ?",
            (symbol, strategy)
        )
        
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fees: float,
        realized_pnl: float,
        strategy: str,
        trade_id: Optional[str] = None
    ) -> None:
        """Save a completed trade.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Trade quantity
            price: Execution price
            fees: Trading fees
            realized_pnl: Realized profit/loss
            strategy: Strategy that executed the trade
            trade_id: Optional unique trade identifier
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO trades 
            (symbol, side, quantity, price, fees, realized_pnl, strategy, trade_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, quantity, price, fees, realized_pnl, strategy, trade_id))
        
        self.connection.commit()
        self.logger.debug(f"Saved trade: {side} {quantity} {symbol} @ {price}")

    def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get trades, optionally filtered by symbol.
        
        Args:
            symbol: Optional symbol filter
            limit: Optional limit on number of trades
            
        Returns:
            List of trade dictionaries
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        
        if symbol:
            cursor.execute(
                "SELECT * FROM trades WHERE symbol = ? ORDER BY executed_at DESC",
                (symbol,)
            )
        else:
            cursor.execute("SELECT * FROM trades ORDER BY executed_at DESC")
        
        if limit:
            trades = [dict(row) for row in cursor.fetchmany(limit)]
        else:
            trades = [dict(row) for row in cursor.fetchall()]
        
        return trades

    def save_cash_equity(
        self,
        cash_balance: float,
        total_equity: float,
        total_fees: float,
        total_realized_pnl: float,
        total_unrealized_pnl: float
    ) -> None:
        """Save cash and equity information.
        
        Args:
            cash_balance: Current cash balance
            total_equity: Total portfolio equity
            total_fees: Total fees paid
            total_realized_pnl: Total realized profit/loss
            total_unrealized_pnl: Total unrealized profit/loss
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO cash_equity 
            (cash_balance, total_equity, total_fees, total_realized_pnl, total_unrealized_pnl)
            VALUES (?, ?, ?, ?, ?)
        """, (cash_balance, total_equity, total_fees, total_realized_pnl, total_unrealized_pnl))
        
        self.connection.commit()
        self.logger.debug(f"Saved cash/equity: cash=${cash_balance:,.2f}, equity=${total_equity:,.2f}")

    def get_latest_cash_equity(self) -> Optional[Dict[str, Any]]:
        """Get the latest cash and equity information.
        
        Returns:
            Latest cash/equity dictionary or None if not found
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM cash_equity ORDER BY updated_at DESC LIMIT 1")
        
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_portfolio_snapshot(
        self,
        total_equity: float,
        cash_balance: float,
        total_positions_value: float,
        total_unrealized_pnl: float,
        position_count: int
    ) -> None:
        """Save a portfolio snapshot for historical tracking.
        
        Args:
            total_equity: Total portfolio equity
            cash_balance: Current cash balance
            total_positions_value: Total value of all positions
            total_unrealized_pnl: Total unrealized profit/loss
            position_count: Number of open positions
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO portfolio_snapshots 
            (total_equity, cash_balance, total_positions_value, total_unrealized_pnl, position_count)
            VALUES (?, ?, ?, ?, ?)
        """, (total_equity, cash_balance, total_positions_value, total_unrealized_pnl, position_count))
        
        self.connection.commit()
        self.logger.debug(f"Saved portfolio snapshot: equity=${total_equity:,.2f}")

    def get_portfolio_snapshots(
        self,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get portfolio snapshots for historical analysis.
        
        Args:
            limit: Optional limit on number of snapshots
            
        Returns:
            List of portfolio snapshot dictionaries
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM portfolio_snapshots ORDER BY snapshot_at DESC")
        
        if limit:
            snapshots = [dict(row) for row in cursor.fetchmany(limit)]
        else:
            snapshots = [dict(row) for row in cursor.fetchall()]
        
        return snapshots

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get a comprehensive portfolio summary.
        
        Returns:
            Dictionary containing portfolio summary information
        """
        if not self.initialized:
            self.initialize()
        
        # Get latest cash/equity
        cash_equity = self.get_latest_cash_equity()
        
        # Get all positions
        positions = self.get_positions()
        
        # Get recent trades (last 10)
        recent_trades = self.get_trades(limit=10)
        
        # Calculate totals
        total_positions_value = sum(pos['quantity'] * pos['current_price'] for pos in positions)
        total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)
        
        return {
            "cash_equity": cash_equity,
            "positions": positions,
            "position_count": len(positions),
            "total_positions_value": total_positions_value,
            "total_unrealized_pnl": total_unrealized_pnl,
            "recent_trades": recent_trades,
            "last_updated": datetime.now().isoformat()
        }

    def clear_all_data(self) -> None:
        """Clear all data from the store (use with caution)."""
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM positions")
        cursor.execute("DELETE FROM trades")
        cursor.execute("DELETE FROM cash_equity")
        cursor.execute("DELETE FROM portfolio_snapshots")
        
        self.connection.commit()
        self.logger.warning("All data cleared from StateStore")

    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.initialized = False
            self.logger.info("StateStore connection closed")

    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

"""
Persistent state store for trading system using SQLite3.
"""

import sqlite3
import json
import random
import string
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
                value REAL NOT NULL DEFAULT 0.0,
                unrealized_pnl REAL NOT NULL,
                strategy TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, strategy, session_id)
            )
        """)
        
        # Add value column to positions table if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN value REAL NOT NULL DEFAULT 0.0")
            self.logger.info("Added value column to positions table")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                self.logger.debug("Value column already exists in positions table")
            else:
                self.logger.warning(f"Could not add value column to positions table: {e}")
        
        # Add previous_equity column to cash_equity table if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE cash_equity ADD COLUMN previous_equity REAL NOT NULL DEFAULT 0.0")
            self.logger.info("Added previous_equity column to cash_equity table")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                self.logger.debug("Previous_equity column already exists in cash_equity table")
            else:
                self.logger.warning(f"Could not add previous_equity column to cash_equity table: {e}")
        
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
                session_id TEXT NOT NULL,
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
                previous_equity REAL NOT NULL DEFAULT 0.0,
                total_fees REAL NOT NULL,
                total_realized_pnl REAL NOT NULL,
                total_unrealized_pnl REAL NOT NULL,
                session_id TEXT NOT NULL,
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
                session_id TEXT NOT NULL,
                snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Signal windows table (for rolling windows per symbol/timeframe)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                signal_value REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, strategy_name, timestamp)
            )
        """)
        
        # Composite signal windows table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS composite_signal_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                composite_score REAL NOT NULL,
                normalized_score REAL NOT NULL,
                effective_threshold REAL NOT NULL,
                regime TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, timestamp)
            )
        """)
        
        # Create session metadata table for risk-on and other session state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, key)
            )
        """)
        
        # Create lotbook table for FIFO lot tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lotbook (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                lot_id TEXT NOT NULL,
                quantity REAL NOT NULL,
                cost_price REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0.0,
                timestamp TIMESTAMP NOT NULL,
                session_id TEXT NOT NULL,
                trade_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, lot_id, session_id)
            )
        """)
        
        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_at ON portfolio_snapshots(snapshot_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_windows_symbol_timeframe ON signal_windows(symbol, timeframe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_windows_timestamp ON signal_windows(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_composite_windows_symbol_timeframe ON composite_signal_windows(symbol, timeframe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_composite_windows_timestamp ON composite_signal_windows(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_metadata_session_id ON session_metadata(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_metadata_key ON session_metadata(key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lotbook_symbol ON lotbook(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lotbook_session_id ON lotbook(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lotbook_timestamp ON lotbook(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lotbook_trade_id ON lotbook(trade_id)")
        
        self.connection.commit()
        self.logger.debug("Database tables created successfully")

    def save_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        strategy: str,
        session_id: str
    ) -> None:
        """Save or update a position.
        
        Args:
            symbol: Trading symbol (will be canonicalized)
            quantity: Position quantity (positive for long, negative for short)
            entry_price: Entry price of the position
            current_price: Current market price
            strategy: Strategy that created the position
            session_id: Session identifier
        """
        if not self.initialized:
            self.initialize()
        
        # Canonicalize symbol for consistent storage
        from ..core.utils import to_canonical
        canonical_symbol = to_canonical(symbol)
        
        unrealized_pnl = (current_price - entry_price) * quantity
        position_value = quantity * current_price
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO positions 
            (symbol, quantity, entry_price, current_price, value, unrealized_pnl, strategy, session_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (canonical_symbol, quantity, entry_price, current_price, position_value, unrealized_pnl, strategy, session_id))
        
        self.connection.commit()
        self.logger.debug(f"Saved position: {canonical_symbol} {quantity} @ {entry_price}")

    def update_position_price(self, symbol: str, current_price: float) -> None:
        """Update the current price of a position.
        
        Args:
            symbol: Trading symbol (will be canonicalized)
            current_price: New current market price
        """
        if not self.initialized:
            self.initialize()
        
        # Canonicalize symbol for consistent lookup
        from ..core.utils import to_canonical
        canonical_symbol = to_canonical(symbol)
        
        cursor = self.connection.cursor()
        cursor.execute("""
            UPDATE positions 
            SET current_price = ?, 
                value = quantity * ?,
                unrealized_pnl = (? - entry_price) * quantity,
                updated_at = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """, (current_price, current_price, current_price, canonical_symbol))
        
        self.connection.commit()
        self.logger.debug(f"Updated position price: {canonical_symbol} @ {current_price}")

    def remove_position(self, symbol: str, strategy: str) -> None:
        """Remove a position from the store.
        
        Args:
            symbol: Trading symbol (will be canonicalized)
            strategy: Strategy that created the position
        """
        if not self.initialized:
            self.initialize()
        
        # Canonicalize symbol for consistent lookup
        from ..core.utils import to_canonical
        canonical_symbol = to_canonical(symbol)
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM positions WHERE symbol = ? AND strategy = ?", (canonical_symbol, strategy))
        
        self.connection.commit()
        self.logger.debug(f"Removed position: {canonical_symbol} (strategy: {strategy})")

    def get_positions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all current positions for a session.
        
        Args:
            session_id: Session identifier (mandatory)
            
        Returns:
            List of position dictionaries
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for get_positions")
        
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM positions WHERE session_id = ? ORDER BY symbol", (session_id,))
        
        positions = []
        for row in cursor.fetchall():
            positions.append(dict(row))
        
        return positions

    def get_position(self, symbol: str, strategy: str) -> Optional[Dict[str, Any]]:
        """Get a specific position.
        
        Args:
            symbol: Trading symbol (will be canonicalized)
            strategy: Strategy that created the position
            
        Returns:
            Position dictionary or None if not found
        """
        if not self.initialized:
            self.initialize()
        
        # Canonicalize symbol for consistent lookup
        from ..core.utils import to_canonical
        canonical_symbol = to_canonical(symbol)
        
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT * FROM positions WHERE symbol = ? AND strategy = ?",
            (canonical_symbol, strategy)
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
        session_id: str,
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
            session_id: Session identifier
            trade_id: Optional unique trade identifier
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO trades 
            (symbol, side, quantity, price, fees, realized_pnl, strategy, session_id, trade_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, quantity, price, fees, realized_pnl, strategy, session_id, trade_id))
        
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
        total_unrealized_pnl: float,
        session_id: str,
        previous_equity: float = 0.0
    ) -> None:
        """Save cash and equity information.
        
        Args:
            cash_balance: Current cash balance
            total_equity: Total portfolio equity
            total_fees: Total fees paid
            total_realized_pnl: Total realized profit/loss
            total_unrealized_pnl: Total unrealized profit/loss
            session_id: Session identifier
            previous_equity: Previous cycle's equity (for P&L calculation)
        """
        if not self.initialized:
            self.initialize()
        
        # Validate data consistency before saving
        self._validate_cash_equity_data(cash_balance, total_equity, total_fees, total_realized_pnl, total_unrealized_pnl)
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO cash_equity 
            (cash_balance, total_equity, previous_equity, total_fees, total_realized_pnl, total_unrealized_pnl, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (cash_balance, total_equity, previous_equity, total_fees, total_realized_pnl, total_unrealized_pnl, session_id))
        
        self.connection.commit()
        
        # Log successful save with validation
        self.logger.debug(f"CASH_EQUITY_SAVED: cash=${cash_balance:.2f}, equity=${total_equity:.2f}, fees=${total_fees:.2f}")

    def _validate_cash_equity_data(
        self,
        cash_balance: float,
        total_equity: float,
        total_fees: float,
        total_realized_pnl: float,
        total_unrealized_pnl: float,
    ) -> None:
        """Validate cash and equity data for consistency."""
        try:
            # Check for negative values where they shouldn't be
            if cash_balance < 0:
                self.logger.warning(f"CASH_EQUITY_VALIDATION: Negative cash balance: ${cash_balance:.2f}")
            
            if total_equity < 0:
                self.logger.warning(f"CASH_EQUITY_VALIDATION: Negative total equity: ${total_equity:.2f}")
            
            if total_fees < 0:
                self.logger.warning(f"CASH_EQUITY_VALIDATION: Negative total fees: ${total_fees:.2f}")
            
            # Check for reasonable values
            if total_equity > 1000000:  # $1M seems like a reasonable upper bound for testing
                self.logger.warning(f"CASH_EQUITY_VALIDATION: Very high total equity: ${total_equity:.2f}")
            
            if total_fees > total_equity * 0.1:  # Fees shouldn't be more than 10% of equity
                self.logger.warning(f"CASH_EQUITY_VALIDATION: High fees relative to equity: ${total_fees:.2f} vs ${total_equity:.2f}")
            
            # Check for NaN or infinite values
            import math
            if math.isnan(cash_balance) or math.isinf(cash_balance):
                raise ValueError(f"Invalid cash balance: {cash_balance}")
            
            if math.isnan(total_equity) or math.isinf(total_equity):
                raise ValueError(f"Invalid total equity: {total_equity}")
            
            if math.isnan(total_fees) or math.isinf(total_fees):
                raise ValueError(f"Invalid total fees: {total_fees}")
            
            if math.isnan(total_realized_pnl) or math.isinf(total_realized_pnl):
                raise ValueError(f"Invalid total realized P&L: {total_realized_pnl}")
            
            if math.isnan(total_unrealized_pnl) or math.isinf(total_unrealized_pnl):
                raise ValueError(f"Invalid total unrealized P&L: {total_unrealized_pnl}")
                
        except Exception as e:
            self.logger.error(f"CASH_EQUITY_VALIDATION_FAILED: {e}")
            raise

    def get_latest_cash_equity(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest cash and equity information for a session.
        
        Args:
            session_id: Session identifier (mandatory)
            
        Returns:
            Latest cash/equity dictionary or None if not found
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for get_latest_cash_equity")
        
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM cash_equity WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,))
        
        row = cursor.fetchone()
        if row:
            # Get column names from cursor description
            column_names = [description[0] for description in cursor.description]
            return dict(zip(column_names, row))
        return None

    def save_portfolio_snapshot(
        self,
        total_equity: float,
        cash_balance: float,
        total_positions_value: float,
        total_unrealized_pnl: float,
        position_count: int,
        session_id: str
    ) -> None:
        """Save a portfolio snapshot for historical tracking.
        
        Args:
            total_equity: Total portfolio equity
            cash_balance: Current cash balance
            total_positions_value: Total value of all positions
            total_unrealized_pnl: Total unrealized profit/loss
            position_count: Number of open positions
            session_id: Session identifier
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO portfolio_snapshots 
            (total_equity, cash_balance, total_positions_value, total_unrealized_pnl, position_count, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (total_equity, cash_balance, total_positions_value, total_unrealized_pnl, position_count, session_id))
        
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
        cash_equity = self.get_latest_cash_equity(session_id)
        
        # Get all positions
        positions = self.get_positions(session_id)
        
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

    def clear_all_positions(self) -> None:
        """Clear all positions from the store."""
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM positions")
        self.connection.commit()
        self.logger.info("All positions cleared from StateStore")

    def clear_session_data(self, session_id: str) -> None:
        """Clear data for a specific session only."""
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM positions WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM trades WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM cash_equity WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM portfolio_snapshots WHERE session_id = ?", (session_id,))
        
        self.connection.commit()
        self.logger.info(f"Session data cleared for session {session_id}")
    
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

    def generate_session_id(self) -> str:
        """Generate a unique session ID with timestamp and random suffix.
        
        Returns:
            Unique session ID string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"session_{timestamp}_{random_suffix}"

    def new_session(
        self, 
        session_id: str, 
        start_cash: float, 
        mode: str = "paper"
    ) -> Dict[str, Any]:
        """Create a new trading session.
        
        Args:
            session_id: Unique session identifier
            start_cash: Starting cash amount
            mode: Trading mode ("paper" or "live")
            
        Returns:
            Session metadata dictionary
        """
        if not self.initialized:
            self.initialize()
        
        # Create session metadata
        session_meta = {
            "session_id": session_id,
            "start_ts": datetime.now().isoformat(),
            "mode": mode,
            "budget": start_cash
        }
        
        # Clear existing data for this session only
        self.clear_session_data(session_id)
        
        # Initialize with starting cash
        self.save_cash_equity(
            cash_balance=start_cash,
            total_equity=start_cash,
            total_fees=0.0,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            session_id=session_id,
            previous_equity=start_cash
        )
        
        # Save initial portfolio snapshot
        self.save_portfolio_snapshot(
            total_equity=start_cash,
            cash_balance=start_cash,
            total_positions_value=0.0,
            total_unrealized_pnl=0.0,
            position_count=0,
            session_id=session_id
        )
        
        self.logger.info(f"Created new session {session_id} with ${start_cash:,.2f} starting cash")
        return session_meta

    def continue_session(self, session_id: str, start_cash: float, mode: str = "paper") -> Dict[str, Any]:
        """Continue an existing session without clearing data.
        
        This method is used when we want to continue trading in an existing session
        without losing positions, cash, or other data. It only initializes if the session
        doesn't exist.
        
        Args:
            session_id: Unique session identifier
            start_cash: Starting cash amount (used only if session doesn't exist)
            mode: Trading mode ("paper" or "live")
            
        Returns:
            Session metadata dictionary
        """
        if not self.initialized:
            self.initialize()
        
        # Check if session already exists
        try:
            existing_session = self.load_session(session_id)
            if existing_session:
                self.logger.info(f"Continuing existing session {session_id} without clearing data")
                return existing_session
        except ValueError:
            # Session doesn't exist, create it
            pass
        
        # Session doesn't exist, create new one
        self.logger.info(f"Session {session_id} not found, creating new session")
        return self.new_session(session_id, start_cash, mode)

    def load_session(self, session_id: str) -> Dict[str, Any]:
        """Load an existing session by ID.
        
        Args:
            session_id: Session identifier to load
            
        Returns:
            Session metadata dictionary
            
        Raises:
            ValueError: If session not found
        """
        if not self.initialized:
            self.initialize()
        
        # Check if we have any data (positions, trades, or cash/equity)
        cursor = self.connection.cursor()
        
        # Check for existing data
        cursor.execute("SELECT COUNT(*) FROM positions")
        position_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM trades")
        trade_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM cash_equity")
        cash_equity_count = cursor.fetchone()[0]
        
        if position_count == 0 and trade_count == 0 and cash_equity_count == 0:
            raise ValueError(f"Session {session_id} not found - no data exists")
        
        # Get latest cash/equity data
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        positions = self.get_positions(session_id)
        
        session_meta = {
            "session_id": session_id,
            "start_ts": "unknown",  # We don't store session start time currently
            "mode": "unknown",      # We don't store session mode currently
            "budget": latest_cash_equity["cash_balance"] if latest_cash_equity else 0.0
        }
        
        self.logger.info(f"Loaded session {session_id} with {len(positions)} positions")
        return session_meta

    def get_session_summary(self) -> Dict[str, Any]:
        """Get current session summary.
        
        Returns:
            Session summary dictionary
        """
        if not self.initialized:
            self.initialize()
        
        # Get current state
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        positions = self.get_positions(session_id)
        recent_trades = self.get_trades(limit=5)
        
        # Calculate totals
        total_positions_value = sum(pos['quantity'] * pos['current_price'] for pos in positions)
        total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions)
        
        return {
            "cash_balance": latest_cash_equity["cash_balance"] if latest_cash_equity else 0.0,
            "total_equity": latest_cash_equity["total_equity"] if latest_cash_equity else 0.0,
            "position_count": len(positions),
            "total_positions_value": total_positions_value,
            "total_unrealized_pnl": total_unrealized_pnl,
            "recent_trades_count": len(recent_trades),
            "total_fees": latest_cash_equity["total_fees"] if latest_cash_equity else 0.0,
            "last_updated": datetime.now().isoformat()
        }

    def get_session_cash(self, session_id: str) -> float:
        """Get current session cash balance.
        
        Args:
            session_id: Session identifier (mandatory)
            
        Returns:
            Current cash balance for the session
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for get_session_cash")
        
        if not self.initialized:
            self.initialize()
        
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        return latest_cash_equity["cash_balance"] if latest_cash_equity else 0.0

    def get_session_equity(self, session_id: str) -> float:
        """Get current session total equity.
        
        Args:
            session_id: Session identifier (mandatory)
            
        Returns:
            Current total equity for the session
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for get_session_equity")
        
        if not self.initialized:
            self.initialize()
        
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        return latest_cash_equity["total_equity"] if latest_cash_equity else 0.0

    def get_session_deployed_capital(self, session_id: str) -> float:
        """Get current session deployed capital (total equity - cash balance).
        
        Args:
            session_id: Session identifier (mandatory)
            
        Returns:
            Current deployed capital for the session
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for get_session_deployed_capital")
        
        if not self.initialized:
            self.initialize()
        
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        if not latest_cash_equity:
            return 0.0
        
        # Deployed capital = total equity - cash balance
        total_equity = latest_cash_equity["total_equity"]
        cash_balance = latest_cash_equity["cash_balance"]
        deployed_capital = total_equity - cash_balance
        
        return max(0.0, deployed_capital)  # Ensure non-negative

    def debit_cash(self, session_id: str, amount: float, fees: float = 0.0) -> bool:
        """Debit cash from session (for BUY orders).
        
        Args:
            session_id: Session identifier (mandatory)
            amount: Amount to debit (notional value)
            fees: Additional fees to debit
            
        Returns:
            True if successful, False if insufficient funds
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for debit_cash")
        
        if not self.initialized:
            self.initialize()
        
        current_cash = self.get_session_cash(session_id)
        total_debit = amount + fees
        
        if total_debit > current_cash:
            self.logger.warning(f"Insufficient cash: trying to debit ${total_debit:.2f}, have ${current_cash:.2f}")
            return False
        
        new_cash = current_cash - total_debit
        
        # Get latest equity data to update
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        
        # Update cash balance
        self.save_cash_equity(
            cash_balance=new_cash,
            total_equity=latest_cash_equity["total_equity"] if latest_cash_equity else new_cash,
            total_fees=(latest_cash_equity["total_fees"] if latest_cash_equity else 0.0) + fees,
            total_realized_pnl=latest_cash_equity.get("total_realized_pnl", 0.0) if latest_cash_equity else 0.0,
            total_unrealized_pnl=latest_cash_equity.get("total_unrealized_pnl", 0.0) if latest_cash_equity else 0.0,
            session_id=session_id,
            previous_equity=latest_cash_equity.get("previous_equity", new_cash) if latest_cash_equity else new_cash
        )
        
        self.logger.debug(f"Debited ${total_debit:.2f} from cash: ${current_cash:.2f} → ${new_cash:.2f}")
        return True

    def credit_cash(self, session_id: str, amount: float, fees: float = 0.0) -> bool:
        """Credit cash to session (for SELL orders).
        
        Args:
            session_id: Session identifier (mandatory)
            amount: Amount to credit (notional value)
            fees: Fees to subtract from credit
            
        Returns:
            True if successful, False if error
            
        Raises:
            ValueError: If session_id is not provided
        """
        if not session_id:
            raise ValueError("session_id is mandatory for credit_cash")
        
        if not self.initialized:
            self.initialize()
        
        current_cash = self.get_session_cash(session_id)
        net_credit = amount - fees
        
        if net_credit < 0:
            self.logger.warning(f"Negative credit after fees: ${net_credit:.2f}")
            return False
        
        new_cash = current_cash + net_credit
        
        # Get latest equity data to update
        latest_cash_equity = self.get_latest_cash_equity(session_id)
        
        # Update cash balance
        self.save_cash_equity(
            cash_balance=new_cash,
            total_equity=latest_cash_equity["total_equity"] if latest_cash_equity else new_cash,
            total_fees=(latest_cash_equity["total_fees"] if latest_cash_equity else 0.0) + fees,
            total_realized_pnl=latest_cash_equity.get("total_realized_pnl", 0.0) if latest_cash_equity else 0.0,
            total_unrealized_pnl=latest_cash_equity.get("total_unrealized_pnl", 0.0) if latest_cash_equity else 0.0,
            session_id=session_id,
            previous_equity=latest_cash_equity.get("previous_equity", new_cash) if latest_cash_equity else new_cash
        )
        
        self.logger.debug(f"Credited ${net_credit:.2f} to cash: ${current_cash:.2f} → ${new_cash:.2f}")
        return True

    def save_signal_window(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        signal_value: float
    ) -> None:
        """Save a signal value to the rolling window.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1h', '4h')
            strategy_name: Name of the strategy
            signal_value: Signal value to store
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO signal_windows 
            (symbol, timeframe, strategy_name, signal_value, timestamp)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (symbol, timeframe, strategy_name, signal_value))
        
        # Keep only the last N=200 records per symbol/timeframe/strategy
        cursor.execute("""
            DELETE FROM signal_windows 
            WHERE symbol = ? AND timeframe = ? AND strategy_name = ?
            AND id NOT IN (
                SELECT id FROM signal_windows 
                WHERE symbol = ? AND timeframe = ? AND strategy_name = ?
                ORDER BY timestamp DESC LIMIT 200
            )
        """, (symbol, timeframe, strategy_name, symbol, timeframe, strategy_name))
        
        self.connection.commit()
        self.logger.debug(f"Saved signal window: {symbol}/{timeframe}/{strategy_name} = {signal_value:.4f}")

    def get_signal_window(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        limit: int = 200
    ) -> List[float]:
        """Get signal window values for a specific symbol/timeframe/strategy.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            strategy_name: Strategy name
            limit: Maximum number of values to return (default 200)
            
        Returns:
            List of signal values (most recent first)
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT signal_value FROM signal_windows 
            WHERE symbol = ? AND timeframe = ? AND strategy_name = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (symbol, timeframe, strategy_name, limit))
        
        return [row[0] for row in cursor.fetchall()]

    def save_composite_signal_window(
        self,
        symbol: str,
        timeframe: str,
        composite_score: float,
        normalized_score: float,
        effective_threshold: float,
        regime: str
    ) -> None:
        """Save composite signal values to the rolling window.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            composite_score: Raw composite score
            normalized_score: Normalized composite score
            effective_threshold: Effective threshold used
            regime: Market regime ('trending', 'ranging', etc.)
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO composite_signal_windows 
            (symbol, timeframe, composite_score, normalized_score, effective_threshold, regime, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (symbol, timeframe, composite_score, normalized_score, effective_threshold, regime))
        
        # Keep only the last N=200 records per symbol/timeframe
        cursor.execute("""
            DELETE FROM composite_signal_windows 
            WHERE symbol = ? AND timeframe = ?
            AND id NOT IN (
                SELECT id FROM composite_signal_windows 
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC LIMIT 200
            )
        """, (symbol, timeframe, symbol, timeframe))
        
        self.connection.commit()
        self.logger.debug(f"Saved composite signal window: {symbol}/{timeframe} score={composite_score:.4f} norm={normalized_score:.4f} thr={effective_threshold:.4f}")

    def get_composite_signal_window(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Get composite signal window values for a specific symbol/timeframe.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            limit: Maximum number of values to return (default 200)
            
        Returns:
            List of composite signal dictionaries (most recent first)
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT composite_score, normalized_score, effective_threshold, regime, timestamp
            FROM composite_signal_windows 
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (symbol, timeframe, limit))
        
        return [dict(row) for row in cursor.fetchall()]

    def get_signal_window_stats(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str
    ) -> Dict[str, float]:
        """Get statistical measures for a signal window.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            strategy_name: Strategy name
            
        Returns:
            Dictionary with mean, std, min, max, count
        """
        if not self.initialized:
            self.initialize()
        
        signals = self.get_signal_window(symbol, timeframe, strategy_name)
        
        if not signals:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        
        import statistics
        
        mean_val = statistics.mean(signals)
        std_val = statistics.stdev(signals) if len(signals) > 1 else 0.0
        min_val = min(signals)
        max_val = max(signals)
        
        return {
            "mean": mean_val,
            "std": std_val,
            "min": min_val,
            "max": max_val,
            "count": len(signals)
        }

    def get_session_metadata(self, session_id: str, key: str, default: Any = None) -> Any:
        """Get session metadata value.
        
        Args:
            session_id: Session identifier
            key: Metadata key
            default: Default value if key not found
            
        Returns:
            Metadata value or default
        """
        try:
            if not self.initialized:
                return default
            
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT value FROM session_metadata WHERE session_id = ? AND key = ?",
                (session_id, key)
            )
            result = cursor.fetchone()
            
            if result:
                # Try to parse as JSON, fallback to string
                try:
                    return json.loads(result[0])
                except (json.JSONDecodeError, ValueError):
                    return result[0]
            
            return default
            
        except Exception as e:
            self.logger.warning(f"Error getting session metadata {key}: {e}")
            return default

    def set_session_metadata(self, session_id: str, key: str, value: Any) -> bool:
        """Set session metadata value.
        
        Args:
            session_id: Session identifier
            key: Metadata key
            value: Metadata value (will be JSON serialized)
            
        Returns:
            True if successful
        """
        try:
            if not self.initialized:
                return False
            
            # Serialize value as JSON
            json_value = json.dumps(value)
            
            cursor = self.connection.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO session_metadata (session_id, key, value, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (session_id, key, json_value, datetime.now().isoformat())
            )
            self.connection.commit()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting session metadata {key}: {e}")
            return False

    # LotBook persistence methods
    
    def save_lot(
        self,
        symbol: str,
        lot_id: str,
        quantity: float,
        cost_price: float,
        fee: float,
        timestamp: datetime,
        session_id: str,
        trade_id: Optional[str] = None
    ) -> None:
        """Save a lot to the lotbook.
        
        Args:
            symbol: Trading symbol
            lot_id: Unique lot identifier
            quantity: Lot quantity
            cost_price: Cost price per unit
            fee: Trading fees for this lot
            timestamp: When the lot was created
            session_id: Session identifier
            trade_id: Optional exchange trade ID for idempotency
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO lotbook 
            (symbol, lot_id, quantity, cost_price, fee, timestamp, session_id, trade_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, lot_id, quantity, cost_price, fee, timestamp.isoformat(), session_id, trade_id))
        
        self.connection.commit()
        self.logger.debug(f"Saved lot {lot_id}: {quantity:.6f} {symbol} @ ${cost_price:.4f}")

    def get_lotbook(self, symbol: str, session_id: str) -> List[Dict[str, Any]]:
        """Get all lots for a symbol in FIFO order.
        
        Args:
            symbol: Trading symbol
            session_id: Session identifier
            
        Returns:
            List of lot dictionaries in FIFO order (oldest first)
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT * FROM lotbook 
            WHERE symbol = ? AND session_id = ? 
            ORDER BY timestamp ASC, id ASC
        """, (symbol, session_id))
        
        lots = []
        for row in cursor.fetchall():
            lot_dict = dict(row)
            # Convert timestamp string back to datetime if needed
            if isinstance(lot_dict.get('timestamp'), str):
                try:
                    lot_dict['timestamp'] = datetime.fromisoformat(lot_dict['timestamp'])
                except ValueError:
                    pass  # Keep as string if parsing fails
            lots.append(lot_dict)
        
        return lots

    def set_lotbook(self, symbol: str, lots: List[Dict[str, Any]], session_id: str) -> None:
        """Set all lots for a symbol (replaces existing).
        
        Args:
            symbol: Trading symbol
            lots: List of lot dictionaries
            session_id: Session identifier
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        
        # Remove existing lots for this symbol/session
        cursor.execute("DELETE FROM lotbook WHERE symbol = ? AND session_id = ?", (symbol, session_id))
        
        # Insert new lots
        for lot in lots:
            cursor.execute("""
                INSERT INTO lotbook 
                (symbol, lot_id, quantity, cost_price, fee, timestamp, session_id, trade_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                lot.get('lot_id', ''),
                lot.get('quantity', 0.0),
                lot.get('cost_price', 0.0),
                lot.get('fee', 0.0),
                lot.get('timestamp', datetime.now()).isoformat() if isinstance(lot.get('timestamp'), datetime) else str(lot.get('timestamp', datetime.now())),
                session_id,
                lot.get('trade_id')
            ))
        
        self.connection.commit()
        self.logger.debug(f"Set lotbook for {symbol}: {len(lots)} lots")

    def snapshot_all_lotbooks(self, session_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get all lotbooks for all symbols in the session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary mapping symbol -> list of lots
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT symbol FROM lotbook 
            WHERE session_id = ? 
            GROUP BY symbol
        """, (session_id,))
        
        symbols = [row[0] for row in cursor.fetchall()]
        
        lotbooks = {}
        for symbol in symbols:
            lotbooks[symbol] = self.get_lotbook(symbol, session_id)
        
        self.logger.debug(f"Snapshot lotbooks: {len(symbols)} symbols with lots")
        return lotbooks

    def load_all_lotbooks(self, session_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Load all lotbooks for all symbols in the session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary mapping symbol -> list of lots
        """
        return self.snapshot_all_lotbooks(session_id)

    def clear_lotbook(self, symbol: str, session_id: str) -> int:
        """Clear all lots for a symbol.
        
        Args:
            symbol: Trading symbol
            session_id: Session identifier
            
        Returns:
            Number of lots cleared
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM lotbook WHERE symbol = ? AND session_id = ?", (symbol, session_id))
        
        cleared_count = cursor.rowcount
        self.connection.commit()
        
        self.logger.debug(f"Cleared {cleared_count} lots for {symbol}")
        return cleared_count

    def clear_all_lotbooks(self, session_id: str) -> int:
        """Clear all lotbooks for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Total number of lots cleared
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM lotbook WHERE session_id = ?", (session_id,))
        
        cleared_count = cursor.rowcount
        self.connection.commit()
        
        self.logger.debug(f"Cleared all {cleared_count} lots for session {session_id}")
        return cleared_count

    def get_lotbook_summary(self, session_id: str) -> Dict[str, Any]:
        """Get summary of all lotbooks in the session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary with lotbook summary information
        """
        if not self.initialized:
            self.initialize()
        
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT 
                symbol,
                COUNT(*) as lot_count,
                SUM(quantity) as total_quantity,
                SUM(quantity * cost_price + fee) as total_cost,
                AVG(cost_price) as avg_cost_price
            FROM lotbook 
            WHERE session_id = ? 
            GROUP BY symbol
        """, (session_id,))
        
        summary = {
            "session_id": session_id,
            "total_symbols": 0,
            "total_lots": 0,
            "symbols": {}
        }
        
        for row in cursor.fetchall():
            symbol, lot_count, total_quantity, total_cost, avg_cost_price = row
            summary["symbols"][symbol] = {
                "lot_count": lot_count,
                "total_quantity": total_quantity or 0.0,
                "total_cost": total_cost or 0.0,
                "avg_cost_price": avg_cost_price or 0.0
            }
            summary["total_lots"] += lot_count
        
        summary["total_symbols"] = len(summary["symbols"])
        
        return summary

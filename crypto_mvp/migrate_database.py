#!/usr/bin/env python3
"""
Database schema migration script to add session_id columns to existing tables.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime

def migrate_database():
    """Add session_id columns to existing database tables."""
    db_path = Path("trading_state.db")
    
    if not db_path.exists():
        print("No database file found. Schema will be created on first run.")
        return
    
    print(f"Migrating database: {db_path}")
    print(f"Migration started at: {datetime.now()}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check current schema
        print("\n--- Current Schema Check ---")
        cursor.execute("PRAGMA table_info(positions)")
        positions_columns = [row[1] for row in cursor.fetchall()]
        print(f"Positions columns: {positions_columns}")
        
        cursor.execute("PRAGMA table_info(cash_equity)")
        cash_equity_columns = [row[1] for row in cursor.fetchall()]
        print(f"Cash_equity columns: {cash_equity_columns}")
        
        cursor.execute("PRAGMA table_info(trades)")
        trades_columns = [row[1] for row in cursor.fetchall()]
        print(f"Trades columns: {trades_columns}")
        
        cursor.execute("PRAGMA table_info(portfolio_snapshots)")
        portfolio_columns = [row[1] for row in cursor.fetchall()]
        print(f"Portfolio_snapshots columns: {portfolio_columns}")
        
        print("\n--- Adding session_id columns ---")
        
        # Add session_id column to positions table
        if 'session_id' not in positions_columns:
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN session_id TEXT")
                cursor.execute("UPDATE positions SET session_id = 'default' WHERE session_id IS NULL")
                print("✓ Added session_id to positions table")
            except Exception as e:
                print(f"  positions table: {e}")
        else:
            print("  positions table: session_id already exists")
        
        # Add session_id column to trades table
        if 'session_id' not in trades_columns:
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN session_id TEXT")
                cursor.execute("UPDATE trades SET session_id = 'default' WHERE session_id IS NULL")
                print("✓ Added session_id to trades table")
            except Exception as e:
                print(f"  trades table: {e}")
        else:
            print("  trades table: session_id already exists")
        
        # Add session_id column to cash_equity table
        if 'session_id' not in cash_equity_columns:
            try:
                cursor.execute("ALTER TABLE cash_equity ADD COLUMN session_id TEXT")
                cursor.execute("UPDATE cash_equity SET session_id = 'default' WHERE session_id IS NULL")
                print("✓ Added session_id to cash_equity table")
            except Exception as e:
                print(f"  cash_equity table: {e}")
        else:
            print("  cash_equity table: session_id already exists")
        
        # Add session_id column to portfolio_snapshots table
        if 'session_id' not in portfolio_columns:
            try:
                cursor.execute("ALTER TABLE portfolio_snapshots ADD COLUMN session_id TEXT")
                cursor.execute("UPDATE portfolio_snapshots SET session_id = 'default' WHERE session_id IS NULL")
                print("✓ Added session_id to portfolio_snapshots table")
            except Exception as e:
                print(f"  portfolio_snapshots table: {e}")
        else:
            print("  portfolio_snapshots table: session_id already exists")
        
        print("\n--- Updating constraints and indexes ---")
        
        # Drop old unique constraints and create new ones with session_id
        try:
            cursor.execute("DROP INDEX IF EXISTS idx_positions_symbol_strategy")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_symbol_strategy_session ON positions(symbol, strategy, session_id)")
            print("✓ Updated positions unique constraint")
        except Exception as e:
            print(f"  positions constraint: {e}")
        
        # Create indexes for session_id columns
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_session_id ON positions(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_session_id ON trades(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cash_equity_session_id ON cash_equity(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_session_id ON portfolio_snapshots(session_id)")
            print("✓ Created session_id indexes")
        except Exception as e:
            print(f"  indexes: {e}")
        
        conn.commit()
        print("\n✓ Database migration completed successfully")
        
        # Verify migration
        print("\n--- Verification ---")
        cursor.execute("PRAGMA table_info(positions)")
        positions_columns_after = [row[1] for row in cursor.fetchall()]
        print(f"Positions columns after: {positions_columns_after}")
        
        cursor.execute("SELECT COUNT(*) FROM positions WHERE session_id IS NOT NULL")
        positions_count = cursor.fetchone()[0]
        print(f"Positions with session_id: {positions_count}")
        
        cursor.execute("SELECT COUNT(*) FROM cash_equity WHERE session_id IS NOT NULL")
        cash_equity_count = cursor.fetchone()[0]
        print(f"Cash_equity records with session_id: {cash_equity_count}")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
    
    print(f"Migration completed at: {datetime.now()}")

if __name__ == "__main__":
    migrate_database()

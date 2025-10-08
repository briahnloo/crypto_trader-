#!/usr/bin/env python3
"""
Fix the database by properly debiting cash for existing positions.
"""
import sqlite3
from pathlib import Path

# Find the database
db_path = Path("trading_state.db")
if not db_path.exists():
    db_path = Path("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/trading_state.db")
if not db_path.exists():
    db_path = Path("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/trading_state.db")

print(f"📂 Database: {db_path}")

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get latest session
cursor.execute("""
    SELECT DISTINCT session_id 
    FROM cash_equity 
    ORDER BY id DESC 
    LIMIT 1
""")
latest_session = cursor.fetchone()[0]
print(f"📊 Session: {latest_session}")

# Calculate total position value
cursor.execute("""
    SELECT SUM(quantity * entry_price) as total_value
    FROM positions 
    WHERE session_id = ?
""", (latest_session,))
total_position_value = cursor.fetchone()[0] or 0

print(f"💰 Total position value: ${total_position_value:,.2f}")

# Get initial cash
cursor.execute("""
    SELECT cash_balance 
    FROM cash_equity 
    WHERE session_id = ?
    ORDER BY id ASC
    LIMIT 1
""", (latest_session,))
initial_cash = cursor.fetchone()[0]
print(f"💵 Initial cash: ${initial_cash:,.2f}")

# Calculate correct cash
correct_cash = initial_cash - total_position_value
print(f"✅ Correct cash should be: ${correct_cash:,.2f}")

# Get current cash
cursor.execute("""
    SELECT cash_balance 
    FROM cash_equity 
    WHERE session_id = ?
    ORDER BY id DESC
    LIMIT 1
""", (latest_session,))
current_cash = cursor.fetchone()[0]
print(f"❌ Current cash in DB: ${current_cash:,.2f}")
print(f"📉 Difference: ${current_cash - correct_cash:,.2f}")

# Ask for confirmation
print("\n" + "=" * 80)
print("⚠️  This will UPDATE the cash_equity table to debit cash for existing positions.")
print(f"⚠️  Cash will be changed from ${current_cash:,.2f} to ${correct_cash:,.2f}")
print("=" * 80)
response = input("Continue? (yes/no): ")

if response.lower() != 'yes':
    print("Aborted.")
    conn.close()
    exit(0)

# Update cash_equity
correct_equity = correct_cash + total_position_value
cursor.execute("""
    INSERT INTO cash_equity 
    (cash_balance, total_equity, total_fees, total_realized_pnl, total_unrealized_pnl, session_id)
    VALUES (?, ?, 0.0, 0.0, 0.0, ?)
""", (correct_cash, correct_equity, latest_session))

conn.commit()

print(f"\n✅ Fixed! Cash updated to ${correct_cash:,.2f}")
print(f"✅ Equity updated to ${correct_equity:,.2f}")
print(f"✅ Formula: ${correct_cash:,.2f} (cash) + ${total_position_value:,.2f} (positions) = ${correct_equity:,.2f}")

conn.close()


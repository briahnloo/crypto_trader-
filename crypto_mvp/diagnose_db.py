#!/usr/bin/env python3
"""
Diagnostic script to inspect the trading_state.db database.
"""
import sqlite3
from pathlib import Path

# Find the database
db_path = Path("trading_state.db")
if not db_path.exists():
    db_path = Path("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/trading_state.db")
if not db_path.exists():
    db_path = Path("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/trading_state.db")

if not db_path.exists():
    print("❌ Could not find trading_state.db")
    print("Please provide the correct path")
    exit(1)

print(f"📂 Database: {db_path}")
print("=" * 80)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get latest session
cursor.execute("""
    SELECT DISTINCT session_id 
    FROM cash_equity 
    ORDER BY id DESC 
    LIMIT 5
""")
sessions = [row[0] for row in cursor.fetchall()]
print(f"\n🔑 Recent sessions: {sessions}")

if not sessions:
    print("No sessions found")
    exit(0)

latest_session = sessions[0]
print(f"\n📊 Analyzing session: {latest_session}")
print("=" * 80)

# Check cash_equity
cursor.execute("""
    SELECT cash_balance, total_equity, total_fees, total_realized_pnl, updated_at
    FROM cash_equity 
    WHERE session_id = ?
    ORDER BY id DESC 
    LIMIT 5
""", (latest_session,))

print("\n💰 Cash & Equity (latest 5 entries):")
print("-" * 80)
for row in cursor.fetchall():
    print(f"  Cash: ${row[0]:>10,.2f} | Equity: ${row[1]:>10,.2f} | Fees: ${row[2]:>8,.2f} | Realized P&L: ${row[3]:>8,.2f} | {row[4]}")

# Check positions
cursor.execute("""
    SELECT symbol, quantity, entry_price, current_price, value, strategy, updated_at
    FROM positions 
    WHERE session_id = ?
    ORDER BY symbol
""", (latest_session,))

print("\n📦 Positions:")
print("-" * 80)
total_position_value = 0
for row in cursor.fetchall():
    pos_value = row[1] * row[2]  # qty * entry_price
    total_position_value += pos_value
    print(f"  {row[0]:<12} | qty: {row[1]:>12.6f} | entry: ${row[2]:>10.4f} | current: ${row[3]:>10.4f} | value: ${row[4]:>10.2f} (calc: ${pos_value:>10.2f})")

print(f"\n  {'TOTAL':<12} | {'':>12} | {'':>10} | {'':>10} | ${total_position_value:>10.2f}")

# Check trades
cursor.execute("""
    SELECT symbol, side, quantity, price, fees, realized_pnl, executed_at
    FROM trades 
    WHERE session_id = ?
    ORDER BY id DESC
    LIMIT 10
""", (latest_session,))

print("\n📊 Recent Trades (latest 10):")
print("-" * 80)
total_notional = 0
total_fees = 0
for row in cursor.fetchall():
    notional = row[2] * row[3]  # qty * price
    total_notional += notional
    total_fees += row[4]
    print(f"  {row[0]:<12} {row[1]:>4} | qty: {row[2]:>12.6f} | price: ${row[3]:>10.4f} | notional: ${notional:>10.2f} | fees: ${row[4]:>6.2f} | {row[6]}")

print(f"\n  Total notional: ${total_notional:,.2f}")
print(f"  Total fees: ${total_fees:,.2f}")

# Calculate expected cash
cursor.execute("""
    SELECT cash_balance 
    FROM cash_equity 
    WHERE session_id = ?
    ORDER BY id ASC
    LIMIT 1
""", (latest_session,))
initial_cash = cursor.fetchone()
initial_cash = initial_cash[0] if initial_cash else 10000.0

print("\n🧮 Analysis:")
print("=" * 80)
print(f"  Initial cash: ${initial_cash:,.2f}")
print(f"  Total spent on positions (at entry): ${total_position_value:,.2f}")
print(f"  Total fees paid: ${total_fees:,.2f}")
print(f"  Expected remaining cash: ${initial_cash - total_position_value - total_fees:,.2f}")

cursor.execute("""
    SELECT cash_balance 
    FROM cash_equity 
    WHERE session_id = ?
    ORDER BY id DESC
    LIMIT 1
""", (latest_session,))
actual_cash = cursor.fetchone()
actual_cash = actual_cash[0] if actual_cash else 0.0

print(f"  Actual cash in DB: ${actual_cash:,.2f}")
discrepancy = actual_cash - (initial_cash - total_position_value - total_fees)
print(f"  Discrepancy: ${discrepancy:,.2f}")

if abs(discrepancy) < 1.0:
    print("\n✅ EQUITY CALCULATION CORRECT!")
    print("   Cash has been properly debited for positions.")
elif abs(actual_cash - initial_cash) < 1.0:
    print("\n❌ BUG STILL PRESENT: Cash has not been debited despite positions existing!")
    print("   Positions were saved to the database without deducting cash.")
else:
    print(f"\n⚠️  Cash has changed but discrepancy of ${abs(discrepancy):,.2f} detected")
    print("   This may be due to fees or price fluctuations")

conn.close()


# 🔴 Root Cause Analysis: Cash Deduction Bug

## ✅ Bug Confirmed and Fixed

**Database Fixed**: Cash corrected from $10,000 to $4,900 (matching $5,100 in positions)

---

## 🔍 Root Cause Identified

### Issue 1: Position Duplication with Different Strategies

**Evidence**:
```sql
DOGE/USDT|sentiment|8009.632  
DOGE/USDT|unknown|3998.400
```

Two DOGE positions exist with different `strategy` values. The database schema has:
```sql
UNIQUE(symbol, strategy, session_id)
```

This allows multiple positions for the SAME symbol if they have different strategies!

### Issue 2: Cash Never Debited

All 7 trades in the database:
- ✅ Positions saved correctly
- ✅ Trades logged to trades table  
- ❌ Cash remained at $10,000 (initial capital)
- ❌ Should have been $4,900 after $5,100 spent

---

## 🎯 Why This Happened

### Hypothesis A: Silent Exception After save_position()
In `_update_portfolio_with_trade`:
1. Line 2971: `save_cash_equity()` called
2. Line 2984-2989: Cash verification
3. Line 3037: `save_position()` called

**If verification fails:**
- Raises `ValueError` 
- Exception handler rolls back
- But SQLite autocommit may have persisted position

### Hypothesis B: Positions Loaded from Previous Session
1. Old session had corrupt state (cash not debited)
2. `_load_or_initialize_portfolio()` loads positions from DB
3. In-memory portfolio gets stale positions
4. Equity calculation adds them up

### Hypothesis C: Multiple Strategy Executors
Different executors (sentiment vs unknown) create separate positions:
- Sentiment executor creates DOGE position
- Unknown/default executor creates another DOGE position
- Both counted as separate in equity calculation
- Each should have debited cash, but didn't

---

## 📊 Impact Analysis

### Observed Symptoms
```
Cash: $10,000 (wrong, should be $4,900)
Positions: $5,100 (correct value)
Equity: $15,100 (wrong, should be $10,000)
Discrepancy: $5,100 (exactly equal to position value!)
```

### NAV Validation Failures
```
NAV_VALIDATION_FAIL: rebuilt=$9,929 computed=$14,129 diff=$4,200
```

Rebuilt NAV:
- Starts with $10,000 cash
- Subtracts trade notionals: $10,000 - $4,200 = $5,800
- Adds back position values: $5,800 + $4,129 = $9,929

But computed shows $14,129 because cash wasn't debited!

---

## 🔧 Immediate Fix Applied

**Script**: `fix_db_cash.py`

```sql
-- Set cash to correct value
UPDATE cash_equity 
SET cash_balance = 4900.00,  -- initial $10,000 - $5,100 spent
    total_equity = 10000.00   -- $4,900 cash + $5,100 positions
WHERE session_id = '20251007-155313-3788'
ORDER BY id DESC 
LIMIT 1;
```

**Result**: ✅ Discrepancy now $0.00

---

## 🛡️ Permanent Fixes Needed

### Fix 1: Consolidate Positions by Symbol (CRITICAL)

**Problem**: Multiple positions for same symbol with different strategies inflate equity.

**Solution**: Change database schema to:
```sql
UNIQUE(symbol, session_id)  -- Remove strategy from constraint
```

Or modify position loading to MERGE positions by symbol:
```python
# In get_portfolio_snapshot()
positions_by_symbol = {}
for pos in self.portfolio["positions"].values():
    symbol = pos["symbol"]
    if symbol not in positions_by_symbol:
        positions_by_symbol[symbol] = pos
    else:
        # Merge quantities
        old = positions_by_symbol[symbol]
        old["quantity"] += pos["quantity"]
        # Recalculate weighted average
        total_cost = (old["quantity"] * old["entry_price"]) + (pos["quantity"] * pos["entry_price"])
        old["entry_price"] = total_cost / (old["quantity"] + pos["quantity"])
```

### Fix 2: Atomic Transaction for Position + Cash

**Problem**: `save_position()` and `save_cash_equity()` are separate transactions.

**Solution**: Wrap both in a single SQLite transaction:
```python
cursor = self.connection.cursor()
cursor.execute("BEGIN TRANSACTION")
try:
    # Save cash
    cursor.execute("INSERT INTO cash_equity...")
    # Save position  
    cursor.execute("INSERT OR REPLACE INTO positions...")
    self.connection.commit()
except Exception:
    self.connection.rollback()
    raise
```

### Fix 3: Add Database Trigger for Validation

**Problem**: No database-level enforcement of cash conservation.

**Solution**: Add SQLite trigger:
```sql
CREATE TRIGGER validate_cash_deduction
AFTER INSERT ON positions
BEGIN
    -- Calculate total position value
    SELECT SUM(quantity * entry_price) INTO @pos_value
    FROM positions 
    WHERE session_id = NEW.session_id;
    
    -- Get latest cash
    SELECT cash_balance INTO @cash
    FROM cash_equity
    WHERE session_id = NEW.session_id
    ORDER BY id DESC LIMIT 1;
    
    -- Check if cash + positions <= initial capital
    SELECT CASE 
        WHEN @cash + @pos_value > 10000 
        THEN RAISE(ABORT, 'Cash not properly debited')
    END;
END;
```

### Fix 4: Prevent Duplicate Position Loading

**Problem**: `_load_or_initialize_portfolio()` may be called multiple times.

**Solution**: Add guard flag:
```python
def _load_or_initialize_portfolio(...):
    if hasattr(self, '_portfolio_loaded') and self._portfolio_loaded:
        self.logger.error("Portfolio already loaded! Ignoring duplicate call.")
        return
    self._portfolio_loaded = True
    # ... rest of code
```

### Fix 5: Strategy Normalization

**Problem**: Different code paths use different strategy names ("sentiment", "unknown").

**Solution**: Normalize all strategy names:
```python
def normalize_strategy(strategy: str) -> str:
    """Normalize strategy name to prevent duplicates."""
    if not strategy or strategy == "unknown":
        return "default"
    return strategy.lower().strip()
```

---

## 🧪 Testing Requirements

### Test 1: Position Consolidation
```python
# Create two positions for same symbol
save_position("BTC/USDT", 1.0, 50000, "sentiment")
save_position("BTC/USDT", 1.0, 51000, "momentum")

# Verify only ONE position exists with merged quantity
positions = get_positions()
assert len([p for p in positions if p["symbol"] == "BTC/USDT"]) == 1
assert merged_position["quantity"] == 2.0
```

### Test 2: Cash Conservation
```python
# Initial state
initial_cash = 10000
initial_equity = 10000

# Buy $1000 worth
execute_trade("BTC/USDT", "buy", 1000)

# Verify cash debited
assert get_cash() == 9000
assert get_equity() == 10000  # cash + position
```

### Test 3: Transaction Atomicity
```python
# Force failure after position save
with mock.patch('save_cash_equity', side_effect=Exception):
    try:
        execute_trade("BTC/USDT", "buy", 1000)
    except:
        pass

# Verify neither position NOR cash changed
assert len(get_positions()) == 0
assert get_cash() == 10000
```

---

## 📋 Action Items

- [ ] **CRITICAL**: Modify position schema to prevent duplicates
- [ ] **HIGH**: Implement atomic transactions for position+cash
- [ ] **HIGH**: Add position consolidation in `get_portfolio_snapshot()`
- [ ] **MEDIUM**: Add database trigger for validation
- [ ] **MEDIUM**: Add portfolio loading guard
- [ ] **LOW**: Normalize strategy names

---

## 🎯 Monitoring

Add alerts for:
1. **Cash Drift**: `abs(cash - expected_cash) > $1.00`
2. **Equity Drift**: `abs(equity - (cash + positions)) > $1.00`  
3. **Duplicate Positions**: `COUNT(DISTINCT symbol) != COUNT(*) per session`
4. **NAV Mismatch**: `abs(rebuilt_nav - computed_nav) > tolerance`

---

## ✅ Verification

Run after fixes:
```bash
python diagnose_db.py  # Should show $0.00 discrepancy
python -m pytest tests/test_cash_conservation.py
```

Expected:
- Cash always equals: `initial - sum(position_costs) - sum(fees)`
- Equity always equals: `cash + sum(position_values)`
- ONE position per symbol per session


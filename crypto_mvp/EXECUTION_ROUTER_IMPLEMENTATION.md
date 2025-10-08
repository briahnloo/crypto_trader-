# Execution Router Implementation - Deterministic Action Mapping

## Goal ✅
- `final_action=SELL` → actual short/sell or proper skip (never BUY fills)
- Exploration budget affects ONLY exploration orders
- Normal trades ignore exploration limits

## Implementation

### File Created
**Location:** `crypto_mvp/src/crypto_mvp/execution/execution_router.py`

### Core Components

#### 1. Deterministic Action Mapping
```python
final_action → (OrderSideAction, OrderIntent, reason)

# Examples:
"BUY" → (BUY, NORMAL, "open_long")
"SELL" → (SELL, NORMAL, "open_short")  # If shorting allowed
"SELL" → (SKIP, NORMAL, "shorting_disabled")  # If shorting disabled
```

#### 2. Order Intents
```python
class OrderIntent(Enum):
    NORMAL = "normal"          # Regular high-quality trade
    PILOT = "pilot"            # Relaxed RR pilot trade  
    EXPLORE = "explore"        # Exploration budget trade
    EXIT = "exit"              # Position exit
    RISK_MANAGEMENT = "risk"   # Stop/TP management
```

**Budget Checks:**
- `NORMAL`: ✅ Bypasses exploration budget
- `PILOT`: ⚠️ Checks exploration budget
- `EXPLORE`: ⚠️ Checks exploration budget

#### 3. Shorting Constraint Handling

**When Shorting Disabled:**
```python
if final_action == "SELL" and not shorting_allowed:
    if has_position and position_side == "long":
        → (SELL, EXIT, "close_long")  # Allow closing longs
    else:
        → (SKIP, NORMAL, "shorting_disabled")  # Prevent opening shorts
```

**Result:** SELL signals downgraded to "Close longs / Do not open shorts"

### Integration Points

#### 1. Normal Trades
```python
# In _execute_profit_optimized_trades()
routed_side, order_intent, route_reason = self.execution_router.route_action(
    final_action=initial_action,  # "BUY" or "SELL"
    symbol=symbol,
    has_position=has_position,
    position_side=position_side,
    is_pilot=False,
    is_exploration=False  # Normal trades
)

# Create metadata with proper tagging
order_metadata = self.execution_router.create_order_metadata(
    intent=order_intent,  # OrderIntent.NORMAL
    strategy=strategy_name,
    signal_data=signal,
    stop_loss=stop_loss,
    take_profit=take_profit,
    risk_reward_ratio=rr_ratio
)

# Normal trades NEVER check exploration budget
# They proceed directly to execution
```

#### 2. Pilot Trades
```python
# In _execute_pilot_trade()
routed_side, order_intent, route_reason = self.execution_router.route_action(
    final_action=initial_action,
    symbol=symbol,
    has_position=has_position,
    position_side=position_side,
    is_pilot=True,
    is_exploration=False  # Pilots are separate from exploration
)

# Pilots check exploration budget
if not self.can_explore(pilot_target_notional):
    return None
    
# Create metadata with PILOT tagging
order_metadata = self.execution_router.create_order_metadata(
    intent=OrderIntent.PILOT,  # Tagged as pilot
    strategy=strategy_name,
    signal_data=signal
)
```

#### 3. Exploration Trades
```python
# In _execute_exploration_trade()
routed_side, order_intent, route_reason = self.execution_router.route_action(
    final_action=initial_action,
    symbol=symbol,
    has_position=has_position,
    position_side=position_side,
    is_pilot=False,
    is_exploration=True  # Tag as EXPLORATION
)

# Exploration trades check exploration budget
if not self.can_explore(exploration_target_notional):
    return None
    
# Create metadata with EXPLORE tagging
order_metadata = self.execution_router.create_order_metadata(
    intent=OrderIntent.EXPLORE,  # Tagged as exploration
    strategy=strategy_name,
    signal_data=signal
)

# Metadata includes:
# - order_intent: "explore"
# - is_exploration: True
# - is_pilot: False
# - is_normal: False
```

## Order Metadata Structure

All orders now include:
```python
{
    "strategy": "momentum",
    "order_intent": "normal",  # "normal", "pilot", or "explore"
    "is_exploration": False,
    "is_pilot": False,
    "is_normal": True,
    "signal_score": 0.65,
    "confidence": 0.75,
    "stop_loss": 98000.0,
    "take_profit": 102000.0,
    "risk_reward_ratio": 2.0
}
```

## Shorting Configuration

**In config/profit_optimized.yaml:**
```yaml
risk:
  short_enabled: false  # Global shorting toggle

symbols:
  BTC/USDT:
    allow_short: false  # Symbol-specific shorting
  ETH/USDT:
    allow_short: false
```

**Shorting Allowed When:**
- `risk.short_enabled = true` AND
- `symbols.<SYMBOL>.allow_short = true`

## Log Output Examples

### Normal Trade (BUY) - Bypasses Exploration Budget
```
INFO: ACTION_ROUTE: BUY → BUY (intent=normal, reason=open_long)
INFO: POSITION_SIZE: BTC/USDT buy qty=0.012500 notional=$1,250.00 (order_intent=normal)
INFO: Trade executed with intent=NORMAL (exploration budget NOT checked)
```

### Normal Trade (SELL) - Shorting Disabled
```
INFO: ACTION_ROUTE: SELL → SKIP (intent=normal, reason=shorting_disabled)
INFO: SKIP BTC/USDT SELL reason=shorting_disabled
INFO: SELL signal for BTC/USDT downgraded to SKIP: shorting_disabled
```

### Normal Trade (SELL) - Closing Long
```
INFO: ACTION_ROUTE: SELL → SELL (intent=exit, reason=close_long)
INFO: POSITION_SIZE: BTC/USDT sell qty=0.012500 (order_intent=exit)
INFO: Closing long position in BTC/USDT
```

### Pilot Trade - Checks Exploration Budget
```
INFO: ACTION_ROUTE: BUY → BUY (intent=pilot, reason=open_long)
INFO: 🚁 PILOT: target_notional=$1,000.00 * 0.4 = $400.00
INFO: Checking exploration budget for pilot trade: $400.00
INFO: EXPLORATION: can_explore passed (need $400.00, have $800.00 left)
INFO: Trade executed with intent=PILOT
```

### Exploration Trade - Tagged with order_intent="explore"
```
INFO: ACTION_ROUTE: BUY → BUY (intent=explore, reason=open_long)
INFO: 🔍 EXPLORATION: target_notional=$500.00 * 0.5 = $250.00
INFO: Checking exploration budget: $250.00
INFO: EXPLORATION: can_explore passed (need $250.00, have $550.00 left)
INFO: Trade executed with intent=EXPLORE (is_exploration=True, is_pilot=False)
```

### Exploration Budget Exhausted - Normal Trades Still Go Through
```
INFO: EXPLORATION budget exhausted: used=$300.00, limit=$300.00
INFO: SKIP EXPLORATION BTC/USDT BUY reason=exploration_limit

# But normal trades continue:
INFO: ACTION_ROUTE: BUY → BUY (intent=normal, reason=open_long)
INFO: Trade executed with intent=NORMAL (bypasses exploration budget ✅)
```

## Acceptance Criteria ✅

### ✅ Logs Never Show "final_action SELL" with BUY Fills

**Before (WRONG):**
```
DECISION: final_action=SELL
ORDER: side=BUY, qty=0.01 BTC  # ❌ WRONG!
```

**After (CORRECT):**
```
DECISION: final_action=SELL, initial_action=SELL
ACTION_ROUTE: SELL → SKIP (intent=normal, reason=shorting_disabled)
SKIP BTC/USDT SELL reason=shorting_disabled  # ✅ CORRECT!
```

OR if closing long:
```
DECISION: final_action=SELL, initial_action=SELL
ACTION_ROUTE: SELL → SELL (intent=exit, reason=close_long)
ORDER: side=SELL, qty=0.01 BTC (closing long)  # ✅ CORRECT!
```

OR if shorting allowed:
```
DECISION: final_action=SELL, initial_action=SELL
ACTION_ROUTE: SELL → SELL (intent=normal, reason=open_short)
ORDER: side=SELL, qty=0.01 BTC (opening short)  # ✅ CORRECT!
```

### ✅ Normal Trades Go Through Even When Exploration Budget Depleted

**Scenario: Exploration budget = $300, used = $300**

**Exploration Trade:**
```
🔍 EXPLORATION: target_notional=$100.00
EXPLORATION budget exhausted for SOL/USDT (need $100.00)
SKIP EXPLORATION SOL/USDT BUY reason=exploration_limit  # ❌ Blocked
```

**Normal Trade (same cycle):**
```
POSITION_SIZE: BTC/USDT buy qty=0.012500 notional=$1,250.00 (order_intent=normal)
Trade executed with intent=NORMAL  # ✅ Goes through!
```

**Pilot Trade (same cycle):**
```
🚁 PILOT: target_notional=$400.00
Checking exploration budget for pilot trade: $400.00
SKIP PILOT ETH/USDT BUY reason=exploration_limit  # ❌ Blocked
```

**Result:** Normal trades bypass exploration limits ✅

## Order Intent Usage Summary

| Trade Type | Order Intent | Checks Exploration Budget? | Example |
|------------|--------------|---------------------------|---------|
| Normal qualified | `normal` | ❌ NO | score ≥ 0.65, RR ≥ 1.3 |
| Pilot (relaxed RR) | `pilot` | ✅ YES | score ≥ 0.55, RR ≥ 1.15 |
| Exploration | `explore` | ✅ YES | score ≥ 0.30, forced entry |
| Exit (manual/auto) | `exit` | ❌ NO | Closing positions |
| Risk mgmt (SL/TP) | `risk` | ❌ NO | Stop/TP updates |

## Files Modified

1. ✅ `/crypto_mvp/src/crypto_mvp/execution/execution_router.py` - **NEW**
   - Deterministic action→side mapping
   - Shorting constraint handling
   - Order intent classification

2. ✅ `/crypto_mvp/src/crypto_mvp/trading_system.py` - **UPDATED**
   - Integrated router in 3 paths: normal, pilot, exploration
   - Added shorting downgrade logic
   - Proper metadata tagging with order_intent
   - Exploration budget only for exploration/pilot trades

3. ✅ `/crypto_mvp/EXECUTION_ROUTER_IMPLEMENTATION.md` - **CREATED**
   - Comprehensive documentation

## Benefits

### 1. Deterministic Behavior
- `final_action=SELL` always maps correctly
- No more unexpected BUY fills on SELL signals
- Clear audit trail with routing reasons

### 2. Exploration Budget Isolation
- Normal trades **never** blocked by exploration limits
- Exploration budget reserved for experimental trades
- Pilot trades use exploration budget (lower quality signals)

### 3. Venue Constraint Compliance
- Shorting disabled → SELL signals properly handled
- Close longs allowed even when shorting disabled
- Prevents invalid orders to exchange

### 4. Clear Intent Tracking
- Every order tagged with `order_intent`
- Analytics can separate normal vs exploration performance
- Risk monitoring knows which trades to count

---

**Status:** ✅ Complete - Ready for testing  
**Date:** 2025-10-07  
**Implementation:** Execution router with deterministic mapping and exploration budget isolation


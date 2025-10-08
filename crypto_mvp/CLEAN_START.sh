#!/bin/bash
# Ultimate clean start script - ensures all fixes are loaded

echo "╔══════════════════════════════════════════════════════════════════════════╗"
echo "║                    🧹 CLEAN START - ALL FIXES APPLIED                    ║"
echo "╚══════════════════════════════════════════════════════════════════════════╝"
echo ""

cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"

# Step 1: Clear ALL Python cache
echo "🧹 Step 1: Clearing Python bytecode cache..."
find src -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find src -name "*.pyc" -delete 2>/dev/null
echo "✅ Python cache cleared"
echo ""

# Step 2: Clear database
echo "🧹 Step 2: Clearing old database..."
if [ -f trading_state.db ]; then
    rm -f trading_state.db
    echo "✅ Database cleared"
else
    echo "ℹ️  No old database found"
fi
echo ""

# Step 3: Archive old logs
echo "🧹 Step 3: Archiving old logs..."
if [ -f logs/crypto_mvp.log ]; then
    mkdir -p logs/archive
    mv logs/crypto_mvp.log "logs/archive/crypto_mvp_$(date +%Y%m%d_%H%M%S).log"
    echo "✅ Logs archived"
else
    echo "ℹ️  No old logs found"
fi
echo ""

# Step 4: Verify fixes
echo "🔍 Step 4: Verifying all fixes are in source code..."
python3 << 'PYEOF'
with open('src/crypto_mvp/state/store.py') as f:
    content = f.read()
    assert 'recalculated_equity = new_cash + positions_value' in content, "debit_cash fix missing!"
    assert content.count('recalculated_equity') >= 2, "credit_cash fix missing!"
    
with open('src/crypto_mvp/trading_system.py') as f:
    content = f.read()
    assert 'order_manager.set_state_store(self.state_store)' in content, "state_store setup missing!"
    assert 'state_store_cash = self.state_store.get_session_cash' in content, "cash sync missing!"
    
print("✅ All 4 critical fixes verified in source code!")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ Fix verification failed! Check source files!"
    exit 1
fi
echo ""

# Step 5: Start system
SESSION_ID="CLEAN-$(date +%Y%m%d-%H%M%S)"
echo "═══════════════════════════════════════════════════════════════════════════"
echo "🚀 Step 5: Starting trading system..."
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""
echo "📝 Session: $SESSION_ID"
echo "💰 Capital: $10,000"
echo ""
echo "🔍 WATCH FOR THESE IN LOGS:"
echo "   ✅ CRITICAL: State store set on order_manager"
echo "   🟡 SIMULATION_MODE_FILL"
echo "   💳 DEBIT_CASH: showing equity recalculation"
echo "   🔍 SAVE_PORTFOLIO_CHECK: showing cash sync"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

# Run the system
exec python -m crypto_mvp --session-id "$SESSION_ID" --capital 10000


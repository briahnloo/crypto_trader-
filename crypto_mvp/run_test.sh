#!/bin/bash
# Quick test script to verify equity calculation is fixed

cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"

echo "======================================================================"
echo "  🧪 TESTING EQUITY CALCULATION FIX"
echo "======================================================================"
echo ""

# Ensure clean state
echo "Ensuring clean state..."
rm -f trading_state.db trade_ledger.db crypto_trading.db 2>/dev/null
echo "✅ Databases cleared"
echo ""

# Run validation
echo "Running validation..."
python test_equity_fix.py
echo ""

# Run single cycle
echo "======================================================================"
echo "  🚀 RUNNING SINGLE TRADING CYCLE"
echo "======================================================================"
echo ""
echo "Watch for:"
echo "  ✅ Equity around \$9,999 (NOT \$10,100!)"
echo "  ✅ Cash around \$9,899 (NOT \$10,000!)"
echo ""

python -m crypto_mvp --once --capital 10000 --override-session-capital

echo ""
echo "======================================================================"
echo "  📊 CHECKING RESULTS"
echo "======================================================================"
echo ""

# Check database
if [ -f "trading_state.db" ]; then
    echo "Latest database record:"
    sqlite3 trading_state.db "SELECT cash_balance, total_equity FROM cash_equity ORDER BY id DESC LIMIT 1" | \
    while IFS='|' read cash equity; do
        echo "  Cash: \$$cash"
        echo "  Equity: \$$equity"
        echo ""
        
        # Validate
        if (( $(echo "$cash < 10000" | bc -l) )); then
            echo "  ✅ CORRECT: Cash decreased (was \$10,000)"
        else
            echo "  ❌ WRONG: Cash still \$10,000 (bug persists!)"
        fi
        
        if (( $(echo "$equity < 10100" | bc -l) )); then
            echo "  ✅ CORRECT: Equity realistic (not phantom)"
        else
            echo "  ❌ WRONG: Equity inflated (bug persists!)"
        fi
    done
else
    echo "⚠️  No database created (system may not have run)"
fi

echo ""
echo "======================================================================"


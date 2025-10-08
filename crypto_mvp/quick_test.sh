#!/bin/bash
# Quick test to verify equity fix

cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"

echo "Starting system for 90 seconds to get 1-2 trades..."
echo "Watch for VERSION_CHECK marker..."
echo ""

timeout 90 python -m crypto_mvp --capital 10000 2>&1 | tee test_output.log

echo ""
echo "========================================="
echo "Checking results..."
echo "========================================="

# Check for version marker
if grep -q "VERSION_CHECK: EQUITY FIX v2.0" test_output.log; then
    echo "✅ Correct code version loaded"
else
    echo "❌ Old code still running!"
fi

# Check for cash sync marker
if grep -q "SAVE_PORTFOLIO_CHECK" test_output.log; then
    echo "✅ Cash sync is happening"
else
    echo "⚠️  No cash sync found"
fi

# Run diagnostic
echo ""
python diagnose_db.py 2>/dev/null | tail -8


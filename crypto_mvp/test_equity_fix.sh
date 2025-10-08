#!/bin/bash
# Test script to verify the equity fix works

echo "╔══════════════════════════════════════════════════════════════════════════╗"
echo "║                    🧪 EQUITY FIX VERIFICATION TEST                       ║"
echo "╚══════════════════════════════════════════════════════════════════════════╝"
echo ""

# Clean old database
echo "🧹 Cleaning old database..."
rm -f trading_state.db
echo "✅ Database cleared"
echo ""

# Generate test session
SESSION_ID="TEST-$(date +%Y%m%d-%H%M%S)"
echo "📝 Test Session: $SESSION_ID"
echo "💰 Starting Capital: $10,000"
echo ""

echo "══════════════════════════════════════════════════════════════════════════"
echo "🚀 Starting trading system for 2 cycles..."
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

# Run for limited time
cd /Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto\ trader/crypto_mvp
timeout 150 python -m crypto_mvp --session-id "$SESSION_ID" --capital 10000 2>&1 | tee test_run.log &
PID=$!

# Wait for startup
sleep 20

# Give it time for 2 cycles
sleep 130

# Kill if still running
kill $PID 2>/dev/null

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "📊 VERIFICATION RESULTS:"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

# Run diagnostic
python diagnose_db.py

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "🔍 CHECKING FOR DIAGNOSTIC MARKERS IN LOGS:"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

echo "Looking for cash sync markers..."
grep "SAVE_PORTFOLIO_CHECK" test_run.log | tail -5

echo ""
echo "Looking for cash updates..."
grep "💰 CASH_UPDATE" test_run.log | tail -5

echo ""
echo "Looking for equity snapshots..."
grep "EQUITY_SNAPSHOT" test_run.log | tail -3

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "✅ TEST COMPLETE"
echo "══════════════════════════════════════════════════════════════════════════"


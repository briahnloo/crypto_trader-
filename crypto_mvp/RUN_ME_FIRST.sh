#!/bin/bash
# Quick validation and startup script for the fixed trading system

echo "======================================================================"
echo "  🧪 EQUITY FIX VALIDATION & STARTUP"
echo "======================================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "config/profit_optimized.yaml" ]; then
    echo "❌ Error: Please run this script from the crypto_mvp directory"
    exit 1
fi

echo "1. Running validation tests..."
echo "----------------------------------------------------------------------"
python test_equity_fix.py
echo ""

echo "2. Checking for old database files..."
echo "----------------------------------------------------------------------"
if [ -f "trading_state.db" ] || [ -f "trade_ledger.db" ]; then
    echo "⚠️  Old database files found!"
    echo "   These may contain orphaned positions from buggy sessions."
    echo ""
    read -p "   Delete them and start fresh? (y/n): " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        rm -f trading_state.db trade_ledger.db crypto_trading.db test_*.db
        echo "   ✅ Databases cleared!"
    else
        echo "   ⚠️  Keeping old databases (may cause phantom equity)"
    fi
else
    echo "✅ No old databases found - starting fresh!"
fi
echo ""

echo "3. Ready to start trading system!"
echo "----------------------------------------------------------------------"
echo ""
echo "Choose an option:"
echo ""
echo "  1) Single cycle test (recommended first time)"
echo "     python -m crypto_mvp --once --capital 10000 --override-session-capital"
echo ""
echo "  2) Continuous trading"
echo "     python -m crypto_mvp --capital 10000 --override-session-capital"
echo ""
echo "  3) Run validation only (don't start trading)"
echo ""
read -p "Enter choice (1/2/3): " choice

case $choice in
    1)
        echo ""
        echo "🚀 Starting single cycle test..."
        echo ""
        python -m crypto_mvp --once --capital 10000 --override-session-capital
        ;;
    2)
        echo ""
        echo "🚀 Starting continuous trading..."
        echo "   Press Ctrl+C to stop gracefully"
        echo ""
        python -m crypto_mvp --capital 10000 --override-session-capital
        ;;
    3)
        echo ""
        echo "✅ Validation complete. Run manually when ready:"
        echo "   python -m crypto_mvp --once --capital 10000 --override-session-capital"
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

echo ""
echo "======================================================================"
echo "  ✅ DONE"
echo "======================================================================"


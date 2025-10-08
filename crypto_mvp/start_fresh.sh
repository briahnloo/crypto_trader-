#!/bin/bash
# Start the trading system with a fresh session and clean state

echo "═══════════════════════════════════════════════════════════════════"
echo "🔄 Starting Fresh Trading System"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Generate fresh session ID
SESSION_ID="FRESH-$(date +%Y%m%d-%H%M%S)"
echo "📝 Session ID: $SESSION_ID"
echo "💰 Capital: $10,000"
echo ""

# Clean up old log to see only new entries
if [ -f logs/crypto_mvp.log ]; then
    echo "🧹 Archiving old log..."
    mv logs/crypto_mvp.log "logs/crypto_mvp_$(date +%Y%m%d_%H%M%S).log.bak"
fi

echo "══════════════════════════════════════════════════════════════════="
echo "✅ CRITICAL FIXES APPLIED:"
echo "   1. debit_cash() now recalculates equity = cash + positions"
echo "   2. credit_cash() now recalculates equity = cash + positions"
echo "   3. Position consolidation prevents duplicate counting"
echo "   4. Comprehensive diagnostic logging added"
echo "══════════════════════════════════════════════════════════════════="
echo ""
echo "🔍 WATCH FOR THESE MARKERS IN LOGS:"
echo "   🟡 = Simulation mode fill (order_manager path)"
echo "   💳 = Cash debit/credit with equity recalculation"
echo "   ✅ = Operation completed successfully"
echo ""
echo "══════════════════════════════════════════════════════════════════="
echo "🚀 Starting system..."
echo ""

# Start the system
cd /Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto\ trader/crypto_mvp
python -m crypto_mvp --session-id "$SESSION_ID" --capital 10000


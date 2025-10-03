#!/bin/bash

# Crypto Trading System Control Script
# This script helps you monitor and control the trading system

PROJECT_DIR="/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"

case "$1" in
    "start")
        echo "🚀 Starting Crypto Trading System..."
        cd "$PROJECT_DIR"
        source venv/bin/activate
        python -m crypto_mvp --cycle-interval 60 --capital 10000 &
        echo "✅ Trading system started in background"
        echo "📊 Process ID: $!"
        ;;
    "status")
        echo "📊 Checking trading system status..."
        if pgrep -f "python -m crypto_mvp" > /dev/null; then
            echo "✅ Trading system is RUNNING"
            echo "📈 Process details:"
            ps aux | grep "python -m crypto_mvp" | grep -v grep
        else
            echo "❌ Trading system is NOT running"
        fi
        ;;
    "stop")
        echo "⏹️  Stopping trading system..."
        pkill -f "python -m crypto_mvp"
        echo "✅ Trading system stopped"
        ;;
    "logs")
        echo "📋 Recent trading logs:"
        if [ -f "$PROJECT_DIR/logs/crypto_mvp.log" ]; then
            tail -20 "$PROJECT_DIR/logs/crypto_mvp.log"
        else
            echo "No log file found"
        fi
        ;;
    "restart")
        echo "🔄 Restarting trading system..."
        pkill -f "python -m crypto_mvp"
        sleep 2
        cd "$PROJECT_DIR"
        source venv/bin/activate
        python -m crypto_mvp --cycle-interval 60 --capital 10000 &
        echo "✅ Trading system restarted"
        ;;
    *)
        echo "🎯 Crypto Trading System Control"
        echo "Usage: $0 {start|stop|status|logs|restart}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the trading system"
        echo "  stop    - Stop the trading system"
        echo "  status  - Check if system is running"
        echo "  logs    - Show recent logs"
        echo "  restart - Restart the trading system"
        ;;
esac

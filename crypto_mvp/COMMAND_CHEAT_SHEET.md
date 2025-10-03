# 🚀 Crypto Trading System - Command Cheat Sheet

## 🔧 **Setup & Installation**

### **Initial Setup (One-time only):**
```bash
# 1. Navigate to project directory
cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"

# 2. Activate virtual environment
source venv/bin/activate

# 3. Install package in development mode
pip install -e .
```

### **Daily Startup:**
```bash
# Navigate to project and activate environment
cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"
source venv/bin/activate
```

---

## 🚀 **Running the Trading System**

### **Basic Commands:**

| Command | Description | Use Case |
|---------|-------------|----------|
| `python -m crypto_mvp` | Run continuous trading (paper mode) | Live trading simulation |
| `python -m crypto_mvp --once` | Run single cycle and exit | Quick testing |
| `python -m crypto_mvp --once --capital 10000` | Single cycle with $10k capital | Test with specific capital |
| `python -m crypto_mvp --once --symbols BTC/USDT ETH/USDT` | Single cycle with specific symbols | Test specific cryptocurrencies |

### **Strategy-Specific Commands:**

| Command | Description | Best For |
|---------|-------------|----------|
| `python -m crypto_mvp --once --strategy momentum` | Momentum-based trading | Trending markets |
| `python -m crypto_mvp --once --strategy breakout` | Breakout strategy | Volatile markets |
| `python -m crypto_mvp --once --strategy mean_reversion` | Mean reversion | Range-bound markets |
| `python -m crypto_mvp --once --strategy arbitrage` | Arbitrage opportunities | Cross-exchange trading |
| `python -m crypto_mvp --once --strategy sentiment` | Sentiment-driven trading | News-driven markets |
| `python -m crypto_mvp --once --strategy composite` | Multi-strategy approach | Balanced approach |

### **Advanced Commands:**

| Command | Description | Use Case |
|---------|-------------|----------|
| `python -m crypto_mvp --config config/profit_optimized.yaml --once` | Custom config file | Different trading parameters |
| `python -m crypto_mvp --live --once --capital 1000` | **LIVE TRADING** (REAL MONEY) | Actual trading with real funds |
| `python -m crypto_mvp --dry-run --once` | Force simulation mode | Safe testing even with live flag |
| `python -m crypto_mvp --cycle-interval 60 --once` | Custom cycle timing | Different update frequencies |
| `python -m crypto_mvp --max-cycles 10` | Limited number of cycles | Controlled testing |

---

## 🛠️ **Development Commands (Makefile)**

### **Quick Development Workflow:**
```bash
# Install dependencies
make install

# Run the system
make run

# Run tests
make test

# Run tests with coverage
make test-cov

# Format code
make fmt

# Lint code
make lint

# Type checking
make typecheck

# Clean up
make clean
```

### **Full Development Setup:**
```bash
# Complete development environment
make dev-setup

# Run all CI checks
make ci
```

---

## 🐳 **Docker Commands**

```bash
# Build Docker image
make docker-build

# Run in Docker (single cycle)
make docker-run

# Development with Docker
make docker-dev

# Run tests in Docker
make docker-test
```

---

## 📊 **Available Trading Symbols**

### **Major Cryptocurrencies:**
- `BTC/USDT` - Bitcoin
- `ETH/USDT` - Ethereum
- `ADA/USDT` - Cardano
- `DOT/USDT` - Polkadot
- `SOL/USDT` - Solana

### **Example Multi-Symbol Commands:**
```bash
# Trade top 3 cryptocurrencies
python -m crypto_mvp --once --symbols BTC/USDT ETH/USDT ADA/USDT

# Trade with specific capital
python -m crypto_mvp --once --symbols BTC/USDT ETH/USDT --capital 50000
```

---

## ⚡ **Quick Start Examples**

### **1. Test Run (Recommended First):**
```bash
cd "/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp"
source venv/bin/activate
python -m crypto_mvp --once --capital 10000
```

### **2. Test Different Strategies:**
```bash
# Test momentum strategy
python -m crypto_mvp --once --strategy momentum --capital 10000

# Test sentiment strategy
python -m crypto_mvp --once --strategy sentiment --capital 10000
```

### **3. Test with Specific Symbols:**
```bash
# Test with Bitcoin and Ethereum only
python -m crypto_mvp --once --symbols BTC/USDT ETH/USDT --capital 10000
```

### **4. Continuous Paper Trading:**
```bash
# Run continuous simulation (press Ctrl+C to stop)
python -m crypto_mvp --capital 10000

# Run with custom cycle interval (60 seconds between cycles)
python -m crypto_mvp --cycle-interval 60 --capital 10000

# Run with very short intervals for testing (30 seconds)
python -m crypto_mvp --cycle-interval 30 --capital 10000

# Run with limited cycles for testing
python -m crypto_mvp --cycle-interval 60 --max-cycles 5 --capital 10000
```

---

## 🔍 **Troubleshooting**

### **Common Issues & Solutions:**

| Problem | Solution |
|---------|----------|
| `No module named crypto_mvp` | Run `pip install -e .` in project directory |
| `source: no such file or directory: venv/bin/activate` | Make sure you're in the correct directory |
| `can't find '__main__' module` | Install package with `pip install -e .` |
| Permission errors | Check file permissions and virtual environment |
| **System only runs one cycle then stops** | **FIXED**: Added `cycle_interval` to config. Use `--cycle-interval 60` for 1-minute cycles |
| **System waits too long between cycles** | Use `--cycle-interval 30` for 30-second intervals |

### **Verification Commands:**
```bash
# Check if package is installed
pip list | grep crypto

# Check current directory
pwd

# Check virtual environment
which python

# Test import
python -c "import crypto_mvp; print('Package installed successfully!')"
```

---

## 🚨 **Safety Notes**

### **⚠️ LIVE TRADING WARNINGS:**
- **NEVER** use `--live` flag without understanding the risks
- Always test with `--once` and `--dry-run` first
- Start with small amounts in live mode
- The system will ask for confirmation before live trading

### **🛡️ Safe Testing:**
```bash
# Always start with these safe commands:
python -m crypto_mvp --once --dry-run --capital 1000
python -m crypto_mvp --once --capital 1000
```

---

## 📈 **Understanding Output**

### **Key Metrics to Watch:**
- **Total Equity**: Your current portfolio value
- **P&L**: Profit/Loss for the cycle
- **Trades Executed**: Number of actual trades
- **Signals Generated**: Trading opportunities identified
- **Risk Score**: Current risk level (lower is better)

### **Performance Indicators:**
- **Win Rate**: Percentage of profitable trades
- **Sharpe Ratio**: Risk-adjusted returns (higher is better)
- **Max Drawdown**: Largest peak-to-trough decline
- **Profit Factor**: Gross profit / Gross loss

---

## 🎯 **Pro Tips**

1. **Start Small**: Always test with small amounts first
2. **Use --once**: Perfect for testing and learning
3. **Monitor Logs**: Check `logs/` directory for detailed information
4. **Paper Trading**: Use simulation mode to understand the system
5. **Strategy Testing**: Try different strategies to see what works best
6. **Risk Management**: Never risk more than you can afford to lose

---

## 📞 **Need Help?**

If you encounter issues:
1. Check this cheat sheet first
2. Look at the logs in the `logs/` directory
3. Try the troubleshooting commands above
4. Make sure you're in the correct directory and virtual environment

**Happy Trading! 🚀💰**

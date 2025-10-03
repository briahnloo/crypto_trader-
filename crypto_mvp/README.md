# Crypto MVP 🚀

A comprehensive cryptocurrency trading MVP with multiple strategies, data sources, and risk management capabilities.

## 🎯 Quick Start (Paper Mode in 3 Commands)

Get up and running in paper/simulation mode in under 5 minutes:

```bash
# 1. Clone and setup
git clone <repository-url> && cd crypto_mvp && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# 2. Run single cycle in paper mode
python -m crypto_mvp --once

# 3. View results
ls logs/ && cat logs/crypto_mvp.log | tail -20
```

**Expected Output:**
```
🚀 Crypto MVP - Profit-Maximizing Trading System
============================================================
📁 Config: config/profit_optimized.yaml
💰 Mode: PAPER/SIMULATION
🔄 Cycles: Single cycle
============================================================

🔄 TRADING CYCLE: cycle_1
================================================================================
📅 Time: 2025-10-02T19:40:31.203146
💰 Symbol: PORTFOLIO
🎯 Strategy: composite

💎 EQUITY:
   📈 Current: $100,000.00
   📊 Previous: $100,000.00
   💰 P&L: $0.00 (+0.00%)

📋 POSITIONS:
   🔢 Count: 0
   💵 Total Value: $0.00

🧠 DECISIONS:
   🔢 Count: 4
   🟡 Confidence: 70.0%
   🟡 Risk Score: 30.0%
   📝 signals_generated: 5
   📝 trades_executed: 0

✅ Single cycle completed successfully!
```

## 🚨 Live Trading Checklist

**⚠️ CRITICAL: Only proceed after completing ALL safety checks**

### Pre-Trading Safety Checks

- [ ] **API Keys Configured**: All exchange API keys are set in `.env`
- [ ] **Sandbox Mode OFF**: `sandbox: false` in config for live trading
- [ ] **Dry Run OFF**: `dry_run: false` in config for live trading
- [ ] **Small Capital**: Start with minimal capital (e.g., $100-1000)
- [ ] **Testnet Verified**: Successfully tested on testnet/sandbox first
- [ ] **Backup Strategy**: Have manual trading backup plan
- [ ] **Risk Limits Set**: Position sizes and risk limits configured
- [ ] **Monitoring Setup**: Log monitoring and alerting configured

### Live Trading Commands

```bash
# 1. Final safety check
python -m crypto_mvp --config config/profit_optimized.yaml --dry-run --once

# 2. Start live trading (requires CONFIRM prompt)
python -m crypto_mvp --config config/profit_optimized.yaml --live

# 3. Monitor logs
tail -f logs/crypto_mvp.log
```

### Safety Confirmations

The system will prompt for explicit confirmation before live trading:

```
⚠️  LIVE TRADING MODE ENABLED ⚠️
This will execute REAL trades with REAL money.

Are you sure you want to proceed? Type 'CONFIRM' to continue: 
```

## 🛡️ Safety Rails Summary

### Built-in Protections

#### 1. **Paper Mode Default**
- All trading starts in simulation mode
- No real money at risk during development/testing
- Mock data and simulated fills

#### 2. **Explicit Live Mode Confirmation**
- Requires `--live` flag AND confirmation prompt
- Cannot accidentally enable live trading
- Clear warnings about real money risk

#### 3. **API Key Validation**
- Validates all required API keys before live trading
- Prevents execution with missing credentials
- Clear error messages for missing keys

#### 4. **Dry Run Override**
- `--dry-run` flag prevents live orders even in live mode
- Useful for staging and final testing
- Overrides all live trading flags

#### 5. **Risk Management Guards**
- Position size limits (max 25% per position)
- Portfolio risk budget (max 3% total risk)
- Correlation constraints (max 60% correlation)
- Sector caps (layer1: 40%, defi: 30%, meme: 20%)
- Daily loss limits (3% max daily loss)

#### 6. **Cost Simulation**
- Arbitrage opportunities filtered by net profit after all costs
- Realistic fee simulation (trading, transfer, slippage)
- Only profitable opportunities after costs are executed

#### 7. **Configuration Validation**
- Pydantic schema validation on startup
- Range checks for risk parameters
- Helpful error messages for invalid configs

#### 8. **State Persistence**
- Portfolio state saved to SQLite database
- Survives system restarts
- Prevents data loss

### Safety Configuration

```yaml
# config/profit_optimized.yaml
trading:
  live_mode: false        # Must be explicitly enabled
  dry_run: true          # Prevents live orders
  sandbox: true          # Uses testnet/sandbox

risk:
  max_drawdown: 0.10     # 10% maximum drawdown
  stop_loss: 0.02        # 2% stop loss
  position_sizing:
    risk_per_trade: 0.01 # 1% risk per trade
    max_position_size: 0.1 # 10% max position size
  daily_loss_limit: 0.03 # 3% daily loss limit

portfolio:
  max_positions: 5       # Maximum 5 positions
  max_correlation: 0.6   # 60% max correlation
  max_portfolio_risk: 0.03 # 3% max portfolio risk
```

## 🔧 Troubleshooting

### Common Issues and Solutions

#### 1. **Rate Limit Errors**

**Symptoms:**
```
Rate limit exceeded. Please try again later.
HTTP 429: Too Many Requests
```

**Solutions:**
```bash
# Check rate limit configuration
grep -A 5 "rate_limit" config/profit_optimized.yaml

# Increase delays between requests
# Edit config/profit_optimized.yaml
exchanges:
  binance:
    rate_limit: 20  # Increase from 10 to 20
    timeout: 60     # Increase timeout

# Use offline mode for testing
OFFLINE=1 python -m crypto_mvp --once
```

#### 2. **Missing Data Errors**

**Symptoms:**
```
No price data available for BTC/USDT
Failed to get ticker for ETH/USDT
```

**Solutions:**
```bash
# Check API keys
grep -E "(api_key|secret)" .env

# Test individual connectors
python -c "
from src.crypto_mvp.data.connectors.binance import BinanceConnector
connector = BinanceConnector()
connector.initialize()
print(connector.get_ticker('BTC/USDT'))
"

# Use offline mode with fixtures
OFFLINE=1 python -m crypto_mvp --once
```

#### 3. **Schema Validation Errors**

**Symptoms:**
```
Configuration validation failed: • risk -> position_sizing -> risk_per_trade: Input should be less than or equal to 0.1
```

**Solutions:**
```bash
# Validate configuration
python -c "
from src.crypto_mvp.core.config_manager import ConfigManager
config = ConfigManager('config/profit_optimized.yaml')
print('Config valid:', config.is_validated())
"

# Fix invalid values in config/profit_optimized.yaml
# Example: Change risk_per_trade from 0.15 to 0.05
```

#### 4. **Import/Module Errors**

**Symptoms:**
```
ModuleNotFoundError: No module named 'crypto_mvp'
ImportError: cannot import name 'ConfigManager'
```

**Solutions:**
```bash
# Ensure you're in the correct directory
pwd  # Should show .../crypto_mvp

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .

# Check Python path
python -c "import sys; print(sys.path)"
```

#### 5. **Database/State Errors**

**Symptoms:**
```
sqlite3.OperationalError: database is locked
Failed to save portfolio state
```

**Solutions:**
```bash
# Check database file permissions
ls -la trading_state.db

# Remove locked database (will reset state)
rm trading_state.db

# Check for multiple running instances
ps aux | grep crypto_mvp

# Kill any stuck processes
pkill -f crypto_mvp
```

#### 6. **Permission Errors**

**Symptoms:**
```
PermissionError: [Errno 13] Permission denied: 'logs/crypto_mvp.log'
```

**Solutions:**
```bash
# Create logs directory
mkdir -p logs

# Fix permissions
chmod 755 logs/
chmod 644 logs/*.log

# Run with proper permissions
sudo chown -R $USER:$USER .
```

#### 7. **Memory/Performance Issues**

**Symptoms:**
```
MemoryError: Unable to allocate array
System is running slowly
```

**Solutions:**
```bash
# Reduce data limits in config
trading:
  ohlcv_limit: 50    # Reduce from 100
  max_open_trades: 3 # Reduce from 5

# Use smaller timeframes
trading:
  timeframe: "5m"    # Use 5-minute instead of 1-hour

# Monitor system resources
htop
df -h
```

### Debug Mode

Enable detailed logging for troubleshooting:

```bash
# Set debug logging level
export LOG_LEVEL=DEBUG

# Run with verbose output
python -m crypto_mvp --once --verbose

# Check specific module logs
grep "ERROR" logs/crypto_mvp.log
grep "WARNING" logs/crypto_mvp.log
```

### Getting Help

1. **Check Logs**: Always check `logs/crypto_mvp.log` first
2. **Run Tests**: `pytest tests/test_smoke.py -v` to verify setup
3. **Validate Config**: Use config validation tools
4. **Use Offline Mode**: `OFFLINE=1 python -m crypto_mvp --once` for testing
5. **Check Issues**: Look for similar issues in the repository

## 📊 Features

- **Multiple Trading Strategies**: Momentum, breakout, mean reversion, arbitrage, sentiment-based, and more
- **Rich Data Sources**: Coinbase, Binance, CoinGecko, Fear & Greed Index, Whale Alert, social sentiment
- **Advanced Analytics**: Profit optimization, risk management, portfolio tracking
- **Real-time Execution**: Multi-strategy execution with order management
- **Comprehensive Monitoring**: CLI interface, logging, and analytics dashboard

## 🏗️ Project Structure

```
crypto_mvp/
├── config/                 # Configuration files
│   └── profit_optimized.yaml  # Main trading configuration
├── src/crypto_mvp/        # Main source code
│   ├── core/              # Core utilities (config, logging)
│   ├── data/              # Data connectors and engine
│   ├── indicators/        # Technical indicators
│   ├── strategies/        # Trading strategies
│   ├── risk/              # Risk management
│   ├── execution/         # Order execution
│   ├── analytics/         # Analytics and reporting
│   ├── cli/               # Command-line interface
│   └── state/             # State persistence
├── tests/                 # Test suite
├── fixtures/              # Sample data for offline testing
├── logs/                  # Log files
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project configuration
└── README.md             # This file
```

## 🛠️ Development

### Development Environment Setup

#### Option 1: Local Development

```bash
# Clone the repository
git clone <repository-url>
cd crypto_mvp

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install pre-commit hooks
pre-commit install

# Run tests to verify setup
pytest
```

#### Option 2: DevContainer (Recommended)

1. Open the project in VS Code or Cursor
2. Install the "Dev Containers" extension
3. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
4. Select "Dev Containers: Reopen in Container"
5. Wait for the container to build and start

#### Option 3: Docker Development

```bash
# Build development image
docker-compose build crypto-mvp-dev

# Start development container
docker-compose up -d crypto-mvp-dev

# Access the container
docker-compose exec crypto-mvp-dev bash
```

### Development Loop

#### 1. Code Quality & Pre-commit Hooks

```bash
# Install pre-commit hooks (first time only)
pre-commit install

# Run all pre-commit hooks on staged files
pre-commit run

# Run all pre-commit hooks on all files
pre-commit run --all-files

# Update pre-commit hooks
pre-commit autoupdate
```

#### 2. Code Formatting & Linting

```bash
# Format code with Black
black src/ tests/

# Sort imports with isort
isort src/ tests/

# Lint with Ruff
ruff check src/ tests/
ruff check src/ tests/ --fix  # Auto-fix issues

# Type checking with mypy
mypy src/

# Run all quality checks
make fmt    # Format code
make lint   # Lint code
make typecheck  # Type checking
```

#### 3. Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/crypto_mvp --cov-report=html

# Run specific test categories
pytest -m "not slow"
pytest -m integration

# Run tests in watch mode (requires pytest-watch)
ptw

# Run smoke tests only
pytest tests/test_smoke.py -v
```

#### 4. Development Workflow

```bash
# 1. Make changes to code
# 2. Stage changes
git add .

# 3. Pre-commit hooks run automatically
# 4. If hooks fail, fix issues and re-stage
git add .

# 5. Commit changes
git commit -m "feat: add new feature"

# 6. Run full test suite
pytest

# 7. Push changes
git push origin feature-branch
```

### Code Quality Standards

The project enforces strict code quality standards through pre-commit hooks:

- **Black**: Code formatting (88 character line length)
- **isort**: Import sorting (Black-compatible profile)
- **Ruff**: Fast Python linting and formatting
- **mypy**: Static type checking
- **bandit**: Security vulnerability scanning
- **pre-commit-hooks**: Basic file checks (trailing whitespace, end-of-file, etc.)

### Testing Strategy

```bash
# Unit tests (fast)
pytest tests/unit/

# Integration tests (slower)
pytest tests/integration/

# Smoke tests (verification)
pytest tests/test_smoke.py

# All tests with coverage
pytest --cov=src/crypto_mvp --cov-report=html --cov-report=term
```

### Docker Development

```bash
# Build and test Docker image
docker build -t crypto-mvp .

# Run containerized application
docker run --rm crypto-mvp --once

# Development with Docker Compose
docker-compose up -d crypto-mvp-dev
docker-compose exec crypto-mvp-dev bash

# Run tests in container
docker-compose exec crypto-mvp-dev pytest
```

## ⚙️ Configuration

The application uses YAML configuration files. See `config/profit_optimized.yaml` for the default configuration.

Key configuration areas:
- **Exchanges**: API keys and trading parameters
- **Strategies**: Strategy-specific parameters
- **Risk Management**: Position sizing and risk limits
- **Data Sources**: API endpoints and credentials

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run quality checks
6. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## ⚠️ Disclaimer

This software is for educational and research purposes only. Trading cryptocurrencies involves substantial risk of loss. Use at your own risk.

**Never trade with money you cannot afford to lose.**
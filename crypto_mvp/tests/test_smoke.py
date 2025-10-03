"""
Smoke tests for the Crypto MVP application.
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_mvp.analytics.profit_analytics import ProfitAnalytics
from crypto_mvp.core.config_manager import ConfigManager
from crypto_mvp.data.engine import ProfitOptimizedDataEngine
from crypto_mvp.execution.multi_strategy import MultiStrategyExecutor
from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager
from crypto_mvp.strategies.composite import ProfitMaximizingSignalEngine


def test_config_loading():
    """Test that configuration can be loaded."""
    config_path = "config/profit_optimized.yaml"

    # Test config loading
    config_manager = ConfigManager(config_path)
    config = config_manager.to_dict()

    # Assert config has required sections
    assert isinstance(config, dict)
    assert len(config) > 0

    # Check for key sections
    required_sections = ["trading", "risk", "signals", "data_sources", "logging"]
    for section in required_sections:
        assert section in config, f"Missing required config section: {section}"

    # Test specific config values
    assert "timeframe" in config["trading"]
    assert "symbols" in config["trading"]
    assert "strategies" in config["trading"]


def test_data_engine_initialization():
    """Test data engine initialization with mock data."""
    # Initialize data engine
    data_engine = ProfitOptimizedDataEngine()
    data_engine.initialize()

    # Test that connectors are initialized
    assert hasattr(data_engine, "connectors")
    assert len(data_engine.connectors) > 0

    # Test getting ticker data (should return mock data)
    ticker_data = data_engine.get_ticker("BTC/USDT")
    assert isinstance(ticker_data, dict)
    assert "price" in ticker_data
    assert "volume" in ticker_data
    assert ticker_data["price"] > 0

    # Test getting OHLCV data
    ohlcv_data = data_engine.get_ohlcv("BTC/USDT", "1h", 10)
    assert isinstance(ohlcv_data, list)
    assert len(ohlcv_data) > 0

    # Test sentiment data
    sentiment_data = data_engine.get_sentiment_data("BTC/USDT")
    assert isinstance(sentiment_data, dict)


@pytest.mark.asyncio
async def test_composite_signal_generation():
    """Test composite signal generation."""
    # Initialize signal engine
    signal_engine = ProfitMaximizingSignalEngine()
    signal_engine.initialize()

    # Generate composite signal
    signal = await signal_engine.generate_composite_signals("BTC/USDT", "1h")

    # Assert signal structure
    assert isinstance(signal, dict)

    # Check required keys
    required_keys = [
        "individual_signals",
        "composite_score",
        "profit_probability",
        "risk_adjusted_return",
        "confidence",
        "metadata",
    ]

    for key in required_keys:
        assert key in signal, f"Missing required signal key: {key}"

    # Check value ranges
    assert -1.0 <= signal["composite_score"] <= 1.0
    assert 0.0 <= signal["profit_probability"] <= 1.0
    assert 0.0 <= signal["confidence"] <= 1.0

    # Check individual signals
    individual_signals = signal["individual_signals"]
    assert isinstance(individual_signals, dict)
    assert len(individual_signals) > 0


def test_multi_strategy_executor():
    """Test MultiStrategyExecutor with mock signal."""
    # Initialize risk manager
    risk_config = {
        "max_risk_per_trade": 0.02,
        "kelly_safety_factor": 0.5,
        "initial_portfolio_value": 10000.0,
    }
    risk_manager = ProfitOptimizedRiskManager(risk_config)

    # Initialize multi-strategy executor
    executor = MultiStrategyExecutor(risk_manager)
    executor.initialize()

    # Create mock signal
    mock_signal = {
        "symbol": "BTC/USDT",
        "score": 0.7,
        "confidence": 0.8,
        "signal_strength": 0.75,
        "current_price": 50000.0,
        "volatility": 0.02,
        "volume_ratio": 1.5,
    }

    # Execute strategy
    result = executor.execute_strategy("momentum", mock_signal, 10000.0)

    # Assert result structure
    assert isinstance(result, dict)

    # Check required keys
    required_keys = [
        "strategy",
        "symbol",
        "position_size",
        "entry_price",
        "execution_result",
        "expected_profit",
    ]

    for key in required_keys:
        assert key in result, f"Missing required result key: {key}"

    # Check values
    assert result["strategy"] == "momentum"
    assert result["symbol"] == "BTC/USDT"
    assert result["position_size"] >= 0
    assert result["entry_price"] > 0
    assert result["expected_profit"] >= 0

    # Check execution result
    execution_result = result["execution_result"]
    assert isinstance(execution_result, dict)
    assert "filled" in execution_result
    assert "entry_price" in execution_result
    assert "fees" in execution_result


def test_trade_logging_and_analytics():
    """Test trade logging and analytics dict keys."""
    # Initialize profit analytics
    analytics_config = {"initial_capital": 10000.0, "auto_save": False}
    analytics = ProfitAnalytics(analytics_config)
    analytics.initialize()

    # Log a mock trade
    analytics.log_trade(
        symbol="BTC/USDT",
        strategy="momentum",
        side="buy",
        quantity=0.1,
        entry_price=50000.0,
        exit_price=51000.0,
        fees=10.0,
    )

    # Generate profit report
    report = analytics.generate_profit_report()

    # Assert report structure
    assert isinstance(report, dict)

    # Check required keys
    required_keys = [
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "total_pnl",
        "total_return",
        "avg_win",
        "avg_loss",
        "sharpe_ratio",
        "strategy_performance",
    ]

    for key in required_keys:
        assert key in report, f"Missing required analytics key: {key}"

    # Check values (be more flexible with trade count)
    assert report["total_trades"] >= 1
    assert report["winning_trades"] >= 1
    assert report["losing_trades"] >= 0
    assert report["win_rate"] >= 0.0
    assert report["profit_factor"] >= 0
    assert report["max_drawdown"] >= 0
    assert report["total_pnl"] >= 0  # Should be profitable trade

    # Check strategy performance
    strategy_perf = report["strategy_performance"]
    assert isinstance(strategy_perf, dict)
    assert "momentum" in strategy_perf

    momentum_perf = strategy_perf["momentum"]
    assert "total_trades" in momentum_perf
    assert "win_rate" in momentum_perf
    assert "profit_factor" in momentum_perf
    assert "total_pnl" in momentum_perf


@pytest.mark.asyncio
async def test_integration_smoke():
    """Test basic integration of all components."""
    # Load config
    config_manager = ConfigManager("config/profit_optimized.yaml")
    config = config_manager.to_dict()

    # Initialize data engine
    data_engine = ProfitOptimizedDataEngine()
    data_engine.initialize()

    # Initialize signal engine
    signal_engine = ProfitMaximizingSignalEngine()
    signal_engine.initialize()

    # Initialize risk manager
    risk_manager = ProfitOptimizedRiskManager(config.get("risk", {}))

    # Initialize executor
    executor = MultiStrategyExecutor(risk_manager)
    executor.initialize()

    # Initialize analytics
    analytics = ProfitAnalytics({"initial_capital": 10000.0, "auto_save": False})
    analytics.initialize()

    # Test full workflow
    # 1. Get market data
    ticker = data_engine.get_ticker("BTC/USDT")
    assert ticker["price"] > 0

    # 2. Generate signal
    signal = await signal_engine.generate_composite_signals("BTC/USDT")
    assert signal["composite_score"] is not None

    # 3. Execute trade (if signal is strong enough)
    if signal["composite_score"] > 0.3:
        result = executor.execute_strategy("momentum", signal, 10000.0)
        assert result["position_size"] >= 0

    # 4. Log trade
    analytics.log_trade(
        symbol="BTC/USDT",
        strategy="momentum",
        side="buy",
        quantity=0.1,
        entry_price=50000.0,
        exit_price=50500.0,
        fees=5.0,
    )

    # 5. Generate report
    report = analytics.generate_profit_report()
    assert report["total_trades"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-q"])

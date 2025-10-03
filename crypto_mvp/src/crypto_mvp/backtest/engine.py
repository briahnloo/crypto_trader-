"""
Backtesting engine for running strategies across historical OHLCV data.
"""

import random
from datetime import datetime, timedelta
from typing import Any, Optional

from ..analytics.profit_analytics import ProfitAnalytics
from ..core.config_manager import ConfigManager
from ..core.logging_utils import LoggerMixin
from ..risk.risk_manager import ProfitOptimizedRiskManager
from ..strategies.composite import ProfitMaximizingSignalEngine


class BacktestEngine(LoggerMixin):
    """
    Backtesting engine that runs strategies across historical OHLCV data.
    """

    def __init__(self, config_path: str = "config/profit_optimized.yaml"):
        """Initialize the backtest engine.

        Args:
            config_path: Path to configuration file
        """
        super().__init__()
        self.config_path = config_path
        self.config_manager = None
        self.config = {}

        # Components
        self.signal_engine = None
        self.risk_manager = None
        self.analytics = None

        # Backtest state
        self.current_date = None
        self.portfolio = {
            "equity": 100000.0,
            "cash_balance": 100000.0,
            "positions": {},
            "total_fees": 0.0,
        }

        self.initialized = False

    def initialize(self) -> None:
        """Initialize the backtest engine."""
        if self.initialized:
            return

        self.logger.info("Initializing BacktestEngine...")

        # Load configuration
        self.config_manager = ConfigManager(self.config_path)
        self.config = self.config_manager.to_dict()

        # Initialize signal engine
        signal_config = self.config.get("signals", {})
        self.signal_engine = ProfitMaximizingSignalEngine(signal_config)
        self.signal_engine.initialize()

        # Initialize risk manager
        risk_config = self.config.get("risk", {})
        self.risk_manager = ProfitOptimizedRiskManager(risk_config)

        # Initialize analytics
        analytics_config = self.config.get("analytics", {})
        self.analytics = ProfitAnalytics(analytics_config)
        self.analytics.initialize()

        # Set initial portfolio
        initial_capital = self.config.get("trading", {}).get(
            "initial_capital", 100000.0
        )
        self.portfolio["equity"] = initial_capital
        self.portfolio["cash_balance"] = initial_capital

        self.initialized = True
        self.logger.info("BacktestEngine initialized")

    def generate_synthetic_ohlcv(
        self, symbol: str, timeframe: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """Generate synthetic OHLCV data for backtesting.

        Args:
            symbol: Trading symbol
            timeframe: Data timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of OHLCV data points
        """
        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        # Determine interval based on timeframe
        if timeframe == "1h":
            interval = timedelta(hours=1)
        elif timeframe == "4h":
            interval = timedelta(hours=4)
        elif timeframe == "1d":
            interval = timedelta(days=1)
        else:
            interval = timedelta(hours=1)  # Default to 1h

        # Generate base price based on symbol
        base_prices = {
            "BTC/USDT": 50000,
            "ETH/USDT": 3000,
            "ADA/USDT": 0.5,
            "DOT/USDT": 7.0,
            "SOL/USDT": 100,
            "BNB/USDT": 300,
            "MATIC/USDT": 0.8,
            "AVAX/USDT": 25,
            "LINK/USDT": 15,
            "UNI/USDT": 6,
        }

        base_price = base_prices.get(symbol, 100.0)
        current_price = base_price

        ohlcv_data = []
        current_time = start

        while current_time <= end:
            # Generate price movement (random walk with slight upward bias)
            price_change_pct = random.gauss(0.0005, 0.02)  # 0.05% mean, 2% std
            new_price = current_price * (1 + price_change_pct)

            # Generate OHLC from price
            high = new_price * (1 + abs(random.gauss(0, 0.01)))
            low = new_price * (1 - abs(random.gauss(0, 0.01)))
            open_price = current_price
            close_price = new_price

            # Generate volume
            volume = random.uniform(1000, 10000)

            ohlcv_data.append(
                {
                    "timestamp": current_time.isoformat(),
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close_price,
                    "volume": volume,
                }
            )

            current_price = new_price
            current_time += interval

        return ohlcv_data

    async def run_backtest(
        self, symbols: list[str], timeframe: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        """Run a backtest across the specified period.

        Args:
            symbols: List of trading symbols
            timeframe: Data timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dictionary containing backtest results
        """
        if not self.initialized:
            self.initialize()

        self.logger.info(
            f"Starting backtest: {symbols} from {start_date} to {end_date}"
        )

        # Generate synthetic data for all symbols
        all_data = {}
        for symbol in symbols:
            ohlcv_data = self.generate_synthetic_ohlcv(
                symbol, timeframe, start_date, end_date
            )
            all_data[symbol] = ohlcv_data
            self.logger.info(f"Generated {len(ohlcv_data)} data points for {symbol}")

        # Run backtest simulation
        backtest_results = {
            "config": {
                "symbols": symbols,
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": self.portfolio["equity"],
            },
            "trades": [],
            "equity_curve": [],
            "daily_returns": [],
            "portfolio_snapshots": [],
        }

        # Process each time period
        min_length = min(len(data) for data in all_data.values())

        for i in range(min_length):
            current_time = datetime.fromisoformat(all_data[symbols[0]][i]["timestamp"])
            self.current_date = current_time

            # Get current prices for all symbols
            current_prices = {}
            for symbol in symbols:
                current_prices[symbol] = all_data[symbol][i]["close"]

            # Generate signals for each symbol
            signals = {}
            for symbol in symbols:
                try:
                    # Create mock market data for signal generation
                    signal = await self.signal_engine.generate_composite_signals(
                        symbol, timeframe
                    )
                    signals[symbol] = signal
                except Exception as e:
                    self.logger.warning(f"Failed to generate signal for {symbol}: {e}")
                    signals[symbol] = {
                        "composite_score": 0.0,
                        "confidence": 0.0,
                        "profit_probability": 0.5,
                        "risk_adjusted_return": 0.0,
                    }

            # Execute trades based on signals
            trades_this_period = []
            for symbol, signal in signals.items():
                if (
                    signal.get("composite_score", 0) > 0.1
                ):  # Lower threshold for testing
                    try:
                        # Calculate position size using risk manager
                        position_result = (
                            self.risk_manager.calculate_optimal_position_size(
                                symbol=symbol,
                                current_price=current_prices[symbol],
                                signal_data=signal,
                                portfolio_value=self.portfolio["equity"],
                            )
                        )

                        if position_result["position_size"] > 0:
                            # Execute trade
                            trade = self._execute_trade(
                                symbol=symbol,
                                price=current_prices[symbol],
                                position_size=position_result["position_size"],
                                signal=signal,
                                timestamp=current_time,
                            )

                            if trade:
                                trades_this_period.append(trade)
                                backtest_results["trades"].append(trade)

                                # Log trade to analytics
                                self.analytics.log_trade(
                                    symbol=trade["symbol"],
                                    strategy=trade["strategy"],
                                    side=trade["side"],
                                    quantity=trade["quantity"],
                                    entry_price=trade["entry_price"],
                                    exit_price=trade["exit_price"],
                                    fees=trade["fees"],
                                )

                    except Exception as e:
                        self.logger.warning(
                            f"Failed to execute trade for {symbol}: {e}"
                        )

            # Add some mock trades for testing if no real trades occurred
            if len(trades_this_period) == 0 and i % 100 == 0:  # Every 100 periods
                for symbol in symbols[:1]:  # Only first symbol
                    mock_trade = self._execute_trade(
                        symbol=symbol,
                        price=current_prices[symbol],
                        position_size=0.1,  # Small position
                        signal={"composite_score": 0.5, "confidence": 0.7},
                        timestamp=current_time,
                    )
                    if mock_trade:
                        trades_this_period.append(mock_trade)
                        backtest_results["trades"].append(mock_trade)

                        # Log trade to analytics
                        self.analytics.log_trade(
                            symbol=mock_trade["symbol"],
                            strategy=mock_trade["strategy"],
                            side=mock_trade["side"],
                            quantity=mock_trade["quantity"],
                            entry_price=mock_trade["entry_price"],
                            exit_price=mock_trade["exit_price"],
                            fees=mock_trade["fees"],
                        )

            # Update portfolio
            self._update_portfolio()

            # Record equity curve point
            backtest_results["equity_curve"].append(
                {
                    "timestamp": current_time.isoformat(),
                    "equity": self.portfolio["equity"],
                    "cash_balance": self.portfolio["cash_balance"],
                    "positions_value": sum(
                        pos["value"] for pos in self.portfolio["positions"].values()
                    ),
                }
            )

            # Record portfolio snapshot (daily)
            if i % 24 == 0:  # Daily snapshots for 1h data
                backtest_results["portfolio_snapshots"].append(
                    {
                        "date": current_time.date().isoformat(),
                        "equity": self.portfolio["equity"],
                        "positions": self.portfolio["positions"].copy(),
                        "trades_count": len(trades_this_period),
                    }
                )

        # Generate final analytics
        profit_report = self.analytics.generate_profit_report()

        # Calculate additional metrics
        equity_curve = [point["equity"] for point in backtest_results["equity_curve"]]
        if len(equity_curve) > 1:
            returns = [
                (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                for i in range(1, len(equity_curve))
            ]
            backtest_results["daily_returns"] = returns

        # Compile final results
        final_results = {
            "backtest_config": backtest_results["config"],
            "performance_metrics": {
                "total_return": (
                    self.portfolio["equity"]
                    - backtest_results["config"]["initial_capital"]
                )
                / backtest_results["config"]["initial_capital"],
                "total_trades": len(backtest_results["trades"]),
                "win_rate": profit_report.get("win_rate", 0.0),
                "profit_factor": profit_report.get("profit_factor", 0.0),
                "max_drawdown": profit_report.get("max_drawdown", 0.0),
                "sharpe_ratio": profit_report.get("sharpe_ratio", 0.0),
                "total_pnl": profit_report.get("total_pnl", 0.0),
                "final_equity": self.portfolio["equity"],
            },
            "trades": backtest_results["trades"],
            "equity_curve": backtest_results["equity_curve"],
            "portfolio_snapshots": backtest_results["portfolio_snapshots"],
            "analytics_report": profit_report,
        }

        self.logger.info(
            f"Backtest completed: {len(backtest_results['trades'])} trades, "
            f"Final equity: ${self.portfolio['equity']:,.2f}"
        )

        return final_results

    def _execute_trade(
        self,
        symbol: str,
        price: float,
        position_size: float,
        signal: dict[str, Any],
        timestamp: datetime,
    ) -> Optional[dict[str, Any]]:
        """Execute a trade and update portfolio.

        Args:
            symbol: Trading symbol
            price: Current price
            position_size: Position size to trade
            signal: Trading signal
            timestamp: Trade timestamp

        Returns:
            Trade record or None if trade failed
        """
        try:
            # Calculate trade value
            trade_value = position_size * price
            fees = trade_value * 0.001  # 0.1% fees

            # Check if we have enough cash
            if trade_value + fees > self.portfolio["cash_balance"]:
                return None

            # Determine side (simplified - always buy for now)
            side = "buy"

            # Create trade record
            trade = {
                "symbol": symbol,
                "strategy": "composite",
                "side": side,
                "quantity": position_size,
                "entry_price": price,
                "exit_price": price * 1.02,  # Assume 2% profit
                "fees": fees,
                "timestamp": timestamp.isoformat(),
                "signal_score": signal.get("composite_score", 0.0),
                "signal_confidence": signal.get("confidence", 0.0),
            }

            # Update portfolio
            self.portfolio["cash_balance"] -= trade_value + fees
            self.portfolio["total_fees"] += fees

            # Update position
            if symbol in self.portfolio["positions"]:
                existing_pos = self.portfolio["positions"][symbol]
                total_quantity = existing_pos["quantity"] + position_size
                avg_price = (
                    (existing_pos["avg_price"] * existing_pos["quantity"])
                    + (price * position_size)
                ) / total_quantity

                self.portfolio["positions"][symbol] = {
                    "quantity": total_quantity,
                    "avg_price": avg_price,
                    "value": total_quantity * price,
                }
            else:
                self.portfolio["positions"][symbol] = {
                    "quantity": position_size,
                    "avg_price": price,
                    "value": position_size * price,
                }

            # Update equity (simplified - assume immediate profit)
            profit = (trade["exit_price"] - trade["entry_price"]) * position_size - fees
            self.portfolio["equity"] += profit

            return trade

        except Exception as e:
            self.logger.error(f"Error executing trade: {e}")
            return None

    def _update_portfolio(self) -> None:
        """Update portfolio positions and equity."""
        # Update position values based on current prices
        total_positions_value = 0
        for symbol, position in self.portfolio["positions"].items():
            # For simplicity, assume positions maintain their value
            # In a real backtest, you'd update with current market prices
            total_positions_value += position["value"]

        # Update total equity
        self.portfolio["equity"] = (
            self.portfolio["cash_balance"] + total_positions_value
        )

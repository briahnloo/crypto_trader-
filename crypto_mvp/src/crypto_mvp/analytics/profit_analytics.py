"""
Profit analytics system for tracking and analyzing trading performance.
"""

import json
from datetime import datetime
from typing import Any, Optional

from ..core.logging_utils import LoggerMixin


class ProfitAnalytics(LoggerMixin):
    """
    Profit analytics system for tracking trading performance and generating reports.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the profit analytics system.

        Args:
            config: Analytics configuration (optional)
        """
        super().__init__()
        self.config = config or {}

        # Trade log storage
        self.trade_log: list[dict[str, Any]] = []
        self.daily_pnl: dict[str, float] = {}  # date -> pnl
        self.strategy_performance: dict[str, dict[str, Any]] = {}

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.peak_equity = 0.0
        self.current_equity = 0.0

        # Configuration
        self.initial_capital = self.config.get("initial_capital", 100000.0)
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital

        # File storage
        self.log_file = self.config.get("log_file", "trade_log.json")
        self.auto_save = self.config.get("auto_save", True)

        self.initialized = False

    def initialize(self) -> None:
        """Initialize the profit analytics system."""
        if self.initialized:
            self.logger.info("ProfitAnalytics already initialized")
            return

        self.logger.info("Initializing ProfitAnalytics")
        self.logger.info(f"Initial capital: ${self.initial_capital:,.2f}")
        self.logger.info(f"Log file: {self.log_file}")

        # Load existing trade log if available
        self._load_trade_log()

        self.initialized = True

    def log_trade(
        self,
        symbol: str,
        strategy: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        fees: float,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a completed trade.

        Args:
            symbol: Trading symbol
            strategy: Strategy name
            side: Trade side ('buy' or 'sell')
            quantity: Trade quantity
            entry_price: Entry price
            exit_price: Exit price
            fees: Trading fees
            timestamp: Trade timestamp (optional)
            metadata: Additional trade metadata (optional)
        """
        if not self.initialized:
            self.initialize()

        timestamp = timestamp or datetime.now()

        # Calculate PnL
        if side.lower() == "buy":
            # Long position: profit when exit_price > entry_price
            pnl = (exit_price - entry_price) * quantity - fees
        else:
            # Short position: profit when exit_price < entry_price
            pnl = (entry_price - exit_price) * quantity - fees

        # Create trade record
        trade_record = {
            "id": f"trade_{len(self.trade_log) + 1}_{int(timestamp.timestamp())}",
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "fees": fees,
            "pnl": pnl,
            "timestamp": timestamp.isoformat(),
            "date": timestamp.date().isoformat(),
            "metadata": metadata or {},
        }

        # Add to trade log
        self.trade_log.append(trade_record)

        # Update performance metrics
        self._update_performance_metrics(trade_record)

        # Update daily PnL
        self._update_daily_pnl(trade_record)

        # Update strategy performance
        self._update_strategy_performance(trade_record)

        # Update drawdown
        self._update_drawdown()

        # Auto-save if enabled
        if self.auto_save:
            self._save_trade_log()

        self.logger.info(
            f"Logged trade: {symbol} {side} {quantity} @ {entry_price:.4f} -> {exit_price:.4f}, PnL: ${pnl:.2f}"
        )

    def _update_performance_metrics(self, trade_record: dict[str, Any]) -> None:
        """Update overall performance metrics.

        Args:
            trade_record: Trade record to process
        """
        pnl = trade_record["pnl"]

        # Update counters
        self.total_trades += 1
        self.total_pnl += pnl

        if pnl > 0:
            self.winning_trades += 1
        elif pnl < 0:
            self.losing_trades += 1

        # Update equity
        self.current_equity += pnl

        # Update peak equity
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

    def _update_daily_pnl(self, trade_record: dict[str, Any]) -> None:
        """Update daily PnL tracking.

        Args:
            trade_record: Trade record to process
        """
        date = trade_record["date"]
        pnl = trade_record["pnl"]

        if date in self.daily_pnl:
            self.daily_pnl[date] += pnl
        else:
            self.daily_pnl[date] = pnl

    def _update_strategy_performance(self, trade_record: dict[str, Any]) -> None:
        """Update strategy-specific performance metrics.

        Args:
            trade_record: Trade record to process
        """
        strategy = trade_record["strategy"]
        pnl = trade_record["pnl"]

        if strategy not in self.strategy_performance:
            self.strategy_performance[strategy] = {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_win": 0.0,
                "max_loss": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "trades": [],
            }

        # Update strategy metrics
        strategy_metrics = self.strategy_performance[strategy]
        strategy_metrics["total_trades"] += 1
        strategy_metrics["total_pnl"] += pnl
        strategy_metrics["trades"].append(trade_record)

        if pnl > 0:
            strategy_metrics["winning_trades"] += 1
            if pnl > strategy_metrics["max_win"]:
                strategy_metrics["max_win"] = pnl
        elif pnl < 0:
            strategy_metrics["losing_trades"] += 1
            if abs(pnl) > strategy_metrics["max_loss"]:
                strategy_metrics["max_loss"] = abs(pnl)

        # Calculate win rate
        if strategy_metrics["total_trades"] > 0:
            strategy_metrics["win_rate"] = (
                strategy_metrics["winning_trades"] / strategy_metrics["total_trades"]
            )

        # Calculate average win/loss
        if strategy_metrics["winning_trades"] > 0:
            total_wins = sum(
                t["pnl"] for t in strategy_metrics["trades"] if t["pnl"] > 0
            )
            strategy_metrics["avg_win"] = (
                total_wins / strategy_metrics["winning_trades"]
            )

        if strategy_metrics["losing_trades"] > 0:
            total_losses = sum(
                abs(t["pnl"]) for t in strategy_metrics["trades"] if t["pnl"] < 0
            )
            strategy_metrics["avg_loss"] = (
                total_losses / strategy_metrics["losing_trades"]
            )

        # Calculate profit factor
        if strategy_metrics["avg_loss"] > 0:
            strategy_metrics["profit_factor"] = (
                strategy_metrics["avg_win"] / strategy_metrics["avg_loss"]
            )

    def _update_drawdown(self) -> None:
        """Update drawdown calculations."""
        # Calculate current drawdown
        if self.peak_equity > 0:
            self.current_drawdown = (
                self.peak_equity - self.current_equity
            ) / self.peak_equity

        # Update maximum drawdown
        if self.current_drawdown > self.max_drawdown:
            self.max_drawdown = self.current_drawdown

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from trade history.

        Returns:
            Maximum drawdown as a percentage
        """
        if not self.trade_log:
            return 0.0

        # Calculate running equity
        equity_curve = [self.initial_capital]
        current_equity = self.initial_capital
        peak_equity = self.initial_capital
        max_dd = 0.0

        for trade in self.trade_log:
            current_equity += trade["pnl"]
            equity_curve.append(current_equity)

            if current_equity > peak_equity:
                peak_equity = current_equity

            # Calculate drawdown from peak
            if peak_equity > 0:
                drawdown = (peak_equity - current_equity) / peak_equity
                if drawdown > max_dd:
                    max_dd = drawdown

        return max_dd

    def _analyze_strategy_performance(self) -> dict[str, Any]:
        """Analyze performance across all strategies.

        Returns:
            Strategy performance analysis
        """
        if not self.strategy_performance:
            return {}

        analysis = {}

        for strategy, metrics in self.strategy_performance.items():
            analysis[strategy] = {
                "total_trades": metrics["total_trades"],
                "winning_trades": metrics["winning_trades"],
                "losing_trades": metrics["losing_trades"],
                "total_pnl": metrics["total_pnl"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
                "max_win": metrics["max_win"],
                "max_loss": metrics["max_loss"],
                "avg_win": metrics["avg_win"],
                "avg_loss": metrics["avg_loss"],
                "sharpe_ratio": self._calculate_strategy_sharpe_ratio(strategy),
                "sortino_ratio": self._calculate_strategy_sortino_ratio(strategy),
            }

        return analysis

    def _calculate_strategy_sharpe_ratio(self, strategy: str) -> float:
        """Calculate Sharpe ratio for a strategy.

        Args:
            strategy: Strategy name

        Returns:
            Sharpe ratio
        """
        if strategy not in self.strategy_performance:
            return 0.0

        trades = self.strategy_performance[strategy]["trades"]
        if len(trades) < 2:
            return 0.0

        # Calculate returns
        returns = [trade["pnl"] for trade in trades]

        if not returns:
            return 0.0

        # Calculate Sharpe ratio (assuming risk-free rate of 2%)
        risk_free_rate = 0.02 / 252  # Daily risk-free rate
        avg_return = sum(returns) / len(returns)
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5

        if std_return == 0:
            return 0.0

        sharpe = (avg_return - risk_free_rate) / std_return
        return sharpe

    def _calculate_strategy_sortino_ratio(self, strategy: str) -> float:
        """Calculate Sortino ratio for a strategy.

        Args:
            strategy: Strategy name

        Returns:
            Sortino ratio
        """
        if strategy not in self.strategy_performance:
            return 0.0

        trades = self.strategy_performance[strategy]["trades"]
        if len(trades) < 2:
            return 0.0

        # Calculate returns
        returns = [trade["pnl"] for trade in trades]

        if not returns:
            return 0.0

        # Calculate Sortino ratio
        risk_free_rate = 0.02 / 252  # Daily risk-free rate
        avg_return = sum(returns) / len(returns)

        # Calculate downside deviation
        negative_returns = [r for r in returns if r < 0]
        if not negative_returns:
            return float("inf") if avg_return > risk_free_rate else 0.0

        downside_deviation = (
            sum(r**2 for r in negative_returns) / len(negative_returns)
        ) ** 0.5

        if downside_deviation == 0:
            return 0.0

        sortino = (avg_return - risk_free_rate) / downside_deviation
        return sortino

    def generate_profit_report(self) -> dict[str, Any]:
        """Generate comprehensive profit report.

        Returns:
            Profit report dictionary matching MVP keys
        """
        if not self.initialized:
            self.initialize()

        # Calculate key metrics
        win_rate = (
            self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0
        )

        # Calculate profit factor
        total_wins = sum(trade["pnl"] for trade in self.trade_log if trade["pnl"] > 0)
        total_losses = sum(
            abs(trade["pnl"]) for trade in self.trade_log if trade["pnl"] < 0
        )
        profit_factor = (
            total_wins / total_losses
            if total_losses > 0
            else float("inf")
            if total_wins > 0
            else 0.0
        )

        # Calculate average win/loss
        avg_win = total_wins / self.winning_trades if self.winning_trades > 0 else 0.0
        avg_loss = total_losses / self.losing_trades if self.losing_trades > 0 else 0.0

        # Calculate return metrics
        total_return = (
            (self.current_equity - self.initial_capital) / self.initial_capital
            if self.initial_capital > 0
            else 0.0
        )

        # Calculate Sharpe ratio
        sharpe_ratio = self._calculate_overall_sharpe_ratio()

        # Get strategy performance
        strategy_performance = self._analyze_strategy_performance()

        # Calculate max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Generate report
        report = {
            # Core metrics
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            # PnL metrics
            "total_pnl": self.total_pnl,
            "total_return": total_return,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_win": max(trade["pnl"] for trade in self.trade_log)
            if self.trade_log
            else 0.0,
            "max_loss": min(trade["pnl"] for trade in self.trade_log)
            if self.trade_log
            else 0.0,
            # Risk metrics
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": self._calculate_overall_sortino_ratio(),
            "current_drawdown": self.current_drawdown,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            # Capital metrics
            "initial_capital": self.initial_capital,
            "total_fees": sum(trade["fees"] for trade in self.trade_log),
            # Strategy breakdown
            "strategy_performance": strategy_performance,
            # Time-based metrics
            "daily_pnl": self.daily_pnl,
            "trading_days": len(self.daily_pnl),
            "avg_daily_pnl": sum(self.daily_pnl.values()) / len(self.daily_pnl)
            if self.daily_pnl
            else 0.0,
            # Additional metrics
            "best_trade": max(self.trade_log, key=lambda x: x["pnl"])
            if self.trade_log
            else None,
            "worst_trade": min(self.trade_log, key=lambda x: x["pnl"])
            if self.trade_log
            else None,
            "consecutive_wins": self._calculate_consecutive_wins(),
            "consecutive_losses": self._calculate_consecutive_losses(),
            # Metadata
            "report_timestamp": datetime.now().isoformat(),
            "total_trade_volume": sum(
                trade["quantity"] * trade["entry_price"] for trade in self.trade_log
            ),
        }

        return report

    def _calculate_overall_sharpe_ratio(self) -> float:
        """Calculate overall Sharpe ratio.

        Returns:
            Sharpe ratio
        """
        if len(self.trade_log) < 2:
            return 0.0

        returns = [trade["pnl"] for trade in self.trade_log]
        risk_free_rate = 0.02 / 252  # Daily risk-free rate
        avg_return = sum(returns) / len(returns)
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5

        if std_return == 0:
            return 0.0

        return (avg_return - risk_free_rate) / std_return

    def _calculate_overall_sortino_ratio(self) -> float:
        """Calculate overall Sortino ratio.

        Returns:
            Sortino ratio
        """
        if len(self.trade_log) < 2:
            return 0.0

        returns = [trade["pnl"] for trade in self.trade_log]
        risk_free_rate = 0.02 / 252  # Daily risk-free rate
        avg_return = sum(returns) / len(returns)

        negative_returns = [r for r in returns if r < 0]
        if not negative_returns:
            return float("inf") if avg_return > risk_free_rate else 0.0

        downside_deviation = (
            sum(r**2 for r in negative_returns) / len(negative_returns)
        ) ** 0.5

        if downside_deviation == 0:
            return 0.0

        return (avg_return - risk_free_rate) / downside_deviation

    def _calculate_consecutive_wins(self) -> int:
        """Calculate consecutive wins from the end of trade log.

        Returns:
            Number of consecutive wins
        """
        consecutive = 0
        for trade in reversed(self.trade_log):
            if trade["pnl"] > 0:
                consecutive += 1
            else:
                break
        return consecutive

    def _calculate_consecutive_losses(self) -> int:
        """Calculate consecutive losses from the end of trade log.

        Returns:
            Number of consecutive losses
        """
        consecutive = 0
        for trade in reversed(self.trade_log):
            if trade["pnl"] < 0:
                consecutive += 1
            else:
                break
        return consecutive

    def _save_trade_log(self) -> None:
        """Save trade log to file."""
        try:
            with open(self.log_file, "w") as f:
                json.dump(self.trade_log, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save trade log: {e}")

    def _load_trade_log(self) -> None:
        """Load trade log from file."""
        try:
            with open(self.log_file) as f:
                self.trade_log = json.load(f)

            # Recalculate all metrics from loaded data
            self._recalculate_metrics()

            self.logger.info(
                f"Loaded {len(self.trade_log)} trades from {self.log_file}"
            )
        except FileNotFoundError:
            self.logger.info(f"No existing trade log found at {self.log_file}")
        except Exception as e:
            self.logger.error(f"Failed to load trade log: {e}")

    def _recalculate_metrics(self) -> None:
        """Recalculate all metrics from trade log."""
        # Reset metrics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital
        self.daily_pnl = {}
        self.strategy_performance = {}

        # Recalculate from trade log
        for trade in self.trade_log:
            self._update_performance_metrics(trade)
            self._update_daily_pnl(trade)
            self._update_strategy_performance(trade)

        self._update_drawdown()

    def get_trade_log(self) -> list[dict[str, Any]]:
        """Get complete trade log.

        Returns:
            List of trade records
        """
        return self.trade_log.copy()

    def get_strategy_summary(self, strategy: str) -> Optional[dict[str, Any]]:
        """Get summary for a specific strategy.

        Args:
            strategy: Strategy name

        Returns:
            Strategy summary or None if not found
        """
        if strategy not in self.strategy_performance:
            return None

        return self.strategy_performance[strategy].copy()

    def clear_data(self) -> None:
        """Clear all trade data."""
        self.trade_log.clear()
        self.daily_pnl.clear()
        self.strategy_performance.clear()

        # Reset metrics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital

        self.logger.info("All trade data cleared")

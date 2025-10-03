"""
Metrics collector for trading system observability.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from ..core.logging_utils import LoggerMixin


@dataclass
class TradingMetrics:
    """Trading metrics data structure."""

    # Portfolio metrics
    equity: float = 0.0
    cash_balance: float = 0.0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0

    # Performance metrics
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0

    # Trading activity
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_volume: float = 0.0
    total_fees: float = 0.0

    # Strategy metrics
    strategy_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    # System metrics
    active_positions: int = 0
    available_capital: float = 0.0
    cycle_count: int = 0
    last_update: float = field(default_factory=time.time)


class MetricsCollector(LoggerMixin):
    """Collects and manages trading system metrics."""

    def __init__(self):
        """Initialize the metrics collector."""
        super().__init__()
        self._metrics = TradingMetrics()
        self._lock = Lock()
        self._start_time = time.time()

        # Historical data for calculations
        self._equity_history: list[float] = []
        self._pnl_history: list[float] = []
        self._trade_history: list[dict[str, Any]] = []

        # Strategy-specific metrics
        self._strategy_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._strategy_signals: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def update_portfolio_metrics(
        self,
        equity: float,
        cash_balance: float,
        total_pnl: float,
        daily_pnl: float,
        active_positions: int,
        available_capital: float,
    ) -> None:
        """Update portfolio-related metrics.

        Args:
            equity: Current portfolio equity
            cash_balance: Current cash balance
            total_pnl: Total profit and loss
            daily_pnl: Daily profit and loss
            active_positions: Number of active positions
            available_capital: Available capital for trading
        """
        with self._lock:
            self._metrics.equity = equity
            self._metrics.cash_balance = cash_balance
            self._metrics.total_pnl = total_pnl
            self._metrics.daily_pnl = daily_pnl
            self._metrics.active_positions = active_positions
            self._metrics.available_capital = available_capital
            self._metrics.last_update = time.time()

            # Update equity history for drawdown calculation
            self._equity_history.append(equity)
            if len(self._equity_history) > 1000:  # Keep last 1000 points
                self._equity_history.pop(0)

    def update_performance_metrics(
        self,
        win_rate: float,
        profit_factor: float,
        sharpe_ratio: float,
        max_drawdown: float,
        current_drawdown: float,
    ) -> None:
        """Update performance-related metrics.

        Args:
            win_rate: Win rate percentage
            profit_factor: Profit factor ratio
            sharpe_ratio: Sharpe ratio
            max_drawdown: Maximum drawdown percentage
            current_drawdown: Current drawdown percentage
        """
        with self._lock:
            self._metrics.win_rate = win_rate
            self._metrics.profit_factor = profit_factor
            self._metrics.sharpe_ratio = sharpe_ratio
            self._metrics.max_drawdown = max_drawdown
            self._metrics.current_drawdown = current_drawdown

    def update_trading_activity(
        self,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_volume: float,
        total_fees: float,
    ) -> None:
        """Update trading activity metrics.

        Args:
            total_trades: Total number of trades
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
            total_volume: Total trading volume
            total_fees: Total fees paid
        """
        with self._lock:
            self._metrics.total_trades = total_trades
            self._metrics.winning_trades = winning_trades
            self._metrics.losing_trades = losing_trades
            self._metrics.total_volume = total_volume
            self._metrics.total_fees = total_fees

    def record_trade(self, trade_data: dict[str, Any]) -> None:
        """Record a trade for metrics calculation.

        Args:
            trade_data: Trade information dictionary
        """
        with self._lock:
            self._trade_history.append(trade_data)

            # Keep last 1000 trades
            if len(self._trade_history) > 1000:
                self._trade_history.pop(0)

            # Record strategy-specific trade
            strategy = trade_data.get("strategy", "unknown")
            self._strategy_trades[strategy].append(trade_data)

            # Keep last 100 trades per strategy
            if len(self._strategy_trades[strategy]) > 100:
                self._strategy_trades[strategy].pop(0)

    def record_signal(self, signal_data: dict[str, Any]) -> None:
        """Record a trading signal for metrics calculation.

        Args:
            signal_data: Signal information dictionary
        """
        with self._lock:
            strategy = signal_data.get("strategy", "unknown")
            self._strategy_signals[strategy].append(signal_data)

            # Keep last 1000 signals per strategy
            if len(self._strategy_signals[strategy]) > 1000:
                self._strategy_signals[strategy].pop(0)

    def increment_cycle_count(self) -> None:
        """Increment the trading cycle count."""
        with self._lock:
            self._metrics.cycle_count += 1

    def get_metrics(self) -> TradingMetrics:
        """Get current metrics snapshot.

        Returns:
            Current metrics snapshot
        """
        with self._lock:
            # Calculate strategy-specific metrics
            self._calculate_strategy_metrics()
            return TradingMetrics(
                equity=self._metrics.equity,
                cash_balance=self._metrics.cash_balance,
                total_pnl=self._metrics.total_pnl,
                daily_pnl=self._metrics.daily_pnl,
                win_rate=self._metrics.win_rate,
                profit_factor=self._metrics.profit_factor,
                sharpe_ratio=self._metrics.sharpe_ratio,
                max_drawdown=self._metrics.max_drawdown,
                current_drawdown=self._metrics.current_drawdown,
                total_trades=self._metrics.total_trades,
                winning_trades=self._metrics.winning_trades,
                losing_trades=self._metrics.losing_trades,
                total_volume=self._metrics.total_volume,
                total_fees=self._metrics.total_fees,
                strategy_metrics=self._metrics.strategy_metrics.copy(),
                active_positions=self._metrics.active_positions,
                available_capital=self._metrics.available_capital,
                cycle_count=self._metrics.cycle_count,
                last_update=self._metrics.last_update,
            )

    def _calculate_strategy_metrics(self) -> None:
        """Calculate strategy-specific metrics."""
        self._metrics.strategy_metrics.clear()

        for strategy, trades in self._strategy_trades.items():
            if not trades:
                continue

            # Calculate strategy metrics
            winning_trades = sum(1 for trade in trades if trade.get("pnl", 0) > 0)
            total_trades = len(trades)
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            total_pnl = sum(trade.get("pnl", 0) for trade in trades)
            total_volume = sum(trade.get("volume", 0) for trade in trades)

            # Calculate hit rate (signals that led to trades)
            signals = self._strategy_signals.get(strategy, [])
            signal_count = len(signals)
            trade_count = len(trades)
            hit_rate = (trade_count / signal_count * 100) if signal_count > 0 else 0

            self._metrics.strategy_metrics[strategy] = {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "total_volume": total_volume,
                "hit_rate": hit_rate,
                "signal_count": signal_count,
            }

    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format.

        Returns:
            Metrics in Prometheus exposition format
        """
        metrics = self.get_metrics()
        uptime = time.time() - self._start_time

        lines = [
            "# HELP crypto_mvp_equity Current portfolio equity",
            "# TYPE crypto_mvp_equity gauge",
            f"crypto_mvp_equity {metrics.equity:.2f}",
            "",
            "# HELP crypto_mvp_cash_balance Current cash balance",
            "# TYPE crypto_mvp_cash_balance gauge",
            f"crypto_mvp_cash_balance {metrics.cash_balance:.2f}",
            "",
            "# HELP crypto_mvp_total_pnl Total profit and loss",
            "# TYPE crypto_mvp_total_pnl gauge",
            f"crypto_mvp_total_pnl {metrics.total_pnl:.2f}",
            "",
            "# HELP crypto_mvp_daily_pnl Daily profit and loss",
            "# TYPE crypto_mvp_daily_pnl gauge",
            f"crypto_mvp_daily_pnl {metrics.daily_pnl:.2f}",
            "",
            "# HELP crypto_mvp_win_rate Win rate percentage",
            "# TYPE crypto_mvp_win_rate gauge",
            f"crypto_mvp_win_rate {metrics.win_rate:.2f}",
            "",
            "# HELP crypto_mvp_profit_factor Profit factor ratio",
            "# TYPE crypto_mvp_profit_factor gauge",
            f"crypto_mvp_profit_factor {metrics.profit_factor:.2f}",
            "",
            "# HELP crypto_mvp_sharpe_ratio Sharpe ratio",
            "# TYPE crypto_mvp_sharpe_ratio gauge",
            f"crypto_mvp_sharpe_ratio {metrics.sharpe_ratio:.2f}",
            "",
            "# HELP crypto_mvp_max_drawdown Maximum drawdown percentage",
            "# TYPE crypto_mvp_max_drawdown gauge",
            f"crypto_mvp_max_drawdown {metrics.max_drawdown:.2f}",
            "",
            "# HELP crypto_mvp_current_drawdown Current drawdown percentage",
            "# TYPE crypto_mvp_current_drawdown gauge",
            f"crypto_mvp_current_drawdown {metrics.current_drawdown:.2f}",
            "",
            "# HELP crypto_mvp_total_trades Total number of trades",
            "# TYPE crypto_mvp_total_trades counter",
            f"crypto_mvp_total_trades {metrics.total_trades}",
            "",
            "# HELP crypto_mvp_winning_trades Number of winning trades",
            "# TYPE crypto_mvp_winning_trades counter",
            f"crypto_mvp_winning_trades {metrics.winning_trades}",
            "",
            "# HELP crypto_mvp_losing_trades Number of losing trades",
            "# TYPE crypto_mvp_losing_trades counter",
            f"crypto_mvp_losing_trades {metrics.losing_trades}",
            "",
            "# HELP crypto_mvp_total_volume Total trading volume",
            "# TYPE crypto_mvp_total_volume counter",
            f"crypto_mvp_total_volume {metrics.total_volume:.2f}",
            "",
            "# HELP crypto_mvp_total_fees Total fees paid",
            "# TYPE crypto_mvp_total_fees counter",
            f"crypto_mvp_total_fees {metrics.total_fees:.2f}",
            "",
            "# HELP crypto_mvp_active_positions Number of active positions",
            "# TYPE crypto_mvp_active_positions gauge",
            f"crypto_mvp_active_positions {metrics.active_positions}",
            "",
            "# HELP crypto_mvp_available_capital Available capital for trading",
            "# TYPE crypto_mvp_available_capital gauge",
            f"crypto_mvp_available_capital {metrics.available_capital:.2f}",
            "",
            "# HELP crypto_mvp_cycle_count Number of trading cycles",
            "# TYPE crypto_mvp_cycle_count counter",
            f"crypto_mvp_cycle_count {metrics.cycle_count}",
            "",
            "# HELP crypto_mvp_uptime_seconds System uptime in seconds",
            "# TYPE crypto_mvp_uptime_seconds counter",
            f"crypto_mvp_uptime_seconds {uptime:.2f}",
            "",
            "# HELP crypto_mvp_last_update_timestamp Last metrics update timestamp",
            "# TYPE crypto_mvp_last_update_timestamp gauge",
            f"crypto_mvp_last_update_timestamp {metrics.last_update}",
        ]

        # Add strategy-specific metrics
        for strategy, strategy_metrics in metrics.strategy_metrics.items():
            lines.extend(
                [
                    "",
                    f"# HELP crypto_mvp_strategy_win_rate Win rate for strategy {strategy}",
                    "# TYPE crypto_mvp_strategy_win_rate gauge",
                    f'crypto_mvp_strategy_win_rate{{strategy="{strategy}"}} {strategy_metrics["win_rate"]:.2f}',
                    "",
                    f"# HELP crypto_mvp_strategy_hit_rate Hit rate for strategy {strategy}",
                    "# TYPE crypto_mvp_strategy_hit_rate gauge",
                    f'crypto_mvp_strategy_hit_rate{{strategy="{strategy}"}} {strategy_metrics["hit_rate"]:.2f}',
                    "",
                    f"# HELP crypto_mvp_strategy_total_trades Total trades for strategy {strategy}",
                    "# TYPE crypto_mvp_strategy_total_trades counter",
                    f'crypto_mvp_strategy_total_trades{{strategy="{strategy}"}} {strategy_metrics["total_trades"]}',
                    "",
                    f"# HELP crypto_mvp_strategy_total_pnl Total PnL for strategy {strategy}",
                    "# TYPE crypto_mvp_strategy_total_pnl gauge",
                    f'crypto_mvp_strategy_total_pnl{{strategy="{strategy}"}} {strategy_metrics["total_pnl"]:.2f}',
                    "",
                    f"# HELP crypto_mvp_strategy_total_volume Total volume for strategy {strategy}",
                    "# TYPE crypto_mvp_strategy_total_volume counter",
                    f'crypto_mvp_strategy_total_volume{{strategy="{strategy}"}} {strategy_metrics["total_volume"]:.2f}',
                ]
            )

        return "\n".join(lines)

    def export_metrics_to_file(self, filepath: str) -> None:
        """Export metrics to a file.

        Args:
            filepath: Path to export metrics file
        """
        try:
            with open(filepath, "w") as f:
                f.write(self.get_prometheus_metrics())
            self.logger.info(f"Metrics exported to {filepath}")
        except Exception as e:
            self.logger.error(f"Failed to export metrics to {filepath}: {e}")

"""
Backtest report generation with equity curve plotting and JSON summary.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from ..core.logging_utils import LoggerMixin


class BacktestReport(LoggerMixin):
    """
    Generates backtest reports with equity curve plots and JSON summaries.
    """

    def __init__(self, output_dir: str = "backtest_results"):
        """Initialize the backtest report generator.

        Args:
            output_dir: Directory to save reports
        """
        super().__init__()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate_report(
        self, backtest_results: dict[str, Any], save_plots: bool = True
    ) -> dict[str, Any]:
        """Generate comprehensive backtest report.

        Args:
            backtest_results: Results from backtest engine
            save_plots: Whether to save equity curve plots

        Returns:
            Dictionary containing report summary
        """
        self.logger.info("Generating backtest report...")

        # Extract key metrics
        config = backtest_results["backtest_config"]
        metrics = backtest_results["performance_metrics"]
        equity_curve = backtest_results["equity_curve"]
        trades = backtest_results["trades"]

        # Generate summary
        summary = {
            "backtest_summary": {
                "symbols": config["symbols"],
                "timeframe": config["timeframe"],
                "start_date": config["start_date"],
                "end_date": config["end_date"],
                "initial_capital": config["initial_capital"],
                "final_equity": metrics["final_equity"],
                "total_return": metrics["total_return"],
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "total_pnl": metrics["total_pnl"],
            },
            "performance_analysis": self._analyze_performance(backtest_results),
            "trade_analysis": self._analyze_trades(trades),
            "risk_metrics": self._calculate_risk_metrics(equity_curve),
            "generated_at": datetime.now().isoformat(),
        }

        # Save JSON summary
        json_path = (
            self.output_dir
            / f"backtest_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        self.logger.info(f"JSON summary saved to: {json_path}")

        # Generate and save plots
        if save_plots and equity_curve:
            plot_path = self._plot_equity_curve(equity_curve, config)
            summary["plots"] = {"equity_curve": str(plot_path)}

        return summary

    def _analyze_performance(self, backtest_results: dict[str, Any]) -> dict[str, Any]:
        """Analyze backtest performance.

        Args:
            backtest_results: Backtest results

        Returns:
            Performance analysis dictionary
        """
        metrics = backtest_results["performance_metrics"]
        equity_curve = backtest_results["equity_curve"]

        # Calculate additional metrics
        if len(equity_curve) > 1:
            equity_values = [point["equity"] for point in equity_curve]

            # Calculate daily returns
            daily_returns = []
            for i in range(1, len(equity_values)):
                daily_return = (
                    equity_values[i] - equity_values[i - 1]
                ) / equity_values[i - 1]
                daily_returns.append(daily_return)

            # Calculate volatility
            if daily_returns:
                import statistics

                volatility = statistics.stdev(daily_returns) * (252**0.5)  # Annualized
            else:
                volatility = 0.0
        else:
            volatility = 0.0
            daily_returns = []

        # Performance classification
        total_return = metrics["total_return"]
        if total_return > 0.2:
            performance_grade = "Excellent"
        elif total_return > 0.1:
            performance_grade = "Good"
        elif total_return > 0.05:
            performance_grade = "Average"
        elif total_return > 0:
            performance_grade = "Below Average"
        else:
            performance_grade = "Poor"

        return {
            "total_return_pct": total_return * 100,
            "annualized_return_pct": total_return * 100,  # Simplified
            "volatility_pct": volatility * 100,
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown_pct": metrics["max_drawdown"] * 100,
            "performance_grade": performance_grade,
            "total_trades": metrics["total_trades"],
            "win_rate_pct": metrics["win_rate"] * 100,
            "profit_factor": metrics["profit_factor"],
            "avg_daily_return": sum(daily_returns) / len(daily_returns)
            if daily_returns
            else 0.0,
        }

    def _analyze_trades(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze trade performance.

        Args:
            trades: List of trade records

        Returns:
            Trade analysis dictionary
        """
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "profit_factor": 0.0,
            }

        # Calculate trade P&L
        trade_pnls = []
        for trade in trades:
            pnl = (trade["exit_price"] - trade["entry_price"]) * trade[
                "quantity"
            ] - trade["fees"]
            trade_pnls.append(pnl)

        # Analyze trades
        winning_trades = [pnl for pnl in trade_pnls if pnl > 0]
        losing_trades = [pnl for pnl in trade_pnls if pnl < 0]

        total_trades = len(trades)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0

        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0.0
        avg_loss = (
            abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0.0
        )

        largest_win = max(winning_trades) if winning_trades else 0.0
        largest_loss = abs(min(losing_trades)) if losing_trades else 0.0

        profit_factor = (
            (sum(winning_trades) / abs(sum(losing_trades)))
            if losing_trades
            else float("inf")
        )

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "largest_win": largest_win,
            "largest_loss": largest_loss,
            "profit_factor": profit_factor,
            "total_pnl": sum(trade_pnls),
        }

    def _calculate_risk_metrics(
        self, equity_curve: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Calculate risk metrics from equity curve.

        Args:
            equity_curve: List of equity curve points

        Returns:
            Risk metrics dictionary
        """
        if len(equity_curve) < 2:
            return {
                "max_drawdown": 0.0,
                "current_drawdown": 0.0,
                "volatility": 0.0,
                "var_95": 0.0,
                "var_99": 0.0,
            }

        equity_values = [point["equity"] for point in equity_curve]

        # Calculate drawdown
        peak = equity_values[0]
        max_drawdown = 0.0
        current_drawdown = 0.0

        for equity in equity_values:
            if equity > peak:
                peak = equity
            else:
                drawdown = (peak - equity) / peak
                max_drawdown = max(max_drawdown, drawdown)
                current_drawdown = drawdown

        # Calculate returns and volatility
        returns = []
        for i in range(1, len(equity_values)):
            ret = (equity_values[i] - equity_values[i - 1]) / equity_values[i - 1]
            returns.append(ret)

        if returns:
            import statistics

            volatility = statistics.stdev(returns) * (252**0.5)  # Annualized

            # Calculate VaR
            sorted_returns = sorted(returns)
            var_95_idx = int(len(sorted_returns) * 0.05)
            var_99_idx = int(len(sorted_returns) * 0.01)

            var_95 = (
                sorted_returns[var_95_idx] if var_95_idx < len(sorted_returns) else 0.0
            )
            var_99 = (
                sorted_returns[var_99_idx] if var_99_idx < len(sorted_returns) else 0.0
            )
        else:
            volatility = 0.0
            var_95 = 0.0
            var_99 = 0.0

        return {
            "max_drawdown": max_drawdown,
            "current_drawdown": current_drawdown,
            "volatility": volatility,
            "var_95": var_95,
            "var_99": var_99,
        }

    def _plot_equity_curve(
        self, equity_curve: list[dict[str, Any]], config: dict[str, Any]
    ) -> Path:
        """Plot equity curve and save to file.

        Args:
            equity_curve: List of equity curve points
            config: Backtest configuration

        Returns:
            Path to saved plot file
        """
        if not equity_curve:
            return None

        # Extract data
        timestamps = [
            datetime.fromisoformat(point["timestamp"]) for point in equity_curve
        ]
        equity_values = [point["equity"] for point in equity_curve]

        # Create plot
        plt.figure(figsize=(12, 8))

        # Plot equity curve
        plt.subplot(2, 1, 1)
        plt.plot(timestamps, equity_values, "b-", linewidth=2, label="Portfolio Equity")
        plt.axhline(
            y=config["initial_capital"],
            color="r",
            linestyle="--",
            alpha=0.7,
            label="Initial Capital",
        )
        plt.title(
            f'Equity Curve - {", ".join(config["symbols"])} ({config["start_date"]} to {config["end_date"]})'
        )
        plt.ylabel("Portfolio Value ($)")
        plt.legend()
        plt.grid(True, alpha=0.3)

        # Format x-axis
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=7))
        plt.xticks(rotation=45)

        # Plot drawdown
        plt.subplot(2, 1, 2)
        peak = equity_values[0]
        drawdowns = []
        for equity in equity_values:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * 100
            drawdowns.append(drawdown)

        plt.fill_between(
            timestamps, drawdowns, 0, color="red", alpha=0.3, label="Drawdown"
        )
        plt.plot(timestamps, drawdowns, "r-", linewidth=1)
        plt.title("Drawdown (%)")
        plt.ylabel("Drawdown (%)")
        plt.xlabel("Date")
        plt.legend()
        plt.grid(True, alpha=0.3)

        # Format x-axis
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=7))
        plt.xticks(rotation=45)

        # Adjust layout
        plt.tight_layout()

        # Save plot
        plot_path = (
            self.output_dir
            / f"equity_curve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        plt.savefig(plot_path, dpi=300, bbox_inches="tight")
        plt.close()

        self.logger.info(f"Equity curve plot saved to: {plot_path}")

        return plot_path

    def save_detailed_results(self, backtest_results: dict[str, Any]) -> Path:
        """Save detailed backtest results to JSON.

        Args:
            backtest_results: Complete backtest results

        Returns:
            Path to saved file
        """
        results_path = (
            self.output_dir
            / f"backtest_detailed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(results_path, "w") as f:
            json.dump(backtest_results, f, indent=2, default=str)

        self.logger.info(f"Detailed results saved to: {results_path}")

        return results_path

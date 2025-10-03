"""
Backtesting module for the Crypto MVP application.
"""

import asyncio

from .engine import BacktestEngine
from .report import BacktestReport

__all__ = [
    "BacktestEngine",
    "BacktestReport",
    "run_backtest",
]


def run_backtest(
    config_path: str, symbols: list, timeframe: str, start: str, end: str
) -> dict:
    """
    Run a backtest with the specified parameters.

    Args:
        config_path: Path to configuration file
        symbols: List of trading symbols
        timeframe: Data timeframe (e.g., '1h', '1d')
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)

    Returns:
        Dictionary containing backtest results and metrics
    """
    # Initialize backtest engine
    engine = BacktestEngine(config_path)

    # Run backtest
    results = asyncio.run(engine.run_backtest(symbols, timeframe, start, end))

    # Generate report
    report_generator = BacktestReport()
    summary = report_generator.generate_report(results)

    # Add summary to results
    results["summary"] = summary

    return results

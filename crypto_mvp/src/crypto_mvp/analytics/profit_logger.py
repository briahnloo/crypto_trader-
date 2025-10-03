"""
Profit-focused logger for trading cycles and daily summaries.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import pytz

from ..core.logging_utils import LoggerMixin


class ProfitLogger(LoggerMixin):
    """
    Profit-focused logger for comprehensive trading cycle and daily summary logging.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize the profit logger.

        Args:
            config: Logging configuration dictionary
        """
        super().__init__()
        self.config = config

        # Logging configuration
        self.log_level = self.config.get("log_level", "INFO")
        self.log_file = self.config.get("log_file", "profit_logs.json")
        self.console_output = self.config.get("console_output", True)
        self.emoji_enabled = self.config.get("emoji_enabled", True)
        self.detailed_logging = self.config.get("detailed_logging", True)

        # Log storage
        self.trading_cycles: list[dict[str, Any]] = []
        self.daily_summaries: list[dict[str, Any]] = []

        # Performance tracking
        self.current_equity = self.config.get("initial_equity", 100000.0)
        self.peak_equity = self.current_equity
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0

        # Daily rollover tracking
        self.timezone = self.config.get("timezone", "UTC")
        self.daily_start_equity = self.current_equity
        self.daily_start_time = datetime.now(timezone.utc)
        self.previous_equity = self.current_equity
        self.last_daily_reset = datetime.now(timezone.utc).date()
        self.daily_trades = 0
        self.daily_winning_trades = 0
        self.daily_losing_trades = 0
        self.daily_pnl = 0.0

        self.initialized = False

    def initialize(self) -> None:
        """Initialize the profit logger."""
        if self.initialized:
            self.logger.info("ProfitLogger already initialized")
            return

        self.logger.info("Initializing ProfitLogger")
        self.logger.info(f"Log level: {self.log_level}")
        self.logger.info(f"Log file: {self.log_file}")
        self.logger.info(f"Console output: {self.console_output}")
        self.logger.info(f"Emoji enabled: {self.emoji_enabled}")

        # Load existing logs if available
        self._load_logs()

        self.initialized = True

    def _check_daily_rollover(self, current_time: Optional[datetime] = None) -> bool:
        """Check if a daily rollover has occurred and handle it.
        
        Args:
            current_time: Current time to check against (defaults to now)
            
        Returns:
            True if a rollover occurred, False otherwise
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Convert to configured timezone
        try:
            tz = pytz.timezone(self.timezone)
            current_time_tz = current_time.astimezone(tz)
            current_date = current_time_tz.date()
        except Exception:
            # Fallback to UTC if timezone is invalid
            current_date = current_time.date()
        
        # Check if we've crossed a day boundary
        if current_date > self.last_daily_reset:
            self.logger.info(f"Daily rollover detected: {self.last_daily_reset} -> {current_date}")
            
            # Generate daily summary for the previous day
            self._generate_daily_summary()
            
            # Reset daily tracking variables
            self.daily_start_equity = self.current_equity
            self.daily_start_time = current_time
            self.daily_trades = 0
            self.daily_winning_trades = 0
            self.daily_losing_trades = 0
            self.daily_pnl = 0.0
            self.last_daily_reset = current_date
            
            return True
        
        return False

    def _generate_daily_summary(self) -> None:
        """Generate and log a daily summary for the previous day."""
        try:
            # Calculate daily metrics
            daily_return = (self.current_equity - self.daily_start_equity) / self.daily_start_equity * 100 if self.daily_start_equity > 0 else 0.0
            
            # Calculate win rate for the day
            daily_win_rate = self.daily_winning_trades / self.daily_trades if self.daily_trades > 0 else 0.0
            
            # Calculate profit factor for the day
            daily_profit_factor = float('inf') if self.daily_losing_trades == 0 and self.daily_winning_trades > 0 else 0.0
            if self.daily_losing_trades > 0:
                # Simplified profit factor calculation
                daily_profit_factor = self.daily_winning_trades / self.daily_losing_trades
            
            # Calculate Sharpe ratio (simplified)
            daily_sharpe = 0.0
            if self.daily_trades > 0:
                # Use a simplified Sharpe calculation
                daily_sharpe = daily_return / max(1.0, abs(daily_return) * 0.1) if daily_return != 0 else 0.0
            
            # Calculate max drawdown for the day (simplified)
            daily_max_drawdown = 0.0
            if self.daily_start_equity > 0:
                daily_max_drawdown = max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)
            
            # Create daily summary data
            daily_data = {
                "date": self.last_daily_reset,
                "timestamp": self.daily_start_time,
                "performance": {
                    "win_rate": daily_win_rate,
                    "sharpe_ratio": daily_sharpe,
                    "max_drawdown": daily_max_drawdown,
                    "total_return": daily_return / 100.0,  # Convert percentage to decimal
                    "profit_factor": daily_profit_factor,
                },
                "trading_activity": {
                    "total_trades": self.daily_trades,
                    "winning_trades": self.daily_winning_trades,
                    "losing_trades": self.daily_losing_trades,
                    "total_volume": 0.0,  # Would need to track this separately
                    "total_fees": 0.0,    # Would need to track this separately
                },
                "equity": {
                    "start_equity": self.daily_start_equity,
                    "end_equity": self.current_equity,
                    "peak_equity": self.peak_equity,
                },
                "risk_metrics": {
                    "current_drawdown": daily_max_drawdown,
                    "volatility": 0.02,  # Default volatility
                    "var_95": 0.03,      # Default VaR
                },
                "strategy_performance": {},  # Would need to track per-strategy metrics
                "metadata": {
                    "timezone": self.timezone,
                    "rollover_type": "automatic",
                },
            }
            
            # Log the daily summary
            self.log_daily_summary(daily_data)
            
        except Exception as e:
            self.logger.error(f"Failed to generate daily summary: {e}")

    def log_trading_cycle(self, cycle_data: dict[str, Any]) -> None:
        """Log a complete trading cycle with comprehensive data.

        Args:
            cycle_data: Dictionary containing cycle information
        """
        if not self.initialized:
            self.initialize()

        # Check for daily rollover first
        cycle_timestamp = cycle_data.get("timestamp", datetime.now())
        if isinstance(cycle_timestamp, str):
            try:
                cycle_timestamp = datetime.fromisoformat(cycle_timestamp.replace('Z', '+00:00'))
            except:
                cycle_timestamp = datetime.now(timezone.utc)
        
        self._check_daily_rollover(cycle_timestamp)

        # Extract cycle data
        cycle_id = cycle_data.get("cycle_id", f"cycle_{len(self.trading_cycles) + 1}")
        timestamp = cycle_timestamp
        symbol = cycle_data.get("symbol", "UNKNOWN")
        strategy = cycle_data.get("strategy", "UNKNOWN")

        # Equity and P&L data
        equity_data = cycle_data.get("equity", {})
        current_equity = equity_data.get("current_equity", self.current_equity)
        previous_equity = equity_data.get("previous_equity", self.current_equity)
        cycle_pnl = current_equity - previous_equity

        # Position data
        positions = cycle_data.get("positions", {})
        position_count = len(positions)
        total_position_value = sum(pos.get("value", 0) for pos in positions.values())

        # Decision data
        decisions = cycle_data.get("decisions", {})
        decision_count = len(decisions)
        risk_score = decisions.get("risk_score", 0.0)
        confidence = decisions.get("confidence", 0.0)

        # Trade data
        trades = cycle_data.get("trades", [])
        trade_count = len(trades)
        total_trade_volume = sum(trade.get("volume", 0) for trade in trades)
        total_fees = sum(trade.get("fees", 0) for trade in trades)

        # Create cycle log entry
        cycle_log = {
            "cycle_id": cycle_id,
            "timestamp": timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else str(timestamp),
            "symbol": symbol,
            "strategy": strategy,
            "equity": {
                "current_equity": current_equity,
                "previous_equity": previous_equity,
                "cycle_pnl": cycle_pnl,
                "equity_change_pct": (cycle_pnl / previous_equity * 100)
                if previous_equity > 0
                else 0.0,
            },
            "positions": {
                "count": position_count,
                "total_value": total_position_value,
                "details": positions,
            },
            "decisions": {
                "count": decision_count,
                "risk_score": risk_score,
                "confidence": confidence,
                "details": decisions,
            },
            "trades": {
                "count": trade_count,
                "total_volume": total_trade_volume,
                "total_fees": total_fees,
                "details": trades,
            },
            "metadata": cycle_data.get("metadata", {}),
        }

        # Add to cycle logs
        self.trading_cycles.append(cycle_log)

        # Update performance tracking
        self.current_equity = current_equity
        self.previous_equity = previous_equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        self.total_trades += trade_count
        self.total_pnl += cycle_pnl

        # Update daily tracking
        self.daily_trades += trade_count
        self.daily_pnl += cycle_pnl

        # Count winning/losing trades
        for trade in trades:
            trade_pnl = trade.get("pnl", 0)
            if trade_pnl > 0:
                self.winning_trades += 1
                self.daily_winning_trades += 1
            elif trade_pnl < 0:
                self.losing_trades += 1
                self.daily_losing_trades += 1

        # Log to console with emojis and formatting
        if self.console_output:
            self._log_cycle_to_console(cycle_log)

        # Save logs
        self._save_logs()

        self.logger.info(
            f"Logged trading cycle: {cycle_id} for {symbol} using {strategy}"
        )

    def log_daily_summary(self, daily_data: dict[str, Any]) -> None:
        """Log daily summary with key performance metrics.

        Args:
            daily_data: Dictionary containing daily summary information
        """
        if not self.initialized:
            self.initialize()

        # Extract daily data
        date = daily_data.get("date", datetime.now().date())
        timestamp = daily_data.get("timestamp", datetime.now())

        # Performance metrics
        performance = daily_data.get("performance", {})
        win_rate = performance.get("win_rate", 0.0)
        sharpe_ratio = performance.get("sharpe_ratio", 0.0)
        max_drawdown = performance.get("max_drawdown", 0.0)
        total_return = performance.get("total_return", 0.0)
        profit_factor = performance.get("profit_factor", 0.0)

        # Trading activity
        trading_activity = daily_data.get("trading_activity", {})
        total_trades = trading_activity.get("total_trades", 0)
        winning_trades = trading_activity.get("winning_trades", 0)
        losing_trades = trading_activity.get("losing_trades", 0)
        total_volume = trading_activity.get("total_volume", 0.0)
        total_fees = trading_activity.get("total_fees", 0.0)

        # Equity data
        equity_data = daily_data.get("equity", {})
        start_equity = equity_data.get("start_equity", self.current_equity)
        end_equity = equity_data.get("end_equity", self.current_equity)
        daily_pnl = end_equity - start_equity

        # Risk metrics
        risk_metrics = daily_data.get("risk_metrics", {})
        current_drawdown = risk_metrics.get("current_drawdown", 0.0)
        volatility = risk_metrics.get("volatility", 0.0)
        var_95 = risk_metrics.get("var_95", 0.0)

        # Strategy performance
        strategy_performance = daily_data.get("strategy_performance", {})

        # Create daily summary log entry
        daily_log = {
            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
            "timestamp": timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else str(timestamp),
            "performance": {
                "win_rate": win_rate,
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown": max_drawdown,
                "total_return": total_return,
                "profit_factor": profit_factor,
                "daily_pnl": daily_pnl,
                "daily_return": (daily_pnl / start_equity * 100)
                if start_equity > 0
                else 0.0,
            },
            "trading_activity": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "total_volume": total_volume,
                "total_fees": total_fees,
                "avg_trade_size": total_volume / total_trades
                if total_trades > 0
                else 0.0,
            },
            "equity": {
                "start_equity": start_equity,
                "end_equity": end_equity,
                "daily_pnl": daily_pnl,
                "peak_equity": self.peak_equity,
            },
            "risk_metrics": {
                "current_drawdown": current_drawdown,
                "volatility": volatility,
                "var_95": var_95,
            },
            "strategy_performance": strategy_performance,
            "metadata": daily_data.get("metadata", {}),
        }

        # Add to daily summaries
        self.daily_summaries.append(daily_log)

        # Log to console with emojis and formatting
        if self.console_output:
            self._log_daily_summary_to_console(daily_log)

        # Save logs
        self._save_logs()

        self.logger.info(f"Logged daily summary for {date}")

    def _log_cycle_to_console(self, cycle_log: dict[str, Any]) -> None:
        """Log trading cycle to console with emojis and formatting.

        Args:
            cycle_log: Cycle log data
        """
        if not self.emoji_enabled:
            return

        print("\n" + "=" * 80)
        print(f"🔄 TRADING CYCLE: {cycle_log['cycle_id']}")
        print("=" * 80)

        # Basic info
        print(f"📅 Time: {cycle_log['timestamp']}")
        print(f"💰 Symbol: {cycle_log['symbol']}")
        print(f"🎯 Strategy: {cycle_log['strategy']}")

        # Equity section
        equity = cycle_log["equity"]
        pnl_emoji = "📈" if equity["cycle_pnl"] >= 0 else "📉"
        print("\n💎 EQUITY:")
        print(f"   {pnl_emoji} Current: ${equity['current_equity']:,.2f}")
        print(f"   📊 Previous: ${equity['previous_equity']:,.2f}")
        print(
            f"   💰 P&L: ${equity['cycle_pnl']:,.2f} ({equity['equity_change_pct']:+.2f}%)"
        )

        # Positions section
        positions = cycle_log["positions"]
        print("\n📋 POSITIONS:")
        print(f"   🔢 Count: {positions['count']}")
        print(f"   💵 Total Value: ${positions['total_value']:,.2f}")

        if self.detailed_logging and positions["details"]:
            for symbol, pos in positions["details"].items():
                print(
                    f"   📊 {symbol}: {pos.get('quantity', 0):.4f} @ ${pos.get('price', 0):.2f}"
                )

        # Decisions section
        decisions = cycle_log["decisions"]
        confidence_emoji = (
            "🟢"
            if decisions["confidence"] > 0.7
            else "🟡"
            if decisions["confidence"] > 0.4
            else "🔴"
        )
        risk_emoji = (
            "🟢"
            if decisions["risk_score"] < 0.3
            else "🟡"
            if decisions["risk_score"] < 0.7
            else "🔴"
        )

        print("\n🧠 DECISIONS:")
        print(f"   🔢 Count: {decisions['count']}")
        print(f"   {confidence_emoji} Confidence: {decisions['confidence']:.1%}")
        print(f"   {risk_emoji} Risk Score: {decisions['risk_score']:.1%}")

        if self.detailed_logging and decisions["details"]:
            for key, value in decisions["details"].items():
                if key not in ["risk_score", "confidence"]:
                    print(f"   📝 {key}: {value}")

        # Trades section
        trades = cycle_log["trades"]
        print("\n💼 TRADES:")
        print(f"   🔢 Count: {trades['count']}")
        print(f"   📊 Volume: ${trades['total_volume']:,.2f}")
        print(f"   💸 Fees: ${trades['total_fees']:,.2f}")

        if self.detailed_logging and trades["details"]:
            for i, trade in enumerate(trades["details"]):
                side_emoji = "🟢" if trade.get("side") == "buy" else "🔴"
                pnl_emoji = "📈" if trade.get("pnl", 0) >= 0 else "📉"
                print(
                    f"   {side_emoji} Trade {i+1}: {trade.get('side', 'N/A')} {trade.get('quantity', 0):.4f} @ ${trade.get('price', 0):.2f}"
                )
                print(f"      {pnl_emoji} P&L: ${trade.get('pnl', 0):,.2f}")

        print("=" * 80)

    def _log_daily_summary_to_console(self, daily_log: dict[str, Any]) -> None:
        """Log daily summary to console with emojis and formatting.

        Args:
            daily_log: Daily log data
        """
        if not self.emoji_enabled:
            return

        print("\n" + "=" * 80)
        print(f"📊 DAILY SUMMARY: {daily_log['date']}")
        print("=" * 80)

        # Performance section
        perf = daily_log["performance"]
        win_rate_emoji = (
            "🟢" if perf["win_rate"] > 0.6 else "🟡" if perf["win_rate"] > 0.4 else "🔴"
        )
        sharpe_emoji = (
            "🟢"
            if perf["sharpe_ratio"] > 1.0
            else "🟡"
            if perf["sharpe_ratio"] > 0.0
            else "🔴"
        )
        dd_emoji = (
            "🟢"
            if perf["max_drawdown"] < 0.05
            else "🟡"
            if perf["max_drawdown"] < 0.15
            else "🔴"
        )
        pnl_emoji = "📈" if perf["daily_pnl"] >= 0 else "📉"

        print("\n📈 PERFORMANCE:")
        print(f"   {win_rate_emoji} Win Rate: {perf['win_rate']:.1%}")
        print(f"   {sharpe_emoji} Sharpe Ratio: {perf['sharpe_ratio']:.3f}")
        print(f"   {dd_emoji} Max Drawdown: {perf['max_drawdown']:.1%}")
        print(f"   💰 Total Return: {perf['total_return']:.1%}")
        print(f"   📊 Profit Factor: {perf['profit_factor']:.2f}")
        print(
            f"   {pnl_emoji} Daily P&L: ${perf['daily_pnl']:,.2f} ({perf['daily_return']:+.2f}%)"
        )

        # Trading activity section
        activity = daily_log["trading_activity"]
        print("\n💼 TRADING ACTIVITY:")
        print(f"   🔢 Total Trades: {activity['total_trades']}")
        print(f"   🟢 Winning Trades: {activity['winning_trades']}")
        print(f"   🔴 Losing Trades: {activity['losing_trades']}")
        print(f"   📊 Total Volume: ${activity['total_volume']:,.2f}")
        print(f"   💸 Total Fees: ${activity['total_fees']:,.2f}")
        print(f"   📏 Avg Trade Size: ${activity['avg_trade_size']:,.2f}")

        # Equity section
        equity = daily_log["equity"]
        print("\n💎 EQUITY:")
        print(f"   🌅 Start: ${equity['start_equity']:,.2f}")
        print(f"   🌆 End: ${equity['end_equity']:,.2f}")
        print(f"   📈 Peak: ${equity['peak_equity']:,.2f}")

        # Risk metrics section
        risk = daily_log["risk_metrics"]
        print("\n⚠️  RISK METRICS:")
        print(f"   📉 Current Drawdown: {risk['current_drawdown']:.1%}")
        print(f"   📊 Volatility: {risk['volatility']:.1%}")
        print(f"   🎯 VaR (95%): {risk['var_95']:.1%}")

        # Strategy performance section
        if daily_log["strategy_performance"]:
            print("\n🎯 STRATEGY PERFORMANCE:")
            for strategy, perf in daily_log["strategy_performance"].items():
                strategy_emoji = "🟢" if perf.get("pnl", 0) > 0 else "🔴"
                print(
                    f"   {strategy_emoji} {strategy}: {perf.get('trades', 0)} trades, ${perf.get('pnl', 0):,.2f} P&L"
                )

        print("=" * 80)

    def _save_logs(self) -> None:
        """Save logs to file."""
        try:
            log_data = {
                "trading_cycles": self.trading_cycles,
                "daily_summaries": self.daily_summaries,
                "performance_summary": {
                    "current_equity": self.current_equity,
                    "peak_equity": self.peak_equity,
                    "total_trades": self.total_trades,
                    "winning_trades": self.winning_trades,
                    "losing_trades": self.losing_trades,
                    "total_pnl": self.total_pnl,
                },
                "daily_rollover_state": {
                    "timezone": self.timezone,
                    "daily_start_equity": self.daily_start_equity,
                    "daily_start_time": self.daily_start_time.isoformat(),
                    "previous_equity": self.previous_equity,
                    "last_daily_reset": self.last_daily_reset.isoformat(),
                    "daily_trades": self.daily_trades,
                    "daily_winning_trades": self.daily_winning_trades,
                    "daily_losing_trades": self.daily_losing_trades,
                    "daily_pnl": self.daily_pnl,
                },
                "last_updated": datetime.now().isoformat(),
            }

            with open(self.log_file, "w") as f:
                json.dump(log_data, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to save logs: {e}")

    def _load_logs(self) -> None:
        """Load logs from file."""
        try:
            with open(self.log_file) as f:
                log_data = json.load(f)

            self.trading_cycles = log_data.get("trading_cycles", [])
            self.daily_summaries = log_data.get("daily_summaries", [])

            # Restore performance summary
            perf_summary = log_data.get("performance_summary", {})
            self.current_equity = perf_summary.get(
                "current_equity", self.current_equity
            )
            self.peak_equity = perf_summary.get("peak_equity", self.peak_equity)
            self.total_trades = perf_summary.get("total_trades", 0)
            self.winning_trades = perf_summary.get("winning_trades", 0)
            self.losing_trades = perf_summary.get("losing_trades", 0)
            self.total_pnl = perf_summary.get("total_pnl", 0.0)

            # Restore daily rollover state
            rollover_state = log_data.get("daily_rollover_state", {})
            if rollover_state:
                self.timezone = rollover_state.get("timezone", self.timezone)
                self.daily_start_equity = rollover_state.get("daily_start_equity", self.current_equity)
                self.previous_equity = rollover_state.get("previous_equity", self.current_equity)
                self.daily_trades = rollover_state.get("daily_trades", 0)
                self.daily_winning_trades = rollover_state.get("daily_winning_trades", 0)
                self.daily_losing_trades = rollover_state.get("daily_losing_trades", 0)
                self.daily_pnl = rollover_state.get("daily_pnl", 0.0)
                
                # Parse datetime fields
                try:
                    daily_start_time_str = rollover_state.get("daily_start_time")
                    if daily_start_time_str:
                        self.daily_start_time = datetime.fromisoformat(daily_start_time_str.replace('Z', '+00:00'))
                    
                    last_reset_str = rollover_state.get("last_daily_reset")
                    if last_reset_str:
                        self.last_daily_reset = datetime.fromisoformat(last_reset_str).date()
                except Exception as e:
                    self.logger.warning(f"Failed to parse datetime fields from rollover state: {e}")
                    # Reset to current time
                    self.daily_start_time = datetime.now(timezone.utc)
                    self.last_daily_reset = datetime.now(timezone.utc).date()

            self.logger.info(
                f"Loaded {len(self.trading_cycles)} trading cycles and {len(self.daily_summaries)} daily summaries"
            )

        except FileNotFoundError:
            self.logger.info(f"No existing log file found at {self.log_file}")
        except Exception as e:
            self.logger.error(f"Failed to load logs: {e}")

    def get_trading_cycles(self) -> list[dict[str, Any]]:
        """Get all trading cycles.

        Returns:
            List of trading cycle logs
        """
        return self.trading_cycles.copy()

    def get_daily_summaries(self) -> list[dict[str, Any]]:
        """Get all daily summaries.

        Returns:
            List of daily summary logs
        """
        return self.daily_summaries.copy()

    def get_performance_summary(self) -> dict[str, Any]:
        """Get overall performance summary.

        Returns:
            Performance summary dictionary
        """
        return {
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": self.total_pnl,
            "win_rate": self.winning_trades / self.total_trades
            if self.total_trades > 0
            else 0.0,
            "total_cycles": len(self.trading_cycles),
            "total_days": len(self.daily_summaries),
        }

    def force_daily_rollover(self) -> None:
        """Manually trigger a daily rollover and generate summary."""
        self.logger.info("Manual daily rollover triggered")
        self._generate_daily_summary()
        
        # Reset daily tracking variables
        self.daily_start_equity = self.current_equity
        self.daily_start_time = datetime.now(timezone.utc)
        self.daily_trades = 0
        self.daily_winning_trades = 0
        self.daily_losing_trades = 0
        self.daily_pnl = 0.0
        self.last_daily_reset = datetime.now(timezone.utc).date()
        
        self.logger.info("Daily rollover completed and baseline reset")

    def clear_logs(self) -> None:
        """Clear all logs."""
        self.trading_cycles.clear()
        self.daily_summaries.clear()
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.current_equity = self.config.get("initial_equity", 100000.0)
        self.peak_equity = self.current_equity
        
        # Reset daily rollover state
        self.daily_start_equity = self.current_equity
        self.daily_start_time = datetime.now(timezone.utc)
        self.previous_equity = self.current_equity
        self.last_daily_reset = datetime.now(timezone.utc).date()
        self.daily_trades = 0
        self.daily_winning_trades = 0
        self.daily_losing_trades = 0
        self.daily_pnl = 0.0

        self.logger.info("All logs cleared")

    def update_config(self, new_config: dict[str, Any]) -> None:
        """Update logging configuration.

        Args:
            new_config: New configuration parameters
        """
        self.config.update(new_config)

        # Update instance variables
        self.log_level = self.config.get("log_level", self.log_level)
        self.log_file = self.config.get("log_file", self.log_file)
        self.console_output = self.config.get("console_output", self.console_output)
        self.emoji_enabled = self.config.get("emoji_enabled", self.emoji_enabled)
        self.detailed_logging = self.config.get(
            "detailed_logging", self.detailed_logging
        )

        self.logger.info("Configuration updated")

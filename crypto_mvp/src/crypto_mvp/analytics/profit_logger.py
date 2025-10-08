"""
Profit-focused logger for trading cycles and daily summaries.

NOTE: log_trading_cycle() and log_daily_summary() methods have been 
replaced by consolidated logging in trading_system.py
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import pytz

from ..core.logging_utils import LoggerMixin
from ..core.utils import get_mark_price, validate_mark_price


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
        
        # Session tracking
        self.session_id = None
        self.previous_equity = self.current_equity
        self.last_daily_reset = datetime.now(timezone.utc).date()
        self.daily_trades = 0
        self.daily_winning_trades = 0
        self.daily_losing_trades = 0
        self.daily_pnl = 0.0

        # Session tracking
        self.session_start_time = datetime.now(timezone.utc)
        self.session_start_equity = self.current_equity
        self.is_continuing_session = False
        self.session_id = f"session_{int(self.session_start_time.timestamp())}"

        self.initialized = False
        
        # Trade ledger reference (will be set by trading system)
        self.trade_ledger = None

    def set_trade_ledger(self, trade_ledger) -> None:
        """Set the trade ledger reference for single source of truth.
        
        Args:
            trade_ledger: TradeLedger instance
        """
        self.trade_ledger = trade_ledger
        self.logger.info("Trade ledger set for single source of truth")

    def get_metrics_from_ledger(self, session_id: str = None) -> dict[str, Any]:
        """Get all metrics from trade ledger as single source of truth with fallback to in-memory fills.
        
        Args:
            session_id: Session ID to filter by (optional)
            
        Returns:
            Dictionary with all metrics from committed trades only
        """
        if not self.trade_ledger:
            self.logger.warning("No trade ledger available, returning empty metrics")
            return {
                "total_trades": 0,
                "trade_count": 0,  # Number of fills
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "buy_trades": 0,
                "sell_trades": 0,
                "symbols_traded": [],
                "strategies_used": [],
                "win_rate": 0.0,
                "avg_trade_size": 0.0,
                "largest_trade": 0.0,
                "smallest_trade": 0.0
            }
        
        try:
            # Get daily metrics from ledger (committed trades only)
            if session_id:
                # Get session-specific metrics
                daily_metrics = self.trade_ledger.calculate_daily_metrics(
                    date=None,  # All dates
                    session_id=session_id
                )
            else:
                # Get all-time metrics
                daily_metrics = self.trade_ledger.calculate_daily_metrics()
            
            # Check if ledger returned empty results but we have in-memory fills
            if (daily_metrics.get("total_trades", 0) == 0 and 
                hasattr(self, 'trading_system') and 
                self.trading_system and 
                hasattr(self.trading_system, 'in_memory_fills') and 
                self.trading_system.in_memory_fills):
                
                # Use fallback to in-memory fills
                self.logger.info("Ledger empty but in-memory fills exist, using fallback metrics")
                fallback_metrics = self.trading_system.get_metrics_from_in_memory_fills(session_id)
                
                # Log the fallback usage
                self.logger.info(f"FALLBACK_METRICS: trades={fallback_metrics.get('total_trades', 0)} "
                               f"volume=${fallback_metrics.get('total_volume', 0):.2f} "
                               f"fees=${fallback_metrics.get('total_fees', 0):.2f}")
                
                return fallback_metrics
            
            return daily_metrics
            
        except Exception as e:
            self.logger.error(f"Error getting metrics from ledger: {e}")
            
            # Try fallback to in-memory fills on error
            if (hasattr(self, 'trading_system') and 
                self.trading_system and 
                hasattr(self.trading_system, 'in_memory_fills') and 
                self.trading_system.in_memory_fills):
                
                self.logger.info("Ledger error, using fallback to in-memory fills")
                fallback_metrics = self.trading_system.get_metrics_from_in_memory_fills(session_id)
                
                # Log the fallback usage
                self.logger.info(f"FALLBACK_METRICS: trades={fallback_metrics.get('total_trades', 0)} "
                               f"volume=${fallback_metrics.get('total_volume', 0):.2f} "
                               f"fees=${fallback_metrics.get('total_fees', 0):.2f}")
                
                return fallback_metrics
            
            return {
                "total_trades": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "buy_trades": 0,
                "sell_trades": 0,
                "symbols_traded": [],
                "strategies_used": [],
                "win_rate": 0.0,
                "avg_trade_size": 0.0,
                "largest_trade": 0.0,
                "smallest_trade": 0.0
            }

    def _get_trading_activity_from_ledger(self) -> dict[str, Any]:
        """Get trading activity metrics from trade ledger as single source of truth.
        
        Returns:
            Dictionary with trading activity metrics from committed trades only
        """
        ledger_metrics = self.get_metrics_from_ledger(self.session_id)
        
        return {
            "total_trades": ledger_metrics.get("total_trades", 0),
            "winning_trades": self.daily_winning_trades,  # Keep local P&L tracking
            "losing_trades": self.daily_losing_trades,    # Keep local P&L tracking
            "total_volume": ledger_metrics.get("total_volume", 0.0),
            "total_fees": ledger_metrics.get("total_fees", 0.0),
            "avg_trade_size": ledger_metrics.get("avg_trade_size", 0.0),
        }

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initialize the profit logger for a specific session.
        
        Args:
            session_id: Session identifier for session-scoped logging
        """
        if self.initialized:
            self.logger.info("ProfitLogger already initialized")
            return

        self.session_id = session_id
        self.logger.info("Initializing ProfitLogger")
        self.logger.info(f"Log level: {self.log_level}")
        
        if session_id:
            # Reset logger state for new session
            session_initial_equity = self.config.get("initial_equity", 100000.0)
            self.current_equity = session_initial_equity
            self.peak_equity = session_initial_equity  # Reset peak to session start
            self.total_trades = 0
            self.winning_trades = 0
            self.losing_trades = 0
            self.total_pnl = 0.0
            self.daily_start_equity = session_initial_equity
            self.daily_start_time = datetime.now(timezone.utc)
            self.daily_trades = 0
            self.daily_winning_trades = 0
            self.daily_losing_trades = 0
            
            # Reset session tracking
            self.session_start_equity = session_initial_equity
            self.is_continuing_session = False
            
            self.log_file = f"profit_logs_{session_id}.json"
            self.logger.info(f"Session ID: {session_id}")
            self.logger.info(f"Session initial equity: ${self.current_equity:,.2f}")
        
        self.logger.info(f"Log file: {self.log_file}")
        self.logger.info(f"Console output: {self.console_output}")
        self.logger.info(f"Emoji enabled: {self.emoji_enabled}")

        # Load existing logs if available (session-scoped)
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
            
            # Reset analytics daily counters
            if hasattr(self, 'profit_analytics') and self.profit_analytics:
                self.profit_analytics.reset_daily_counters()
            self.daily_winning_trades = 0
            self.daily_losing_trades = 0
            self.daily_pnl = 0.0
            self.last_daily_reset = current_date
            
            # Reset exploration budget counters for new day
            if hasattr(self, 'state_store') and self.state_store:
                try:
                    # Reset exploration counters to 0 for new day
                    self.state_store.set_session_metadata(
                        self.session_id, "exploration_used_notional_today", 0.0
                    )
                    self.state_store.set_session_metadata(
                        self.session_id, "exploration_forced_count_today", 0
                    )
                    self.logger.info("Daily reset: exploration budget counters reset to 0")
                except Exception as e:
                    self.logger.warning(f"Failed to reset exploration counters: {e}")
            
            return True
        
        return False

    # DEPRECATED: This method has been replaced by consolidated logging in trading_system.py
    # def _generate_daily_summary(self) -> None:
    #     """Generate and log a daily summary for the previous day."""
    #     # Initialize daily_summary_data with safe defaults BEFORE any try/except
    #     daily_summary_data = {
    #         "date": self.last_daily_reset or "unknown",
    #         "timestamp": datetime.now().isoformat(),
    #         "session_info": {
    #             "session_id": self.session_id or "unknown",
    #             "session_start_time": self.session_start_time or datetime.now().isoformat(),
    #             "is_continuing_session": self.is_continuing_session,
    #             "session_start_equity": self.session_start_equity or 0.0,
    #         },
    #         "performance": {
    #             "win_rate": 0.0,
    #             "sharpe_ratio": 0.0,
    #             "max_drawdown": 0.0,
    #             "total_return": 0.0,
    #             "profit_factor": 0.0,
    #             "daily_pnl": 0.0,
    #             "daily_return": 0.0,
    #         },
    #         "trading_activity": {
    #             "total_trades": 0,
    #             "winning_trades": 0,
    #             "losing_trades": 0,
    #             "total_volume": 0.0,
    #             "total_fees": 0.0,
    #             "avg_trade_size": 0.0,
    #         },
    #         "equity": {
    #             "start_equity": self.session_start_equity or 0.0,
    #             "end_equity": self.current_equity or 0.0,
    #             "peak_equity": self.peak_equity or 0.0,
    #         },
    #         "risk_metrics": {
    #             "current_drawdown": 0.0,
    #             "volatility": 0.02,
    #             "var_95": 0.03,
    #         },
    #         "strategy_performance": {},
    #         "metadata": {
    #             "timezone": self.timezone,
    #             "rollover_type": "error_fallback",
    #         },
    #     }
    #     
    #     try:
    #         # Calculate daily metrics
    #         daily_return = (self.current_equity - self.daily_start_equity) / self.daily_start_equity * 100 if self.daily_start_equity > 0 else 0.0
    #         
    #         # Calculate win rate for the day
    #         daily_win_rate = self.daily_winning_trades / self.daily_trades if self.daily_trades > 0 else 0.0
    #         
    #         # Calculate profit factor for the day
    #         daily_profit_factor = float('inf') if self.daily_losing_trades == 0 and self.daily_winning_trades > 0 else 0.0
    #         if self.daily_losing_trades > 0:
    #             # Simplified profit factor calculation
    #             daily_profit_factor = self.daily_winning_trades / self.daily_losing_trades
    #         
    #         # Calculate Sharpe ratio (simplified)
    #         daily_sharpe = 0.0
    #         if self.daily_trades > 0:
    #             # Use a simplified Sharpe calculation
    #             daily_sharpe = daily_return / max(1.0, abs(daily_return) * 0.1) if daily_return != 0 else 0.0
    #         
    #         # Calculate max drawdown for the day (simplified)
    #         daily_max_drawdown = 0.0
    #         if self.daily_start_equity > 0:
    #             daily_max_drawdown = max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)
    #         
    #         # Update daily_summary_data with calculated values
    #         daily_summary_data.update({
    #             "date": self.last_daily_reset,
    #             "timestamp": self.daily_start_time,
    #             "session_info": {
    #                 "session_id": self.session_id,
    #                 "session_start_time": self.session_start_time,
    #                 "is_continuing_session": self.is_continuing_session,
    #                 "session_start_equity": self.session_start_equity,
    #             },
    #             "performance": {
    #                 "win_rate": daily_win_rate,
    #                 "sharpe_ratio": daily_sharpe,
    #                 "max_drawdown": daily_max_drawdown,
    #                 "total_return": daily_return / 100.0,  # Convert percentage to decimal
    #                 "profit_factor": daily_profit_factor,
    #                 "daily_pnl": self.daily_pnl,
    #                 "daily_return": daily_return,
    #             },
    #             "trading_activity": self._get_trading_activity_from_ledger(),
    #             "equity": {
    #                 "start_equity": self.daily_start_equity,
    #                 "end_equity": self.current_equity,
    #                 "peak_equity": self.peak_equity if self.is_continuing_session else self.current_equity,
    #             },
    #             "risk_metrics": {
    #                 "current_drawdown": daily_max_drawdown,
    #                 "volatility": 0.02,  # Default volatility
    #                 "var_95": 0.03,      # Default VaR
    #             },
    #             "strategy_performance": {},  # Would need to track per-strategy metrics
    #             "metadata": {
    #                 "timezone": self.timezone,
    #                 "rollover_type": "automatic",
    #             },
    #         })
    #         
    #     except Exception as e:
    #         self.logger.error(f"Failed to generate daily summary: {e}")
    #         # daily_summary_data already has safe defaults, keep them
    #     
    #     # Always try to log the summary data (either calculated or fallback)
    #     try:
    #         self.log_daily_summary(daily_summary_data)
    #     except Exception as log_error:
    #         self.logger.error(f"Failed to log daily summary: {log_error}")

    # DEPRECATED: This method has been replaced by consolidated logging in trading_system.py
    # def log_trading_cycle(self, cycle_data: dict[str, Any]) -> None:
    #     """Log a complete trading cycle with comprehensive data.
    #
    #     Args:
    #         cycle_data: Dictionary containing cycle information
    #     """
    #     if not self.initialized:
    #         self.initialize()
    #
    #     # Check for daily rollover first
    #     cycle_timestamp = cycle_data.get("timestamp", datetime.now())
    #     if isinstance(cycle_timestamp, str):
    #         try:
    #             cycle_timestamp = datetime.fromisoformat(cycle_timestamp.replace('Z', '+00:00'))
    #         except:
    #             cycle_timestamp = datetime.now(timezone.utc)
    #     
    #     self._check_daily_rollover(cycle_timestamp)
    #
    #     # Extract cycle data
    #     cycle_id = cycle_data.get("cycle_id", f"cycle_{len(self.trading_cycles) + 1}")
    #     timestamp = cycle_timestamp
    #     symbol = cycle_data.get("symbol", "UNKNOWN")
    #     strategy = cycle_data.get("strategy", "UNKNOWN")
    #
    #     # Equity and P&L data
    #     equity_data = cycle_data.get("equity", {})
    #     current_equity = equity_data.get("current_equity", self.current_equity)
    #     previous_equity = equity_data.get("previous_equity", self.current_equity)
    #     cycle_pnl = current_equity - previous_equity
    #
    #     # Position data
    #     positions = cycle_data.get("positions", {})
    #     # Only count positions with non-zero quantity
    #     position_count = len([pos for pos in positions.values() if abs(pos.get("quantity", 0)) > 1e-8])
    #     total_position_value = sum(pos.get("value", 0) for pos in positions.values())
    #
    #     # Decision data
    #     decisions = cycle_data.get("decisions", {})
    #     decision_count = len(decisions)
    #     risk_score = decisions.get("risk_score", 0.0)
    #     confidence = decisions.get("confidence", 0.0)
    #
    #     # Trade data
    #     trades = cycle_data.get("trades", [])
    #     trade_count = len(trades)
    #     total_trade_volume = sum(trade.get("volume", 0) for trade in trades)
    #     total_fees = sum(trade.get("fees", 0) for trade in trades)
    #
    #     # Create cycle log entry
    #     cycle_log = {
    #         "cycle_id": cycle_id,
    #         "timestamp": timestamp.isoformat()
    #         if isinstance(timestamp, datetime)
    #         else str(timestamp),
    #         "symbol": symbol,
    #         "strategy": strategy,
    #         "equity": {
    #             "current_equity": current_equity,
    #             "previous_equity": previous_equity,
    #             "cycle_pnl": cycle_pnl,
    #             "equity_change_pct": (cycle_pnl / previous_equity * 100)
    #             if previous_equity > 0
    #             else 0.0,
    #         },
    #         "positions": {
    #             "count": position_count,
    #             "total_value": total_position_value,
    #             "details": positions,
    #         },
    #         "decisions": {
    #             "count": decision_count,
    #             "risk_score": risk_score,
    #             "confidence": confidence,
    #             "details": decisions,
    #         },
    #         "trades": {
    #             "count": trade_count,
    #             "total_volume": total_trade_volume,
    #             "total_fees": total_fees,
    #             "details": trades,
    #         },
    #         "metadata": cycle_data.get("metadata", {}),
    #     }
    #
    #     # Add to cycle logs
    #     self.trading_cycles.append(cycle_log)
    #
    #     # Update performance tracking
    #     self.current_equity = current_equity
    #     self.previous_equity = previous_equity
    #     if current_equity > self.peak_equity:
    #         self.peak_equity = current_equity
    #
    #     # Note: total_trades now comes from trade ledger as single source of truth
    #     self.total_pnl += cycle_pnl
    #
    #     # Update daily tracking
    #     # Note: daily_trades now comes from trade ledger as single source of truth
    #     self.daily_pnl += cycle_pnl
    #
    #     # Count winning/losing trades
    #     for trade in trades:
    #         trade_pnl = trade.get("pnl", 0)
    #         if trade_pnl > 0:
    #             self.winning_trades += 1
    #             self.daily_winning_trades += 1
    #         elif trade_pnl < 0:
    #             self.losing_trades += 1
    #             self.daily_losing_trades += 1
    #
    #     # Log to console with emojis and formatting
    #     if self.console_output:
    #         self._log_cycle_to_console(cycle_log)
    #
    #     # Save logs
    #     self._save_logs()
    #
    #     self.logger.info(
    #         f"Logged trading cycle: {cycle_id} for {symbol} using {strategy}"
    #     )

    # DEPRECATED: This method has been replaced by consolidated logging in trading_system.py
    # def log_daily_summary(self, daily_data: dict[str, Any]) -> None:
    #     """Log daily summary with key performance metrics.
    #
    #     Args:
    #         daily_data: Dictionary containing daily summary information
    #     """
    #     if not self.initialized:
    #         self.initialize()
    #
    #     # Extract daily data
    #     date = daily_data.get("date", datetime.now().date())
    #     timestamp = daily_data.get("timestamp", datetime.now())
    #
    #     # Performance metrics
    #     performance = daily_data.get("performance", {})
    #     win_rate = performance.get("win_rate", 0.0)
    #     sharpe_ratio = performance.get("sharpe_ratio", 0.0)
    #     max_drawdown = performance.get("max_drawdown", 0.0)
    #     total_return = performance.get("total_return", 0.0)
    #     profit_factor = performance.get("profit_factor", 0.0)
    #
    #     # Trading activity
    #     trading_activity = daily_data.get("trading_activity", {})
    #     total_trades = trading_activity.get("total_trades", 0)
    #     winning_trades = trading_activity.get("winning_trades", 0)
    #     losing_trades = trading_activity.get("losing_trades", 0)
    #     total_volume = trading_activity.get("total_volume", 0.0)
    #     total_fees = trading_activity.get("total_fees", 0.0)
    #
    #     # Equity data
    #     equity_data = daily_data.get("equity", {})
    #     start_equity = equity_data.get("start_equity", self.current_equity)
    #     end_equity = equity_data.get("end_equity", self.current_equity)
    #     daily_pnl = end_equity - start_equity
    #
    #     # Risk metrics
    #     risk_metrics = daily_data.get("risk_metrics", {})
    #     current_drawdown = risk_metrics.get("current_drawdown", 0.0)
    #     volatility = risk_metrics.get("volatility", 0.0)
    #     var_95 = risk_metrics.get("var_95", 0.0)
    #
    #     # Strategy performance
    #     strategy_performance = daily_data.get("strategy_performance", {})
    #
    #     # Create daily summary log entry
    #     daily_log = {
    #         "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
    #         "timestamp": timestamp.isoformat()
    #         if isinstance(timestamp, datetime)
    #         else str(timestamp),
    #         "performance": {
    #             "win_rate": win_rate,
    #             "sharpe_ratio": sharpe_ratio,
    #             "max_drawdown": max_drawdown,
    #             "total_return": total_return,
    #             "profit_factor": profit_factor,
    #             "daily_pnl": daily_pnl,
    #             "daily_return": (daily_pnl / start_equity * 100)
    #             if start_equity > 0
    #             else 0.0,
    #         },
    #         "trading_activity": {
    #             "total_trades": total_trades,
    #             "winning_trades": winning_trades,
    #             "losing_trades": losing_trades,
    #             "total_volume": total_volume,
    #             "total_fees": total_fees,
    #             "avg_trade_size": total_volume / total_trades
    #             if total_trades > 0
    #             else 0.0,
    #         },
    #         "equity": {
    #             "start_equity": start_equity,
    #             "end_equity": end_equity,
    #             "daily_pnl": daily_pnl,
    #             "peak_equity": self.peak_equity,
    #         },
    #         "risk_metrics": {
    #             "current_drawdown": current_drawdown,
    #             "volatility": volatility,
    #             "var_95": var_95,
    #         },
    #         "strategy_performance": strategy_performance,
    #         "metadata": daily_data.get("metadata", {}),
    #     }
    #
    #     # Add to daily summaries
    #     self.daily_summaries.append(daily_log)
    #
    #     # Log to console with emojis and formatting
    #     if self.console_output:
    #         self._log_daily_summary_to_console(daily_log)
    #
    #     # Save logs
    #     self._save_logs()
    #
    #     self.logger.info(f"Logged daily summary for {date}")

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
                # Try to get live mark price for display
                mark_price = pos.get('current_price', pos.get('price', 0))
                if mark_price and mark_price > 0:
                    print(
                        f"   📊 {symbol}: {pos.get('quantity', 0):.4f} @ ${mark_price:.2f}"
                    )
                else:
                    print(
                        f"   📊 {symbol}: {pos.get('quantity', 0):.4f} @ N/A (no valid price)"
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
            # Filter out invalid trades (qty <= 0, price <= 0, or not committed)
            valid_trades = []
            for trade in trades["details"]:
                quantity = trade.get('quantity', 0)
                price = trade.get('price', 0)
                committed = trade.get('committed', True)  # Default to True for backward compatibility
                
                # Skip invalid trades
                if quantity <= 0 or price <= 0 or not committed:
                    continue
                    
                valid_trades.append(trade)
            
            # Display only valid trades
            for i, trade in enumerate(valid_trades):
                side_emoji = "🟢" if trade.get("side") == "buy" else "🔴"
                pnl_emoji = "📈" if trade.get("pnl", 0) >= 0 else "📉"
                
                # Add exit reason if present
                exit_reason = trade.get('exit_reason', '')
                reason_text = f" ({exit_reason})" if exit_reason else ""
                
                print(
                    f"   {side_emoji} Trade {i+1}: {trade.get('side', 'N/A')} {trade.get('quantity', 0):.4f} @ ${trade.get('price', 0):.2f}{reason_text}"
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
        session_info = daily_log.get("session_info", {})
        session_status = "🔄 CONTINUING SESSION" if session_info.get("is_continuing_session", False) else "🆕 NEW SESSION"
        print(f"📊 DAILY SUMMARY: {daily_log['date']} ({session_status})")
        if session_info.get("session_id"):
            print(f"🆔 Session ID: {session_info['session_id']}")
        print("=" * 80)

        # Performance section removed

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
                "session_id": self.session_id,
                "session_start_time": self.session_start_time.isoformat(),
                "session_start_equity": self.session_start_equity,
                "is_continuing_session": self.is_continuing_session,
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

            # Check if we're continuing a session (same day as last log entry)
            last_session_id = log_data.get("session_id")
            last_session_time = log_data.get("session_start_time")
            last_session_start_equity = log_data.get("session_start_equity")
            
            # Check if capital has changed significantly (indicating a new session)
            current_capital = self.config.get("initial_capital", 100000.0)
            capital_changed = False
            if last_session_start_equity and abs(last_session_start_equity - current_capital) > current_capital * 0.05:  # 5% threshold
                capital_changed = True
                self.logger.info(f"Capital changed significantly: {last_session_start_equity} -> {current_capital}, starting new session")
            
            if last_session_id and last_session_time and not capital_changed:
                try:
                    last_session_datetime = datetime.fromisoformat(last_session_time.replace('Z', '+00:00'))
                    current_date = datetime.now(timezone.utc).date()
                    last_session_date = last_session_datetime.date()
                    
                    # If same day and within reasonable time (e.g., within 24 hours), continue session
                    if current_date == last_session_date:
                        self.is_continuing_session = True
                        self.session_id = last_session_id
                        self.session_start_time = last_session_datetime
                        self.logger.info(f"Continuing previous session: {self.session_id}")
                    else:
                        self.logger.info(f"Starting new session (date changed): {self.session_id}")
                        
                except Exception as e:
                    self.logger.warning(f"Could not parse session time: {e}, starting new session")
            else:
                self.logger.info(f"Starting new session (no previous session found or capital changed): {self.session_id}")

            # Only restore performance data if continuing session
            if self.is_continuing_session:
                perf_summary = log_data.get("performance_summary", {})
                self.current_equity = perf_summary.get("current_equity", self.current_equity)
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
                    
                self.logger.info("Restored performance data from previous session")
            else:
                # Reset to current equity for new session
                self.session_start_equity = self.current_equity
                self.daily_start_equity = self.current_equity
                self.logger.info("Starting fresh session - resetting performance counters")

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

    def get_enhanced_position_details(
        self, 
        positions: dict[str, dict[str, Any]], 
        data_engine=None,
        live_mode: bool = False
    ) -> dict[str, dict[str, Any]]:
        """
        Get enhanced position details with live mark prices.
        
        Args:
            positions: Dictionary of position data
            data_engine: Data engine for getting live prices
            live_mode: Whether in live trading mode
            
        Returns:
            Enhanced position details with live mark prices
        """
        enhanced_positions = {}
        
        for symbol, position in positions.items():
            try:
                # Start with existing position data
                enhanced_pos = position.copy()
                
                # Try to get live mark price if data engine is available
                if data_engine:
                    mark_price = get_mark_price(
                        symbol, 
                        data_engine, 
                        live_mode=live_mode
                    )
                    
                    if mark_price and validate_mark_price(mark_price, symbol):
                        enhanced_pos["current_price"] = mark_price
                        enhanced_pos["market_value"] = position.get("quantity", 0) * mark_price
                        enhanced_pos["unrealized_pnl"] = (mark_price - position.get("entry_price", 0)) * position.get("quantity", 0)
                        enhanced_pos["price_source"] = "live_mark"
                    else:
                        # Use existing price if no live price available
                        existing_price = position.get("current_price", position.get("price", 0))
                        if existing_price and existing_price > 0:
                            enhanced_pos["current_price"] = existing_price
                            enhanced_pos["market_value"] = position.get("quantity", 0) * existing_price
                            enhanced_pos["unrealized_pnl"] = (existing_price - position.get("entry_price", 0)) * position.get("quantity", 0)
                            enhanced_pos["price_source"] = "cached"
                        else:
                            enhanced_pos["current_price"] = 0
                            enhanced_pos["market_value"] = 0
                            enhanced_pos["unrealized_pnl"] = 0
                            enhanced_pos["price_source"] = "none"
                else:
                    # No data engine, use existing data
                    existing_price = position.get("current_price", position.get("price", 0))
                    enhanced_pos["current_price"] = existing_price
                    enhanced_pos["market_value"] = position.get("quantity", 0) * existing_price if existing_price else 0
                    enhanced_pos["unrealized_pnl"] = (existing_price - position.get("entry_price", 0)) * position.get("quantity", 0) if existing_price else 0
                    enhanced_pos["price_source"] = "cached"
                
                enhanced_positions[symbol] = enhanced_pos
                
            except Exception as e:
                self.logger.warning(f"Error enhancing position data for {symbol}: {e}")
                # Fallback to original position data
                enhanced_positions[symbol] = position
        
        return enhanced_positions

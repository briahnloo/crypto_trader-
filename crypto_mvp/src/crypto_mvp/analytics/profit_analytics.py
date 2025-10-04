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
        
        # Session tracking
        self.session_id = None

        self.initialized = False

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initialize the profit analytics system for a specific session.
        
        Args:
            session_id: Session identifier for session-scoped analytics
        """
        if self.initialized:
            self.logger.info("ProfitAnalytics already initialized")
            return

        self.session_id = session_id
        self.logger.info("Initializing ProfitAnalytics")
        
        # Reset analytics for new session
        if session_id:
            # Use actual session capital from config instead of default
            session_capital = self.config.get("initial_capital", self.initial_capital)
            self.initial_capital = session_capital
            self.current_equity = session_capital
            self.peak_equity = session_capital
            
            # Reset performance tracking for new session
            self.total_trades = 0
            self.winning_trades = 0
            self.losing_trades = 0
            self.total_pnl = 0.0
            self.max_drawdown = 0.0
            self.current_drawdown = 0.0
            
            self.logger.info(f"Session ID: {session_id}")
            self.logger.info(f"Session initial capital: ${self.initial_capital:,.2f}")
            self.log_file = f"profit_logs_{session_id}.json"
        else:
            self.logger.info(f"Initial capital: ${self.initial_capital:,.2f}")
            self.log_file = self.config.get("log_file", "profit_logs.json")
        
        self.logger.info(f"Log file: {self.log_file}")

        # Load existing trade log if available (session-scoped)
        self._load_trade_log()

        self.initialized = True

    def log_trade(self, trade: dict[str, Any]) -> None:
        """Log a completed trade from trade dictionary.

        Args:
            trade: Trade dictionary with required keys
        """
        if not self.initialized:
            self.initialize()

        # Validate trade is a dictionary
        if not isinstance(trade, dict):
            self.logger.warning(f"log_trade received non-dict trade: {type(trade)}")
            return

        # Validate and extract required fields with safe defaults
        try:
            # Coerce missing numerics to 0.0 and strings to ""
            symbol = str(trade.get("symbol", "UNKNOWN")) if trade.get("symbol") is not None else "UNKNOWN"
            strategy = str(trade.get("strategy", "unknown")) if trade.get("strategy") is not None else "unknown"
            side = str(trade.get("side", "buy")) if trade.get("side") is not None else "buy"
            
            # Safe numeric coercion with fallback to 0.0
            quantity = 0.0
            try:
                quantity = float(trade.get("quantity", 0.0))
            except (ValueError, TypeError):
                quantity = 0.0
                
            entry_price = 0.0
            try:
                entry_price = float(trade.get("entry_price", 0.0))
            except (ValueError, TypeError):
                entry_price = 0.0
                
            exit_price = 0.0
            try:
                exit_price = float(trade.get("exit_price", 0.0))
            except (ValueError, TypeError):
                exit_price = 0.0
                
            fees = 0.0
            try:
                fees = float(trade.get("fees", 0.0))
            except (ValueError, TypeError):
                fees = 0.0
            
            timestamp = trade.get("timestamp", datetime.now())
            
            # Handle timestamp conversion
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    timestamp = datetime.now()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.now()
                
            metadata = trade.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            
            # Extract pilot flag
            pilot = trade.get("pilot", False)
            if not isinstance(pilot, bool):
                pilot = False
            
        except Exception as e:
            self.logger.warning(f"Failed to parse trade fields: {e}")
            return

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
            "pilot": pilot,
            "metadata": metadata,
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

        # Calculate average win/loss - guard with if trades:
        if strategy_metrics["winning_trades"] > 0 and strategy_metrics["trades"]:
            total_wins = sum(
                t.get("pnl", 0.0) for t in strategy_metrics["trades"] if t.get("pnl", 0.0) > 0
            )
            strategy_metrics["avg_win"] = (
                total_wins / strategy_metrics["winning_trades"]
            )

        if strategy_metrics["losing_trades"] > 0 and strategy_metrics["trades"]:
            total_losses = sum(
                abs(t.get("pnl", 0.0)) for t in strategy_metrics["trades"] if t.get("pnl", 0.0) < 0
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
            # Guard with safe pnl extraction
            pnl = trade.get("pnl", 0.0) if trade.get("pnl") is not None else 0.0
            current_equity += pnl
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
        if not trades or len(trades) < 2:
            return 0.0

        # Calculate returns - guard with if trades:
        returns = [trade.get("pnl", 0.0) for trade in trades if trade.get("pnl") is not None]

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
        if not trades or len(trades) < 2:
            return 0.0

        # Calculate returns - guard with if trades:
        returns = [trade.get("pnl", 0.0) for trade in trades if trade.get("pnl") is not None]

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

    def generate_profit_report(self, state_store=None, session_id=None) -> dict[str, Any]:
        """Generate comprehensive profit report.

        Args:
            state_store: Optional state store to read trades from
            session_id: Optional session ID to filter trades

        Returns:
            Profit report dictionary matching MVP keys
        """
        if not self.initialized:
            self.initialize()

        # Try to read trades from state store if provided
        trades = []
        if state_store and session_id:
            try:
                # Read trades from state store for the session
                state_trades = state_store.get_trades()
                
                # Filter by session and convert to analytics format
                from datetime import datetime, timezone
                import pytz
                
                # Get current date in UTC for filtering
                current_date = datetime.now(timezone.utc).date()
                
                for trade in state_trades:
                    if trade.get('session_id') == session_id:
                        # Parse trade timestamp and filter by date
                        executed_at = trade.get('executed_at')
                        if executed_at:
                            try:
                                if isinstance(executed_at, str):
                                    trade_datetime = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                                else:
                                    trade_datetime = executed_at
                                
                                # Ensure timezone awareness
                                if trade_datetime.tzinfo is None:
                                    trade_datetime = trade_datetime.replace(tzinfo=timezone.utc)
                                
                                trade_date = trade_datetime.date()
                                
                                # Only include trades from current date
                                if trade_date == current_date:
                                    # Convert state store trade format to analytics format
                                    analytics_trade = {
                                        'symbol': trade.get('symbol'),
                                        'strategy': trade.get('strategy', 'unknown'),
                                        'side': trade.get('side'),
                                        'quantity': trade.get('quantity', 0.0),
                                        'entry_price': trade.get('price', 0.0),
                                        'exit_price': trade.get('price', 0.0),  # Use same price for now
                                        'fees': trade.get('fees', 0.0),
                                        'pnl': trade.get('realized_pnl', 0.0),
                                        'timestamp': trade_datetime.isoformat(),
                                        'date': trade_date.isoformat(),
                                        'pilot': False,
                                        'metadata': {}
                                    }
                                    trades.append(analytics_trade)
                            except Exception as e:
                                self.logger.warning(f"Failed to parse trade timestamp {executed_at}: {e}")
                                continue
                
                self.logger.info(f"summary_src=ledger entries={len(trades)} for date={current_date} tz=UTC session={session_id}")
                
            except Exception as e:
                self.logger.warning(f"Failed to read trades from state store: {e}, using trade_log")
                trades = self.trade_log
        else:
            trades = self.trade_log

        # Handle empty trades case - return all zeros and empty dicts
        if not trades:
            return self._generate_empty_report()

        # Guard all aggregates with if trades: checks
        
        # Calculate key metrics with safe handling
        win_rate = (
            self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0
        )

        # Calculate profit factor with safe handling - guard with if trades:
        total_wins = 0.0
        total_losses = 0.0
        if trades:
            total_wins = sum(trade.get("pnl", 0.0) for trade in trades if trade.get("pnl", 0.0) > 0)
            total_losses = sum(
                abs(trade.get("pnl", 0.0)) for trade in trades if trade.get("pnl", 0.0) < 0
            )
        
        profit_factor = (
            total_wins / total_losses
            if total_losses > 0
            else float("inf")
            if total_wins > 0
            else 0.0
        )

        # Calculate average win/loss with safe handling - guard with if trades:
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

        # Calculate max/min trades with guards
        max_win = 0.0
        max_loss = 0.0
        total_fees = 0.0
        total_trade_volume = 0.0
        best_trade = None
        worst_trade = None
        
        if trades:
            max_win = max(trade.get("pnl", 0.0) for trade in trades)
            max_loss = min(trade.get("pnl", 0.0) for trade in trades)
            total_fees = sum(trade.get("fees", 0.0) for trade in trades)
            total_trade_volume = sum(
                trade.get("quantity", 0.0) * trade.get("entry_price", 0.0) for trade in trades
            )
            best_trade = max(trades, key=lambda x: x.get("pnl", 0.0))
            worst_trade = min(trades, key=lambda x: x.get("pnl", 0.0))

        # Calculate daily metrics with guards
        avg_daily_pnl = 0.0
        if self.daily_pnl:
            avg_daily_pnl = sum(self.daily_pnl.values()) / len(self.daily_pnl)

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
            "max_win": max_win,
            "max_loss": max_loss,
            # Risk metrics
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": self._calculate_overall_sortino_ratio(),
            "current_drawdown": self.current_drawdown,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            # Capital metrics
            "initial_capital": self.initial_capital,
            "total_fees": total_fees,
            # Strategy breakdown
            "strategy_performance": strategy_performance,
            # Time-based metrics
            "daily_pnl": self.daily_pnl,
            "trading_days": len(self.daily_pnl),
            "avg_daily_pnl": avg_daily_pnl,
            # Additional metrics
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "consecutive_wins": self._calculate_consecutive_wins(),
            "consecutive_losses": self._calculate_consecutive_losses(),
            # Metadata
            "report_timestamp": datetime.now().isoformat(),
            "total_trade_volume": total_trade_volume,
        }

        return report

    def _calculate_overall_sharpe_ratio(self) -> float:
        """Calculate overall Sharpe ratio.

        Returns:
            Sharpe ratio
        """
        if not self.trade_log or len(self.trade_log) < 2:
            return 0.0

        # Guard with if trades:
        returns = [trade.get("pnl", 0.0) for trade in self.trade_log if trade.get("pnl") is not None]
        
        if not returns:
            return 0.0
            
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
        if not self.trade_log or len(self.trade_log) < 2:
            return 0.0

        # Guard with if trades:
        returns = [trade.get("pnl", 0.0) for trade in self.trade_log if trade.get("pnl") is not None]
        
        if not returns:
            return 0.0
            
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
        if self.trade_log:
            for trade in reversed(self.trade_log):
                if trade.get("pnl", 0.0) > 0:
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
        if self.trade_log:
            for trade in reversed(self.trade_log):
                if trade.get("pnl", 0.0) < 0:
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

    def update_equity_from_session(self, session_cash: float, positions: dict[str, dict[str, Any]]) -> None:
        """Update equity from session cash and mark-to-market positions.
        
        Args:
            session_cash: Current session cash balance
            positions: Current positions with mark-to-market values
        """
        # Calculate mark-to-market value of positions
        mtm_value = 0.0
        for symbol, position in positions.items():
            quantity = position.get("quantity", 0.0)
            current_price = position.get("current_price", 0.0)
            mtm_value += quantity * current_price
        
        # Update equity as cash + mark-to-market
        self.current_equity = session_cash + mtm_value
        
        # Update peak equity if current is higher
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
            
        self.logger.debug(f"Updated equity from session: cash=${session_cash:.2f}, mtm=${mtm_value:.2f}, total=${self.current_equity:.2f}")

    def _generate_empty_report(self) -> dict[str, Any]:
        """Generate a zeroed report for empty trade sessions.
        
        Returns:
            Empty report dictionary with all metrics set to safe defaults
        """
        return {
            # Core metrics - all zeroed
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            # PnL metrics - all zeroed
            "total_pnl": 0.0,
            "total_return": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            # Risk metrics - all zeroed
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "current_drawdown": 0.0,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            # Capital metrics
            "initial_capital": self.initial_capital,
            "total_fees": 0.0,
            # Strategy breakdown - empty
            "strategy_performance": {},
            # Time-based metrics - all zeroed
            "daily_pnl": {},
            "trading_days": 0,
            "avg_daily_pnl": 0.0,
            # Additional metrics - all None/zeroed
            "best_trade": None,
            "worst_trade": None,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            # Metadata
            "report_timestamp": datetime.now().isoformat(),
            "total_trade_volume": 0.0,
        }

    def reset_daily_counters(self) -> None:
        """Reset daily counters while preserving session data."""
        # Reset daily PnL tracking
        self.daily_pnl.clear()
        
        # Reset daily counters but keep session totals
        self.logger.info("Daily counters reset - session totals preserved")

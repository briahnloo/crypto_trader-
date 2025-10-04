"""
Profit-maximizing trading system orchestration.
"""

import asyncio
from datetime import datetime
from typing import Any, Optional

from .analytics import ProfitAnalytics, ProfitLogger
from .analytics.trade_ledger import TradeLedger
from .core.config_manager import ConfigManager
from .core.logging_utils import LoggerMixin
from .core.utils import get_mark_price, validate_mark_price, to_canonical
from .data.engine import ProfitOptimizedDataEngine
from .execution.multi_strategy import MultiStrategyExecutor
from .execution.order_manager import OrderManager
from .risk import AdvancedPortfolioManager, ProfitOptimizedRiskManager
from .state import StateStore
from .strategies.composite import ProfitMaximizingSignalEngine


class ProfitMaximizingTradingSystem(LoggerMixin):
    """
    Main trading system that orchestrates all components for profit-maximized trading.
    """

    def __init__(self, config_path: str = "config/profit_optimized.yaml"):
        """Initialize the trading system.

        Args:
            config_path: Path to configuration file
        """
        super().__init__()
        self.config_path = config_path
        self.config_manager = None
        self.config = {}

        # Core components
        self.data_engine = None
        self.signal_engine = None
        self.risk_manager = None
        self.portfolio_manager = None
        self.order_manager = None
        self.multi_strategy_executor = None

        # Analytics and logging
        self.profit_analytics = None
        self.profit_logger = None
        self.trade_ledger = None

        # State persistence
        self.state_store = None

        # Portfolio tracking (in-memory for now, synced with state store)
        self.portfolio = {
            "equity": 100000.0,
            "cash_balance": 100000.0,
            "positions": {},
            "total_fees": 0.0,
            "last_updated": datetime.now(),
        }

        # System state
        self.running = False
        self.cycle_count = 0
        self.last_cycle_time = None
        self.initialized = False
        
        # Session tracking
        self.current_session_id = None

    def initialize(
        self, 
        session_id: str, 
        continue_session: bool = False, 
        respect_session_capital: bool = True,
        include_existing: bool = False
    ) -> None:
        """Initialize all system components with session management.
        
        Args:
            session_id: Mandatory session identifier (no fallbacks)
            continue_session: Whether to continue an existing session
            respect_session_capital: Whether to respect session capital settings
            include_existing: Whether to include existing exchange positions in live mode
        """
        if self.initialized:
            self.logger.info("Trading system already initialized")
            return

        # Validate session_id is provided
        if not session_id or not session_id.strip():
            raise ValueError("session_id is mandatory and cannot be empty")

        self.logger.info(f"Initializing ProfitMaximizingTradingSystem with session: {session_id}...")

        # Set session ID immediately after validation
        self.current_session_id = session_id

        try:
            # Load configuration (only if not already loaded)
            if not self.config_manager or not self.config:
                self.config_manager = ConfigManager(self.config_path)
                self.config = self.config_manager.to_dict()
                self.logger.info("Configuration loaded successfully")
            else:
                self.logger.info("Configuration already loaded, using existing config")

            # Initialize data engine
            self.data_engine = ProfitOptimizedDataEngine()
            self.data_engine.initialize()
            self.logger.info("Data engine initialized")

            # Initialize signal engine with state store
            signal_config = self.config.get("signals", {})
            self.signal_engine = ProfitMaximizingSignalEngine(signal_config)
            self.logger.info("Signal engine initialized")

            # Initialize risk manager
            risk_config = self.config.get("risk", {})
            self.risk_manager = ProfitOptimizedRiskManager(risk_config)
            self.logger.info("Risk manager initialized")

            # Initialize portfolio manager
            portfolio_config = self.config.get("portfolio", {})
            self.portfolio_manager = AdvancedPortfolioManager(portfolio_config)
            self.logger.info("Portfolio manager initialized")

            # Initialize order manager
            order_config = self.config.get("execution", {})
            # Add trading mode flags to order manager config
            trading_config = self.config.get("trading", {})
            order_config.update(
                {
                    "live_mode": trading_config.get("live_mode", False),
                    "dry_run": trading_config.get("dry_run", False),
                    "simulate": not trading_config.get("live_mode", False)
                    or trading_config.get("dry_run", False),
                }
            )
            self.order_manager = OrderManager(order_config)

            # Validate API keys for live trading
            if trading_config.get("live_mode", False):
                if not self.order_manager.validate_api_keys(self.config):
                    raise RuntimeError("API key validation failed for live trading")
                self.logger.info("API keys validated for live trading")

            self.logger.info("Order manager initialized")

            # Initialize multi-strategy executor
            self.multi_strategy_executor = MultiStrategyExecutor(self.risk_manager)
            self.multi_strategy_executor.initialize()
            self.logger.info("Multi-strategy executor initialized")

            # Initialize analytics
            analytics_config = self.config.get("analytics", {})
            self.profit_analytics = ProfitAnalytics(analytics_config)
            self.profit_analytics.initialize(session_id)
            self.logger.info("Profit analytics initialized")
            
            # Initialize trade ledger
            ledger_db_path = analytics_config.get("ledger_db_path", "trade_ledger.db")
            self.trade_ledger = TradeLedger(ledger_db_path)
            self.logger.info(f"Trade ledger initialized at {ledger_db_path}")

            # Initialize profit logger
            logger_config = self.config.get("logging", {})
            # Pass the actual session capital to the logger
            session_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            logger_config["initial_equity"] = session_capital
            self.profit_logger = ProfitLogger(logger_config)
            self.profit_logger.initialize(session_id)
            self.logger.info("Profit logger initialized")

            # Initialize state store
            db_path = self.config.get("state", {}).get("db_path", "trading_state.db")
            self.state_store = StateStore(db_path)
            self.state_store.initialize()
            self.logger.info("State store initialized")
            
            # Set state store on signal engine for rolling windows
            if self.signal_engine:
                self.signal_engine.set_state_store(self.state_store)
                self.logger.info("State store set on signal engine for rolling windows")
            
            # Set state store and session ID on order manager for budget enforcement
            if self.order_manager:
                self.order_manager.set_state_store(self.state_store)
                self.order_manager.set_session_id(session_id)
                self.logger.info("State store and session ID set on order manager for budget enforcement")

            # Load existing state or initialize with config values and session management
            self._load_or_initialize_portfolio(session_id, continue_session, respect_session_capital)

            # Handle external positions in live mode
            if self.config.get("trading", {}).get("live_mode", False) and include_existing:
                self._handle_external_positions()
            elif self.config.get("trading", {}).get("live_mode", False) and not include_existing:
                self._check_for_external_positions()

            self.initialized = True
            self.logger.info("Trading system initialization complete")

        except Exception as e:
            self.logger.error(f"Failed to initialize trading system: {e}")
            raise

    def _check_for_external_positions(self) -> None:
        """Check for external positions on exchange and log warning if found."""
        try:
            # This is a placeholder - in a real implementation, you would query the exchange
            # for existing positions that are not part of the current session
            self.logger.warning("external_positions_detected: Non-session positions exist on exchange but are ignored by default")
        except Exception as e:
            self.logger.error(f"Error checking for external positions: {e}")

    def _handle_external_positions(self) -> None:
        """Import existing exchange positions by reducing session cash by their market value."""
        try:
            # This is a placeholder - in a real implementation, you would:
            # 1. Query the exchange for existing positions
            # 2. Calculate their current market value
            # 3. Reduce session cash by that amount
            # 4. Add the positions to the session state
            self.logger.info("Importing existing exchange positions into session")
            # Placeholder: reduce cash by market value of external positions
            # external_positions_value = self._get_external_positions_value()
            # self.state_store.debit_cash(external_positions_value, 0.0)
        except Exception as e:
            self.logger.error(f"Error handling external positions: {e}")

    def _load_or_initialize_portfolio(
        self, 
        session_id: str, 
        continue_session: bool = False, 
        respect_session_capital: bool = True
    ) -> None:
        """Load existing portfolio state or initialize with session management.
        
        Args:
            session_id: Mandatory session identifier (no fallbacks)
            continue_session: Whether to continue an existing session
            respect_session_capital: Whether to respect session capital settings
        """
        try:
            # Determine starting capital
            initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            
            if continue_session:
                # Try to load existing session
                try:
                    session_meta = self.state_store.load_session(session_id)
                    self.logger.info(f"Resumed session {session_id}")
                    
                    # Load existing state
                    latest_cash_equity = self.state_store.get_latest_cash_equity(session_id)
                    existing_positions = self.state_store.get_positions(session_id)
                    
                    if latest_cash_equity:
                        # Use session capital unless override is requested
                        if respect_session_capital:
                            self.portfolio["cash_balance"] = latest_cash_equity["cash_balance"]
                            self.portfolio["equity"] = latest_cash_equity["total_equity"]
                        else:
                            # Override with CLI capital
                            self.portfolio["cash_balance"] = initial_capital
                            self.portfolio["equity"] = initial_capital
                            # Update state store with new capital
                            self.state_store.save_cash_equity(
                                cash_balance=initial_capital,
                                total_equity=initial_capital,
                                total_fees=latest_cash_equity.get("total_fees", 0.0),
                                total_realized_pnl=0.0,
                                total_unrealized_pnl=0.0,
                                session_id=session_id
                            )
                        
                        self.portfolio["total_fees"] = latest_cash_equity.get("total_fees", 0.0)
                        
                        # Load positions (ensure existing_positions is a list)
                        if isinstance(existing_positions, list):
                            for pos in existing_positions:
                                symbol = pos["symbol"]
                                self.portfolio["positions"][symbol] = {
                                    "quantity": pos["quantity"],
                                    "entry_price": pos["entry_price"],
                                    "current_price": pos["current_price"],
                                    "unrealized_pnl": pos["unrealized_pnl"],
                                    "strategy": pos["strategy"]
                                }
                        else:
                            self.logger.warning(f"existing_positions is not a list: {type(existing_positions)}")
                            self.portfolio["positions"] = {}
                        
                        # Use portfolio snapshot for consistent position count
                        portfolio_snapshot = self.get_portfolio_snapshot()
                        self.logger.info(f"Loaded existing portfolio state: equity=${self.portfolio['equity']:,.2f}, positions={portfolio_snapshot['position_count']}")
                    else:
                        # No existing data, create new session
                        session_meta = self.state_store.new_session(session_id, initial_capital, "paper")
                        self.portfolio["equity"] = initial_capital
                        self.portfolio["cash_balance"] = initial_capital
                        self.portfolio["total_fees"] = 0.0
                        self.logger.info(f"Created new session {session_id}: equity=${initial_capital:,.2f}")
                        
                except ValueError as e:
                    # Session not found, create new one
                    self.logger.info(f"Session {session_id} not found, creating new session: {e}")
                    session_meta = self.state_store.new_session(session_id, initial_capital, "paper")
                    self.portfolio["equity"] = initial_capital
                    self.portfolio["cash_balance"] = initial_capital
                    self.portfolio["total_fees"] = 0.0
                    self.logger.info(f"Created new session {session_id}: equity=${initial_capital:,.2f}")
            else:
                # Start fresh session
                session_meta = self.state_store.new_session(session_id, initial_capital, "paper")
                self.portfolio["equity"] = initial_capital
                self.portfolio["cash_balance"] = initial_capital
                self.portfolio["total_fees"] = 0.0
                self.logger.info(f"Started fresh session {session_id}: equity=${initial_capital:,.2f}")
                
        except Exception as e:
            self.logger.error(f"Failed to load/initialize portfolio: {e}")
            raise RuntimeError(f"Failed to initialize portfolio for session {session_id}: {e}")

    def _save_portfolio_state(self) -> None:
        """Save current portfolio state to persistent store."""
        try:
            # Get current state from authoritative sources
            cash_balance = self._get_cash_balance()
            total_equity = self._get_total_equity()
            positions = self.state_store.get_positions(self.current_session_id)
            
            # Calculate totals from state store data
            total_positions_value = 0.0
            total_unrealized_pnl = 0.0
            
            for position in positions:
                quantity = position["quantity"]
                current_price = position.get("current_price", position["entry_price"])
                entry_price = position["entry_price"]
                
                total_positions_value += quantity * current_price
                total_unrealized_pnl += (current_price - entry_price) * quantity
            
            # Save cash/equity to state store
            self.state_store.save_cash_equity(
                cash_balance=cash_balance,
                total_equity=total_equity,
                total_fees=self.portfolio.get("total_fees", 0.0),
                total_realized_pnl=0.0,  # Would need to track this separately
                total_unrealized_pnl=total_unrealized_pnl,
                session_id=self.current_session_id
            )
            
            # Save portfolio snapshot
            self.state_store.save_portfolio_snapshot(
                total_equity=total_equity,
                cash_balance=cash_balance,
                total_positions_value=total_positions_value,
                total_unrealized_pnl=total_unrealized_pnl,
                position_count=len(positions),
                session_id=self.current_session_id
            )
            
            # Use portfolio snapshot for consistent position count
            portfolio_snapshot = self.get_portfolio_snapshot()
            self.logger.debug(f"Saved portfolio state: equity=${total_equity:.2f}, "
                            f"cash=${cash_balance:.2f}, positions={portfolio_snapshot['position_count']}")
            
        except Exception as e:
            self.logger.error(f"Failed to save portfolio state: {e}")

    async def _get_comprehensive_market_data(
        self, symbols: list[str]
    ) -> dict[str, Any]:
        """Get comprehensive market data for all symbols.

        Args:
            symbols: List of trading symbols

        Returns:
            Comprehensive market data dictionary
        """
        self.logger.debug(
            f"Getting comprehensive market data for {len(symbols)} symbols"
        )

        # Convert all symbols to canonical format
        canonical_symbols = [to_canonical(symbol) for symbol in symbols]
        
        market_data = {
            "timestamp": datetime.now().isoformat(),
            "symbols": canonical_symbols,
            "ticker_data": {},
            "ohlcv_data": {},
            "sentiment_data": {},
            "on_chain_data": {},
            "whale_activity": {},
        }

        try:
            # Get ticker data for all symbols (using canonical format)
            for symbol in canonical_symbols:
                try:
                    ticker = self.data_engine.get_ticker(symbol)
                    market_data["ticker_data"][symbol] = ticker
                except Exception as e:
                    self.logger.warning(f"Failed to get ticker for {symbol}: {e}")
                    market_data["ticker_data"][symbol] = None

            # Get OHLCV data for all symbols (using canonical format)
            timeframe = self.config.get("trading", {}).get("timeframe", "1h")
            limit = self.config.get("trading", {}).get("ohlcv_limit", 100)

            for symbol in canonical_symbols:
                try:
                    ohlcv = self.data_engine.get_ohlcv(symbol, timeframe, limit)
                    market_data["ohlcv_data"][symbol] = ohlcv
                except Exception as e:
                    self.logger.warning(f"Failed to get OHLCV for {symbol}: {e}")
                    market_data["ohlcv_data"][symbol] = []

            # Get sentiment data
            try:
                sentiment_data = self.data_engine.get_sentiment_data(
                    "BTC/USDT"
                )  # Use BTC as market sentiment proxy
                market_data["sentiment_data"] = sentiment_data
            except Exception as e:
                self.logger.warning(f"Failed to get sentiment data: {e}")
                market_data["sentiment_data"] = {}

            # Get on-chain data
            try:
                on_chain_data = self.data_engine.get_on_chain_data("BTC/USDT")
                market_data["on_chain_data"] = on_chain_data
            except Exception as e:
                self.logger.warning(f"Failed to get on-chain data: {e}")
                market_data["on_chain_data"] = {}

            # Get whale activity
            try:
                whale_activity = self.data_engine.get_whale_activity("BTC/USDT")
                market_data["whale_activity"] = whale_activity
            except Exception as e:
                self.logger.warning(f"Failed to get whale activity: {e}")
                market_data["whale_activity"] = {}

            self.logger.info(f"Retrieved market data for {len(symbols)} symbols")

        except Exception as e:
            self.logger.error(f"Error getting comprehensive market data: {e}")
            raise

        return market_data

    async def _generate_all_signals(
        self, market_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate trading signals for all symbols.

        Args:
            market_data: Comprehensive market data

        Returns:
            Dictionary of signals for all symbols
        """
        self.logger.debug("Generating trading signals for all symbols")

        symbols = market_data["symbols"]
        all_signals = {}

        try:
            # Generate composite signals for each symbol
            for symbol in symbols:
                try:
                    # Get timeframe from config
                    timeframe = self.config.get("trading", {}).get("timeframe", "1h")

                    # Generate composite signal
                    composite_signal = (
                        await self.signal_engine.generate_composite_signals(
                            symbol, timeframe
                        )
                    )
                    all_signals[symbol] = composite_signal

                    self.logger.debug(
                        f"Generated signal for {symbol}: score={composite_signal.get('composite_score', 0):.3f}"
                    )

                except Exception as e:
                    self.logger.warning(f"Failed to generate signal for {symbol}: {e}")
                    # Provide neutral signal as fallback
                    all_signals[symbol] = {
                        "composite_score": 0.0,
                        "confidence": 0.0,
                        "profit_probability": 0.5,
                        "risk_adjusted_return": 0.0,
                        "individual_signals": {},
                        "metadata": {"error": str(e)},
                    }

            self.logger.info(f"Generated signals for {len(all_signals)} symbols")
            
            # Log top 2 symbols by composite score
            self._log_top_symbols(all_signals)

        except Exception as e:
            self.logger.error(f"Error generating signals: {e}")
            raise

        return all_signals

    def _log_cycle_summary(self, cycle_results: dict[str, Any], execution_results: dict[str, Any]) -> None:
        """Log comprehensive cycle summary with equity, P&L, and performance metrics.
        
        Args:
            cycle_results: Cycle execution results
            execution_results: Trade execution results
        """
        try:
            # Get current portfolio state
            current_equity = self._get_total_equity()
            current_cash = self._get_cash_balance()
            positions = self._get_active_positions()
            
            # Calculate metrics
            position_count = len(positions)
            total_position_value = sum(pos.get("value", 0) for pos in positions.values())
            total_unrealized_pnl = sum(pos.get("unrealized_pnl", 0) for pos in positions.values())
            
            # Trade execution metrics
            trades_executed = execution_results.get("trades_executed", 0)
            total_pnl = execution_results.get("total_pnl", 0.0)
            
            # Signal metrics
            signals_generated = len(cycle_results.get("signals", {}))
            
            # Calculate cycle performance
            cycle_duration = (datetime.now() - datetime.fromisoformat(cycle_results["timestamp"])).total_seconds()
            
            # Log comprehensive summary
            self.logger.info("=" * 80)
            self.logger.info(f"📊 CYCLE #{self.cycle_count} SUMMARY")
            self.logger.info("=" * 80)
            
            # Portfolio Overview
            self.logger.info(f"💰 PORTFOLIO OVERVIEW:")
            self.logger.info(f"   Total Equity: ${current_equity:,.2f}")
            self.logger.info(f"   Cash Balance: ${current_cash:,.2f}")
            self.logger.info(f"   Position Value: ${total_position_value:,.2f}")
            self.logger.info(f"   Unrealized P&L: ${total_unrealized_pnl:,.2f}")
            
            # Trading Activity
            self.logger.info(f"📈 TRADING ACTIVITY:")
            self.logger.info(f"   Trades Executed: {trades_executed}")
            self.logger.info(f"   Cycle P&L: ${total_pnl:,.2f}")
            self.logger.info(f"   Open Positions: {position_count}")
            
            # Signal Analysis
            self.logger.info(f"🎯 SIGNAL ANALYSIS:")
            self.logger.info(f"   Signals Generated: {signals_generated}")
            
            # Top positions by value
            if positions:
                self.logger.info(f"💼 TOP POSITIONS:")
                sorted_positions = sorted(
                    positions.items(), 
                    key=lambda x: abs(x[1].get("value", 0)), 
                    reverse=True
                )[:3]  # Top 3
                
                for symbol, position in sorted_positions:
                    value = position.get("value", 0)
                    pnl = position.get("unrealized_pnl", 0)
                    pnl_pct = (pnl / value * 100) if value > 0 else 0.0
                    self.logger.info(f"   {symbol}: ${value:,.2f} (P&L: ${pnl:,.2f}, {pnl_pct:+.1f}%)")
            
            # Performance metrics
            self.logger.info(f"⚡ PERFORMANCE:")
            self.logger.info(f"   Cycle Duration: {cycle_duration:.1f}s")
            self.logger.info(f"   Session ID: {self.current_session_id}")
            
            # Error summary - check both cycle and execution errors
            cycle_errors = cycle_results.get("errors", [])
            execution_errors = execution_results.get("errors", [])
            all_errors = cycle_errors + execution_errors
            
            if all_errors:
                self.logger.info(f"⚠️  ERRORS: {len(all_errors)} errors occurred")
                for error in all_errors[:3]:  # Show first 3 errors
                    self.logger.info(f"   - {error}")
            else:
                self.logger.info(f"✅ STATUS: No errors")
            
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Failed to generate cycle summary: {e}")

    def _log_top_symbols(self, all_signals: dict[str, Any]) -> None:
        """Log compact breakdown for top 2 symbols by composite score.
        
        Args:
            all_signals: Dictionary of all generated signals by symbol
        """
        if not all_signals:
            return
        
        # Sort symbols by composite score (absolute value for ranking)
        sorted_symbols = sorted(
            all_signals.items(),
            key=lambda x: abs(x[1].get("composite_score", 0)),
            reverse=True
        )
        
        # Log top 2 symbols
        for i, (symbol, signal_data) in enumerate(sorted_symbols[:2]):
            try:
                composite_score = signal_data.get("composite_score", 0.0)
                individual_signals = signal_data.get("individual_signals", {})
                regime = signal_data.get("metadata", {}).get("regime", "unknown")
                
                # Build strategy breakdown with abbreviations
                strategy_abbrevs = {
                    "momentum": "mom",
                    "breakout": "brk", 
                    "mean_reversion": "mr",
                    "sentiment": "sent",
                    "volatility": "vol",
                    "correlation": "corr",
                    "arbitrage": "arb",
                    "news_driven": "news",
                    "whale_tracking": "whale",
                    "on_chain": "onchain"
                }
                
                strategy_scores = []
                for strategy_name, strategy_signal in individual_signals.items():
                    if "error" in strategy_signal:
                        continue
                    
                    abbrev = strategy_abbrevs.get(strategy_name, strategy_name[:4])
                    score = strategy_signal.get("score", 0.0)
                    strategy_scores.append(f"{abbrev}={score:.2f}")
                
                # Create compact breakdown
                breakdown_str = "[" + " ".join(strategy_scores) + "]" if strategy_scores else "[no_data]"
                
                # Format: score=0.493 [mom=0.40 brk=0.52 mr=0.31 sent=0.28 vol=0.45] regime=ranging
                log_line = f"score={composite_score:.3f} {breakdown_str} regime={regime}"
                
                # Ensure under 120 characters
                if len(log_line) > 120:
                    # Truncate strategy scores if too long
                    max_breakdown_len = 120 - len(f"score={composite_score:.3f} [] regime={regime}")
                    if len(breakdown_str) > max_breakdown_len:
                        # Keep only first few strategies
                        truncated_scores = []
                        current_len = 2  # Account for []
                        for score_str in strategy_scores:
                            if current_len + len(score_str) + 1 <= max_breakdown_len:
                                truncated_scores.append(score_str)
                                current_len += len(score_str) + 1
                            else:
                                break
                        breakdown_str = "[" + " ".join(truncated_scores) + "]"
                        log_line = f"score={composite_score:.3f} {breakdown_str} regime={regime}"
                
                self.logger.info(f"{symbol}: {log_line}")
                
            except Exception as e:
                self.logger.warning(f"Failed to log breakdown for {symbol}: {e}")

    def _select_best_strategy(self, signal_bundle: dict[str, Any]) -> str:
        """Select the best strategy based on expected risk-adjusted return.
        
        Args:
            signal_bundle: Dictionary containing composite signal data with individual strategy signals
            
        Returns:
            Name of the best strategy to execute
        """
        self.logger.debug("Selecting best strategy based on risk-adjusted return")
        
        # Get strategy configuration
        strategies_config = self.config.get("strategies", {})
        min_confidence = self.config.get("trading", {}).get("min_confidence", 0.4)
        
        # Strategy mapping for strategies that don't have direct executors
        strategy_mapping = {
            "news_driven": "sentiment",
            "whale_tracking": "sentiment", 
            "on_chain": "sentiment",
            "volatility": "momentum",
            "correlation": "momentum",
            "mean_reversion": "breakout"
        }
        
        # Get individual signals from the composite signal bundle
        individual_signals = signal_bundle.get("individual_signals", {})
        
        if not individual_signals:
            self.logger.warning("No individual signals found in signal bundle")
            return "momentum"  # Default fallback
        
        best_strategy = None
        best_score = -float('inf')
        
        # Evaluate each strategy
        for strategy_name, strategy_signal in individual_signals.items():
            # Check if strategy is enabled
            strategy_config = strategies_config.get(strategy_name, {})
            if not strategy_config.get("enabled", True):
                self.logger.debug(f"Strategy {strategy_name} is disabled, skipping")
                continue
            
            # Extract signal metrics
            signal_strength = strategy_signal.get("signal_strength", 0.0)
            confidence = strategy_signal.get("confidence", 0.0)
            score = strategy_signal.get("score", 0.0)
            
            # Check minimum confidence threshold
            if confidence < min_confidence:
                self.logger.debug(f"Strategy {strategy_name} below confidence threshold: {confidence:.3f} < {min_confidence:.3f}")
                continue
            
            # Calculate risk-adjusted return score
            # This combines signal strength, confidence, and base score
            risk_adjusted_score = self._calculate_risk_adjusted_strategy_score(
                strategy_name, strategy_signal, strategy_config
            )
            
            self.logger.debug(f"Strategy {strategy_name}: score={score:.3f}, confidence={confidence:.3f}, risk_adjusted={risk_adjusted_score:.3f}")
            
            # Select strategy with highest risk-adjusted score
            if risk_adjusted_score > best_score:
                best_score = risk_adjusted_score
                best_strategy = strategy_name
        
        # Map strategy to available executor if needed
        if best_strategy and best_strategy in strategy_mapping:
            mapped_strategy = strategy_mapping[best_strategy]
            self.logger.debug(f"Mapping strategy {best_strategy} to executor {mapped_strategy}")
            best_strategy = mapped_strategy
        
        # Fallback to default if no strategy meets criteria
        if best_strategy is None:
            self.logger.warning("No strategy meets minimum criteria, using default momentum")
            best_strategy = "momentum"
        
        self.logger.info(f"Selected strategy: {best_strategy} (score: {best_score:.3f})")
        return best_strategy
    
    def _calculate_risk_adjusted_strategy_score(
        self, 
        strategy_name: str, 
        strategy_signal: dict[str, Any], 
        strategy_config: dict[str, Any]
    ) -> float:
        """Calculate risk-adjusted score for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            strategy_signal: Signal data for the strategy
            strategy_config: Configuration for the strategy
            
        Returns:
            Risk-adjusted score for the strategy
        """
        # Base components
        base_score = strategy_signal.get("score", 0.0)
        confidence = strategy_signal.get("confidence", 0.0)
        signal_strength = strategy_signal.get("signal_strength", 0.0)
        
        # Strategy weight from config
        strategy_weight = strategy_config.get("weight", 0.2)
        
        # Risk components
        volatility = strategy_signal.get("volatility", 0.02)  # Default 2% volatility
        max_drawdown = strategy_signal.get("max_drawdown", 0.05)  # Default 5% max drawdown
        
        # Calculate risk penalty (higher volatility and drawdown = lower score)
        risk_penalty = 1.0 - (volatility * 10) - (max_drawdown * 5)
        risk_penalty = max(0.1, risk_penalty)  # Minimum 10% of original score
        
        # Calculate expected return component
        expected_return = base_score * confidence * signal_strength
        
        # Apply strategy weight
        weighted_return = expected_return * strategy_weight
        
        # Apply risk adjustment
        risk_adjusted_score = weighted_return * risk_penalty
        
        # Add bonus for high-confidence signals
        confidence_bonus = confidence * 0.1 if confidence > 0.8 else 0.0
        
        final_score = risk_adjusted_score + confidence_bonus
        
        return final_score

    async def _execute_profit_optimized_trades(
        self, signals: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute profit-optimized trades based on signals.

        Args:
            signals: Dictionary of signals for all symbols

        Returns:
            Execution results dictionary
        """
        execution_start_time = datetime.now()
        self.logger.info(f"TRADE_EXECUTION_START: {execution_start_time.isoformat()}")
        self.logger.debug("Executing profit-optimized trades")

        execution_results = {
            "timestamp": execution_start_time.isoformat(),
            "trades_executed": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "trades": [],
            "errors": [],
        }

        try:
            # Get available capital
            available_capital = self._get_available_capital()

            # Build candidates with SL/TP + RR derivation first
            candidates = []
            for symbol, signal in signals.items():
                try:
                    # Get current price using mark price helper
                    current_price = get_mark_price(
                        symbol, 
                        self.data_engine, 
                        live_mode=self.config.get("trading", {}).get("live_mode", False)
                    )
                    
                    if not current_price or current_price <= 0:
                        continue

                    # Get composite score and regime
                    composite_score = signal.get("composite_score", 0)
                    regime = signal.get("metadata", {}).get("regime", "ranging")
                    
                    # Determine side based on composite score
                    side = "buy" if composite_score > 0 else "sell"
                    
                    # Get existing SL/TP from signal metadata
                    existing_sl = signal.get("metadata", {}).get("stop_loss")
                    existing_tp = signal.get("metadata", {}).get("take_profit")
                    
                    # Derive SL/TP using the robust three-tier system
                    try:
                        sl_tp_result = self.risk_manager.derive_sl_tp(
                            entry_price=current_price,
                            side=side,
                            atr=None,  # Will be calculated if needed
                            strategy_sl=existing_sl,
                            strategy_tp=existing_tp,
                            symbol=symbol
                        )
                    except ValueError as e:
                        if "no_atr_no_fallback" in str(e):
                            self.logger.info(f"⏭️ SKIP {symbol} reason=no_atr_no_fallback (ATR failed, fallback disabled)")
                            continue
                        else:
                            raise
                    
                    stop_loss = sl_tp_result["stop_loss"]
                    take_profit = sl_tp_result["take_profit"]
                    sl_tp_src = sl_tp_result["source"]
                    
                    # Calculate risk-reward ratio using new robust method
                    try:
                        rr_ratio = self.risk_manager.compute_rr(
                            entry=current_price,
                            sl=stop_loss,
                            tp=take_profit,
                            side=side
                        )
                    except ValueError as e:
                        self.logger.warning(f"RR calculation failed for {symbol}: {e}")
                        continue
                    
                    # Create candidate with all derived data
                    candidate = {
                        "symbol": symbol,
                        "signal": signal,
                        "current_price": current_price,
                        "composite_score": composite_score,
                        "side": side,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "sl_tp_src": sl_tp_src,
                        "risk_reward_ratio": rr_ratio,
                        "regime": regime,
                        "atr": sl_tp_result.get("atr")
                    }
                    candidates.append(candidate)
                    
                except Exception as e:
                    self.logger.debug(f"Error building candidate for {symbol}: {e}")
                    continue

            if not candidates:
                self.logger.info("No candidates could be built (price/RR issues)")
                return execution_results

            # Apply RR gate first: skip if rr < config threshold
            rr_min = self.config.get("risk", {}).get("rr_min", 1.30)
            rr_filtered_candidates = []
            for candidate in candidates:
                if candidate["risk_reward_ratio"] >= rr_min:
                    rr_filtered_candidates.append(candidate)
                else:
                    self.logger.info(f"⏭️ SKIP {candidate['symbol']} reason=rr_too_low ratio={candidate['risk_reward_ratio']:.2f}")

            if not rr_filtered_candidates:
                self.logger.info(f"No candidates meet minimum RR threshold ({rr_min})")
                # Try pilot trade logic here since no regular candidates qualify
                pilot_result = self._execute_pilot_trade(signals, available_capital)
                if pilot_result:
                    execution_results["trades"].append(pilot_result)
                    execution_results["trades_executed"] += 1
                    execution_results["total_pnl"] += pilot_result.get("expected_profit", 0)
                    execution_results["total_fees"] += pilot_result.get("execution_result", {}).get("fees", 0)
                return execution_results

            # Apply score filtering with dynamic threshold and score floor logic
            filtered_candidates = []
            for candidate in candidates:
                # Get the dynamic effective threshold from signal metadata
                effective_threshold = candidate["signal"].get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.65)
                composite_score = abs(candidate["composite_score"])
                rr_ratio = candidate["risk_reward_ratio"]
                
                # Dynamic score floor logic
                rr_relax_for_pilot = self.config.get("risk", {}).get("rr_relax_for_pilot", 1.60)
                if rr_ratio >= rr_relax_for_pilot:
                    # Strong RR - allow lower score floor
                    score_floor = max(effective_threshold - 0.05, 0.55)
                    floor_reason = "strong_rr"
                else:
                    score_floor = effective_threshold
                    floor_reason = "standard"
                
                if composite_score >= score_floor:
                    # Add score floor info to candidate
                    candidate["effective_threshold"] = effective_threshold
                    candidate["score_floor"] = score_floor
                    candidate["floor_reason"] = floor_reason
                    filtered_candidates.append(candidate)
                else:
                    # Enhanced logging for score-based skips
                    raw_score = candidate["signal"].get("metadata", {}).get("normalization", {}).get("raw_composite_score", composite_score)
                    normalized_score = candidate["signal"].get("metadata", {}).get("normalization", {}).get("normalized_composite_score", composite_score)
                    window_size = candidate["signal"].get("metadata", {}).get("normalization", {}).get("window_size", 0)
                    session_cash = self.state_store.get_session_cash(self.current_session_id) if self.state_store else 0.0
                    
                    self.logger.info(f"⏭️ SKIP {candidate['symbol']} reason=score_too_low "
                                   f"thr={effective_threshold:.3f} score_floor={score_floor:.3f} score={normalized_score:.3f} "
                                   f"pre={raw_score:.3f} post={normalized_score:.3f} winN={window_size} "
                                   f"rr={rr_ratio:.2f} notional=$0.00 cash=${session_cash:.2f}")

            if not filtered_candidates:
                self.logger.info("No candidates meet minimum score threshold")
                # Try pilot trade logic here since no regular candidates qualify
                pilot_result = self._execute_pilot_trade(signals, available_capital)
                if pilot_result:
                    execution_results["trades"].append(pilot_result)
                    execution_results["trades_executed"] += 1
                    execution_results["total_pnl"] += pilot_result.get("expected_profit", 0)
                    execution_results["total_fees"] += pilot_result.get("execution_result", {}).get("fees", 0)
                return execution_results

            # Execute trades for each qualifying candidate
            pilot_trade_executed = False  # Track if pilot trade was executed this cycle
            
            for candidate in filtered_candidates:
                try:
                    # Extract data from pre-built candidate
                    symbol = candidate["symbol"]
                    signal = candidate["signal"]
                    current_price = candidate["current_price"]
                    composite_score = candidate["composite_score"]
                    side = candidate["side"]
                    stop_loss = candidate["stop_loss"]
                    take_profit = candidate["take_profit"]
                    sl_tp_src = candidate["sl_tp_src"]
                    rr_ratio = candidate["risk_reward_ratio"]
                    regime = candidate["regime"]
                    effective_threshold = candidate["effective_threshold"]
                    score_floor = candidate["score_floor"]
                    floor_reason = candidate["floor_reason"]

                    # Early price validation - reject before any processing
                    if current_price is None or current_price <= 0:
                        self.logger.info(f"REJECTED {symbol} {side.upper()} reason=invalid_entry_price")
                        continue

                    # Add required fields for executors
                    signal["symbol"] = symbol
                    signal["current_price"] = current_price
                    signal["price"] = current_price  # Map current_price to price for executors
                    signal["score"] = composite_score  # Map composite_score to score
                    signal["signal_strength"] = abs(composite_score)  # Use absolute composite score as signal strength
                    signal["signal_type"] = side
                    
                    # Add SL/TP to metadata with source information
                    if "metadata" not in signal:
                        signal["metadata"] = {}
                    signal["metadata"]["stop_loss"] = stop_loss
                    signal["metadata"]["take_profit"] = take_profit
                    signal["metadata"]["risk_reward_ratio"] = rr_ratio
                    signal["metadata"]["sl_tp_src"] = sl_tp_src
                    
                    # Add sentiment metadata
                    signal["metadata"]["sentiment_type"] = "bullish" if composite_score > 0 else "bearish"
                    
                    # Add breakout metadata
                    signal["metadata"]["breakout_type"] = "upward" if composite_score > 0 else "downward"
                    
                    # Add volume ratio (mock data for now)
                    signal["metadata"]["volume_ratio"] = 1.5  # Assume 50% above average volume

                    # Select best strategy based on risk-adjusted return
                    strategy_name = self._select_best_strategy(signal)

                    trade_result = self.multi_strategy_executor.execute_strategy(
                        strategy_name=strategy_name,
                        signal=signal,
                        capital=available_capital
                        * 0.1,  # Use 10% of available capital per trade
                    )

                    # Handle rejection cases
                    if trade_result and trade_result.get("status") == "rejected":
                        reason = trade_result.get("reason", "unknown")
                        self.logger.info(f"REJECTED {symbol} {side.upper()} reason={reason}")
                        continue

                    if trade_result and trade_result.get("position_size", 0) > 0:
                        # Add SL/TP info to trade result for logging
                        trade_result["stop_loss"] = stop_loss
                        trade_result["take_profit"] = take_profit
                        trade_result["risk_reward_ratio"] = rr_ratio
                        trade_result["sl_tp_src"] = sl_tp_src
                        
                        # Update portfolio with trade - only proceed if successful
                        portfolio_updated = self._update_portfolio_with_trade(symbol, trade_result)
                        
                        if portfolio_updated:
                            # Log trade to analytics
                            self._log_trade_to_analytics(symbol, trade_result)

                            # Record execution result
                            execution_results["trades"].append(trade_result)
                            execution_results["trades_executed"] += 1
                            execution_results["total_pnl"] += trade_result.get(
                                "expected_profit", 0
                            )
                            execution_results["total_fees"] += trade_result.get(
                                "execution_result", {}
                            ).get("fees", 0)

                            # Enhanced logging for executed trades with threshold and score floor info
                            raw_score = signal.get("metadata", {}).get("normalization", {}).get("raw_composite_score", composite_score)
                            normalized_score = signal.get("metadata", {}).get("normalization", {}).get("normalized_composite_score", composite_score)
                            window_size = signal.get("metadata", {}).get("normalization", {}).get("window_size", 0)
                            
                            # Enhanced SL/TP logging with ATR info
                            atr_value = candidate.get("atr")
                            atr_str = f"{atr_value:.6f}" if atr_value is not None else "NA"
                            
                            # Get price source for transparency
                            price_source = trade_result.get("execution_result", {}).get("price_source", "strategy")
                            
                            # Check if detailed SL/TP logging is enabled
                            sl_tp_logging = self.config.get("logging", {}).get("sl_tp_line", True)
                            if sl_tp_logging:
                                self.logger.info(
                                    f"🎯 {symbol} {side.upper()} qty={trade_result.get('position_size', 0):.4f} @ ${current_price:.2f} "
                                    f"notional=${trade_result.get('position_size', 0) * current_price:.2f} "
                                    f"fees=${trade_result.get('execution_result', {}).get('fees', 0):.2f} "
                                    f"SL=${stop_loss:.2f} TP=${take_profit:.2f} RR={rr_ratio:.2f} "
                                    f"sl_tp_src={sl_tp_src} atr={atr_str} price_src={price_source} "
                                    f"cal_thr={effective_threshold:.3f} score_floor={score_floor:.3f} pre={raw_score:.3f} post={normalized_score:.3f} winN={window_size}"
                                )
                            else:
                                # Simplified logging without SL/TP details
                                self.logger.info(
                                    f"🎯 {symbol} {side.upper()} qty={trade_result.get('position_size', 0):.4f} @ ${current_price:.2f} "
                                    f"notional=${trade_result.get('position_size', 0) * current_price:.2f} "
                                    f"fees=${trade_result.get('execution_result', {}).get('fees', 0):.2f} "
                                    f"RR={rr_ratio:.2f} price_src={price_source} cal_thr={effective_threshold:.3f} score_floor={score_floor:.3f}"
                                )
                        else:
                            # Portfolio update failed - log rejection
                            self.logger.info(f"REJECTED {symbol} {side.upper()} reason=portfolio_update_failed")

                except Exception as e:
                    error_msg = f"Failed to execute trade for {symbol}: {e}"
                    self.logger.error(error_msg)
                    execution_results["errors"].append(error_msg)

            # PILOT TRADE LOGIC: If no trades were executed, try pilot trade
            if execution_results["trades_executed"] == 0 and not pilot_trade_executed:
                pilot_result = self._execute_pilot_trade(signals, available_capital)
                if pilot_result:
                    execution_results["trades"].append(pilot_result)
                    execution_results["trades_executed"] += 1
                    execution_results["total_pnl"] += pilot_result.get("expected_profit", 0)
                    execution_results["total_fees"] += pilot_result.get("execution_result", {}).get("fees", 0)
                    pilot_trade_executed = True

            self.logger.info(
                f"Executed {execution_results['trades_executed']} trades, total PnL: ${execution_results['total_pnl']:.2f}"
            )

        except Exception as e:
            self.logger.error(f"Error executing trades: {e}")
            raise
        
        # Log execution completion timing
        execution_end_time = datetime.now()
        execution_duration = (execution_end_time - execution_start_time).total_seconds()
        self.logger.info(
            f"TRADE_EXECUTION_END: {execution_end_time.isoformat()} "
            f"duration={execution_duration:.3f}s trades={execution_results['trades_executed']}"
        )

        return execution_results

    def _execute_pilot_trade(self, signals: dict[str, Any], available_capital: float) -> Optional[dict[str, Any]]:
        """Execute a pilot trade when no symbols meet the effective threshold.
        
        Pilot trade criteria:
        - score ≥ 0.55
        - RR ≥ config.rr_relax_for_pilot (default 1.60)
        - valid price/liquidity
        - Size = min(1.0% of session cash, normal position sizing)
        - Tag as pilot=True
        
        Args:
            signals: All available signals
            available_capital: Available capital for trading
            
        Returns:
            Pilot trade result or None if no suitable pilot trade found
        """
        self.logger.info("🔍 PILOT: No symbols met effective threshold, searching for pilot trade candidates")
        
        pilot_candidates = []
        
        # Find pilot trade candidates
        for symbol, signal in signals.items():
            try:
                # Get current price
                current_price = get_mark_price(
                    symbol, 
                    self.data_engine, 
                    live_mode=self.config.get("trading", {}).get("live_mode", False)
                )
                
                if not current_price or current_price <= 0:
                    continue
                
                # Get composite score and regime
                composite_score = signal.get("composite_score", 0)
                normalized_score = signal.get("metadata", {}).get("normalization", {}).get("normalized_composite_score", composite_score)
                regime = signal.get("metadata", {}).get("regime", "ranging")
                
                # Pilot criteria: score ≥ 0.55
                if abs(normalized_score) < 0.55:
                    continue
                
                # Determine side based on composite score
                side = "buy" if composite_score > 0 else "sell"
                
                # Get existing SL/TP from signal metadata
                existing_sl = signal.get("metadata", {}).get("stop_loss")
                existing_tp = signal.get("metadata", {}).get("take_profit")
                
                # Derive SL/TP using the same robust three-tier system as regular trades
                try:
                    sl_tp_result = self.risk_manager.derive_sl_tp(
                        entry_price=current_price,
                        side=side,
                        atr=None,  # Will be calculated if needed
                        strategy_sl=existing_sl,
                        strategy_tp=existing_tp,
                        symbol=symbol
                    )
                except ValueError as e:
                    if "no_atr_no_fallback" in str(e):
                        self.logger.debug(f"Pilot trade skipped for {symbol}: no_atr_no_fallback")
                        continue
                    else:
                        raise
                
                stop_loss = sl_tp_result["stop_loss"]
                take_profit = sl_tp_result["take_profit"]
                sl_tp_src = sl_tp_result["source"]
                
                # Calculate risk-reward ratio using the same robust method as regular trades
                try:
                    rr_ratio = self.risk_manager.compute_rr(
                        entry=current_price,
                        sl=stop_loss,
                        tp=take_profit,
                        side=side
                    )
                except ValueError as e:
                    self.logger.debug(f"RR calculation failed for pilot {symbol}: {e}")
                    continue
                
                # Pilot criteria: RR ≥ config threshold
                rr_relax_for_pilot = self.config.get("risk", {}).get("rr_relax_for_pilot", 1.60)
                if rr_ratio < rr_relax_for_pilot:
                    continue
                
                # Valid price/liquidity check (basic validation)
                if not validate_mark_price(current_price, symbol):
                    continue
                
                # Add to pilot candidates with priority score
                pilot_candidates.append({
                    "symbol": symbol,
                    "signal": signal,
                    "current_price": current_price,
                    "composite_score": composite_score,
                    "normalized_score": normalized_score,
                    "side": side,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "sl_tp_src": sl_tp_src,
                    "risk_reward_ratio": rr_ratio,
                    "priority_score": abs(normalized_score) * rr_ratio,  # Higher is better
                    "atr": sl_tp_result.get("atr")
                })
                
            except Exception as e:
                self.logger.debug(f"Error evaluating {symbol} for pilot trade: {e}")
                continue
        
        if not pilot_candidates:
            rr_relax_for_pilot = self.config.get("risk", {}).get("rr_relax_for_pilot", 1.60)
            self.logger.info(f"🔍 PILOT: No candidates meet pilot criteria (score≥0.55, RR≥{rr_relax_for_pilot})")
            return None
        
        # Select best pilot candidate (highest priority score)
        best_candidate = max(pilot_candidates, key=lambda x: x["priority_score"])
        
        self.logger.info(
            f"🚁 PILOT: Selected {best_candidate['symbol']} "
            f"(score={best_candidate['normalized_score']:.3f}, RR={best_candidate['risk_reward_ratio']:.2f})"
        )
        
        # Execute pilot trade with reduced size
        symbol = best_candidate["symbol"]
        signal = best_candidate["signal"]
        current_price = best_candidate["current_price"]
        side = best_candidate["side"]
        stop_loss = best_candidate["stop_loss"]
        take_profit = best_candidate["take_profit"]
        sl_tp_src = best_candidate["sl_tp_src"]
        rr_ratio = best_candidate["risk_reward_ratio"]
        
        # Add required fields for executors
        signal["symbol"] = symbol
        signal["current_price"] = current_price
        signal["price"] = current_price
        signal["score"] = best_candidate["composite_score"]
        signal["signal_strength"] = abs(best_candidate["composite_score"])
        signal["signal_type"] = side
        
        # Add SL/TP to metadata
        if "metadata" not in signal:
            signal["metadata"] = {}
        signal["metadata"]["stop_loss"] = stop_loss
        signal["metadata"]["take_profit"] = take_profit
        signal["metadata"]["risk_reward_ratio"] = rr_ratio
        signal["metadata"]["sl_tp_src"] = sl_tp_src
        signal["metadata"]["sentiment_type"] = "bullish" if best_candidate["composite_score"] > 0 else "bearish"
        signal["metadata"]["breakout_type"] = "upward" if best_candidate["composite_score"] > 0 else "downward"
        signal["metadata"]["volume_ratio"] = 1.5
        
        # Select best strategy
        strategy_name = self._select_best_strategy(signal)
        
        # PILOT SIZING: min(1.0% of session cash, normal position sizing)
        session_cash = self.state_store.get_session_cash(self.current_session_id) if self.state_store else available_capital
        pilot_cash_limit = session_cash * 0.01  # 1% of session cash
        
        # Calculate normal position sizing (10% of available capital)
        normal_capital = available_capital * 0.1
        
        # Use the smaller of the two
        pilot_capital = min(pilot_cash_limit, normal_capital)
        
        self.logger.info(
            f"🚁 PILOT: Using {pilot_capital:.2f} capital "
            f"(1% session={pilot_cash_limit:.2f}, normal={normal_capital:.2f})"
        )
        
        # Execute pilot trade
        trade_result = self.multi_strategy_executor.execute_strategy(
            strategy_name=strategy_name,
            signal=signal,
            capital=pilot_capital
        )
        
        # Handle rejection cases for pilot trades
        if trade_result and trade_result.get("status") == "rejected":
            reason = trade_result.get("reason", "unknown")
            self.logger.info(f"REJECTED PILOT {symbol} {side.upper()} reason={reason}")
            return None
        
        if trade_result and trade_result.get("position_size", 0) > 0:
            # Tag as pilot trade
            trade_result["pilot"] = True
            trade_result["stop_loss"] = stop_loss
            trade_result["take_profit"] = take_profit
            trade_result["risk_reward_ratio"] = rr_ratio
            trade_result["sl_tp_src"] = sl_tp_src
            
            # Update portfolio with pilot trade - only log if successful
            portfolio_updated = self._update_portfolio_with_trade(symbol, trade_result)
            
            if portfolio_updated:
                # Log pilot trade to analytics
                self._log_trade_to_analytics(symbol, trade_result)
                
                # Enhanced logging for pilot trade with score floor
                raw_score = signal.get("metadata", {}).get("normalization", {}).get("raw_composite_score", best_candidate["composite_score"])
                normalized_score = best_candidate["normalized_score"]
                window_size = signal.get("metadata", {}).get("normalization", {}).get("window_size", 0)
                effective_threshold = signal.get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.65)
                score_floor = effective_threshold
                
                # Enhanced SL/TP logging for pilot trades
                atr_value = best_candidate.get("atr")
                atr_str = f"{atr_value:.6f}" if atr_value is not None else "NA"
                
                # Get price source for transparency
                price_source = trade_result.get("execution_result", {}).get("price_source", "strategy")
                
                # Check if detailed SL/TP logging is enabled
                sl_tp_logging = self.config.get("logging", {}).get("sl_tp_line", True)
                if sl_tp_logging:
                    self.logger.info(
                        f"🚁 PILOT {symbol} {side.upper()} qty={trade_result.get('position_size', 0):.4f} @ ${current_price:.2f} "
                        f"notional=${trade_result.get('position_size', 0) * current_price:.2f} "
                        f"fees=${trade_result.get('execution_result', {}).get('fees', 0):.2f} "
                        f"SL=${stop_loss:.2f} TP=${take_profit:.2f} RR={rr_ratio:.2f} "
                        f"sl_tp_src={sl_tp_src} atr={atr_str} price_src={price_source} pilot=True"
                    )
                else:
                    # Simplified logging without SL/TP details
                    self.logger.info(
                        f"🚁 PILOT {symbol} {side.upper()} qty={trade_result.get('position_size', 0):.4f} @ ${current_price:.2f} "
                        f"notional=${trade_result.get('position_size', 0) * current_price:.2f} "
                        f"fees=${trade_result.get('execution_result', {}).get('fees', 0):.2f} "
                        f"RR={rr_ratio:.2f} price_src={price_source} pilot=True"
                    )
                
                return trade_result
            else:
                # Portfolio update failed - pilot trade rejected
                self.logger.info(f"REJECTED PILOT {symbol} {side.upper()} reason=portfolio_update_failed")
                return None
        
        self.logger.info(f"🚁 PILOT: Failed to execute pilot trade for {symbol}")
        return None

    def _update_portfolio_with_trade(
        self, symbol: str, trade_result: dict[str, Any]
    ) -> bool:
        """Update portfolio with trade result using atomic operations and proper cash accounting.

        Args:
            symbol: Trading symbol (will be converted to canonical)
            trade_result: Trade execution result
        """
        # Store original state for rollback
        original_cash = None
        original_positions = None
        original_fees = None
        
        try:
            # Convert to canonical symbol
            canonical_symbol = to_canonical(symbol)
            
            position_size = trade_result.get("position_size", 0)
            execution_result = trade_result.get("execution_result", {})
            entry_price = execution_result.get("entry_price", 0)
            fees = execution_result.get("fees", 0)
            expected_profit = trade_result.get("expected_profit", 0)
            strategy = trade_result.get("strategy", "unknown")

            # Step 1: Validate entry price early - before any portfolio mutations
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Invalid entry_price: {entry_price} for {canonical_symbol}. Rejecting trade.")
                return False

            # Step 2: Capture original state for rollback
            original_cash = self._get_cash_balance()
            original_positions = self.state_store.get_positions(self.current_session_id).copy()
            original_fees = self.portfolio.get("total_fees", 0.0)
            equity_before = self._get_total_equity()

            # Step 3: Calculate cash impact: BUY = -notional - fees, SELL = +notional - fees
            notional_value = abs(position_size) * entry_price
            
            if position_size > 0:  # Buy
                cash_impact = -(notional_value + fees)
                side = "BUY"
            else:  # Sell
                cash_impact = notional_value - fees
                side = "SELL"
            
            new_cash = original_cash + cash_impact
            
            # Step 4: Validate sufficient cash for buy orders
            if position_size > 0 and new_cash < 0:
                self.logger.error(f"Insufficient cash for BUY: need ${notional_value + fees:.2f}, have ${original_cash:.2f}")
                return False

            # Step 5: Update cash balance BEFORE updating positions
            self.state_store.save_cash_equity(
                cash_balance=new_cash,
                total_equity=equity_before,  # Will recalculate after position update
                total_fees=original_fees + fees,
                total_realized_pnl=expected_profit,
                total_unrealized_pnl=0.0,
                session_id=self.current_session_id
            )
            
            # Update portfolio cache
            self.portfolio["cash_balance"] = new_cash
            self.portfolio["total_fees"] = original_fees + fees

            # Step 6: Get existing position and calculate new position values
            existing_position = None
            for pos in original_positions:
                if to_canonical(pos["symbol"]) == canonical_symbol:
                    existing_position = pos
                    break

            # Step 7: Set average cost correctly: avg_cost = (old_qty*old_avg + new_qty*fill_price) / total_qty
            if existing_position:
                old_quantity = existing_position["quantity"]
                old_avg_price = existing_position["entry_price"]
                new_quantity = old_quantity + position_size
                
                # Calculate weighted average price
                if new_quantity != 0:
                    total_cost = (old_quantity * old_avg_price) + (position_size * entry_price)
                    new_avg_price = total_cost / new_quantity
                else:
                    new_avg_price = entry_price
            else:
                new_quantity = position_size
                new_avg_price = entry_price

            # Step 8: Update position in state store
            self.state_store.save_position(
                symbol=canonical_symbol,
                quantity=new_quantity,
                entry_price=new_avg_price,
                current_price=entry_price,
                strategy=strategy,
                session_id=self.current_session_id
            )

            # Step 9: Save trade to persistent store
            trade_side = "buy" if position_size > 0 else "sell"
            self.state_store.save_trade(
                symbol=canonical_symbol,
                side=trade_side,
                quantity=abs(position_size),
                price=entry_price,
                fees=fees,
                realized_pnl=expected_profit,
                strategy=strategy,
                session_id=self.current_session_id
            )
            
            # Step 9b: Commit fill to trade ledger immediately after successful portfolio update
            if self.trade_ledger:
                trade_id = f"{canonical_symbol}_{trade_side}_{int(datetime.now().timestamp() * 1000)}"
                success = self.trade_ledger.commit_fill(
                    trade_id=trade_id,
                    session_id=self.current_session_id,
                    symbol=canonical_symbol,
                    side=trade_side,
                    quantity=position_size,  # Use signed quantity
                    fill_price=entry_price,
                    fees=fees,
                    strategy=strategy
                )
                if success:
                    self.logger.debug(f"Fill committed to trade ledger: {trade_id}")
                else:
                    self.logger.warning(f"Failed to commit fill to trade ledger: {trade_id}")

            # Step 10: Recalculate total equity and validate
            equity_after = self._get_total_equity()
            equity_change = abs(equity_after - equity_before)
            
            # Step 11: Add assertion: abs(equity_before - equity_after) <= epsilon (accounting for fees)
            # For buy orders, equity should remain approximately the same (cash decreases, position value increases)
            # For sell orders, equity should remain approximately the same (cash increases, position value decreases)
            # Small differences are allowed due to fees
            epsilon = fees + 0.01  # Allow for fees plus small rounding
            if equity_change > epsilon:
                self.logger.error(f"Equity validation failed: change=${equity_change:.2f} > epsilon=${epsilon:.2f}")
                raise ValueError(f"Equity validation failed: change=${equity_change:.2f}")
            
            # Step 12: Log comprehensive fill information
            self.logger.info(
                f"FILL: side={side} symbol={canonical_symbol} qty={position_size:.6f} "
                f"fill_price=${entry_price:.4f} notional=${notional_value:.2f} fee=${fees:.4f} "
                f"cash_before=${original_cash:.2f}→cash_after=${new_cash:.2f} "
                f"equity_before=${equity_before:.2f}→equity_after=${equity_after:.2f} "
                f"equity_change=${equity_change:.2f}"
            )

            # Step 13: Update portfolio cache for immediate access
            self.portfolio["last_updated"] = datetime.now()

            # Step 14: Save complete portfolio state
            self._save_portfolio_state()

            self.logger.info(f"Updated portfolio with trade: {canonical_symbol} "
                           f"{position_size} @ ${entry_price:.4f}, "
                           f"cash_impact=${cash_impact:.2f}, equity_change=${equity_change:.2f}")
            
            return True  # Success

        except Exception as e:
            self.logger.error(f"Error updating portfolio: {e}")
            
            # Step 15: If any step fails, rollback all changes and return error
            if original_cash is not None:
                try:
                    self.logger.warning("Rolling back portfolio changes due to error")
                    
                    # Restore original cash balance
                    self.state_store.save_cash_equity(
                        cash_balance=original_cash,
                        total_equity=self._get_total_equity(),  # Recalculate without the failed trade
                        total_fees=original_fees,
                        total_realized_pnl=0.0,
                        total_unrealized_pnl=0.0,
                        session_id=self.current_session_id
                    )
                    
                    # Restore original positions
                    for pos in original_positions:
                        self.state_store.save_position(
                            symbol=pos["symbol"],
                            quantity=pos["quantity"],
                            entry_price=pos["entry_price"],
                            current_price=pos["current_price"],
                            strategy=pos["strategy"],
                            session_id=self.current_session_id
                        )
                    
                    # Restore portfolio cache
                    self.portfolio["cash_balance"] = original_cash
                    self.portfolio["total_fees"] = original_fees
                    self.portfolio["last_updated"] = datetime.now()
                    
                    self.logger.info("Portfolio rollback completed successfully")
                    
                except Exception as rollback_error:
                    self.logger.error(f"Failed to rollback portfolio changes: {rollback_error}")
            
            return False  # Failed

    def _update_position_prices(self) -> None:
        """Update current prices for all positions."""
        try:
            for symbol in list(self.portfolio["positions"].keys()):
                try:
                    # Get current price from data engine
                    ticker_data = self.data_engine.get_ticker(symbol)
                    if ticker_data and ticker_data.get("price", 0) > 0:
                        current_price = ticker_data["price"]
                        
                        # Update in-memory position
                        pos = self.portfolio["positions"][symbol]
                        pos["current_price"] = current_price
                        pos["unrealized_pnl"] = (current_price - pos["entry_price"]) * pos["quantity"]
                        
                        # Update in persistent store
                        self.state_store.update_position_price(symbol, current_price)
                        
                except Exception as e:
                    self.logger.warning(f"Failed to update price for {symbol}: {e}")
            
            # Save updated portfolio state
            self._save_portfolio_state()
            
        except Exception as e:
            self.logger.error(f"Error updating position prices: {e}")

    def _log_trade_to_analytics(
        self, symbol: str, trade_result: dict[str, Any]
    ) -> None:
        """Log trade to analytics system.

        Args:
            symbol: Trading symbol
            trade_result: Trade execution result
        """
        try:
            execution_result = trade_result.get("execution_result", {})

            # Extract trade details
            side = "buy"  # Simplified - could be determined from trade logic
            quantity = trade_result.get("position_size", 0)
            entry_price = trade_result.get("entry_price", 0)
            exit_price = entry_price * 1.02  # Simplified - assume 2% profit
            fees = execution_result.get("fees", 0)
            
            # Check if this is a pilot trade
            is_pilot = trade_result.get("pilot", False)

            # Log to profit analytics with pilot flag
            trade_data = {
                "symbol": symbol,
                "strategy": trade_result.get("strategy", "unknown"),
                "side": side,
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "fees": fees,
                "pilot": is_pilot,
                "metadata": {
                    "pilot": is_pilot,
                    "stop_loss": trade_result.get("stop_loss"),
                    "take_profit": trade_result.get("take_profit"),
                    "risk_reward_ratio": trade_result.get("risk_reward_ratio"),
                }
            }
            
            self.profit_analytics.log_trade(trade_data)

        except Exception as e:
            self.logger.error(f"Error logging trade to analytics: {e}")

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        """Get a consistent portfolio snapshot for all displays.
        
        Returns:
            Dictionary with consistent portfolio state including positions, cash, equity, and count
        """
        try:
            # Get consistent data from single source
            cash_balance = self._get_cash_balance()
            active_positions = self._get_active_positions()
            
            # Calculate equity directly to avoid circular dependency with _get_total_equity()
            total_position_value = sum(pos.get("value", 0.0) for pos in active_positions.values())
            total_equity = cash_balance + total_position_value
            
            # Calculate position metrics
            position_count = len(active_positions)
            
            # Get detailed position breakdown
            positions_detail = {}
            for symbol, position in active_positions.items():
                positions_detail[symbol] = {
                    "quantity": position.get("quantity", 0.0),
                    "entry_price": position.get("entry_price", 0.0),
                    "current_price": position.get("current_price", 0.0),
                    "value": position.get("value", 0.0),
                    "unrealized_pnl": position.get("unrealized_pnl", 0.0),
                    "strategy": position.get("strategy", "unknown")
                }
            
            snapshot = {
                "cash_balance": cash_balance,
                "total_equity": total_equity,
                "position_count": position_count,
                "total_position_value": total_position_value,
                "positions": positions_detail,
                "active_positions": active_positions,  # Keep original for compatibility
                "timestamp": datetime.now().isoformat(),
                "session_id": self.current_session_id
            }
            
            return snapshot
            
        except Exception as e:
            self.logger.error(f"Error creating portfolio snapshot: {e}")
            # Return safe defaults
            return {
                "cash_balance": 0.0,
                "total_equity": 0.0,
                "position_count": 0,
                "total_position_value": 0.0,
                "positions": {},
                "active_positions": {},
                "timestamp": datetime.now().isoformat(),
                "session_id": self.current_session_id
            }

    def _get_total_equity(self) -> float:
        """Get total portfolio equity using session-scoped data and mark prices.
        
        Formula: equity = session_cash + Σ(session_qty * get_mark_price(symbol))
        
        Returns:
            Total equity value for current session
        """
        # Get session-scoped cash balance
        cash_balance = self._get_cash_balance()
        total_equity = cash_balance
        
        # Get session-scoped positions (now with calculated values)
        positions = self._get_active_positions()
        
        priced_positions = []
        unpriced_positions = []
        long_value = 0.0
        short_value = 0.0
        
        for symbol, position in positions.items():
            # Ensure symbol is canonical
            canonical_symbol = to_canonical(symbol)
            quantity = position["quantity"]
            position_value = position.get("value", 0.0)
            
            # Skip positions with zero quantity
            if quantity == 0:
                continue
                
            try:
                # Get live mark price for validation
                mark_price = get_mark_price(
                    canonical_symbol, 
                    self.data_engine, 
                    live_mode=self.config.get("trading", {}).get("live_mode", False)
                )
                
                if mark_price and validate_mark_price(mark_price, canonical_symbol):
                    # Add position value to total equity (both long and short positions)
                    total_equity += position_value
                    
                    # Track long vs short values
                    if quantity > 0:
                        long_value += position_value
                    else:
                        short_value += position_value
                    
                    # Get average cost and P&L from position data
                    avg_cost = position.get("entry_price", 0.0)
                    unrealized_pnl = position.get("unrealized_pnl", 0.0)
                    
                    priced_positions.append({
                        "symbol": canonical_symbol,
                        "quantity": quantity,
                        "price": mark_price,
                        "value": position_value,
                        "avg_cost": avg_cost,
                        "unrealized_pnl": unrealized_pnl
                    })
                    
                    self.logger.debug(f"Valued {canonical_symbol}: qty={quantity} @ ${mark_price:.4f} = ${position_value:.2f} avg_cost=${avg_cost:.4f} pnl=${unrealized_pnl:.2f}")
                else:
                    # Track unpriced positions (missing marks only, never zero-out totals)
                    unpriced_positions.append({
                        "symbol": canonical_symbol,
                        "quantity": quantity,
                        "reason": "no_valid_mark_price"
                    })
                    
                    self.logger.warning(f"Skipping {canonical_symbol} position valuation - no valid mark price available")
                    
            except Exception as e:
                self.logger.error(f"Error valuing position {canonical_symbol}: {e}")
                unpriced_positions.append({
                    "symbol": canonical_symbol,
                    "quantity": quantity,
                    "reason": f"error: {e}"
                })
                # Continue with other positions
        
        # Calculate position count directly (avoid circular dependency with get_portfolio_snapshot)
        valuation_count = len(priced_positions)
        active_count = len(positions)
        
        # Validate position count consistency across all sources
        # Note: We can't use get_portfolio_snapshot here as it would create circular dependency
        if valuation_count == active_count:
            self.logger.debug(
                f"POSITION_COUNT: valuation={valuation_count} active={active_count} (consistent)"
            )
        else:
            self.logger.warning(
                f"POSITION_COUNT: valuation={valuation_count} active={active_count} (INCONSISTENT)"
            )
        
        # VALUATION logging moved to ui_panels system to avoid duplicates
        # Log comprehensive valuation summary
        # self.logger.info(
        #     f"VALUATION: equity=${total_equity:.2f} cash=${cash_balance:.2f} "
        #     f"long_val=${long_value:.2f} short_val=${short_value:.2f} "
        #     f"positions={valuation_count}"
        # )
        
        # Log per-position breakdown with average cost and P&L
        # Commented out to avoid duplicate logs - position info is shown in cycle summary
        # for position in priced_positions:
        #     symbol = position["symbol"]
        #     quantity = position["quantity"]
        #     price = position["price"]
        #     value = position["value"]
        #     avg_cost = position["avg_cost"]
        #     unrealized_pnl = position["unrealized_pnl"]
        #     self.logger.info(
        #         f"POSITION: {symbol} qty={quantity:.6f} mark=${price:.4f} avg_cost=${avg_cost:.4f} value=${value:.2f} pnl=${unrealized_pnl:.2f}"
        #     )
        
        # Log summary for unpriced positions if any
        if unpriced_positions:
            self.logger.warning(
                f"UNPRICED: {len(unpriced_positions)} positions without valid prices: "
                f"{[pos['symbol'] for pos in unpriced_positions]}"
            )
        
        # Update portfolio equity in memory (for caching)
        self.portfolio["equity"] = total_equity
        return total_equity

    def _get_active_positions(self) -> dict[str, dict[str, Any]]:
        """Get active positions from session-scoped state store with calculated values.

        Returns:
            Dictionary of active positions for current session with calculated values
        """
        try:
            if not self.current_session_id:
                raise RuntimeError("No session ID available - session binding failed")
            
            # Get session-scoped positions (state store is already session-scoped)
            positions_list = self.state_store.get_positions(self.current_session_id)
            # Convert list to dictionary for compatibility
            positions_dict = {}
            for position in positions_list:
                symbol = position["symbol"]
                quantity = position["quantity"]
                
                # Calculate current position value using mark price
                position_value = 0.0
                mark_price = None
                
                try:
                    # Get live mark price for valuation
                    canonical_symbol = to_canonical(symbol)
                    mark_price = get_mark_price(
                        canonical_symbol, 
                        self.data_engine, 
                        live_mode=self.config.get("trading", {}).get("live_mode", False)
                    )
                    
                    if mark_price and validate_mark_price(mark_price, canonical_symbol):
                        # Calculate position value as quantity * mark_price
                        position_value = quantity * mark_price
                        
                        # Calculate P&L using average cost basis
                        avg_cost = position["entry_price"]
                        
                        # Ensure P&L ≈ 0 immediately after entry (before market moves)
                        if abs(mark_price - avg_cost) < 0.01:  # Within 1 cent tolerance
                            unrealized_pnl = 0.0
                        else:
                            if quantity > 0:  # Long position
                                unrealized_pnl = (mark_price - avg_cost) * quantity
                            else:  # Short position
                                unrealized_pnl = (avg_cost - mark_price) * abs(quantity)
                        
                        self.logger.debug(f"Position {canonical_symbol}: qty={quantity} mark=${mark_price:.4f} avg_cost=${avg_cost:.4f} value=${position_value:.2f} pnl=${unrealized_pnl:.2f}")
                    else:
                        self.logger.warning(f"No valid mark price for {canonical_symbol}, using entry price for valuation")
                        mark_price = position["entry_price"]
                        position_value = quantity * mark_price
                        unrealized_pnl = 0.0  # No P&L when using entry price
                        
                except Exception as e:
                    self.logger.warning(f"Error calculating value for {symbol}: {e}, using entry price")
                    mark_price = position["entry_price"]
                    position_value = quantity * mark_price
                    unrealized_pnl = 0.0  # No P&L when using entry price
                
                positions_dict[symbol] = {
                    "quantity": quantity,
                    "entry_price": position["entry_price"],
                    "current_price": mark_price or position.get("current_price", position["entry_price"]),
                    "value": position_value,
                    "unrealized_pnl": unrealized_pnl,
                    "strategy": position.get("strategy", "unknown")
                }
            return positions_dict
        except Exception as e:
            self.logger.error(f"Error getting session positions from state store: {e}")
            raise RuntimeError(f"Failed to get positions for session {self.current_session_id}: {e}")

    def _get_cash_balance(self) -> float:
        """Get cash balance from session-scoped state store.

        Returns:
            Cash balance for current session
        """
        try:
            if not self.current_session_id:
                raise RuntimeError("No session ID available - session binding failed")
            
            # Get session-scoped cash balance
            return self.state_store.get_session_cash(self.current_session_id)
        except Exception as e:
            self.logger.error(f"Error getting session cash balance: {e}")
            raise RuntimeError(f"Failed to get cash balance for session {self.current_session_id}: {e}")

    def _get_available_capital(self) -> float:
        """Get available capital for trading from authoritative state store.

        Returns:
            Available capital
        """
        try:
            cash_balance = self._get_cash_balance()
            return max(0, cash_balance)
        except Exception as e:
            self.logger.error(f"Error getting available capital: {e}")
            return max(0, self.portfolio.get("cash_balance", 0.0))

    def cleanup(self) -> None:
        """Cleanup resources and close connections."""
        try:
            if self.state_store:
                self.state_store.close()
                self.logger.info("State store connection closed")
            
            self.logger.info("Trading system cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    async def run_trading_cycle(self) -> dict[str, Any]:
        """Run one complete trading cycle.

        Returns:
            Cycle results dictionary
        """
        if not self.initialized:
            raise RuntimeError("Trading system not initialized")

        # Validate session_id before each cycle
        if not self.current_session_id:
            raise RuntimeError("session_id not set - cannot run trading cycle without valid session")

        self.cycle_count += 1
        cycle_start_time = datetime.now()

        self.logger.info(f"Starting trading cycle #{self.cycle_count}")

        cycle_results = {
            "cycle_id": f"cycle_{self.cycle_count}",
            "timestamp": cycle_start_time.isoformat(),
            "duration": 0.0,
            "market_data": {},
            "signals": {},
            "execution_results": {},
            "portfolio_snapshot": {},
            "errors": [],
        }

        try:
            # Get trading symbols from config
            symbols = self.config.get("trading", {}).get(
                "symbols", ["BTC/USDT", "ETH/USDT", "ADA/USDT"]
            )

            # 1. Get comprehensive market data
            self.logger.info("Step 1: Getting comprehensive market data")
            market_data = await self._get_comprehensive_market_data(symbols)
            cycle_results["market_data"] = market_data

            # 1.5. Update position prices with latest market data
            self.logger.info("Step 1.5: Updating position prices")
            self._update_position_prices()

            # 2. Generate all signals
            self.logger.info("Step 2: Generating trading signals")
            signals = await self._generate_all_signals(market_data)
            cycle_results["signals"] = signals

            # 3. Execute profit-optimized trades
            self.logger.info("Step 3: Executing profit-optimized trades")
            execution_results = await self._execute_profit_optimized_trades(signals)
            cycle_results["execution_results"] = execution_results

            # 4. Update portfolio (placeholder)
            portfolio_update_start = datetime.now()
            self.logger.info(f"PORTFOLIO_UPDATE_START: {portfolio_update_start.isoformat()}")
            self.logger.info("Step 4: Updating portfolio")
            # Portfolio updates are handled in _update_portfolio_with_trade
            
            # Log portfolio update completion
            portfolio_update_end = datetime.now()
            portfolio_update_duration = (portfolio_update_end - portfolio_update_start).total_seconds()
            self.logger.info(
                f"PORTFOLIO_UPDATE_END: {portfolio_update_end.isoformat()} "
                f"duration={portfolio_update_duration:.3f}s"
            )

            # 5. Analytics and logging
            self.logger.info("Step 5: Analytics and logging")
            
            # Generate comprehensive cycle summary
            self._log_cycle_summary(cycle_results, execution_results)

            # Log trading cycle with actual data
            cycle_log_data = {
                "cycle_id": cycle_results["cycle_id"],
                "timestamp": cycle_start_time,
                "symbol": "PORTFOLIO",  # Portfolio-level cycle
                "strategy": "composite",
                "equity": {
                    "current_equity": self._get_total_equity(),
                    "previous_equity": self._get_total_equity()
                    - execution_results.get("total_pnl", 0),
                },
                "positions": self._get_active_positions(),  # Use actual positions data
                "decisions": {
                    "risk_score": 0.3,
                    "confidence": 0.7,
                    "signals_generated": len(signals),
                    "trades_executed": execution_results.get("trades_executed", 0),
                },
                "trades": execution_results.get("trades", []),  # Use actual trades data
                "metadata": {
                    "cycle_count": self.cycle_count,
                    "symbols_analyzed": len(symbols),
                },
            }

            try:
                self.profit_logger.log_trading_cycle(cycle_log_data)
            except Exception as e:
                self.logger.error(f"Error in profit logger: {e}")
                self.logger.error(f"Cycle log data: {cycle_log_data}")

            # Update analytics equity from session cash + MTM
            try:
                session_cash = self._get_cash_balance()
                positions = self._get_active_positions()
                self.profit_analytics.update_equity_from_session(session_cash, positions)
            except Exception as e:
                self.logger.error(f"Error updating analytics equity: {e}")
            
            # Ensure all trades are committed to state store before generating summary
            self._ensure_trades_committed()
            
            # Generate profit report using state store trades
            try:
                profit_report = self.profit_analytics.generate_profit_report(
                    state_store=self.state_store,
                    session_id=self.current_session_id
                )
            except Exception as e:
                self.logger.error(f"Error in profit analytics: {e}")
                profit_report = {}

            # Log daily summary if it's a new day
            try:
                # Initialize daily_summary_data with safe defaults
                daily_summary_data = {
                    "date": datetime.now().date(),
                    "timestamp": datetime.now(),
                    "performance": {
                        "win_rate": 0.0,
                        "sharpe_ratio": 0.0,
                        "max_drawdown": 0.0,
                        "total_return": 0.0,
                        "profit_factor": 0.0,
                    },
                    "trading_activity": {
                        "total_trades": 0,
                        "winning_trades": 0,
                        "losing_trades": 0,
                        "total_volume": 0.0,
                        "total_fees": 0.0,
                    },
                    "equity": {
                        "start_equity": self.portfolio["equity"] - execution_results.get("total_pnl", 0),
                        "end_equity": self.portfolio["equity"],
                    },
                    "risk_metrics": {
                        "current_drawdown": 0.0,
                        "volatility": 0.02,  # Placeholder
                        "var_95": 0.03,  # Placeholder
                    },
                    "strategy_performance": {},
                    "metadata": {"cycle_count": self.cycle_count},
                }
                
                # Update with actual data if available
                if self._should_log_daily_summary():
                    # Query trade ledger for current session and date
                    current_date = datetime.now().date().isoformat()
                    ledger_metrics = {}
                    
                    if self.trade_ledger:
                        try:
                            ledger_metrics = self.trade_ledger.calculate_daily_metrics(
                                self.current_session_id, current_date
                            )
                            
                            # Log ledger summary
                            entries_count = ledger_metrics.get("total_trades", 0)
                            self.logger.info(f"summary_src=ledger entries={entries_count} trades_executed={entries_count}")
                            
                        except Exception as e:
                            self.logger.error(f"Failed to query trade ledger: {e}")
                            ledger_metrics = {}
                    
                    # Use ledger metrics if available, otherwise fall back to profit report
                    if ledger_metrics and ledger_metrics.get("total_trades", 0) > 0:
                        # Use ledger data as source of truth
                        daily_summary_data["trading_activity"] = {
                            "total_trades": ledger_metrics.get("total_trades", 0),
                            "total_volume": ledger_metrics.get("total_volume", 0.0),
                            "total_fees": ledger_metrics.get("total_fees", 0.0),
                            "total_notional": ledger_metrics.get("total_notional", 0.0),
                            "buy_trades": ledger_metrics.get("buy_trades", 0),
                            "sell_trades": ledger_metrics.get("sell_trades", 0),
                            "symbols_traded": ledger_metrics.get("symbols_traded", []),
                            "strategies_used": ledger_metrics.get("strategies_used", [])
                        }
                        
                        # Validate trade counts match between execution and ledger
                        execution_trades = execution_results.get("trades_executed", 0)
                        ledger_trades = ledger_metrics.get("total_trades", 0)
                        
                        if execution_trades != ledger_trades:
                            self.logger.warning(f"Trade count mismatch: execution={execution_trades}, ledger={ledger_trades}")
                        else:
                            self.logger.info(f"Trade count validation passed: {execution_trades} trades")
                    else:
                        # Fall back to profit report data
                        execution_trades = execution_results.get("trades_executed", 0)
                        summary_trades = profit_report.get("total_trades", 0)
                        
                        if execution_trades != summary_trades:
                            self.logger.warning(f"Trade count mismatch: execution={execution_trades}, summary={summary_trades}")
                        else:
                            self.logger.info(f"Trade count validation passed: {execution_trades} trades")
                    
                    daily_summary_data.update({
                        "performance": {
                            "win_rate": profit_report.get("win_rate", 0.0),
                            "sharpe_ratio": profit_report.get("sharpe_ratio", 0.0),
                            "max_drawdown": profit_report.get("max_drawdown", 0.0),
                            "total_return": profit_report.get("total_return", 0.0),
                            "profit_factor": profit_report.get("profit_factor", 0.0),
                        },
                        "trading_activity": {
                            "total_trades": profit_report.get("total_trades", 0),
                            "winning_trades": profit_report.get("winning_trades", 0),
                            "losing_trades": profit_report.get("losing_trades", 0),
                            "total_volume": profit_report.get("total_trade_volume", 0.0),
                            "total_fees": profit_report.get("total_fees", 0.0),
                        },
                        "risk_metrics": {
                            "current_drawdown": profit_report.get("current_drawdown", 0.0),
                            "volatility": 0.02,  # Placeholder
                            "var_95": 0.03,  # Placeholder
                        },
                        "strategy_performance": profit_report.get("strategy_performance", {}),
                    })

                self.profit_logger.log_daily_summary(daily_summary_data)
            except Exception as e:
                self.logger.error(f"Error in daily summary: {e}")

            # Portfolio snapshot using consistent state
            try:
                portfolio_snapshot = self.get_portfolio_snapshot()
                cycle_results["portfolio_snapshot"] = {
                    "total_equity": portfolio_snapshot["total_equity"],
                    "cash_balance": portfolio_snapshot["cash_balance"],
                    "active_positions": portfolio_snapshot["position_count"],
                    "total_position_value": portfolio_snapshot["total_position_value"],
                    "available_capital": self._get_available_capital(),
                    "positions_detail": portfolio_snapshot["positions"],
                    "timestamp": portfolio_snapshot["timestamp"]
                }
            except Exception as e:
                self.logger.error(f"Error in portfolio snapshot: {e}")
                cycle_results["portfolio_snapshot"] = {}

            # Calculate cycle duration
            cycle_end_time = datetime.now()
            cycle_duration = (cycle_end_time - cycle_start_time).total_seconds()
            cycle_results["duration"] = cycle_duration

            self.last_cycle_time = cycle_end_time

            self.logger.info(
                f"Trading cycle #{self.cycle_count} completed in {cycle_duration:.2f}s"
            )
            self.logger.info(f"Portfolio equity: ${self._get_total_equity():,.2f}")
            self.logger.info(
                f"Available capital: ${self._get_available_capital():,.2f}"
            )

        except Exception as e:
            error_msg = f"Error in trading cycle #{self.cycle_count}: {e}"
            self.logger.error(error_msg)
            cycle_results["errors"].append(error_msg)

        return cycle_results

    def _ensure_trades_committed(self) -> None:
        """Ensure all trades are committed to the state store before generating summaries.
        
        This method ensures that any pending trades are properly saved to the trade ledger
        before the daily summary is generated.
        """
        try:
            # Force a save of the current portfolio state to ensure all trades are persisted
            self._save_portfolio_state()
            
            # Verify trades are accessible from state store
            if self.state_store and self.current_session_id:
                trades = self.state_store.get_trades()
                session_trades = [t for t in trades if t.get('session_id') == self.current_session_id]
                self.logger.debug(f"Verified {len(session_trades)} trades committed to state store for session {self.current_session_id}")
            
        except Exception as e:
            self.logger.error(f"Error ensuring trades are committed: {e}")

    def _should_log_daily_summary(self) -> bool:
        """Check if daily summary should be logged.

        Returns:
            True if daily summary should be logged
        """
        if not self.last_cycle_time:
            return True

        # Log daily summary if it's been more than 24 hours
        time_since_last = datetime.now() - self.last_cycle_time
        return time_since_last.total_seconds() > 86400  # 24 hours

    async def run(self, max_cycles: Optional[int] = None) -> None:
        """Run the trading system.

        Args:
            max_cycles: Maximum number of cycles to run (None for infinite)
        """
        if not self.initialized:
            self.initialize()

        self.running = True
        self.logger.info("Starting trading system")

        try:
            cycle_count = 0

            while self.running:
                if max_cycles and cycle_count >= max_cycles:
                    self.logger.info(f"Reached maximum cycles ({max_cycles}), stopping")
                    break

                try:
                    # Run one trading cycle
                    cycle_results = await self.run_trading_cycle()
                    cycle_count += 1

                    # Sleep between cycles
                    sleep_duration = self.config.get("trading", {}).get(
                        "cycle_interval", 300
                    )  # 5 minutes default
                    self.logger.info(
                        f"Sleeping for {sleep_duration} seconds until next cycle"
                    )
                    await asyncio.sleep(sleep_duration)

                except KeyboardInterrupt:
                    self.logger.info(
                        "Received keyboard interrupt, stopping trading system"
                    )
                    break
                except Exception as e:
                    self.logger.error(f"Error in trading cycle: {e}")
                    # Continue running despite errors
                    await asyncio.sleep(30)  # Wait 1 minute before retrying

        except Exception as e:
            self.logger.error(f"Fatal error in trading system: {e}")
            raise
        finally:
            self.running = False
            self.logger.info("Trading system stopped")

    def stop(self) -> None:
        """Stop the trading system."""
        self.running = False
        self.logger.info("Trading system stop requested")

    def get_system_status(self) -> dict[str, Any]:
        """Get current system status.

        Returns:
            System status dictionary
        """
        return {
            "initialized": self.initialized,
            "running": self.running,
            "cycle_count": self.cycle_count,
            "last_cycle_time": self.last_cycle_time.isoformat()
            if self.last_cycle_time
            else None,
            "portfolio": {
                "total_equity": self._get_total_equity(),
                "cash_balance": self._get_cash_balance(),
                "active_positions": len(self._get_active_positions()),
                "available_capital": self._get_available_capital(),
            },
            "config_loaded": self.config_manager is not None,
            "components_initialized": {
                "data_engine": self.data_engine is not None,
                "signal_engine": self.signal_engine is not None,
                "risk_manager": self.risk_manager is not None,
                "portfolio_manager": self.portfolio_manager is not None,
                "order_manager": self.order_manager is not None,
                "multi_strategy_executor": self.multi_strategy_executor is not None,
                "profit_analytics": self.profit_analytics is not None,
                "profit_logger": self.profit_logger is not None,
            },
        }

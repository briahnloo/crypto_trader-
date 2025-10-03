"""
Profit-maximizing trading system orchestration.
"""

import asyncio
from datetime import datetime
from typing import Any, Optional

from .analytics import ProfitAnalytics, ProfitLogger
from .core.config_manager import ConfigManager
from .core.logging_utils import LoggerMixin
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

    def initialize(self) -> None:
        """Initialize all system components."""
        if self.initialized:
            self.logger.info("Trading system already initialized")
            return

        self.logger.info("Initializing ProfitMaximizingTradingSystem...")

        try:
            # Load configuration
            self.config_manager = ConfigManager(self.config_path)
            self.config = self.config_manager.to_dict()
            self.logger.info("Configuration loaded successfully")

            # Initialize data engine
            self.data_engine = ProfitOptimizedDataEngine()
            self.data_engine.initialize()
            self.logger.info("Data engine initialized")

            # Initialize signal engine
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
            self.profit_analytics.initialize()
            self.logger.info("Profit analytics initialized")

            # Initialize profit logger
            logger_config = self.config.get("logging", {})
            self.profit_logger = ProfitLogger(logger_config)
            self.profit_logger.initialize()
            self.logger.info("Profit logger initialized")

            # Initialize state store
            db_path = self.config.get("state", {}).get("db_path", "trading_state.db")
            self.state_store = StateStore(db_path)
            self.state_store.initialize()
            self.logger.info("State store initialized")

            # Load existing state or initialize with config values
            self._load_or_initialize_portfolio()

            self.initialized = True
            self.logger.info("Trading system initialization complete")

        except Exception as e:
            self.logger.error(f"Failed to initialize trading system: {e}")
            raise

    def _load_or_initialize_portfolio(self) -> None:
        """Load existing portfolio state or initialize with default values."""
        try:
            # Try to load existing state
            latest_cash_equity = self.state_store.get_latest_cash_equity()
            existing_positions = self.state_store.get_positions()
            
            if latest_cash_equity and existing_positions:
                # Load existing state
                self.portfolio["cash_balance"] = latest_cash_equity["cash_balance"]
                self.portfolio["equity"] = latest_cash_equity["total_equity"]
                self.portfolio["total_fees"] = latest_cash_equity["total_fees"]
                
                # Load positions
                for pos in existing_positions:
                    symbol = pos["symbol"]
                    self.portfolio["positions"][symbol] = {
                        "quantity": pos["quantity"],
                        "entry_price": pos["entry_price"],
                        "current_price": pos["current_price"],
                        "unrealized_pnl": pos["unrealized_pnl"],
                        "strategy": pos["strategy"]
                    }
                
                self.logger.info(f"Loaded existing portfolio state: equity=${self.portfolio['equity']:,.2f}, positions={len(self.portfolio['positions'])}")
            else:
                # Initialize with config values
                initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
                self.portfolio["equity"] = initial_capital
                self.portfolio["cash_balance"] = initial_capital
                self.portfolio["total_fees"] = 0.0
                
                # Save initial state
                self._save_portfolio_state()
                self.logger.info(f"Initialized new portfolio: equity=${initial_capital:,.2f}")
                
        except Exception as e:
            self.logger.error(f"Failed to load/initialize portfolio: {e}")
            # Fallback to default initialization
            initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            self.portfolio["equity"] = initial_capital
            self.portfolio["cash_balance"] = initial_capital
            self.portfolio["total_fees"] = 0.0

    def _save_portfolio_state(self) -> None:
        """Save current portfolio state to persistent store."""
        try:
            # Calculate totals
            total_positions_value = sum(
                pos["quantity"] * pos["current_price"] 
                for pos in self.portfolio["positions"].values()
            )
            total_unrealized_pnl = sum(
                pos["unrealized_pnl"] 
                for pos in self.portfolio["positions"].values()
            )
            
            # Save cash/equity
            self.state_store.save_cash_equity(
                cash_balance=self.portfolio["cash_balance"],
                total_equity=self.portfolio["equity"],
                total_fees=self.portfolio["total_fees"],
                total_realized_pnl=0.0,  # Would need to track this separately
                total_unrealized_pnl=total_unrealized_pnl
            )
            
            # Save portfolio snapshot
            self.state_store.save_portfolio_snapshot(
                total_equity=self.portfolio["equity"],
                cash_balance=self.portfolio["cash_balance"],
                total_positions_value=total_positions_value,
                total_unrealized_pnl=total_unrealized_pnl,
                position_count=len(self.portfolio["positions"])
            )
            
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

        market_data = {
            "timestamp": datetime.now().isoformat(),
            "symbols": symbols,
            "ticker_data": {},
            "ohlcv_data": {},
            "sentiment_data": {},
            "on_chain_data": {},
            "whale_activity": {},
        }

        try:
            # Get ticker data for all symbols
            for symbol in symbols:
                try:
                    ticker = self.data_engine.get_ticker(symbol)
                    market_data["ticker_data"][symbol] = ticker
                except Exception as e:
                    self.logger.warning(f"Failed to get ticker for {symbol}: {e}")
                    market_data["ticker_data"][symbol] = None

            # Get OHLCV data for all symbols
            timeframe = self.config.get("trading", {}).get("timeframe", "1h")
            limit = self.config.get("trading", {}).get("ohlcv_limit", 100)

            for symbol in symbols:
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

        except Exception as e:
            self.logger.error(f"Error generating signals: {e}")
            raise

        return all_signals

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
        self.logger.debug("Executing profit-optimized trades")

        execution_results = {
            "timestamp": datetime.now().isoformat(),
            "trades_executed": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "trades": [],
            "errors": [],
        }

        try:
            # Get available capital
            available_capital = self._get_available_capital()

            # Filter signals by minimum score threshold
            min_score = self.config.get("trading", {}).get("min_signal_score", 0.15)
            filtered_signals = {
                symbol: signal
                for symbol, signal in signals.items()
                if signal.get("composite_score", 0) >= min_score
            }

            if not filtered_signals:
                self.logger.info("No signals meet minimum score threshold")
                return execution_results

            # Execute trades for each qualifying signal
            for symbol, signal in filtered_signals.items():
                try:
                    # Get current price
                    ticker_data = self.data_engine.get_ticker(symbol)
                    current_price = ticker_data.get("price", 0) if ticker_data else 0

                    if current_price <= 0:
                        self.logger.warning(
                            f"Invalid price for {symbol}: {current_price}"
                        )
                        continue

                    # Add required fields for executors
                    signal["symbol"] = symbol
                    signal["current_price"] = current_price
                    signal["price"] = current_price  # Map current_price to price for executors
                    signal["score"] = signal.get("composite_score", 0)  # Map composite_score to score
                    signal["signal_strength"] = abs(signal.get("composite_score", 0))  # Use absolute composite score as signal strength
                    
                    # Add signal_type based on composite score
                    signal["signal_type"] = "buy" if signal.get("composite_score", 0) > 0 else "sell"
                    
                    # Add metadata for executors
                    if "metadata" not in signal:
                        signal["metadata"] = {}
                    
                    # Add sentiment metadata
                    signal["metadata"]["sentiment_type"] = "bullish" if signal.get("composite_score", 0) > 0 else "bearish"
                    
                    # Add breakout metadata
                    signal["metadata"]["breakout_type"] = "upward" if signal.get("composite_score", 0) > 0 else "downward"
                    
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

                    if trade_result and trade_result.get("position_size", 0) > 0:
                        # Update portfolio with trade
                        self._update_portfolio_with_trade(symbol, trade_result)

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

                        self.logger.info(
                            f"Executed trade for {symbol}: size={trade_result.get('position_size', 0):.4f}, profit=${trade_result.get('expected_profit', 0):.2f}"
                        )

                except Exception as e:
                    error_msg = f"Failed to execute trade for {symbol}: {e}"
                    self.logger.error(error_msg)
                    execution_results["errors"].append(error_msg)

            self.logger.info(
                f"Executed {execution_results['trades_executed']} trades, total PnL: ${execution_results['total_pnl']:.2f}"
            )

        except Exception as e:
            self.logger.error(f"Error executing trades: {e}")
            raise

        return execution_results

    def _update_portfolio_with_trade(
        self, symbol: str, trade_result: dict[str, Any]
    ) -> None:
        """Update portfolio with trade result.

        Args:
            symbol: Trading symbol
            trade_result: Trade execution result
        """
        try:
            position_size = trade_result.get("position_size", 0)
            entry_price = trade_result.get("entry_price", 0)
            execution_result = trade_result.get("execution_result", {})
            fees = execution_result.get("fees", 0)
            expected_profit = trade_result.get("expected_profit", 0)
            strategy = trade_result.get("strategy", "unknown")

            # Update position in memory
            if symbol in self.portfolio["positions"]:
                existing_pos = self.portfolio["positions"][symbol]
                new_quantity = existing_pos["quantity"] + position_size
                
                # Calculate new average price
                total_value = existing_pos["quantity"] * existing_pos["entry_price"] + position_size * entry_price
                new_avg_price = total_value / new_quantity if new_quantity != 0 else entry_price
                
                self.portfolio["positions"][symbol]["quantity"] = new_quantity
                self.portfolio["positions"][symbol]["entry_price"] = new_avg_price
                self.portfolio["positions"][symbol]["current_price"] = entry_price
                self.portfolio["positions"][symbol]["unrealized_pnl"] = (entry_price - new_avg_price) * new_quantity
            else:
                self.portfolio["positions"][symbol] = {
                    "quantity": position_size,
                    "entry_price": entry_price,
                    "current_price": entry_price,
                    "unrealized_pnl": 0.0,
                    "strategy": strategy
                }

            # Update cash balance
            trade_value = position_size * entry_price
            self.portfolio["cash_balance"] -= trade_value + fees

            # Update equity (simplified - assumes immediate profit realization)
            self.portfolio["equity"] += expected_profit - fees
            self.portfolio["total_fees"] += fees
            self.portfolio["last_updated"] = datetime.now()

            # Save to persistent store
            self.state_store.save_position(
                symbol=symbol,
                quantity=self.portfolio["positions"][symbol]["quantity"],
                entry_price=self.portfolio["positions"][symbol]["entry_price"],
                current_price=self.portfolio["positions"][symbol]["current_price"],
                strategy=strategy
            )

            # Save trade to persistent store
            side = "buy" if position_size > 0 else "sell"
            self.state_store.save_trade(
                symbol=symbol,
                side=side,
                quantity=abs(position_size),
                price=entry_price,
                fees=fees,
                realized_pnl=expected_profit,
                strategy=strategy
            )

            # Save updated portfolio state
            self._save_portfolio_state()

            self.logger.debug(
                f"Updated portfolio for {symbol}: position={position_size:.4f}, equity=${self.portfolio['equity']:.2f}"
            )

        except Exception as e:
            self.logger.error(f"Error updating portfolio: {e}")

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

            # Log to profit analytics
            self.profit_analytics.log_trade(
                symbol=symbol,
                strategy=trade_result.get("strategy", "unknown"),
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                fees=fees,
            )

        except Exception as e:
            self.logger.error(f"Error logging trade to analytics: {e}")

    def _get_total_equity(self) -> float:
        """Get total portfolio equity.

        Returns:
            Total equity value
        """
        return self.portfolio["equity"]

    def _get_active_positions(self) -> dict[str, dict[str, Any]]:
        """Get active positions.

        Returns:
            Dictionary of active positions
        """
        return self.portfolio["positions"].copy()

    def _get_cash_balance(self) -> float:
        """Get cash balance.

        Returns:
            Cash balance
        """
        return self.portfolio["cash_balance"]

    def _get_available_capital(self) -> float:
        """Get available capital for trading.

        Returns:
            Available capital
        """
        # Use cash balance as available capital for now
        return max(0, self.portfolio["cash_balance"])

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
            self.logger.info("Step 4: Updating portfolio")
            # Portfolio updates are handled in _update_portfolio_with_trade

            # 5. Analytics and logging
            self.logger.info("Step 5: Analytics and logging")

            # Log trading cycle
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
                "positions": self._get_active_positions(),
                "decisions": {
                    "risk_score": 0.3,
                    "confidence": 0.7,
                    "signals_generated": len(signals),
                    "trades_executed": execution_results.get("trades_executed", 0),
                },
                "trades": execution_results.get("trades", []),
                "metadata": {
                    "cycle_count": self.cycle_count,
                    "symbols_analyzed": len(symbols),
                },
            }

            self.profit_logger.log_trading_cycle(cycle_log_data)

            # Generate profit report
            profit_report = self.profit_analytics.generate_profit_report()

            # Log daily summary if it's a new day
            if self._should_log_daily_summary():
                daily_summary_data = {
                    "date": datetime.now().date(),
                    "timestamp": datetime.now(),
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
                    "equity": {
                        "start_equity": self.portfolio["equity"]
                        - execution_results.get("total_pnl", 0),
                        "end_equity": self.portfolio["equity"],
                    },
                    "risk_metrics": {
                        "current_drawdown": profit_report.get("current_drawdown", 0.0),
                        "volatility": 0.02,  # Placeholder
                        "var_95": 0.03,  # Placeholder
                    },
                    "strategy_performance": profit_report.get(
                        "strategy_performance", {}
                    ),
                    "metadata": {"cycle_count": self.cycle_count},
                }

                self.profit_logger.log_daily_summary(daily_summary_data)

            # Portfolio snapshot
            cycle_results["portfolio_snapshot"] = {
                "total_equity": self._get_total_equity(),
                "cash_balance": self._get_cash_balance(),
                "active_positions": len(self._get_active_positions()),
                "available_capital": self._get_available_capital(),
            }

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
                    await asyncio.sleep(60)  # Wait 1 minute before retrying

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

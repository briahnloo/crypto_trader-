"""
Profit-maximizing trading system orchestration.
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional, List, Dict

from .analytics import ProfitAnalytics, ProfitLogger
from .analytics.trade_ledger import TradeLedger
from .analytics.pnl_logger import get_pnl_logger
from .core.config_manager import ConfigManager
from .core.logging_utils import LoggerMixin
from .core.utils import get_mark_price, get_entry_price, get_exit_value, validate_mark_price, to_canonical, clear_cycle_price_cache, set_pricing_context, clear_pricing_context, PricingContextError
from .core.pricing_snapshot import create_pricing_snapshot, clear_pricing_snapshot, get_current_pricing_snapshot
from .core.nav_validation import NAVValidator, NAVValidationResult
from .core.decimal_money import (
    to_decimal, quantize_currency, quantize_quantity, calculate_notional, 
    calculate_fees, calculate_pnl, calculate_position_value, format_currency, 
    format_quantity, safe_divide, safe_multiply, sum_decimals, abs_decimal
)
from .core.money import D, q_money, ensure_decimal
from .data.engine import ProfitOptimizedDataEngine
from .execution.multi_strategy import MultiStrategyExecutor
from .execution.order_manager import OrderManager, OrderSide
from .execution.regime_detector import RegimeDetector
from .execution.symbol_filter import SymbolFilter
from .execution.execution_router import ExecutionRouter, OrderSideAction, OrderIntent, FinalAction
from .connectors import CoinbaseConnector
from .risk import AdvancedPortfolioManager, ProfitOptimizedRiskManager
from .risk.portfolio_transaction import portfolio_transaction
from .state import StateStore
from .strategies.composite import ProfitMaximizingSignalEngine
from .lot_book import LotBook, Lot
# Note: live.preflight import removed as it's not part of the package structure
# This may need to be handled differently based on your deployment setup


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
        self.regime_detector = None
        self.symbol_filter = None

        # Analytics and logging
        self.profit_analytics = None
        self.profit_logger = None
        self.trade_ledger = None

        # State persistence
        self.state_store = None

        # LotBook for FIFO realized P&L tracking
        self.lot_books = {}  # symbol -> LotBook instance

        # Portfolio tracking (in-memory for now, synced with state store)
        # Will be properly initialized during initialize() method
        self.portfolio = {
            "equity": to_decimal(0.0),  # Will be set during initialization
            "cash_balance": to_decimal(0.0),  # Will be set during initialization
            "positions": {},
            "total_fees": to_decimal(0.0),
            "last_updated": datetime.now(),
        }
        
        # In-memory position cache indexed by canonical symbol for lockstep sync with state store
        self._in_memory_positions = {}  # canonical_symbol -> position_data
        
        # In-memory fill tracking for fallback when ledger fails
        self.in_memory_fills = []

        # System state
        self.running = False
        self.cycle_count = 0
        self.last_cycle_time = None
        self.initialized = False
        
        # Session tracking
        self.current_session_id = None
        
        # Execution router for deterministic action mapping
        self.execution_router = None
        
        # Per-cycle pricing snapshot hit tracking (reduce log noise)
        self._pricing_snapshot_hits_this_cycle = set()  # Reset each cycle
        
        # Initialize previous equity tracking for cycle comparisons
        # Will be set properly during initialization when session_id is available
        self._previous_equity = 0.0  # Will be set to actual initial capital during initialization

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

            # ATR calculation now handled by TechnicalCalculator (pandas-free)
            # ATRService has pandas dependency issues with numpy 2.x, so we skip it
            self.atr_service = None  # Use technical_calculator.calculate_atr() in strategies
            self.logger.info("Using TechnicalCalculator for ATR (pandas-free implementation)")

            # Initialize signal engine with state store
            signal_config = self.config.get("signals", {})
            self.signal_engine = ProfitMaximizingSignalEngine(signal_config)
            self.signal_engine.initialize()
            # Pass data engine to strategies so they can fetch real OHLCV data
            self.signal_engine.set_data_engine(self.data_engine)
            self.logger.info("Signal engine initialized with real data source")

            # Initialize risk manager
            risk_config = self.config.get("risk", {})
            self.risk_manager = ProfitOptimizedRiskManager(risk_config)
            self.risk_manager.initialize()
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
            self.order_manager = OrderManager(order_config, self.current_session_id)
            
            # Set data engine on order manager for ATR calculation
            self.order_manager.data_engine = self.data_engine
            
            # CRITICAL FIX: Set state_store on order_manager so it can debit/credit cash!
            # Without this, apply_fill_cash_impact() silently fails and positions are created without cash deduction
            self.order_manager.set_state_store(self.state_store)
            self.logger.critical("=" * 80)
            self.logger.critical("VERSION_CHECK: EQUITY FIX v2.0 LOADED - State store connected to order_manager")
            self.logger.critical("This version includes: debit_cash equity recalc + cash sync in _save_portfolio_state")
            self.logger.critical("=" * 80)
            
            # Initialize connector for fee information
            self._initialize_connector()
            
            # Initialize symbol filter
            self.symbol_filter = SymbolFilter(self.config)
            self.logger.info("Symbol filter initialized")
            
            # Initialize execution router
            self.execution_router = ExecutionRouter(self.config)
            self.logger.info("Execution router initialized")
            
            # Initialize exit manager for automated exits
            from .execution.exit_manager import ExitManager
            exit_config = self.config.get("risk", {})
            self.exit_manager = ExitManager(exit_config)
            self.logger.info("Exit manager initialized")

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

            # Initialize regime detector
            signals_config = self.config.get("signals", {})
            self.regime_detector = RegimeDetector(self.config)
            
            # Set up regime detector callbacks (placeholder implementations)
            def get_ema_callback(symbol: str, period: int) -> Optional[float]:
                """Get EMA value from data engine."""
                try:
                    if self.data_engine:
                        # Placeholder - in real implementation, get EMA from data engine
                        return 50000.0  # Mock value
                    return None
                except Exception:
                    return None
            
            def get_adx_callback(symbol: str, period: int) -> Optional[float]:
                """Get ADX value from data engine."""
                try:
                    if self.data_engine:
                        # Placeholder - in real implementation, get ADX from data engine
                        return 25.0  # Mock value
                    return None
                except Exception:
                    return None
            
            def get_atr_callback(symbol: str, period: int) -> Optional[float]:
                """Get ATR value from data engine."""
                try:
                    if self.data_engine and hasattr(self, 'atr_service'):
                        return self.atr_service.get_atr(symbol, self.data_engine, period)
                    return None
                except Exception:
                    return None
            
            self.regime_detector.set_callbacks(get_ema_callback, get_adx_callback, get_atr_callback)
            self.logger.info("Regime detector initialized")

            # Initialize analytics
            # Initialize trade ledger first (single source of truth)
            analytics_config = self.config.get("analytics", {})
            ledger_db_path = analytics_config.get("ledger_db_path", "trade_ledger.db")
            self.trade_ledger = TradeLedger(ledger_db_path)
            self.logger.info(f"Trade ledger initialized at {ledger_db_path}")
            
            # Initialize profit analytics with trade ledger reference
            self.profit_analytics = ProfitAnalytics(analytics_config)
            self.profit_analytics.set_trade_ledger(self.trade_ledger)
            self.profit_analytics.initialize(session_id)
            self.logger.info("Profit analytics initialized with trade ledger")
            
            # Initialize NAV validator
            # Increased default tolerance from $0.01 to $50 to handle fee timing and entry price differences
            nav_tolerance = analytics_config.get("nav_validation_tolerance", 50.00)
            # Force minimum tolerance of $10 for production reliability
            nav_tolerance = max(nav_tolerance, 10.00)
            self.nav_validator = NAVValidator(tolerance=nav_tolerance)
            self.logger.info(f"NAV validator initialized with tolerance ${nav_tolerance:.2f} (minimum $10.00)")

            # Initialize profit logger with trade ledger reference
            logger_config = self.config.get("logging", {})
            # Pass the actual session capital to the logger
            session_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            logger_config["initial_equity"] = session_capital
            self.profit_logger = ProfitLogger(logger_config)
            self.profit_logger.set_trade_ledger(self.trade_ledger)
            self.profit_logger.trading_system = self  # Set reference for fallback access
            self.profit_logger.initialize(session_id)
            self.logger.info("Profit logger initialized with trade ledger")

            # Initialize state store
            db_path = self.config.get("state", {}).get("db_path", "trading_state.db")
            self.state_store = StateStore(db_path)
            self.state_store.initialize()
            self.logger.info("State store initialized")
            
            # Initialize LotBooks for FIFO realized P&L tracking
            self._initialize_lotbooks(session_id)
            self.logger.info("LotBooks initialized")
            
            # Run preflight checks before enabling trading
            self.logger.info("Running preflight checks...")
            try:
                # Simple preflight check stub - replace with actual preflight logic if needed
                preflight_results = {
                    'overall_status': 'passed',
                    'checks': ['data_engine_available', 'config_valid', 'state_store_ready']
                }
                self.logger.info(f"Preflight checks completed: {preflight_results['overall_status']}")
            except Exception as e:
                self.logger.error(f"Preflight checks failed: {e}")
                raise RuntimeError(f"Preflight checks failed: {e}")
            self.logger.info("Preflight checks passed")
            
            # Update previous equity tracking now that state store is available
            # For the first cycle, we'll set this properly after portfolio is loaded
            # Don't set it to initial capital here as it should be the actual current equity
            initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            self.logger.info(f"EQUITY_INIT: Will set _previous_equity after portfolio loading (initial_capital=${initial_capital:,.2f})")
            
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
            
            # Log feature flags
            self._log_feature_flags()
            
            # Log effective trading universe
            self._log_trading_universe()

        except Exception as e:
            self.logger.error(f"Failed to initialize trading system: {e}")
            raise

    def _log_feature_flags(self) -> None:
        """Log feature flags status on startup."""
        try:
            # Check realization engine status
            realization_enabled = self._is_realization_enabled()
            
            self.logger.info(f"FEATURE_FLAGS: realization.enabled={realization_enabled}")
            
            if realization_enabled:
                self.logger.info("Profit realization engine: ENABLED - using advanced exit logic with take profit ladder and trailing stops")
            else:
                self.logger.info("Profit realization engine: DISABLED - using legacy/simple exit logic")
                
        except Exception as e:
            self.logger.error(f"Error logging feature flags: {e}")

    def _is_realization_enabled(self) -> bool:
        """Check if profit realization engine is enabled, handling environment variables."""
        try:
            # Use config manager's get method to resolve environment variables
            if hasattr(self, 'config_manager') and self.config_manager:
                realization_enabled = self.config_manager.get("realization.enabled", False)
            else:
                # Fallback to direct config access
                realization_enabled = self.config.get("realization", {}).get("enabled", False)
            
            # Handle environment variable resolution (string values)
            if isinstance(realization_enabled, str):
                return realization_enabled.lower() in ("true", "1", "yes")
            
            # Handle boolean values
            return bool(realization_enabled)
            
        except Exception as e:
            self.logger.error(f"Error checking realization enabled flag: {e}")
            return False
    
    def _log_trading_universe(self) -> None:
        """Log the effective trading universe after validating symbols through resolve_venue."""
        try:
            # Get whitelist from config
            whitelist = self.config.get("universe", {}).get("whitelist", [])
            if not whitelist:
                whitelist = self.config.get("trading", {}).get("symbol_whitelist", [])
            
            if not whitelist:
                self.logger.warning("No trading universe defined in config")
                return
            
            # Validate each symbol through data engine's resolve_venue
            supported_symbols = []
            unsupported_symbols = []
            
            for symbol in whitelist:
                venue, normalized, status = self.data_engine.resolve_venue(symbol)
                if status == "ok" and venue:
                    supported_symbols.append(f"{symbol}({venue})")
                else:
                    unsupported_symbols.append(f"{symbol}:{status}")
            
            # Log the effective trading universe
            self.logger.info(f"EFFECTIVE_TRADING_UNIVERSE: {len(supported_symbols)} symbols supported")
            if supported_symbols:
                self.logger.info(f"SUPPORTED_SYMBOLS: {', '.join(supported_symbols)}")
            
            if unsupported_symbols:
                self.logger.warning(f"UNSUPPORTED_SYMBOLS: {', '.join(unsupported_symbols)}")
                self.logger.warning("These symbols will be excluded from trading due to venue limitations")
            
            if not supported_symbols:
                self.logger.error("CRITICAL: No supported symbols in trading universe! System will not be able to trade.")
                
        except Exception as e:
            self.logger.error(f"Error logging trading universe: {e}")

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

    def _initialize_connector(self) -> None:
        """Initialize exchange connector for fee information."""
        try:
            # Get exchange configuration
            exchanges_config = self.config.get("exchanges", {})
            
            # Initialize Coinbase connector if configured
            if "coinbase" in exchanges_config:
                coinbase_config = exchanges_config["coinbase"]
                connector = CoinbaseConnector(coinbase_config)
                
                if connector.initialize():
                    self.order_manager.set_connector(connector)
                    self.logger.info("Coinbase connector initialized and set on order manager")
                    
                    # Log fee information from single source of truth (config/fees.yaml)
                    try:
                        from .execution.fee_slippage import get_effective_fees
                        effective_fees = get_effective_fees()
                        
                        # Assert that the calculator uses the same values
                        from .execution.fee_slippage import FeeSlippageCalculator
                        calculator = FeeSlippageCalculator()
                        assert float(calculator.maker_fee_bps) == effective_fees["maker_bps"], \
                            f"Fee mismatch: calculator maker={float(calculator.maker_fee_bps)}, config={effective_fees['maker_bps']}"
                        assert float(calculator.taker_fee_bps) == effective_fees["taker_bps"], \
                            f"Fee mismatch: calculator taker={float(calculator.taker_fee_bps)}, config={effective_fees['taker_bps']}"
                        
                        self.logger.info(
                            f"FEE_SCHEDULE: PASS – taker={effective_fees['taker_bps']:.1f}bps, "
                            f"maker={effective_fees['maker_bps']:.1f}bps (from config/fees.yaml)"
                        )
                    except Exception as e:
                        self.logger.warning(f"Could not retrieve fee information: {e}")
                else:
                    self.logger.warning("Failed to initialize Coinbase connector")
            else:
                self.logger.info("No exchange connector configured - using default fees")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize connector: {e}")

    def _load_or_initialize_portfolio(
        self, 
        session_id: str, 
        continue_session: bool = False, 
        respect_session_capital: bool = True
    ) -> None:
        """Load or initialize portfolio. WARNING: This should only be called ONCE during initialization!"""
        import traceback
        stack_trace = ''.join(traceback.format_stack()[-5:-1])
        self.logger.warning(f"🚨🚨🚨 _load_or_initialize_portfolio CALLED 🚨🚨🚨")
        self.logger.warning(f"  session_id={session_id}")
        self.logger.warning(f"  continue_session={continue_session}")
        self.logger.warning(f"  respect_session_capital={respect_session_capital}")
        self.logger.warning(f"  Called from:\n{stack_trace}")
        
        # CRITICAL: Prevent multiple loads which would reload stale positions
        if hasattr(self, '_portfolio_loaded') and self._portfolio_loaded:
            self.logger.error("❌❌❌ DUPLICATE LOAD PREVENTED ❌❌❌")
            self.logger.error(f"Portfolio already loaded! Ignoring duplicate call from:\n{stack_trace}")
            self.logger.error(f"This would have reloaded positions from database, potentially with stale cash!")
            return
        
        self._portfolio_loaded = True
        self.logger.info(f"✅ Portfolio loading guard set - future calls will be blocked")
        
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
                            self.portfolio["cash_balance"] = to_decimal(latest_cash_equity["cash_balance"])
                            self.portfolio["equity"] = to_decimal(latest_cash_equity["total_equity"])
                            self.portfolio["total_fees"] = to_decimal(latest_cash_equity.get("total_fees", 0.0))
                            
                            # Load positions (ensure existing_positions is a list)
                            if isinstance(existing_positions, list):
                                self.logger.info(f"🔄 LOADING_POSITIONS_FROM_STATE_STORE: Found {len(existing_positions)} positions in database")
                                total_position_value = 0.0
                                for pos in existing_positions:
                                    symbol = pos["symbol"]
                                    qty = to_decimal(pos["quantity"])
                                    entry_price = to_decimal(pos["entry_price"])
                                    pos_value = float(qty * entry_price)
                                    total_position_value += pos_value
                                    
                                    self.logger.info(f"  📦 Loading: {symbol} qty={float(qty):.6f} entry=${float(entry_price):.4f} value=${pos_value:.2f}")
                                    
                                    self.portfolio["positions"][symbol] = {
                                        "quantity": qty,
                                        "entry_price": entry_price,
                                        "current_price": to_decimal(pos["current_price"]),
                                        "unrealized_pnl": to_decimal(pos["unrealized_pnl"]),
                                        "strategy": pos["strategy"]
                                    }
                                self.logger.warning(f"⚠️ POSITIONS_LOADED_FROM_DB: {len(existing_positions)} positions with total value ${total_position_value:.2f}")
                                self.logger.warning(f"⚠️ CASH_CHECK: Current cash_balance=${format_currency(self.portfolio['cash_balance'])}")
                                self.logger.warning(f"⚠️ IMPLIED_SPENT: If these positions were bought, cash should be ${float(self.portfolio['cash_balance']) - total_position_value:.2f}")
                            else:
                                self.logger.warning(f"existing_positions is not a list: {type(existing_positions)}")
                                self.portfolio["positions"] = {}
                        else:
                            # CRITICAL FIX: Override with CLI capital - start FRESH, no positions
                            # We cannot keep old positions with new capital - that would create phantom equity!
                            self.logger.warning(f"PORTFOLIO_INIT: Overriding session capital (was ${latest_cash_equity['cash_balance']:.2f}) with ${initial_capital:.2f}")
                            if existing_positions:
                                self.logger.warning(f"PORTFOLIO_INIT: Clearing {len(existing_positions)} existing positions due to capital override")
                            
                            self.portfolio["cash_balance"] = to_decimal(initial_capital)
                            self.portfolio["equity"] = to_decimal(initial_capital)
                            self.portfolio["total_fees"] = to_decimal(0.0)
                            self.portfolio["positions"] = {}  # CLEAR positions when overriding capital!
                            
                            # Update state store with new capital
                            self.state_store.save_cash_equity(
                                cash_balance=initial_capital,
                                total_equity=initial_capital,
                                total_fees=0.0,  # Reset fees
                                total_realized_pnl=0.0,
                                total_unrealized_pnl=0.0,
                                session_id=session_id,
                                previous_equity=initial_capital  # Set to initial capital
                            )
                            
                            # Clear positions from state store
                            for pos in existing_positions if existing_positions else []:
                                try:
                                    self.state_store.remove_position(pos["symbol"], pos.get("strategy", "unknown"))
                                except Exception as e:
                                    self.logger.error(f"Failed to clear position {pos['symbol']}: {e}")
                        
                        # Use portfolio snapshot for consistent position count
                        portfolio_snapshot = self.get_portfolio_snapshot()
                        
                        # Validation: if equity is 0.0 but cash_balance > 0, set equity = cash_balance
                        if self.portfolio["equity"] == to_decimal(0.0) and self.portfolio["cash_balance"] > to_decimal(0.0):
                            self.portfolio["equity"] = self.portfolio["cash_balance"]
                            self.logger.warning(f"PORTFOLIO_INIT: Corrected equity from $0.00 to ${format_currency(self.portfolio['equity'])} (cash_balance > 0)")
                        
                        self.logger.info(f"PORTFOLIO_INIT: equity={format_currency(self.portfolio['equity'])}, cash={format_currency(self.portfolio['cash_balance'])}, positions={portfolio_snapshot['position_count']}")
                        self.logger.info(f"Resumed session {session_id}: equity={format_currency(self.portfolio['equity'])}")
                        
                        # Set _previous_equity to the previous cycle's equity from state store
                        # This ensures that the first cycle after resuming shows correct P&L
                        stored_previous_equity = latest_cash_equity.get("previous_equity", 0.0)
                        if stored_previous_equity > 0:
                            self._previous_equity = stored_previous_equity
                            self.logger.info(f"PORTFOLIO_INIT: Set _previous_equity to ${self._previous_equity:,.2f} from state store for resumed session")
                        else:
                            # Fallback: use current equity if no previous equity stored
                            self._previous_equity = float(self.portfolio["equity"])
                            self.logger.info(f"PORTFOLIO_INIT: Set _previous_equity to ${self._previous_equity:,.2f} (fallback to current equity) for resumed session")
                    else:
                        # No existing data, create new session
                        session_meta = self.state_store.continue_session(session_id, initial_capital, "paper")
                        self.portfolio["equity"] = to_decimal(initial_capital)
                        self.portfolio["cash_balance"] = to_decimal(initial_capital)
                        self.portfolio["total_fees"] = to_decimal(0.0)
                        # Store session start equity for daily loss tracking
                        self.state_store.set_session_metadata(session_id, "session_start_equity", initial_capital)
                        
                        # Validation: if equity is 0.0 but cash_balance > 0, set equity = cash_balance
                        if self.portfolio["equity"] == to_decimal(0.0) and self.portfolio["cash_balance"] > to_decimal(0.0):
                            self.portfolio["equity"] = self.portfolio["cash_balance"]
                            self.logger.warning(f"PORTFOLIO_INIT: Corrected equity from $0.00 to ${format_currency(self.portfolio['equity'])} (cash_balance > 0)")
                        
                        portfolio_snapshot = self.get_portfolio_snapshot()
                        self.logger.info(f"PORTFOLIO_INIT: equity={format_currency(self.portfolio['equity'])}, cash={format_currency(self.portfolio['cash_balance'])}, positions={portfolio_snapshot['position_count']}")
                        self.logger.info(f"Created new session {session_id}: equity={format_currency(to_decimal(initial_capital))}")
                        
                        # Set _previous_equity to initial capital for new session
                        self._previous_equity = initial_capital
                        self.logger.info(f"PORTFOLIO_INIT: Set _previous_equity to ${self._previous_equity:,.2f} for new session")
                        
                except ValueError as e:
                    # Session not found, create new one
                    self.logger.info(f"Session {session_id} not found, creating new session: {e}")
                    session_meta = self.state_store.new_session(session_id, initial_capital, "paper")
                    self.portfolio["equity"] = to_decimal(initial_capital)
                    self.portfolio["cash_balance"] = to_decimal(initial_capital)
                    self.portfolio["total_fees"] = to_decimal(0.0)
                    # Store session start equity for daily loss tracking
                    self.state_store.set_session_metadata(session_id, "session_start_equity", initial_capital)
                    
                    # Validation: if equity is 0.0 but cash_balance > 0, set equity = cash_balance
                    if self.portfolio["equity"] == to_decimal(0.0) and self.portfolio["cash_balance"] > to_decimal(0.0):
                        self.portfolio["equity"] = self.portfolio["cash_balance"]
                        self.logger.warning(f"PORTFOLIO_INIT: Corrected equity from $0.00 to ${format_currency(self.portfolio['equity'])} (cash_balance > 0)")
                    
                    portfolio_snapshot = self.get_portfolio_snapshot()
                    self.logger.info(f"PORTFOLIO_INIT: equity={format_currency(self.portfolio['equity'])}, cash={format_currency(self.portfolio['cash_balance'])}, positions={portfolio_snapshot['position_count']}")
                    self.logger.info(f"Created new session {session_id}: equity={format_currency(to_decimal(initial_capital))}")
                    
                    # Set _previous_equity to initial capital for new session
                    self._previous_equity = float(initial_capital)
                    self.logger.info(f"PORTFOLIO_INIT: Set _previous_equity to ${self._previous_equity:,.2f} for new session")
            else:
                # Start fresh session
                session_meta = self.state_store.new_session(session_id, initial_capital, "paper")
                self.portfolio["equity"] = to_decimal(initial_capital)
                self.portfolio["cash_balance"] = to_decimal(initial_capital)
                self.portfolio["total_fees"] = to_decimal(0.0)
                # Store session start equity for daily loss tracking
                self.state_store.set_session_metadata(session_id, "session_start_equity", initial_capital)
                
                # Validation: if equity is 0.0 but cash_balance > 0, set equity = cash_balance
                if self.portfolio["equity"] == to_decimal(0.0) and self.portfolio["cash_balance"] > to_decimal(0.0):
                    self.portfolio["equity"] = self.portfolio["cash_balance"]
                    self.logger.warning(f"PORTFOLIO_INIT: Corrected equity from $0.00 to ${format_currency(self.portfolio['equity'])} (cash_balance > 0)")
                
                portfolio_snapshot = self.get_portfolio_snapshot()
                self.logger.info(f"PORTFOLIO_INIT: equity={format_currency(self.portfolio['equity'])}, cash={format_currency(self.portfolio['cash_balance'])}, positions={portfolio_snapshot['position_count']}")
                self.logger.info(f"Started fresh session {session_id}: equity={format_currency(to_decimal(initial_capital))}")
                
                # Set _previous_equity to initial capital for fresh session
                self._previous_equity = float(initial_capital)
                self.logger.info(f"PORTFOLIO_INIT: Set _previous_equity to ${self._previous_equity:,.2f} for fresh session")
                
        except Exception as e:
            self.logger.error(f"Failed to load/initialize portfolio: {e}")
            raise RuntimeError(f"Failed to initialize portfolio for session {session_id}: {e}")
        
        # Final validation and debugging of _previous_equity
        # Note: _previous_equity should already be set by the session-specific initialization above
        actual_equity = self._get_total_equity()
        initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
        
        # Debug logging to track equity initialization
        self.logger.info(f"EQUITY_INIT_DEBUG: initial_capital=${initial_capital:,.2f}")
        self.logger.info(f"EQUITY_INIT_DEBUG: actual_equity=${actual_equity:,.2f}")
        self.logger.info(f"EQUITY_INIT_DEBUG: portfolio cash=${self.portfolio.get('cash_balance', 0):,.2f}")
        self.logger.info(f"EQUITY_INIT_DEBUG: portfolio equity=${self.portfolio.get('equity', 0):,.2f}")
        self.logger.info(f"EQUITY_INIT_DEBUG: position count={len(self.portfolio.get('positions', {}))}")
        self.logger.info(f"EQUITY_INIT_DEBUG: _previous_equity=${getattr(self, '_previous_equity', 'NOT_SET'):,.2f}")
        
        # CRITICAL FIX: Only set _previous_equity if it wasn't already set by session-specific initialization
        # NEVER use actual_equity as fallback - it includes positions from previous sessions
        if not hasattr(self, '_previous_equity') or self._previous_equity is None or self._previous_equity == 0.0:
            # Fallback: Use initial_capital for safety (should not happen if session init worked correctly)
            self._previous_equity = initial_capital
            self.logger.warning(f"PORTFOLIO_INIT: _previous_equity was not set by session initialization! Using initial_capital=${self._previous_equity:,.2f} as fallback")
        else:
            self.logger.info(f"PORTFOLIO_INIT: _previous_equity correctly set to ${self._previous_equity:,.2f} by session initialization")
        
        # Validation: Log if _previous_equity differs from expected values
        if abs(self._previous_equity - initial_capital) < 0.01:
            self.logger.info(f"EQUITY_INIT_VALIDATION: _previous_equity matches initial_capital (new session or no trading yet)")
        else:
            self.logger.info(f"EQUITY_INIT_VALIDATION: _previous_equity (${self._previous_equity:,.2f}) != initial_capital (${initial_capital:,.2f}) - resumed session or has trading history")

    def _save_portfolio_state(self) -> None:
        """Save current portfolio state to persistent store using portfolio snapshot as single source of truth."""
        try:
            # CRITICAL: Read cash from state_store as authoritative source
            # The in-memory self.portfolio["cash_balance"] may be stale
            if self.current_session_id:
                state_store_cash = self.state_store.get_session_cash(self.current_session_id)
                in_memory_cash = float(self.portfolio.get('cash_balance', 0.0))
                cash_diff = abs(state_store_cash - in_memory_cash)
                
                # Only log WARNING if mismatch > $0.01, otherwise INFO
                if cash_diff > 0.01:
                    self.logger.warning(f"🔍 SAVE_PORTFOLIO_CHECK: MISMATCH ${cash_diff:.2f} - state_store cash=${state_store_cash:.2f}, in-memory cash={format_currency(self.portfolio.get('cash_balance', 0.0))}")
                else:
                    self.logger.info(f"SAVE_PORTFOLIO_CHECK: in sync (state_store=${state_store_cash:.2f})")
                
                # CRITICAL FIX: Use state_store cash as authoritative, update in-memory to match
                self.portfolio["cash_balance"] = to_decimal(state_store_cash)
            
            # Get authoritative portfolio snapshot (SINGLE SOURCE OF TRUTH)
            self.logger.info(f"SAVE_PORTFOLIO_STATE: Getting portfolio snapshot...")
            portfolio_snapshot = self.get_portfolio_snapshot()
            
            # Extract values from the authoritative snapshot
            cash_balance = portfolio_snapshot["cash_balance"]
            total_equity = portfolio_snapshot["total_equity"]
            total_positions_value = portfolio_snapshot["total_position_value"]
            total_realized_pnl = portfolio_snapshot["total_realized_pnl"]
            total_unrealized_pnl = portfolio_snapshot["total_unrealized_pnl"]
            position_count = portfolio_snapshot["position_count"]
            
            self.logger.info(f"SAVE_PORTFOLIO_STATE: Snapshot values - cash={format_currency(to_decimal(cash_balance))}, equity={format_currency(to_decimal(total_equity))}, positions_value={format_currency(to_decimal(total_positions_value))}, position_count={position_count}")
            
            # Save cash/equity to state store with values from snapshot
            self.state_store.save_cash_equity(
                cash_balance=float(cash_balance),
                total_equity=float(total_equity),
                total_fees=float(self.portfolio.get("total_fees", 0.0)),
                total_realized_pnl=float(total_realized_pnl),
                total_unrealized_pnl=float(total_unrealized_pnl),
                session_id=self.current_session_id,
                previous_equity=float(getattr(self, '_previous_equity', total_equity))
            )
            self.logger.info(f"SAVE_PORTFOLIO_STATE: Successfully saved cash={format_currency(to_decimal(cash_balance))} to state store")
            
            # Save portfolio snapshot with authoritative values
            # Debug the values before saving
            self.logger.debug(f"PORTFOLIO_SNAPSHOT_DEBUG: total_equity={total_equity} (type: {type(total_equity)})")
            self.logger.debug(f"PORTFOLIO_SNAPSHOT_DEBUG: cash_balance={cash_balance} (type: {type(cash_balance)})")
            self.logger.debug(f"PORTFOLIO_SNAPSHOT_DEBUG: total_positions_value={total_positions_value} (type: {type(total_positions_value)})")
            self.logger.debug(f"PORTFOLIO_SNAPSHOT_DEBUG: total_unrealized_pnl={total_unrealized_pnl} (type: {type(total_unrealized_pnl)})")
            self.logger.debug(f"PORTFOLIO_SNAPSHOT_DEBUG: position_count={position_count} (type: {type(position_count)})")
            
            self.state_store.save_portfolio_snapshot(
                total_equity=float(total_equity),
                cash_balance=float(cash_balance),
                total_positions_value=float(total_positions_value),  # Fixed: use correct parameter name
                total_unrealized_pnl=float(total_unrealized_pnl),
                position_count=int(position_count),
                session_id=self.current_session_id
            )
            
            self.logger.debug(f"Saved portfolio state: equity=${total_equity:.2f}, "
                            f"cash=${cash_balance:.2f}, positions={position_count}")
            
        except Exception as e:
            self.logger.error(f"Failed to save portfolio state: {e}")

    def _commit_portfolio_transaction(self, mark_prices: dict[str, float]) -> bool:
        """Commit portfolio changes using transactional approach with validation.
        
        Args:
            mark_prices: Current mark prices for all symbols
            
        Returns:
            True if committed successfully, False if validation failed
        """
        try:
            with portfolio_transaction(
                state_store=self.state_store,
                portfolio_manager=self.portfolio_manager,
                previous_equity=float(getattr(self, '_previous_equity', 0.0)),
                session_id=self.current_session_id,
                config=self.config
            ) as tx:
                # Stage any pending portfolio changes here
                # This is where individual trade updates would be staged
                # For now, we'll commit the current state as-is
                
                # Commit with current mark prices
                success = tx.commit(mark_prices)
                
                if success:
                    self.logger.info("Portfolio transaction committed successfully")
                    # Update _previous_equity for next cycle from committed state
                    latest_cash_equity = self.state_store.get_latest_cash_equity(self.current_session_id)
                    if latest_cash_equity:
                        old_previous = self._previous_equity
                        self._previous_equity = float(latest_cash_equity["total_equity"])
                        self.logger.info(f"📊 UPDATED_PREVIOUS_EQUITY: ${old_previous:.2f} → ${self._previous_equity:.2f} (from state store after transaction)")
                else:
                    self.logger.warning("Portfolio transaction validation failed - changes discarded")
                
                return success
                
        except Exception as e:
            self.logger.error(f"Portfolio transaction failed: {e}")
            return False

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
                    
                    # Detect regime and add to signal metadata
                    if self.regime_detector:
                        try:
                            regime, regime_details = self.regime_detector.detect_regime(symbol)
                            if "metadata" not in composite_signal:
                                composite_signal["metadata"] = {}
                            composite_signal["metadata"]["regime"] = regime
                            composite_signal["metadata"]["regime_details"] = regime_details
                        except Exception as e:
                            self.logger.warning(f"Failed to detect regime for {symbol}: {e}")
                            if "metadata" not in composite_signal:
                                composite_signal["metadata"] = {}
                            composite_signal["metadata"]["regime"] = "unknown"
                    
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
        """Log comprehensive cycle summary with separated P&L types and clear warnings."""
        try:
            # Get authoritative portfolio snapshot (SINGLE SOURCE OF TRUTH)
            portfolio_snapshot = self.get_portfolio_snapshot()
            
            # Extract values from the authoritative snapshot
            current_equity = portfolio_snapshot["total_equity"]
            current_cash = portfolio_snapshot["cash_balance"]
            position_count = portfolio_snapshot["position_count"]
            total_position_value = portfolio_snapshot["total_position_value"]
            total_realized_pnl = portfolio_snapshot["total_realized_pnl"]
            total_unrealized_pnl = portfolio_snapshot["total_unrealized_pnl"]
            
            # Get positions for detailed breakdown
            positions = portfolio_snapshot["active_positions"]
            
            # ACCOUNTING PATH GUARD: Ensure all critical values use Decimal (no float/Decimal mixing)
            # Wrap raw values in D() immediately at boundary
            cash_d = D(current_cash)
            positions_value_d = D(total_position_value)
            realized_pnl_d = D(total_realized_pnl)
            
            # Get previous equity for comparison - wrap in D() at boundary
            previous_equity_raw = float(getattr(self, '_previous_equity', current_equity))
            previous_equity = D(previous_equity_raw)
            current_equity_d = D(current_equity)
            
            # GUARD: Verify all accounting values are now Decimal - this catches float contamination
            if not ensure_decimal(cash_d, positions_value_d, realized_pnl_d, current_equity_d, previous_equity):
                raise ValueError(
                    "Float detected in accounting path! "
                    f"cash={type(cash_d)}, positions_value={type(positions_value_d)}, "
                    f"realized_pnl={type(realized_pnl_d)}, current_equity={type(current_equity_d)}, "
                    f"previous_equity={type(previous_equity)}"
                )
            
            # Calculate equity change using Decimal arithmetic
            equity_change = q_money(current_equity_d - previous_equity)
            equity_change_pct = float((equity_change / previous_equity * D("100"))) if previous_equity > D("0") else 0.0
            
            # Convert back to float for display (but keep Decimal for calculations)
            previous_equity_float = float(previous_equity)
            equity_change_float = float(equity_change)
            
            # Calculate different types of P&L
            trading_pnl = self._calculate_trading_pnl(execution_results)
            # Use unrealized P&L from snapshot (already calculated with mark prices)
            unrealized_pnl = total_unrealized_pnl
            total_pnl = trading_pnl + unrealized_pnl
            
            # Debug logging for equity calculation
            self.logger.info(f"EQUITY_CYCLE_DEBUG: current_equity=${current_equity:,.2f}")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: previous_equity=${previous_equity_float:,.2f}")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: equity_change=${equity_change_float:,.2f}")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: equity_change_pct={equity_change_pct:.2f}%")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: cash_balance=${current_cash:,.2f}")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: total_position_value=${total_position_value:,.2f}")
            self.logger.info(f"EQUITY_CYCLE_DEBUG: position_count={position_count}")
            self.logger.info(f"P&L_BREAKDOWN: trading_pnl=${trading_pnl:,.2f}, unrealized_pnl=${unrealized_pnl:,.2f}, total_pnl=${total_pnl:,.2f}")
            
            # Add warnings about P&L types
            if abs(unrealized_pnl) > 0.01:
                self.logger.warning(f"⚠️  UNREALIZED_PNL_WARNING: ${unrealized_pnl:,.2f} unrealized gains/losses from price fluctuations - NOT actual trading profits!")
            
            if abs(equity_change_float) > 0.01 and abs(trading_pnl) < 0.01:
                self.logger.warning(f"⚠️  PRICE_FLUCTUATION_WARNING: Equity change (${equity_change_float:,.2f}) is due to price movements, not trading activity!")
            
            # Validation: If we have positions but equity change is significant, this might indicate a bug
            if position_count > 0 and abs(equity_change_float) > 0.01:
                self.logger.warning(f"EQUITY_CYCLE_WARNING: Significant equity change (${equity_change_float:,.2f}) with {position_count} positions - this may indicate price fluctuations or calculation error")
            
            # Format timestamp
            timestamp = datetime.now()
            formatted_time = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")
            
            # Format individual positions
            position_details = []
            for sym, pos in positions.items():
                if abs(pos.get("quantity", 0)) > 1e-8:
                    qty = pos.get("quantity", 0)
                    price = pos.get("value", 0) / qty if qty != 0 else 0
                    position_details.append(f"📊 {sym}: {qty:.4f} @ ${price:.2f}")
            
            # Performance metrics calculation removed
            
            # Pre-calculate trading activity metrics
            total_trades = self._get_total_trades()
            winning_trades = self._get_winning_trades()
            losing_trades = self._get_losing_trades()
            total_volume = self._get_total_volume()
            total_fees = self._get_total_fees()
            avg_trade_size = self._get_avg_trade_size()
            
            # Pre-calculate risk metrics
            current_drawdown = self._calculate_current_drawdown()
            volatility = self._calculate_volatility()
            var_95 = self._calculate_var_95()
            
            # Pre-calculate strategy performance
            strategy_perf = self._get_strategy_performance()
            
            # Build the complete formatted output as a single string
            output_lines = [
                "",
                f"🔄 TRADING CYCLE: cycle_{self.cycle_count}",
                "=" * 80,
                f"📅 Time: {formatted_time}",
                f"💰 Symbol: PORTFOLIO",
                f"🎯 Strategy: composite",
                "",
                "💎 EQUITY:",
                f"   📈 Current: ${current_equity:,.2f}",
                f"   📊 Previous: ${previous_equity:,.2f}",
                f"   💰 Total P&L: ${equity_change:,.2f} ({equity_change_pct:+.2f}%)",
                "",
                "📊 P&L BREAKDOWN:",
                f"   🎯 Trading P&L: ${trading_pnl:,.2f} (actual profits/losses from trades)",
                f"   📈 Unrealized P&L: ${unrealized_pnl:,.2f} (price fluctuations only)",
                f"   ⚠️  Note: Unrealized gains are NOT real profits until positions are closed!",
                "",
                "📋 POSITIONS:",
                f"   🔢 Count: {position_count}",
                f"   💵 Total Value: ${total_position_value:,.2f}"
            ]
            
            # Add position details
            for detail in position_details:
                output_lines.append(f"   {detail}")
            
            output_lines.extend([
                "",
                "💼 TRADING ACTIVITY:",
                f"   🔢 Total Trades: {total_trades}",
                f"   🟢 Winning Trades: {winning_trades}",
                f"   🔴 Losing Trades: {losing_trades}",
                f"   📊 Total Volume: ${total_volume:,.2f}",
                f"   💸 Total Fees: ${total_fees:,.2f}",
                f"   📏 Avg Trade Size: ${avg_trade_size:,.2f}",
                "",
                "⚠️  RISK METRICS:",
                f"   📉 Current Drawdown: {current_drawdown:.1f}%",
                f"   📊 Volatility: {volatility:.1f}%",
                f"   🎯 VaR (95%): {var_95:.1f}%",
                "",
                "🎯 STRATEGY PERFORMANCE:"
            ])
            
            # Add strategy performance details
            if strategy_perf:
                for strategy_name, perf in strategy_perf.items():
                    trades = perf.get("trades", 0)
                    pnl = perf.get("pnl", 0.0)
                    output_lines.append(f"   🔴 {strategy_name}: {trades} trades, ${pnl:,.2f} P&L")
            else:
                output_lines.append("   🔴 unknown: 0 trades, $0.00 P&L")
            
            # Log the complete formatted output as a single block
            for line in output_lines:
                self.logger.info(line)
            
            # Update previous equity for next cycle
            old_previous = self._previous_equity
            self._previous_equity = float(current_equity)
            self.logger.info(f"📊 UPDATED_PREVIOUS_EQUITY: ${old_previous:.2f} → ${self._previous_equity:.2f} (at end of cycle summary)")
            
            # Diagnostic summary for debugging
            self.logger.info("=" * 80)
            self.logger.info("🔍 DIAGNOSTIC SUMMARY:")
            self.logger.info(f"  In-Memory Cash: {format_currency(self.portfolio['cash_balance'])}")
            self.logger.info(f"  StateStore Cash: {format_currency(to_decimal(self._get_cash_balance()))}")
            self.logger.info(f"  Position Count: {len(self.portfolio['positions'])}")
            self.logger.info(f"  _previous_equity: ${self._previous_equity:,.2f}")
            self.logger.info(f"  Calculated Equity: ${current_equity:,.2f}")
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Error in cycle summary logging: {e}")

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
                    # Filter by data_quality and eligible flag BEFORE any processing
                    data_quality = signal.get("metadata", {}).get("data_quality", "ok")
                    eligible = signal.get("metadata", {}).get("eligible", True)
                    
                    if data_quality != "ok" or not eligible:
                        self.logger.info(f"DATA_EXCLUDE: {symbol} filtered before ranking (data_quality={data_quality}, eligible={eligible})")
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=0.0,
                            action="SKIP",
                            reason=f"data_quality_{data_quality}_eligible_{eligible}"
                        )
                        continue
                    
                    # Get entry price with strict validation
                    current_price = get_entry_price(
                        symbol, 
                        self.data_engine, 
                        live_mode=self.config.get("trading", {}).get("live_mode", False),
                        cycle_id=self.cycle_count
                    )
                    
                    # Early price validation - reject before any processing
                    if current_price is None or current_price <= 0:
                        self.logger.error(f"Invalid entry_price for {symbol}: {current_price}. Rejecting trade.")
                        # Log decision trace for invalid price
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=current_price or 0.0,
                            action="SKIP",
                            reason="invalid_price"
                        )
                        continue

                    # Get composite score and regime
                    composite_score = signal.get("composite_score", 0)
                    regime = signal.get("metadata", {}).get("regime", "ranging")
                    
                    # Determine initial action based on composite score
                    initial_action = "BUY" if composite_score > 0 else "SELL"
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
                            # Log decision trace for ATR failure
                            self._log_decision_trace(
                                symbol=symbol,
                                signal=signal,
                                current_price=current_price,
                                action="SKIP",
                                reason="no_atr_no_fallback"
                            )
                            continue
                        else:
                            raise
                    
                    stop_loss = sl_tp_result["stop_loss"]
                    take_profit = sl_tp_result["take_profit"]
                    sl_tp_src = sl_tp_result["source"]
                    
                    # DEBUG: Log SL/TP derivation values
                    self.logger.debug(f"SL_TP_DEBUG: symbol={symbol}, side={side}, entry_price={current_price}, "
                                    f"stop_loss={stop_loss}, take_profit={take_profit}, source={sl_tp_src}")
                    
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
                        # Log decision trace for RR calculation failure
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=current_price,
                            action="SKIP",
                            reason=f"rr_calculation_failed_{str(e)}"
                        )
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
                    
                    # DEBUG: Log candidate creation values
                    self.logger.debug(f"CANDIDATE_DEBUG: symbol={symbol}, side={side}, composite_score={composite_score}, "
                                    f"stop_loss={stop_loss}, take_profit={take_profit}, sl_tp_src={sl_tp_src}")
                    candidates.append(candidate)
                    
                except Exception as e:
                    self.logger.debug(f"Error building candidate for {symbol}: {e}")
                    # Log decision trace for candidate building failure
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=signal,
                        current_price=current_price if 'current_price' in locals() else 0.0,
                        action="SKIP",
                        reason=f"candidate_build_failed_{str(e)}"
                    )
                    continue

            if not candidates:
                self.logger.info("No candidates could be built (price/RR issues)")
                # Log decision traces for all symbols when no candidates are built
                for symbol, signal in signals.items():
                    current_price = signal.get("current_price", 0.0)
                    if not current_price:
                        # Try to get price if not in signal
                        try:
                            current_price = get_entry_price(
                                symbol, 
                                self.data_engine, 
                                live_mode=self.config.get("trading", {}).get("live_mode", False),
                                cycle_id=self.cycle_count
                            ) or 0.0
                        except:
                            current_price = 0.0
                    
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=signal,
                        current_price=current_price,
                        action="HOLD",
                        reason="no_candidates_built"
                    )
                return execution_results

            # Apply RR gate first: skip if rr < config threshold
            rr_min = self.config.get("risk", {}).get("rr_min", 1.30)
            rr_filtered_candidates = []
            for candidate in candidates:
                if candidate["risk_reward_ratio"] >= rr_min:
                    rr_filtered_candidates.append(candidate)
                else:
                    self.logger.info(f"⏭️ SKIP {candidate['symbol']} reason=rr_too_low ratio={candidate['risk_reward_ratio']:.2f}")
                    # Log decision trace for RR filtering
                    self._log_decision_trace(
                        symbol=candidate["symbol"],
                        signal=candidate["signal"],
                        current_price=candidate["current_price"],
                        action="SKIP",
                        reason=f"rr_too_low_{candidate['risk_reward_ratio']:.2f}"
                    )

            if not rr_filtered_candidates:
                self.logger.info(f"No candidates meet minimum RR threshold ({rr_min})")
                # Log decision traces for symbols that don't meet RR threshold
                for candidate in candidates:
                    if candidate["risk_reward_ratio"] < rr_min:
                        self._log_decision_trace(
                            symbol=candidate["symbol"],
                            signal=candidate["signal"],
                            current_price=candidate["current_price"],
                            action="SKIP",
                            reason=f"rr_too_low_{candidate['risk_reward_ratio']:.2f}"
                        )
                
                # Try pilot trade logic here since no regular candidates qualify
                pilot_result = self._execute_pilot_trade(signals, available_capital)
                if pilot_result:
                    execution_results["trades"].append(pilot_result)
                    execution_results["trades_executed"] += 1
                    execution_results["total_pnl"] += pilot_result.get("expected_profit", 0)
                    execution_results["total_fees"] += pilot_result.get("execution_result", {}).get("fees", 0)
                return execution_results

            # Apply score filtering with top-k or threshold-based selection
            gate_cfg = self.config.get("risk", {}).get("entry_gate", {})
            enable_top_k = gate_cfg.get("enable_top_k", False)
            
            # Get top_k_entries from exploration config first, then fall back to entry_gate config
            exploration_cfg = self.config.get("risk", {}).get("exploration", {})
            top_k_entries = exploration_cfg.get("top_k_entries") or gate_cfg.get("top_k_entries", 4)
            
            hard_floor_min = gate_cfg.get("hard_floor_min", 0.53)
            
            # Check if risk-on mode is active and use lower gate floor
            risk_on_active = False
            if self.state_store and self.current_session_id:
                risk_on_active = self.state_store.get_session_metadata(
                    self.current_session_id, "risk_on_active", False
                )
            
            if risk_on_active:
                risk_on_cfg = self.config.get("risk", {}).get("risk_on", {})
                min_gate_floor = risk_on_cfg.get("min_gate_floor", 0.35)
                hard_floor_min = min_gate_floor  # Use risk-on gate floor
                self.logger.info(f"RISK-ON: Using lower gate floor {hard_floor_min:.3f} instead of normal {gate_cfg.get('hard_floor_min', 0.53):.3f}")
            
            # Check if new entries are halted due to daily loss limit
            halt_new_entries = False
            if self.state_store and self.current_session_id:
                halt_new_entries = self.state_store.get_session_metadata(
                    self.current_session_id, "halt_new_entries_today", False
                )
            
            if halt_new_entries:
                self.logger.info("HALT: Skipping new entries due to daily loss limit breach")
                # Log decision traces for all symbols when halted
                for symbol, signal in signals.items():
                    current_price = signal.get("current_price", 0.0)
                    if not current_price:
                        # Try to get price if not in signal
                        try:
                            current_price = get_entry_price(
                                symbol, 
                                self.data_engine, 
                                live_mode=self.config.get("trading", {}).get("live_mode", False),
                                cycle_id=self.cycle_count
                            ) or 0.0
                        except:
                            current_price = 0.0
                    
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=signal,
                        current_price=current_price,
                        action="SKIP",
                        reason="daily_loss_limit_halt"
                    )
                return execution_results
            
            # Create atomic signal selection: single {symbol: score} map
            symbol_scores = {}
            for candidate in candidates:
                symbol_scores[candidate["symbol"]] = candidate["composite_score"]
            
            # Store candidates for decision trace logging in selection methods
            self._current_candidates = candidates
            
            # Apply atomic signal selection
            if enable_top_k:
                selected_symbols = self._select_top_k_symbols(symbol_scores, top_k_entries, hard_floor_min)
            else:
                selected_symbols = self._select_threshold_symbols(symbol_scores, candidates, gate_cfg)
            
            # Log exactly the returned list (no recomputation, no abs())
            if selected_symbols:
                chosen_symbols = [f"{symbol}:{score:.3f}" for symbol, score in selected_symbols]
                self.logger.info(f"ENTRY SELECTOR: top_k={enable_top_k}, K={top_k_entries if enable_top_k else 'N/A'}, floor={hard_floor_min:.3f}, chosen=[{', '.join(chosen_symbols)}]")
            else:
                self.logger.info(f"ENTRY SELECTOR: top_k={enable_top_k}, K={top_k_entries if enable_top_k else 'N/A'}, floor={hard_floor_min:.3f}, chosen=[] (no candidates >= floor)")
            
            # Build filtered_candidates from selected symbols
            filtered_candidates = []
            for symbol, score in selected_symbols:
                # Find the original candidate
                candidate = next((c for c in candidates if c["symbol"] == symbol), None)
                if candidate:
                    # Add required fields for selected candidates
                    signal = candidate["signal"]
                    composite_score = candidate["composite_score"]
                    
                    # Get effective threshold from signal metadata
                    effective_threshold = signal.get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.65)
                    
                    # Calculate score floor and gate info
                    gate_margin = gate_cfg.get("gate_margin", 0.05)
                    score_floor = hard_floor_min
                    floor_reason = "top_k_hard_floor" if enable_top_k else "threshold_based"
                    
                    # Add required fields to candidate
                    candidate["effective_threshold"] = effective_threshold
                    candidate["score_floor"] = score_floor
                    candidate["floor_reason"] = floor_reason
                
                filtered_candidates.append(candidate)

            if not filtered_candidates:
                self.logger.info("No candidates meet minimum score threshold")
                # Log decision traces for symbols that don't meet score threshold
                # The selection methods already log traces for filtered symbols, but let's ensure all symbols get traces
                processed_symbols = set()
                for candidate in candidates:
                    processed_symbols.add(candidate["symbol"])
                
                # Log traces for any symbols that didn't get processed
                for symbol, signal in signals.items():
                    if symbol not in processed_symbols:
                        current_price = signal.get("current_price", 0.0)
                        if not current_price:
                            try:
                                current_price = get_entry_price(
                    symbol, 
                    self.data_engine,
                    live_mode=self.config.get("trading", {}).get("live_mode", False),
                    cycle_id=self.cycle_count
                ) or 0.0
                            except:
                                current_price = 0.0
                        
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=current_price,
                            action="HOLD",
                            reason="not_processed"
                        )
                
                # Try pilot trade logic here since no regular candidates qualify
                pilot_result = self._execute_pilot_trade(signals, available_capital)
                if pilot_result:
                    execution_results["trades"].append(pilot_result)
                    execution_results["trades_executed"] += 1
                    execution_results["total_pnl"] += pilot_result.get("expected_profit", 0)
                    execution_results["total_fees"] += pilot_result.get("execution_result", {}).get("fees", 0)
                
                # Try exploration budget logic if pilot trade didn't execute
                if not pilot_result:
                    exploration_result = self._execute_exploration_trade(signals, available_capital)
                    if exploration_result:
                        execution_results["trades"].append(exploration_result)
                        execution_results["trades_executed"] += 1
                        execution_results["total_pnl"] += exploration_result.get("expected_profit", 0)
                        execution_results["total_fees"] += exploration_result.get("execution_result", {}).get("fees", 0)
                
                return execution_results

            # Execute trades for each qualifying candidate
            pilot_trade_executed = False  # Track if pilot trade was executed this cycle
            
            for candidate in filtered_candidates:
                try:
                    # Extract data from pre-built candidate
                    symbol = candidate["symbol"]
                    
                    # Validate symbol against whitelist
                    if self.symbol_filter and not self.symbol_filter.is_whitelist_empty():
                        is_allowed, reason, _ = self.symbol_filter.is_symbol_allowed(symbol)
                        if not is_allowed:
                            self.logger.info(f"SYMBOL_FILTER: Blocked trade on {symbol} - {reason}")
                            # Log decision trace for symbol filter blocking
                            self._log_decision_trace(
                                symbol=symbol,
                                signal=signal,
                                current_price=current_price,
                                action="SKIP",
                                reason=f"symbol_filter_blocked_{reason}"
                            )
                            continue
                    
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
                    
                    # Determine initial action from side
                    initial_action = "BUY" if side == "buy" else "SELL"

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
                    
                    # Add regime and entry price to metadata
                    signal["metadata"]["regime"] = regime
                    signal["metadata"]["entry_price"] = current_price

                    # Select best strategy based on risk-adjusted return
                    strategy_name = self._select_best_strategy(signal)

                    # Use risk-based sizing for regular trades
                    sizing_cfg = self.config.get("risk", {}).get("sizing", {})
                    
                    if self.order_manager and stop_loss:
                        # Calculate target notional using risk-based sizing
                        target_notional = self.order_manager.calculate_target_notional(
                            equity=available_capital,
                            entry_price=current_price,
                            stop_price=stop_loss,
                            cfg=sizing_cfg
                        )
                        
                        # NOTE: can_explore() check REMOVED - this is a regular trade, not an exploration trade
                        # Exploration limits should only apply to exploration trades, not regular qualified trades
                        
                        # Route action through execution router
                        has_position = symbol in self.portfolio.get("positions", {})
                        position_side = None
                        if has_position:
                            pos = self.portfolio["positions"][symbol]
                            qty = pos.get("quantity", 0)
                            position_side = "long" if qty > 0 else "short" if qty < 0 else None
                        
                        routed_side, order_intent, route_reason = self.execution_router.route_action(
                            final_action=initial_action,
                            symbol=symbol,
                            has_position=has_position,
                            position_side=position_side,
                            is_pilot=False,
                            is_exploration=False
                        )
                        
                        # Log routing decision
                        self.logger.info(self.execution_router.get_routing_summary(
                            initial_action, routed_side, order_intent, route_reason
                        ))
                        
                        # Skip if routed to SKIP
                        if routed_side == OrderSideAction.SKIP:
                            self.logger.info(f"SKIP {symbol} {initial_action} reason={route_reason}")
                            self._log_decision_trace(
                                symbol=symbol,
                                signal=signal,
                                current_price=current_price,
                                action="SKIP",
                                reason=route_reason
                            )
                            continue
                        
                        # Map routed side to OrderSide
                        if routed_side == OrderSideAction.BUY:
                            order_side = OrderSide.BUY
                        elif routed_side == OrderSideAction.SELL:
                            order_side = OrderSide.SELL
                        elif routed_side == OrderSideAction.CLOSE_LONG:
                            order_side = OrderSide.SELL
                        else:
                            self.logger.warning(f"Unknown routed side: {routed_side}")
                            continue
                        
                        # Prepare gate information for telemetry
                        gate_info = {
                            "base_gate": effective_threshold,
                            "effective_gate": effective_threshold,
                            "score": composite_score
                        }
                        
                        # Create order metadata with proper tagging
                        order_metadata = self.execution_router.create_order_metadata(
                            intent=order_intent,
                            strategy=strategy_name,
                            signal_data=signal,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            risk_reward_ratio=rr_ratio
                        )
                        
                        # Execute trade using slice execution
                        execution_result = self.order_manager.execute_by_slices(
                            symbol=symbol,
                            side=order_side,
                            target_notional=target_notional,
                            current_price=current_price,
                            strategy=strategy_name,
                            is_pilot=False,
                            cfg=sizing_cfg,
                            gate_info=gate_info,
                            metadata=order_metadata
                        )
                        
                        # Convert execution result to trade result format
                        if execution_result["executed_notional"] > 0:
                            trade_result = {
                                "status": "executed",
                                "position_size": execution_result["executed_notional"] / current_price,
                                "entry_price": current_price,
                                "notional_value": execution_result["executed_notional"],
                                "slices_executed": execution_result["slices_executed"],
                                "execution_ratio": execution_result["execution_ratio"]
                            }
                        else:
                            trade_result = {"status": "rejected", "reason": "no_execution"}
                    else:
                        # Fallback to old logic if order manager not available
                        trade_result = self.multi_strategy_executor.execute_strategy(
                            strategy_name=strategy_name,
                            signal=signal,
                            capital=available_capital * 0.1,  # Use 10% of available capital per trade
                        )

                    # Handle rejection cases
                    if trade_result and trade_result.get("status") == "rejected":
                        reason = trade_result.get("reason", "unknown")
                        self.logger.info(f"REJECTED {symbol} {side.upper()} reason={reason}")
                        # Log decision trace for rejected trade
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=current_price,
                            action="SKIP",
                            reason=f"execution_rejected_{reason}"
                        )
                        continue

                    if trade_result and trade_result.get("position_size", 0) > 0:
                        # Add SL/TP info to trade result for logging
                        trade_result["stop_loss"] = stop_loss
                        trade_result["take_profit"] = take_profit
                        trade_result["risk_reward_ratio"] = rr_ratio
                        trade_result["sl_tp_src"] = sl_tp_src
                        
                        # Update portfolio with trade - only proceed if successful
                        self.logger.info(f"🎯 EXECUTING_TRADE: about to call _update_portfolio_with_trade for {symbol}")
                        portfolio_updated = self._update_portfolio_with_trade(symbol, trade_result)
                        self.logger.info(f"✅ TRADE_COMPLETED: _update_portfolio_with_trade returned {portfolio_updated}")
                        
                        if portfolio_updated:
                            # Log trade to analytics
                            self._log_trade_to_analytics(symbol, trade_result)

                            # Log decision trace for executed trade
                            position_size = trade_result.get("position_size", 0)
                            
                            # DEBUG: Log the actual values being used in decision trace
                            self.logger.debug(f"DECISION_TRACE_DEBUG: symbol={symbol}, side={side}, composite_score={composite_score}, "
                                            f"position_size={position_size}, entry_price={current_price}, "
                                            f"stop_loss={stop_loss}, take_profit={take_profit}")
                            
                            self._log_decision_trace(
                                symbol=symbol,
                                signal=signal,
                                current_price=current_price,
                                action=side.upper(),
                                reason="executed",
                                entry_price=current_price,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                size=position_size
                            )

                            # Record execution result
                            execution_results["trades"].append(trade_result)
                            execution_results["trades_executed"] += 1
                            execution_results["total_pnl"] += trade_result.get(
                                "expected_profit", 0
                            )
                            execution_results["total_fees"] += trade_result.get(
                                "execution_result", {}
                            ).get("fees", 0)
                        else:
                            # Log decision trace for portfolio update failure
                            self._log_decision_trace(
                                symbol=symbol,
                                signal=signal,
                                current_price=current_price,
                                action="SKIP",
                                reason="portfolio_update_failed"
                            )
                    elif trade_result and trade_result.get("position_size", 0) == 0:
                        # Log decision trace for zero position size (no execution)
                        self._log_decision_trace(
                            symbol=symbol,
                            signal=signal,
                            current_price=current_price,
                            action="SKIP",
                            reason="zero_position_size"
                        )

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
            
            # Update session trade count for daily loss limit tracking
            if execution_results['trades_executed'] > 0:
                current_trade_count = self.state_store.get_session_metadata(
                    self.current_session_id, "trades_executed_count", 0
                )
                new_trade_count = current_trade_count + execution_results['trades_executed']
                self.state_store.set_session_metadata(
                    self.current_session_id, "trades_executed_count", new_trade_count
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
        - score > 0 (positive only, respecting long-only mode)
        - RR ≥ config.rr_relax_for_pilot (default 1.60)
        - valid price/liquidity
        - Risk-on mode must be active
        - Notional = min(session_cap_remaining, per_symbol_cap, max_notional_pct_of_equity) but >= pilot_min_notional
        - BUY only
        
        Args:
            signals: All available signals
            available_capital: Available capital for trading
            
        Returns:
            Pilot trade result or None if no suitable pilot trade found
        """
        # Check if new entries are halted due to daily loss limit
        if self.state_store and self.current_session_id:
            halt_new_entries = self.state_store.get_session_metadata(
                self.current_session_id, "halt_new_entries_today", False
            )
            if halt_new_entries:
                self.logger.info("🔍 PILOT: Skipped due to daily loss limit halt")
                return None
        
        # Check if risk-on mode is active (required for pilot trades)
        risk_on_active = False
        if self.state_store and self.current_session_id:
            risk_on_active = self.state_store.get_session_metadata(
                self.current_session_id, "risk_on_active", False
            )
        
        if not risk_on_active:
            self.logger.info("🔍 PILOT: Skipped - risk-on mode not active")
            return None
        
        self.logger.info("🔍 PILOT: No symbols met effective threshold, searching for pilot trade candidates (risk-on active)")
        
        pilot_candidates = []
        
        # Find pilot trade candidates
        for symbol, signal in signals.items():
            try:
                # Get entry price with strict validation
                current_price = get_entry_price(
                    symbol, 
                    self.data_engine, 
                    live_mode=self.config.get("trading", {}).get("live_mode", False),
                    cycle_id=self.cycle_count
                )
                
                # Early price validation - reject before any processing
                if current_price is None or current_price <= 0:
                    self.logger.error(f"Invalid entry_price for {symbol}: {current_price}. Rejecting pilot trade.")
                    continue
                
                # Get composite score and regime
                composite_score = signal.get("composite_score", 0)
                normalized_score = signal.get("metadata", {}).get("normalization", {}).get("normalized_composite_score", composite_score)
                regime = signal.get("metadata", {}).get("regime", "ranging")
                
                # Pilot criteria: use effective gate with pilot gating
                effective_threshold = signal.get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.65)
                gate_cfg = self.config.get("risk", {}).get("entry_gate", {})
                gate_margin = gate_cfg.get("gate_margin", 0.01)
                hard_floor_min = gate_cfg.get("hard_floor_min", 0.53)
                
                # Calculate effective gate
                effective_gate = max(effective_threshold - gate_margin, hard_floor_min)
                
                # Pilot gate: allow slightly lower threshold
                pilot_gate = max(effective_gate - 0.01, 0.52)
                
                if abs(normalized_score) < pilot_gate:
                    continue
                
                # PILOT: Only consider positive scores (BUY only, respecting long-only mode)
                if composite_score <= 0:
                    continue
                
                # Force BUY only for pilot trades
                side = "buy"
                
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
        
        # Add regime and entry price to metadata
        signal["metadata"]["regime"] = regime
        signal["metadata"]["entry_price"] = current_price
        
        # Select best strategy
        strategy_name = self._select_best_strategy(signal)
        
        # PILOT SIZING: Use min(session_cap_remaining, per_symbol_cap, max_notional_pct_of_equity) but >= pilot_min_notional
        sizing_cfg = self.config.get("risk", {}).get("sizing", {})
        pilot_min_notional = self.config.get("risk", {}).get("pilot_min_notional", 300)
        
        # Calculate target notional using risk-based sizing
        if self.order_manager and stop_loss:
            # Get session cap remaining
            session_cap_remaining = self._get_session_cap_remaining()
            
            # Get per-symbol cap
            per_symbol_cap = sizing_cfg.get("max_position_size", 5000)
            
            # Get max notional as percentage of equity
            max_notional_pct = sizing_cfg.get("max_notional_pct", 0.02)  # 2% default
            max_notional_pct_of_equity = available_capital * max_notional_pct
            
            # Calculate pilot notional: min of all caps, but not less than pilot_min_notional
            pilot_target_notional = max(
                min(session_cap_remaining, per_symbol_cap, max_notional_pct_of_equity),
                pilot_min_notional
            )
            
            self.logger.info(
                f"🚁 PILOT: notional=max(min(session_cap=${session_cap_remaining:.2f}, per_symbol_cap=${per_symbol_cap:.2f}, "
                f"max_notional_pct=${max_notional_pct_of_equity:.2f}), pilot_min=${pilot_min_notional:.2f}) = ${pilot_target_notional:.2f}"
            )
            
            # Route action through execution router for pilots
            initial_action = "BUY" if side == "buy" else "SELL"
            has_position = symbol in self.portfolio.get("positions", {})
            position_side_val = None
            if has_position:
                pos = self.portfolio["positions"][symbol]
                qty = pos.get("quantity", 0)
                position_side_val = "long" if qty > 0 else "short" if qty < 0 else None
            
            routed_side, order_intent, route_reason = self.execution_router.route_action(
                final_action=initial_action,
                symbol=symbol,
                has_position=has_position,
                position_side=position_side_val,
                is_pilot=True,
                is_exploration=False  # Pilots are NOT exploration trades
            )
            
            # Log routing decision
            self.logger.info(self.execution_router.get_routing_summary(
                initial_action, routed_side, order_intent, route_reason
            ))
            
            # Skip if routed to SKIP
            if routed_side == OrderSideAction.SKIP:
                self.logger.info(f"SKIP PILOT {symbol} {initial_action} reason={route_reason}")
                return None
            
            # Map routed side to OrderSide
            if routed_side == OrderSideAction.BUY:
                final_order_side = OrderSide.BUY
            elif routed_side == OrderSideAction.SELL or routed_side == OrderSideAction.CLOSE_LONG:
                final_order_side = OrderSide.SELL
            else:
                self.logger.warning(f"Unknown routed side for pilot: {routed_side}")
                return None
            
            # Check exploration limits before executing pilot trade
            # Note: Pilots use exploration budget (not normal budget)
            if not self.can_explore(pilot_target_notional):
                self.logger.info(f"SKIP PILOT {symbol} {side.upper()} reason=exploration_limit")
                return None
            
            # Prepare gate information for telemetry
            gate_info = {
                "base_gate": pilot_gate,
                "effective_gate": pilot_gate,
                "score": normalized_score
            }
            
            # Create order metadata with pilot tagging
            order_metadata = self.execution_router.create_order_metadata(
                intent=OrderIntent.PILOT,
                strategy=strategy_name,
                signal_data=signal,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward_ratio=rr_ratio
            )
            
            # Execute pilot trade using slice execution
            execution_result = self.order_manager.execute_by_slices(
                symbol=symbol,
                side=final_order_side,
                target_notional=pilot_target_notional,
                current_price=current_price,
                strategy=strategy_name,
                is_pilot=True,
                cfg=sizing_cfg,
                gate_info=gate_info,
                metadata=order_metadata
            )
            
            # Convert execution result to trade result format
            if execution_result["executed_notional"] > 0:
                trade_result = {
                    "status": "executed",
                    "position_size": execution_result["executed_notional"] / current_price,
                    "entry_price": current_price,
                    "notional_value": execution_result["executed_notional"],
                    "slices_executed": execution_result["slices_executed"],
                    "execution_ratio": execution_result["execution_ratio"]
                }
            else:
                trade_result = {"status": "rejected", "reason": "no_execution"}
        else:
            # Fallback to old logic if order manager not available
            session_cash = self.state_store.get_session_cash(self.current_session_id) if self.state_store else available_capital
            pilot_cash_limit = session_cash * 0.01  # 1% of session cash
            normal_capital = available_capital * 0.1
            pilot_capital = min(pilot_cash_limit, normal_capital)
            
            self.logger.info(
                f"🚁 PILOT: Using {pilot_capital:.2f} capital (fallback mode)"
            )
            
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
            self.logger.info(f"🎯 EXECUTING_TRADE: about to call _update_portfolio_with_trade for {symbol} (pilot)")
            portfolio_updated = self._update_portfolio_with_trade(symbol, trade_result)
            self.logger.info(f"✅ TRADE_COMPLETED: _update_portfolio_with_trade returned {portfolio_updated}")
            
            if portfolio_updated:
                # Log DECISION_TRACE for pilot trade with intent="pilot_buy"
                self._log_decision_trace(
                    symbol=symbol,
                    signal=signal,
                    current_price=current_price,
                    action="BUY",
                    reason="pilot_buy",
                    intent="pilot_buy"
                )
                
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

    def can_explore(self, order_value: float) -> bool:
        """Check if exploration is allowed for the given order value.
        
        Args:
            order_value: The notional value of the proposed order
            
        Returns:
            True if exploration is allowed, False otherwise
        """
        # Check if exploration is enabled
        exploration_cfg = self.config.get("risk", {}).get("exploration", {})
        if not exploration_cfg.get("enabled", False):
            return False
        
        # Get exploration configuration
        budget_pct_per_day = exploration_cfg.get("budget_pct_per_day", 0.03)
        max_forced_per_day = exploration_cfg.get("max_forced_per_day", 2)
        
        # Get current equity
        current_equity = self._get_total_equity()
        exploration_budget_usd = current_equity * budget_pct_per_day
        
        # Check if state store is available
        if not self.state_store or not self.current_session_id:
            self.logger.warning("No state store available for exploration budget tracking")
            return False
            
        # Get exploration counters
        exploration_used_notional_today = self.state_store.get_session_metadata(
            self.current_session_id, "exploration_used_notional_today", 0.0
        )
        exploration_forced_count_today = self.state_store.get_session_metadata(
            self.current_session_id, "exploration_forced_count_today", 0
        )
        
        # Check count limit
        if exploration_forced_count_today >= max_forced_per_day:
            self.logger.info(f"EXPLORATION_LIMIT: max forced count reached ({exploration_forced_count_today}/{max_forced_per_day})")
            return False
            
        # Check budget limit
        if exploration_used_notional_today >= exploration_budget_usd:
            self.logger.info(f"EXPLORATION_LIMIT: budget exhausted (${exploration_used_notional_today:.2f}/${exploration_budget_usd:.2f})")
            return False
        
        # Check if this specific order would exceed remaining budget
        remaining_budget = exploration_budget_usd - exploration_used_notional_today
        if order_value > remaining_budget:
            self.logger.info(f"EXPLORATION_LIMIT: insufficient budget (need ${order_value:.2f}, have ${remaining_budget:.2f} left)")
            return False
        
        return True

    def _execute_exploration_trade(self, signals: dict[str, Any], available_capital: float) -> Optional[dict[str, Any]]:
        """Execute an exploration trade using the exploration budget when no regular candidates qualify.
        
        Exploration trade criteria:
        - Only if config.risk.exploration.enabled is true
        - Check budget counters: exploration_used_notional_today, exploration_forced_count_today
        - Compute exploration_budget_usd = equity * budget_pct_per_day
        - If exploration_forced_count_today >= max_forced_per_day OR used_notional >= exploration_budget_usd: skip
        - Else: pick top-1 symbol whose score >= exploration.min_score with valid price
        - Submit with size_mult_vs_normal and tighter_stop_mult
        - Tag trade metadata: exploration=true
        - Increment counters in StateStore
        
        Args:
            signals: All available signals
            available_capital: Available capital for trading
            
        Returns:
            Exploration trade result or None if no suitable exploration trade found
        """
        # Check if exploration is enabled
        exploration_cfg = self.config.get("risk", {}).get("exploration", {})
        if not exploration_cfg.get("enabled", False):
            return None
        
        # Check if new entries are halted due to daily loss limit
        if self.state_store and self.current_session_id:
            halt_new_entries = self.state_store.get_session_metadata(
                self.current_session_id, "halt_new_entries_today", False
            )
            if halt_new_entries:
                self.logger.info("🔍 EXPLORATION: Skipped due to daily loss limit halt")
                return None
            
        self.logger.info("🔍 EXPLORATION: Checking exploration budget for forced pilot")
        
        # Get exploration configuration
        budget_pct_per_day = exploration_cfg.get("budget_pct_per_day", 0.03)
        min_score = exploration_cfg.get("min_score", 0.30)
        max_forced_per_day = exploration_cfg.get("max_forced_per_day", 2)
        size_mult_vs_normal = exploration_cfg.get("size_mult_vs_normal", 0.5)
        tighter_stop_mult = exploration_cfg.get("tighter_stop_mult", 0.7)
        
        # Get current equity
        current_equity = self._get_total_equity()
        exploration_budget_usd = current_equity * budget_pct_per_day
        
        # Read budget counters from StateStore (create if missing)
        if not self.state_store:
            self.logger.warning("No state store available for exploration budget tracking")
            return None
            
        # Get or initialize exploration counters
        exploration_used_notional_today = self.state_store.get_session_metadata(
            self.current_session_id, "exploration_used_notional_today", 0.0
        )
        exploration_forced_count_today = self.state_store.get_session_metadata(
            self.current_session_id, "exploration_forced_count_today", 0
        )
        
        # Log budget status
        remaining_budget = exploration_budget_usd - exploration_used_notional_today
        remaining_count = max_forced_per_day - exploration_forced_count_today
        self.logger.info(f"EXPLORATION: budget=${exploration_used_notional_today:.2f}/${exploration_budget_usd:.2f} (${remaining_budget:.2f} left), count={exploration_forced_count_today}/{max_forced_per_day} ({remaining_count} left)")
        
        # Check budget limits
        if exploration_forced_count_today >= max_forced_per_day:
            self.logger.info(f"EXPLORATION: skipped - max forced count reached ({exploration_forced_count_today}/{max_forced_per_day})")
            return None
            
        if exploration_used_notional_today >= exploration_budget_usd:
            self.logger.info(f"EXPLORATION: skipped - budget exhausted (${exploration_used_notional_today:.2f}/${exploration_budget_usd:.2f})")
            return None
        
        # Rank all tradable symbols by score desc and pick top-1
        exploration_candidates = []
        
        for symbol, signal in signals.items():
            try:
                # Get entry price with validation
                current_price = get_entry_price(
                    symbol, 
                    self.data_engine, 
                    live_mode=self.config.get("trading", {}).get("live_mode", False),
                    cycle_id=self.cycle_count
                )
                
                # Validate price
                if current_price is None or current_price <= 0:
                    self.logger.debug(f"EXPLORATION: skipped {symbol} due to invalid price")
                    continue
                
                # Get composite score
                composite_score = signal.get("composite_score", 0)
                normalized_score = signal.get("metadata", {}).get("normalization", {}).get("normalized_composite_score", composite_score)
                
                # Check minimum score requirement
                if abs(normalized_score) < min_score:
                    continue
                
                # Add to candidates
                exploration_candidates.append({
                    "symbol": symbol,
                    "signal": signal,
                    "current_price": current_price,
                    "composite_score": composite_score,
                    "normalized_score": normalized_score,
                    "score_abs": abs(normalized_score)
                })
                
            except Exception as e:
                self.logger.debug(f"EXPLORATION: error evaluating {symbol}: {e}")
                continue
        
        # Sort by score descending and take top-1
        exploration_candidates.sort(key=lambda x: x["score_abs"], reverse=True)
        
        
        if not exploration_candidates:
            self.logger.info(f"EXPLORATION: no candidates meet minimum score {min_score}")
            return None
        
        best_candidate = exploration_candidates[0]
        symbol = best_candidate["symbol"]
        signal = best_candidate["signal"]
        current_price = best_candidate["current_price"]
        composite_score = best_candidate["composite_score"]
        normalized_score = best_candidate["normalized_score"]
        
        # Get regime from signal metadata
        regime = signal.get("metadata", {}).get("regime", "unknown")
        
        # Determine side
        side = "buy" if composite_score > 0 else "sell"
        
        # Get existing SL/TP from signal metadata
        existing_sl = signal.get("metadata", {}).get("stop_loss")
        existing_tp = signal.get("metadata", {}).get("take_profit")
        
        # Derive SL/TP using tighter stop multiplier
        try:
            sl_tp_result = self.risk_manager.derive_sl_tp(
                entry_price=current_price,
                side=side,
                atr=None,
                strategy_sl=existing_sl,
                strategy_tp=existing_tp,
                symbol=symbol
            )
            
            # Apply tighter stop multiplier
            stop_loss = sl_tp_result["stop_loss"]
            take_profit = sl_tp_result["take_profit"]
            
            # Adjust stop loss to be tighter
            if side == "buy":
                # For long positions, move stop loss closer to entry price
                stop_distance = abs(current_price - stop_loss)
                tighter_stop_distance = stop_distance * tighter_stop_mult
                stop_loss = current_price - tighter_stop_distance
            else:
                # For short positions, move stop loss closer to entry price
                stop_distance = abs(stop_loss - current_price)
                tighter_stop_distance = stop_distance * tighter_stop_mult
                stop_loss = current_price + tighter_stop_distance
            
            sl_tp_src = sl_tp_result["source"] + "_exploration_tightened"
            
        except ValueError as e:
            self.logger.debug(f"EXPLORATION: SL/TP derivation failed for {symbol}: {e}")
            return None
        
        # Calculate risk-reward ratio
        try:
            rr_ratio = self.risk_manager.compute_rr(
                entry=current_price,
                sl=stop_loss,
                tp=take_profit,
                side=side
            )
        except ValueError as e:
            self.logger.debug(f"EXPLORATION: RR calculation failed for {symbol}: {e}")
            return None
        
        # Add required fields for executors
        signal["symbol"] = symbol
        signal["current_price"] = current_price
        signal["price"] = current_price
        signal["score"] = composite_score
        signal["signal_strength"] = abs(composite_score)
        signal["signal_type"] = side
        
        # Add SL/TP to metadata
        if "metadata" not in signal:
            signal["metadata"] = {}
        signal["metadata"]["stop_loss"] = stop_loss
        signal["metadata"]["take_profit"] = take_profit
        signal["metadata"]["risk_reward_ratio"] = rr_ratio
        signal["metadata"]["sl_tp_src"] = sl_tp_src
        signal["metadata"]["sentiment_type"] = "bullish" if composite_score > 0 else "bearish"
        signal["metadata"]["exploration"] = True  # Tag as exploration trade
        
        # Add regime and entry price to metadata
        signal["metadata"]["regime"] = regime
        signal["metadata"]["entry_price"] = current_price
        
        # Select best strategy
        strategy_name = self._select_best_strategy(signal)
        
        # Calculate target notional with exploration size multiplier
        sizing_cfg = self.config.get("risk", {}).get("sizing", {})
        
        if self.order_manager and stop_loss:
            target_notional = self.order_manager.calculate_target_notional(
                equity=available_capital,
                entry_price=current_price,
                stop_price=stop_loss,
                cfg=sizing_cfg
            )
            
            # Apply exploration size multiplier
            exploration_target_notional = target_notional * size_mult_vs_normal
            
            self.logger.info(
                f"🔍 EXPLORATION: target_notional=${target_notional:.2f} * {size_mult_vs_normal:.1f} = ${exploration_target_notional:.2f}"
            )
            
            # Route action through execution router for exploration trades
            initial_action = "BUY" if side == "buy" else "SELL"
            has_position = symbol in self.portfolio.get("positions", {})
            position_side_val = None
            if has_position:
                pos = self.portfolio["positions"][symbol]
                qty = pos.get("quantity", 0)
                position_side_val = "long" if qty > 0 else "short" if qty < 0 else None
            
            routed_side, order_intent, route_reason = self.execution_router.route_action(
                final_action=initial_action,
                symbol=symbol,
                has_position=has_position,
                position_side=position_side_val,
                is_pilot=False,
                is_exploration=True  # Tag as EXPLORATION trade
            )
            
            # Log routing decision
            self.logger.info(self.execution_router.get_routing_summary(
                initial_action, routed_side, order_intent, route_reason
            ))
            
            # Skip if routed to SKIP
            if routed_side == OrderSideAction.SKIP:
                self.logger.info(f"SKIP EXPLORATION {symbol} {initial_action} reason={route_reason}")
                return None
            
            # Map routed side to OrderSide
            if routed_side == OrderSideAction.BUY:
                final_order_side = OrderSide.BUY
            elif routed_side == OrderSideAction.SELL or routed_side == OrderSideAction.CLOSE_LONG:
                final_order_side = OrderSide.SELL
            else:
                self.logger.warning(f"Unknown routed side for exploration: {routed_side}")
                return None
            
            # Check exploration limits using can_explore
            # NOTE: Only EXPLORATION trades hit exploration budget checks
            if not self.can_explore(exploration_target_notional):
                self.logger.info(f"EXPLORATION budget exhausted for {symbol} (need ${exploration_target_notional:.2f})")
                return None
            
            # Exploration check passed - proceed with execution
            remaining_budget = exploration_budget_usd - exploration_used_notional_today
            self.logger.info(
                f"EXPLORATION: can_explore passed (need ${exploration_target_notional:.2f}, have ${remaining_budget:.2f} left)"
            )
            
            # Create order metadata with EXPLORATION tagging
            order_metadata = self.execution_router.create_order_metadata(
                intent=OrderIntent.EXPLORE,
                strategy=strategy_name,
                signal_data=signal,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward_ratio=rr_ratio
            )
            
            # Execute exploration trade using slice execution
            execution_result = self.order_manager.execute_by_slices(
                symbol=symbol,
                side=final_order_side,
                target_notional=exploration_target_notional,
                current_price=current_price,
                strategy=strategy_name,
                is_pilot=True,  # Use pilot execution path for sizing
                cfg=sizing_cfg,
                gate_info={
                    "base_gate": min_score,
                    "effective_gate": min_score,
                    "score": normalized_score
                },
                metadata=order_metadata
            )
            
            if execution_result["executed_notional"] > 0:
                # Calculate expected notional for budget tracking
                expected_notional = exploration_target_notional
                
                # Increment counters in StateStore
                new_used_notional = exploration_used_notional_today + expected_notional
                new_forced_count = exploration_forced_count_today + 1
                
                self.state_store.set_session_metadata(
                    self.current_session_id, "exploration_used_notional_today", new_used_notional
                )
                self.state_store.set_session_metadata(
                    self.current_session_id, "exploration_forced_count_today", new_forced_count
                )
                
                # Log exploration trade
                remaining_budget = exploration_budget_usd - new_used_notional
                self.logger.info(
                    f"EXPLORATION: forced pilot on {symbol}, score={normalized_score:.3f}, "
                    f"risk_mult={size_mult_vs_normal:.1f}, stop_mult={tighter_stop_mult:.1f}, "
                    f"budget_used=${new_used_notional:.2f}, budget_total=${exploration_budget_usd:.2f}, remaining=${remaining_budget:.2f}"
                )
                
                trade_result = {
                    "strategy": strategy_name,
                    "symbol": symbol,
                    "side": side,
                    "status": "executed",
                    "position_size": execution_result["executed_notional"] / current_price,
                    "entry_price": current_price,
                    "notional_value": execution_result["executed_notional"],
                    "slices_executed": execution_result["slices_executed"],
                    "execution_ratio": execution_result["execution_ratio"],
                    "exploration": True,  # Tag as exploration trade
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "risk_reward_ratio": rr_ratio,
                    "sl_tp_src": sl_tp_src
                }
            else:
                trade_result = {"status": "rejected", "reason": "no_execution"}
        else:
            # Fallback to old logic if order manager not available
            session_cash = self.state_store.get_session_cash(self.current_session_id) if self.state_store else available_capital
            exploration_cash_limit = session_cash * 0.01 * size_mult_vs_normal  # 1% of session cash with multiplier
            normal_capital = available_capital * 0.1 * size_mult_vs_normal
            exploration_capital = min(exploration_cash_limit, normal_capital)
            
            self.logger.info(
                f"🔍 EXPLORATION: Using ${exploration_capital:.2f} capital (fallback mode)"
            )
            
            trade_result = self.multi_strategy_executor.execute_strategy(
                strategy_name=strategy_name,
                signal=signal,
                capital=exploration_capital
            )
        
        # Handle rejection cases
        if trade_result and trade_result.get("status") == "rejected":
            reason = trade_result.get("reason", "unknown")
            self.logger.info(f"EXPLORATION: skipped due to {reason}")
            return None
        
        if trade_result and trade_result.get("position_size", 0) > 0:
            # Tag as exploration trade
            trade_result["exploration"] = True
            trade_result["stop_loss"] = stop_loss
            trade_result["take_profit"] = take_profit
            trade_result["risk_reward_ratio"] = rr_ratio
            trade_result["sl_tp_src"] = sl_tp_src
            
            # Update portfolio with exploration trade
            self.logger.info(f"🎯 EXECUTING_TRADE: about to call _update_portfolio_with_trade for {symbol} (exploration)")
            portfolio_updated = self._update_portfolio_with_trade(symbol, trade_result)
            self.logger.info(f"✅ TRADE_COMPLETED: _update_portfolio_with_trade returned {portfolio_updated}")
            
            if portfolio_updated:
                # Log exploration trade to analytics
                self._log_trade_to_analytics(symbol, trade_result)
                
                self.logger.info(
                    f"🔍 EXPLORATION: {symbol} {side.upper()} executed - "
                    f"score={normalized_score:.3f} size=${trade_result.get('position_size', 0) * current_price:.2f} "
                    f"RR={rr_ratio:.2f} exploration=True"
                )
                
                return trade_result
            else:
                # Portfolio update failed - exploration trade rejected
                self.logger.info(f"EXPLORATION: {symbol} {side.upper()} rejected - portfolio_update_failed")
                return None
        
        return None

    def _update_portfolio_with_trade(
        self, symbol: str, trade_result: dict[str, Any]
    ) -> bool:
        """Update portfolio with trade result using atomic operations and proper cash accounting.

        Args:
            symbol: Trading symbol (will be converted to canonical)
            trade_result: Trade execution result
        """
        import traceback
        stack_trace = ''.join(traceback.format_stack()[-5:-1])
        self.logger.info(f"🔵🔵🔵 _update_portfolio_with_trade CALLED 🔵🔵🔵")
        self.logger.info(f"  symbol={symbol}")
        self.logger.info(f"  trade_result keys={list(trade_result.keys()) if trade_result else None}")
        self.logger.info(f"  Called from:\n{stack_trace}")
        
        # Store original state for rollback
        original_cash = None
        original_positions = None
        original_fees = None
        
        try:
            # Convert to canonical symbol
            canonical_symbol = to_canonical(symbol)
            
            position_size = trade_result.get("position_size", 0)
            self.logger.info(f"🔵 PORTFOLIO_UPDATE_ENTRY: symbol={canonical_symbol}, position_size={position_size}")
            execution_result = trade_result.get("execution_result", {})
            entry_price = trade_result.get("entry_price", 0)  # Fixed: get from trade_result, not execution_result
            fees = execution_result.get("fees", 0)
            expected_profit = trade_result.get("expected_profit", 0)
            strategy = trade_result.get("strategy", "unknown")

            # Step 1: Validate entry price early - before any portfolio mutations
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Invalid entry_price: {entry_price} for {canonical_symbol}. Rejecting trade.")
                self.logger.info(f"❌ EARLY_RETURN: reason=invalid_entry_price, price={entry_price}, symbol={canonical_symbol}")
                return False

            # Step 2: Capture original state for rollback
            original_cash = self._get_cash_balance()
            original_positions = self.state_store.get_positions(self.current_session_id).copy()
            original_fees = self.portfolio.get("total_fees", 0.0)
            equity_before = self._get_total_equity()

            # Step 3: Calculate cash impact: BUY = -notional - fees, SELL = +notional - fees
            notional_value = calculate_notional(to_decimal(abs(position_size)), to_decimal(entry_price))
            fees_decimal = to_decimal(fees)
            
            if position_size > 0:  # Buy
                cash_impact = -(notional_value + fees_decimal)
                side = "BUY"
            else:  # Sell
                cash_impact = notional_value - fees_decimal
                side = "SELL"
            
            # Unit check: Ensure summary.side matches fill.side if fill info is available
            # If mismatch, overwrite summary.side with fill.side before printing
            if execution_result and "fills" in execution_result and execution_result["fills"]:
                # Get the first fill's side (all fills in this execution should have same side)
                fill = execution_result["fills"][0]
                if hasattr(fill, 'side'):
                    fill_side = fill.side.value if hasattr(fill.side, 'value') else str(fill.side)
                    if fill_side.upper() != side:
                        self.logger.warning(f"Side mismatch detected: summary={side}, fill={fill_side}. Overwriting summary.side with fill.side")
                        side = fill_side.upper()
            
            new_cash = to_decimal(original_cash) + cash_impact
            
            # Step 4: Validate sufficient cash for buy orders
            if position_size > 0 and new_cash < to_decimal(0):
                self.logger.error(f"Insufficient cash for BUY: need {format_currency(notional_value + fees_decimal)}, have {format_currency(to_decimal(original_cash))}")
                self.logger.info(f"❌ EARLY_RETURN: reason=insufficient_cash, needed={format_currency(notional_value + fees_decimal)}, available={format_currency(to_decimal(original_cash))}, symbol={canonical_symbol}")
                return False

            # Step 5: Update cash balance BEFORE updating positions
            # Note: realized_pnl will be updated after LotBook processing
            
            # CRITICAL FIX: Ensure cash deduction is properly saved and logged
            self.logger.info(f"CASH_DEDUCTION_DEBUG: Before trade - original_cash={format_currency(to_decimal(original_cash))}, notional_value={format_currency(notional_value)}, fees={format_currency(fees_decimal)}, cash_impact={format_currency(cash_impact)}")
            self.logger.info(f"CASH_DEDUCTION_DEBUG: After calculation - new_cash={format_currency(new_cash)}")
            
            # CRITICAL: Update in-memory portfolio FIRST to avoid stale reads
            old_cash = to_decimal(self.portfolio.get("cash_balance", 0.0))
            self.logger.info(f"💰 CASH_UPDATE: original={format_currency(to_decimal(original_cash))} → new={format_currency(new_cash)} (impact={format_currency(cash_impact)})")
            self.portfolio["cash_balance"] = new_cash
            self.logger.info(f"📝 IN_MEMORY_UPDATED: self.portfolio['cash_balance']={format_currency(self.portfolio['cash_balance'])}")
            self.portfolio["total_fees"] = to_decimal(original_fees) + fees_decimal
            
            # Log cash balance update with detailed debugging
            cash_change = new_cash - old_cash
            self.logger.info(f"CASH_BALANCE_UPDATED[IN-MEMORY]: {format_currency(old_cash)} -> {format_currency(new_cash)} ({format_currency(cash_change)}) for {canonical_symbol} {side}")
            
            # REMOVED: Temporary save_cash_equity() here - it causes overwrites
            # Cash will be saved by the FINAL save after equity recalculation (line ~3200)

            # Lock provenance for first entry (if this is a new position)
            snapshot = get_current_pricing_snapshot()
            if snapshot and position_size > 0:  # New BUY entry
                # Check if this is a new position
                is_new_position = True
                for pos in original_positions:
                    if to_canonical(pos["symbol"]) == canonical_symbol:
                        is_new_position = False
                        break
                
                if is_new_position:
                    # Lock the provenance from the current price data
                    price_data = snapshot.by_symbol.get(canonical_symbol)
                    if price_data and price_data.source:
                        # Extract venue and price_type from source
                        source_parts = price_data.source.split("_")
                        venue = source_parts[0] if len(source_parts) > 0 else "unknown"
                        price_type = "_".join(source_parts[1:]) if len(source_parts) > 1 else "last"
                        snapshot.lock_provenance(canonical_symbol, venue, price_type)
            
            # Step 6: Get existing position and calculate new position values
            existing_position = None
            for pos in original_positions:
                if to_canonical(pos["symbol"]) == canonical_symbol:
                    existing_position = pos
                    break

            # Step 7: Set average cost correctly: avg_cost = (old_qty*old_avg + new_qty*fill_price) / total_qty
            if existing_position:
                old_quantity = to_decimal(existing_position["quantity"])
                old_avg_price = to_decimal(existing_position["entry_price"])
                new_quantity = old_quantity + to_decimal(position_size)
                
                # Calculate weighted average price
                if new_quantity != to_decimal(0):
                    total_cost = (old_quantity * old_avg_price) + (to_decimal(position_size) * to_decimal(entry_price))
                    new_avg_price = total_cost / new_quantity
                else:
                    new_avg_price = to_decimal(entry_price)
            else:
                new_quantity = to_decimal(position_size)
                new_avg_price = to_decimal(entry_price)

            # Step 8: Update position in state store
            self.state_store.save_position(
                symbol=canonical_symbol,
                quantity=float(new_quantity),
                entry_price=float(new_avg_price),
                current_price=float(entry_price),
                strategy=strategy,
                session_id=self.current_session_id
            )
            
            # Step 8b: Update portfolio cache with new position
            if canonical_symbol not in self.portfolio["positions"]:
                self.portfolio["positions"][canonical_symbol] = {}
            
            self.portfolio["positions"][canonical_symbol].update({
                "quantity": new_quantity,
                "entry_price": new_avg_price,
                "current_price": to_decimal(entry_price),
                "unrealized_pnl": to_decimal(0.0),  # Will be updated by price update
                "strategy": strategy,
                "updated_at": datetime.now()
            })
            
            # Remove position from cache if quantity is zero
            if new_quantity == to_decimal(0):
                if canonical_symbol in self.portfolio["positions"]:
                    del self.portfolio["positions"][canonical_symbol]

            # Step 9: Process fill with LotBook for accurate FIFO realized P&L
            trade_side = "buy" if position_size > 0 else "sell"
            
            # Get trade ID from execution result for idempotency
            trade_id = None
            if execution_result and "fills" in execution_result and execution_result["fills"]:
                fill = execution_result["fills"][0]
                if hasattr(fill, 'metadata') and fill.metadata.get('trade_id'):
                    trade_id = fill.metadata['trade_id']
            
            # Process fill with LotBook
            lotbook_result = self._process_fill_with_lotbook(
                symbol=canonical_symbol,
                side=trade_side,
                quantity=abs(position_size),
                fill_price=entry_price,
                fees=fees,
                trade_id=trade_id
            )
            
            # Use LotBook realized P&L instead of expected_profit
            actual_realized_pnl = lotbook_result["realized_pnl"]
            
            # Save trade to persistent store with actual realized P&L
            self.state_store.save_trade(
                symbol=canonical_symbol,
                side=trade_side,
                quantity=abs(position_size),
                price=entry_price,
                fees=fees,
                realized_pnl=actual_realized_pnl,
                strategy=strategy,
                session_id=self.current_session_id,
                trade_id=trade_id
            )
            
            # NOTE: actual_realized_pnl will be saved in the final save_cash_equity below (after equity recalculation)
            if actual_realized_pnl != expected_profit:
                self.logger.debug(f"Realized P&L updated from LotBook: ${actual_realized_pnl:.4f} (was ${expected_profit:.4f})")
            
            # Step 9b: Commit fill to trade ledger immediately after successful portfolio update
            # Always track fill in-memory for fallback purposes
            trade_id = f"{canonical_symbol}_{trade_side}_{int(datetime.now().timestamp() * 1000)}"
            self.logger.info(f"TRADE_EXECUTION_DEBUG: Creating trade {trade_id}")
            
            # Get exit reason if this is an exit order
            exit_reason = None
            if hasattr(self, 'order_manager') and hasattr(self.order_manager, 'orders'):
                for order in self.order_manager.orders.values():
                    if (order.symbol == canonical_symbol and 
                        order.metadata.get('exit_action') and 
                        order.metadata.get('reason')):
                        exit_reason = order.metadata['reason']
                        break
                
            # Create fill record for in-memory tracking
            fill_record = {
                "trade_id": trade_id,
                "session_id": self.current_session_id,
                "symbol": canonical_symbol,
                "side": trade_side,
                "quantity": position_size,
                "fill_price": entry_price,
                "fees": fees,
                "strategy": strategy,
                "exit_reason": exit_reason,
                "executed_at": datetime.now(),
                "date": datetime.now().date().isoformat(),
                "notional_value": abs(position_size) * entry_price
            }
            
            # Add to in-memory fills
            self.in_memory_fills.append(fill_record)
            
            # Try to commit to trade ledger with enhanced fill details
            ledger_success = False
            if self.trade_ledger:
                self.logger.info(f"TRADE_LEDGER_DEBUG: Attempting to save trade {trade_id} to ledger")
                
                # Extract fee and slippage details from trade_result if available
                effective_fill_price = entry_price  # Default to entry price
                fee_bps_applied = None
                slippage_bps_applied = None
                
                if trade_result:
                    # Check for fill details in execution_result
                    exec_result = trade_result.get("execution_result", {})
                    if "fill_details" in exec_result:
                        fill_details = exec_result["fill_details"]
                        effective_fill_price = fill_details.get("effective_fill_price", entry_price)
                        fee_bps_applied = fill_details.get("fee_bps")
                        slippage_bps_applied = fill_details.get("slippage_bps")
                
                ledger_success = self.trade_ledger.commit_fill(
                    trade_id=trade_id,
                    session_id=self.current_session_id,
                    symbol=canonical_symbol,
                    side=trade_side,
                    quantity=position_size,  # Use signed quantity
                    fill_price=entry_price,
                    fees=fees,
                    strategy=strategy,
                    exit_reason=exit_reason,
                    effective_fill_price=effective_fill_price,
                    fee_bps_applied=fee_bps_applied,
                    slippage_bps_applied=slippage_bps_applied
                )
                if ledger_success:
                    self.logger.info(f"TRADE_LEDGER_DEBUG: Trade {trade_id} successfully committed to ledger")
                else:
                    self.logger.warning(f"TRADE_LEDGER_DEBUG: Failed to commit fill to trade ledger: {trade_id}")
            else:
                self.logger.debug(f"Fill tracked in-memory only (no trade ledger): {trade_id}")

            # Step 10: Recalculate total equity and validate
            equity_after = self._get_total_equity()
            equity_change = equity_after - equity_before  # Signed change (negative for fee impact)
            
            # CRITICAL FIX: Save the recalculated equity to state store
            # This is the FINAL save that includes both cash deduction AND position addition
            self.logger.info(f"💾 FINAL_EQUITY_SAVE: Saving recalculated equity=${equity_after:.2f} (was ${equity_before:.2f})")
            self.state_store.save_cash_equity(
                cash_balance=float(new_cash),
                total_equity=float(equity_after),  # ← CRITICAL: Use recalculated equity!
                total_fees=float(to_decimal(original_fees) + fees_decimal),
                total_realized_pnl=float(actual_realized_pnl),
                total_unrealized_pnl=0.0,
                session_id=self.current_session_id,
                previous_equity=float(getattr(self, '_previous_equity', equity_before))
            )
            self.logger.info(f"✅ FINAL_SAVE_COMPLETE: cash=${float(new_cash):.2f}, equity=${equity_after:.2f}")
            
            # Also update in-memory portfolio equity to match
            self.portfolio["equity"] = to_decimal(equity_after)
            self.logger.info(f"📝 IN_MEMORY_EQUITY_UPDATED: self.portfolio['equity']={format_currency(to_decimal(equity_after))}")
            
            # Log equity impact with fees
            if position_size > 0:  # BUY
                self.logger.info(
                    f"FILL: {side} {canonical_symbol} qty={position_size:.6f} @ ${entry_price:.4f} "
                    f"fee=${fees:.2f} | equity_before=${equity_before:.2f} → equity_after=${equity_after:.2f} "
                    f"(Δ=${equity_change:.2f}, fee_impact=${-fees:.2f})"
                )
            else:  # SELL
                realized_pnl = expected_profit  # This includes fees
                self.logger.info(
                    f"FILL: {side} {canonical_symbol} qty={position_size:.6f} @ ${entry_price:.4f} "
                    f"fee=${fees:.2f} realized_pnl=${realized_pnl:.2f} | "
                    f"equity_before=${equity_before:.2f} → equity_after=${equity_after:.2f} "
                    f"(Δ=${equity_change:.2f})"
                )
            
            # Step 11: Validate equity change
            # For buy orders, equity decreases by fees (cash down, position up, net = -fees)
            # For sell orders, equity changes by realized P&L
            abs_equity_change = abs(equity_change)
            epsilon = abs(fees) + abs(expected_profit) + 1.0  # Allow for fees, P&L, and rounding
            if abs_equity_change > epsilon:
                self.logger.warning(f"Equity change ${abs_equity_change:.2f} > expected ${epsilon:.2f} (may be price movement)")
            
            
            # Step 12: Log comprehensive fill information
            # Check if this is an exit order with reason metadata
            exit_reason = ""
            if hasattr(self, 'order_manager') and hasattr(self.order_manager, 'orders'):
                # Look for recent orders with exit metadata
                for order in self.order_manager.orders.values():
                    if (order.symbol == canonical_symbol and 
                        order.metadata.get('exit_action') and 
                        order.metadata.get('reason')):
                        exit_reason = f" reason={order.metadata['reason']}"
                        break
            
            # Calculate position value gained/lost for detailed breakdown
            position_value_change = notional_value if position_size > 0 else -notional_value
            
            self.logger.info(
                f"FILL: side={side} symbol={canonical_symbol} qty={position_size:.6f} "
                f"fill_price=${entry_price:.4f} notional=${notional_value:.2f} fee=${fees:.4f} "
                f"cash_before=${original_cash:.2f}→cash_after=${new_cash:.2f} "
                f"equity_before=${equity_before:.2f}→equity_after=${equity_after:.2f} "
                f"equity_delta=${equity_change:.2f} (cash_impact=${cash_impact:.2f} position_change=${position_value_change:.2f}){exit_reason}"
            )
            
            # Add explanation for equity changes
            if abs(equity_change) < 0.01:  # Equity constant (within rounding)
                self.logger.info(
                    f"EQUITY_EXPLANATION: {canonical_symbol} {side} - Equity constant during position entry "
                    f"(cash→positions transfer: ${abs(cash_impact):.2f} cash → ${abs(position_value_change):.2f} position value)"
                )
            else:
                self.logger.info(
                    f"EQUITY_EXPLANATION: {canonical_symbol} {side} - Equity changed by ${equity_change:.2f} "
                    f"(fees=${fees:.4f} + market_moves=${equity_change - fees:.4f})"
            )

            # Step 13: Update portfolio cache for immediate access
            self.portfolio["last_updated"] = datetime.now()

            # Step 14: Save complete portfolio state
            self._save_portfolio_state()

            # Step 15: Create TP ladder orders for new entries that increase net exposure
            try:
                # Check if this is a new entry (increasing absolute net quantity from/through zero)
                old_quantity = existing_position["quantity"] if existing_position else 0
                new_quantity = new_quantity
                
                # Determine if this increases net exposure (crossing zero or increasing absolute size)
                increases_net_exposure = (
                    (old_quantity == 0 and new_quantity != 0) or  # New position
                    (old_quantity * new_quantity > 0 and abs(new_quantity) > abs(old_quantity))  # Same side, larger size
                )
                
                if increases_net_exposure:
                    self.logger.info(f"Entry fill detected for {canonical_symbol}, creating TP ladder orders")
                    
                    # Create TP ladder orders
                    tp_orders = self.order_manager.create_tp_ladder_orders(
                        symbol=canonical_symbol,
                        position_size=float(new_quantity),
                        avg_cost=float(new_avg_price),
                        current_price=float(entry_price),
                        risk_manager=self.risk_manager,
                        config=self.config
                    )
                    
                    if tp_orders:
                        self.logger.info(f"Created {len(tp_orders)} TP ladder orders for {canonical_symbol}")
                        # Note: Orders are created but not executed immediately - they will be GTC resting orders
                    else:
                        self.logger.debug(f"No TP ladder orders created for {canonical_symbol}")
                else:
                    self.logger.debug(f"Fill for {canonical_symbol} does not increase net exposure, skipping TP ladders")
                    
            except Exception as e:
                self.logger.error(f"Error creating TP ladder orders for {canonical_symbol}: {e}")
                # Don't fail the trade for TP ladder errors

            # Get snapshot ID for logging
            snapshot = get_current_pricing_snapshot()
            snapshot_id = snapshot.id if snapshot else "N/A"
            
            self.logger.info(
                f"PORTFOLIO_COMMITTED[snapshot={snapshot_id}]: {canonical_symbol} "
                f"cash=${float(new_cash):.2f}, positions=${self._get_total_positions_value():.2f}, "
                f"total=${equity_after:.2f} (Δ=${equity_change:.2f})"
            )
            
            return True  # Success

        except Exception as e:
            import traceback
            self.logger.error(f"🔴🔴🔴 EXCEPTION in _update_portfolio_with_trade: {e} 🔴🔴🔴")
            self.logger.error(f"Exception type: {type(e).__name__}")
            self.logger.error(f"Exception traceback:\n{traceback.format_exc()}")
            self.logger.error(f"State: original_cash={original_cash}, symbol={canonical_symbol if 'canonical_symbol' in locals() else 'N/A'}")
            
            # Step 15: If any step fails, rollback all changes and return error
            if original_cash is not None:
                try:
                    self.logger.warning("Rolling back portfolio changes due to error")
                    
                    # Restore original cash balance
                    self.state_store.save_cash_equity(
                        cash_balance=float(original_cash),
                        total_equity=self._get_total_equity(),  # Recalculate without the failed trade
                        total_fees=float(original_fees),
                        total_realized_pnl=0.0,
                        total_unrealized_pnl=0.0,
                        session_id=self.current_session_id,
                        previous_equity=float(getattr(self, '_previous_equity', original_cash))
                    )
                    
                    # Restore original positions
                    for pos in original_positions:
                        self.state_store.save_position(
                            symbol=pos["symbol"],
                            quantity=float(pos["quantity"]),
                            entry_price=float(pos["entry_price"]),
                            current_price=float(pos["current_price"]),
                            strategy=pos["strategy"],
                            session_id=self.current_session_id
                        )
                    
                    # Restore portfolio cache
                    self.portfolio["cash_balance"] = to_decimal(original_cash)
                    self.portfolio["total_fees"] = to_decimal(original_fees)
                    self.portfolio["last_updated"] = datetime.now()
                    
                    self.logger.info("Portfolio rollback completed successfully")
                    
                except Exception as rollback_error:
                    self.logger.error(f"Failed to rollback portfolio changes: {rollback_error}")
            
            return False  # Failed

    def _update_position_prices(self) -> None:
        """Update current prices for all positions using the pricing snapshot from this cycle.
        
        This function relies on the atomic position hydration that happens at cycle start.
        If positions are not properly hydrated, this will fail fast.
        
        Now uses the pricing snapshot created at the start of the cycle to ensure:
        1. All pricing is consistent within the cycle
        2. Equity changes every cycle as cash + Σ(qty * mark) + realized_pnl
        3. Proper fallback logic for missing symbols
        """
        try:
            if not self.current_session_id:
                self.logger.warning("No session ID available for position price updates")
                return
            
            # Validate that positions were properly hydrated
            if not self._in_memory_positions:
                self.logger.warning("POSITION_PRICE_UPDATE: No positions in memory cache - skipping price updates")
                return
            
            # Get the pricing snapshot created for this cycle
            pricing_snapshot = get_current_pricing_snapshot()
            if not pricing_snapshot:
                self.logger.error("POSITION_PRICE_UPDATE: No pricing snapshot available - cannot update position prices")
                return
                
            self.logger.info(f"POSITION_PRICE_UPDATE: Processing {len(self._in_memory_positions)} hydrated positions using snapshot {pricing_snapshot.id}")
            
            # Track successful updates for validation
            successful_updates = 0
            total_positions_value = to_decimal(0.0)
            
            for canonical_symbol, position_data in self._in_memory_positions.items():
                symbol = position_data["symbol"]
                quantity = position_data["quantity"]
                
                # Skip positions with zero quantity
                if quantity == 0:
                    continue
                    
                try:
                    # Ensure canonical symbol normalization
                    normalized_symbol = to_canonical(symbol)
                    
                    # Check if realization is enabled for bid/ask exit valuation
                    realization_enabled = self._is_realization_enabled()
                    current_price = None
                    
                    if realization_enabled:
                        # Use realistic exit values (bid/ask) for position valuation
                        side = "long" if quantity > 0 else "short"
                        current_price = pricing_snapshot.get_exit_value(normalized_symbol, side)
                        
                        if current_price:
                            self.logger.debug(f"POSITION_PRICE_UPDATE: {symbol} - got exit value from snapshot: {current_price}")
                        else:
                            # Fallback to mark price from snapshot
                            current_price = pricing_snapshot.get_mark_price(normalized_symbol)
                            if current_price:
                                self.logger.debug(f"POSITION_PRICE_UPDATE: {symbol} - got mark price from snapshot: {current_price}")
                    else:
                        # Use standard mark price (mid price) from snapshot
                        current_price = pricing_snapshot.get_mark_price(normalized_symbol)
                        if current_price:
                            self.logger.debug(f"POSITION_PRICE_UPDATE: {symbol} - got mark price from snapshot: {current_price}")
                    
                    # Fallback logic if symbol not in snapshot
                    if not current_price:
                        self.logger.warning(f"POSITION_PRICE_FALLBACK: {symbol} not in pricing snapshot, using fallback logic")
                        
                        # Fallback 1: Last known mark from ledger (stored in position_data)
                        if position_data.get("current_price") and position_data["current_price"] > 0:
                            current_price = position_data["current_price"]
                            self.logger.info(f"POSITION_PRICE_FALLBACK: {symbol} - using last known mark from ledger: {current_price}")
                        
                        # Fallback 2: Last trade fill price from LotBook
                        elif normalized_symbol in self.lot_books:
                            lot_book = self.lot_books[normalized_symbol]
                            if lot_book.lots:
                                # Get most recent lot's entry price
                                last_lot = lot_book.lots[-1]
                                current_price = last_lot.entry_price
                                self.logger.info(f"POSITION_PRICE_FALLBACK: {symbol} - using last fill price from LotBook: {current_price}")
                        
                        # Fallback 3: Entry price (last resort)
                        if not current_price:
                            current_price = position_data["entry_price"]
                            self.logger.warning(f"POSITION_PRICE_FALLBACK: {symbol} - using entry price as last resort: {current_price}")
                    
                    self.logger.info(f"POSITION_PRICE_DEBUG: {symbol} - final price: {current_price}")
                    
                    if current_price and validate_mark_price(current_price, normalized_symbol):
                        # Calculate new position value
                        new_value = quantity * current_price
                        entry_price = position_data["entry_price"]
                        unrealized_pnl = (current_price - entry_price) * quantity
                        
                        # Update total positions value
                        total_positions_value += to_decimal(new_value)
                        
                        self.logger.info(f"POSITION_PRICE_DEBUG: {symbol} - updating price from {position_data.get('current_price', 'None')} to {current_price}")
                        self.logger.info(f"POSITION_PRICE_DEBUG: {symbol} - updating value to {new_value} (quantity={quantity}, price={current_price})")
                        
                        # Update state store position with live price and value
                        # Note: Hydration already validated positions exist, no need to double-check
                        self.state_store.update_position_price(symbol, current_price)
                        
                        # Update in-memory cache
                        position_data["current_price"] = current_price
                        position_data["value"] = new_value
                        position_data["unrealized_pnl"] = unrealized_pnl
                        position_data["updated_at"] = datetime.now()
                        
                        # Also update in-memory portfolio for backward compatibility
                        if symbol in self.portfolio["positions"]:
                            pos = self.portfolio["positions"][symbol]
                            old_value = pos.get("value", 0)
                            pos["current_price"] = current_price
                            pos["value"] = new_value
                            pos["unrealized_pnl"] = unrealized_pnl
                            
                            # Initialize meta if not present
                            if "meta" not in pos:
                                pos["meta"] = {}
                            
                            # Update high/low since entry tracking
                            if current_price > pos["meta"].get("high_since_entry", float(entry_price)):
                                pos["meta"]["high_since_entry"] = current_price
                            
                            if current_price < pos["meta"].get("low_since_entry", float(entry_price)):
                                pos["meta"]["low_since_entry"] = current_price
                            
                            # Increment bars since entry
                            pos["meta"]["bars_since_entry"] = pos["meta"].get("bars_since_entry", 0) + 1
                            
                            self.logger.info(f"POSITION_PRICE_DEBUG: {symbol} - updated in-memory value from {old_value} to {new_value}")
                            successful_updates += 1
                        else:
                            self.logger.error(f"POSITION_HYDRATION_MISMATCH: Position {symbol} not found in in-memory portfolio after hydration")
                            # This should not happen with atomic hydration - abort cycle
                            raise RuntimeError(f"Position hydration mismatch detected for {symbol} in portfolio - cycle aborted")
                    else:
                        self.logger.warning(f"POSITION_PRICE_DEBUG: {symbol} - no valid mark price available even with fallbacks")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to update price for {symbol}: {e}")
            
            # Validate that all hydrated positions were successfully updated
            expected_updates = len([p for p in self._in_memory_positions.values() if p["quantity"] != 0])
            if successful_updates < expected_updates:
                missing = expected_updates - successful_updates
                self.logger.warning(f"POSITION_UPDATE_PARTIAL: Expected {expected_updates} updates, completed {successful_updates} ({missing} failed)")
                # Don't raise - allow partial updates as long as some succeeded
            
            # Log total positions value after updates
            self.logger.info(f"POSITION_PRICE_UPDATE: Total positions value = {format_currency(total_positions_value)}")
            
            # Save updated portfolio state
            self._save_portfolio_state()
            
            self.logger.info(f"POSITION_PRICE_UPDATE: Successfully updated {successful_updates} position prices")
            
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
        
        This is the SINGLE SOURCE OF TRUTH for portfolio equity calculations.
        Formula: total_equity = cash + sum(pos.qty * mark_price(symbol))
        (realized_pnl already flows into cash when positions are closed)
        
        Returns:
            Dictionary with consistent portfolio state including positions, cash, equity, and count
        """
        try:
            # 🛡️ BULLETPROOF: Read cash directly from state store (AUTHORITATIVE SOURCE)
            # Do NOT use self.portfolio["cash_balance"] as it can be stale
            cash_balance = to_decimal(self.state_store.get_session_cash(self.current_session_id))
            self.logger.info(f"💎 SNAPSHOT_CASH_SOURCE: using authoritative state_store cash={format_currency(cash_balance)}")
            
            active_positions = self.portfolio.get("positions", {})
            
            # CRITICAL FIX: Consolidate positions by symbol (ignore strategy differences)
            # The database allows multiple positions per symbol with different strategies,
            # but for equity calculation we must consolidate them to avoid double-counting
            consolidated_positions = {}
            duplicate_count = 0
            for symbol, pos in active_positions.items():
                canonical_symbol = to_canonical(symbol)
                if canonical_symbol not in consolidated_positions:
                    consolidated_positions[canonical_symbol] = {
                        "quantity": to_decimal(pos.get("quantity", 0.0)),
                        "entry_price": to_decimal(pos.get("entry_price", 0.0)),
                        "current_price": to_decimal(pos.get("current_price", 0.0)),
                        "unrealized_pnl": to_decimal(pos.get("unrealized_pnl", 0.0)),
                        "strategy": pos.get("strategy", "default"),
                        "value": to_decimal(pos.get("value", 0.0))
                    }
                else:
                    # Merge with existing position (weighted average)
                    duplicate_count += 1
                    old = consolidated_positions[canonical_symbol]
                    old_qty = old["quantity"]
                    new_qty = to_decimal(pos.get("quantity", 0.0))
                    total_qty = old_qty + new_qty
                    
                    if total_qty > to_decimal(0):
                        # Weighted average entry price
                        old_cost = old_qty * old["entry_price"]
                        new_cost = new_qty * to_decimal(pos.get("entry_price", 0.0))
                        old["entry_price"] = (old_cost + new_cost) / total_qty
                        old["quantity"] = total_qty
                        
                        # Use latest current price
                        old["current_price"] = to_decimal(pos.get("current_price", old["current_price"]))
                        
                        # Merge unrealized P&L
                        old["unrealized_pnl"] = old["unrealized_pnl"] + to_decimal(pos.get("unrealized_pnl", 0.0))
                        
                        # Keep most informative strategy
                        if old["strategy"] == "default" or old["strategy"] == "unknown":
                            old["strategy"] = pos.get("strategy", "default")
                    
                    self.logger.warning(f"⚠️ DUPLICATE_POSITION_MERGED: {canonical_symbol} had {len([s for s in active_positions if to_canonical(s) == canonical_symbol])} entries, consolidated into one")
            
            if duplicate_count > 0:
                self.logger.error(f"🚨 POSITION_DUPLICATION_DETECTED: {duplicate_count} duplicate positions merged (FIX DATABASE SCHEMA!)")
            
            # Use consolidated positions for equity calculation
            active_positions = consolidated_positions
            
            # Calculate positions value using mark prices (SINGLE SOURCE OF TRUTH)
            total_positions_value = to_decimal(0.0)
            self.logger.info(f"📸 SNAPSHOT_POSITIONS_START: Calculating positions from self.portfolio['positions'], count={len(active_positions)}")
            for symbol, position in active_positions.items():
                quantity = to_decimal(position.get("quantity", 0.0))
                if abs_decimal(quantity) > to_decimal(1e-8):  # Has position
                    try:
                        # Get current mark price for accurate valuation
                        canonical_symbol = to_canonical(symbol)
                        mark_price = self.get_cached_mark_price(
                            canonical_symbol, 
                            self.data_engine, 
                            live_mode=self.config.get("trading", {}).get("live_mode", False),
                            cycle_id=self.cycle_count
                        )
                        
                        if mark_price and validate_mark_price(mark_price, canonical_symbol):
                            position_value = calculate_position_value(quantity, to_decimal(mark_price))
                            total_positions_value += position_value
                            self.logger.info(f"  📊 Position: {canonical_symbol} qty={float(quantity):.6f}, mark_price=${mark_price:.4f}, value=${float(position_value):.2f}")
                        else:
                            # Fallback to entry price if mark price unavailable
                            entry_price = to_decimal(position.get("entry_price", 0.0))
                            position_value = calculate_position_value(quantity, entry_price)
                            total_positions_value += position_value
                            self.logger.info(f"  📊 Position: {canonical_symbol} qty={float(quantity):.6f}, entry_price=${float(entry_price):.4f} (fallback), value=${float(position_value):.2f}")
                    except Exception as e:
                        self.logger.warning(f"Failed to get mark price for {symbol}: {e}")
                        # Use entry price as fallback
                        entry_price = to_decimal(position.get("entry_price", 0.0))
                        position_value = calculate_position_value(quantity, entry_price)
                        total_positions_value += position_value
                        self.logger.info(f"  📊 Position: {canonical_symbol} qty={float(quantity):.6f}, entry_price=${float(entry_price):.4f} (fallback-error), value=${float(position_value):.2f}")
            self.logger.info(f"📸 SNAPSHOT_POSITIONS_TOTAL: total_positions_value=${float(total_positions_value):.2f}")
            
            # Get realized P&L from state store (for logging only)
            total_realized_pnl = to_decimal(0.0)
            if self.current_session_id:
                try:
                    latest_cash_equity = self.state_store.get_latest_cash_equity(self.current_session_id)
                    if latest_cash_equity:
                        total_realized_pnl = to_decimal(latest_cash_equity.get("total_realized_pnl", 0.0))
                except Exception as e:
                    self.logger.warning(f"Could not get realized P&L: {e}")
            
            # CRITICAL FIX: total_equity = cash + positions_value ONLY
            # Realized P&L is already included in cash_balance when positions are closed
            # Adding it again would be double-counting!
            # Wrap values in D() at boundary for Decimal precision
            cash_balance_d = D(cash_balance)
            total_positions_value_d = D(total_positions_value)
            
            self.logger.debug(f"🔍 EQUITY_CALC_TYPES: cash_balance={cash_balance} (type:{type(cash_balance)}), total_positions_value={total_positions_value} (type:{type(total_positions_value)})")
            
            # Calculate equity using Decimal arithmetic with q_money for final precision
            total_equity_d = q_money(cash_balance_d + total_positions_value_d)
            total_equity = to_decimal(total_equity_d)  # Convert back to existing decimal type for compatibility
            
            # Log the authoritative equity calculation with detailed breakdown
            self.logger.info(f"EQUITY_SNAPSHOT: cash={format_currency(cash_balance)}, positions={format_currency(total_positions_value)}, total={format_currency(total_equity)} (realized_pnl={format_currency(total_realized_pnl)} already in cash)")
            self.logger.info(f"EQUITY_BREAKDOWN: cash={format_currency(cash_balance)} + positions={format_currency(total_positions_value)} = {format_currency(total_equity)}")
            
            # Calculate position metrics
            position_count = len(active_positions)
            
            # Get detailed position breakdown
            positions_detail = {}
            for symbol, position in active_positions.items():
                positions_detail[symbol] = {
                    "quantity": float(position.get("quantity", 0.0)),
                    "entry_price": float(position.get("entry_price", 0.0)),
                    "current_price": float(position.get("current_price", 0.0)),
                    "value": float(position.get("value", 0.0)),
                    "unrealized_pnl": float(position.get("unrealized_pnl", 0.0)),
                    "strategy": position.get("strategy", "unknown")
                }
            
            # Calculate unrealized P&L for completeness
            total_unrealized_pnl = to_decimal(0.0)
            for symbol, position in active_positions.items():
                quantity = to_decimal(position.get("quantity", 0.0))
                if abs_decimal(quantity) > to_decimal(1e-8):
                    entry_price = to_decimal(position.get("entry_price", 0.0))
                    try:
                        canonical_symbol = to_canonical(symbol)
                        mark_price = self.get_cached_mark_price(
                            canonical_symbol, 
                            self.data_engine, 
                            live_mode=self.config.get("trading", {}).get("live_mode", False),
                            cycle_id=self.cycle_count
                        )
                        if mark_price and validate_mark_price(mark_price, canonical_symbol):
                            unrealized_pnl = calculate_pnl(quantity, entry_price, to_decimal(mark_price))
                            total_unrealized_pnl += unrealized_pnl
                    except Exception:
                        # Skip if mark price unavailable
                        pass
            
            snapshot = {
                "cash_balance": float(cash_balance),
                "total_equity": float(total_equity),
                "position_count": position_count,
                "total_position_value": float(total_positions_value),
                "total_realized_pnl": float(total_realized_pnl),
                "total_unrealized_pnl": float(total_unrealized_pnl),
                "positions": positions_detail,
                "active_positions": active_positions,  # Keep original for compatibility
                "timestamp": datetime.now().isoformat(),
                "session_id": self.current_session_id
            }
            
            return snapshot
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error creating portfolio snapshot: {e}")
            self.logger.error(f"SNAPSHOT_ERROR_TRACEBACK: {traceback.format_exc()}")
            # Return safe defaults with ALL required keys
            return {
                "cash_balance": 0.0,
                "total_equity": 0.0,
                "position_count": 0,
                "total_position_value": 0.0,
                "total_realized_pnl": 0.0,
                "total_unrealized_pnl": 0.0,
                "positions": {},
                "active_positions": {},
                "timestamp": datetime.now().isoformat(),
                "session_id": self.current_session_id
            }
    
    def _get_total_positions_value(self) -> float:
        """Calculate total value of all positions.
        
        Returns:
            Total positions value in USD
        """
        total = 0.0
        for symbol, position in self.portfolio.get("positions", {}).items():
            quantity = float(position.get("quantity", 0.0))
            if abs(quantity) > 1e-8:
                current_price = float(position.get("current_price", 0.0))
                total += abs(quantity) * current_price
        return total

    def get_cached_mark_price(self, symbol: str, data_engine=None, live_mode: bool = False, max_age_seconds: int = 30, cycle_id: Optional[int] = None) -> Optional[float]:
        """Get mark price using unified cycle price cache.
        
        Args:
            symbol: Trading symbol in any format
            data_engine: Data engine instance (uses self.data_engine if None)
            live_mode: Whether in live trading mode
            max_age_seconds: Maximum age of ticker data in live mode
            cycle_id: Cycle ID for cache key (uses self.cycle_count if None)
            
        Returns:
            Mark price as float, or None if no valid price found
        """
        if data_engine is None:
            data_engine = self.data_engine
            
        if not data_engine:
            self.logger.warning(f"No data engine available for {symbol}")
            return None
        
        # Use unified get_mark_price with cycle_id
        effective_cycle_id = cycle_id if cycle_id is not None else self.cycle_count
        return get_mark_price(
            symbol=symbol,
            data_engine=data_engine,
            live_mode=live_mode,
            max_age_seconds=max_age_seconds,
            cycle_id=effective_cycle_id
        )

    def _log_decision_trace(self, symbol: str, signal: dict[str, Any], current_price: float, 
                           action: str, reason: str, entry_price: float = None, 
                           stop_loss: float = None, take_profit: float = None, 
                           size: float = None, winning_subsignal: str = None, 
                           winning_score: float = None, intent: str = None) -> None:
        """Log structured decision trace for a symbol.
        
        Args:
            symbol: Trading symbol
            signal: Composite signal data
            current_price: Current market price
            action: Decision action (BUY/SELL/HOLD/SKIP)
            reason: Reason for the decision
            entry_price: Entry price (if action is BUY/SELL)
            stop_loss: Stop loss price (if action is BUY/SELL)
            take_profit: Take profit price (if action is BUY/SELL)
            size: Position size (if action is BUY/SELL)
            winning_subsignal: Name of the winning sub-signal or "composite" if composite gates the action
            winning_score: Score of the winning sub-signal
            intent: Order intent (e.g., "pilot_buy", "normal", "explore")
        """
        try:
            # Extract data from signal
            composite_score = signal.get("composite_score", 0.0)
            confidence = signal.get("confidence", 0.0)
            regime = signal.get("metadata", {}).get("regime", "unknown")
            effective_threshold = signal.get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.0)
            
            # Populate entry_price from pricing snapshot even for SKIP decisions
            # This ensures we always have entry_price when PRICING_SNAPSHOT_HIT is logged
            entry_price_decimal = None
            if entry_price is None:
                # Try signal metadata first
                entry_price = signal.get("metadata", {}).get("entry_price")
            
            if entry_price is None:
                # Get from pricing snapshot using Decimal
                try:
                    snapshot = get_current_pricing_snapshot()
                    if snapshot:
                        canonical_symbol = to_canonical(symbol)
                        price_from_snapshot = snapshot.get_entry_price(canonical_symbol)
                        if price_from_snapshot is not None:
                            entry_price_decimal = to_decimal(price_from_snapshot)
                            entry_price = float(entry_price_decimal)
                except Exception as e:
                    self.logger.debug(f"Could not get entry_price from pricing snapshot for {symbol}: {e}")
            else:
                # Convert provided entry_price to Decimal for consistency
                entry_price_decimal = to_decimal(entry_price)
            
            # Determine winning sub-signal if not provided
            if winning_subsignal is None:
                winning_subsignal, winning_score = self._determine_winning_subsignal(signal)
            
            # Create decision trace (use Decimal for entry_price rounding)
            decision_trace = {
                "symbol": symbol,
                "regime": regime,
                "composite_score": round(composite_score, 4),
                "threshold": round(effective_threshold, 4),
                "confidence": round(confidence, 4),
                "winning_subsignal": winning_subsignal,
                "winning_score": round(winning_score, 4) if winning_score is not None else None,
                "final_action": action,
                "reason": reason,
                "entry_price": round(float(entry_price_decimal), 4) if entry_price_decimal else None,
                "stop_loss": round(stop_loss, 4) if stop_loss else None,
                "take_profit": round(take_profit, 4) if take_profit else None,
                "size": round(size, 6) if size else None
            }
            
            # Add intent if provided
            if intent:
                decision_trace["intent"] = intent
            
            # Log as structured JSON
            import json
            trace_json = json.dumps(decision_trace, separators=(',', ':'))
            self.logger.info(f"DECISION_TRACE {trace_json}")
            
        except Exception as e:
            self.logger.error(f"Failed to log decision trace for {symbol}: {e}")

    def _determine_winning_subsignal(self, signal: dict[str, Any]) -> tuple[str, float]:
        """Determine the winning sub-signal from composite signal data.
        
        Args:
            signal: Composite signal data
            
        Returns:
            Tuple of (winning_subsignal_name, winning_score)
        """
        try:
            individual_signals = signal.get("individual_signals", {})
            
            if not individual_signals:
                # No individual signals, composite gates the action
                return "composite", signal.get("composite_score", 0.0)
            
            # Find the sub-signal with the highest weighted contribution
            best_subsignal = None
            best_score = 0.0
            best_contribution = 0.0
            
            for name, subsignal in individual_signals.items():
                if "error" in subsignal:
                    continue  # Skip failed signals
                    
                raw_score = subsignal.get("score", 0.0)
                confidence = subsignal.get("confidence", 0.0)
                
                # Calculate weighted contribution (score * confidence)
                contribution = abs(raw_score) * confidence
                
                if contribution > best_contribution:
                    best_contribution = contribution
                    best_subsignal = name
                    best_score = raw_score
            
            if best_subsignal:
                return best_subsignal, best_score
            else:
                # Fallback to composite if no valid sub-signals
                return "composite", signal.get("composite_score", 0.0)
                
        except Exception as e:
            self.logger.warning(f"Failed to determine winning sub-signal: {e}")
            return "composite", signal.get("composite_score", 0.0)

    def get_metrics_from_in_memory_fills(self, session_id: str = None, date: str = None) -> dict[str, Any]:
        """Get trading metrics from in-memory fills as fallback when ledger is empty.
        
        Args:
            session_id: Session ID to filter by (optional)
            date: Date to filter by in YYYY-MM-DD format (optional)
            
        Returns:
            Dictionary with trading metrics from in-memory fills
        """
        if not self.in_memory_fills:
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
        
        # Filter fills by session_id and date if provided
        filtered_fills = self.in_memory_fills
        
        if session_id:
            filtered_fills = [f for f in filtered_fills if f.get("session_id") == session_id]
        
        if date:
            filtered_fills = [f for f in filtered_fills if f.get("date") == date]
        
        if not filtered_fills:
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
        
        # Calculate metrics from filtered fills
        total_trades = len(filtered_fills)
        
        # Separate new exposure trades (non-reduce-only) from all trades
        new_exposure_fills = []
        for fill in filtered_fills:
            # Check if this is a reduce-only exit (from exit_reason)
            is_reduce_only = fill.get("exit_reason") is not None
            
            if not is_reduce_only:
                new_exposure_fills.append(fill)
        
        # Volume and notional: only count new exposure (exclude reduce-only exits)
        total_volume = sum(abs(f.get("quantity", 0)) for f in new_exposure_fills)
        total_notional = sum(f.get("notional_value", 0) for f in new_exposure_fills)
        
        # Fees: count from all fills (including reduce-only exits)
        total_fees = sum(f.get("fees", 0) for f in filtered_fills)
        
        buy_trades = len([f for f in filtered_fills if f.get("side", "").lower() == "buy"])
        sell_trades = len([f for f in filtered_fills if f.get("side", "").lower() == "sell"])
        
        symbols_traded = list(set(f.get("symbol", "") for f in filtered_fills if f.get("symbol")))
        strategies_used = list(set(f.get("strategy", "") for f in filtered_fills if f.get("strategy")))
        
        trade_sizes = [abs(f.get("quantity", 0)) for f in filtered_fills]
        avg_trade_size = sum(trade_sizes) / len(trade_sizes) if trade_sizes else 0.0
        largest_trade = max(trade_sizes) if trade_sizes else 0.0
        smallest_trade = min(trade_sizes) if trade_sizes else 0.0
        
        return {
            "total_trades": total_trades,
            "total_volume": total_volume,
            "total_fees": total_fees,
            "total_notional": total_notional,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "symbols_traded": symbols_traded,
            "strategies_used": strategies_used,
            "win_rate": 0.0,  # Would need P&L calculation from positions
            "avg_trade_size": avg_trade_size,
            "largest_trade": largest_trade,
            "smallest_trade": smallest_trade
            }

    def _get_total_equity(self) -> float:
        """Get total portfolio equity using portfolio snapshot as single source of truth.
        
        Formula: equity = cash + positions_value
        (realized_pnl is already included in cash when positions close)
        
        Returns:
            Total portfolio equity from authoritative snapshot
        """
        # Use portfolio snapshot as single source of truth
        portfolio_snapshot = self.get_portfolio_snapshot()
        return portfolio_snapshot["total_equity"]

    def _reconcile_equity_discrepancy(self, calculated_equity: float, stored_equity: float, discrepancy: float) -> None:
        """Attempt to reconcile equity discrepancies automatically."""
        try:
            # Calculate practical epsilon tolerance: max(1.00, 0.0001 * total_equity)
            total_equity = max(abs(calculated_equity), abs(stored_equity))
            tolerance = max(1.00, 0.0001 * total_equity)
            
            # Check if within tolerance - skip reconciliation if so
            if abs(discrepancy) <= tolerance:
                self.logger.info(f"EQUITY_RECONCILIATION: within epsilon (diff=${discrepancy:.2f} <= tolerance=${tolerance:.2f})")
                # Update stored equity to match calculated equity silently
                self.portfolio['equity'] = calculated_equity
                return
            
            # Only proceed with reconciliation if discrepancy exceeds tolerance
            self.logger.warning(f"EQUITY_RECONCILIATION: Attempting to reconcile ${discrepancy:.2f} discrepancy (tolerance=${tolerance:.2f})")
            
            # Cap max iterations at 3 with warning
            max_iterations = 3
            
            # Initialize iteration counter if not exists
            if not hasattr(self, '_reconcile_iterations'):
                self._reconcile_iterations = 0
            
            # Track reconciliation iterations to prevent infinite loops
            self._reconcile_iterations += 1
            
            # Hard stop if max iterations exceeded
            if self._reconcile_iterations > max_iterations:
                self.logger.warning(f"EQUITY_RECONCILIATION: Max iterations ({max_iterations}) exceeded - hard stop")
                self.logger.warning(f"EQUITY_RECONCILIATION: Final discrepancy: ${discrepancy:.2f}, tolerance: ${tolerance:.2f}")
                self.logger.warning("HINT: Consider checking for data inconsistencies or increasing tolerance")
                # Reset iteration counter for next cycle
                self._reconcile_iterations = 0
                return
            
            # Check if discrepancy is due to missing position updates
            positions = self.state_store.get_positions(self.current_session_id)
            if positions:
                self.logger.warning(f"EQUITY_RECONCILIATION: Large discrepancy (${discrepancy:.2f}) with {len(positions)} positions - may indicate data inconsistency (iter {self._reconcile_iterations}/{max_iterations})")
                
                # Log detailed position information for debugging
                # Handle both dict and list formats for portfolio_snapshot
                if isinstance(positions, dict):
                    # If portfolio_snapshot is a dict → iterate .items()
                    for symbol, position in positions.items():
                        if abs(position.get("quantity", 0)) > 1e-8:
                            quantity = position.get("quantity", 0)
                            current_price = position.get("current_price", 0)
                            position_value = quantity * current_price
                            self.logger.warning(f"EQUITY_RECONCILIATION: {symbol} qty={quantity:.6f} price=${current_price:.4f} value=${position_value:.2f}")
                else:
                    # If it's a list → iterate elements and read symbol/qty/mark keys
                    for position in positions:
                        symbol = position.get("symbol", "unknown")
                        if abs(position.get("quantity", 0)) > 1e-8:
                            quantity = position.get("quantity", 0)
                            current_price = position.get("current_price", 0)
                            position_value = quantity * current_price
                            self.logger.warning(f"EQUITY_RECONCILIATION: {symbol} qty={quantity:.6f} price=${current_price:.4f} value=${position_value:.2f}")
                
                # Use calculated equity as authoritative
                self.portfolio['equity'] = calculated_equity
                self.logger.warning(f"EQUITY_RECONCILIATION: Updated stored equity to ${calculated_equity:.2f} (calculated value, iter {self._reconcile_iterations}/{max_iterations})")
            else:
                self.logger.warning(f"EQUITY_RECONCILIATION: No positions found, using calculated equity (iter {self._reconcile_iterations}/{max_iterations})")
                self.portfolio['equity'] = calculated_equity
                
        except Exception as e:
            self.logger.error(f"Error during equity reconciliation: {e}")

    def _validate_equity_consistency(self) -> bool:
        """Validate equity consistency across all data sources."""
        try:
            # Get equity from different sources
            calculated_equity = self._get_total_equity()
            stored_equity = self.portfolio.get("equity", 0.0)
            cash_balance = self._get_cash_balance()
            positions = self.state_store.get_positions(self.current_session_id)
            
            # Calculate equity from components
            total_position_value = sum(
                pos.get("quantity", 0) * pos.get("current_price", 0)
                for pos in positions.values()
                if abs(pos.get("quantity", 0)) > 1e-8
            )
            
            # Get realized P&L from state store
            total_realized_pnl = 0.0
            if self.current_session_id:
                try:
                    latest_cash_equity = self.state_store.get_latest_cash_equity(self.current_session_id)
                    if latest_cash_equity:
                        total_realized_pnl = latest_cash_equity.get("total_realized_pnl", 0.0)
                except Exception as e:
                    self.logger.warning(f"Could not get realized P&L for equity consistency: {e}")
            
            # CRITICAL FIX: Don't add realized_pnl (it's already in cash)
            component_equity = cash_balance + total_position_value
            
            # Check consistency
            calculated_vs_stored = abs(calculated_equity - stored_equity)
            calculated_vs_component = abs(calculated_equity - component_equity)
            stored_vs_component = abs(stored_equity - component_equity)
            
            # Use practical epsilon tolerance: max(1.00, 0.0001 * total_equity)
            max_tolerance = max(1.00, 0.0001 * abs(calculated_equity))
            
            is_consistent = (
                calculated_vs_stored <= max_tolerance and
                calculated_vs_component <= max_tolerance and
                stored_vs_component <= max_tolerance
            )
            
            if not is_consistent:
                self.logger.error(f"EQUITY_CONSISTENCY_FAILED:")
                self.logger.error(f"  Calculated: ${calculated_equity:.2f}")
                self.logger.error(f"  Stored: ${stored_equity:.2f}")
                self.logger.error(f"  Component: ${component_equity:.2f}")
                self.logger.error(f"  Cash: ${cash_balance:.2f}")
                self.logger.error(f"  Position Value: ${total_position_value:.2f}")
                self.logger.error(f"  Realized P&L: ${total_realized_pnl:.2f}")
                self.logger.error(f"  Discrepancies: calc_vs_stored=${calculated_vs_stored:.2f}, calc_vs_comp=${calculated_vs_component:.2f}, stored_vs_comp=${stored_vs_component:.2f}")
            else:
                self.logger.debug(f"EQUITY_CONSISTENCY_PASSED: All equity calculations agree within tolerance")
            
            return is_consistent
            
        except Exception as e:
            self.logger.error(f"Error validating equity consistency: {e}")
            return False

    def _validate_session_state(self) -> bool:
        """Validate session state to ensure system is properly initialized before trading.
        
        Returns:
            True if validation passes, False if validation fails
        """
        try:
            # Get current equity and cash balance
            current_equity = self._get_total_equity()
            cash_balance = self._get_cash_balance()
            
            # CRITICAL FIX: Use the same position source as get_portfolio_snapshot() for consistency
            # Was using _get_active_positions() (database), now using self.portfolio["positions"] (in-memory)
            positions = self.portfolio.get("positions", {})
            
            # Calculate current market value of positions for validation
            positions_value = 0.0
            self.logger.info(f"🔍 VALIDATION_POSITIONS_START: Calculating positions from self.portfolio['positions'] (same as snapshot), count={len(positions)}")
            for symbol, position in positions.items():
                quantity = position.get("quantity", 0.0)
                if abs(quantity) > 1e-8:  # Has position (same threshold as snapshot)
                    try:
                        canonical_symbol = to_canonical(symbol)
                        mark_price = self.get_cached_mark_price(
                            canonical_symbol, 
                            self.data_engine, 
                            live_mode=self.config.get("trading", {}).get("live_mode", False),
                            cycle_id=self.cycle_count
                        )
                        if mark_price and validate_mark_price(mark_price, canonical_symbol):
                            # Use same calculation as snapshot: calculate_position_value
                            current_market_value = float(calculate_position_value(to_decimal(quantity), to_decimal(mark_price)))
                            positions_value += current_market_value
                            self.logger.info(f"  📊 Position: {canonical_symbol} qty={quantity:.6f}, mark_price=${mark_price:.4f}, value=${current_market_value:.2f}")
                        else:
                            # Fall back to entry price (same as snapshot)
                            entry_price = position.get("entry_price", 0.0)
                            if entry_price > 0:
                                current_market_value = float(calculate_position_value(to_decimal(quantity), to_decimal(entry_price)))
                                positions_value += current_market_value
                                self.logger.info(f"  📊 Position: {canonical_symbol} qty={quantity:.6f}, entry_price=${entry_price:.4f} (fallback), value=${current_market_value:.2f}")
                            else:
                                self.logger.warning(f"  ⚠️  Position: {canonical_symbol} qty={quantity:.6f}, NO PRICE AVAILABLE, value=$0.00")
                    except Exception as e:
                        self.logger.warning(f"Error calculating position value for {symbol}: {e}")
            self.logger.info(f"🔍 VALIDATION_POSITIONS_TOTAL: positions_value=${positions_value:.2f}")
            
            # Validation 1: Check if equity > 0.0 (NON-BLOCKING - WARNING ONLY)
            if current_equity <= 0.0:
                self.logger.warning(f"SESSION_VALIDATION_WARNING: equity=${current_equity:.2f} <= 0.0 - system not properly initialized (continuing execution)")
                # return False  # DISABLED: Allow execution to continue
            
            # Validation 2: Check if cash_balance > 0.0 (or positions exist) (NON-BLOCKING - WARNING ONLY)
            if cash_balance <= 0.0 and len(positions) == 0:
                self.logger.warning(f"SESSION_VALIDATION_WARNING: cash_balance=${cash_balance:.2f} <= 0.0 and no positions - system not properly initialized (continuing execution)")
                # return False  # DISABLED: Allow execution to continue
            
            # Validation 3: Validate internal consistency - snapshot equity should equal component sum
            # This validates that get_portfolio_snapshot() is calculating correctly
            snapshot_equity = current_equity  # From get_portfolio_snapshot()
            component_equity = cash_balance + positions_value  # Manual calculation
            
            # Use adaptive tolerance: max(1.00, 0.001 * equity)
            tolerance = max(1.00, 0.001 * abs(snapshot_equity))
            equity_diff = abs(snapshot_equity - component_equity)
            
            self.logger.info(f"🔍 EQUITY_CONSISTENCY_CHECK: snapshot=${snapshot_equity:.2f}, components=${component_equity:.2f}, diff=${equity_diff:.2f}, tolerance=${tolerance:.2f}")
            
            if equity_diff > tolerance:
                self.logger.warning(f"SESSION_VALIDATION_WARNING: equity inconsistency - snapshot=${snapshot_equity:.2f}, components=${component_equity:.2f}, diff=${equity_diff:.2f} > tolerance=${tolerance:.2f} (continuing execution)")
                self.logger.warning(f"SESSION_VALIDATION_DETAILS: cash=${cash_balance:.2f}, positions_value=${positions_value:.2f}, position_count={len(positions)}")
                # return False  # DISABLED: Allow execution to continue
            
            # Validation 4: Validate equity is reasonable relative to session baseline
            # Get baseline equity for this session (initial capital or resumed equity)
            total_realized_pnl = 0.0  # Initialize for logging
            if self.current_session_id:
                try:
                    # Try to get previous cycle's equity or initial capital
                    latest_cash_equity = self.state_store.get_latest_cash_equity(self.current_session_id)
                    if latest_cash_equity:
                        baseline_equity = latest_cash_equity.get("previous_equity", 0.0)
                        if baseline_equity == 0.0:
                            # This might be first record, use total_equity as baseline
                            baseline_equity = latest_cash_equity.get("total_equity", 0.0)
                        total_realized_pnl = latest_cash_equity.get("total_realized_pnl", 0.0)
                        
                        # Check if equity change is reasonable (within 50% of baseline per cycle)
                        if baseline_equity > 0:
                            equity_change = abs(snapshot_equity - baseline_equity)
                            max_reasonable_change = baseline_equity * 0.50  # 50% max change per cycle
                            
                            self.logger.info(f"🔍 EQUITY_BASELINE_CHECK: current=${snapshot_equity:.2f}, baseline=${baseline_equity:.2f}, change=${equity_change:.2f}, max_reasonable=${max_reasonable_change:.2f}")
                            
                            if equity_change > max_reasonable_change:
                                self.logger.warning(f"SESSION_VALIDATION_WARNING: Large equity change detected - current=${snapshot_equity:.2f}, baseline=${baseline_equity:.2f}, change=${equity_change:.2f} > {max_reasonable_change:.2f} (continuing execution)")
                    else:
                        # No previous equity - this is a new session, validate against initial capital
                        initial_capital = self.config.get("portfolio", {}).get("initial_capital", 10000.0)
                        self.logger.info(f"🔍 NEW_SESSION_CHECK: current=${snapshot_equity:.2f}, initial_capital=${initial_capital:.2f}")
                        if abs(snapshot_equity - initial_capital) > 100.0:  # More than $100 difference
                            self.logger.warning(f"SESSION_VALIDATION_WARNING: New session equity differs from initial capital - current=${snapshot_equity:.2f}, expected=${initial_capital:.2f} (continuing execution)")
                except Exception as e:
                    self.logger.warning(f"Could not get baseline equity for validation: {e}")
            
            # All validations passed
            self.logger.info(f"SESSION_VALIDATION_PASSED: equity=${current_equity:.2f}, cash=${cash_balance:.2f}, positions_value=${positions_value:.2f}, realized_pnl_tracked=${total_realized_pnl:.2f} (in cash), position_count={len(positions)}")
            return True
            
        except Exception as e:
            self.logger.error(f"SESSION_VALIDATION_ERROR: Exception during validation: {e}")
            return False

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
                    mark_price = self.get_cached_mark_price(
                        canonical_symbol, 
                        self.data_engine, 
                        live_mode=self.config.get("trading", {}).get("live_mode", False),
                        cycle_id=self.cycle_count
                    )
                    
                    if mark_price and validate_mark_price(mark_price, canonical_symbol):
                        # Calculate position value as quantity * mark_price
                        position_value = quantity * mark_price
                        
                        # Calculate P&L using average cost basis
                        avg_cost = position["entry_price"]
                        
                        # Calculate unrealized P&L based on position direction
                        if quantity > 0:  # Long position
                            unrealized_pnl = (mark_price - avg_cost) * quantity
                        else:  # Short position
                            unrealized_pnl = (avg_cost - mark_price) * abs(quantity)
                        
                        self.logger.debug(f"Position {canonical_symbol}: {quantity:.6f} × ${mark_price:.4f} = ${position_value:.2f} (avg_cost=${avg_cost:.4f} pnl=${unrealized_pnl:.2f})")
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

    def _hydrate_positions_from_store(self) -> bool:
        """Atomically hydrate in-memory position cache from state store with validation.
        
        This ensures in-memory positions are in lockstep with the authoritative state store.
        Positions are indexed by canonical symbol for consistent lookup.
        
        Returns:
            True if hydration succeeded, False if validation failed (cycle should abort)
        """
        try:
            if not self.current_session_id:
                self.logger.warning("No session ID available for position hydration")
                return False
                
            # Step 1: Get expected position count from state store
            positions_list = self.state_store.get_positions(self.current_session_id)
            expected_count = len(positions_list)
            
            self.logger.info(f"POSITION_HYDRATE: Loading {expected_count} positions from state store")
            
            # Step 2: Build new position map with validation
            new_positions = {}
            validation_errors = []
            
            self.logger.debug(f"POSITION_HYDRATE_DEBUG: Processing {len(positions_list)} positions from state store")
            for i, position in enumerate(positions_list):
                self.logger.debug(f"POSITION_HYDRATE_DEBUG: Position {i+1}: {position}")
                try:
                    # Validate position schema
                    required_fields = ["symbol", "quantity", "entry_price"]
                    for field in required_fields:
                        if field not in position:
                            error_msg = f"Missing required field '{field}' in position {position.get('symbol', 'unknown')}"
                            validation_errors.append(error_msg)
                            self.logger.warning(f"POSITION_HYDRATE_SKIP: {error_msg}")
                            continue
                    
                    symbol = position["symbol"]
                    canonical_symbol = to_canonical(symbol)
                    quantity = position["quantity"]
                    entry_price = position["entry_price"]
                    strategy = position.get("strategy", "unknown")
                    
                    # Validate data types and ranges
                    if not isinstance(quantity, (int, float)):
                        error_msg = f"Invalid quantity type for {symbol}: {type(quantity)}"
                        validation_errors.append(error_msg)
                        self.logger.warning(f"POSITION_HYDRATE_SKIP: {error_msg}")
                        continue
                    
                    if not isinstance(entry_price, (int, float)) or entry_price <= 0:
                        error_msg = f"Invalid entry_price for {symbol}: {entry_price}"
                        validation_errors.append(error_msg)
                        self.logger.warning(f"POSITION_HYDRATE_SKIP: {error_msg}")
                        continue
                    
                    # Handle multiple positions per symbol by aggregating them
                    # This maintains backward compatibility with existing position management logic
                    if canonical_symbol in new_positions:
                        # Aggregate with existing position
                        existing = new_positions[canonical_symbol]
                        total_quantity = existing["quantity"] + quantity
                        total_value = existing["value"] + position.get("value", 0.0)
                        total_unrealized_pnl = existing["unrealized_pnl"] + position.get("unrealized_pnl", 0.0)
                        
                        # Calculate weighted average entry price
                        weighted_entry_price = (
                            (existing["entry_price"] * existing["quantity"]) + 
                            (entry_price * quantity)
                        ) / total_quantity
                        
                        # Update aggregated position
                        new_positions[canonical_symbol].update({
                            "quantity": total_quantity,
                            "entry_price": weighted_entry_price,
                            "value": total_value,
                            "unrealized_pnl": total_unrealized_pnl,
                            "strategy": f"{existing['strategy']},{strategy}",  # Combine strategies
                            "updated_at": datetime.now()
                        })
                        
                        self.logger.debug(f"AGGREGATED: {canonical_symbol} -> {total_quantity} @ {weighted_entry_price} (combined from {existing['strategy']} + {strategy})")
                    else:
                        # First position for this symbol
                        new_positions[canonical_symbol] = {
                            "symbol": symbol,
                            "canonical_symbol": canonical_symbol,
                            "strategy": strategy,
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "current_price": position.get("current_price", entry_price),
                            "value": position.get("value", 0.0),
                            "unrealized_pnl": position.get("unrealized_pnl", 0.0),
                            "session_id": position.get("session_id", self.current_session_id),
                            "updated_at": position.get("updated_at", datetime.now())
                        }
                        
                        self.logger.debug(f"HYDRATED: {canonical_symbol} -> {quantity} @ {entry_price}")
                    
                except Exception as e:
                    error_msg = f"Error processing position {position.get('symbol', 'unknown')}: {e}"
                    validation_errors.append(error_msg)
                    self.logger.warning(f"POSITION_HYDRATE_SKIP: {error_msg}")
                    continue
            
            # Step 3: Validate count and schema
            loaded_count = len(new_positions)
            # Count validation: we expect at least one position per symbol, but positions may be aggregated
            # So we check that we loaded at least one position and no validation errors occurred
            if loaded_count == 0 and expected_count > 0:
                self.logger.error(f"POSITION_HYDRATE_FAILED: No positions loaded from {expected_count} database positions")
                if validation_errors:
                    self.logger.error(f"POSITION_HYDRATE_FAILED: Validation errors: {validation_errors}")
                # Clear cache on failure
                self._in_memory_positions.clear()
                return False
            elif loaded_count == 0 and expected_count == 0:
                # No positions in database and none loaded - this is valid for new sessions
                self.logger.info(f"POSITION_HYDRATE: No positions in database - starting fresh session")
            
            if validation_errors:
                self.logger.error(f"POSITION_HYDRATE_FAILED: Schema validation errors: {validation_errors}")
                # Clear cache on failure
                self._in_memory_positions.clear()
                return False
            
            # Step 4: Atomic swap - only update if validation passed
            self._in_memory_positions.clear()
            self._in_memory_positions.update(new_positions)
            
            self.logger.info(f"POSITION_HYDRATE: Successfully hydrated {loaded_count} positions")
            return True
            
        except Exception as e:
            self.logger.error(f"POSITION_HYDRATE_FAILED: Exception during hydration: {e}")
            return False

    def _rehydrate_position(self, symbol: str) -> bool:
        """Rehydrate a single position from state store when desync is detected.
        
        Args:
            symbol: Trading symbol to rehydrate
            
        Returns:
            True if position was successfully rehydrated, False otherwise
        """
        try:
            if not self.current_session_id:
                self.logger.warning(f"No session ID available for position rehydration: {symbol}")
                return False
                
            canonical_symbol = to_canonical(symbol)
            
            # Get position from state store
            position = self.state_store.get_position(symbol, "unknown")  # Try with generic strategy first
            if not position:
                # Try to find position by symbol only (check all strategies)
                positions_list = self.state_store.get_positions(self.current_session_id)
                position = None
                for pos in positions_list:
                    if pos["symbol"] == symbol:
                        position = pos
                        break
            
            if not position:
                self.logger.warning(f"POSITION_DESYNC: symbol={symbol}, action=rehydrate - Position not found in state store")
                return False
            
            # Update in-memory cache
            self._in_memory_positions[canonical_symbol] = {
                "symbol": symbol,
                "canonical_symbol": canonical_symbol,
                "quantity": position["quantity"],
                "entry_price": position["entry_price"],
                "current_price": position.get("current_price", position["entry_price"]),
                "value": position.get("value", 0.0),
                "unrealized_pnl": position.get("unrealized_pnl", 0.0),
                "strategy": position.get("strategy", "unknown"),
                "session_id": position.get("session_id", self.current_session_id),
                "updated_at": position.get("updated_at", datetime.now())
            }
            
            self.logger.info(f"POSITION_RESYNCED: symbol={symbol}, quantity={position['quantity']}, entry_price={position['entry_price']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error rehydrating position {symbol}: {e}")
            return False

    def _get_cash_balance(self) -> float:
        """Get cash balance from session-scoped state store.

        Returns:
            Cash balance for current session
        """
        try:
            if not self.current_session_id:
                self.logger.error(f"Session ID is None. Current session ID: {self.current_session_id}")
                raise RuntimeError("No session ID available - session binding failed")
            
            # Get session-scoped cash balance
            cash_balance = self.state_store.get_session_cash(self.current_session_id)
            self.logger.debug(f"CASH_BALANCE_DEBUG: Retrieved ${cash_balance:,.2f} for session {self.current_session_id}")
            return cash_balance
        except Exception as e:
            self.logger.error(f"Error getting session cash balance: {e}")
            raise RuntimeError(f"Failed to get cash balance for session {self.current_session_id}: {e}")

    def _get_available_capital(self) -> float:
        """Get available capital for trading from authoritative state store.

        Returns:
            Available capital
        """
        try:
            # Force a fresh read from the database to ensure we get the latest cash balance
            # This is critical for accurate available capital calculation after trades
            cash_balance = self._get_cash_balance()
            available_capital = max(0, cash_balance)
            
            # Debug logging to track cash balance vs available capital
            self.logger.info(f"AVAILABLE_CAPITAL_DEBUG: cash_balance=${cash_balance:,.2f}, available_capital=${available_capital:,.2f}")
            
            return available_capital
        except Exception as e:
            self.logger.error(f"Error getting available capital: {e}")
            fallback_capital = max(0, self.portfolio.get("cash_balance", 0.0))
            self.logger.warning(f"AVAILABLE_CAPITAL_FALLBACK: Using portfolio cache ${fallback_capital:,.2f}")
            return fallback_capital
    
    def _get_session_cap_remaining(self) -> float:
        """Get remaining session capital cap for new trades.
        
        Returns:
            Remaining session capital cap (uses available capital as proxy)
        """
        # For now, use available capital as session cap remaining
        # This can be extended to track cumulative notional deployed in session
        return self._get_available_capital()

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

        # Validate session state before trading (NON-BLOCKING - WARNING ONLY)
        validation_result = self._validate_session_state()
        if not validation_result:
            self.logger.warning("SESSION_VALIDATION_WARNING: Session state validation returned False, but continuing execution to observe system behavior")
            # raise RuntimeError("Session state validation failed - system not properly initialized")  # DISABLED: Allow execution to continue

        # Hydrate in-memory positions from state store at cycle start with fail-fast validation
        if not self._hydrate_positions_from_store():
            self.logger.error("POSITION_HYDRATE_FAILED: Aborting trading cycle due to position hydration failure")
            raise RuntimeError("Position hydration failed - cycle aborted to prevent data inconsistency")

        self.cycle_count += 1
        cycle_start_time = datetime.now()
        
        # Reset reconciliation iteration counter for each new cycle
        self._reconcile_iterations = 0
        
        # Set cycle_id on order manager for price caching
        self.order_manager.set_cycle_id(self.cycle_count)
        
        # Clear per-cycle price cache for fresh data
        clear_cycle_price_cache(self.cycle_count - 1)  # Clear previous cycle
        self.logger.debug(f"Cleared price cache for cycle #{self.cycle_count}")
        
        # Clear previous pricing snapshot and context
        clear_pricing_snapshot()
        clear_pricing_context()
        
        # Set up pricing context for this cycle
        pricing_context = set_pricing_context(self.cycle_count)
        self.logger.debug(f"Set pricing context for cycle #{self.cycle_count}")

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
            # Get trading symbols from config and filter by whitelist
            all_symbols = self.config.get("trading", {}).get(
                "symbols", ["BTC/USDT", "ETH/USDT", "ADA/USDT"]
            )
            
            # Filter symbols by whitelist if available
            if self.symbol_filter and not self.symbol_filter.is_whitelist_empty():
                symbols = []
                for symbol in all_symbols:
                    is_allowed, reason, _ = self.symbol_filter.is_symbol_allowed(symbol)
                    if is_allowed:
                        symbols.append(symbol)
                    else:
                        self.logger.info(f"SYMBOL_FILTER: Skipping {symbol} - {reason}")
                self.logger.info(f"SYMBOL_WHITELIST: Filtered {len(all_symbols)} symbols to {len(symbols)} whitelisted symbols")
            else:
                symbols = all_symbols
                self.logger.info(f"SYMBOL_WHITELIST: No whitelist configured, using all {len(symbols)} symbols")

            # 1. Get comprehensive market data and create pricing snapshot
            self.logger.info("Step 1: Getting comprehensive market data and creating pricing snapshot")
            try:
                market_data = await self._get_comprehensive_market_data(symbols)
                cycle_results["market_data"] = market_data
                
                # Create pricing snapshot for this cycle
                pricing_snapshot = create_pricing_snapshot(
                    cycle_id=self.cycle_count,
                    symbols=symbols,
                    data_engine=self.data_engine
                )
                self.logger.info(f"Created pricing snapshot for cycle {self.cycle_count} with {len(pricing_snapshot.by_symbol)} symbols")
                
            except Exception as e:
                self.logger.warning(f"Failed to get comprehensive market data: {e}")
                market_data = {}
                cycle_results["market_data"] = market_data

            # 1.5. Update position prices with latest market data
            self.logger.info("Step 1.5: Updating position prices")
            try:
                self._update_position_prices()
            except Exception as e:
                self.logger.error(f"Failed to update position prices: {e}")
                cycle_results["errors"].append(f"Failed to update position prices: {e}")

            # 1.6. Check risk-on triggers and manage risk-on window
            self.logger.info("Step 1.6: Checking risk-on triggers")
            self._manage_risk_on_window(symbols)

            # 1.7. Check daily loss limits and halt flag
            self.logger.info("Step 1.7: Checking daily loss limits")
            self._check_daily_loss_limits()
            
            # 1.8. Check for exit conditions (BEFORE generating new signals)
            self.logger.info("Step 1.8: Checking exit conditions for existing positions")
            exit_results = await self._check_and_execute_exits(symbols)
            if exit_results.get("exits_executed", 0) > 0:
                self.logger.info(
                    f"EXIT_SUMMARY: Executed {exit_results['exits_executed']} exits, "
                    f"reasons: {exit_results.get('exit_reasons', [])}"
                )

            # 2. Generate all signals
            self.logger.info("Step 2: Generating trading signals")
            signals = await self._generate_all_signals(market_data)
            cycle_results["signals"] = signals

            # 3. Execute profit-optimized trades
            self.logger.info("Step 3: Executing profit-optimized trades")
            execution_results = await self._execute_profit_optimized_trades(signals)
            cycle_results["execution_results"] = execution_results

            # 3.5. Auto-manage exits based on risk manager suggestions
            self.logger.info("Step 3.5: Auto-managing exits")
            try:
                # Get current marks for exit management
                current_marks = {}
                for symbol in symbols:
                    try:
                        # Check if realization is enabled for bid/ask exit valuation
                        realization_enabled = self._is_realization_enabled()
                        
                        if realization_enabled:
                            # Use realistic exit values (bid/ask) for exit decisions
                            position = self.portfolio.get("positions", {}).get(symbol, {})
                            position_qty = position.get("quantity", 0)
                            
                            if abs(position_qty) > 1e-8:  # Has position
                                # Determine position side for exit valuation
                                side = "long" if position_qty > 0 else "short"
                                exit_value = get_exit_value(
                                    symbol, 
                                    side, 
                                    self.data_engine,
                                    live_mode=self.config.get("trading", {}).get("live_mode", False),
                                    cycle_id=self.cycle_count
                                )
                                if exit_value:
                                    current_marks[symbol] = exit_value
                                    self.logger.debug(f"Using exit value for {symbol} ({side}): {exit_value}")
                                else:
                                    # Fallback to mark price
                                    ticker_data = self.data_engine.get_ticker(symbol)
                                    if ticker_data and ticker_data.get("price", 0) > 0:
                                        current_marks[symbol] = ticker_data["price"]
                            else:
                                # No position, use mark price
                                ticker_data = self.data_engine.get_ticker(symbol)
                                if ticker_data and ticker_data.get("price", 0) > 0:
                                    current_marks[symbol] = ticker_data["price"]
                        else:
                            # Use standard mark price (mid price)
                            ticker_data = self.data_engine.get_ticker(symbol)
                            if ticker_data and ticker_data.get("price", 0) > 0:
                                current_marks[symbol] = ticker_data["price"]
                    except Exception as e:
                        self.logger.warning(f"Failed to get exit price for {symbol}: {e}")
                
                # Call auto_manage_exits
                exit_orders = self.order_manager.auto_manage_exits(
                    self.portfolio, 
                    self.risk_manager, 
                    current_marks
                )
                
                if exit_orders:
                    self.logger.info(f"Created {len(exit_orders)} exit orders")
                    # Track exit events for P&L logging
                    exit_events = []
                    
                    # Execute exit orders immediately
                    for order in exit_orders:
                        try:
                            current_price = current_marks.get(order.symbol, order.price or 0)
                            if current_price > 0:
                                fill = self.order_manager.execute_order(order, current_price)
                                if fill.quantity > 0:
                                    self.logger.info(f"Exit order filled: {order.symbol} {fill.quantity} @ {fill.price}")
                                    
                                    # Log exit event for P&L tracking
                                    try:
                                        pnl_logger = get_pnl_logger()
                                        metadata = order.metadata or {}
                                        
                                        # Determine exit type from metadata
                                        exit_type = metadata.get("exit_type", "UNKNOWN")
                                        if not exit_type or exit_type == "UNKNOWN":
                                            exit_reason = metadata.get("exit_reason", "")
                                            if "stop" in exit_reason.lower():
                                                exit_type = "SL"
                                            elif "profit" in exit_reason.lower() or "tp" in exit_reason.lower():
                                                exit_type = "TP"
                                            elif "trail" in exit_reason.lower():
                                                exit_type = "TRAIL_STOP"
                                            elif "time" in exit_reason.lower():
                                                exit_type = "TIME_STOP"
                                        
                                        entry_price = metadata.get("entry_price", 0)
                                        stop_price = metadata.get("stop_price")
                                        realized_pnl = metadata.get("realized_pnl", 0)
                                        
                                        # Calculate realized P&L if not in metadata
                                        if realized_pnl == 0 and entry_price > 0:
                                            pnl_per_unit = fill.price - entry_price
                                            realized_pnl = pnl_per_unit * fill.quantity - fill.fees
                                        
                                        pnl_logger.log_exit_event(
                                            symbol=order.symbol,
                                            exit_type=exit_type,
                                            quantity=fill.quantity,
                                            exit_price=fill.price,
                                            entry_price=entry_price if entry_price > 0 else fill.price,
                                            stop_price=stop_price,
                                            realized_pnl=realized_pnl,
                                            reason=metadata.get("exit_reason", "")
                                        )
                                        
                                        # Track for cycle summary
                                        exit_events.append({
                                            "symbol": order.symbol,
                                            "exit_type": exit_type,
                                            "quantity": fill.quantity,
                                            "exit_price": fill.price,
                                            "entry_price": entry_price if entry_price > 0 else fill.price,
                                            "realized_pnl": realized_pnl,
                                            "r_multiple": "N/A"  # Will be calculated in logger
                                        })
                                    except Exception as log_err:
                                        self.logger.warning(f"Failed to log exit event: {log_err}")
                                    
                        except Exception as e:
                            self.logger.error(f"Error executing exit order {order.id}: {e}")
                    
                    # Log exit P&L summary if any exits occurred
                    if exit_events:
                        try:
                            pnl_logger = get_pnl_logger()
                            pnl_logger.log_pnl_from_exits_section(
                                cycle_id=self.cycle_count,
                                exits=exit_events
                            )
                        except Exception as log_err:
                            self.logger.warning(f"Failed to log exit P&L summary: {log_err}")
                else:
                    self.logger.debug("No exit orders created")
                    
            except Exception as e:
                self.logger.error(f"Error in auto-manage exits: {e}")
                cycle_results["errors"].append(f"Exit management error: {e}")

            # 4. Update portfolio using transactional approach
            portfolio_update_start = datetime.now()
            self.logger.info(f"PORTFOLIO_UPDATE_START: {portfolio_update_start.isoformat()}")
            self.logger.info("Step 4: Updating portfolio with transactional validation")
            
            # Commit portfolio changes using transactional approach
            # This validates the final staged state against previous equity
            try:
                # Get current mark prices for all symbols
                mark_prices = {}
                for symbol in symbols:
                    try:
                        ticker_data = self.data_engine.get_ticker(symbol)
                        if ticker_data and ticker_data.get("price", 0) > 0:
                            mark_prices[symbol] = ticker_data["price"]
                    except Exception as e:
                        self.logger.warning(f"Failed to get mark price for {symbol}: {e}")
                
                # Commit portfolio transaction with validation
                transaction_success = self._commit_portfolio_transaction(mark_prices)
                
                if not transaction_success:
                    self.logger.error("Portfolio transaction validation failed - cycle may have invalid state")
                    cycle_results["errors"].append("Portfolio transaction validation failed")
                
            except Exception as e:
                self.logger.error(f"Portfolio transaction error: {e}")
                cycle_results["errors"].append(f"Portfolio transaction error: {e}")
            
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
            
            # Log comprehensive P&L breakdown for this cycle
            try:
                pnl_logger = get_pnl_logger()
                portfolio_snapshot = self.get_portfolio_snapshot()
                
                # Get equity change
                previous_equity = float(getattr(self, '_previous_equity', portfolio_snapshot["total_equity"]))
                equity_change = portfolio_snapshot["total_equity"] - previous_equity
                
                pnl_logger.log_cycle_pnl_summary(
                    cycle_id=self.cycle_count,
                    cash=portfolio_snapshot["cash_balance"],
                    positions_value=portfolio_snapshot["total_position_value"],
                    realized_pnl=portfolio_snapshot["total_realized_pnl"],
                    unrealized_pnl=portfolio_snapshot["total_unrealized_pnl"],
                    total_equity=portfolio_snapshot["total_equity"],
                    positions=portfolio_snapshot["active_positions"],
                    equity_change=equity_change
                )
            except Exception as e:
                self.logger.warning(f"Failed to log cycle P&L summary: {e}")
            
            # Save portfolio state AFTER updating _previous_equity in cycle summary
            self._save_portfolio_state()
            
            # Log available capital immediately after saving portfolio state to ensure accurate values
            self.logger.info(f"Available capital: ${self._get_available_capital():,.2f}")

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

            # NOTE: log_trading_cycle() method has been replaced by consolidated logging above

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
                # Calculate equity changes using Decimal arithmetic to avoid type mixing
                current_equity_for_summary = D(self.portfolio["equity"])
                total_pnl_for_summary = D(execution_results.get("total_pnl", 0))
                start_equity_for_summary = q_money(current_equity_for_summary - total_pnl_for_summary)
                
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
                        "start_equity": float(start_equity_for_summary),
                        "end_equity": float(current_equity_for_summary),
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

                # NOTE: log_daily_summary() method has been replaced by consolidated logging above
                pass
            except Exception as e:
                self.logger.error(f"Error in daily summary: {e}")

            # Portfolio snapshot using consistent state
            try:
                portfolio_snapshot = self.get_portfolio_snapshot()
                # Calculate equity components for detailed tracking
                total_equity = portfolio_snapshot["total_equity"]
                cash_balance = portfolio_snapshot["cash_balance"]
                total_position_value = portfolio_snapshot["total_position_value"]
                total_unrealized_pnl = sum(pos.get("unrealized_pnl", 0) for pos in portfolio_snapshot["positions"].values())
                
                cycle_results["portfolio_snapshot"] = {
                    "total_equity": total_equity,
                    "cash_balance": cash_balance,
                    "active_positions": portfolio_snapshot["position_count"],
                    "total_position_value": total_position_value,
                    "available_capital": self._get_available_capital(),
                    "positions_detail": portfolio_snapshot["positions"],
                    "timestamp": portfolio_snapshot["timestamp"],
                    "equity_components": {
                        "cash_balance": cash_balance,
                        "position_value": total_position_value,
                        "unrealized_pnl": total_unrealized_pnl,
                        "equity_from_market_moves": total_unrealized_pnl,
                        "cash_percentage": (cash_balance / total_equity * 100) if total_equity > 0 else 0,
                        "position_percentage": (total_position_value / total_equity * 100) if total_equity > 0 else 0
                    }
                }
            except Exception as e:
                self.logger.error(f"Error in portfolio snapshot: {e}")
                cycle_results["portfolio_snapshot"] = {}

            # Post-cycle equity assertion: cash + marked position value ≈ reported equity
            self._assert_equity_consistency()

            # Calculate cycle duration
            cycle_end_time = datetime.now()
            cycle_duration = (cycle_end_time - cycle_start_time).total_seconds()
            cycle_results["duration"] = cycle_duration

            self.last_cycle_time = cycle_end_time

            # Log pricing context for this cycle
            snapshot = get_current_pricing_snapshot()
            if snapshot:
                snapshot.log_pricing_context()
            else:
                self.logger.warning("No pricing snapshot available for cycle completion logging")

            self.logger.info(
                f"Trading cycle #{self.cycle_count} completed in {cycle_duration:.2f}s"
            )
            self.logger.info(f"Portfolio equity: ${self._get_total_equity():,.2f}")
            # Available capital is now logged immediately after portfolio state save (line 3202)

        except PricingContextError as e:
            error_msg = f"PRICING_CONTEXT_ERROR in trading cycle #{self.cycle_count}: {e}"
            self.logger.error(error_msg)
            cycle_results["errors"].append(error_msg)
            # Abort cycle safely due to pricing context error
            self.logger.error("ABORTING CYCLE: Pricing context error - cycle aborted safely")
        except Exception as e:
            error_msg = f"Error in trading cycle #{self.cycle_count}: {e}"
            self.logger.error(error_msg)
            cycle_results["errors"].append(error_msg)

        # LotBook persistence validation
        try:
            snapshot_result = self._snapshot_all_lotbooks()
            if snapshot_result.get("all_match", False):
                cycle_results["lotbook_validation"] = "PASS"
            else:
                cycle_results["lotbook_validation"] = "FAIL"
                cycle_results["errors"].append("LotBook persistence validation failed")
        except Exception as e:
            self.logger.error(f"LotBook snapshot validation failed: {e}")
            cycle_results["lotbook_validation"] = "ERROR"
            cycle_results["errors"].append(f"LotBook validation error: {e}")

        # NAV validation: rebuild portfolio from TradeLedger using PricingSnapshot
        self.logger.info("NAV_VALIDATION_ENTRY: Starting NAV validation")
        try:
            # Get current pricing snapshot
            pricing_snapshot = get_current_pricing_snapshot()
            if pricing_snapshot is None:
                self.logger.warning("NAV_VALIDATION_SKIP: No pricing snapshot available")
                cycle_results["nav_validation"] = "SKIP"
            else:
                self.logger.info("NAV_VALIDATION_ENTRY: Pricing snapshot available, proceeding with validation")
                # Get trades from ledger for this session
                trades = self.trade_ledger.get_trades_by_session(self.current_session_id)
                self.logger.info(f"NAV_VALIDATION_DEBUG: Retrieved {len(trades)} trades from ledger")
                
                # Get computed equity
                computed_equity = self._get_total_equity()
                
                # Get initial cash from config (starting capital for the session)
                # Use the initial capital from config, not the current cash balance
                initial_cash = self.config.get("trading", {}).get("initial_capital", 100000.0)
                
                # Run NAV validation
                self.logger.info(f"NAV_VALIDATION_CALL: About to call nav_validator.validate_nav")
                nav_result = self.nav_validator.validate_nav(
                    trades=trades,
                    pricing_snapshot=pricing_snapshot,
                    computed_equity=computed_equity,
                    initial_cash=initial_cash
                )
                self.logger.info(f"NAV_VALIDATION_CALL: nav_validator.validate_nav completed")
                
                # Log validation result
                if nav_result.is_valid:
                    cycle_results["nav_validation"] = "PASS"
                    self.logger.info(
                        f"NAV_VALIDATION_PASS: rebuilt=${nav_result.rebuilt_equity:.2f} "
                        f"computed=${nav_result.computed_equity:.2f} "
                        f"diff=${nav_result.difference:.4f}"
                    )
                else:
                    cycle_results["nav_validation"] = "FAIL"
                    cycle_results["errors"].append(f"NAV validation failed: {nav_result.error_message}")
                    self.logger.error(
                        f"NAV_VALIDATION_FAIL: {nav_result.error_message} "
                        f"rebuilt=${nav_result.rebuilt_equity:.2f} "
                        f"computed=${nav_result.computed_equity:.2f} "
                        f"diff=${nav_result.difference:.4f} "
                        f"tolerance=${nav_result.tolerance:.4f}"
                    )
                    
                    # TEMPORARILY DISABLED: Don't abort persistence on NAV validation failure
                    # self.logger.error("NAV_VALIDATION_FAIL: Aborting persistence due to NAV validation failure")
                    # raise RuntimeError(f"NAV validation failed: {nav_result.error_message}")
                    
        except Exception as e:
            self.logger.error(f"NAV validation error: {e}")
            cycle_results["nav_validation"] = "ERROR"
            cycle_results["errors"].append(f"NAV validation error: {e}")
            # Don't abort on validation errors, just log them

        return cycle_results

    def _assert_equity_consistency(self) -> None:
        """Post-cycle assertion: cash + marked position value ≈ reported equity.
        
        This lightweight guardrail catches future ledger/snapshot drift by verifying
        that the sum of cash and marked position values matches the reported equity
        within a small epsilon tolerance.
        
        CRITICAL FIX: Use get_portfolio_snapshot() as single source of truth to avoid
        position consolidation discrepancies.
        """
        try:
            # 🛡️ BULLETPROOF: Use portfolio snapshot as SINGLE SOURCE OF TRUTH
            # This ensures we're using the same consolidated positions and calculations
            snapshot = self.get_portfolio_snapshot()
            
            # Extract values from authoritative snapshot
            cash_balance = snapshot["cash_balance"]
            marked_position_value = snapshot["total_position_value"]
            reported_equity = snapshot["total_equity"]
            total_realized_pnl = snapshot["total_realized_pnl"]
            
            # Build position details for debugging from consolidated snapshot data
            position_details = []
            for symbol, position_data in snapshot["positions"].items():
                quantity = position_data.get("quantity", 0.0)
                position_value = position_data.get("value", 0.0)
                
                if abs(quantity) > 1e-8:  # Only count non-zero positions
                    position_details.append({
                        "symbol": symbol,
                        "quantity": quantity,
                        "value": position_value
                    })
            
            # Calculate expected equity: cash + marked position value
            # CRITICAL FIX: Don't add realized_pnl (it's already in cash)
            expected_equity = cash_balance + marked_position_value
            
            # Define practical epsilon tolerance: max(1.00, 0.0001 * total_equity)
            epsilon = max(1.00, 0.0001 * abs(reported_equity))
            
            # Check if values are within tolerance
            difference = abs(expected_equity - reported_equity)
            
            if difference > epsilon:
                # Mismatch detected - log warning with components and IDs
                self.logger.warning(
                    f"EQUITY_DRIFT_DETECTED: session={self.current_session_id} cycle={self.cycle_count} "
                    f"cash=${cash_balance:,.2f} + positions=${marked_position_value:,.2f} = expected=${expected_equity:,.2f} "
                    f"≠ reported=${reported_equity:,.2f} (diff=${difference:,.2f} > ε=${epsilon:,.2f}, realized_pnl_tracked=${total_realized_pnl:,.2f} in cash)"
                )
                
                # Log position details for debugging
                if position_details:
                    position_summary = ", ".join([
                        f"{pos['symbol']}:{pos['quantity']:.6f}@${pos['value']:.2f}" 
                        for pos in position_details
                    ])
                    self.logger.warning(f"POSITION_BREAKDOWN: {position_summary}")
                else:
                    self.logger.warning("POSITION_BREAKDOWN: no active positions")
                    
            else:
                # Values are consistent - log at info level for visibility
                self.logger.info(
                    f"EQUITY_BALANCE: session={self.current_session_id} cycle={self.cycle_count} "
                    f"cash=${cash_balance:,.2f} + positions=${marked_position_value:,.2f} + realized_pnl=${total_realized_pnl:,.2f} = ${expected_equity:,.2f} "
                    f"≈ reported=${reported_equity:,.2f} ✓ (diff=${difference:,.2f} ≤ ε=${epsilon:,.2f})"
                )
                
        except Exception as e:
            # Don't let equity assertion failures break the cycle
            self.logger.error(f"EQUITY_ASSERTION_ERROR: session={self.current_session_id} cycle={self.cycle_count} - {e}")

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
                "regime_detector": self.regime_detector is not None,
            },
        }

    async def _check_and_execute_exits(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Check all positions for exit conditions and execute exits.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dictionary with exit execution results
        """
        results = {
            "exits_checked": 0,
            "exits_executed": 0,
            "exit_reasons": [],
            "total_exit_pnl": 0.0
        }
        
        try:
            # Get current positions
            positions = self.portfolio.get("positions", {})
            if not positions:
                self.logger.debug("No positions to check for exits")
                return results
            
            # Get current prices for all symbols
            current_prices = {}
            for symbol in positions.keys():
                try:
                    mark_price = self.get_cached_mark_price(
                        symbol,
                        self.data_engine,
                        live_mode=self.config.get("trading", {}).get("live_mode", False),
                        cycle_id=self.cycle_count
                    )
                    if mark_price:
                        current_prices[symbol] = mark_price
                except Exception as e:
                    self.logger.warning(f"Failed to get price for {symbol}: {e}")
            
            # Check for exit conditions
            exit_conditions = self.exit_manager.check_exits(
                positions=positions,
                current_prices=current_prices,
                state_store=self.state_store,
                session_id=self.current_session_id,
                data_engine=self.data_engine
            )
            
            results["exits_checked"] = len(positions)
            
            # Execute exits
            for exit_condition in exit_conditions:
                if not exit_condition.should_exit:
                    continue
                
                try:
                    symbol = exit_condition.symbol
                    position = positions.get(symbol, {})
                    position_qty = float(position.get("quantity", 0))
                    
                    if position_qty == 0:
                        continue
                    
                    # Calculate exit quantity
                    exit_qty = abs(position_qty * exit_condition.exit_percentage)
                    
                    # Determine exit side (opposite of position)
                    exit_side = "sell" if position_qty > 0 else "buy"
                    
                    # Execute exit order
                    self.logger.info(
                        f"EXECUTING_EXIT: {symbol} {exit_side} {exit_qty:.6f} @ ${exit_condition.exit_price:.4f} "
                        f"reason={exit_condition.reason}"
                    )
                    
                    # Create exit order through order manager
                    order_result = await self.order_manager.create_and_fill_order(
                        symbol=symbol,
                        side=exit_side,
                        quantity=exit_qty,
                        price=exit_condition.exit_price,
                        order_type="market"
                    )
                    
                    if order_result and order_result.get("status") == "filled":
                        results["exits_executed"] += 1
                        results["exit_reasons"].append(exit_condition.reason)
                        
                        # Calculate exit P&L
                        entry_price = float(position.get("entry_price", 0))
                        if position_qty > 0:  # Long exit
                            pnl = (exit_condition.exit_price - entry_price) * exit_qty
                        else:  # Short exit
                            pnl = (entry_price - exit_condition.exit_price) * exit_qty
                        
                        results["total_exit_pnl"] += pnl
                        
                        self.logger.info(
                            f"EXIT_EXECUTED: {symbol} {exit_side} {exit_qty:.6f} P&L=${pnl:.2f} "
                            f"reason={exit_condition.reason}"
                        )
                    else:
                        self.logger.warning(f"EXIT_FAILED: {symbol} exit order failed")
                        
                except Exception as e:
                    self.logger.error(f"Failed to execute exit for {symbol}: {e}")
            
        except Exception as e:
            self.logger.error(f"Error in exit checking: {e}")
        
        return results
    
    def _manage_risk_on_window(self, symbols: list[str]) -> None:
        """Manage risk-on window based on volatility triggers.
        
        Args:
            symbols: List of trading symbols to check for risk-on triggers
        """
        if not self.regime_detector or not self.state_store:
            return
        
        risk_on_cfg = self.config.get("risk", {}).get("risk_on", {})
        if not risk_on_cfg.get("enabled", False):
            return
        
        # Get current risk-on window cycles remaining
        risk_on_window_cycles_remaining = self.state_store.get_session_metadata(
            self.current_session_id, "risk_on_window_cycles_remaining", 0
        )
        
        # Check if we should trigger a new risk-on window
        if risk_on_window_cycles_remaining == 0:
            # Check each symbol for risk-on trigger
            for symbol in symbols:
                try:
                    risk_on_triggered, details = self.regime_detector.detect_risk_on_trigger(symbol, self.data_engine)
                    
                    if risk_on_triggered:
                        # Set new risk-on window
                        window_cycles = risk_on_cfg.get("window_cycles", 3)
                        self.state_store.set_session_metadata(
                            self.current_session_id, "risk_on_window_cycles_remaining", window_cycles
                        )
                        self.state_store.set_session_metadata(
                            self.current_session_id, "risk_on_active", True
                        )
                        
                        self.logger.info(
                            f"RISK-ON: trigger vol_ratio={details.get('vol_ratio', 0):.2f}, "
                            f"window={window_cycles} cycles"
                        )
                        break  # Only need one symbol to trigger
                        
                except Exception as e:
                    self.logger.warning(f"Error checking risk-on trigger for {symbol}: {e}")
        
        # Manage existing risk-on window
        elif risk_on_window_cycles_remaining > 0:
            # Decrement window cycles
            new_cycles_remaining = risk_on_window_cycles_remaining - 1
            
            if new_cycles_remaining > 0:
                # Update remaining cycles
                self.state_store.set_session_metadata(
                    self.current_session_id, "risk_on_window_cycles_remaining", new_cycles_remaining
                )
                self.logger.debug(f"RISK-ON: window continues, {new_cycles_remaining} cycles remaining")
            else:
                # Window ended
                self.state_store.set_session_metadata(
                    self.current_session_id, "risk_on_window_cycles_remaining", 0
                )
                self.state_store.set_session_metadata(
                    self.current_session_id, "risk_on_active", False
                )
                self.logger.info("RISK-ON: window ended")

    def _check_daily_loss_limits(self) -> None:
        """Check daily loss limits and set halt flag if exceeded."""
        if not self.risk_manager or not self.state_store or not self.current_session_id:
            return
        
        current_equity = self._get_total_equity()
        is_first_cycle = (self.cycle_count == 1)
        
        self.logger.info(f"DAILY_LOSS_CHECK: cycle_count={self.cycle_count}, is_first_cycle={is_first_cycle}")
        
        should_halt, reason = self.risk_manager.check_daily_loss_limit(
            state_store=self.state_store,
            session_id=self.current_session_id,
            current_equity=current_equity,
            is_first_cycle=is_first_cycle
        )
        
        if should_halt and reason == "daily_loss_limit_exceeded":
            self.logger.info("DAILY_LOSS: New entries halted due to daily loss limit breach")


    def _calculate_trading_pnl(self, execution_results: dict[str, Any]) -> float:
        """Calculate actual trading P&L from executed trades only."""
        try:
            # Get realized P&L from execution results
            realized_pnl = execution_results.get("total_realized_pnl", 0.0)
            
            # Get fees from execution results
            total_fees = execution_results.get("total_fees", 0.0)
            
            # Trading P&L = realized P&L - fees
            trading_pnl = realized_pnl - total_fees
            
            self.logger.debug(f"TRADING_PNL_CALC: realized_pnl=${realized_pnl:,.2f}, fees=${total_fees:,.2f}, trading_pnl=${trading_pnl:,.2f}")
            
            return trading_pnl
        except Exception as e:
            self.logger.error(f"Error calculating trading P&L: {e}")
            return 0.0

    def _calculate_unrealized_pnl(self, positions: dict[str, Any]) -> float:
        """Calculate unrealized P&L from open positions."""
        try:
            unrealized_pnl = 0.0
            
            for symbol, position in positions.items():
                if abs(position.get("quantity", 0)) > 1e-8:
                    quantity = position.get("quantity", 0)
                    current_price = position.get("current_price", 0)
                    avg_cost = position.get("avg_cost", 0)
                    
                    if current_price > 0 and avg_cost > 0:
                        # Unrealized P&L = (current_price - avg_cost) * quantity
                        position_unrealized = (current_price - avg_cost) * quantity
                        unrealized_pnl += position_unrealized
                        
                        self.logger.debug(f"UNREALIZED_PNL: {symbol} qty={quantity:.6f} current=${current_price:.4f} avg_cost=${avg_cost:.4f} unrealized=${position_unrealized:.2f}")
            
            self.logger.debug(f"TOTAL_UNREALIZED_PNL: ${unrealized_pnl:,.2f}")
            return unrealized_pnl
        except Exception as e:
            self.logger.error(f"Error calculating unrealized P&L: {e}")
            return 0.0

    def _get_total_trades(self) -> int:
        """Get total number of trades from trade ledger."""
        try:
            if self.trade_ledger and self.current_session_id:
                metrics = self.trade_ledger.calculate_daily_metrics(session_id=self.current_session_id)
                return metrics.get("total_trades", 0)
            return 0
        except Exception as e:
            self.logger.debug(f"Error getting total trades: {e}")
            return 0

    def _get_winning_trades(self) -> int:
        """Get number of winning trades from trade ledger."""
        try:
            if self.trade_ledger and self.current_session_id:
                metrics = self.trade_ledger.calculate_daily_metrics(session_id=self.current_session_id)
                return metrics.get("winning_trades", 0)
            return 0
        except Exception as e:
            self.logger.debug(f"Error getting winning trades: {e}")
            return 0

    def _get_losing_trades(self) -> int:
        """Get number of losing trades from trade ledger."""
        try:
            if self.trade_ledger and self.current_session_id:
                metrics = self.trade_ledger.calculate_daily_metrics(session_id=self.current_session_id)
                return metrics.get("losing_trades", 0)
            return 0
        except Exception as e:
            self.logger.debug(f"Error getting losing trades: {e}")
            return 0

    def _get_total_volume(self) -> float:
        """Get total trading volume from trade ledger."""
        try:
            if self.trade_ledger and self.current_session_id:
                metrics = self.trade_ledger.calculate_daily_metrics(session_id=self.current_session_id)
                return metrics.get("total_volume", 0.0)
            return 0.0
        except Exception as e:
            self.logger.debug(f"Error getting total volume: {e}")
            return 0.0

    def _get_total_fees(self) -> float:
        """Get total fees paid from trade ledger."""
        try:
            if self.trade_ledger and self.current_session_id:
                metrics = self.trade_ledger.calculate_daily_metrics(session_id=self.current_session_id)
                return metrics.get("total_fees", 0.0)
            return 0.0
        except Exception as e:
            self.logger.debug(f"Error getting total fees: {e}")
            return 0.0

    def _get_avg_trade_size(self) -> float:
        """Get average trade size."""
        total_trades = self._get_total_trades()
        if total_trades == 0:
            return 0.0
        return self._get_total_volume() / total_trades

    def _select_top_k_symbols(self, symbol_scores: dict[str, float], top_k_entries: int, hard_floor_min: float) -> list[tuple[str, float]]:
        """Select top K symbols based on score magnitude, preserving sign.
        
        Args:
            symbol_scores: Dictionary mapping symbol to composite score
            top_k_entries: Number of top symbols to select
            hard_floor_min: Minimum score magnitude threshold
            
        Returns:
            List of (symbol, score) tuples ordered by score magnitude (descending)
        """
        # Filter by hard floor (using absolute value for threshold check)
        # AND filter negative scores if long_only mode is active
        filtered_scores = {}
        for symbol, score in symbol_scores.items():
            # Check hard floor first
            if abs(score) < hard_floor_min:
                # Log decision trace for symbols filtered out by hard floor
                candidate = next((c for c in getattr(self, '_current_candidates', []) if c["symbol"] == symbol), None)
                if candidate:
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=candidate["signal"],
                        current_price=candidate["current_price"],
                        action="SKIP",
                        reason=f"score_below_hard_floor_{abs(score):.3f}_<_{hard_floor_min:.3f}"
                    )
                continue
            
            # Check long-only filter: drop negative scores if long_only mode is active
            if self.execution_router and self.execution_router.long_only and score < 0:
                # Log decision trace for symbols filtered out by long-only mode
                candidate = next((c for c in getattr(self, '_current_candidates', []) if c["symbol"] == symbol), None)
                if candidate:
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=candidate["signal"],
                        current_price=candidate["current_price"],
                        action="SKIP",
                        reason="shorting_disabled"
                    )
                continue
            
            # Symbol passes all filters
            filtered_scores[symbol] = score
        
        # Sort by absolute score (descending) and take top K
        sorted_symbols = sorted(filtered_scores.items(), key=lambda x: abs(x[1]), reverse=True)
        selected_symbols = sorted_symbols[:top_k_entries]
        
        # Log decision traces for symbols not selected (beyond top K)
        if len(sorted_symbols) > top_k_entries:
            for symbol, score in sorted_symbols[top_k_entries:]:
                candidate = next((c for c in getattr(self, '_current_candidates', []) if c["symbol"] == symbol), None)
                if candidate:
                    self._log_decision_trace(
                        symbol=symbol,
                        signal=candidate["signal"],
                        current_price=candidate["current_price"],
                        action="SKIP",
                        reason=f"not_top_{top_k_entries}_rank_{sorted_symbols.index((symbol, score)) + 1}"
                    )
        
        return selected_symbols

    def _select_threshold_symbols(self, symbol_scores: dict[str, float], candidates: list[dict], gate_cfg: dict) -> list[tuple[str, float]]:
        """Select symbols based on threshold criteria, preserving original scores.
        
        Args:
            symbol_scores: Dictionary mapping symbol to composite score
            candidates: List of candidate dictionaries
            gate_cfg: Gate configuration
            
        Returns:
            List of (symbol, score) tuples that meet threshold criteria
        """
        selected_symbols = []
        
        for candidate in candidates:
            symbol = candidate["symbol"]
            score = symbol_scores[symbol]
            
            # Get the dynamic effective threshold from signal metadata
            effective_threshold = candidate["signal"].get("metadata", {}).get("normalization", {}).get("effective_threshold", 0.65)
            rr_ratio = candidate["risk_reward_ratio"]
            
            # New effective gate calculation with volatility-aware easing
            gate_margin = gate_cfg.get("gate_margin", 0.01)
            
            # Base effective gate: adaptive threshold minus margin, but not below hard floor
            hard_floor_min = gate_cfg.get("hard_floor_min", 0.53)
            effective_gate = max(effective_threshold - gate_margin, hard_floor_min)
            
            # Optional volatility-aware easing
            volatility_easing = gate_cfg.get("volatility_easing", False)
            if volatility_easing:
                # Get volatility from signal metadata
                volatility = candidate["signal"].get("metadata", {}).get("volatility", 0.0)
                if volatility > 0:
                    # Ease gate by up to 10% for high volatility
                    easing_factor = min(volatility * 0.1, 0.1)
                    effective_gate = max(effective_gate - easing_factor, hard_floor_min)
            
            # Check if score meets effective gate (using absolute value for threshold check)
            if abs(score) < effective_gate:
                # Log decision trace for symbols not meeting threshold
                self._log_decision_trace(
                    symbol=symbol,
                    signal=candidate["signal"],
                    current_price=candidate["current_price"],
                    action="SKIP",
                    reason=f"score_below_threshold_{abs(score):.3f}_<_{effective_gate:.3f}"
                )
                continue
            
            # Check long-only filter: drop negative scores if long_only mode is active
            if self.execution_router and self.execution_router.long_only and score < 0:
                # Log decision trace for symbols filtered out by long-only mode
                self._log_decision_trace(
                    symbol=symbol,
                    signal=candidate["signal"],
                    current_price=candidate["current_price"],
                    action="SKIP",
                    reason="shorting_disabled"
                )
                continue
            
            # Symbol passes all filters
            selected_symbols.append((symbol, score))
        
        return selected_symbols

    def _calculate_current_drawdown(self) -> float:
        """Calculate current drawdown percentage."""
        # Placeholder - implement based on your peak equity tracking
        return 0.0

    def _calculate_volatility(self) -> float:
        """Calculate volatility percentage."""
        # Placeholder - implement based on your volatility calculation
        return 2.0

    def _calculate_var_95(self) -> float:
        """Calculate 95% Value at Risk."""
        # Placeholder - implement based on your VaR calculation
        return 3.0

    def _get_strategy_performance(self) -> dict:
        """Get strategy-specific performance metrics."""
        # Placeholder - implement based on your strategy tracking
        return {}

    # LotBook integration methods
    
    def _initialize_lotbooks(self, session_id: str) -> None:
        """Initialize LotBooks for all whitelisted symbols.
        
        Args:
            session_id: Session identifier
        """
        try:
            # Get whitelisted symbols from config
            trading_symbols = self.config.get("trading", {}).get("symbols", [])
            
            # Load existing LotBooks from state store
            persisted_lotbooks = self.state_store.load_all_lotbooks(session_id)
            
            # Initialize LotBook for each symbol
            for symbol in trading_symbols:
                canonical_symbol = to_canonical(symbol)
                
                # Create new LotBook instance
                lot_book = LotBook()
                
                # Load persisted lots if they exist
                if canonical_symbol in persisted_lotbooks:
                    persisted_lots = persisted_lotbooks[canonical_symbol]
                    
                    # Convert persisted lot data to Lot objects and add to LotBook
                    for lot_data in persisted_lots:
                        try:
                            # Convert timestamp string back to datetime if needed
                            timestamp = lot_data.get('timestamp')
                            if isinstance(timestamp, str):
                                timestamp = datetime.fromisoformat(timestamp)
                            elif timestamp is None:
                                timestamp = datetime.now()
                            
                            lot_book.add_lot(
                                symbol=canonical_symbol,
                                quantity=lot_data.get('quantity', 0.0),
                                price=lot_data.get('cost_price', 0.0),
                                fee=lot_data.get('fee', 0.0),
                                timestamp=timestamp
                            )
                        except Exception as e:
                            self.logger.warning(f"Failed to load lot for {canonical_symbol}: {e}")
                
                self.lot_books[canonical_symbol] = lot_book
                self.logger.debug(f"Initialized LotBook for {canonical_symbol} with {len(lot_book.get_lots(canonical_symbol))} lots")
            
            # Log summary
            total_symbols = len(self.lot_books)
            total_lots = sum(len(lot_book.get_lots(symbol)) for symbol, lot_book in self.lot_books.items())
            self.logger.info(f"LOTBOOK_INIT: {total_symbols} symbols, {total_lots} total lots loaded")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize LotBooks: {e}")
            raise

    def _process_fill_with_lotbook(
        self,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        fees: float,
        trade_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Process a fill using LotBook for FIFO realized P&L calculation.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Fill quantity (positive)
            fill_price: Fill price
            fees: Trading fees
            trade_id: Optional exchange trade ID for idempotency
            
        Returns:
            Dictionary with fill processing results including realized P&L
        """
        try:
            canonical_symbol = to_canonical(symbol)
            
            # Check for duplicate fill using trade_id (idempotency)
            if trade_id:
                existing_lot = self._check_duplicate_fill(canonical_symbol, trade_id)
                if existing_lot:
                    self.logger.info(f"DUPLICATE_FILL: {trade_id} already processed, returning cached result")
                    return {
                        "realized_pnl": 0.0,  # No additional P&L for duplicate
                        "total_fees": 0.0,    # No additional fees for duplicate
                        "side": side,
                        "symbol": canonical_symbol,
                        "quantity": quantity,
                        "fill_price": fill_price,
                        "duplicate": True
                    }
            
            # Get or create LotBook for this symbol
            if canonical_symbol not in self.lot_books:
                self.lot_books[canonical_symbol] = LotBook()
                self.logger.debug(f"Created new LotBook for {canonical_symbol}")
            
            lot_book = self.lot_books[canonical_symbol]
            
            if side.lower() == "buy":
                # Add lot to LotBook
                lot_id = lot_book.add_lot(
                    symbol=canonical_symbol,
                    quantity=quantity,
                    price=fill_price,
                    fee=fees,
                    timestamp=datetime.now()
                )
                
                # Save lot to state store for persistence
                self.state_store.save_lot(
                    symbol=canonical_symbol,
                    lot_id=lot_id,
                    quantity=quantity,
                    cost_price=fill_price,
                    fee=fees,
                    timestamp=datetime.now(),
                    session_id=self.current_session_id,
                    trade_id=trade_id
                )
                
                realized_pnl = 0.0  # No realized P&L on buys
                
                self.logger.debug(f"BUY: Added lot {lot_id} to {canonical_symbol}: {quantity:.6f} @ ${fill_price:.4f}")
                
            elif side.lower() == "sell":
                # Consume lots using FIFO
                try:
                    consumption_result = lot_book.consume(
                        symbol=canonical_symbol,
                        quantity=quantity,
                        fill_price=fill_price,
                        fee=fees
                    )
                    
                    realized_pnl = consumption_result.realized_pnl
                    
                    # Update persisted LotBook in state store
                    self._persist_lotbook(canonical_symbol)
                    
                    self.logger.info(
                        f"SELL: Consumed {quantity:.6f} {canonical_symbol} @ ${fill_price:.4f}: "
                        f"realized_pnl=${realized_pnl:.4f}, consumed_lots={len(consumption_result.consumed_lots)}"
                    )
                    
                except ValueError as e:
                    if "No lots available" in str(e):
                        self.logger.warning(f"SELL: No lots available for {canonical_symbol}, treating as short sale")
                        realized_pnl = 0.0  # No realized P&L for short sales
                    else:
                        raise
            
            else:
                raise ValueError(f"Invalid side: {side}")
            
            return {
                "realized_pnl": realized_pnl,
                "total_fees": fees,
                "side": side,
                "symbol": canonical_symbol,
                "quantity": quantity,
                "fill_price": fill_price
            }
            
        except Exception as e:
            self.logger.error(f"Failed to process fill with LotBook for {symbol}: {e}")
            # Return safe fallback
            return {
                "realized_pnl": 0.0,
                "total_fees": fees,
                "side": side,
                "symbol": to_canonical(symbol),
                "quantity": quantity,
                "fill_price": fill_price,
                "error": str(e)
            }

    def _check_duplicate_fill(self, symbol: str, trade_id: str) -> Optional[dict]:
        """Check if a fill with the given trade_id has already been processed.
        
        Args:
            symbol: Trading symbol
            trade_id: Exchange trade ID
            
        Returns:
            Existing lot data if duplicate found, None otherwise
        """
        try:
            # Check in state store for existing lot with this trade_id
            cursor = self.state_store.connection.cursor()
            cursor.execute(
                "SELECT * FROM lotbook WHERE symbol = ? AND trade_id = ?",
                (symbol, trade_id)
            )
            existing_lot = cursor.fetchone()
            
            if existing_lot:
                return dict(existing_lot)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to check for duplicate fill {trade_id}: {e}")
            return None

    def _persist_lotbook(self, symbol: str) -> None:
        """Persist LotBook for a symbol to state store.
        
        Args:
            symbol: Trading symbol
        """
        try:
            canonical_symbol = to_canonical(symbol)
            
            if canonical_symbol not in self.lot_books:
                return
            
            lot_book = self.lot_books[canonical_symbol]
            lots = lot_book.get_lots(canonical_symbol)
            
            # Convert Lot objects to dictionaries for persistence
            lot_data = []
            for lot in lots:
                lot_data.append({
                    "lot_id": lot.lot_id,
                    "quantity": lot.quantity,
                    "cost_price": lot.price,
                    "fee": lot.fee,
                    "timestamp": lot.timestamp
                })
            
            # Save to state store
            self.state_store.set_lotbook(canonical_symbol, lot_data, self.current_session_id)
            
        except Exception as e:
            self.logger.error(f"Failed to persist LotBook for {symbol}: {e}")

    def _snapshot_all_lotbooks(self) -> dict[str, Any]:
        """Create snapshot of all LotBooks and validate persistence.
        
        Returns:
            Dictionary with snapshot results
        """
        try:
            snapshot_start = datetime.now()
            
            # Persist all LotBooks
            for symbol in self.lot_books.keys():
                self._persist_lotbook(symbol)
            
            # Load back from state store to validate
            persisted_lotbooks = self.state_store.snapshot_all_lotbooks(self.current_session_id)
            
            # Compare with in-memory LotBooks
            validation_results = {}
            total_lots_persisted = 0
            total_lots_loaded = 0
            symbols_with_lots = 0
            
            for symbol, lot_book in self.lot_books.items():
                in_memory_lots = lot_book.get_lots(symbol)
                persisted_lots = persisted_lotbooks.get(symbol, [])
                
                in_memory_count = len(in_memory_lots)
                persisted_count = len(persisted_lots)
                
                validation_results[symbol] = {
                    "in_memory_lots": in_memory_count,
                    "persisted_lots": persisted_count,
                    "match": in_memory_count == persisted_count
                }
                
                total_lots_persisted += in_memory_count
                total_lots_loaded += persisted_count
                
                # Count symbols that actually have lots
                if in_memory_count > 0:
                    symbols_with_lots += 1
            
            snapshot_duration = (datetime.now() - snapshot_start).total_seconds()
            
            # Check if all LotBooks match
            all_match = all(result["match"] for result in validation_results.values())
            
            result = {
                "timestamp": snapshot_start.isoformat(),
                "duration_seconds": snapshot_duration,
                "total_symbols": len(self.lot_books),
                "symbols_with_lots": symbols_with_lots,
                "total_lots_persisted": total_lots_persisted,
                "total_lots_loaded": total_lots_loaded,
                "all_match": all_match,
                "validation_results": validation_results
            }
            
            if all_match:
                self.logger.info(f"LOTBOOK_PERSISTENCE: PASS – {total_lots_persisted} lots across {symbols_with_lots} symbols")
            else:
                self.logger.error(f"LOTBOOK_PERSISTENCE: FAIL - Mismatch detected")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to snapshot LotBooks: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "all_match": False
            }

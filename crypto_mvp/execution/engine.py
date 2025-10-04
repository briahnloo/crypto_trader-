"""
Atomic execution engine for crypto trading bot.

This module provides atomic trade execution with hardened pricing,
risk-based position sizing, SL/TP calculation, and edge after costs guard.
"""

from datetime import datetime
from typing import List, Optional, Callable, Dict, Any
import logging
import time

from portfolio.ledger import Ledger, Fill, apply_fill
from portfolio.snapshot import PortfolioSnapshot
from market.prices import get_executable_price, get_atr, get_atr_1m_60, clear_atr_cache
from risk.sltp import sl_tp_defaults, get_sl_tp_summary
from risk.position_sizing import size_for_risk, get_position_size_summary

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Atomic execution engine for trades."""
    
    def __init__(self, get_mark_price_callback: Callable[[str], Optional[float]], 
                 get_ticker_callback: Optional[Callable[[str], Dict[str, Any]]] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        Initialize execution engine.
        
        Args:
            get_mark_price_callback: Function to get current mark price for validation
            get_ticker_callback: Function to get ticker data with bid/ask prices
            config: Configuration dictionary for execution settings
        """
        self.get_mark_price_callback = get_mark_price_callback
        self.get_ticker_callback = get_ticker_callback
        self.config = config or {}
        self.committed_fills: List[Fill] = []
        
        # Initialize edge after costs guard
        self.edge_guard = None
        if self.config.get("execution", {}).get("require_edge_after_costs", False):
            try:
                from .edge_guard import EdgeAfterCostsGuard
                guard_config = {
                    **self.config.get("execution", {}),
                    "maker_fee_bps": self.config.get("execution", {}).get("maker_fee_bps", 10),
                    "taker_fee_bps": self.config.get("execution", {}).get("taker_fee_bps", 20)
                }
                self.edge_guard = EdgeAfterCostsGuard(guard_config)
                logger.info("Edge after costs guard initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize edge guard: {e}")
                self.edge_guard = None
        
        # Initialize post-only order router
        self.post_only_router = None
        if self.config.get("execution", {}).get("post_only", False):
            try:
                from .post_only_router import PostOnlyOrderRouter
                router_config = self.config.get("execution", {})
                self.post_only_router = PostOnlyOrderRouter(router_config)
                logger.info("Post-only order router initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize post-only router: {e}")
                self.post_only_router = None
        
        # Initialize OCO manager
        self.oco_manager = None
        if self.config.get("risk", {}).get("oco_enabled", False):
            try:
                from .oco_manager import OCOManager
                oco_config = self.config.get("risk", {})
                self.oco_manager = OCOManager(oco_config)
                
                # Set OCO callbacks
                self.oco_manager.set_callbacks(
                    get_atr_callback=get_atr_1m_60,
                    create_order_callback=self._create_order_callback,
                    cancel_order_callback=self._cancel_order_callback,
                    get_mark_price_callback=self.get_mark_price_callback
                )
                logger.info("OCO manager initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize OCO manager: {e}")
                self.oco_manager = None
        
        # Initialize market data filter
        self.market_data_filter = None
        if self.config.get("market_data"):
            try:
                from .market_data_filter import MarketDataFilter
                self.market_data_filter = MarketDataFilter(self.config)
                logger.info("Market data filter initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize market data filter: {e}")
                self.market_data_filter = None
        
        # Initialize risk sizing calculator
        self.risk_sizing_calculator = None
        if self.config.get("risk", {}).get("risk_per_trade_pct"):
            try:
                from .risk_sizing_calculator import RiskSizingCalculator
                self.risk_sizing_calculator = RiskSizingCalculator(self.config)
                logger.info("Risk sizing calculator initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize risk sizing calculator: {e}")
                self.risk_sizing_calculator = None
        
        # Initialize symbol filter
        self.symbol_filter = None
        if self.config.get("universe", {}).get("whitelist"):
            try:
                from .symbol_filter import SymbolFilter
                self.symbol_filter = SymbolFilter(self.config)
                logger.info("Symbol filter initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize symbol filter: {e}")
                self.symbol_filter = None
        
        # Initialize trade metrics collector
        self.trade_metrics = None
        if self.config.get("logging", {}).get("enhanced_execution_logs", False):
            try:
                from .trade_metrics import TradeMetrics
                self.trade_metrics = TradeMetrics(self.config)
                logger.info("Trade metrics collector initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize trade metrics collector: {e}")
                self.trade_metrics = None
        
        # Initialize decision engine guard
        self.decision_engine_guard = None
        if self.config.get("market_data", {}).get("require_l2_mid", False):
            try:
                from .decision_engine_guard import DecisionEngineGuard
                self.decision_engine_guard = DecisionEngineGuard(self.config)
                logger.info("Decision engine guard initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize decision engine guard: {e}")
                self.decision_engine_guard = None
        
        # Initialize regime detector
        self.regime_detector = None
        if self.config.get("signals", {}).get("regime"):
            try:
                from .regime_detector import RegimeDetector
                self.regime_detector = RegimeDetector(self.config)
                
                # Set regime detector callbacks
                from ..market.prices import get_ema, get_adx
                self.regime_detector.set_callbacks(
                    get_ema_callback=get_ema,
                    get_adx_callback=get_adx
                )
                logger.info("Regime detector initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize regime detector: {e}")
                self.regime_detector = None
        
        # Initialize portfolio sweeper
        self.portfolio_sweeper = None
        if self.config.get("risk", {}).get("oco_enabled", False):
            try:
                from .portfolio_sweeper import PortfolioSweeper
                self.portfolio_sweeper = PortfolioSweeper(self.config)
                
                # Set portfolio sweeper callbacks
                self.portfolio_sweeper.set_callbacks(
                    get_positions_callback=self._get_positions_callback,
                    get_oco_orders_callback=self._get_oco_orders_callback,
                    get_atr_callback=self._get_atr_callback,
                    get_mark_price_callback=self._get_mark_price_callback,
                    create_oco_callback=self._create_oco_callback,
                    update_oco_callback=self._update_oco_callback,
                    flatten_position_callback=self._flatten_position_callback
                )
                logger.info("Portfolio sweeper initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize portfolio sweeper: {e}")
                self.portfolio_sweeper = None
        
        # Initialize stop-loss cooldown tracker
        self.sl_cooldown_tracker = None
        if self.config.get("risk", {}).get("cooldown_after_sl_seconds"):
            try:
                from .sl_cooldown_tracker import StopLossCooldownTracker
                self.sl_cooldown_tracker = StopLossCooldownTracker(self.config)
                logger.info("Stop-loss cooldown tracker initialized")
            except ImportError as e:
                logger.warning(f"Failed to initialize stop-loss cooldown tracker: {e}")
                self.sl_cooldown_tracker = None
    
    def reset_cycle(self):
        """Reset committed fills for new cycle and clear ATR cache."""
        self.committed_fills = []
        clear_atr_cache()
    
    def _create_order_callback(self, symbol: str, side: str, quantity: float, price: float, order_type: str) -> Optional[str]:
        """Callback for creating orders."""
        # This would integrate with the actual order management system
        # For now, return a mock order ID
        import uuid
        return f"order_{uuid.uuid4().hex[:8]}"
    
    def _cancel_order_callback(self, order_id: str) -> bool:
        """Callback for cancelling orders."""
        # This would integrate with the actual order management system
        # For now, return True (successful cancellation)
        return True
    
    def _check_fill_callback(self, order_id: str) -> bool:
        """Callback for checking if order is filled."""
        # This would integrate with the actual order management system
        # For now, simulate random fills (30% chance)
        import random
        return random.random() < 0.3
    
    def _get_positions_callback(self) -> List[Dict[str, Any]]:
        """Get current positions (callback for portfolio sweeper)."""
        if not self.get_portfolio_callback:
            return []
        
        try:
            portfolio = self.get_portfolio_callback()
            positions = []
            
            for symbol, position in portfolio.get("positions", {}).items():
                if position.get("quantity", 0) != 0:
                    positions.append({
                        "symbol": symbol,
                        "quantity": position.get("quantity", 0),
                        "avg_cost": position.get("avg_cost", 0),
                        "value": position.get("value", 0),
                        "pnl": position.get("pnl", 0)
                    })
            
            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def _get_oco_orders_callback(self) -> Dict[str, Any]:
        """Get active OCO orders (callback for portfolio sweeper)."""
        if not self.oco_manager:
            return {}
        
        try:
            return self.oco_manager.active_oco_orders
        except Exception as e:
            logger.error(f"Failed to get OCO orders: {e}")
            return {}
    
    def _get_atr_callback(self, symbol: str) -> Optional[float]:
        """Get ATR for symbol (callback for portfolio sweeper)."""
        try:
            from ..market.prices import get_atr_1m_60
            return get_atr_1m_60(symbol)
        except Exception as e:
            logger.error(f"Failed to get ATR for {symbol}: {e}")
            return None
    
    def _get_mark_price_callback(self, symbol: str) -> Optional[float]:
        """Get mark price for symbol (callback for portfolio sweeper)."""
        try:
            from ..market.prices import get_mark_price
            return get_mark_price(symbol)
        except Exception as e:
            logger.error(f"Failed to get mark price for {symbol}: {e}")
            return None
    
    def _create_oco_callback(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        atr: float
    ) -> Optional[str]:
        """Create OCO order (callback for portfolio sweeper)."""
        if not self.oco_manager:
            return None
        
        try:
            # Create a mock fill ID for the OCO order
            fill_id = f"sweeper_oco_{symbol}_{int(datetime.now().timestamp())}"
            
            # Create OCO order
            oco_order = self.oco_manager.create_oco_order(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                stop_loss=sl_price,
                take_profit=tp_price,
                atr=atr,
                strategy="portfolio_sweeper",
                fill_id=fill_id
            )
            
            if oco_order:
                return fill_id
            return None
        except Exception as e:
            logger.error(f"Failed to create OCO order for {symbol}: {e}")
            return None
    
    def _update_oco_callback(self, oco_id: str, new_tp_price: float, new_sl_price: float) -> bool:
        """Update OCO order (callback for portfolio sweeper)."""
        if not self.oco_manager:
            return False
        
        try:
            # Find the OCO order
            oco_order = self.oco_manager.active_oco_orders.get(oco_id)
            if not oco_order:
                return False
            
            # Update the OCO order prices
            oco_order.take_profit = new_tp_price
            oco_order.stop_loss = new_sl_price
            oco_order.last_updated = datetime.now()
            
            # In a real system, this would update the actual orders on the exchange
            # For now, we just update the local representation
            
            return True
        except Exception as e:
            logger.error(f"Failed to update OCO order {oco_id}: {e}")
            return False
    
    def _flatten_position_callback(self, symbol: str, side: str, quantity: float) -> bool:
        """Flatten position (callback for portfolio sweeper)."""
        try:
            # Create a market order to flatten the position
            order_id = self.create_order_callback(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=0.0,  # Market order
                order_type="market"
            )
            
            if order_id:
                logger.info(f"Flattening position: {symbol} {side} {quantity}")
                
                # Record stop-loss event for cooldown tracking
                if self.sl_cooldown_tracker:
                    self.sl_cooldown_tracker.record_stop_loss(symbol)
                
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to flatten position {symbol}: {e}")
            return False
    
    def record_stop_loss_event(self, symbol: str) -> None:
        """Record a stop-loss event for cooldown tracking."""
        if self.sl_cooldown_tracker:
            self.sl_cooldown_tracker.record_stop_loss(symbol)
    
    def executable_price(self, symbol: str, max_attempts: int = 2) -> Optional[float]:
        """
        Fetch best executable price with retry logic.
        
        Args:
            symbol: Symbol to get price for
            max_attempts: Maximum number of attempts
            
        Returns:
            Executable price or None if not available
        """
        # Use the hardened pricing function
        return get_executable_price(symbol)
    
    async def execute_trade(
        self,
        ledger: Ledger,
        symbol: str,
        side: str,
        strategy: str = "unknown",
        fees: float = 0.0,
        meta: Optional[Dict[str, Any]] = None,
        snapshot: Optional[PortfolioSnapshot] = None
    ) -> tuple[Ledger, bool]:
        """
        Atomically execute a trade with risk-based position sizing.
        
        Args:
            ledger: Current ledger state
            symbol: Symbol to trade
            side: "BUY" or "SELL"
            strategy: Strategy name
            fees: Trading fees
            meta: Additional metadata
            snapshot: Current portfolio snapshot for equity calculation
            
        Returns:
            Tuple of (updated_ledger, success)
        """
        if meta is None:
            meta = {}
        
        # Step 1: Log PLANNED trade
        logger.info(f"PLANNED: {symbol} {side} @ market price, strategy={strategy}")
        
        # Step 1.1: Check symbol whitelist
        if self.symbol_filter:
            try:
                should_skip, reason, details = self.symbol_filter.should_skip_trade(
                    symbol=symbol,
                    side=side,
                    strategy=strategy
                )
                
                if should_skip:
                    logger.warning(f"REJECTED: {symbol} {side} (reason=symbol_filter_{reason})")
                    return ledger, False
                    
            except Exception as e:
                logger.warning(f"Symbol filter check failed for {symbol}: {e}")
                # Continue execution if symbol filter fails
        
        # Step 1.2: Check stop-loss cooldown
        if self.sl_cooldown_tracker:
            try:
                should_skip, reason, details = self.sl_cooldown_tracker.should_skip_trade(symbol)
                
                if should_skip:
                    logger.warning(f"REJECTED: {symbol} {side} (reason=sl_cooldown_{reason})")
                    return ledger, False
                    
            except Exception as e:
                logger.warning(f"Stop-loss cooldown check failed for {symbol}: {e}")
                # Continue execution if cooldown check fails
        
        # Step 1.5: Check edge after costs guard
        if self.edge_guard and self.get_ticker_callback:
            try:
                ticker_data = self.get_ticker_callback(symbol)
                if ticker_data:
                    should_skip, reason, details = self.edge_guard.should_skip_trade(
                        symbol, ticker_data, meta
                    )
                    if should_skip:
                        logger.info(f"REJECTED: {symbol} {side} (reason=edge_guard_{reason})")
                        if details:
                            logger.debug(f"Edge guard details: {details}")
                        return ledger, False
            except Exception as e:
                logger.warning(f"Edge guard check failed for {symbol}: {e}")
        
        # Step 1.6: Check market data filter (spread and freshness)
        if self.market_data_filter and self.get_ticker_callback:
            try:
                ticker_data = self.get_ticker_callback(symbol)
                should_skip, reason, details = self.market_data_filter.should_skip_trade(
                    symbol, ticker_data
                )
                if should_skip:
                    logger.info(f"REJECTED: {symbol} {side} (reason=market_data_{reason})")
                    if details:
                        logger.debug(f"Market data filter details: {details}")
                    return ledger, False
            except Exception as e:
                logger.warning(f"Market data filter check failed for {symbol}: {e}")
        
        # Step 1.7: Check decision engine guard (L2 mid validation)
        if self.decision_engine_guard and self.get_ticker_callback:
            try:
                ticker_data = self.get_ticker_callback(symbol)
                is_valid, reason, details = self.decision_engine_guard.validate_decision_data(
                    symbol=symbol,
                    ticker_data=ticker_data,
                    execution_venue="binance"  # Default execution venue
                )
                if not is_valid:
                    stale_tick = details.get("stale_tick", False)
                    logger.info(f"REJECTED: {symbol} {side} (reason=decision_guard_{reason}, stale_tick={stale_tick})")
                    if details:
                        logger.debug(f"Decision engine guard details: {details}")
                    return ledger, False
            except Exception as e:
                logger.warning(f"Decision engine guard check failed for {symbol}: {e}")
                # Continue with trade if edge guard fails
        
        # Step 1.8: Use post-only order router if enabled
        if self.post_only_router and self.get_ticker_callback:
            try:
                # Calculate position size first (needed for order routing)
                atr = get_atr(symbol)
                if snapshot:
                    equity = snapshot.equity
                else:
                    equity = ledger.cash + sum(pos.qty * get_executable_price(symbol) for pos in ledger.positions.values())
                
                # Get SL for position sizing
                try:
                    sl, tp, sl_tp_meta = sl_tp_defaults(
                        symbol=symbol,
                        entry=get_executable_price(symbol),
                        side=side,
                        atr=atr
                    )
                except Exception as e:
                    logger.warning(f"REJECTED: {symbol} {side} (reason=sl_tp_error: {e})")
                    return ledger, False
                
                # Calculate position size using risk-based sizing if available
                if self.risk_sizing_calculator:
                    # Get current default size for comparison
                    current_default_size = size_for_risk(equity=equity, entry=get_executable_price(symbol), sl=sl)
                    
                    # Calculate risk-based size
                    qty, sizing_reason, sizing_details = self.risk_sizing_calculator.calculate_position_size(
                        symbol=symbol,
                        side=side,
                        entry_price=get_executable_price(symbol),
                        equity=equity,
                        current_default_size=current_default_size,
                        oco_manager=self.oco_manager
                    )
                    
                    if qty <= 0:
                        logger.warning(f"REJECTED: {symbol} {side} (reason=risk_sizing_{sizing_reason})")
                        return ledger, False
                else:
                    # Fallback to default sizing
                    qty = size_for_risk(equity=equity, entry=get_executable_price(symbol), sl=sl)
                    if qty <= 0:
                        logger.warning(f"REJECTED: {symbol} {side} (reason=size=0)")
                        return ledger, False
                
                # Route order through post-only router
                success, router_details = await self.post_only_router.route_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    get_ticker_callback=self.get_ticker_callback,
                    create_order_callback=self._create_order_callback,
                    cancel_order_callback=self._cancel_order_callback,
                    check_fill_callback=self._check_fill_callback
                )
                
                if success:
                    # Order was filled, create fill record
                    entry = get_executable_price(symbol)
                    fill_meta = {
                        **meta,
                        "post_only": True,
                        "maker_fill": router_details.get("maker_fill", False),
                        "wait_time_seconds": router_details.get("wait_time_seconds", 0.0),
                        "final_status": router_details.get("final_status", "unknown"),
                        "order_id": router_details.get("order_id", "unknown")
                    }
                    
                    fill = Fill(
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        price=entry,
                        fees=fees,
                        ts=datetime.now(),
                        sl=sl,
                        tp=tp,
                        strategy=strategy,
                        meta=fill_meta
                    )
                    
                    try:
                        updated_ledger = apply_fill(
                            ledger=ledger,
                            fill=fill,
                            get_mark_price=self.get_mark_price_callback
                        )
                        
                        # Log execution with post-only details
                        sl_tp_summary = get_sl_tp_summary(sl, tp, sl_tp_meta)
                        position_summary = get_position_size_summary(qty, entry, sl, tp, side, equity)
                        maker_fill = router_details.get("maker_fill", False)
                        wait_time = router_details.get("wait_time_seconds", 0.0)
                        
                        # Calculate enhanced trade metrics
                        enhanced_metrics = ""
                        if self.trade_metrics:
                            try:
                                trade_metrics = self.trade_metrics.calculate_trade_metrics(
                                    symbol=symbol,
                                    side=side,
                                    entry_price=entry,
                                    quantity=qty,
                                    fees=fees,
                                    strategy=strategy,
                                    ticker_data=self.get_ticker_callback(symbol) if self.get_ticker_callback else None,
                                    signal_data=meta,
                                    sl_price=sl,
                                    tp_price=tp,
                                    atr=atr,
                                    maker_fill=maker_fill,
                                    wait_time_seconds=wait_time
                                )
                                
                                enhanced_metrics = self.trade_metrics.get_trade_summary(trade_metrics)
                                self.trade_metrics.add_trade(trade_metrics)
                                
                            except Exception as e:
                                logger.warning(f"Failed to calculate trade metrics for {symbol}: {e}")
                        
                        logger.info(
                            f"EXECUTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} "
                            f"fees=${fees:.2f} strategy={strategy} maker_fill={maker_fill} "
                            f"wait_time={wait_time:.2f}s {sl_tp_summary} {position_summary} {enhanced_metrics}"
                        )
                        
                        self.committed_fills.append(fill)
                        
                        # Place OCO order after successful fill
                        if self.oco_manager:
                            try:
                                fill_id = f"fill_{symbol}_{side}_{int(time.time())}"
                                oco_success, oco_details = await self.oco_manager.place_oco_order(
                                    symbol=symbol,
                                    side=side,
                                    entry_price=entry,
                                    quantity=qty,
                                    strategy=strategy,
                                    fill_id=fill_id
                                )
                                
                                if oco_success:
                                    logger.info(f"OCO_PLACED: {symbol} {side} (fill_id={fill_id})")
                                else:
                                    reason = oco_details.get("reason", "unknown")
                                    logger.warning(f"OCO_FAILED: {symbol} {side} (reason={reason})")
                                    
                            except Exception as e:
                                logger.warning(f"OCO placement failed for {symbol}: {e}")
                        
                        return updated_ledger, True
                        
                    except ValueError as e:
                        logger.warning(f"REJECTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} (reason=invariant: {e})")
                        return ledger, False
                        
                else:
                    # Order was not filled
                    reason = router_details.get("reason", "unknown")
                    logger.info(f"REJECTED: {symbol} {side} (reason=post_only_{reason})")
                    return ledger, False
                    
            except Exception as e:
                logger.warning(f"Post-only router failed for {symbol}: {e}")
                # Fall back to regular execution
        
        # Step 2: Get executable price (fallback for non-post-only or failed post-only)
        entry = get_executable_price(symbol)
        if not entry:
            logger.warning(f"REJECTED: {symbol} {side} (reason=no_price)")
            return ledger, False
        
        # Step 3: Get ATR for SL/TP calculation
        atr = get_atr(symbol)
        
        # Step 4: Calculate SL/TP
        try:
            sl, tp, sl_tp_meta = sl_tp_defaults(
                symbol=symbol,
                entry=entry,
                side=side,
                atr=atr
            )
        except Exception as e:
            logger.warning(f"REJECTED: {symbol} {side} (reason=sl_tp_error: {e})")
            return ledger, False
        
        # Step 5: Calculate risk-based position size
        if snapshot:
            equity = snapshot.equity
        else:
            # Fallback to ledger equity if no snapshot
            equity = ledger.cash + sum(pos.qty * entry for pos in ledger.positions.values())
        
        # Calculate position size using risk-based sizing if available
        if self.risk_sizing_calculator:
            # Get current default size for comparison
            current_default_size = size_for_risk(equity=equity, entry=entry, sl=sl)
            
            # Calculate risk-based size
            qty, sizing_reason, sizing_details = self.risk_sizing_calculator.calculate_position_size(
                symbol=symbol,
                side=side,
                entry_price=entry,
            equity=equity,
                current_default_size=current_default_size,
                oco_manager=self.oco_manager
            )
            
            if qty <= 0:
                logger.warning(f"REJECTED: {symbol} {side} (reason=risk_sizing_{sizing_reason})")
                return ledger, False
        else:
            # Fallback to default sizing
            qty = size_for_risk(equity=equity, entry=entry, sl=sl)
        
        if qty <= 0:
            logger.warning(f"REJECTED: {symbol} {side} (reason=size=0)")
            return ledger, False
        
        # Step 6: Create fill with calculated values
        fill_meta = {
            **meta,
            "atr_mode": sl_tp_meta["mode"],
            "risk": sl_tp_meta["risk"],
            "rr": sl_tp_meta["rr"]
        }
        
        fill = Fill(
            symbol=symbol,
            side=side,
            qty=qty,
            price=entry,
            fees=fees,
            ts=datetime.now(),
            sl=sl,
            tp=tp,
            strategy=strategy,
            meta=fill_meta
        )
        
        # Step 7: Apply fill atomically
        try:
            updated_ledger = apply_fill(
                ledger=ledger,
                fill=fill,
                get_mark_price=self.get_mark_price_callback
            )
            
            # Step 8: Log EXECUTED trade with SL/TP info
            sl_tp_summary = get_sl_tp_summary(sl, tp, sl_tp_meta)
            position_summary = get_position_size_summary(qty, entry, sl, tp, side, equity)
            
            # Calculate enhanced trade metrics
            enhanced_metrics = ""
            if self.trade_metrics:
                try:
                    trade_metrics = self.trade_metrics.calculate_trade_metrics(
                        symbol=symbol,
                        side=side,
                        entry_price=entry,
                        quantity=qty,
                        fees=fees,
                        strategy=strategy,
                        ticker_data=self.get_ticker_callback(symbol) if self.get_ticker_callback else None,
                        signal_data=meta,
                        sl_price=sl,
                        tp_price=tp,
                        atr=atr,
                        maker_fill=False,  # Regular execution is typically taker
                        wait_time_seconds=0.0
                    )
                    
                    enhanced_metrics = self.trade_metrics.get_trade_summary(trade_metrics)
                    self.trade_metrics.add_trade(trade_metrics)
                    
                except Exception as e:
                    logger.warning(f"Failed to calculate trade metrics for {symbol}: {e}")
            
            logger.info(
                f"EXECUTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} "
                f"fees=${fees:.2f} strategy={strategy} {sl_tp_summary} {position_summary} {enhanced_metrics}"
            )
            
            # Step 9: Add to committed fills
            self.committed_fills.append(fill)
            
            # Step 10: Place OCO order after successful fill
            if self.oco_manager:
                try:
                    fill_id = f"fill_{symbol}_{side}_{int(time.time())}"
                    oco_success, oco_details = await self.oco_manager.place_oco_order(
                        symbol=symbol,
                        side=side,
                        entry_price=entry,
                        quantity=qty,
                        strategy=strategy,
                        fill_id=fill_id
                    )
                    
                    if oco_success:
                        logger.info(f"OCO_PLACED: {symbol} {side} (fill_id={fill_id})")
                    else:
                        reason = oco_details.get("reason", "unknown")
                        logger.warning(f"OCO_FAILED: {symbol} {side} (reason={reason})")
                        
                except Exception as e:
                    logger.warning(f"OCO placement failed for {symbol}: {e}")
            
            return updated_ledger, True
            
        except ValueError as e:
            # Step 10: Log REJECTED trade
            logger.warning(f"REJECTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} (reason=invariant: {e})")
            return ledger, False
        
        except Exception as e:
            # Step 11: Log REJECTED trade for unexpected errors
            logger.error(f"REJECTED: {symbol} {side} {qty:.6f} @ ${entry:.4f} (reason=error: {e})")
            return ledger, False
    
    def get_committed_fills(self) -> List[Fill]:
        """Get list of fills committed in current cycle."""
        return self.committed_fills.copy()
    
    def get_cycle_metrics(self) -> Dict[str, Any]:
        """Get execution metrics for current cycle."""
        if not self.committed_fills:
            return {
                "trades_executed": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "symbols_traded": [],
                "strategies_used": []
            }
        
        return {
            "trades_executed": len(self.committed_fills),
            "total_volume": sum(abs(fill.qty) for fill in self.committed_fills),
            "total_fees": sum(fill.fees for fill in self.committed_fills),
            "total_notional": sum(fill.notional for fill in self.committed_fills),
            "symbols_traded": list(set(fill.symbol for fill in self.committed_fills)),
            "strategies_used": list(set(fill.strategy for fill in self.committed_fills))
        }

    async def update_trailing_orders(self) -> int:
        """
        Update trailing take-profit orders for all active OCO orders.
        
        Returns:
            Number of orders updated
        """
        if not self.oco_manager:
            return 0
        
        try:
            updated_count = await self.oco_manager.update_trailing_orders()
            if updated_count > 0:
                logger.info(f"Updated {updated_count} trailing take-profit orders")
            return updated_count
        except Exception as e:
            logger.warning(f"Failed to update trailing orders: {e}")
            return 0
    
    async def handle_oco_time_stops(self) -> int:
        """
        Handle time stops for OCO orders that have exceeded the time limit.
        
        Returns:
            Number of orders processed for time stop
        """
        if not self.oco_manager:
            return 0
        
        try:
            processed_count = await self.oco_manager.handle_time_stops()
            if processed_count > 0:
                logger.info(f"Processed {processed_count} OCO time stops")
            return processed_count
        except Exception as e:
            logger.warning(f"Failed to handle OCO time stops: {e}")
            return 0
    
    def get_oco_statistics(self) -> Dict[str, Any]:
        """Get OCO order statistics."""
        if not self.oco_manager:
            return {"oco_enabled": False}
        
        return self.oco_manager.get_oco_statistics()


def create_execution_engine(
    get_mark_price_callback: Callable[[str], Optional[float]],
    get_ticker_callback: Optional[Callable[[str], Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None
) -> ExecutionEngine:
    """Create an execution engine instance."""
    return ExecutionEngine(get_mark_price_callback, get_ticker_callback, config)

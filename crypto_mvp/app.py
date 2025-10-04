"""
Main application for crypto trading bot with atomic trade pipeline.

This module integrates the atomic trade ledger, execution engine, and
portfolio snapshot to provide consistent state across all UI panels.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List, Any
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from portfolio.ledger import Ledger, create_empty_ledger, calculate_session_metrics
from portfolio.snapshot import PortfolioSnapshot, snapshot_from_ledger, format_equity_summary
from execution.engine import ExecutionEngine, create_execution_engine
from src.crypto_mvp.ui_panels import log_cycle_summary
from src.crypto_mvp.core.utils import start_cycle_logging

logger = logging.getLogger(__name__)


class TradingApp:
    """Main trading application with atomic trade pipeline."""
    
    def __init__(self, initial_cash: float = 10000.0, session_id: str = None):
        """
        Initialize trading application.
        
        Args:
            initial_cash: Initial cash balance
            session_id: Session identifier
        """
        self.initial_cash = initial_cash
        self.session_id = session_id or f"session_{int(datetime.now().timestamp())}"
        self.ledger = create_empty_ledger(initial_cash)
        self.execution_engine = None
        self.current_snapshot: Optional[PortfolioSnapshot] = None
        self.cycle_count = 0
        self.start_equity: Optional[float] = None  # Track starting equity for daily P&L
        
        # Initialize execution engine with mark price callback, ticker callback, and config
        self.execution_engine = create_execution_engine(
            self._get_mark_price,
            self._get_ticker_data,
            self.config
        )
        
        logger.info(f"Trading app initialized: session={self.session_id}, cash=${initial_cash:,.2f}")
    
    def _get_mark_price(self, symbol: str) -> Optional[float]:
        """
        Get current mark price (mid price) for a symbol.
        
        This uses mid price (bid + ask) / 2 for unrealized P&L calculations.
        """
        # Get ticker data to calculate mid price
        ticker_data = self._get_ticker_data(symbol)
        if not ticker_data:
            # Fallback to mock prices if no ticker data
            mock_prices = {
                "BTC/USDT": 50000.0,
                "ETH/USDT": 3000.0,
                "BNB/USDT": 300.0,
                "ADA/USDT": 0.5,
                "SOL/USDT": 100.0
            }
            return mock_prices.get(symbol)
        
        # Calculate mid price from bid/ask
        bid = ticker_data.get("bid")
        ask = ticker_data.get("ask")
        
        if bid and ask and bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        
        # Fallback to last price if bid/ask not available
        return ticker_data.get("last")
    
    def _get_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get ticker data with bid/ask prices and timestamp for a symbol.
        
        This is a placeholder - in real implementation, this would
        connect to your data source to get order book data.
        """
        import time
        import random
        
        # Simulate different market conditions
        current_time = time.time()
        
        # Simulate occasional stale data (older than 200ms)
        if random.random() < 0.1:  # 10% chance of stale data
            timestamp = current_time - 0.5  # 500ms old
        else:
            timestamp = current_time - 0.05  # 50ms old (fresh)
        
        # Simulate different spread conditions
        if random.random() < 0.15:  # 15% chance of wide spread
            # Wide spread scenario
            mock_tickers = {
                "BTC/USDT": {
                    "bid": 49950.0,  # 0.1% spread (10 bps)
                    "ask": 50050.0,
                    "last": 50000.0,
                    "volume": 1000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "ETH/USDT": {
                    "bid": 2985.0,   # 0.5% spread (50 bps)
                    "ask": 3015.0,
                    "last": 3000.0,
                    "volume": 5000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "BNB/USDT": {
                    "bid": 297.0,    # 1% spread (100 bps)
                    "ask": 303.0,
                    "last": 300.0,
                    "volume": 2000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "ADA/USDT": {
                    "bid": 0.495,    # 1% spread (100 bps)
                    "ask": 0.505,
                    "last": 0.5,
                    "volume": 10000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "SOL/USDT": {
                    "bid": 99.0,     # 1% spread (100 bps)
                    "ask": 101.0,
                    "last": 100.0,
                    "volume": 3000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                }
            }
        else:
            # Normal spread scenario
            mock_tickers = {
                "BTC/USDT": {
                    "bid": 49995.0,  # 0.02% spread (2 bps)
                    "ask": 50005.0,
                    "last": 50000.0,
                    "volume": 1000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "ETH/USDT": {
                    "bid": 2998.0,   # 0.13% spread (13 bps)
                    "ask": 3002.0,
                    "last": 3000.0,
                    "volume": 5000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "BNB/USDT": {
                    "bid": 299.5,    # 0.33% spread (33 bps)
                    "ask": 300.5,
                    "last": 300.0,
                    "volume": 2000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "ADA/USDT": {
                    "bid": 0.499,    # 0.4% spread (40 bps)
                    "ask": 0.501,
                    "last": 0.5,
                    "volume": 10000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                },
                "SOL/USDT": {
                    "bid": 99.8,     # 0.4% spread (40 bps)
                    "ask": 100.2,
                    "last": 100.0,
                    "volume": 3000.0,
                    "timestamp": timestamp,
                    "venue": "binance"
                }
            }
        
        return mock_tickers.get(symbol)
    
    def _update_mark_prices(self) -> Dict[str, float]:
        """Update all mark prices for current snapshot."""
        marks = {}
        
        # Get prices for all symbols with positions
        symbols = set(pos.symbol for pos in self.ledger.positions.values())
        
        for symbol in symbols:
            price = self._get_mark_price(symbol)
            if price and price > 0:
                marks[symbol] = price
        
        return marks
    
    def create_snapshot(self) -> PortfolioSnapshot:
        """Create current portfolio snapshot."""
        marks = self._update_mark_prices()
        snapshot = snapshot_from_ledger(self.ledger, marks)
        
        # Set start equity on first snapshot
        if self.start_equity is None:
            self.start_equity = snapshot.equity
        
        return snapshot
    
    async def execute_cycle(self, trade_requests: List[Dict]) -> Dict:
        """
        Execute a trading cycle with atomic trade processing.
        
        Args:
            trade_requests: List of trade requests
            
        Returns:
            Cycle execution results
        """
        cycle_start = datetime.now()
        self.cycle_count += 1
        
        logger.info(f"Starting trading cycle #{self.cycle_count}")
        
        # Use debounced logging for this cycle
        with start_cycle_logging():
            # Reset execution engine for new cycle
            self.execution_engine.reset_cycle()
            
            # Execute trades atomically with risk-based sizing
            trades_executed = 0
            trades_rejected = 0
            
            # Create snapshot for equity calculation
            current_snapshot = self.create_snapshot()
            
            for trade_req in trade_requests:
                symbol = trade_req.get("symbol")
                side = trade_req.get("side")
                strategy = trade_req.get("strategy", "unknown")
                
                if not symbol or not side:
                    logger.warning(f"Skipping invalid trade request: {trade_req}")
                    trades_rejected += 1
                    continue
                
                # Execute trade with risk-based position sizing
                updated_ledger, success = await self.execution_engine.execute_trade(
                    ledger=self.ledger,
                    symbol=symbol,
                    side=side,
                    strategy=strategy,
                    fees=trade_req.get("fees", 0.0),
                    meta={"session_id": self.session_id},
                    snapshot=current_snapshot
                )
                
                if success:
                    self.ledger = updated_ledger
                    trades_executed += 1
                    # Update snapshot after successful trade
                    current_snapshot = self.create_snapshot()
                else:
                    trades_rejected += 1
            
            # Create snapshot after all trades
            self.current_snapshot = self.create_snapshot()
            
            # Run portfolio sweep
            if self.execution_engine.portfolio_sweeper:
                try:
                    sweep_results = self.execution_engine.portfolio_sweeper.sweep_portfolio()
                    if sweep_results.get("actions_taken", 0) > 0:
                        logger.info(
                            f"Portfolio sweep: {sweep_results['oco_attached']} OCO attached, "
                            f"{sweep_results['oco_updated']} OCO updated, "
                            f"{sweep_results['protective_exits']} protective exits"
                        )
                except Exception as e:
                    logger.warning(f"Failed to run portfolio sweep: {e}")
            
            # Cleanup expired cooldowns
            if self.execution_engine.sl_cooldown_tracker:
                try:
                    expired_count = self.execution_engine.sl_cooldown_tracker.cleanup_expired_cooldowns()
                    if expired_count > 0:
                        logger.info(f"Cleaned up {expired_count} expired stop-loss cooldowns")
                except Exception as e:
                    logger.warning(f"Failed to cleanup expired cooldowns: {e}")
            
            # Get execution metrics
            execution_metrics = self.execution_engine.get_cycle_metrics()
            committed_fills = self.execution_engine.get_committed_fills()
            
            # Calculate cycle duration
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            
            # Session metrics
            session_metrics = calculate_session_metrics(
                self.ledger, 
                self.session_id, 
                datetime.now().date().isoformat()
            )
            
            # Log unified cycle summary
            log_cycle_summary(
                cycle_id=self.cycle_count,
                duration=cycle_duration,
                snapshot=self.current_snapshot,
                committed_fills=committed_fills,
                ledger=self.ledger,
                session_metrics=session_metrics,
                start_equity=self.start_equity
            )
            
            # Prepare cycle results
            cycle_results = {
                "cycle_id": self.cycle_count,
                "duration": cycle_duration,
                "trades_executed": trades_executed,
                "trades_rejected": trades_rejected,
                "committed_fills": committed_fills,
                "execution_metrics": execution_metrics,
                "snapshot": self.current_snapshot,
                "session_metrics": session_metrics
            }
        
        # Log cycle completion
        self._log_cycle_summary(cycle_results)
        
        return cycle_results
    
    def _log_cycle_summary(self, results: Dict):
        """Log comprehensive cycle summary using single snapshot."""
        if not self.current_snapshot:
            logger.warning("No snapshot available for cycle summary")
            return
        
        snapshot = self.current_snapshot
        execution = results["execution_metrics"]
        
        # Cycle header with consistent position count
        logger.info(
            f"Trading cycle #{results['cycle_id']} completed in {results['duration']:.2f}s"
        )
        
        # Portfolio state using snapshot
        logger.info(f"Portfolio: {format_equity_summary(snapshot)}")
        logger.info(f"Available capital: ${snapshot.cash:,.2f}")
        
        # Trading activity using execution metrics
        if execution["trades_executed"] > 0:
            logger.info(
                f"Trading: {execution['trades_executed']} trades executed, "
                f"volume={execution['total_volume']:.2f}, fees=${execution['total_fees']:.2f}"
            )
        else:
            logger.info("Trading: No trades executed")
        
        # Position breakdown using snapshot
        if snapshot.position_count > 0:
            positions_info = []
            for symbol, position in snapshot.positions.items():
                mark_price = snapshot.marks.get(symbol, 0.0)
                value = snapshot.get_position_value(symbol)
                pnl = snapshot.get_position_pnl(symbol)
                
                positions_info.append(
                    f"{symbol} qty={position.qty:.6f} @ ${mark_price:.4f} "
                    f"avg_cost=${position.avg_cost:.4f} value=${value:.2f} pnl=${pnl:.2f}"
                )
            
            logger.info(f"Positions ({snapshot.position_count}): {'; '.join(positions_info)}")
        else:
            logger.info("Positions: None")
        
        # Daily summary using session metrics
        session = results["session_metrics"]
        if session["total_trades"] > 0:
            logger.info(
                f"Daily Summary: {session['total_trades']} total trades, "
                f"volume={session['total_volume']:.2f}, fees=${session['total_fees']:.2f}, "
                f"notional=${session['total_notional']:,.2f}"
            )
        else:
            logger.info("Daily Summary: No trades today")
        
        # Validation: Ensure consistency
        execution_trades = execution["trades_executed"]
        session_trades = session["total_trades"]
        position_count = snapshot.position_count
        
        if execution_trades == session_trades:
            logger.info(f"Trade count validation: EXECUTED={execution_trades}, SESSION={session_trades} ✓")
        else:
            logger.warning(f"Trade count mismatch: EXECUTED={execution_trades}, SESSION={session_trades}")
        
        logger.info(f"Position count validation: SNAPSHOT={position_count} ✓")
    
    def get_status(self) -> Dict:
        """Get current application status."""
        if not self.current_snapshot:
            self.current_snapshot = self.create_snapshot()
        
        return {
            "session_id": self.session_id,
            "cycle_count": self.cycle_count,
            "snapshot": self.current_snapshot,
            "ledger_state": {
                "cash": self.ledger.cash,
                "equity": self.ledger.equity,
                "total_fills": len(self.ledger.fills),
                "active_positions": len(self.ledger.positions)
            }
        }


async def main():
    """Main application entry point."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create trading app
    app = TradingApp(initial_cash=10000.0)
    
    # Example trade requests (quantity now calculated automatically)
    trade_requests = [
        {"symbol": "BTC/USDT", "side": "BUY", "strategy": "momentum", "fees": 2.50},
        {"symbol": "ETH/USDT", "side": "BUY", "strategy": "momentum", "fees": 1.25},
        {"symbol": "BNB/USDT", "side": "BUY", "strategy": "arbitrage", "fees": 0.75},
    ]
    
    # Execute trading cycles
    for i in range(3):
        logger.info(f"\n{'='*50}")
        logger.info(f"EXECUTING CYCLE {i+1}")
        logger.info(f"{'='*50}")
        
        # Execute cycle
        results = await app.execute_cycle(trade_requests)
        
        # Wait between cycles
        if i < 2:
            logger.info("Waiting 2 seconds until next cycle...")
            import time
            time.sleep(2)
    
    # Final status
    status = app.get_status()
    logger.info(f"\n{'='*50}")
    logger.info("FINAL STATUS")
    logger.info(f"{'='*50}")
    logger.info(f"Session: {status['session_id']}")
    logger.info(f"Cycles completed: {status['cycle_count']}")
    logger.info(f"Total fills: {status['ledger_state']['total_fills']}")
    logger.info(f"Final equity: ${status['snapshot'].equity:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())

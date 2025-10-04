"""
Trade metrics collection and calculation for enhanced execution logging.

This module collects and calculates detailed trade metrics for expectancy debugging,
including spread analysis, slippage calculation, and regime classification.
"""

import math
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class TradeMetrics(LoggerMixin):
    """
    Collects and calculates detailed trade metrics for enhanced logging.
    
    Features:
    - Spread and slippage calculation
    - Fee analysis
    - Edge after costs calculation
    - Regime classification
    - Signal score tracking
    - Risk-reward analysis
    - ATR and distance calculations
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the trade metrics collector.
        
        Args:
            config: Configuration dictionary with logging settings
        """
        super().__init__()
        self.config = config
        
        # Logging settings
        logging_config = config.get("logging", {})
        self.enhanced_logs = logging_config.get("enhanced_execution_logs", True)
        self.aggregation_interval = logging_config.get("aggregation_interval", 50)
        self.include_regime_analysis = logging_config.get("include_regime_analysis", True)
        
        # Trade history for aggregation
        self.trade_history: List[Dict[str, Any]] = []
        
        self.logger.info(f"TradeMetrics initialized: enhanced_logs={self.enhanced_logs}, "
                        f"aggregation_interval={self.aggregation_interval}")
    
    def calculate_trade_metrics(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        fees: float,
        strategy: str,
        ticker_data: Optional[Dict[str, Any]] = None,
        signal_data: Optional[Dict[str, Any]] = None,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        atr: Optional[float] = None,
        maker_fill: bool = False,
        wait_time_seconds: float = 0.0
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive trade metrics.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Position quantity
            fees: Trading fees
            strategy: Strategy name
            ticker_data: Ticker data with bid/ask
            signal_data: Signal data with scores
            sl_price: Stop-loss price
            tp_price: Take-profit price
            atr: ATR value
            maker_fill: Whether this was a maker fill
            wait_time_seconds: Wait time for fill
            
        Returns:
            Dictionary of calculated metrics
        """
        metrics = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "fees": fees,
            "strategy": strategy,
            "timestamp": datetime.now(),
            "maker_fill": maker_fill,
            "wait_time_seconds": wait_time_seconds
        }
        
        # Calculate spread metrics
        spread_metrics = self._calculate_spread_metrics(ticker_data, entry_price)
        metrics.update(spread_metrics)
        
        # Calculate slippage
        slippage_metrics = self._calculate_slippage_metrics(ticker_data, entry_price, side)
        metrics.update(slippage_metrics)
        
        # Calculate fee metrics
        fee_metrics = self._calculate_fee_metrics(fees, entry_price, quantity)
        metrics.update(fee_metrics)
        
        # Calculate edge after costs
        edge_metrics = self._calculate_edge_metrics(metrics, signal_data)
        metrics.update(edge_metrics)
        
        # Calculate regime
        regime = self._calculate_regime(symbol, signal_data, ticker_data)
        metrics["regime"] = regime
        
        # Calculate signal score
        signal_score = self._extract_signal_score(signal_data)
        metrics["signal_score"] = signal_score
        
        # Calculate risk-reward metrics
        rr_metrics = self._calculate_risk_reward_metrics(entry_price, sl_price, tp_price)
        metrics.update(rr_metrics)
        
        # Calculate ATR and distances
        atr_metrics = self._calculate_atr_metrics(atr, entry_price, sl_price, tp_price)
        metrics.update(atr_metrics)
        
        return metrics
    
    def _calculate_spread_metrics(
        self,
        ticker_data: Optional[Dict[str, Any]],
        entry_price: float
    ) -> Dict[str, Any]:
        """Calculate spread-related metrics."""
        if not ticker_data or "bid" not in ticker_data or "ask" not in ticker_data:
            return {
                "spread_bps_at_entry": None,
                "bid": None,
                "ask": None,
                "mid_price": None
            }
        
        bid = ticker_data["bid"]
        ask = ticker_data["ask"]
        mid_price = (bid + ask) / 2
        
        if mid_price > 0:
            spread_bps = ((ask - bid) / mid_price) * 10000
        else:
            spread_bps = None
        
        return {
            "spread_bps_at_entry": spread_bps,
            "bid": bid,
            "ask": ask,
            "mid_price": mid_price
        }
    
    def _calculate_slippage_metrics(
        self,
        ticker_data: Optional[Dict[str, Any]],
        entry_price: float,
        side: str
    ) -> Dict[str, Any]:
        """Calculate slippage metrics."""
        if not ticker_data or "bid" not in ticker_data or "ask" not in ticker_data:
            return {
                "slippage_bps": None,
                "expected_price": None
            }
        
        bid = ticker_data["bid"]
        ask = ticker_data["ask"]
        
        # Expected price based on side
        if side.upper() == "BUY":
            expected_price = ask  # Buying at ask
        else:  # SELL
            expected_price = bid  # Selling at bid
        
        if expected_price > 0:
            slippage_bps = ((entry_price - expected_price) / expected_price) * 10000
        else:
            slippage_bps = None
        
        return {
            "slippage_bps": slippage_bps,
            "expected_price": expected_price
        }
    
    def _calculate_fee_metrics(
        self,
        fees: float,
        entry_price: float,
        quantity: float
    ) -> Dict[str, Any]:
        """Calculate fee-related metrics."""
        notional = entry_price * quantity
        
        if notional > 0:
            fee_bps = (fees / notional) * 10000
        else:
            fee_bps = None
        
        return {
            "fee_bps": fee_bps,
            "notional": notional
        }
    
    def _calculate_edge_metrics(
        self,
        metrics: Dict[str, Any],
        signal_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate edge after costs metrics."""
        spread_bps = metrics.get("spread_bps_at_entry", 0) or 0
        fee_bps = metrics.get("fee_bps", 0) or 0
        
        # Get expected move from signal data
        expected_move_bps = self._extract_expected_move_bps(signal_data)
        
        if expected_move_bps is not None:
            # Edge after costs = expected move - spread - 2*fees (round trip)
            edge_after_costs_bps = expected_move_bps - spread_bps - (2 * fee_bps)
        else:
            edge_after_costs_bps = None
        
        return {
            "edge_after_costs_bps": edge_after_costs_bps,
            "expected_move_bps": expected_move_bps
        }
    
    def _calculate_regime(
        self,
        symbol: str,
        signal_data: Optional[Dict[str, Any]],
        ticker_data: Optional[Dict[str, Any]]
    ) -> str:
        """Calculate market regime classification."""
        # Simple regime classification based on volatility and signal strength
        signal_score = self._extract_signal_score(signal_data)
        spread_bps = self._calculate_spread_metrics(ticker_data, 0).get("spread_bps_at_entry", 0) or 0
        
        if signal_score is None:
            return "unknown"
        
        if signal_score > 0.7 and spread_bps < 5:
            return "trending_tight"
        elif signal_score > 0.5 and spread_bps < 10:
            return "trending_normal"
        elif signal_score < 0.3 or spread_bps > 20:
            return "choppy_wide"
        else:
            return "normal"
    
    def _extract_signal_score(self, signal_data: Optional[Dict[str, Any]]) -> Optional[float]:
        """Extract signal score from signal data."""
        if not signal_data:
            return None
        
        # Try different possible signal score fields
        for field in ["signal_score", "confidence", "strength", "score"]:
            if field in signal_data:
                return float(signal_data[field])
        
        return None
    
    def _extract_expected_move_bps(self, signal_data: Optional[Dict[str, Any]]) -> Optional[float]:
        """Extract expected move in basis points from signal data."""
        if not signal_data:
            return None
        
        # Try different possible expected move fields
        for field in ["expected_move", "expected_move_bps", "target_move"]:
            if field in signal_data:
                value = signal_data[field]
                if isinstance(value, (int, float)):
                    # If it's already in bps, return as is
                    if field.endswith("_bps") or value > 1:
                        return float(value)
                    else:
                        # Convert percentage to bps
                        return float(value) * 10000
        
        return None
    
    def _calculate_risk_reward_metrics(
        self,
        entry_price: float,
        sl_price: Optional[float],
        tp_price: Optional[float]
    ) -> Dict[str, Any]:
        """Calculate risk-reward metrics."""
        if not sl_price or not tp_price:
            return {
                "expected_rr": None,
                "risk_amount": None,
                "reward_amount": None
            }
        
        risk_amount = abs(entry_price - sl_price)
        reward_amount = abs(tp_price - entry_price)
        
        if risk_amount > 0:
            expected_rr = reward_amount / risk_amount
        else:
            expected_rr = None
        
        return {
            "expected_rr": expected_rr,
            "risk_amount": risk_amount,
            "reward_amount": reward_amount
        }
    
    def _calculate_atr_metrics(
        self,
        atr: Optional[float],
        entry_price: float,
        sl_price: Optional[float],
        tp_price: Optional[float]
    ) -> Dict[str, Any]:
        """Calculate ATR and distance metrics."""
        metrics = {
            "atr": atr
        }
        
        if sl_price:
            sl_distance = abs(entry_price - sl_price)
            metrics["sl_distance"] = sl_distance
            
            if atr and atr > 0:
                metrics["sl_distance_atr"] = sl_distance / atr
            else:
                metrics["sl_distance_atr"] = None
        else:
            metrics["sl_distance"] = None
            metrics["sl_distance_atr"] = None
        
        if tp_price:
            tp_distance = abs(tp_price - entry_price)
            metrics["tp_distance"] = tp_distance
            
            if atr and atr > 0:
                metrics["tp_distance_atr"] = tp_distance / atr
            else:
                metrics["tp_distance_atr"] = None
        else:
            metrics["tp_distance"] = None
            metrics["tp_distance_atr"] = None
        
        return metrics
    
    def add_trade(self, metrics: Dict[str, Any]) -> None:
        """Add trade metrics to history and check for aggregation."""
        if not self.enhanced_logs:
            return
        
        self.trade_history.append(metrics)
        
        # Check if we should print aggregated table
        if len(self.trade_history) % self.aggregation_interval == 0:
            self._print_aggregated_table()
    
    def _print_aggregated_table(self) -> None:
        """Print aggregated table every N trades."""
        if not self.trade_history:
            return
        
        # Get recent trades for aggregation
        recent_trades = self.trade_history[-self.aggregation_interval:]
        
        # Group by (regime, maker_or_taker, spread_quintile)
        groups = {}
        
        for trade in recent_trades:
            regime = trade.get("regime", "unknown")
            maker_or_taker = "maker" if trade.get("maker_fill", False) else "taker"
            spread_bps = trade.get("spread_bps_at_entry", 0) or 0
            
            # Calculate spread quintile
            spread_quintile = self._calculate_spread_quintile(spread_bps)
            
            key = (regime, maker_or_taker, spread_quintile)
            
            if key not in groups:
                groups[key] = {
                    "count": 0,
                    "total_fees": 0.0,
                    "total_slippage": 0.0,
                    "total_edge": 0.0,
                    "avg_signal_score": 0.0,
                    "avg_rr": 0.0
                }
            
            group = groups[key]
            group["count"] += 1
            group["total_fees"] += trade.get("fee_bps", 0) or 0
            group["total_slippage"] += trade.get("slippage_bps", 0) or 0
            group["total_edge"] += trade.get("edge_after_costs_bps", 0) or 0
            group["avg_signal_score"] += trade.get("signal_score", 0) or 0
            group["avg_rr"] += trade.get("expected_rr", 0) or 0
        
        # Print aggregated table
        self.logger.info("=" * 80)
        self.logger.info(f"TRADE AGGREGATION TABLE (Last {len(recent_trades)} trades)")
        self.logger.info("=" * 80)
        self.logger.info(f"{'Regime':<15} {'Type':<6} {'Spread':<8} {'Count':<6} {'AvgFee':<8} {'AvgSlip':<8} {'AvgEdge':<8} {'AvgSig':<8} {'AvgRR':<8}")
        self.logger.info("-" * 80)
        
        for (regime, maker_or_taker, spread_quintile), group in sorted(groups.items()):
            count = group["count"]
            avg_fee = group["total_fees"] / count if count > 0 else 0
            avg_slippage = group["total_slippage"] / count if count > 0 else 0
            avg_edge = group["total_edge"] / count if count > 0 else 0
            avg_signal = group["avg_signal_score"] / count if count > 0 else 0
            avg_rr = group["avg_rr"] / count if count > 0 else 0
            
            self.logger.info(
                f"{regime:<15} {maker_or_taker:<6} {spread_quintile:<8} {count:<6} "
                f"{avg_fee:<8.2f} {avg_slippage:<8.2f} {avg_edge:<8.2f} "
                f"{avg_signal:<8.3f} {avg_rr:<8.2f}"
            )
        
        self.logger.info("=" * 80)
    
    def _calculate_spread_quintile(self, spread_bps: float) -> str:
        """Calculate spread quintile classification."""
        if spread_bps <= 2:
            return "Q1(0-2)"
        elif spread_bps <= 5:
            return "Q2(2-5)"
        elif spread_bps <= 10:
            return "Q3(5-10)"
        elif spread_bps <= 20:
            return "Q4(10-20)"
        else:
            return "Q5(20+)"
    
    def get_trade_summary(self, metrics: Dict[str, Any]) -> str:
        """Get formatted trade summary for logging."""
        if not self.enhanced_logs:
            return ""
        
        # Format key metrics
        maker_or_taker = "maker" if metrics.get("maker_fill", False) else "taker"
        spread_bps = metrics.get("spread_bps_at_entry", 0) or 0
        slippage_bps = metrics.get("slippage_bps", 0) or 0
        fee_bps = metrics.get("fee_bps", 0) or 0
        edge_bps = metrics.get("edge_after_costs_bps", 0) or 0
        regime = metrics.get("regime", "unknown")
        signal_score = metrics.get("signal_score", 0) or 0
        expected_rr = metrics.get("expected_rr", 0) or 0
        atr = metrics.get("atr", 0) or 0
        tp_distance = metrics.get("tp_distance", 0) or 0
        sl_distance = metrics.get("sl_distance", 0) or 0
        
        return (
            f"type={maker_or_taker} spread={spread_bps:.1f}bps slip={slippage_bps:.1f}bps "
            f"fee={fee_bps:.1f}bps edge={edge_bps:.1f}bps regime={regime} "
            f"signal={signal_score:.3f} rr={expected_rr:.2f} atr={atr:.4f} "
            f"tp_dist={tp_distance:.4f} sl_dist={sl_distance:.4f}"
        )

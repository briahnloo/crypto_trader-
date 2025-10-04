"""
Edge after costs guard for preventing money-losing entries.

This module implements a pre-trade guard that calculates the expected edge
after accounting for spread and fees, and rejects trades that don't meet
the minimum threshold.
"""

from typing import Optional, Dict, Any, Tuple
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class EdgeAfterCostsGuard(LoggerMixin):
    """
    Guard that prevents trades with insufficient edge after costs.
    
    Calculates: edge_after_costs_bps = expected_move_bps - (spread_bps + 2*fee_bps)
    Rejects trades where edge_after_costs_bps < min_threshold
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the edge after costs guard.
        
        Args:
            config: Configuration dictionary with execution settings
        """
        super().__init__()
        self.config = config
        
        # Guard settings
        self.require_edge_after_costs = config.get("require_edge_after_costs", True)
        self.min_edge_after_costs_bps = config.get("min_edge_after_costs_bps", 10)
        
        # Fee settings (from order manager config)
        self.maker_fee_bps = config.get("maker_fee_bps", 10)  # 0.1%
        self.taker_fee_bps = config.get("taker_fee_bps", 20)  # 0.2%
        
        self.logger.info(f"EdgeAfterCostsGuard initialized: require={self.require_edge_after_costs}, "
                        f"min_edge={self.min_edge_after_costs_bps}bps, "
                        f"maker_fee={self.maker_fee_bps}bps, taker_fee={self.taker_fee_bps}bps")
    
    def check_edge_after_costs(
        self,
        symbol: str,
        ticker_data: Dict[str, Any],
        expected_move_bps: float,
        is_maker: bool = False
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if trade has sufficient edge after costs.
        
        Formula: edge_after_costs_bps = expected_move_bps - (spread_bps + 2*fee_bps)
        Requires: edge_after_costs_bps >= min_edge_after_costs_bps
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data with bid/ask prices
            expected_move_bps: Expected price move in basis points
            is_maker: Whether this is a maker order (affects fee calculation)
            
        Returns:
            Tuple of (can_proceed, details_dict)
            - can_proceed: True if trade should proceed
            - details_dict: Dictionary with all calculated components
        """
        if not self.require_edge_after_costs:
            return True, {"reason": "guard_disabled"}
        
        # Extract bid/ask from ticker data
        bid = ticker_data.get('bid')
        ask = ticker_data.get('ask')
        
        if not bid or not ask or bid <= 0 or ask <= 0:
            self.logger.warning(f"REJECTED: {symbol} (reason=missing_bid_ask)")
            return False, {
                "reason": "missing_bid_ask",
                "bid": bid,
                "ask": ask
            }
        
        # Calculate mid price
        mid = (bid + ask) / 2
        
        # Calculate spread in basis points: spread_bps = (ask - bid) / mid * 1e4
        spread_bps = ((ask - bid) / mid) * 10000
        
        # Get fee from venue (use taker for worst-case guard, but respect maker flag)
        if is_maker:
            fee_bps = self.maker_fee_bps  # Use maker fee for maker orders
        else:
            fee_bps = self.taker_fee_bps  # Use taker fee for conservative guard
        
        # Calculate edge after costs: edge_after_costs_bps = expected_move_bps - (spread_bps + 2*fee_bps)
        edge_after_costs_bps = expected_move_bps - (spread_bps + 2 * fee_bps)
        
        # Create details dictionary with all components
        details = {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "fee_bps": fee_bps,
            "expected_move_bps": expected_move_bps,
            "edge_after_costs_bps": edge_after_costs_bps,
            "min_edge_after_costs_bps": self.min_edge_after_costs_bps,
            "is_maker": is_maker
        }
        
        # Check if edge meets threshold
        can_proceed = edge_after_costs_bps >= self.min_edge_after_costs_bps
        
        # Log all components as requested
        if can_proceed:
            self.logger.info(
                f"EDGE_CHECK_PASS: {symbol} - "
                f"spread_bps={spread_bps:.1f}, "
                f"fee_bps={fee_bps}, "
                f"expected_move_bps={expected_move_bps:.1f}, "
                f"edge_after_costs_bps={edge_after_costs_bps:.1f} "
                f"(threshold={self.min_edge_after_costs_bps})"
            )
        else:
            self.logger.info(
                f"EDGE_CHECK_FAIL: {symbol} - "
                f"spread_bps={spread_bps:.1f}, "
                f"fee_bps={fee_bps}, "
                f"expected_move_bps={expected_move_bps:.1f}, "
                f"edge_after_costs_bps={edge_after_costs_bps:.1f} "
                f"(threshold={self.min_edge_after_costs_bps})"
            )
        
        return can_proceed, details
    
    def get_expected_move_bps_from_signal(self, signal: Dict[str, Any]) -> float:
        """
        Extract expected move in basis points from trading signal.
        
        Args:
            signal: Trading signal dictionary
            
        Returns:
            Expected move in basis points
        """
        # Try to get expected move from signal metadata
        expected_move = signal.get("expected_move", 0.0)
        
        # If not available, estimate from confidence and signal strength
        if expected_move <= 0:
            confidence = signal.get("confidence", 0.0)
            signal_strength = signal.get("signal_strength", 0.0)
            
            # Rough estimation: higher confidence/strength = higher expected move
            # This is a simplified heuristic - in practice you'd want more sophisticated estimation
            expected_move = (confidence * signal_strength) * 0.02  # Max 2% move
        
        # Convert to basis points (expected_move is already in decimal form)
        return expected_move * 10000
    
    def should_skip_trade(
        self,
        symbol: str,
        ticker_data: Dict[str, Any],
        signal: Dict[str, Any],
        is_maker: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Main method to check if trade should be skipped due to insufficient edge.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data with bid/ask prices
            signal: Trading signal
            is_maker: Whether this is a maker order
            
        Returns:
            Tuple of (should_skip, reason, details)
        """
        if not self.require_edge_after_costs:
            return False, "guard_disabled", {}
        
        # Get expected move from signal
        expected_move_bps = self.get_expected_move_bps_from_signal(signal)
        
        if expected_move_bps <= 0:
            return True, "no_expected_move", {"expected_move_bps": expected_move_bps}
        
        # Check edge after costs
        can_proceed, details = self.check_edge_after_costs(
            symbol, ticker_data, expected_move_bps, is_maker
        )
        
        if not can_proceed:
            return True, "insufficient_edge", details
        
        return False, "sufficient_edge", details

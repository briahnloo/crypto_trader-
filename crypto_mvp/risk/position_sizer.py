"""
Volatility-Normalized Position Sizer for consistent dollar P&L impact.

This module calculates position sizes to ensure a 0.5-1.0% move results in
$30-$150 on a $10k account, using ATR-based volatility normalization.

Key Features:
- ATR percentage calculation (ATR / price)
- Target 1-1.5R ≈ 0.5-0.8% move on majors
- Risk-based sizing: qty = (equity * risk_per_trade_pct) / (entry * stop_distance)
- Multiple caps: max_notional_pct, per_symbol_cap_$, session_cap_$
- Notional floors: $500 normal, $150 exploration
- Proper qty rounding to exchange steps
"""

from decimal import Decimal
from typing import Dict, Optional, Tuple, Any
import logging

from ..src.crypto_mvp.core.money import (
    to_dec, ONE, ZERO,
    quantize_price, quantize_qty,
    validate_order_size,
    get_exchange_steps
)

logger = logging.getLogger(__name__)


class VolatilityNormalizedSizer:
    """
    Position sizer using ATR-based volatility normalization for consistent P&L impact.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize volatility-normalized position sizer.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Risk parameters
        self.risk_per_trade_pct = to_dec(self.config.get("risk_per_trade_pct", 0.25))  # 0.25% per trade
        self.max_notional_pct = to_dec(self.config.get("max_notional_pct", 2.5))  # 2.5% max notional
        
        # Cap parameters (in dollars)
        self.per_symbol_cap_usd = to_dec(self.config.get("per_symbol_cap_usd", 5000))  # $5000 per symbol
        self.session_cap_usd = to_dec(self.config.get("session_cap_usd", 15000))  # $15000 per session
        
        # Notional floors
        self.notional_floor_normal = to_dec(self.config.get("notional_floor_normal", 500))  # $500 normal
        self.notional_floor_exploration = to_dec(self.config.get("notional_floor_exploration", 150))  # $150 exploration
        
        # ATR targeting
        self.target_r_min = to_dec(self.config.get("target_r_min", 1.0))  # 1R minimum
        self.target_r_max = to_dec(self.config.get("target_r_max", 1.5))  # 1.5R maximum
        self.target_move_pct_min = to_dec(self.config.get("target_move_pct_min", 0.005))  # 0.5%
        self.target_move_pct_max = to_dec(self.config.get("target_move_pct_max", 0.008))  # 0.8%
        
        logger.info(
            f"VolatilityNormalizedSizer initialized: "
            f"risk_per_trade={float(self.risk_per_trade_pct)}%, "
            f"max_notional={float(self.max_notional_pct)}%, "
            f"per_symbol_cap=${float(self.per_symbol_cap_usd)}, "
            f"session_cap=${float(self.session_cap_usd)}, "
            f"floor_normal=${float(self.notional_floor_normal)}, "
            f"floor_exploration=${float(self.notional_floor_exploration)}"
        )
    
    def calculate_atr_pct(
        self,
        symbol: str,
        atr: float,
        price: float,
        data_engine=None
    ) -> Decimal:
        """
        Calculate ATR as percentage of price for volatility normalization.
        
        Args:
            symbol: Trading symbol
            atr: Average True Range value
            price: Current price
            data_engine: Data engine (for fallback ATR calculation)
            
        Returns:
            ATR percentage (e.g., 0.025 for 2.5%)
        """
        price_dec = to_dec(price)
        
        if atr and atr > 0:
            atr_dec = to_dec(atr)
        elif data_engine:
            # Fallback: Try to get ATR from data engine
            try:
                # Assuming data engine has ATR indicator
                atr_value = data_engine.get_indicator(symbol, "atr", period=14)
                if atr_value and atr_value > 0:
                    atr_dec = to_dec(atr_value)
                else:
                    # Fallback to 2% of price (conservative estimate)
                    atr_dec = price_dec * to_dec("0.02")
                    logger.warning(f"No ATR data for {symbol}, using 2% estimate: {float(atr_dec):.4f}")
            except Exception as e:
                atr_dec = price_dec * to_dec("0.02")
                logger.warning(f"Failed to get ATR for {symbol}: {e}, using 2% estimate")
        else:
            # No ATR available - use 2% estimate
            atr_dec = price_dec * to_dec("0.02")
            logger.warning(f"No ATR provided for {symbol}, using 2% estimate")
        
        # Calculate ATR percentage
        if price_dec > ZERO:
            atr_pct = atr_dec / price_dec
        else:
            atr_pct = to_dec("0.02")  # Fallback
        
        logger.debug(f"ATR% for {symbol}: {float(atr_pct * to_dec('100')):.2f}% "
                    f"(ATR={float(atr_dec):.4f}, price={float(price_dec):.4f})")
        
        return atr_pct
    
    def calculate_stop_distance(
        self,
        entry_price: float,
        side: str,
        atr: Optional[float] = None,
        atr_pct: Optional[Decimal] = None,
        stop_loss: Optional[float] = None,
        atr_multiplier: float = 2.0
    ) -> Decimal:
        """
        Calculate stop loss distance using ATR or provided SL.
        
        Args:
            entry_price: Entry price
            side: Position side ("long"/"buy" or "short"/"sell")
            atr: Average True Range value
            atr_pct: ATR percentage (alternative to atr)
            stop_loss: Explicit stop loss price (overrides ATR)
            atr_multiplier: ATR multiplier for stop (default: 2.0)
            
        Returns:
            Stop distance as Decimal
        """
        entry_dec = to_dec(entry_price)
        
        if stop_loss is not None and stop_loss > 0:
            # Use explicit stop loss
            stop_dec = to_dec(stop_loss)
            stop_distance = abs(entry_dec - stop_dec)
        elif atr_pct is not None:
            # Use ATR percentage
            stop_distance = entry_dec * atr_pct * to_dec(atr_multiplier)
        elif atr is not None and atr > 0:
            # Use ATR value
            atr_dec = to_dec(atr)
            stop_distance = atr_dec * to_dec(atr_multiplier)
        else:
            # Fallback: 2% of entry price
            stop_distance = entry_dec * to_dec("0.02")
            logger.warning(f"No ATR/SL provided, using 2% stop distance: {float(stop_distance):.4f}")
        
        return stop_distance
    
    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        side: str,
        equity: float,
        atr: Optional[float] = None,
        stop_loss: Optional[float] = None,
        data_engine=None,
        is_exploration: bool = False,
        current_symbol_exposure: float = 0.0,
        current_session_exposure: float = 0.0
    ) -> Dict[str, Any]:
        """
        Calculate volatility-normalized position size.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            side: Position side ("long"/"buy" or "short"/"sell")
            equity: Total portfolio equity
            atr: Average True Range value
            stop_loss: Explicit stop loss price
            data_engine: Data engine for ATR lookup
            is_exploration: Whether this is an exploration trade (lower floor)
            current_symbol_exposure: Current notional exposure for this symbol
            current_session_exposure: Current total notional exposure this session
            
        Returns:
            Dictionary with size, notional, metrics, and validation info
        """
        # Convert inputs to Decimal
        entry_dec = to_dec(entry_price)
        equity_dec = to_dec(equity)
        symbol_exposure_dec = to_dec(current_symbol_exposure)
        session_exposure_dec = to_dec(current_session_exposure)
        
        # Calculate ATR percentage
        atr_pct = self.calculate_atr_pct(symbol, atr, entry_price, data_engine)
        
        # Calculate stop distance
        stop_distance = self.calculate_stop_distance(
            entry_price=entry_price,
            side=side,
            atr=atr,
            atr_pct=atr_pct,
            stop_loss=stop_loss,
            atr_multiplier=2.0
        )
        
        if stop_distance <= ZERO:
            logger.error(f"Invalid stop distance: {float(stop_distance)}")
            return self._empty_result(symbol, "invalid_stop_distance")
        
        # Calculate quantity based on risk formula
        # qty = (equity * risk_per_trade_pct) / (entry * stop_distance)
        risk_amount = equity_dec * (self.risk_per_trade_pct / to_dec("100"))
        risk_per_unit = stop_distance
        
        qty_by_risk = risk_amount / risk_per_unit
        
        # Calculate notional
        notional_by_risk = qty_by_risk * entry_dec
        
        # Apply notional cap (max_notional_pct of equity)
        max_notional = equity_dec * (self.max_notional_pct / to_dec("100"))
        
        if notional_by_risk > max_notional:
            notional_capped = max_notional
            qty_capped = notional_capped / entry_dec
            cap_reason = "max_notional_pct"
        else:
            notional_capped = notional_by_risk
            qty_capped = qty_by_risk
            cap_reason = "none"
        
        # Apply per-symbol cap
        remaining_symbol_cap = self.per_symbol_cap_usd - symbol_exposure_dec
        if remaining_symbol_cap <= ZERO:
            logger.warning(f"Symbol cap exceeded for {symbol}: ${float(symbol_exposure_dec):.2f} >= ${float(self.per_symbol_cap_usd):.2f}")
            return self._empty_result(symbol, "symbol_cap_exceeded")
        
        if notional_capped > remaining_symbol_cap:
            notional_capped = remaining_symbol_cap
            qty_capped = notional_capped / entry_dec
            cap_reason = "per_symbol_cap"
        
        # Apply session cap
        remaining_session_cap = self.session_cap_usd - session_exposure_dec
        if remaining_session_cap <= ZERO:
            logger.warning(f"Session cap exceeded: ${float(session_exposure_dec):.2f} >= ${float(self.session_cap_usd):.2f}")
            return self._empty_result(symbol, "session_cap_exceeded")
        
        if notional_capped > remaining_session_cap:
            notional_capped = remaining_session_cap
            qty_capped = notional_capped / entry_dec
            cap_reason = "session_cap"
        
        # Round quantity to exchange step
        qty_rounded = quantize_qty(qty_capped, symbol)
        
        # Recompute notional after rounding
        notional_final = qty_rounded * entry_dec
        
        # Apply notional floor
        floor = self.notional_floor_exploration if is_exploration else self.notional_floor_normal
        
        if notional_final < floor:
            # Scale up to meet floor
            qty_floored = floor / entry_dec
            qty_rounded = quantize_qty(qty_floored, symbol)
            notional_final = qty_rounded * entry_dec
            
            logger.info(f"Notional below floor for {symbol}: scaled to ${float(notional_final):.2f} (floor=${float(floor):.2f})")
        
        # Validate order size with exchange
        is_valid, validation_error = validate_order_size(entry_dec, qty_rounded, symbol)
        
        if not is_valid:
            logger.error(f"Order size validation failed for {symbol}: {validation_error}")
            return self._empty_result(symbol, f"validation_failed: {validation_error}")
        
        # Calculate expected P&L for target move
        move_pct = to_dec("0.005")  # 0.5% move
        expected_pnl_05pct = qty_rounded * entry_dec * move_pct
        
        # Calculate risk metrics
        total_risk_usd = qty_rounded * risk_per_unit
        risk_pct_of_equity = (total_risk_usd / equity_dec) * to_dec("100")
        notional_pct_of_equity = (notional_final / equity_dec) * to_dec("100")
        
        result = {
            "symbol": symbol,
            "side": side,
            "quantity": float(qty_rounded),
            "quantity_raw": float(qty_by_risk),
            "entry_price": float(entry_dec),
            "notional": float(notional_final),
            "notional_pct_equity": float(notional_pct_of_equity),
            
            # Risk metrics
            "atr": float(atr) if atr else None,
            "atr_pct": float(atr_pct * to_dec("100")),  # As percentage
            "stop_distance": float(stop_distance),
            "stop_distance_pct": float((stop_distance / entry_dec) * to_dec("100")),
            "risk_amount_usd": float(risk_amount),
            "total_risk_usd": float(total_risk_usd),
            "risk_pct_equity": float(risk_pct_of_equity),
            
            # Expected P&L
            "expected_pnl_0.5pct_move": float(expected_pnl_05pct),
            "expected_pnl_1.0pct_move": float(expected_pnl_05pct * to_dec("2")),
            
            # Caps and floors
            "cap_reason": cap_reason,
            "floor_applied": notional_final == floor,
            "is_exploration": is_exploration,
            "remaining_symbol_cap": float(remaining_symbol_cap),
            "remaining_session_cap": float(remaining_session_cap),
            
            # Validation
            "valid": True,
            "validation_error": None
        }
        
        # Log sizing decision
        logger.info(
            f"POSITION_SIZE: {symbol} {side} qty={float(qty_rounded):.6f} "
            f"notional=${float(notional_final):.2f} ({float(notional_pct_of_equity):.2f}% equity) "
            f"risk=${float(total_risk_usd):.2f} ({float(risk_pct_of_equity):.3f}% equity) "
            f"stop_dist={float(stop_distance):.4f} ({float((stop_distance/entry_dec)*to_dec('100')):.2f}%) "
            f"atr_pct={float(atr_pct*to_dec('100')):.2f}% "
            f"expected_pnl_0.5%=${float(expected_pnl_05pct):.2f} "
            f"cap={cap_reason}"
        )
        
        return result
    
    def _empty_result(self, symbol: str, reason: str) -> Dict[str, Any]:
        """Return empty result for rejected position."""
        logger.warning(f"Position sizing rejected for {symbol}: {reason}")
        return {
            "symbol": symbol,
            "quantity": 0.0,
            "notional": 0.0,
            "valid": False,
            "validation_error": reason,
            "expected_pnl_0.5pct_move": 0.0,
            "expected_pnl_1.0pct_move": 0.0
        }
    
    def get_sizing_summary(self, result: Dict[str, Any]) -> str:
        """Get formatted sizing summary for logging."""
        if not result.get("valid"):
            return f"{result['symbol']}: REJECTED ({result.get('validation_error', 'unknown')})"
        
        return (
            f"{result['symbol']}: qty={result['quantity']:.6f} "
            f"notional=${result['notional']:.2f} ({result['notional_pct_equity']:.2f}% equity) "
            f"risk=${result['total_risk_usd']:.2f} ({result['risk_pct_equity']:.3f}% equity) "
            f"ATR={result['atr_pct']:.2f}% stop_dist={result['stop_distance_pct']:.2f}% "
            f"expected_pnl(0.5%)=${result['expected_pnl_0.5pct_move']:.2f} "
            f"expected_pnl(1.0%)=${result['expected_pnl_1.0pct_move']:.2f} "
            f"cap={result['cap_reason']}"
        )


# Convenience function
def calculate_volatility_normalized_size(
    symbol: str,
    entry_price: float,
    side: str,
    equity: float,
    atr: Optional[float] = None,
    stop_loss: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Convenience function for volatility-normalized position sizing.
    
    See VolatilityNormalizedSizer.calculate_position_size for full documentation.
    """
    sizer = VolatilityNormalizedSizer(config)
    return sizer.calculate_position_size(
        symbol=symbol,
        entry_price=entry_price,
        side=side,
        equity=equity,
        atr=atr,
        stop_loss=stop_loss,
        **kwargs
    )


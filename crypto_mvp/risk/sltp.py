"""
Stop Loss and Take Profit calculation with ATR and percentage fallback.

This module provides robust SL/TP calculation using ATR when available,
with percentage-based fallback for symbols without ATR data.
"""

from typing import Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def sl_tp_defaults(
    symbol: str,
    entry: float,
    side: str,
    atr: Optional[float] = None,
    rr: float = 1.88,
    pct_sl: float = 0.02,
    atr_multiplier: float = 1.5
) -> Tuple[float, float, Dict[str, any]]:
    """
    Calculate stop loss and take profit with ATR or percentage fallback.
    
    Args:
        symbol: Trading symbol
        entry: Entry price
        side: "BUY" or "SELL"
        atr: ATR value (optional)
        rr: Risk-reward ratio (default 1.88)
        pct_sl: Percentage stop loss fallback (default 2%)
        atr_multiplier: ATR multiplier for risk calculation (default 1.5)
        
    Returns:
        Tuple of (sl, tp, metadata)
    """
    # Validate inputs
    if entry <= 0:
        raise ValueError(f"Invalid entry price: {entry}")
    
    if side not in ["BUY", "SELL"]:
        raise ValueError(f"Invalid side: {side}")
    
    if rr <= 0:
        raise ValueError(f"Invalid risk-reward ratio: {rr}")
    
    # Calculate risk amount
    if atr and atr > 0:
        # Use ATR-based risk
        risk = atr_multiplier * atr
        mode = "atr"
        risk_source = f"atr*{atr_multiplier}"
    else:
        # Use percentage-based risk
        risk = pct_sl * entry
        mode = "pct"
        risk_source = f"{pct_sl*100:.1f}%"
    
    # Calculate SL and TP based on side
    if side == "BUY":
        sl = entry - risk
        tp = entry + (rr * risk)
    else:  # SELL
        sl = entry + risk
        tp = entry - (rr * risk)
    
    # Validate results
    if side == "BUY":
        if sl <= 0 or tp <= entry:
            raise ValueError(f"Invalid BUY SL/TP: sl={sl}, tp={tp}, entry={entry}")
    else:
        if sl <= entry or tp <= 0:
            raise ValueError(f"Invalid SELL SL/TP: sl={sl}, tp={tp}, entry={entry}")
    
    # Create metadata
    metadata = {
        "mode": mode,
        "risk": risk,
        "risk_source": risk_source,
        "atr": atr,
        "atr_multiplier": atr_multiplier if mode == "atr" else None,
        "pct_sl": pct_sl if mode == "pct" else None,
        "rr": rr,
        "side": side
    }
    
    logger.debug(
        f"SL/TP calculated for {symbol} {side}: entry=${entry:.4f}, "
        f"sl=${sl:.4f}, tp=${tp:.4f}, mode={mode}, risk=${risk:.4f}"
    )
    
    return sl, tp, metadata


def calculate_risk_amount(
    entry: float,
    sl: float,
    side: str
) -> float:
    """
    Calculate risk amount from entry and stop loss.
    
    Args:
        entry: Entry price
        sl: Stop loss price
        side: "BUY" or "SELL"
        
    Returns:
        Risk amount per unit
    """
    if side == "BUY":
        return entry - sl
    else:  # SELL
        return sl - entry


def calculate_risk_reward_ratio(
    entry: float,
    sl: float,
    tp: float,
    side: str
) -> float:
    """
    Calculate risk-reward ratio from entry, SL, and TP.
    
    Args:
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        side: "BUY" or "SELL"
        
    Returns:
        Risk-reward ratio
    """
    risk = calculate_risk_amount(entry, sl, side)
    
    if side == "BUY":
        reward = tp - entry
    else:  # SELL
        reward = entry - tp
    
    if risk <= 0:
        return 0.0
    
    return reward / risk


def validate_sl_tp(
    entry: float,
    sl: float,
    tp: float,
    side: str,
    min_rr: float = 1.0
) -> bool:
    """
    Validate that SL/TP levels are reasonable.
    
    Args:
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        side: "BUY" or "SELL"
        min_rr: Minimum risk-reward ratio
        
    Returns:
        True if SL/TP is valid
    """
    try:
        # Check basic price relationships
        if side == "BUY":
            if sl >= entry or tp <= entry:
                return False
        else:  # SELL
            if sl <= entry or tp >= entry:
                return False
        
        # Check risk-reward ratio
        rr = calculate_risk_reward_ratio(entry, sl, tp, side)
        if rr < min_rr:
            return False
        
        # Check that prices are positive
        if entry <= 0 or sl <= 0 or tp <= 0:
            return False
        
        return True
        
    except Exception:
        return False


def get_sl_tp_summary(sl: float, tp: float, metadata: Dict[str, any]) -> str:
    """
    Get a summary string for SL/TP logging.
    
    Args:
        sl: Stop loss price
        tp: Take profit price
        metadata: SL/TP metadata
        
    Returns:
        Summary string for logging
    """
    mode = metadata.get("mode", "unknown")
    rr = metadata.get("rr", 0.0)
    atr = metadata.get("atr")
    
    if mode == "atr" and atr:
        return f"sl_tp_src=atr, rr={rr:.2f}, atr={atr:.4f}"
    else:
        return f"sl_tp_src=pct, rr={rr:.2f}"


def emergency_sl_tp_fallback(
    symbol: str,
    entry: float,
    side: str
) -> Tuple[float, float, Dict[str, any]]:
    """
    Emergency fallback SL/TP calculation when normal calculation fails.
    
    Args:
        symbol: Trading symbol
        entry: Entry price
        side: "BUY" or "SELL"
        
    Returns:
        Tuple of (sl, tp, metadata)
    """
    logger.warning(f"Using emergency SL/TP fallback for {symbol}")
    
    # Use very conservative 1% stop loss
    emergency_pct = 0.01
    emergency_rr = 1.5
    
    return sl_tp_defaults(
        symbol=symbol,
        entry=entry,
        side=side,
        atr=None,
        rr=emergency_rr,
        pct_sl=emergency_pct
    )

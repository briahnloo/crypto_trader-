"""
Risk-based position sizing for crypto trading bot.

This module calculates position sizes based on risk management principles,
considering both risk budget and maximum notional exposure.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)


def size_for_risk(
    equity: float,
    entry: float,
    sl: float,
    max_notional_frac: float = 0.01,
    risk_frac: float = 0.0025
) -> float:
    """
    Calculate position size based on risk management.
    
    Args:
        equity: Total portfolio equity
        entry: Entry price
        sl: Stop loss price
        max_notional_frac: Maximum fraction of equity for notional exposure (default 1%)
        risk_frac: Maximum fraction of equity to risk (default 0.25%)
        
    Returns:
        Position size (quantity)
    """
    # Validate inputs
    if equity <= 0:
        logger.warning(f"Invalid equity: {equity}")
        return 0.0
    
    if entry <= 0:
        logger.warning(f"Invalid entry price: {entry}")
        return 0.0
    
    if sl <= 0:
        logger.warning(f"Invalid stop loss: {sl}")
        return 0.0
    
    # Calculate risk per unit
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        logger.warning(f"Invalid risk per unit: {risk_per_unit}")
        return 0.0
    
    # Calculate risk budget
    risk_budget = equity * risk_frac
    
    # Calculate quantity based on risk
    qty_by_risk = risk_budget / risk_per_unit
    
    # Calculate quantity based on maximum notional exposure
    max_notional = equity * max_notional_frac
    qty_by_cap = max_notional / entry
    
    # Take the smaller of the two (most conservative)
    qty = min(qty_by_risk, qty_by_cap)
    
    # Ensure non-negative
    qty = max(0.0, qty)
    
    logger.debug(
        f"Position sizing: equity=${equity:.2f}, entry=${entry:.4f}, sl=${sl:.4f}, "
        f"risk_per_unit=${risk_per_unit:.4f}, risk_budget=${risk_budget:.2f}, "
        f"qty_by_risk={qty_by_risk:.6f}, qty_by_cap={qty_by_cap:.6f}, final_qty={qty:.6f}"
    )
    
    return qty


def size_for_fixed_risk(
    equity: float,
    entry: float,
    sl: float,
    fixed_risk_amount: float
) -> float:
    """
    Calculate position size for a fixed risk amount.
    
    Args:
        equity: Total portfolio equity
        entry: Entry price
        sl: Stop loss price
        fixed_risk_amount: Fixed dollar amount to risk
        
    Returns:
        Position size (quantity)
    """
    if fixed_risk_amount <= 0:
        return 0.0
    
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return 0.0
    
    qty = fixed_risk_amount / risk_per_unit
    return max(0.0, qty)


def size_for_percentage_equity(
    equity: float,
    entry: float,
    equity_percentage: float = 0.01
) -> float:
    """
    Calculate position size as a percentage of equity.
    
    Args:
        equity: Total portfolio equity
        entry: Entry price
        equity_percentage: Percentage of equity to allocate (default 1%)
        
    Returns:
        Position size (quantity)
    """
    if equity_percentage <= 0 or equity_percentage > 1.0:
        return 0.0
    
    notional_amount = equity * equity_percentage
    qty = notional_amount / entry
    
    return max(0.0, qty)


def calculate_position_metrics(
    qty: float,
    entry: float,
    sl: float,
    tp: float,
    side: str
) -> dict:
    """
    Calculate position metrics for logging and analysis.
    
    Args:
        qty: Position quantity
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        side: "BUY" or "SELL"
        
    Returns:
        Dictionary with position metrics
    """
    notional = qty * entry
    
    # Calculate risk and reward
    if side == "BUY":
        risk_per_unit = entry - sl
        reward_per_unit = tp - entry
    else:  # SELL
        risk_per_unit = sl - entry
        reward_per_unit = entry - tp
    
    total_risk = qty * risk_per_unit
    total_reward = qty * reward_per_unit
    
    # Calculate risk-reward ratio
    rr_ratio = total_reward / total_risk if total_risk > 0 else 0.0
    
    return {
        "quantity": qty,
        "notional": notional,
        "risk_per_unit": risk_per_unit,
        "reward_per_unit": reward_per_unit,
        "total_risk": total_risk,
        "total_reward": total_reward,
        "risk_reward_ratio": rr_ratio,
        "side": side
    }


def validate_position_size(
    qty: float,
    entry: float,
    equity: float,
    max_position_frac: float = 0.1
) -> bool:
    """
    Validate that position size is reasonable.
    
    Args:
        qty: Position quantity
        entry: Entry price
        equity: Total portfolio equity
        max_position_frac: Maximum fraction of equity for single position
        
    Returns:
        True if position size is valid
    """
    if qty <= 0:
        return False
    
    notional = qty * entry
    max_notional = equity * max_position_frac
    
    if notional > max_notional:
        logger.warning(
            f"Position size too large: notional=${notional:.2f} > max=${max_notional:.2f} "
            f"({max_position_frac*100:.1f}% of equity)"
        )
        return False
    
    return True


def get_position_size_summary(
    qty: float,
    entry: float,
    sl: float,
    tp: float,
    side: str,
    equity: float
) -> str:
    """
    Get a summary string for position size logging.
    
    Args:
        qty: Position quantity
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        side: "BUY" or "SELL"
        equity: Total portfolio equity
        
    Returns:
        Summary string for logging
    """
    metrics = calculate_position_metrics(qty, entry, sl, tp, side)
    
    notional_pct = (metrics["notional"] / equity) * 100
    risk_pct = (metrics["total_risk"] / equity) * 100
    
    return (
        f"qty={qty:.6f} notional=${metrics['notional']:.2f} "
        f"({notional_pct:.2f}% equity) risk=${metrics['total_risk']:.2f} "
        f"({risk_pct:.3f}% equity) rr={metrics['risk_reward_ratio']:.2f}"
    )

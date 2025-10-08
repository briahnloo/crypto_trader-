"""
Fee and Slippage Calculator for realistic P&L modeling.

This module calculates:
1. Exchange fees (maker/taker basis points)
2. Market impact slippage based on order size
3. Effective fill prices including slippage

Configuration is loaded from config/fees.yaml as single source of truth.
"""

from decimal import Decimal
from typing import Dict, Optional, Tuple
import logging
import yaml
from pathlib import Path

from ..core.money import to_dec, ZERO, ONE, quantize_price

logger = logging.getLogger(__name__)


# Global config loaded once
_FEES_CONFIG = None


def _load_fees_config() -> Dict:
    """Load fees configuration from config/fees.yaml."""
    global _FEES_CONFIG
    
    if _FEES_CONFIG is not None:
        return _FEES_CONFIG
    
    # Try to find fees.yaml in config directory
    config_paths = [
        Path("config/fees.yaml"),
        Path(__file__).parent.parent.parent.parent / "config" / "fees.yaml",
        Path("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/config/fees.yaml")
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, 'r') as f:
                _FEES_CONFIG = yaml.safe_load(f)
                logger.info(f"Loaded fees config from {config_path}")
                return _FEES_CONFIG
    
    # Fallback to hardcoded defaults if file not found
    logger.warning("fees.yaml not found, using hardcoded defaults")
    _FEES_CONFIG = {
        "venue_defaults": {
            "maker_bps": 2.0,
            "taker_bps": 5.0
        },
        "slippage": {
            "base_bps": 5.0,
            "cap_bps": 8.0,
            "notional_scale": 50000
        }
    }
    return _FEES_CONFIG


def get_effective_fees(venue: str = "default") -> Dict[str, float]:
    """
    Get the effective fee schedule being used.
    
    Args:
        venue: Venue name (currently uses defaults for all venues)
        
    Returns:
        Dictionary with maker_bps and taker_bps
    """
    config = _load_fees_config()
    venue_defaults = config.get("venue_defaults", {})
    
    return {
        "maker_bps": float(venue_defaults.get("maker_bps", 2.0)),
        "taker_bps": float(venue_defaults.get("taker_bps", 5.0))
    }


class FeeSlippageCalculator:
    """
    Calculates fees and slippage for realistic trade execution modeling.
    """
    
    def __init__(self, venue: str = "default", config: Optional[Dict] = None):
        """
        Initialize fee/slippage calculator.
        
        Args:
            venue: Exchange venue name
            config: Optional configuration override
        """
        self.venue = venue
        self.config = config or {}
        
        # Load fees from config/fees.yaml
        fees_config = _load_fees_config()
        venue_defaults = fees_config.get("venue_defaults", {})
        slippage_config = fees_config.get("slippage", {})
        
        # Get fee schedule (currently using venue_defaults for all venues)
        self.maker_fee_bps = to_dec(str(venue_defaults.get("maker_bps", 2.0)))
        self.taker_fee_bps = to_dec(str(venue_defaults.get("taker_bps", 5.0)))
        
        # Slippage model parameters from config
        self.slippage_base_notional = to_dec(str(slippage_config.get("notional_scale", 50000)))
        self.slippage_scale_factor = to_dec(str(slippage_config.get("base_bps", 5)))
        self.slippage_max_bps = to_dec(str(slippage_config.get("cap_bps", 8)))
        
        logger.info(
            f"FeeSlippageCalculator initialized: venue={venue}, "
            f"maker_fee={float(self.maker_fee_bps)}bps, taker_fee={float(self.taker_fee_bps)}bps, "
            f"slippage_model: max((notional/${float(self.slippage_base_notional)})*{float(self.slippage_scale_factor)}bps, 0) "
            f"capped at {float(self.slippage_max_bps)}bps"
        )
    
    def calculate_slippage_bps(self, notional: Decimal, is_market_order: bool = True) -> Decimal:
        """
        Calculate slippage in basis points based on order size.
        
        Market Impact Model:
        slip_bps = min((notional / $50k) * 5bps, 8bps)
        
        Limit orders: 0 bps (assumes patient execution)
        Market orders: Use model above
        
        Args:
            notional: Order notional value in USD
            is_market_order: Whether this is a market order
            
        Returns:
            Slippage in basis points as Decimal
        """
        if not is_market_order:
            # Limit orders - assume no slippage (patient execution)
            return ZERO
        
        # Market orders - calculate slippage based on size
        notional_dec = to_dec(notional)
        
        # slippage_bps = (notional / base_notional) * scale_factor
        slippage_ratio = notional_dec / self.slippage_base_notional
        slippage_bps = slippage_ratio * self.slippage_scale_factor
        
        # Cap at max slippage
        slippage_bps = min(slippage_bps, self.slippage_max_bps)
        
        logger.debug(
            f"Slippage calc: notional=${float(notional_dec):.2f}, "
            f"ratio={float(slippage_ratio):.4f}, "
            f"slip={float(slippage_bps):.2f}bps (capped at {float(self.slippage_max_bps)}bps)"
        )
        
        return slippage_bps
    
    def calculate_effective_fill_price(
        self,
        mark_price: Decimal,
        side: str,
        slippage_bps: Decimal
    ) -> Decimal:
        """
        Calculate effective fill price including slippage.
        
        For BUY: effective_fill_price = mark * (1 + slip_bps/10_000)
        For SELL: effective_fill_price = mark * (1 - slip_bps/10_000)
        
        Args:
            mark_price: Mark price
            side: Order side ("BUY" or "SELL")
            slippage_bps: Slippage in basis points
            
        Returns:
            Effective fill price as Decimal
        """
        mark_dec = to_dec(mark_price)
        slip_multiplier = slippage_bps / to_dec("10000")
        
        if side.upper() in ["BUY", "LONG"]:
            # Buying - pay slippage (worse price)
            effective_price = mark_dec * (ONE + slip_multiplier)
        else:
            # Selling - lose to slippage (worse price)
            effective_price = mark_dec * (ONE - slip_multiplier)
        
        logger.debug(
            f"Effective fill: mark=${float(mark_dec):.4f}, side={side}, "
            f"slip={float(slippage_bps):.2f}bps, "
            f"effective=${float(effective_price):.4f}"
        )
        
        return effective_price
    
    def calculate_fees(
        self,
        notional: Decimal,
        is_maker: bool = False
    ) -> Decimal:
        """
        Calculate trading fees.
        
        fee = notional * fee_bps / 10_000
        
        Args:
            notional: Order notional value
            is_maker: Whether this is a maker order (otherwise taker)
            
        Returns:
            Fee amount as Decimal
        """
        notional_dec = to_dec(notional)
        
        if is_maker:
            fee_bps = self.maker_fee_bps
        else:
            fee_bps = self.taker_fee_bps
        
        fee = notional_dec * (fee_bps / to_dec("10000"))
        
        logger.debug(
            f"Fee calc: notional=${float(notional_dec):.2f}, "
            f"{'maker' if is_maker else 'taker'}={float(fee_bps):.2f}bps, "
            f"fee=${float(fee):.4f}"
        )
        
        return fee
    
    def calculate_fill_with_costs(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        mark_price: Decimal,
        is_market_order: bool = True,
        is_maker: bool = False
    ) -> Dict[str, Decimal]:
        """
        Calculate fill details including fees and slippage.
        
        Args:
            symbol: Trading symbol
            side: Order side ("BUY" or "SELL")
            quantity: Order quantity
            mark_price: Mark price before slippage
            is_market_order: Whether this is a market order
            is_maker: Whether this is a maker order
            
        Returns:
            Dictionary with fill details:
            - mark_price: Original mark price
            - slippage_bps: Slippage in basis points
            - effective_fill_price: Price after slippage
            - notional_before_fees: Quantity * effective_fill_price
            - fees: Trading fees
            - total_cost: Total cost (notional + fees for buy, notional - fees for sell)
            - slippage_cost: Dollar cost of slippage
        """
        qty_dec = to_dec(quantity)
        mark_dec = to_dec(mark_price)
        
        # Calculate slippage
        notional_at_mark = qty_dec * mark_dec
        slippage_bps = self.calculate_slippage_bps(notional_at_mark, is_market_order)
        
        # Calculate effective fill price
        effective_fill_price = self.calculate_effective_fill_price(mark_dec, side, slippage_bps)
        
        # Quantize fill price to exchange tick
        effective_fill_price = quantize_price(effective_fill_price, symbol)
        
        # Calculate notional at effective price
        notional = qty_dec * effective_fill_price
        
        # Calculate fees
        fees = self.calculate_fees(notional, is_maker)
        
        # Calculate slippage cost
        slippage_cost = abs(notional - notional_at_mark)
        
        # Calculate total cost (direction-dependent)
        if side.upper() in ["BUY", "LONG"]:
            total_cost = notional + fees  # Buying: pay notional + fees
        else:
            total_cost = notional - fees  # Selling: receive notional - fees
        
        result = {
            "mark_price": mark_dec,
            "slippage_bps": slippage_bps,
            "effective_fill_price": effective_fill_price,
            "notional_before_fees": notional,
            "fees": fees,
            "total_cost": total_cost,
            "slippage_cost": slippage_cost
        }
        
        logger.info(
            f"FILL_COSTS: {symbol} {side} {float(qty_dec):.6f} @ mark=${float(mark_dec):.4f} → "
            f"fill=${float(effective_fill_price):.4f} (slip={float(slippage_bps):.2f}bps/${float(slippage_cost):.4f}), "
            f"notional=${float(notional):.2f}, fees=${float(fees):.4f}, total=${float(total_cost):.2f}"
        )
        
        return result


def calculate_fill_with_costs(
    symbol: str,
    side: str,
    quantity: float,
    mark_price: float,
    venue: str = "default",
    is_market_order: bool = True,
    is_maker: bool = False,
    config: Optional[Dict] = None
) -> Dict[str, float]:
    """
    Convenience function for calculating fill costs.
    
    Args:
        symbol: Trading symbol
        side: Order side
        quantity: Order quantity
        mark_price: Mark price
        venue: Exchange venue
        is_market_order: Whether this is a market order
        is_maker: Whether this is a maker order
        config: Optional configuration
        
    Returns:
        Dictionary with fill costs (all values as float)
    """
    calculator = FeeSlippageCalculator(venue, config)
    result = calculator.calculate_fill_with_costs(
        symbol=symbol,
        side=side,
        quantity=to_dec(quantity),
        mark_price=to_dec(mark_price),
        is_market_order=is_market_order,
        is_maker=is_maker
    )
    
    # Convert Decimals to floats
    return {k: float(v) for k, v in result.items()}


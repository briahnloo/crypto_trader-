"""
Pricing snapshot system for per-cycle price consistency.

This module provides a PricingSnapshot class that ensures all pricing within a trading cycle
uses the same frozen snapshot of prices, preventing equity Δ and decision drift.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import time

from .logging_utils import LoggerMixin


@dataclass
class PriceData:
    """Individual price data for a symbol."""
    price: float
    source: str
    timestamp: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    provenance: Optional[Dict[str, Any]] = None  # Locked valuation source {venue, price_type}


@dataclass
class PricingSnapshot(LoggerMixin):
    """
    Frozen pricing snapshot for a trading cycle.
    
    All pricing within a cycle uses this single snapshot to ensure consistency
    and prevent equity Δ and decision drift.
    """
    id: int
    ts: datetime
    by_symbol: Dict[str, PriceData] = field(default_factory=dict)
    
    # Tracking for logging
    hits: int = 0
    misses: int = 0
    
    # Provenance locking: symbol → {venue, price_type, locked_at}
    locked_provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Hit tracking for debouncing: symbol → {last_log_time, hit_count}
    hit_tracking: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize logger after dataclass creation."""
        super().__init__()
    
    def get_mark_price(self, symbol: str, debounce_ms: int = 300) -> Optional[float]:
        """
        Get mark price for a symbol from the snapshot with debounced logging.
        
        Args:
            symbol: Trading symbol
            debounce_ms: Debounce period for PRICING_SNAPSHOT_HIT logs (milliseconds)
            
        Returns:
            Mark price or None if not found
        """
        price_data = self.by_symbol.get(symbol)
        if price_data:
            self.hits += 1
            self._log_snapshot_hit_debounced(symbol, price_data.price, debounce_ms)
            return price_data.price
        else:
            self.misses += 1
            return None
    
    def _log_snapshot_hit_debounced(self, symbol: str, price: float, debounce_ms: int):
        """
        Log PRICING_SNAPSHOT_HIT with debouncing to reduce log spam.
        
        Only logs at DEBUG level:
        - First hit for each symbol in snapshot lifetime
        - Cache misses (logged separately)
        
        Args:
            symbol: Trading symbol
            price: Price being accessed
            debounce_ms: Minimum milliseconds between logs for same symbol (ignored, kept for compatibility)
        """
        if symbol not in self.hit_tracking:
            # First hit for this symbol - log once at DEBUG
            self.hit_tracking[symbol] = {
                "last_log_time": time.time() * 1000,
                "hit_count": 1,
                "price": price
            }
            self.logger.debug(f"PRICING_SNAPSHOT_HIT: {symbol} = {price:.4f} (snapshot_id={self.id}, first_hit)")
        else:
            # Subsequent hits - just increment counter, no logging (reduce noise)
            tracking = self.hit_tracking[symbol]
            tracking["hit_count"] += 1
            # Don't log subsequent hits to reduce noise
    
    def lock_provenance(self, symbol: str, venue: str, price_type: str):
        """
        Lock the valuation provenance for a symbol.
        
        This should be called when first entering a position to ensure consistent
        valuation throughout the position lifecycle.
        
        Args:
            symbol: Trading symbol
            venue: Venue name (e.g., 'coinbase', 'binance')
            price_type: Price type (e.g., 'bid_ask_mid', 'last', 'ohlcv')
        """
        self.locked_provenance[symbol] = {
            "venue": venue,
            "price_type": price_type,
            "locked_at": datetime.now().isoformat()
        }
        self.logger.info(f"PROVENANCE_LOCKED: {symbol} → {venue}_{price_type}")
    
    def get_locked_provenance(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get the locked provenance for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Provenance dict or None if not locked
        """
        return self.locked_provenance.get(symbol)
    
    def get_entry_price(self, symbol: str) -> Optional[float]:
        """
        Get entry price for a symbol from the snapshot.
        Uses bid/ask mid if available, otherwise falls back to price.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Entry price or None if not found
        """
        price_data = self.by_symbol.get(symbol)
        if price_data:
            self.hits += 1
            # Entry price source order: bid/ask mid → price
            if price_data.mid is not None:
                return price_data.mid
            else:
                return price_data.price
        else:
            self.misses += 1
            return None
    
    def get_exit_value(self, symbol: str, side: str) -> Optional[float]:
        """
        Get exit value for a symbol from the snapshot.
        Uses bid for long positions, ask for short positions.
        
        Args:
            symbol: Trading symbol
            side: Position side ('long', 'buy', 'sell', 'short')
            
        Returns:
            Exit value or None if not found
        """
        price_data = self.by_symbol.get(symbol)
        if not price_data:
            self.misses += 1
            return None
        
        self.hits += 1
        
        # Determine if long or short position
        is_long = side.lower() in ['long', 'buy']
        
        if is_long:
            # Long position - use bid price (what you can sell at)
            if price_data.bid is not None:
                return price_data.bid
            elif price_data.mid is not None:
                return price_data.mid
            else:
                return price_data.price
        else:
            # Short position - use ask price (what you can buy back at)
            if price_data.ask is not None:
                return price_data.ask
            elif price_data.mid is not None:
                return price_data.mid
            else:
                return price_data.price
    
    def get_price_data(self, symbol: str) -> Optional[PriceData]:
        """
        Get full price data for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            PriceData object or None if not found
        """
        return self.by_symbol.get(symbol)
    
    def add_price_data(self, symbol: str, price_data: PriceData) -> None:
        """
        Add price data for a symbol to the snapshot.
        
        Args:
            symbol: Trading symbol
            price_data: Price data to add
        """
        self.by_symbol[symbol] = price_data
    
    def get_staleness_ms(self) -> int:
        """
        Get staleness of the snapshot in milliseconds.
        
        Returns:
            Staleness in milliseconds
        """
        now = datetime.now()
        delta = now - self.ts
        return int(delta.total_seconds() * 1000)
    
    def get_pricing_context(self) -> Dict[str, Any]:
        """
        Get pricing context for logging.
        
        Returns:
            Dictionary with pricing context information
        """
        return {
            "id": self.id,
            "hits": self.hits,
            "misses": self.misses,
            "staleness_ms": self.get_staleness_ms(),
            "symbol_count": len(self.by_symbol)
        }
    
    def log_pricing_context(self) -> None:
        """Log the pricing context for this cycle."""
        context = self.get_pricing_context()
        self.logger.info(f"PRICING_CONTEXT: {context}")


class PricingSnapshotManager(LoggerMixin):
    """
    Manager for pricing snapshots across trading cycles.
    """
    
    def __init__(self):
        """Initialize the pricing snapshot manager."""
        super().__init__()
        self._current_snapshot: Optional[PricingSnapshot] = None
        self._snapshot_created: bool = False
        self._fresh_price_fetching_disabled: bool = False
    
    def create_snapshot(self, cycle_id: int, symbols: list[str], data_engine) -> PricingSnapshot:
        """
        Create a new pricing snapshot for a cycle with resilient data fetching.
        
        Continues with other symbols even if some fail. Uses stale data when fresh unavailable.
        All prices share the same snapshot_id to avoid mixed marks.
        
        Args:
            cycle_id: Current cycle ID
            symbols: List of symbols to include in snapshot
            data_engine: Data engine for fetching prices
            
        Returns:
            New PricingSnapshot instance
        """
        if self._snapshot_created:
            raise RuntimeError("Pricing snapshot already created for this cycle - cannot create another")
        
        self.logger.info(f"Creating pricing snapshot {cycle_id} for {len(symbols)} symbols")
        
        snapshot = PricingSnapshot(
            id=cycle_id,
            ts=datetime.now()
        )
        
        successful_fetches = 0
        stale_fetches = 0
        failed_fetches = 0
        
        # Fetch prices for all symbols - continue on failures
        for symbol in symbols:
            try:
                ticker_data = data_engine.get_ticker(symbol)
                
                if ticker_data and ticker_data.get("price", 0) > 0:
                    # Check if data is stale
                    is_stale = ticker_data.get("is_stale", False)
                    stale_reason = ticker_data.get("stale_reason", "")
                    
                    # Handle provenance as either string or dict
                    provenance = ticker_data.get("provenance", "unknown")
                    if isinstance(provenance, dict):
                        source = provenance.get("source", "unknown")
                    else:
                        source = str(provenance)
                    
                    # Mark source as stale if needed
                    if is_stale:
                        source = f"{source}_STALE"
                        stale_fetches += 1
                    else:
                        successful_fetches += 1
                    
                    price_data = PriceData(
                        price=ticker_data["price"],
                        source=source,
                        timestamp=ticker_data.get("timestamp", datetime.now().isoformat()),
                        bid=ticker_data.get("bid"),
                        ask=ticker_data.get("ask"),
                        mid=ticker_data.get("mid")
                    )
                    snapshot.add_price_data(symbol, price_data)
                    
                    if is_stale:
                        self.logger.info(f"Added {symbol} with STALE data: price={price_data.price}, reason={stale_reason}")
                    else:
                        self.logger.debug(f"Added {symbol}: price={price_data.price}, bid={price_data.bid}, ask={price_data.ask}")
                else:
                    failed_fetches += 1
                    self.logger.warning(f"DATA_SKIP: No valid price data for {symbol} - continuing with other symbols")
                    
            except Exception as e:
                failed_fetches += 1
                self.logger.warning(f"DATA_SKIP: Error fetching price for {symbol}: {e} - continuing with other symbols")
        
        self._current_snapshot = snapshot
        self._snapshot_created = True
        self._fresh_price_fetching_disabled = True  # Disable fresh price fetching after snapshot creation
        
        # Log pricing context with staleness info
        snapshot.log_pricing_context()
        
        # Log summary of fetch results
        total_symbols = len(symbols)
        self.logger.info(
            f"SNAPSHOT_{cycle_id}_COMPLETE: {successful_fetches} fresh, "
            f"{stale_fetches} stale, {failed_fetches} failed out of {total_symbols} symbols - "
            f"snapshot created with {len(snapshot.by_symbol)} symbols"
        )
        
        if failed_fetches > 0:
            self.logger.warning(
                f"SNAPSHOT_{cycle_id}_PARTIAL: {failed_fetches}/{total_symbols} symbols unavailable - "
                f"trading continues with {len(snapshot.by_symbol)} symbols"
            )
        
        return snapshot
    
    def get_current_snapshot(self) -> Optional[PricingSnapshot]:
        """
        Get the current pricing snapshot.
        
        Returns:
            Current snapshot or None if not created
        """
        return self._current_snapshot
    
    def clear_snapshot(self) -> None:
        """Clear the current snapshot (call at cycle end)."""
        self._current_snapshot = None
        self._snapshot_created = False
        self._fresh_price_fetching_disabled = False  # Re-enable fresh price fetching
        self.logger.debug("Pricing snapshot cleared")
    
    def is_snapshot_created(self) -> bool:
        """
        Check if a snapshot has been created for the current cycle.
        
        Returns:
            True if snapshot exists, False otherwise
        """
        return self._snapshot_created
    
    def is_fresh_price_fetching_disabled(self) -> bool:
        """
        Check if fresh price fetching is disabled (after snapshot creation).
        
        Returns:
            True if fresh price fetching is disabled, False otherwise
        """
        return self._fresh_price_fetching_disabled


# Global pricing snapshot manager
_pricing_snapshot_manager: Optional[PricingSnapshotManager] = None


def get_pricing_snapshot_manager() -> PricingSnapshotManager:
    """Get the global pricing snapshot manager."""
    global _pricing_snapshot_manager
    if _pricing_snapshot_manager is None:
        _pricing_snapshot_manager = PricingSnapshotManager()
    return _pricing_snapshot_manager


def create_pricing_snapshot(cycle_id: int, symbols: list[str], data_engine) -> PricingSnapshot:
    """
    Create a new pricing snapshot for a cycle.
    
    Args:
        cycle_id: Current cycle ID
        symbols: List of symbols to include in snapshot
        data_engine: Data engine for fetching prices
        
    Returns:
        New PricingSnapshot instance
    """
    manager = get_pricing_snapshot_manager()
    return manager.create_snapshot(cycle_id, symbols, data_engine)


def get_current_pricing_snapshot() -> Optional[PricingSnapshot]:
    """
    Get the current pricing snapshot.
    
    Returns:
        Current snapshot or None if not created
    """
    manager = get_pricing_snapshot_manager()
    return manager.get_current_snapshot()


def clear_pricing_snapshot() -> None:
    """Clear the current pricing snapshot."""
    manager = get_pricing_snapshot_manager()
    manager.clear_snapshot()


def is_fresh_price_fetching_disabled() -> bool:
    """
    Check if fresh price fetching is disabled (after snapshot creation).
    
    Returns:
        True if fresh price fetching is disabled, False otherwise
    """
    manager = get_pricing_snapshot_manager()
    return manager.is_fresh_price_fetching_disabled()

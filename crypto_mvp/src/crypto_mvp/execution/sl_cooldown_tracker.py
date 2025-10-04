"""
Stop-loss cooldown tracker for preventing immediate re-entry after SL hits.

This module tracks stop-loss events and enforces cooldown periods to prevent
immediate re-entry on the same symbol after a stop-loss is triggered.
"""

import time
from typing import Dict, Optional, Set, Any
from datetime import datetime, timedelta
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class StopLossCooldownTracker(LoggerMixin):
    """
    Tracks stop-loss events and enforces cooldown periods.
    
    Features:
    - Track stop-loss events by symbol and timestamp
    - Enforce configurable cooldown periods
    - Check if symbol is in cooldown
    - Clean up expired cooldowns
    - Comprehensive logging of cooldown events
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the stop-loss cooldown tracker.
        
        Args:
            config: Configuration dictionary with risk settings
        """
        super().__init__()
        self.config = config
        
        # Risk settings
        risk_config = config.get("risk", {})
        self.cooldown_seconds = risk_config.get("cooldown_after_sl_seconds", 180)  # 5 minutes default
        
        # Track cooldowns by symbol -> timestamp
        self.sl_cooldowns: Dict[str, float] = {}
        
        self.logger.info(f"StopLossCooldownTracker initialized: cooldown_seconds={self.cooldown_seconds}")
    
    def record_stop_loss(self, symbol: str) -> None:
        """
        Record a stop-loss event for a symbol.
        
        Args:
            symbol: Trading symbol that hit stop-loss
        """
        current_time = time.time()
        self.sl_cooldowns[symbol] = current_time
        
        self.logger.warning(
            f"STOP_LOSS_COOLDOWN: {symbol} entered {self.cooldown_seconds}s cooldown "
            f"(until {datetime.fromtimestamp(current_time + self.cooldown_seconds).strftime('%H:%M:%S')})"
        )
    
    def is_in_cooldown(self, symbol: str) -> bool:
        """
        Check if a symbol is currently in stop-loss cooldown.
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            True if symbol is in cooldown, False otherwise
        """
        if symbol not in self.sl_cooldowns:
            return False
        
        current_time = time.time()
        cooldown_start = self.sl_cooldowns[symbol]
        cooldown_elapsed = current_time - cooldown_start
        
        if cooldown_elapsed >= self.cooldown_seconds:
            # Cooldown expired, remove from tracking
            del self.sl_cooldowns[symbol]
            self.logger.info(f"COOLDOWN_EXPIRED: {symbol} cooldown period ended")
            return False
        
        # Still in cooldown
        remaining_seconds = self.cooldown_seconds - cooldown_elapsed
        self.logger.debug(f"COOLDOWN_ACTIVE: {symbol} has {remaining_seconds:.0f}s remaining")
        return True
    
    def get_cooldown_status(self, symbol: str) -> Optional[Dict[str, any]]:
        """
        Get detailed cooldown status for a symbol.
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            Dictionary with cooldown details or None if not in cooldown
        """
        if symbol not in self.sl_cooldowns:
            return None
        
        current_time = time.time()
        cooldown_start = self.sl_cooldowns[symbol]
        cooldown_elapsed = current_time - cooldown_start
        
        if cooldown_elapsed >= self.cooldown_seconds:
            # Cooldown expired
            del self.sl_cooldowns[symbol]
            return None
        
        remaining_seconds = self.cooldown_seconds - cooldown_elapsed
        cooldown_end = datetime.fromtimestamp(cooldown_start + self.cooldown_seconds)
        
        return {
            "symbol": symbol,
            "cooldown_start": datetime.fromtimestamp(cooldown_start),
            "cooldown_end": cooldown_end,
            "elapsed_seconds": cooldown_elapsed,
            "remaining_seconds": remaining_seconds,
            "cooldown_seconds": self.cooldown_seconds
        }
    
    def cleanup_expired_cooldowns(self) -> int:
        """
        Clean up expired cooldowns.
        
        Returns:
            Number of expired cooldowns removed
        """
        current_time = time.time()
        expired_symbols = []
        
        for symbol, cooldown_start in self.sl_cooldowns.items():
            if current_time - cooldown_start >= self.cooldown_seconds:
                expired_symbols.append(symbol)
        
        for symbol in expired_symbols:
            del self.sl_cooldowns[symbol]
            self.logger.info(f"COOLDOWN_CLEANUP: {symbol} expired cooldown removed")
        
        return len(expired_symbols)
    
    def get_active_cooldowns(self) -> Dict[str, Dict[str, any]]:
        """
        Get all active cooldowns with their status.
        
        Returns:
            Dictionary of active cooldowns by symbol
        """
        active_cooldowns = {}
        current_time = time.time()
        
        for symbol, cooldown_start in list(self.sl_cooldowns.items()):
            cooldown_elapsed = current_time - cooldown_start
            
            if cooldown_elapsed >= self.cooldown_seconds:
                # Expired, remove it
                del self.sl_cooldowns[symbol]
                continue
            
            remaining_seconds = self.cooldown_seconds - cooldown_elapsed
            cooldown_end = datetime.fromtimestamp(cooldown_start + self.cooldown_seconds)
            
            active_cooldowns[symbol] = {
                "cooldown_start": datetime.fromtimestamp(cooldown_start),
                "cooldown_end": cooldown_end,
                "elapsed_seconds": cooldown_elapsed,
                "remaining_seconds": remaining_seconds,
                "cooldown_seconds": self.cooldown_seconds
            }
        
        return active_cooldowns
    
    def get_cooldown_summary(self) -> Dict[str, any]:
        """
        Get summary of cooldown tracker status.
        
        Returns:
            Dictionary with cooldown tracker summary
        """
        active_cooldowns = self.get_active_cooldowns()
        
        return {
            "cooldown_seconds": self.cooldown_seconds,
            "active_cooldowns_count": len(active_cooldowns),
            "active_cooldowns": active_cooldowns,
            "total_tracked": len(self.sl_cooldowns)
        }
    
    def should_skip_trade(self, symbol: str) -> tuple[bool, str, Dict[str, any]]:
        """
        Check if trade should be skipped due to cooldown.
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            Tuple of (should_skip, reason, details_dict)
        """
        if self.is_in_cooldown(symbol):
            cooldown_status = self.get_cooldown_status(symbol)
            if cooldown_status:
                reason = "sl_cooldown_active"
                details = {
                    "symbol": symbol,
                    "remaining_seconds": cooldown_status["remaining_seconds"],
                    "cooldown_end": cooldown_status["cooldown_end"],
                    "cooldown_seconds": self.cooldown_seconds
                }
                
                self.logger.info(
                    f"REJECTED: {symbol} (reason={reason}, "
                    f"remaining={cooldown_status['remaining_seconds']:.0f}s)"
                )
                
                return True, reason, details
        
        return False, "no_cooldown", {"symbol": symbol}
    
    def reset_cooldowns(self) -> None:
        """Reset all cooldowns (for testing or manual override)."""
        cleared_count = len(self.sl_cooldowns)
        self.sl_cooldowns.clear()
        
        if cleared_count > 0:
            self.logger.info(f"COOLDOWN_RESET: Cleared {cleared_count} active cooldowns")
    
    def update_cooldown_duration(self, new_seconds: int) -> None:
        """
        Update the cooldown duration.
        
        Args:
            new_seconds: New cooldown duration in seconds
        """
        old_seconds = self.cooldown_seconds
        self.cooldown_seconds = new_seconds
        
        self.logger.info(
            f"COOLDOWN_DURATION_UPDATED: {old_seconds}s -> {new_seconds}s"
        )

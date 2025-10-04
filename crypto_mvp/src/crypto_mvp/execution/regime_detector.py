"""
Regime detection system for market condition classification.

This module classifies market conditions as either "trend" or "range" based on:
- EMA50 > EMA200 and ADX(14) > 20 → trend
- Otherwise → range
- Missing indicators → default to range
"""

import math
from typing import Optional, Dict, Any, Tuple, Callable
import logging

from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


class RegimeDetector(LoggerMixin):
    """
    Detects market regime based on EMA and ADX indicators.
    
    Features:
    - Trend detection: EMA50 > EMA200 and ADX(14) > 20
    - Range detection: Default when trend conditions not met
    - Regime-specific thresholds: Different signal requirements per regime
    - Fail-safe design: Default to range when indicators missing
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the regime detector.
        
        Args:
            config: Configuration dictionary with regime settings
        """
        super().__init__()
        self.config = config
        
        # Regime thresholds
        signals_config = config.get("signals", {})
        regime_config = signals_config.get("regime", {})
        
        self.trend_thresholds = regime_config.get("trend", {
            "min_score": 0.50,
            "min_rr": 1.4
        })
        
        self.range_thresholds = regime_config.get("range", {
            "min_score": 0.48,
            "min_rr": 1.2
        })
        
        # Indicator parameters
        self.ema_fast_period = 50
        self.ema_slow_period = 200
        self.adx_period = 14
        self.adx_threshold = 20.0
        
        # Callbacks for indicator data
        self.get_ema_callback: Optional[Callable[[str, int], Optional[float]]] = None
        self.get_adx_callback: Optional[Callable[[str, int], Optional[float]]] = None
        
        self.logger.info(f"RegimeDetector initialized: "
                        f"trend_thresholds={self.trend_thresholds}, "
                        f"range_thresholds={self.range_thresholds}")
    
    def set_callbacks(
        self,
        get_ema_callback: Callable[[str, int], Optional[float]],
        get_adx_callback: Callable[[str, int], Optional[float]]
    ):
        """Set callback functions for indicator data."""
        self.get_ema_callback = get_ema_callback
        self.get_adx_callback = get_adx_callback
        self.logger.info("Regime detector callbacks set")
    
    def detect_regime(self, symbol: str) -> Tuple[str, Dict[str, Any]]:
        """
        Detect market regime for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Tuple of (regime, details_dict)
            - regime: "trend" or "range"
            - details_dict: Dictionary with indicator values and thresholds
        """
        # Get EMA values
        ema_fast = None
        ema_slow = None
        
        if self.get_ema_callback:
            try:
                ema_fast = self.get_ema_callback(symbol, self.ema_fast_period)
                ema_slow = self.get_ema_callback(symbol, self.ema_slow_period)
            except Exception as e:
                self.logger.warning(f"Failed to get EMA for {symbol}: {e}")
        
        # Get ADX value
        adx = None
        if self.get_adx_callback:
            try:
                adx = self.get_adx_callback(symbol, self.adx_period)
            except Exception as e:
                self.logger.warning(f"Failed to get ADX for {symbol}: {e}")
        
        # Create details dictionary
        details = {
            "symbol": symbol,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "adx": adx,
            "ema_fast_period": self.ema_fast_period,
            "ema_slow_period": self.ema_slow_period,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold
        }
        
        # Check if indicators are available
        if ema_fast is None or ema_slow is None or adx is None:
            details["reason"] = "missing_indicators"
            details["regime"] = "range"
            self.logger.info(f"REGIME: {symbol} = range (reason=missing_indicators)")
            return "range", details
        
        # Check for invalid values
        if (math.isnan(ema_fast) or math.isnan(ema_slow) or math.isnan(adx) or
            ema_fast <= 0 or ema_slow <= 0 or adx < 0):
            details["reason"] = "invalid_indicators"
            details["regime"] = "range"
            self.logger.info(f"REGIME: {symbol} = range (reason=invalid_indicators)")
            return "range", details
        
        # Determine regime based on conditions
        # Trend: EMA50 > EMA200 and ADX(14) > 20
        is_trend = (ema_fast > ema_slow) and (adx > self.adx_threshold)
        
        if is_trend:
            regime = "trend"
            reason = "ema_fast_gt_slow_and_adx_gt_threshold"
        else:
            regime = "range"
            if ema_fast <= ema_slow:
                reason = "ema_fast_le_slow"
            else:  # adx <= threshold
                reason = "adx_le_threshold"
        
        details["reason"] = reason
        details["regime"] = regime
        details["is_trend"] = is_trend
        
        self.logger.info(
            f"REGIME: {symbol} = {regime} (reason={reason}) "
            f"EMA{self.ema_fast_period}={ema_fast:.4f} EMA{self.ema_slow_period}={ema_slow:.4f} "
            f"ADX{self.adx_period}={adx:.2f}"
        )
        
        return regime, details
    
    def get_regime_thresholds(self, regime: str) -> Dict[str, float]:
        """
        Get signal thresholds for a specific regime.
        
        Args:
            regime: Market regime ("trend" or "range")
            
        Returns:
            Dictionary with min_score and min_rr thresholds
        """
        if regime == "trend":
            return self.trend_thresholds.copy()
        elif regime == "range":
            return self.range_thresholds.copy()
        else:
            # Default to range thresholds for unknown regime
            self.logger.warning(f"Unknown regime '{regime}', using range thresholds")
            return self.range_thresholds.copy()
    
    def validate_signal_for_regime(
        self,
        symbol: str,
        signal_score: float,
        risk_reward_ratio: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate a signal against regime-specific thresholds.
        
        Args:
            symbol: Trading symbol
            signal_score: Signal strength score
            risk_reward_ratio: Risk-reward ratio
            
        Returns:
            Tuple of (is_valid, reason, details_dict)
        """
        # Detect regime
        regime, regime_details = self.detect_regime(symbol)
        
        # Get regime-specific thresholds
        thresholds = self.get_regime_thresholds(regime)
        min_score = thresholds["min_score"]
        min_rr = thresholds["min_rr"]
        
        # Validate signal
        score_valid = signal_score >= min_score
        rr_valid = risk_reward_ratio >= min_rr
        
        is_valid = score_valid and rr_valid
        
        if is_valid:
            reason = "meets_regime_thresholds"
        elif not score_valid and not rr_valid:
            reason = "score_and_rr_below_threshold"
        elif not score_valid:
            reason = "score_below_threshold"
        else:  # not rr_valid
            reason = "rr_below_threshold"
        
        details = {
            "symbol": symbol,
            "regime": regime,
            "signal_score": signal_score,
            "risk_reward_ratio": risk_reward_ratio,
            "min_score": min_score,
            "min_rr": min_rr,
            "score_valid": score_valid,
            "rr_valid": rr_valid,
            "is_valid": is_valid,
            "reason": reason,
            "regime_details": regime_details
        }
        
        if is_valid:
            self.logger.info(
                f"SIGNAL_VALID: {symbol} {regime} score={signal_score:.3f} "
                f"rr={risk_reward_ratio:.2f} (min_score={min_score}, min_rr={min_rr})"
            )
        else:
            self.logger.info(
                f"SIGNAL_INVALID: {symbol} {regime} score={signal_score:.3f} "
                f"rr={risk_reward_ratio:.2f} (min_score={min_score}, min_rr={min_rr}) "
                f"reason={reason}"
            )
        
        return is_valid, reason, details
    
    def get_regime_summary(self, symbol: str) -> Dict[str, Any]:
        """
        Get comprehensive regime summary for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with regime information and thresholds
        """
        regime, regime_details = self.detect_regime(symbol)
        thresholds = self.get_regime_thresholds(regime)
        
        return {
            "symbol": symbol,
            "regime": regime,
            "thresholds": thresholds,
            "regime_details": regime_details,
            "ema_fast_period": self.ema_fast_period,
            "ema_slow_period": self.ema_slow_period,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold
        }
    
    def get_all_regime_thresholds(self) -> Dict[str, Dict[str, float]]:
        """Get all regime thresholds."""
        return {
            "trend": self.trend_thresholds.copy(),
            "range": self.range_thresholds.copy()
        }
    
    def update_regime_thresholds(
        self,
        regime: str,
        min_score: Optional[float] = None,
        min_rr: Optional[float] = None
    ) -> bool:
        """
        Update regime thresholds.
        
        Args:
            regime: Market regime ("trend" or "range")
            min_score: New minimum score threshold
            min_rr: New minimum risk-reward ratio threshold
            
        Returns:
            True if updated successfully
        """
        if regime not in ["trend", "range"]:
            self.logger.error(f"Invalid regime '{regime}' for threshold update")
            return False
        
        if regime == "trend":
            if min_score is not None:
                self.trend_thresholds["min_score"] = min_score
            if min_rr is not None:
                self.trend_thresholds["min_rr"] = min_rr
        else:  # range
            if min_score is not None:
                self.range_thresholds["min_score"] = min_score
            if min_rr is not None:
                self.range_thresholds["min_rr"] = min_rr
        
        self.logger.info(f"Updated {regime} thresholds: {self.get_regime_thresholds(regime)}")
        return True

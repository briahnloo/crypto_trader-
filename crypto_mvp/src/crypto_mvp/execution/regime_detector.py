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
        self.get_atr_callback: Optional[Callable[[str, int], Optional[float]]] = None
        
        self.logger.info(f"RegimeDetector initialized: "
                        f"trend_thresholds={self.trend_thresholds}, "
                        f"range_thresholds={self.range_thresholds}")
    
    def set_callbacks(
        self,
        get_ema_callback: Callable[[str, int], Optional[float]],
        get_adx_callback: Callable[[str, int], Optional[float]],
        get_atr_callback: Optional[Callable[[str, int], Optional[float]]] = None
    ):
        """Set callback functions for indicator data."""
        self.get_ema_callback = get_ema_callback
        self.get_adx_callback = get_adx_callback
        self.get_atr_callback = get_atr_callback
        self.logger.info("Regime detector callbacks set")
    
    def _is_in_warmup(self, symbol: str) -> bool:
        """
        Check if symbol is in warmup period (insufficient data for indicators).
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if in warmup period, False otherwise
        """
        # Get risk-on configuration for ATR periods
        risk_on_cfg = self.config.get("risk", {}).get("risk_on", {})
        trigger_cfg = risk_on_cfg.get("trigger", {})
        atr_period = trigger_cfg.get("atr_period", 14)
        atr_sma_period = trigger_cfg.get("atr_sma_period", 100)
        
        # Check if we have enough data for the longest period needed
        # We need at least max(EMA200, ADX14, ATR_SMA100) = 200 bars
        max_period_needed = max(self.ema_slow_period, self.adx_period, atr_sma_period)
        
        # Try to get indicators with the longest period needed
        # If any callback returns None, we're likely in warmup
        if self.get_ema_callback:
            try:
                ema_slow = self.get_ema_callback(symbol, self.ema_slow_period)
                if ema_slow is None:
                    return True
            except Exception:
                return True
        
        if self.get_adx_callback:
            try:
                adx = self.get_adx_callback(symbol, self.adx_period)
                if adx is None:
                    return True
            except Exception:
                return True
        
        if self.get_atr_callback:
            try:
                atr_sma = self.get_atr_callback(symbol, atr_sma_period)
                if atr_sma is None:
                    return True
            except Exception:
                return True
        
        return False
    
    def detect_regime(self, symbol: str, data_quality: str = "ok") -> Tuple[str, Dict[str, Any]]:
        """
        Detect market regime for a symbol.
        
        Args:
            symbol: Trading symbol
            data_quality: Data quality status ("ok" | "stale" | "unsupported" | "missing")
            
        Returns:
            Tuple of (regime, details_dict)
            - regime: "trend", "range", or "unknown"
            - details_dict: Dictionary with indicator values, thresholds, and eligible flag
        """
        # Check data quality first
        if data_quality != "ok":
            details = {
                "symbol": symbol,
                "reason": f"data_quality_{data_quality}",
                "regime": "unknown",
                "eligible": False,
                "data_quality": data_quality,
                "indicator_status": "unavailable"
            }
            self.logger.info(f"REGIME_EXCLUDE: symbol={symbol}, reason=data_quality:{data_quality}")
            return "unknown", details
        
        # Check for warmup conditions
        if self._is_in_warmup(symbol):
            details = {
                "symbol": symbol,
                "reason": "insufficient_data_warmup",
                "regime": "unknown",
                "eligible": False,
                "data_quality": "ok",
                "indicator_status": "unavailable",
                "ema_fast_period": self.ema_fast_period,
                "ema_slow_period": self.ema_slow_period,
                "adx_period": self.adx_period,
                "adx_threshold": self.adx_threshold
            }
            self.logger.info(f"REGIME_EXCLUDE: symbol={symbol}, reason=insufficient_data_warmup")
            return "unknown", details
        
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
            details["regime"] = "unknown"
            details["eligible"] = False
            details["data_quality"] = data_quality
            details["indicator_status"] = "unavailable"
            self.logger.info(f"REGIME_EXCLUDE: symbol={symbol}, reason=missing_indicators")
            return "unknown", details
        
        # Check for invalid values
        if (math.isnan(ema_fast) or math.isnan(ema_slow) or math.isnan(adx) or
            ema_fast <= 0 or ema_slow <= 0 or adx < 0):
            details["reason"] = "invalid_indicators"
            details["regime"] = "unknown"
            details["eligible"] = False
            details["data_quality"] = data_quality
            details["indicator_status"] = "unavailable"
            self.logger.info(f"REGIME_EXCLUDE: symbol={symbol}, reason=invalid_indicators")
            return "unknown", details
        
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
        details["eligible"] = True
        details["data_quality"] = data_quality
        details["indicator_status"] = "ok"
        
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
            regime: Market regime ("trend", "range", or "unknown (warmup)")
            
        Returns:
            Dictionary with min_score and min_rr thresholds
        """
        if regime == "trend":
            return self.trend_thresholds.copy()
        elif regime == "range":
            return self.range_thresholds.copy()
        elif regime == "unknown (warmup)":
            # Use conservative thresholds during warmup
            return {
                "min_score": 0.60,  # Higher score requirement during warmup
                "min_rr": 1.5       # Higher RR requirement during warmup
            }
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
    
    def detect_risk_on_trigger(self, symbol: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Detect if risk-on mode should be triggered based on ATR/ATR_SMA ratio.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Tuple of (risk_on_triggered, details_dict)
            - risk_on_triggered: Boolean indicating if risk-on should be activated
            - details_dict: Dictionary with ATR values and ratios
        """
        # Get risk-on configuration
        risk_on_cfg = self.config.get("risk", {}).get("risk_on", {})
        if not risk_on_cfg.get("enabled", False):
            return False, {"reason": "risk_on_disabled"}
        
        trigger_cfg = risk_on_cfg.get("trigger", {})
        atr_period = trigger_cfg.get("atr_period", 14)
        atr_sma_period = trigger_cfg.get("atr_sma_period", 100)
        atr_over_sma_threshold = trigger_cfg.get("atr_over_sma", 1.15)
        
        # Get ATR values from distinct windows
        atr_current = None
        atr_sma = None
        
        if self.get_atr_callback:
            try:
                # Compute ATR(period=14) and ATR_SMA(period=100) from distinct windows
                atr_current = self.get_atr_callback(symbol, atr_period)
                atr_sma = self.get_atr_callback(symbol, atr_sma_period)
            except Exception as e:
                self.logger.warning(f"Failed to get ATR for {symbol}: {e}")
        
        # Create details dictionary
        details = {
            "symbol": symbol,
            "atr_current": atr_current,
            "atr_sma": atr_sma,
            "atr_period": atr_period,
            "atr_sma_period": atr_sma_period,
            "atr_over_sma_threshold": atr_over_sma_threshold,
            "reason": "unknown"
        }
        
        # Check if ATR values are available
        if atr_current is None or atr_sma is None:
            details["reason"] = "missing_atr_data"
            self.logger.info(f"RISK-ON: {symbol} = False (reason=missing_atr_data)")
            return False, details
        
        # Check for invalid values
        if (math.isnan(atr_current) or math.isnan(atr_sma) or
            atr_current <= 0 or atr_sma <= 0):
            details["reason"] = "invalid_atr_data"
            self.logger.info(f"RISK-ON: {symbol} = False (reason=invalid_atr_data)")
            return False, details
        
        # Warmup guard: check if we have enough data for both periods
        # For ATR(14) we need at least 14 bars, for ATR_SMA(100) we need at least 100 bars
        min_bars_needed = max(atr_period, atr_sma_period)
        
        # Check if we're in warmup period (insufficient data)
        if self._is_in_warmup(symbol):
            details["reason"] = "insufficient_data_warmup"
            details["min_bars_needed"] = min_bars_needed
            self.logger.info(f"RISK-ON: {symbol} = False (reason=insufficient_data_warmup)")
            return False, details
        
        # Calculate volatility ratio
        vol_ratio = atr_current / atr_sma if atr_sma > 0 else 1.0
        risk_on_triggered = vol_ratio >= atr_over_sma_threshold
        
        details["vol_ratio"] = vol_ratio
        details["risk_on_triggered"] = risk_on_triggered
        details["min_bars_needed"] = min_bars_needed
        
        if risk_on_triggered:
            details["reason"] = "vol_ratio_above_threshold"
        else:
            details["reason"] = "vol_ratio_below_threshold"
        
        self.logger.info(
            f"RISK-ON: {symbol} = {risk_on_triggered} (reason={details['reason']}) "
            f"ATR={atr_current:.4f} ATR_SMA={atr_sma:.4f} vol_ratio={vol_ratio:.3f} "
            f"threshold={atr_over_sma_threshold:.2f}"
        )
        
        return risk_on_triggered, details
    
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

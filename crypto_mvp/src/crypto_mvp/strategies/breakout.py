"""
Breakout trading strategy using ATR and volume confirmation.
"""

from typing import Any, Optional
import numpy as np

from .base import Strategy
from ..indicators.technical_calculator import get_calculator


class BreakoutStrategy(Strategy):
    """Breakout trading strategy based on ATR and volume confirmation."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the breakout strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "breakout"
        
        # Get technical calculator
        self.calculator = get_calculator()

        # Strategy parameters
        params = config.get("parameters", {}) if config else {}
        self.atr_period = params.get("atr_period", 14)
        self.atr_multiplier = params.get("atr_multiplier", 2.0)
        self.volume_threshold = params.get("min_volume_multiplier", 1.5)
        self.lookback_period = params.get("lookback_period", 20)
        self.breakout_threshold = params.get("breakout_threshold", 0.015)
        self.volume_confirmation = params.get("volume_confirmation", True)
        
        # Data engine reference (will be set by caller)
        self.data_engine = None

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze breakout conditions and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing breakout analysis results
        """
        if not timeframe:
            timeframe = "1h"
        
        try:
            if not self.data_engine:
                return self._neutral_signal(symbol, "no_data_engine")
            
            # Fetch real OHLCV data
            ohlcv = self.data_engine.get_ohlcv(symbol, timeframe, limit=100)
            
            if not ohlcv or len(ohlcv) < self.lookback_period + 10:
                return self._neutral_signal(symbol, "insufficient_data")
            
            # Parse OHLCV data
            parsed = self.calculator.parse_ohlcv(ohlcv)
            highs = parsed["highs"]
            lows = parsed["lows"]
            closes = parsed["closes"]
            volumes = parsed["volumes"]
            
            # Calculate indicators
            atr = self.calculator.calculate_atr(highs, lows, closes, self.atr_period)
            volume_ratio = self.calculator.calculate_volume_ratio(volumes, 20)
            support_resistance = self.calculator.detect_support_resistance(
                highs, lows, closes, self.lookback_period
            )
            
            if atr is None or volume_ratio is None:
                return self._neutral_signal(symbol, "indicator_calculation_failed")
            
            # Get current price
            entry_price = float(closes[-1])
            resistance = support_resistance["resistance"]
            support = support_resistance["support"]
            
            # Calculate breakout strength
            distance_to_resistance_pct = support_resistance["distance_to_resistance"]
            distance_to_support_pct = support_resistance["distance_to_support"]
            
            # Detect breakout: price near resistance (bullish) or support (bearish)
            if distance_to_resistance_pct < self.breakout_threshold:
                # Near resistance - potential upside breakout
                breakout_strength = 1.0 - distance_to_resistance_pct / self.breakout_threshold
                breakout_direction = 1  # Bullish
            elif distance_to_support_pct < self.breakout_threshold:
                # Near support - potential downside breakout
                breakout_strength = 1.0 - distance_to_support_pct / self.breakout_threshold
                breakout_direction = -1  # Bearish
            else:
                # Mid-range, no breakout
                breakout_strength = 0.0
                breakout_direction = 0
            
            # Calculate breakout score
            breakout_score = self._calculate_breakout_score(
                atr, volume_ratio, breakout_strength, breakout_direction
            )
            
            # Determine signal strength
            signal_strength = abs(breakout_score)
            
            # Calculate stop loss and take profit
            stop_loss, take_profit = self._calculate_stop_take_profit(
                entry_price, atr, breakout_score
            )
            
            # Calculate volatility
            volatility = atr / entry_price if entry_price > 0 else 0.02
            
            # Calculate confidence
            confidence = self._calculate_confidence(volume_ratio, breakout_strength)

            return {
                "score": breakout_score,
                "signal_strength": signal_strength,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "volatility": volatility,
                "confidence": confidence,
                "metadata": {
                    "atr": atr,
                    "volume_ratio": volume_ratio,
                    "breakout_strength": breakout_strength,
                    "resistance": resistance,
                    "support": support,
                    "timeframe": timeframe,
                    "strategy": "breakout",
                    "data_points": len(closes)
                },
            }
        except Exception as e:
            self.logger.warning(f"Breakout analysis failed for {symbol}: {e}")
            return self._neutral_signal(symbol, f"error:{str(e)}")
    
    def _neutral_signal(self, symbol: str, reason: str) -> dict[str, Any]:
        """Return a neutral signal when analysis fails."""
        return {
            "score": 0.0,
            "signal_strength": 0.0,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "volatility": 0.02,
            "confidence": 0.0,
            "metadata": {
                "strategy": "breakout",
                "reason": reason,
                "error": True
            }
        }
    
    def _calculate_confidence(self, volume_ratio: float, breakout_strength: float) -> float:
        """Calculate confidence based on volume and breakout strength."""
        confidence = 0.5  # Base confidence
        
        # Volume confirmation adds confidence
        if volume_ratio > self.volume_threshold:
            confidence += 0.3
        elif volume_ratio > 1.0:
            confidence += 0.1
        
        # Breakout strength adds confidence
        confidence += breakout_strength * 0.2
        
        return min(1.0, confidence)

    def _calculate_breakout_score(
        self, 
        atr: float, 
        volume_ratio: float, 
        breakout_strength: float,
        breakout_direction: int
    ) -> float:
        """Calculate breakout score from real indicators.

        Args:
            atr: Average True Range
            volume_ratio: Volume ratio (current vs average)
            breakout_strength: Breakout strength (0 to 1)
            breakout_direction: Direction (+1 bullish, -1 bearish, 0 neutral)

        Returns:
            Breakout score (-1 to 1)
        """
        if breakout_direction == 0 or breakout_strength == 0:
            return 0.0
        
        # Volume confirmation component
        if self.volume_confirmation:
            if volume_ratio > self.volume_threshold:
                volume_score = 0.4  # Strong volume confirmation
            elif volume_ratio > 1.0:
                volume_score = 0.2  # Moderate volume confirmation
            else:
                # Weak volume - likely false breakout, reduce score significantly
                volume_score = -0.3
        else:
            volume_score = 0.0
        
        # Breakout strength component (0 to 1)
        strength_score = breakout_strength * 0.5
        
        # Combine scores
        total_score = volume_score + strength_score
        
        # Apply direction
        total_score *= breakout_direction
        
        # Normalize to -1 to 1 range
        return max(-1.0, min(1.0, total_score))

    def _calculate_stop_take_profit(
        self, entry_price: float, atr: float, breakout_score: float
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels based on ATR.

        Args:
            entry_price: Entry price
            atr: Average True Range
            breakout_score: Breakout score

        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if abs(breakout_score) < 0.3:  # Weak signal
            return None, None

        # Use ATR for stop loss distance: 1.5x ATR for stops, 3x ATR for targets
        stop_distance = atr * 1.5
        take_distance = atr * 3.0

        if breakout_score > 0:  # Bullish breakout
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + take_distance
        else:  # Bearish breakout
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - take_distance

        return stop_loss, take_profit

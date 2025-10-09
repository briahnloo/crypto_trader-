"""
Momentum trading strategy using RSI, MACD, and Williams %R indicators.
"""

from typing import Any, Optional
import numpy as np

from .base import Strategy
from ..indicators.technical_calculator import get_calculator


class MomentumStrategy(Strategy):
    """Momentum trading strategy based on technical indicators."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the momentum strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "momentum"
        
        # Get technical calculator
        self.calculator = get_calculator()

        # Strategy parameters
        params = config.get("parameters", {}) if config else {}
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.rsi_overbought = params.get("rsi_overbought", 70)
        self.macd_fast = params.get("macd_fast", 12)
        self.macd_slow = params.get("macd_slow", 26)
        self.macd_signal = params.get("macd_signal", 9)
        self.williams_period = params.get("williams_period", 14)
        self.williams_oversold = params.get("williams_oversold", -80)
        self.williams_overbought = params.get("williams_overbought", -20)
        self.min_volume_ratio = params.get("min_volume_ratio", 1.2)
        
        # Data engine reference (will be set by caller)
        self.data_engine = None

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze momentum indicators and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing momentum analysis results
        """
        if not timeframe:
            timeframe = "1h"
        
        # Fetch real OHLCV data
        try:
            if not self.data_engine:
                # Fallback to neutral signal if no data engine
                return self._neutral_signal(symbol, "no_data_engine")
            
            ohlcv = self.data_engine.get_ohlcv(symbol, timeframe, limit=100)
            
            if not ohlcv or len(ohlcv) < max(self.macd_slow, self.rsi_period) + 10:
                return self._neutral_signal(symbol, "insufficient_data")
            
            # Parse OHLCV data
            parsed = self.calculator.parse_ohlcv(ohlcv)
            closes = parsed["closes"]
            highs = parsed["highs"]
            lows = parsed["lows"]
            volumes = parsed["volumes"]
            
            # Calculate real indicators
            rsi = self.calculator.calculate_rsi(closes, self.rsi_period)
            macd_data = self.calculator.calculate_macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
            williams_r = self.calculator.calculate_williams_r(highs, lows, closes, self.williams_period)
            volume_ratio = self.calculator.calculate_volume_ratio(volumes, 20)
            volatility = self.calculator.calculate_volatility(closes, 20)
            
            if rsi is None or macd_data is None or williams_r is None:
                return self._neutral_signal(symbol, "indicator_calculation_failed")
            
            # Get current price
            entry_price = float(closes[-1])
            
            # Calculate momentum score from real indicators
            momentum_score = self._calculate_momentum_score(rsi, macd_data["histogram"], williams_r)
            
            # Check volume confirmation
            if volume_ratio and volume_ratio < self.min_volume_ratio:
                # Reduce signal strength if volume is weak
                momentum_score *= 0.7
            
            # Determine signal strength
            signal_strength = abs(momentum_score)
            
            # Calculate stop loss and take profit using ATR
            atr = self.calculator.calculate_atr(highs, lows, closes, 14)
            stop_loss, take_profit = self._calculate_stop_take_profit(
                entry_price, momentum_score, atr
            )
            
            # Calculate confidence based on indicator alignment
            confidence = self._calculate_confidence(rsi, macd_data, williams_r, volume_ratio)

            return {
                "score": momentum_score,
                "signal_strength": signal_strength,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "volatility": volatility or 0.02,
                "confidence": confidence,
                "metadata": {
                    "rsi": rsi,
                    "macd": macd_data["macd"],
                    "macd_signal": macd_data["signal"],
                    "macd_histogram": macd_data["histogram"],
                    "williams_r": williams_r,
                    "volume_ratio": volume_ratio,
                    "atr": atr,
                    "timeframe": timeframe,
                    "strategy": "momentum",
                    "data_points": len(closes)
                },
            }
        except Exception as e:
            self.logger.warning(f"Momentum analysis failed for {symbol}: {e}")
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
                "strategy": "momentum",
                "reason": reason,
                "error": True
            }
        }

    def _calculate_confidence(
        self, 
        rsi: float, 
        macd_data: dict, 
        williams_r: float, 
        volume_ratio: Optional[float]
    ) -> float:
        """
        Calculate confidence based on indicator alignment.
        
        Args:
            rsi: RSI value
            macd_data: MACD data dictionary
            williams_r: Williams %R value
            volume_ratio: Volume ratio (current vs average)
            
        Returns:
            Confidence score (0 to 1)
        """
        alignment_score = 0.0
        
        # Check RSI alignment
        if rsi < self.rsi_oversold or rsi > self.rsi_overbought:
            alignment_score += 0.3  # Strong RSI signal
        elif 40 < rsi < 60:
            alignment_score += 0.1  # Neutral
        
        # Check MACD alignment
        macd_histogram = macd_data["histogram"]
        if abs(macd_histogram) > 0.05:
            alignment_score += 0.3  # Strong MACD signal
        
        # Check Williams %R alignment
        if williams_r < self.williams_oversold or williams_r > self.williams_overbought:
            alignment_score += 0.2  # Williams confirms
        
        # Check volume confirmation
        if volume_ratio and volume_ratio > self.min_volume_ratio:
            alignment_score += 0.2  # Volume confirms
        
        return min(1.0, alignment_score)

    def _calculate_momentum_score(
        self, rsi: float, macd_signal: float, williams_r: float
    ) -> float:
        """Calculate momentum score from indicators.

        Args:
            rsi: RSI value
            macd_signal: MACD signal value
            williams_r: Williams %R value

        Returns:
            Momentum score (-1 to 1)
        """
        # RSI component
        if rsi < self.rsi_oversold:
            rsi_score = 0.5  # Oversold, potential buy
        elif rsi > self.rsi_overbought:
            rsi_score = -0.5  # Overbought, potential sell
        else:
            rsi_score = 0.0  # Neutral

        # MACD component
        if macd_signal > 0:
            macd_score = 0.3  # Bullish momentum
        else:
            macd_score = -0.3  # Bearish momentum

        # Williams %R component
        if williams_r < self.williams_oversold:
            williams_score = 0.2  # Oversold
        elif williams_r > self.williams_overbought:
            williams_score = -0.2  # Overbought
        else:
            williams_score = 0.0  # Neutral

        # Combine scores
        total_score = rsi_score + macd_score + williams_score

        # Normalize to -1 to 1 range
        return max(-1.0, min(1.0, total_score))

    def _calculate_stop_take_profit(
        self, 
        entry_price: float, 
        momentum_score: float,
        atr: Optional[float] = None
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels using ATR or percentage fallback.

        Args:
            entry_price: Entry price
            momentum_score: Momentum score
            atr: Average True Range value (optional)

        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if abs(momentum_score) < 0.3:  # Weak signal
            return None, None

        # Use ATR if available, otherwise fall back to percentage
        if atr and atr > 0:
            # ATR-based stops: 1.5x ATR for stop, 3x ATR for target (2:1 R:R)
            stop_distance = 1.5 * atr
            take_distance = 3.0 * atr
        else:
            # Percentage fallback
            stop_distance = entry_price * 0.02  # 2%
            take_distance = entry_price * 0.04  # 4%

        if momentum_score > 0:  # Buy signal
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + take_distance
        else:  # Sell signal
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - take_distance

        return stop_loss, take_profit

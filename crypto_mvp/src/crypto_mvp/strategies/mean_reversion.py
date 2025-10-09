"""
Mean reversion trading strategy using Bollinger Bands deviation.
"""

from typing import Any, Optional
import numpy as np

from .base import Strategy
from ..indicators.technical_calculator import get_calculator


class MeanReversionStrategy(Strategy):
    """Mean reversion trading strategy based on Bollinger Bands deviation."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the mean reversion strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "mean_reversion"
        
        # Get technical calculator
        self.calculator = get_calculator()

        # Strategy parameters
        params = config.get("parameters", {}) if config else {}
        self.bb_period = params.get("bollinger_period", 20)
        self.bb_std_dev = params.get("bollinger_std_dev", 2.0)
        self.oversold_threshold = params.get("oversold_threshold", 0.2)
        self.overbought_threshold = params.get("overbought_threshold", 0.8)
        self.rsi_period = params.get("rsi_period", 14)
        
        # Data engine reference (will be set by caller)
        self.data_engine = None

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze mean reversion conditions and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing mean reversion analysis results
        """
        if not timeframe:
            timeframe = "1h"
        
        try:
            if not self.data_engine:
                return self._neutral_signal(symbol, "no_data_engine")
            
            # Fetch real OHLCV data
            ohlcv = self.data_engine.get_ohlcv(symbol, timeframe, limit=100)
            
            if not ohlcv or len(ohlcv) < self.bb_period + 10:
                return self._neutral_signal(symbol, "insufficient_data")
            
            # Parse OHLCV data
            parsed = self.calculator.parse_ohlcv(ohlcv)
            closes = parsed["closes"]
            highs = parsed["highs"]
            lows = parsed["lows"]
            
            # Calculate Bollinger Bands
            bb_data = self.calculator.calculate_bollinger_bands(
                closes, self.bb_period, self.bb_std_dev
            )
            
            # Calculate RSI for confirmation
            rsi = self.calculator.calculate_rsi(closes, self.rsi_period)
            
            if bb_data is None or rsi is None:
                return self._neutral_signal(symbol, "indicator_calculation_failed")
            
            # Get current price and BB position
            entry_price = float(closes[-1])
            percent_b = bb_data["percent_b"]  # 0 = lower band, 1 = upper band
            
            # Calculate mean reversion score
            mean_reversion_score = self._calculate_mean_reversion_score(percent_b, rsi)
            
            # Determine signal strength
            signal_strength = abs(mean_reversion_score)
            
            # Calculate stop loss and take profit
            atr = self.calculator.calculate_atr(highs, lows, closes, 14)
            stop_loss, take_profit = self._calculate_stop_take_profit(
                entry_price, mean_reversion_score, atr, bb_data
            )
            
            # Calculate volatility
            volatility = self.calculator.calculate_volatility(closes, 20) or 0.02
            
            # Calculate confidence
            confidence = self._calculate_confidence(percent_b, rsi)

            return {
                "score": mean_reversion_score,
                "signal_strength": signal_strength,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "volatility": volatility,
                "confidence": confidence,
                "metadata": {
                    "percent_b": percent_b,
                    "bb_upper": bb_data["upper"],
                    "bb_middle": bb_data["middle"],
                    "bb_lower": bb_data["lower"],
                    "rsi": rsi,
                    "atr": atr,
                    "timeframe": timeframe,
                    "strategy": "mean_reversion",
                    "data_points": len(closes)
                },
            }
        except Exception as e:
            self.logger.warning(f"Mean reversion analysis failed for {symbol}: {e}")
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
                "strategy": "mean_reversion",
                "reason": reason,
                "error": True
            }
        }
    
    def _calculate_confidence(self, percent_b: float, rsi: float) -> float:
        """Calculate confidence based on indicator alignment."""
        confidence = 0.3  # Base confidence
        
        # Strong BB signal adds confidence
        if percent_b < 0.1 or percent_b > 0.9:
            confidence += 0.4  # Extreme position
        elif percent_b < 0.2 or percent_b > 0.8:
            confidence += 0.2  # Moderate position
        
        # RSI confirmation adds confidence
        if (percent_b < 0.3 and rsi < 30) or (percent_b > 0.7 and rsi > 70):
            confidence += 0.3  # Both indicators agree
        
        return min(1.0, confidence)

    def _calculate_mean_reversion_score(
        self, 
        percent_b: float, 
        rsi: float
    ) -> float:
        """Calculate mean reversion score from real indicators.

        Args:
            percent_b: Price position within Bollinger Bands (0-1)
            rsi: RSI value

        Returns:
            Mean reversion score (-1 to 1)
        """
        # Bollinger Bands position component
        if percent_b < self.oversold_threshold:
            # Oversold - potential buy (mean reversion up)
            bb_score = 0.6 * (self.oversold_threshold - percent_b) / self.oversold_threshold
        elif percent_b > self.overbought_threshold:
            # Overbought - potential sell (mean reversion down)
            bb_score = -0.6 * (percent_b - self.overbought_threshold) / (1.0 - self.overbought_threshold)
        else:
            bb_score = 0.0  # Neutral

        # RSI confirmation component
        if rsi < 30:  # Oversold
            rsi_score = 0.3
        elif rsi > 70:  # Overbought
            rsi_score = -0.3
        else:
            rsi_score = 0.0

        # Price position component
        if percent_b < 0.2:  # Near lower band
            position_score = 0.1
        elif percent_b > 0.8:  # Near upper band
            position_score = -0.1
        else:
            position_score = 0.0

        # Combine scores
        total_score = bb_score + rsi_score + position_score

        # Normalize to -1 to 1 range
        return max(-1.0, min(1.0, total_score))

    def _calculate_stop_take_profit(
        self, 
        entry_price: float, 
        mean_reversion_score: float,
        atr: Optional[float] = None,
        bb_data: Optional[dict] = None
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels.

        Args:
            entry_price: Entry price
            mean_reversion_score: Mean reversion score
            atr: Average True Range (optional)
            bb_data: Bollinger Bands data (optional)

        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if abs(mean_reversion_score) < 0.3:  # Weak signal
            return None, None

        # Use BB bands for targets if available, otherwise ATR or percentage
        if bb_data:
            bb_middle = bb_data["middle"]
            bb_upper = bb_data["upper"]
            bb_lower = bb_data["lower"]
            
            if mean_reversion_score > 0:  # Buy signal (price near lower band)
                # Stop: below lower band
                # Target: middle band (mean reversion)
                stop_loss = bb_lower * 0.99  # 1% below lower band
                take_profit = bb_middle
            else:  # Sell signal (price near upper band)
                # Stop: above upper band
                # Target: middle band (mean reversion)
                stop_loss = bb_upper * 1.01  # 1% above upper band
                take_profit = bb_middle
        elif atr and atr > 0:
            # ATR-based stops
            stop_distance = atr * 1.5
            take_distance = atr * 3.0
            
            if mean_reversion_score > 0:
                stop_loss = entry_price - stop_distance
                take_profit = entry_price + take_distance
            else:
                stop_loss = entry_price + stop_distance
                take_profit = entry_price - take_distance
        else:
            # Percentage fallback
            risk_percent = 0.015  # 1.5% risk
            reward_percent = 0.03  # 3% reward (2:1)
            
            if mean_reversion_score > 0:
                stop_loss = entry_price * (1 - risk_percent)
                take_profit = entry_price * (1 + reward_percent)
            else:
                stop_loss = entry_price * (1 + risk_percent)
                take_profit = entry_price * (1 - reward_percent)

        return stop_loss, take_profit

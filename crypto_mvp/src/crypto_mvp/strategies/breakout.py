"""
Breakout trading strategy using ATR and volume confirmation.
"""

import random
from typing import Any, Optional

from .base import Strategy


class BreakoutStrategy(Strategy):
    """Breakout trading strategy based on ATR and volume confirmation."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the breakout strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "breakout"

        # Strategy parameters
        self.atr_period = config.get("atr_period", 14) if config else 14
        self.atr_multiplier = config.get("atr_multiplier", 2.0) if config else 2.0
        self.volume_threshold = config.get("volume_threshold", 1.5) if config else 1.5
        self.lookback_period = config.get("lookback_period", 20) if config else 20
        self.min_breakout_strength = (
            config.get("min_breakout_strength", 0.5) if config else 0.5
        )

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze breakout conditions and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing breakout analysis results
        """
        # Generate mock data for demonstration
        atr = self._get_mock_atr()
        volume_ratio = self._get_mock_volume_ratio()
        breakout_strength = self._get_mock_breakout_strength()

        # Calculate breakout score
        breakout_score = self._calculate_breakout_score(
            atr, volume_ratio, breakout_strength
        )

        # Determine signal strength
        signal_strength = abs(breakout_score)

        # Generate entry price (mock)
        entry_price = self._get_mock_entry_price(symbol)

        # Calculate stop loss and take profit based on ATR
        stop_loss, take_profit = self._calculate_stop_take_profit(
            entry_price, atr, breakout_score
        )

        # Calculate volatility (using ATR)
        volatility = atr / entry_price if entry_price > 0 else 0.02

        return {
            "score": breakout_score,
            "signal_strength": signal_strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volatility": volatility,
            "confidence": min(signal_strength + 0.1, 1.0),
            "metadata": {
                "atr": atr,
                "volume_ratio": volume_ratio,
                "breakout_strength": breakout_strength,
                "timeframe": timeframe or "1h",
                "strategy": "breakout",
            },
        }

    def _get_mock_atr(self) -> float:
        """Generate mock ATR value."""
        return random.uniform(100, 1000)

    def _get_mock_volume_ratio(self) -> float:
        """Generate mock volume ratio (current vs average)."""
        return random.uniform(0.5, 3.0)

    def _get_mock_breakout_strength(self) -> float:
        """Generate mock breakout strength."""
        return random.uniform(0.0, 2.0)

    def _calculate_breakout_score(
        self, atr: float, volume_ratio: float, breakout_strength: float
    ) -> float:
        """Calculate breakout score from indicators.

        Args:
            atr: Average True Range
            volume_ratio: Volume ratio (current vs average)
            breakout_strength: Breakout strength measure

        Returns:
            Breakout score (-1 to 1)
        """
        # Volume confirmation component
        if volume_ratio > self.volume_threshold:
            volume_score = 0.4  # Strong volume confirmation
        elif volume_ratio > 1.0:
            volume_score = 0.2  # Moderate volume confirmation
        else:
            volume_score = -0.2  # Weak volume (false breakout risk)

        # Breakout strength component
        if breakout_strength > self.min_breakout_strength:
            strength_score = 0.4  # Strong breakout
        elif breakout_strength > 0.2:
            strength_score = 0.1  # Weak breakout
        else:
            strength_score = -0.3  # No breakout

        # ATR component (higher ATR = more volatile = higher breakout potential)
        atr_score = min(0.2, (atr - 500) / 2500)  # Normalize ATR contribution

        # Combine scores
        total_score = volume_score + strength_score + atr_score

        # Add some randomness for demonstration
        total_score += random.uniform(-0.1, 0.1)

        # Normalize to -1 to 1 range
        return max(-1.0, min(1.0, total_score))

    def _get_mock_entry_price(self, symbol: str) -> float:
        """Generate mock entry price based on symbol."""
        base_prices = {
            "BTC/USDT": 50000,
            "ETH/USDT": 3000,
            "ADA/USDT": 0.5,
            "DOT/USDT": 7.0,
        }
        base_price = base_prices.get(symbol, 100)
        return base_price * random.uniform(0.98, 1.02)

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

        # Use ATR for stop loss distance
        atr_stop_distance = atr * self.atr_multiplier

        # Calculate risk/reward ratio
        risk_percent = atr_stop_distance / entry_price
        reward_percent = risk_percent * 2  # 2:1 reward ratio

        if breakout_score > 0:  # Bullish breakout
            stop_loss = entry_price - atr_stop_distance
            take_profit = entry_price + (entry_price * reward_percent)
        else:  # Bearish breakout
            stop_loss = entry_price + atr_stop_distance
            take_profit = entry_price - (entry_price * reward_percent)

        return stop_loss, take_profit

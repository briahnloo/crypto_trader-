"""
Volatility trading strategy based on volatility patterns and mean reversion.
"""

import random
from typing import Any, Optional

from .base import Strategy


class VolatilityStrategy(Strategy):
    """Volatility trading strategy based on volatility patterns."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the volatility strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "volatility"

        # Strategy parameters
        self.volatility_period = config.get("volatility_period", 20) if config else 20
        self.high_volatility_threshold = (
            config.get("high_volatility_threshold", 0.05) if config else 0.05
        )
        self.low_volatility_threshold = (
            config.get("low_volatility_threshold", 0.02) if config else 0.02
        )
        self.volatility_expansion_threshold = (
            config.get("volatility_expansion_threshold", 1.5) if config else 1.5
        )

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze volatility patterns and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing volatility analysis results
        """
        # Generate mock volatility data
        volatility_data = self._get_mock_volatility_data()

        # Calculate volatility score
        volatility_score = self._calculate_volatility_score(volatility_data)

        # Determine signal strength
        signal_strength = abs(volatility_score)

        # Generate entry price (mock)
        entry_price = self._get_mock_entry_price(symbol)

        # Calculate stop loss and take profit
        stop_loss, take_profit = self._calculate_stop_take_profit(
            entry_price, volatility_data, volatility_score
        )

        # Get current volatility
        current_volatility = volatility_data["current_volatility"]

        return {
            "score": volatility_score,
            "signal_strength": signal_strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volatility": current_volatility,
            "confidence": min(signal_strength + 0.05, 1.0),
            "metadata": {
                "volatility_data": volatility_data,
                "timeframe": timeframe or "1h",
                "strategy": "volatility",
            },
        }

    def _get_mock_volatility_data(self) -> dict[str, Any]:
        """Generate mock volatility data."""
        return {
            "current_volatility": random.uniform(0.01, 0.08),
            "average_volatility": random.uniform(0.02, 0.05),
            "volatility_ratio": random.uniform(0.5, 2.0),
            "volatility_trend": random.choice(["increasing", "decreasing", "stable"]),
            "atr": random.uniform(100, 1000),
            "bollinger_width": random.uniform(0.02, 0.08),
        }

    def _calculate_volatility_score(self, volatility_data: dict[str, Any]) -> float:
        """Calculate volatility score from data."""
        current_vol = volatility_data["current_volatility"]
        avg_vol = volatility_data["average_volatility"]
        vol_ratio = volatility_data["volatility_ratio"]

        # Volatility expansion/contraction signal
        if vol_ratio > self.volatility_expansion_threshold:
            # High volatility expansion - potential breakout
            score = 0.4
        elif vol_ratio < 0.7:
            # Low volatility contraction - potential breakout
            score = 0.3
        else:
            score = 0.0

        # Current volatility level
        if current_vol > self.high_volatility_threshold:
            score += 0.2  # High volatility environment
        elif current_vol < self.low_volatility_threshold:
            score += 0.1  # Low volatility environment

        # Add randomness for demonstration
        score += random.uniform(-0.1, 0.1)

        return max(-1.0, min(1.0, score))

    def _get_mock_entry_price(self, symbol: str) -> float:
        """Generate mock entry price."""
        base_prices = {"BTC/USDT": 50000, "ETH/USDT": 3000, "ADA/USDT": 0.5}
        base_price = base_prices.get(symbol, 100)
        return base_price * random.uniform(0.97, 1.03)

    def _calculate_stop_take_profit(
        self,
        entry_price: float,
        volatility_data: dict[str, Any],
        volatility_score: float,
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit based on volatility."""
        if abs(volatility_score) < 0.2:
            return None, None

        current_vol = volatility_data["current_volatility"]
        atr = volatility_data["atr"]

        # Use ATR for stop loss distance with fallback
        if atr is not None and atr > 0:
            stop_distance = atr * 2.0
        else:
            # Fallback to percent-based distance
            stop_distance = entry_price * 0.02  # 2% fallback

        if volatility_score > 0:  # Volatility expansion (potential breakout)
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + (stop_distance * 2)  # 2:1 ratio
        else:  # Volatility contraction (potential reversal)
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - (stop_distance * 1.5)  # 1.5:1 ratio

        return stop_loss, take_profit

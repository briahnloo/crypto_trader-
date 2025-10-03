"""
Mean reversion trading strategy using Bollinger Bands deviation.
"""

import random
from typing import Any, Optional

from .base import Strategy


class MeanReversionStrategy(Strategy):
    """Mean reversion trading strategy based on Bollinger Bands deviation."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the mean reversion strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "mean_reversion"

        # Strategy parameters
        self.bb_period = config.get("bb_period", 20) if config else 20
        self.bb_std_dev = config.get("bb_std_dev", 2.0) if config else 2.0
        self.oversold_threshold = (
            config.get("oversold_threshold", -2.0) if config else -2.0
        )
        self.overbought_threshold = (
            config.get("overbought_threshold", 2.0) if config else 2.0
        )
        self.min_deviation = config.get("min_deviation", 1.5) if config else 1.5
        self.rsi_period = config.get("rsi_period", 14) if config else 14

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze mean reversion conditions and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing mean reversion analysis results
        """
        # Generate mock data for demonstration
        bb_deviation = self._get_mock_bb_deviation()
        rsi = self._get_mock_rsi()
        price_position = self._get_mock_price_position()

        # Calculate mean reversion score
        mean_reversion_score = self._calculate_mean_reversion_score(
            bb_deviation, rsi, price_position
        )

        # Determine signal strength
        signal_strength = abs(mean_reversion_score)

        # Generate entry price (mock)
        entry_price = self._get_mock_entry_price(symbol)

        # Calculate stop loss and take profit
        stop_loss, take_profit = self._calculate_stop_take_profit(
            entry_price, bb_deviation, mean_reversion_score
        )

        # Calculate volatility (mock)
        volatility = self._get_mock_volatility()

        return {
            "score": mean_reversion_score,
            "signal_strength": signal_strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volatility": volatility,
            "confidence": min(signal_strength + 0.15, 1.0),
            "metadata": {
                "bb_deviation": bb_deviation,
                "rsi": rsi,
                "price_position": price_position,
                "timeframe": timeframe or "1h",
                "strategy": "mean_reversion",
            },
        }

    def _get_mock_bb_deviation(self) -> float:
        """Generate mock Bollinger Bands deviation."""
        return random.uniform(-3.0, 3.0)

    def _get_mock_rsi(self) -> float:
        """Generate mock RSI value."""
        return random.uniform(20, 80)

    def _get_mock_price_position(self) -> float:
        """Generate mock price position within Bollinger Bands."""
        return random.uniform(0.0, 1.0)  # 0 = lower band, 1 = upper band

    def _calculate_mean_reversion_score(
        self, bb_deviation: float, rsi: float, price_position: float
    ) -> float:
        """Calculate mean reversion score from indicators.

        Args:
            bb_deviation: Bollinger Bands deviation (standard deviations from mean)
            rsi: RSI value
            price_position: Price position within bands (0-1)

        Returns:
            Mean reversion score (-1 to 1)
        """
        # Bollinger Bands deviation component
        if bb_deviation < self.oversold_threshold:
            bb_score = 0.5  # Oversold, potential buy
        elif bb_deviation > self.overbought_threshold:
            bb_score = -0.5  # Overbought, potential sell
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
        if price_position < 0.2:  # Near lower band
            position_score = 0.2
        elif price_position > 0.8:  # Near upper band
            position_score = -0.2
        else:
            position_score = 0.0

        # Combine scores
        total_score = bb_score + rsi_score + position_score

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
        return base_price * random.uniform(0.97, 1.03)

    def _calculate_stop_take_profit(
        self, entry_price: float, bb_deviation: float, mean_reversion_score: float
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels.

        Args:
            entry_price: Entry price
            bb_deviation: Bollinger Bands deviation
            mean_reversion_score: Mean reversion score

        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if abs(mean_reversion_score) < 0.3:  # Weak signal
            return None, None

        # Calculate risk/reward ratio
        risk_percent = 0.015  # 1.5% risk (tighter for mean reversion)
        reward_percent = 0.03  # 3% reward (2:1 ratio)

        if mean_reversion_score > 0:  # Buy signal (oversold)
            stop_loss = entry_price * (1 - risk_percent)
            take_profit = entry_price * (1 + reward_percent)
        else:  # Sell signal (overbought)
            stop_loss = entry_price * (1 + risk_percent)
            take_profit = entry_price * (1 - reward_percent)

        return stop_loss, take_profit

    def _get_mock_volatility(self) -> float:
        """Generate mock volatility measure."""
        return random.uniform(0.01, 0.04)  # 1% to 4% volatility

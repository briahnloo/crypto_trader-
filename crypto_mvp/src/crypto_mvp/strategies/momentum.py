"""
Momentum trading strategy using RSI, MACD, and Williams %R indicators.
"""

import random
from typing import Any, Optional

from .base import Strategy


class MomentumStrategy(Strategy):
    """Momentum trading strategy based on technical indicators."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the momentum strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "momentum"

        # Strategy parameters
        self.rsi_period = config.get("rsi_period", 14) if config else 14
        self.rsi_oversold = config.get("rsi_oversold", 30) if config else 30
        self.rsi_overbought = config.get("rsi_overbought", 70) if config else 70
        self.macd_fast = config.get("macd_fast", 12) if config else 12
        self.macd_slow = config.get("macd_slow", 26) if config else 26
        self.macd_signal = config.get("macd_signal", 9) if config else 9
        self.williams_period = config.get("williams_period", 14) if config else 14
        self.williams_oversold = config.get("williams_oversold", -80) if config else -80
        self.williams_overbought = (
            config.get("williams_overbought", -20) if config else -20
        )

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze momentum indicators and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing momentum analysis results
        """
        # Generate mock indicator values for demonstration
        rsi = self._get_mock_rsi()
        macd_signal = self._get_mock_macd_signal()
        williams_r = self._get_mock_williams_r()

        # Calculate momentum score
        momentum_score = self._calculate_momentum_score(rsi, macd_signal, williams_r)

        # Determine signal strength
        signal_strength = abs(momentum_score)

        # Generate entry price (mock)
        entry_price = self._get_mock_entry_price(symbol)

        # Calculate stop loss and take profit
        stop_loss, take_profit = self._calculate_stop_take_profit(
            entry_price, momentum_score
        )

        # Calculate volatility (mock)
        volatility = self._get_mock_volatility()

        return {
            "score": momentum_score,
            "signal_strength": signal_strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volatility": volatility,
            "confidence": min(signal_strength + 0.2, 1.0),  # Boost confidence slightly
            "metadata": {
                "rsi": rsi,
                "macd_signal": macd_signal,
                "williams_r": williams_r,
                "timeframe": timeframe or "1h",
                "strategy": "momentum",
            },
        }

    def _get_mock_rsi(self) -> float:
        """Generate mock RSI value."""
        return random.uniform(20, 80)

    def _get_mock_macd_signal(self) -> float:
        """Generate mock MACD signal."""
        return random.uniform(-0.1, 0.1)

    def _get_mock_williams_r(self) -> float:
        """Generate mock Williams %R value."""
        return random.uniform(-100, 0)

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

    def _get_mock_entry_price(self, symbol: str) -> float:
        """Generate mock entry price based on symbol."""
        base_prices = {
            "BTC/USDT": 50000,
            "ETH/USDT": 3000,
            "ADA/USDT": 0.5,
            "DOT/USDT": 7.0,
        }
        base_price = base_prices.get(symbol, 100)
        return base_price * random.uniform(0.95, 1.05)

    def _calculate_stop_take_profit(
        self, entry_price: float, momentum_score: float
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels.

        Args:
            entry_price: Entry price
            momentum_score: Momentum score

        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if abs(momentum_score) < 0.3:  # Weak signal
            return None, None

        # Calculate risk/reward ratio
        risk_percent = 0.02  # 2% risk
        reward_percent = 0.04  # 4% reward (2:1 ratio)

        if momentum_score > 0:  # Buy signal
            stop_loss = entry_price * (1 - risk_percent)
            take_profit = entry_price * (1 + reward_percent)
        else:  # Sell signal
            stop_loss = entry_price * (1 + risk_percent)
            take_profit = entry_price * (1 - reward_percent)

        return stop_loss, take_profit

    def _get_mock_volatility(self) -> float:
        """Generate mock volatility measure."""
        return random.uniform(0.01, 0.05)  # 1% to 5% volatility

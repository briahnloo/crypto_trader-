"""
Sentiment strategy executor.
"""

from typing import Any

from .base import BaseExecutor


class SentimentExecutor(BaseExecutor):
    """
    Executor for sentiment trading strategy.
    """

    def __init__(self, config: dict[str, Any] = None):
        """Initialize sentiment executor.

        Args:
            config: Executor configuration
        """
        super().__init__(config)
        self.name = "SentimentExecutor"

        # Sentiment-specific parameters
        self.stop_loss_pct = self.config.get("stop_loss_pct", 0.03)  # 3% stop loss
        self.take_profit_pct = self.config.get(
            "take_profit_pct", 0.08
        )  # 8% take profit
        self.sentiment_threshold = self.config.get(
            "sentiment_threshold", 0.6
        )  # Minimum sentiment strength
        self.news_impact_factor = self.config.get(
            "news_impact_factor", 1.5
        )  # News impact multiplier

    def execute(
        self, signal: dict[str, Any], position: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute sentiment trading signal.

        Args:
            signal: Trading signal data
            position: Current position data

        Returns:
            Execution result
        """
        if not self.initialized:
            self.initialize()

        # Validate signal
        if not self._validate_signal(signal):
            return self._empty_result()

        # Check sentiment threshold
        sentiment_score = signal.get("sentiment_score", 0.0)
        if abs(sentiment_score) < self.sentiment_threshold:
            return self._empty_result()

        # Get signal data
        symbol = signal.get("symbol", "")
        score = signal.get("score", 0.0)
        confidence = signal.get("confidence", 0.0)
        current_price = signal.get("current_price", 0.0)
        news_impact = signal.get("news_impact", 0.0)

        if current_price <= 0:
            return self._empty_result()

        # Determine position side based on sentiment
        side = "buy" if sentiment_score > 0 else "sell"

        # Calculate position size (sentiment can be volatile)
        available_capital = position.get("available_capital", 10000.0)
        base_quantity = self._calculate_position_size(
            signal, position, available_capital, current_price
        )

        # Adjust position size based on news impact
        news_multiplier = 1.0 + (abs(news_impact) * self.news_impact_factor)
        quantity = base_quantity * news_multiplier

        if quantity <= 0:
            return self._empty_result()

        # Calculate entry price (sentiment can cause slippage)
        slippage = 0.003 if side == "buy" else -0.003  # 0.3% slippage
        entry_price = current_price * (1 + slippage)

        # Calculate stop loss and take profit
        if side == "buy":
            stop_loss = entry_price * (1 - self.stop_loss_pct)
            take_profit = entry_price * (1 + self.take_profit_pct)
        else:
            stop_loss = entry_price * (1 + self.stop_loss_pct)
            take_profit = entry_price * (1 - self.take_profit_pct)

        # Calculate fees (assume taker fee for sentiment trades)
        fees = quantity * entry_price * 0.002  # 0.2% taker fee

        # Calculate expected PnL
        expected_pnl = self._calculate_expected_pnl(
            entry_price, stop_loss, take_profit, quantity, side
        )

        # Simulate fill (sentiment orders have moderate fill probability)
        filled = confidence > 0.5 and abs(sentiment_score) > self.sentiment_threshold

        return {
            "filled": filled,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fees": fees,
            "expected_pnl": expected_pnl,
            "strategy": "sentiment",
            "side": side,
            "quantity": quantity,
            "sentiment_score": sentiment_score,
            "news_impact": news_impact,
            "confidence": confidence,
        }

    def _empty_result(self) -> dict[str, Any]:
        """Return empty execution result.

        Returns:
            Empty result dictionary
        """
        return {
            "filled": False,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "fees": 0.0,
            "expected_pnl": 0.0,
            "strategy": "sentiment",
            "side": "none",
            "quantity": 0.0,
            "sentiment_score": 0.0,
            "news_impact": 0.0,
            "confidence": 0.0,
        }

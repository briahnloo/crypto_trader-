"""
On-chain trading strategy based on blockchain metrics and network activity.
"""

import random
from typing import Any, Optional

from .base import Strategy


class OnChainStrategy(Strategy):
    """On-chain trading strategy based on blockchain metrics."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the on-chain strategy.

        Args:
            config: Strategy configuration (optional)
        """
        super().__init__()
        self.name = "on_chain"

        # Strategy parameters
        self.hash_rate_threshold = (
            config.get("hash_rate_threshold", 100000) if config else 100000
        )
        self.transaction_threshold = (
            config.get("transaction_threshold", 200000) if config else 200000
        )
        self.active_address_threshold = (
            config.get("active_address_threshold", 500000) if config else 500000
        )
        self.network_value_threshold = (
            config.get("network_value_threshold", 0.1) if config else 0.1
        )

    def analyze(self, symbol: str, timeframe: Optional[str] = None) -> dict[str, Any]:
        """Analyze on-chain metrics and generate trading signal.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing on-chain analysis results
        """
        # Generate mock on-chain data
        onchain_data = self._get_mock_onchain_data(symbol)

        # Calculate on-chain score
        onchain_score = self._calculate_onchain_score(onchain_data)

        # Determine signal strength
        signal_strength = abs(onchain_score)

        # Generate entry price (mock)
        entry_price = self._get_mock_entry_price(symbol)

        # Calculate stop loss and take profit
        stop_loss, take_profit = self._calculate_stop_take_profit(
            entry_price, onchain_score
        )

        # Calculate volatility (mock)
        volatility = self._get_mock_volatility()

        return {
            "score": onchain_score,
            "signal_strength": signal_strength,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volatility": volatility,
            "confidence": min(signal_strength + 0.1, 1.0),
            "metadata": {
                "onchain_data": onchain_data,
                "timeframe": timeframe or "1h",
                "strategy": "on_chain",
            },
        }

    def _get_mock_onchain_data(self, symbol: str) -> dict[str, Any]:
        """Generate mock on-chain data."""
        return {
            "hash_rate": random.uniform(50000, 500000),  # TH/s
            "difficulty": random.uniform(20000000000, 50000000000),
            "transaction_count": random.randint(100000, 500000),
            "transaction_volume": random.uniform(1000000, 10000000),  # BTC
            "active_addresses": random.randint(300000, 2000000),
            "network_value": random.uniform(500000000000, 1000000000000),  # USD
            "exchange_flows": {
                "inflows": random.uniform(0, 10000),  # BTC
                "outflows": random.uniform(0, 10000),  # BTC
            },
            "mining_difficulty_change": random.uniform(-0.1, 0.1),  # -10% to +10%
            "network_health_score": random.uniform(0.5, 1.0),
        }

    def _calculate_onchain_score(self, onchain_data: dict[str, Any]) -> float:
        """Calculate on-chain score from data."""
        hash_rate = onchain_data["hash_rate"]
        transaction_count = onchain_data["transaction_count"]
        active_addresses = onchain_data["active_addresses"]
        network_value = onchain_data["network_value"]
        exchange_flows = onchain_data["exchange_flows"]
        difficulty_change = onchain_data["mining_difficulty_change"]
        health_score = onchain_data["network_health_score"]

        # Hash rate component
        if hash_rate > self.hash_rate_threshold:
            hash_score = 0.2
        else:
            hash_score = -0.1

        # Transaction activity component
        if transaction_count > self.transaction_threshold:
            tx_score = 0.2
        else:
            tx_score = -0.1

        # Active addresses component
        if active_addresses > self.active_address_threshold:
            address_score = 0.2
        else:
            address_score = -0.1

        # Exchange flows component
        net_flow = exchange_flows["outflows"] - exchange_flows["inflows"]
        if net_flow > 0:
            flow_score = 0.2  # Net outflow (bullish)
        else:
            flow_score = -0.1  # Net inflow (bearish)

        # Difficulty change component
        if difficulty_change > 0:
            difficulty_score = 0.1  # Increasing difficulty (network growth)
        else:
            difficulty_score = -0.1  # Decreasing difficulty (network decline)

        # Network health component
        health_component = (health_score - 0.5) * 0.4  # -0.2 to +0.2

        # Combine scores
        total_score = (
            hash_score
            + tx_score
            + address_score
            + flow_score
            + difficulty_score
            + health_component
        )

        # Add randomness for demonstration
        total_score += random.uniform(-0.1, 0.1)

        return max(-1.0, min(1.0, total_score))

    def _get_mock_entry_price(self, symbol: str) -> float:
        """Generate mock entry price."""
        base_prices = {"BTC/USDT": 50000, "ETH/USDT": 3000, "ADA/USDT": 0.5}
        base_price = base_prices.get(symbol, 100)
        return base_price * random.uniform(0.98, 1.02)

    def _calculate_stop_take_profit(
        self, entry_price: float, onchain_score: float
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit."""
        if abs(onchain_score) < 0.3:
            return None, None

        risk_percent = 0.02  # 2% risk
        reward_percent = 0.04  # 4% reward

        if onchain_score > 0:
            stop_loss = entry_price * (1 - risk_percent)
            take_profit = entry_price * (1 + reward_percent)
        else:
            stop_loss = entry_price * (1 + risk_percent)
            take_profit = entry_price * (1 - reward_percent)

        return stop_loss, take_profit

    def _get_mock_volatility(self) -> float:
        """Generate mock volatility."""
        return random.uniform(0.02, 0.06)  # 2% to 6% volatility

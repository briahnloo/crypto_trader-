"""
Arbitrage execution and opportunity finder.
"""

import random
from typing import Any, Optional

from ...core.logging_utils import LoggerMixin
from ...data.engine import ProfitOptimizedDataEngine


class ArbitrageFinder(LoggerMixin):
    """
    Arbitrage opportunity finder that discovers price discrepancies across exchanges.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the arbitrage finder.

        Args:
            config: Arbitrage finder configuration (optional)
        """
        super().__init__()
        self.config = config or {}

        # Arbitrage parameters
        self.min_profit_threshold = self.config.get(
            "min_profit_threshold", 0.002
        )  # 0.2% minimum profit
        self.max_spread_threshold = self.config.get(
            "max_spread_threshold", 0.01
        )  # 1% maximum spread
        self.min_volume_threshold = self.config.get(
            "min_volume_threshold", 1000
        )  # $1000 minimum volume
        self.max_execution_time = self.config.get(
            "max_execution_time", 30
        )  # 30 seconds max execution
        
        # Cost simulation parameters
        self.exchange_fees = self.config.get("exchange_fees", {
            "binance": {"maker": 0.001, "taker": 0.001},  # 0.1% each
            "coinbase": {"maker": 0.005, "taker": 0.005},  # 0.5% each
            "coingecko": {"maker": 0.002, "taker": 0.002},  # 0.2% each
            "kraken": {"maker": 0.0016, "taker": 0.0026},  # 0.16%/0.26%
            "huobi": {"maker": 0.002, "taker": 0.002},  # 0.2% each
        })
        
        self.transfer_times = self.config.get("transfer_times", {
            "binance": {"deposit": 5, "withdrawal": 10},  # seconds
            "coinbase": {"deposit": 10, "withdrawal": 15},
            "coingecko": {"deposit": 3, "withdrawal": 5},
            "kraken": {"deposit": 8, "withdrawal": 12},
            "huobi": {"deposit": 6, "withdrawal": 8},
        })
        
        self.transfer_fees = self.config.get("transfer_fees", {
            "BTC": 0.0005,  # 0.05% of value
            "ETH": 0.001,   # 0.1% of value
            "USDT": 0.0001, # 0.01% of value
            "default": 0.0005,
        })
        
        self.slippage_params = self.config.get("slippage_params", {
            "base_slippage": 0.0005,  # 0.05% base slippage
            "volume_impact": 0.0001,  # 0.01% per $10k volume
            "max_slippage": 0.01,     # 1% maximum slippage
        })

        # Exchange configuration
        self.exchanges = self.config.get(
            "exchanges", ["binance", "coinbase", "coingecko"]
        )
        self.supported_symbols = self.config.get(
            "supported_symbols",
            [
                "BTC/USDT",
                "ETH/USDT",
                "ADA/USDT",
                "DOT/USDT",
                "SOL/USDT",
                "BNB/USDT",
                "MATIC/USDT",
                "AVAX/USDT",
                "LINK/USDT",
                "UNI/USDT",
            ],
        )

        # Data engine for price fetching
        self.data_engine = None
        self.initialized = False

    def initialize(self) -> None:
        """Initialize the arbitrage finder."""
        if self.initialized:
            self.logger.info("ArbitrageFinder already initialized")
            return

        self.logger.info("Initializing ArbitrageFinder")

        # Initialize data engine
        try:
            self.data_engine = ProfitOptimizedDataEngine()
            self.data_engine.initialize()
            self.logger.info("Data engine initialized successfully")
        except Exception as e:
            self.logger.warning(f"Failed to initialize data engine: {e}")
            self.logger.info("Will use mock data for arbitrage opportunities")

        self.initialized = True
        self.logger.info(f"Min profit threshold: {self.min_profit_threshold:.1%}")
        self.logger.info(f"Supported symbols: {len(self.supported_symbols)}")

    def find_arbitrage_opportunities(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Find arbitrage opportunities across exchanges for given symbols.

        Args:
            symbols: List of trading symbols to analyze

        Returns:
            List of arbitrage opportunities sorted by profit percentage (descending)
        """
        if not self.initialized:
            self.initialize()

        self.logger.debug(f"Finding arbitrage opportunities for {len(symbols)} symbols")

        opportunities = []

        for symbol in symbols:
            try:
                # Get prices from different exchanges
                exchange_prices = self._get_exchange_prices(symbol)

                if not exchange_prices:
                    self.logger.debug(f"No price data available for {symbol}")
                    continue

                # Find arbitrage opportunities for this symbol
                symbol_opportunities = self._find_symbol_arbitrage(
                    symbol, exchange_prices
                )
                opportunities.extend(symbol_opportunities)

            except Exception as e:
                self.logger.warning(f"Error processing {symbol}: {e}")
                continue

        # Sort opportunities by profit percentage (descending)
        opportunities.sort(key=lambda x: x.get("profit_percentage", 0), reverse=True)

        self.logger.info(f"Found {len(opportunities)} arbitrage opportunities")

        return opportunities

    def _get_exchange_prices(self, symbol: str) -> dict[str, dict[str, Any]]:
        """Get prices from different exchanges for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary of exchange prices
        """
        exchange_prices = {}

        if self.data_engine:
            # Try to get real prices from data engine
            try:
                for exchange in self.exchanges:
                    try:
                        ticker_data = self.data_engine.get_ticker(symbol)
                        if ticker_data and "price" in ticker_data:
                            exchange_prices[exchange] = {
                                "price": ticker_data["price"],
                                "volume": ticker_data.get("volume", 0),
                                "timestamp": ticker_data.get("timestamp", ""),
                                "source": "real",
                            }
                    except Exception as e:
                        self.logger.debug(f"Failed to get price from {exchange}: {e}")
                        continue
            except Exception as e:
                self.logger.debug(f"Data engine error: {e}")

        # If no real prices available, use mock data
        if not exchange_prices:
            exchange_prices = self._generate_mock_prices(symbol)

        return exchange_prices

    def _generate_mock_prices(self, symbol: str) -> dict[str, dict[str, Any]]:
        """Generate mock prices for testing/offline mode.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary of mock exchange prices
        """
        # Base price for different symbols
        base_prices = {
            "BTC/USDT": 50000,
            "ETH/USDT": 3000,
            "ADA/USDT": 0.5,
            "DOT/USDT": 7.0,
            "SOL/USDT": 100,
            "BNB/USDT": 300,
            "MATIC/USDT": 0.8,
            "AVAX/USDT": 25,
            "LINK/USDT": 15,
            "UNI/USDT": 6,
        }

        base_price = base_prices.get(symbol, 100.0)

        # Generate prices with slight variations across exchanges
        mock_prices = {}
        for exchange in self.exchanges:
            # Add random variation (-0.5% to +0.5%)
            variation = random.uniform(-0.005, 0.005)
            price = base_price * (1 + variation)

            # Generate volume
            volume = random.uniform(10000, 100000)

            mock_prices[exchange] = {
                "price": price,
                "volume": volume,
                "timestamp": "mock",
                "source": "mock",
            }

        return mock_prices

    def _find_symbol_arbitrage(
        self, symbol: str, exchange_prices: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find arbitrage opportunities for a specific symbol.

        Args:
            symbol: Trading symbol
            exchange_prices: Prices from different exchanges

        Returns:
            List of arbitrage opportunities for this symbol
        """
        opportunities = []

        if len(exchange_prices) < 2:
            return opportunities

        # Get all exchange pairs
        exchanges = list(exchange_prices.keys())

        for i, buy_exchange in enumerate(exchanges):
            for j, sell_exchange in enumerate(exchanges):
                if i >= j:  # Avoid duplicate pairs and self-pairs
                    continue

                try:
                    buy_price = exchange_prices[buy_exchange]["price"]
                    sell_price = exchange_prices[sell_exchange]["price"]
                    buy_volume = exchange_prices[buy_exchange]["volume"]
                    sell_volume = exchange_prices[sell_exchange]["volume"]

                    # Validate prices
                    if not self._validate_prices(
                        buy_price, sell_price, buy_volume, sell_volume
                    ):
                        continue

                    # Calculate arbitrage opportunity
                    opportunity = self._calculate_arbitrage_opportunity(
                        symbol,
                        buy_exchange,
                        sell_exchange,
                        buy_price,
                        sell_price,
                        buy_volume,
                        sell_volume,
                    )

                    if opportunity:
                        opportunities.append(opportunity)

                except Exception as e:
                    self.logger.debug(
                        f"Error calculating arbitrage for {symbol} "
                        f"({buy_exchange} -> {sell_exchange}): {e}"
                    )
                    continue

        return opportunities

    def _validate_prices(
        self, buy_price: float, sell_price: float, buy_volume: float, sell_volume: float
    ) -> bool:
        """Validate price data for arbitrage calculation.

        Args:
            buy_price: Buy price
            sell_price: Sell price
            buy_volume: Buy volume
            sell_volume: Sell volume

        Returns:
            True if prices are valid, False otherwise
        """
        # Check for valid prices
        if buy_price <= 0 or sell_price <= 0:
            return False

        # Check for reasonable price range (not too far apart)
        price_ratio = max(buy_price, sell_price) / min(buy_price, sell_price)
        if price_ratio > (1 + self.max_spread_threshold):
            return False

        # Check for minimum volume
        if (
            buy_volume < self.min_volume_threshold
            or sell_volume < self.min_volume_threshold
        ):
            return False

        return True

    def _calculate_arbitrage_opportunity(
        self,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        buy_price: float,
        sell_price: float,
        buy_volume: float,
        sell_volume: float,
    ) -> Optional[dict[str, Any]]:
        """Calculate arbitrage opportunity with comprehensive cost simulation.

        Args:
            symbol: Trading symbol
            buy_exchange: Exchange to buy from
            sell_exchange: Exchange to sell to
            buy_price: Buy price
            sell_price: Sell price
            buy_volume: Buy volume
            sell_volume: Sell volume

        Returns:
            Arbitrage opportunity dictionary or None if no opportunity
        """
        # Calculate raw profit percentage
        if sell_price > buy_price:
            # Buy on buy_exchange, sell on sell_exchange
            raw_profit_percentage = (sell_price - buy_price) / buy_price
            direction = "buy_sell"
        else:
            # Buy on sell_exchange, sell on buy_exchange
            raw_profit_percentage = (buy_price - sell_price) / sell_price
            direction = "sell_buy"
            # Swap exchanges for consistency
            buy_exchange, sell_exchange = sell_exchange, buy_exchange
            buy_price, sell_price = sell_price, buy_price

        # Check minimum raw profit threshold
        if raw_profit_percentage < self.min_profit_threshold:
            return None

        # Calculate maximum tradeable amount (limited by volume)
        max_volume = min(buy_volume, sell_volume)
        max_trade_amount = max_volume * 0.1  # Use 10% of available volume

        # Calculate raw expected profit
        raw_expected_profit = max_trade_amount * raw_profit_percentage

        # Simulate comprehensive costs
        cost_breakdown = self._simulate_arbitrage_costs(
            symbol, buy_exchange, sell_exchange, max_trade_amount, buy_price, sell_price
        )

        # Calculate net profit after all costs
        total_costs = cost_breakdown["total_costs"]
        net_profit = raw_expected_profit - total_costs
        net_profit_percentage = net_profit / max_trade_amount if max_trade_amount > 0 else 0

        # Check if net profit is still positive after all costs
        if net_profit <= 0:
            self.logger.debug(
                f"Arbitrage opportunity dropped: raw profit {raw_profit_percentage:.3%}, "
                f"costs {total_costs:.2f}, net profit {net_profit:.2f}"
            )
            return None

        # Calculate execution time estimate
        execution_time = self._estimate_execution_time(buy_exchange, sell_exchange)

        # Check execution time limit
        if execution_time > self.max_execution_time:
            return None

        return {
            "symbol": symbol,
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "raw_profit_percentage": raw_profit_percentage,
            "net_profit_percentage": net_profit_percentage,
            "max_trade_amount": max_trade_amount,
            "raw_expected_profit": raw_expected_profit,
            "net_profit": net_profit,
            "cost_breakdown": cost_breakdown,
            "execution_time": execution_time,
            "direction": direction,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "confidence": self._calculate_confidence(
                net_profit_percentage, max_volume, execution_time
            ),
        }

    def _simulate_arbitrage_costs(
        self,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        trade_amount: float,
        buy_price: float,
        sell_price: float,
    ) -> dict[str, Any]:
        """Simulate comprehensive arbitrage costs including fees, transfers, and slippage.

        Args:
            symbol: Trading symbol
            buy_exchange: Exchange to buy from
            sell_exchange: Exchange to sell to
            trade_amount: Trade amount in USD
            buy_price: Buy price
            sell_price: Sell price

        Returns:
            Dictionary with detailed cost breakdown
        """
        # 1. Trading fees
        buy_fee_rate = self.exchange_fees.get(buy_exchange, {}).get("taker", 0.002)
        sell_fee_rate = self.exchange_fees.get(sell_exchange, {}).get("taker", 0.002)
        
        buy_fee = trade_amount * buy_fee_rate
        sell_fee = trade_amount * sell_fee_rate
        total_trading_fees = buy_fee + sell_fee

        # 2. Transfer fees (if different exchanges)
        transfer_fee = 0.0
        if buy_exchange != sell_exchange:
            # Extract base currency from symbol (e.g., BTC from BTC/USDT)
            base_currency = symbol.split("/")[0]
            transfer_fee_rate = self.transfer_fees.get(base_currency, self.transfer_fees.get("default", 0.0005))
            transfer_fee = trade_amount * transfer_fee_rate

        # 3. Slippage costs
        slippage_costs = self._calculate_slippage_costs(
            symbol, trade_amount, buy_price, sell_price
        )

        # 4. Opportunity cost (time value of money)
        execution_time = self._estimate_execution_time(buy_exchange, sell_exchange)
        opportunity_cost = self._calculate_opportunity_cost(trade_amount, execution_time)

        # 5. Network fees (blockchain transaction costs)
        network_fees = self._estimate_network_fees(symbol, trade_amount)

        # 6. Price impact costs (market impact)
        price_impact_costs = self._calculate_price_impact_costs(
            symbol, trade_amount, buy_price, sell_price
        )

        # Calculate total costs
        total_costs = (
            total_trading_fees +
            transfer_fee +
            slippage_costs +
            opportunity_cost +
            network_fees +
            price_impact_costs
        )

        return {
            "trading_fees": {
                "buy_fee": buy_fee,
                "sell_fee": sell_fee,
                "total": total_trading_fees,
            },
            "transfer_fee": transfer_fee,
            "slippage_costs": slippage_costs,
            "opportunity_cost": opportunity_cost,
            "network_fees": network_fees,
            "price_impact_costs": price_impact_costs,
            "total_costs": total_costs,
            "cost_breakdown_percentage": total_costs / trade_amount if trade_amount > 0 else 0,
        }

    def _calculate_slippage_costs(
        self, symbol: str, trade_amount: float, buy_price: float, sell_price: float
    ) -> float:
        """Calculate slippage costs based on order size and market liquidity.

        Args:
            symbol: Trading symbol
            trade_amount: Trade amount in USD
            buy_price: Buy price
            sell_price: Sell price

        Returns:
            Slippage cost in USD
        """
        # Base slippage
        base_slippage = self.slippage_params["base_slippage"]
        
        # Volume impact slippage (higher volume = more slippage)
        volume_impact = self.slippage_params["volume_impact"]
        volume_slippage = (trade_amount / 10000) * volume_impact  # $10k increments
        
        # Total slippage rate
        total_slippage_rate = min(
            base_slippage + volume_slippage,
            self.slippage_params["max_slippage"]
        )
        
        # Calculate slippage cost (average of buy and sell slippage)
        avg_price = (buy_price + sell_price) / 2
        slippage_cost = trade_amount * total_slippage_rate
        
        return slippage_cost

    def _calculate_opportunity_cost(self, trade_amount: float, execution_time: float) -> float:
        """Calculate opportunity cost based on execution time.

        Args:
            trade_amount: Trade amount in USD
            execution_time: Execution time in seconds

        Returns:
            Opportunity cost in USD
        """
        # Assume 5% annual return opportunity cost
        annual_return_rate = 0.05
        time_cost_rate = (execution_time / (365 * 24 * 3600)) * annual_return_rate
        opportunity_cost = trade_amount * time_cost_rate
        
        return opportunity_cost

    def _estimate_network_fees(self, symbol: str, trade_amount: float) -> float:
        """Estimate blockchain network fees.

        Args:
            symbol: Trading symbol
            trade_amount: Trade amount in USD

        Returns:
            Network fees in USD
        """
        # Base currency network fees (simplified)
        base_currency = symbol.split("/")[0]
        
        network_fee_rates = {
            "BTC": 0.0001,   # 0.01% of value
            "ETH": 0.0002,   # 0.02% of value
            "USDT": 0.00005, # 0.005% of value
            "default": 0.0001,
        }
        
        fee_rate = network_fee_rates.get(base_currency, network_fee_rates["default"])
        network_fees = trade_amount * fee_rate
        
        return network_fees

    def _calculate_price_impact_costs(
        self, symbol: str, trade_amount: float, buy_price: float, sell_price: float
    ) -> float:
        """Calculate price impact costs from market orders.

        Args:
            symbol: Trading symbol
            trade_amount: Trade amount in USD
            buy_price: Buy price
            sell_price: Sell price

        Returns:
            Price impact cost in USD
        """
        # Price impact increases with trade size
        # Assume 0.01% impact per $10k trade size
        impact_rate = (trade_amount / 10000) * 0.0001
        impact_rate = min(impact_rate, 0.005)  # Cap at 0.5%
        
        # Calculate impact cost
        avg_price = (buy_price + sell_price) / 2
        price_impact_cost = trade_amount * impact_rate
        
        return price_impact_cost

    def _estimate_execution_time(self, buy_exchange: str, sell_exchange: str) -> float:
        """Estimate execution time for arbitrage trade including transfer times.

        Args:
            buy_exchange: Buy exchange
            sell_exchange: Sell exchange

        Returns:
            Estimated execution time in seconds
        """
        # Base execution times for different exchanges
        exchange_times = {"binance": 2.0, "coinbase": 3.0, "coingecko": 1.0}

        buy_time = exchange_times.get(buy_exchange, 2.5)
        sell_time = exchange_times.get(sell_exchange, 2.5)

        # Add transfer times if different exchanges
        transfer_time = 0.0
        if buy_exchange != sell_exchange:
            buy_transfer = self.transfer_times.get(buy_exchange, {}).get("withdrawal", 10)
            sell_transfer = self.transfer_times.get(sell_exchange, {}).get("deposit", 10)
            transfer_time = buy_transfer + sell_transfer

        # Add network latency and processing time
        total_time = buy_time + sell_time + transfer_time + 1.0

        return total_time

    def _calculate_confidence(
        self, profit_percentage: float, volume: float, execution_time: float
    ) -> float:
        """Calculate confidence score for arbitrage opportunity.

        Args:
            profit_percentage: Profit percentage
            volume: Available volume
            execution_time: Execution time

        Returns:
            Confidence score (0 to 1)
        """
        # Higher profit = higher confidence
        profit_score = min(1.0, profit_percentage / 0.01)  # Normalize to 1% profit

        # Higher volume = higher confidence
        volume_score = min(1.0, volume / 50000)  # Normalize to $50k volume

        # Lower execution time = higher confidence
        time_score = max(0.0, 1.0 - (execution_time / 60.0))  # Normalize to 60 seconds

        # Weighted average
        confidence = (profit_score * 0.5) + (volume_score * 0.3) + (time_score * 0.2)

        return min(1.0, max(0.0, confidence))

    def get_opportunity_summary(
        self, opportunities: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Get summary of arbitrage opportunities.

        Args:
            opportunities: List of arbitrage opportunities

        Returns:
            Summary dictionary
        """
        if not opportunities:
            return {
                "total_opportunities": 0,
                "total_profit_potential": 0.0,
                "average_profit_percentage": 0.0,
                "best_opportunity": None,
                "symbols_with_opportunities": [],
                "exchange_pairs": [],
            }

        total_profit = sum(opp.get("net_profit", 0) for opp in opportunities)
        avg_profit_pct = sum(
            opp.get("profit_percentage", 0) for opp in opportunities
        ) / len(opportunities)

        symbols = list(set(opp["symbol"] for opp in opportunities))
        exchange_pairs = list(
            set(
                f"{opp['buy_exchange']}-{opp['sell_exchange']}" for opp in opportunities
            )
        )

        best_opportunity = max(
            opportunities, key=lambda x: x.get("profit_percentage", 0)
        )

        return {
            "total_opportunities": len(opportunities),
            "total_profit_potential": total_profit,
            "average_profit_percentage": avg_profit_pct,
            "best_opportunity": best_opportunity,
            "symbols_with_opportunities": symbols,
            "exchange_pairs": exchange_pairs,
        }

    def update_config(self, new_config: dict[str, Any]) -> None:
        """Update configuration parameters.

        Args:
            new_config: New configuration parameters
        """
        self.config.update(new_config)

        # Update instance variables
        self.min_profit_threshold = self.config.get(
            "min_profit_threshold", self.min_profit_threshold
        )
        self.max_spread_threshold = self.config.get(
            "max_spread_threshold", self.max_spread_threshold
        )
        self.min_volume_threshold = self.config.get(
            "min_volume_threshold", self.min_volume_threshold
        )
        self.max_execution_time = self.config.get(
            "max_execution_time", self.max_execution_time
        )

        self.logger.info("Configuration updated")

    def get_config(self) -> dict[str, Any]:
        """Get current configuration.

        Returns:
            Current configuration
        """
        return self.config.copy()

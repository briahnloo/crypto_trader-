"""
Multi-strategy executor that coordinates between individual strategy executors and risk management.
"""

from typing import Any, Optional

from ..core.logging_utils import LoggerMixin
from ..risk.risk_manager import ProfitOptimizedRiskManager
from .executors import (
    ArbitrageExecutor,
    BaseExecutor,
    BreakoutExecutor,
    MarketMakingExecutor,
    MomentumExecutor,
    SentimentExecutor,
)


class MultiStrategyExecutor(LoggerMixin):
    """
    Multi-strategy executor that coordinates between individual strategy executors
    and the risk manager for optimal position sizing and execution.
    """

    def __init__(
        self,
        risk_manager: Optional[ProfitOptimizedRiskManager] = None,
        executor_configs: Optional[dict[str, dict[str, Any]]] = None,
    ):
        """Initialize the multi-strategy executor.

        Args:
            risk_manager: Profit-optimized risk manager instance
            executor_configs: Configuration for individual executors
        """
        super().__init__()

        # Initialize risk manager
        self.risk_manager = risk_manager or ProfitOptimizedRiskManager()

        # Initialize individual executors
        self.executors: dict[str, BaseExecutor] = {}
        self._initialize_executors(executor_configs or {})

        # Execution tracking
        self.execution_history: list = []
        self.initialized = False

    def _initialize_executors(
        self, executor_configs: dict[str, dict[str, Any]]
    ) -> None:
        """Initialize individual strategy executors.

        Args:
            executor_configs: Configuration for each executor
        """
        # Default executor configurations
        default_configs = {
            "momentum": {
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.06,
                "momentum_threshold": 0.6,
            },
            "breakout": {
                "stop_loss_pct": 0.015,
                "take_profit_pct": 0.045,
                "breakout_threshold": 0.7,
                "volume_confirmation": True,
            },
            "arbitrage": {
                "min_profit_pct": 0.005,
                "max_position_size": 0.5,
                "execution_time_limit": 30,
            },
            "market_making": {
                "spread_pct": 0.002,
                "max_position_size": 0.1,
                "inventory_limit": 0.05,
            },
            "sentiment": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.08,
                "sentiment_threshold": 0.6,
            },
        }

        # Merge default configs with provided configs
        configs = {**default_configs, **executor_configs}

        # Initialize executors
        self.executors = {
            "momentum": MomentumExecutor(configs.get("momentum", {})),
            "breakout": BreakoutExecutor(configs.get("breakout", {})),
            "arbitrage": ArbitrageExecutor(configs.get("arbitrage", {})),
            "market_making": MarketMakingExecutor(configs.get("market_making", {})),
            "sentiment": SentimentExecutor(configs.get("sentiment", {})),
        }

        self.logger.info(f"Initialized {len(self.executors)} strategy executors")

    def initialize(self) -> None:
        """Initialize the multi-strategy executor."""
        if self.initialized:
            self.logger.info("MultiStrategyExecutor already initialized")
            return

        self.logger.info("Initializing MultiStrategyExecutor")

        # Initialize risk manager
        self.risk_manager.initialize()

        # Initialize all executors
        for name, executor in self.executors.items():
            executor.initialize()
            self.logger.debug(f"Initialized {name} executor")

        self.initialized = True
        self.logger.info("MultiStrategyExecutor initialization complete")

    def execute_strategy(
        self, strategy_name: str, signal: dict[str, Any], capital: float
    ) -> dict[str, Any]:
        """Execute a trading strategy with risk management.

        Args:
            strategy_name: Name of the strategy to execute
            signal: Trading signal data
            capital: Available capital for the trade

        Returns:
            Trade dictionary containing:
            - strategy: Strategy name
            - symbol: Trading symbol
            - position_size: Optimal position size
            - entry_price: Entry price
            - execution_result: Result from strategy executor
            - expected_profit: Expected profit calculation
        """
        if not self.initialized:
            self.initialize()

        # Validate strategy name
        if strategy_name not in self.executors:
            self.logger.error(f"Unknown strategy: {strategy_name}")
            return self._empty_trade_result(strategy_name, signal)

        # Get executor
        executor = self.executors[strategy_name]

        # Extract signal information
        symbol = signal.get("symbol", "")
        current_price = signal.get("current_price", 0.0)

        if not symbol or current_price <= 0:
            self.logger.error(
                f"Invalid signal data: symbol={symbol}, price={current_price}"
            )
            return self._empty_trade_result(strategy_name, signal)

        self.logger.debug(f"Executing {strategy_name} strategy for {symbol}")

        # Calculate optimal position size using risk manager
        position_data = {"available_capital": capital, "current_price": current_price}

        # Extract stop loss and take profit from signal if available
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")
        
        risk_result = self.risk_manager.calculate_optimal_position_size(
            symbol=symbol,
            signal_data=signal,
            current_price=current_price,
            portfolio_value=capital,
        )

        position_size = risk_result.get("position_size", 0.0)

        if position_size <= 0:
            self.logger.info(
                f"No position size calculated for {symbol} with {strategy_name}"
            )
            return {"status": "rejected", "reason": "risk_rejected"}

        # Prepare position data for executor
        position = {
            "available_capital": capital,
            "position_size": position_size,
            "current_price": current_price,
            "risk_metrics": risk_result.get("metadata", {}),
        }

        # Execute strategy
        execution_result = executor.execute(signal, position)

        # Apply entry price fallback logic
        entry_price = execution_result.get("entry_price", 0.0)
        
        # Fallback logic: if strategy price is invalid, use market price
        if entry_price is None or entry_price <= 0:
            # Get market price as fallback
            market_price = signal.get("current_price", 0.0)
            if market_price and market_price > 0:
                entry_price = market_price
                execution_result["entry_price"] = entry_price
                execution_result["price_source"] = "market_fallback"
                self.logger.debug(f"Using market price fallback for {symbol}: ${entry_price:.2f}")
            else:
                # Still invalid - reject before portfolio update
                self.logger.warning(f"Invalid entry price for {symbol}: strategy={execution_result.get('entry_price')}, market={market_price}")
                return {"status": "rejected", "reason": "invalid_entry_price"}

        # Calculate expected profit
        expected_profit = self._calculate_expected_profit(
            signal, position_size, execution_result
        )

        # Create trade result
        trade_result = {
            "strategy": strategy_name,
            "symbol": symbol,
            "position_size": position_size,
            "entry_price": entry_price,
            "execution_result": execution_result,
            "expected_profit": expected_profit,
            "risk_metrics": risk_result.get("metadata", {}),
            "capital_used": position_size * entry_price,
            "risk_adjusted": risk_result.get("max_risk_respected", False),
        }

        # Track execution
        self.execution_history.append(trade_result)

        self.logger.info(
            f"Executed {strategy_name} for {symbol}: "
            f"size={position_size:.4f}, entry={execution_result.get('entry_price', 0):.2f}, "
            f"expected_profit={expected_profit:.2f}"
        )

        return trade_result

    def _calculate_expected_profit(
        self,
        signal: dict[str, Any],
        position_size: float,
        execution_result: dict[str, Any],
    ) -> float:
        """Calculate expected profit for a trade.

        Args:
            signal: Trading signal data
            position_size: Position size
            execution_result: Execution result from strategy executor

        Returns:
            Expected profit
        """
        # Get execution data
        entry_price = execution_result.get("entry_price", 0.0)
        stop_loss = execution_result.get("stop_loss", 0.0)
        take_profit = execution_result.get("take_profit", 0.0)
        side = execution_result.get("side", "buy")
        fees = execution_result.get("fees", 0.0)

        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return 0.0

        # Calculate profit and loss scenarios
        if side.lower() == "buy":
            # Long position
            profit_scenario = (take_profit - entry_price) * position_size
            loss_scenario = (entry_price - stop_loss) * position_size
        else:
            # Short position
            profit_scenario = (entry_price - take_profit) * position_size
            loss_scenario = (stop_loss - entry_price) * position_size

        # Get signal confidence for win rate estimation
        confidence = signal.get("confidence", 0.5)
        signal_strength = signal.get("signal_strength", 0.5)

        # Estimate win rate based on signal quality
        win_rate = (confidence + signal_strength) / 2

        # Calculate expected profit
        expected_profit = (win_rate * profit_scenario) + (
            (1 - win_rate) * loss_scenario
        )

        # Subtract fees
        expected_profit -= fees

        return expected_profit

    def _empty_trade_result(
        self, strategy_name: str, signal: dict[str, Any]
    ) -> dict[str, Any]:
        """Return empty trade result.

        Args:
            strategy_name: Strategy name
            signal: Signal data

        Returns:
            Empty trade result
        """
        return {
            "strategy": strategy_name,
            "symbol": signal.get("symbol", ""),
            "position_size": 0.0,
            "entry_price": 0.0,
            "execution_result": {
                "filled": False,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "fees": 0.0,
                "expected_pnl": 0.0,
                "strategy": strategy_name,
            },
            "expected_profit": 0.0,
            "risk_metrics": {},
            "capital_used": 0.0,
            "risk_adjusted": False,
        }

    def get_available_strategies(self) -> list:
        """Get list of available strategy names.

        Returns:
            List of strategy names
        """
        return list(self.executors.keys())

    def get_strategy_info(self, strategy_name: str) -> dict[str, Any]:
        """Get information about a specific strategy.

        Args:
            strategy_name: Name of the strategy

        Returns:
            Strategy information
        """
        if strategy_name not in self.executors:
            return {"error": f"Strategy {strategy_name} not found"}

        executor = self.executors[strategy_name]
        return {
            "name": strategy_name,
            "class": executor.__class__.__name__,
            "config": executor.config,
            "initialized": executor.initialized,
        }

    def get_execution_summary(self) -> dict[str, Any]:
        """Get execution summary.

        Returns:
            Execution summary
        """
        total_trades = len(self.execution_history)
        successful_trades = len(
            [
                t
                for t in self.execution_history
                if t["execution_result"].get("filled", False)
            ]
        )

        total_capital_used = sum(t["capital_used"] for t in self.execution_history)
        total_expected_profit = sum(
            t["expected_profit"] for t in self.execution_history
        )

        strategy_counts = {}
        for trade in self.execution_history:
            strategy = trade["strategy"]
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        return {
            "total_trades": total_trades,
            "successful_trades": successful_trades,
            "success_rate": successful_trades / total_trades
            if total_trades > 0
            else 0.0,
            "total_capital_used": total_capital_used,
            "total_expected_profit": total_expected_profit,
            "strategy_distribution": strategy_counts,
            "available_strategies": self.get_available_strategies(),
        }

    def update_executor_config(
        self, strategy_name: str, config: dict[str, Any]
    ) -> bool:
        """Update configuration for a specific executor.

        Args:
            strategy_name: Name of the strategy
            config: New configuration

        Returns:
            True if successful, False otherwise
        """
        if strategy_name not in self.executors:
            self.logger.error(f"Unknown strategy: {strategy_name}")
            return False

        executor = self.executors[strategy_name]
        executor.config.update(config)

        self.logger.info(f"Updated configuration for {strategy_name} executor")
        return True

    def reset_execution_history(self) -> None:
        """Reset execution history."""
        self.execution_history.clear()
        self.logger.info("Execution history reset")

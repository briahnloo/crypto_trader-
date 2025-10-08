"""
Risk management system for cryptocurrency trading.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List

import numpy as np

from ..core.logging_utils import LoggerMixin


class RiskLevel(Enum):
    """Risk level enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    """Risk metrics data structure."""

    var_95: float
    var_99: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    beta: float
    correlation: float
    volatility: float
    risk_level: RiskLevel


@dataclass
class ExitAction:
    """Exit action suggestion data structure."""
    
    symbol: str
    qty: float
    reason: str
    price_hint: Optional[float] = None


class ProfitOptimizedRiskManager(LoggerMixin):
    """Profit-optimized risk manager with Kelly Criterion and volatility/correlation adjustments."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the profit-optimized risk manager.

        Args:
            config: Risk management configuration (optional)
        """
        super().__init__()
        self.initialized = False  # Set this first to avoid attribute errors
        self.config = config or {}

        # Risk limits from config
        self.max_risk_per_trade = self.config.get(
            "max_risk_per_trade", 0.02
        )  # 2% max risk per trade
        self.max_portfolio_risk = self.config.get(
            "max_portfolio_risk", 0.10
        )  # 10% max portfolio risk
        self.max_position_size = self.config.get(
            "max_position_size", 0.20
        )  # 20% max position size
        
        # New execution-based risk parameters from config
        self.per_symbol_cap_pct = self.config.get("per_symbol_cap_pct", 0.15)  # 15% per symbol cap
        self.session_cap_pct = self.config.get("session_cap_pct", 0.60)  # 60% session cap
        self.daily_max_loss_pct = self.config.get("daily_max_loss_pct", 0.02)  # 2% daily max loss
        
        # New risk-based sizing parameters
        self.risk_per_trade_pct = self.config.get(
            "risk_per_trade_pct", 0.25
        )  # 0.25% of equity per trade
        self.max_notional_pct = self.config.get(
            "max_notional_pct", 1.0
        )  # 1.0% max notional of equity
        self.kelly_fraction_limit = self.config.get(
            "kelly_fraction_limit", 0.25
        )  # 25% max Kelly fraction
        self.min_kelly_fraction = self.config.get(
            "min_kelly_fraction", 0.01
        )  # 1% min Kelly fraction

        # Volatility and correlation adjustments
        self.volatility_adjustment_factor = self.config.get(
            "volatility_adjustment_factor", 1.0
        )
        self.correlation_penalty_factor = self.config.get(
            "correlation_penalty_factor", 0.5
        )
        self.max_correlation = self.config.get("max_correlation", 0.7)

        # Kelly Criterion parameters
        self.kelly_safety_factor = self.config.get(
            "kelly_safety_factor", 0.5
        )  # Fractional Kelly
        self.min_win_rate = self.config.get(
            "min_win_rate", 0.45
        )  # Minimum win rate for Kelly
        self.min_profit_factor = self.config.get(
            "min_profit_factor", 1.1
        )  # Minimum profit factor

        # Portfolio tracking
        self.positions: dict[str, dict[str, Any]] = {}
        self.portfolio_value = self.config.get("initial_portfolio_value", 100000.0)
        self.risk_metrics: dict[str, RiskMetrics] = {}

    def initialize(self) -> None:
        """Initialize the risk manager."""
        if self.initialized:
            self.logger.info("ProfitOptimizedRiskManager already initialized")
            return

        self.logger.info("Initializing ProfitOptimizedRiskManager")
        self.logger.info(f"Max risk per trade: {self.max_risk_per_trade:.1%}")
        self.logger.info(f"Max portfolio risk: {self.max_portfolio_risk:.1%}")
        self.logger.info(f"Kelly safety factor: {self.kelly_safety_factor:.1%}")

        self.initialized = True

    def calculate_risk_based_position_size(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        current_price: float,
        portfolio_value: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict[str, Any]:
        """Calculate position size based on risk amount and stop loss.
        
        Args:
            symbol: Trading symbol
            signal_data: Signal data containing side and other info
            current_price: Current market price
            portfolio_value: Total portfolio value
            stop_loss: Stop loss price
            take_profit: Take profit price
            
        Returns:
            Dictionary with position size and risk metrics
        """
        if not portfolio_value:
            portfolio_value = self.portfolio_value
            
        if portfolio_value <= 0:
            self.logger.warning(f"Invalid portfolio value: {portfolio_value}")
            return {
                "position_size": 0.0,
                "risk_amount": 0.0,
                "notional_value": 0.0,
                "max_risk_respected": False,
                "max_notional_respected": False,
                "metadata": {"error": "invalid_portfolio_value"}
            }
        
        # Calculate risk amount as percentage of equity
        risk_amount = portfolio_value * (self.risk_per_trade_pct / 100)
        
        # Determine position side
        side = signal_data.get("side", "buy")
        if "score" in signal_data:
            side = "buy" if signal_data["score"] > 0 else "sell"
        
        # Calculate position size based on stop loss
        if stop_loss and stop_loss > 0:
            if side == "buy":
                # Long position: risk = (entry_price - stop_loss) * quantity
                price_diff = current_price - stop_loss
                if price_diff > 0:
                    position_size = risk_amount / price_diff
                else:
                    self.logger.warning(f"Invalid stop loss for long position: {stop_loss} >= {current_price}")
                    return self._empty_position_result()
            else:
                # Short position: risk = (stop_loss - entry_price) * quantity
                price_diff = stop_loss - current_price
                if price_diff > 0:
                    position_size = risk_amount / price_diff
                else:
                    self.logger.warning(f"Invalid stop loss for short position: {stop_loss} <= {current_price}")
                    return self._empty_position_result()
        else:
            # Fallback: use 0.25% of equity as position value
            position_value = portfolio_value * (self.risk_per_trade_pct / 100)
            position_size = position_value / current_price
            
        # Calculate notional value
        notional_value = abs(position_size) * current_price
        
        # Apply notional cap
        max_notional = portfolio_value * (self.max_notional_pct / 100)
        if notional_value > max_notional:
            position_size = (max_notional / current_price) * (1 if position_size > 0 else -1)
            notional_value = max_notional
            
        # Check if risk limits are respected
        actual_risk = risk_amount if stop_loss else notional_value * (self.risk_per_trade_pct / 100)
        max_risk_respected = actual_risk <= portfolio_value * (self.max_risk_per_trade)
        max_notional_respected = notional_value <= max_notional
        
        # Log the sizing calculation
        self.logger.info(
            f"sizing=risk_based risk_pct={self.risk_per_trade_pct}% qty={position_size:.4f} "
            f"notional=${notional_value:.2f} risk=${actual_risk:.2f} side={side}"
        )
        
        return {
            "position_size": position_size,
            "risk_amount": actual_risk,
            "notional_value": notional_value,
            "max_risk_respected": max_risk_respected,
            "max_notional_respected": max_notional_respected,
            "metadata": {
                "sizing_method": "risk_based",
                "risk_per_trade_pct": self.risk_per_trade_pct,
                "max_notional_pct": self.max_notional_pct,
                "side": side,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            }
        }
    
    def _empty_position_result(self) -> dict[str, Any]:
        """Return empty position result for invalid cases.
        
        Returns:
            Empty position result dictionary
        """
        return {
            "position_size": 0.0,
            "risk_amount": 0.0,
            "notional_value": 0.0,
            "max_risk_respected": False,
            "max_notional_respected": False,
            "metadata": {"error": "invalid_parameters"}
        }

    def calculate_optimal_position_size(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        current_price: float,
        portfolio_value: Optional[float] = None,
        volatility: Optional[float] = None,
        correlation: Optional[float] = None,
    ) -> dict[str, Any]:
        """Calculate optimal position size using Kelly Criterion with adjustments.

        Args:
            symbol: Trading symbol
            signal_data: Signal data from strategies (score, confidence, etc.)
            current_price: Current market price
            portfolio_value: Current portfolio value (optional)
            volatility: Asset volatility (optional)
            correlation: Correlation with portfolio (optional)

        Returns:
            Dictionary containing:
            - position_size: Optimal position size (> 0)
            - kelly_fraction: Kelly fraction used
            - risk_adjusted_size: Risk-adjusted position size
            - max_risk_respected: Whether max risk limits are respected
            - metadata: Additional calculation details
        """
        if not self.initialized:
            self.initialize()

        self.logger.debug(f"Calculating optimal position size for {symbol}")

        # Use provided portfolio value or default
        portfolio_value = portfolio_value or self.portfolio_value

        # Check if we should use risk-based sizing
        sizing_method = self.config.get("position_sizing", {}).get("method", "kelly_criterion")
        if sizing_method == "risk_based":
            # Extract stop loss and take profit from signal data
            stop_loss = signal_data.get("stop_loss")
            take_profit = signal_data.get("take_profit")
            
            # If not provided, try to calculate defaults
            if not stop_loss or not take_profit:
                try:
                    side = "buy" if signal_data.get("score", 0) > 0 else "sell"
                    sl_tp_result = self.calculate_sl_tp_defaults(
                        symbol=symbol,
                        entry_price=current_price,
                        side=side,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
                    stop_loss = sl_tp_result.get("stop_loss", stop_loss)
                    take_profit = sl_tp_result.get("take_profit", take_profit)
                except Exception as e:
                    self.logger.warning(f"Failed to calculate default SL/TP for {symbol}: {e}")
            
            # Use risk-based sizing
            return self.calculate_risk_based_position_size(
                symbol=symbol,
                signal_data=signal_data,
                current_price=current_price,
                portfolio_value=portfolio_value,
                stop_loss=stop_loss,
                take_profit=take_profit
            )

        # Extract signal information for legacy methods
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Estimate Kelly parameters
        win_rate = self._estimate_win_rate(signal_data)
        avg_win = self._estimate_avg_win(signal_data)
        avg_loss = self._estimate_avg_loss(signal_data)

        # Calculate Kelly fraction
        kelly_fraction = self._calculate_kelly_fraction(win_rate, avg_win, avg_loss)

        # Apply volatility adjustment
        volatility_adjustment = self._calculate_volatility_adjustment(volatility)

        # Apply correlation adjustment
        correlation_adjustment = self._calculate_correlation_adjustment(correlation)

        # Calculate base position size
        base_position_size = kelly_fraction * portfolio_value / current_price

        # Apply adjustments
        adjusted_position_size = (
            base_position_size * volatility_adjustment * correlation_adjustment
        )

        # Apply risk limits
        risk_limited_size = self._apply_risk_limits(
            adjusted_position_size, current_price, portfolio_value, signal_confidence
        )

        # Ensure position size is positive
        final_position_size = max(0.0, risk_limited_size)

        # Check if max risk is respected
        position_value = final_position_size * current_price
        position_risk = position_value / portfolio_value
        max_risk_respected = position_risk <= self.max_risk_per_trade

        result = {
            "position_size": final_position_size,
            "kelly_fraction": kelly_fraction,
            "risk_adjusted_size": risk_limited_size,
            "max_risk_respected": max_risk_respected,
            "metadata": {
                "symbol": symbol,
                "current_price": current_price,
                "portfolio_value": portfolio_value,
                "signal_score": signal_score,
                "signal_confidence": signal_confidence,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "volatility": volatility,
                "volatility_adjustment": volatility_adjustment,
                "correlation": correlation,
                "correlation_adjustment": correlation_adjustment,
                "position_value": position_value,
                "position_risk": position_risk,
                "max_risk_per_trade": self.max_risk_per_trade,
                "timestamp": datetime.now().isoformat(),
            },
        }

        self.logger.info(
            f"Position size for {symbol}: {final_position_size:.4f} "
            f"(Kelly: {kelly_fraction:.3f}, Risk: {position_risk:.1%})"
        )

        return result

    def _estimate_win_rate(self, signal_data: dict[str, Any]) -> float:
        """Estimate win rate from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated win rate (0 to 1)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base win rate from signal strength and confidence
        base_win_rate = (signal_strength + signal_confidence) / 2

        # Adjust based on signal score direction
        if signal_score > 0:
            # Positive signal - boost win rate
            score_adjustment = min(0.2, signal_score * 0.1)
        else:
            # Negative signal - reduce win rate
            score_adjustment = max(-0.2, signal_score * 0.1)

        estimated_win_rate = base_win_rate + score_adjustment

        # Clamp to reasonable bounds
        estimated_win_rate = max(self.min_win_rate, min(0.8, estimated_win_rate))

        return estimated_win_rate

    def _estimate_avg_win(self, signal_data: dict[str, Any]) -> float:
        """Estimate average win from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated average win (as decimal, e.g., 0.05 for 5%)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base average win from signal strength
        base_avg_win = signal_strength * 0.05  # Max 5% average win

        # Adjust based on signal score
        if signal_score > 0:
            score_adjustment = signal_score * 0.02  # Up to 2% additional
        else:
            score_adjustment = 0.0  # No win for negative signals

        # Adjust based on confidence
        confidence_adjustment = signal_confidence * 0.01  # Up to 1% additional

        estimated_avg_win = base_avg_win + score_adjustment + confidence_adjustment

        # Clamp to reasonable bounds
        estimated_avg_win = max(0.01, min(0.10, estimated_avg_win))  # 1% to 10%

        return estimated_avg_win

    def _estimate_avg_loss(self, signal_data: dict[str, Any]) -> float:
        """Estimate average loss from signal data.

        Args:
            signal_data: Signal data from strategies

        Returns:
            Estimated average loss (as decimal, e.g., 0.03 for 3%)
        """
        # Extract signal information
        signal_score = signal_data.get("score", 0.0)
        signal_confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)

        # Base average loss from signal strength (inverse relationship)
        base_avg_loss = (1.0 - signal_strength) * 0.04  # Max 4% average loss

        # Adjust based on signal score
        if signal_score < 0:
            score_adjustment = abs(signal_score) * 0.02  # Up to 2% additional loss
        else:
            score_adjustment = 0.0  # No additional loss for positive signals

        # Adjust based on confidence (lower confidence = higher loss)
        confidence_adjustment = (1.0 - signal_confidence) * 0.01  # Up to 1% additional

        estimated_avg_loss = base_avg_loss + score_adjustment + confidence_adjustment

        # Clamp to reasonable bounds
        estimated_avg_loss = max(0.01, min(0.08, estimated_avg_loss))  # 1% to 8%

        return estimated_avg_loss

    def _calculate_kelly_fraction(
        self, win_rate: float, avg_win: float, avg_loss: float
    ) -> float:
        """Calculate Kelly fraction.

        Args:
            win_rate: Win rate (0 to 1)
            avg_win: Average win (as decimal)
            avg_loss: Average loss (as decimal)

        Returns:
            Kelly fraction (0 to 1)
        """
        # Protect against division by zero
        if avg_loss <= 0:
            return 0.0

        # Kelly formula: f = (bp - q) / b
        # where b = avg_win/avg_loss, p = win_rate, q = 1 - win_rate
        b = avg_win / avg_loss
        p = win_rate
        q = 1.0 - win_rate

        kelly_fraction = (b * p - q) / b

        # Apply safety factor (fractional Kelly)
        kelly_fraction *= self.kelly_safety_factor

        # Clamp to limits
        kelly_fraction = max(0.0, min(self.kelly_fraction_limit, kelly_fraction))

        # Ensure minimum Kelly fraction for strong signals
        if kelly_fraction > 0 and kelly_fraction < self.min_kelly_fraction:
            kelly_fraction = self.min_kelly_fraction

        return kelly_fraction

    def _calculate_volatility_adjustment(self, volatility: Optional[float]) -> float:
        """Calculate volatility adjustment factor.

        Args:
            volatility: Asset volatility (optional)

        Returns:
            Volatility adjustment factor (0 to 1)
        """
        if volatility is None:
            return 1.0  # No adjustment if volatility unknown

        # Higher volatility = lower position size
        # Use inverse relationship with some smoothing
        adjustment = 1.0 / (1.0 + volatility * self.volatility_adjustment_factor)

        # Clamp to reasonable bounds
        adjustment = max(0.1, min(1.0, adjustment))

        return adjustment

    def _calculate_correlation_adjustment(self, correlation: Optional[float]) -> float:
        """Calculate correlation adjustment factor.

        Args:
            correlation: Correlation with portfolio (optional)

        Returns:
            Correlation adjustment factor (0 to 1)
        """
        if correlation is None:
            return 1.0  # No adjustment if correlation unknown

        # Higher correlation = lower position size (diversification benefit)
        abs_correlation = abs(correlation)

        if abs_correlation > self.max_correlation:
            # High correlation - significant penalty
            adjustment = 0.1
        else:
            # Moderate correlation - gradual penalty
            adjustment = 1.0 - (abs_correlation * self.correlation_penalty_factor)

        # Clamp to reasonable bounds
        adjustment = max(0.1, min(1.0, adjustment))

        return adjustment

    def _apply_risk_limits(
        self,
        position_size: float,
        current_price: float,
        portfolio_value: float,
        signal_confidence: float,
    ) -> float:
        """Apply risk limits to position size.

        Args:
            position_size: Proposed position size
            current_price: Current market price
            portfolio_value: Portfolio value
            signal_confidence: Signal confidence

        Returns:
            Risk-limited position size
        """
        # Calculate position value
        position_value = position_size * current_price

        # Max risk per trade limit
        max_position_value = portfolio_value * self.max_risk_per_trade
        if position_value > max_position_value:
            position_size = max_position_value / current_price

        # Max position size limit
        max_position_value = portfolio_value * self.max_position_size
        if position_value > max_position_value:
            position_size = max_position_value / current_price

        # Adjust based on signal confidence
        confidence_adjustment = 0.5 + (signal_confidence * 0.5)  # 0.5 to 1.0
        position_size *= confidence_adjustment

        return position_size

    def update_portfolio_value(self, new_value: float) -> None:
        """Update portfolio value.

        Args:
            new_value: New portfolio value
        """
        self.portfolio_value = new_value
        self.logger.info(f"Updated portfolio value to {new_value:,.2f}")

    def get_risk_summary(self) -> dict[str, Any]:
        """Get risk summary for the portfolio.

        Returns:
            Risk summary dictionary
        """
        total_position_value = sum(
            pos.get("size", 0) * pos.get("price", 0) for pos in self.positions.values()
        )

        return {
            "portfolio_value": self.portfolio_value,
            "total_position_value": total_position_value,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_portfolio_risk": self.max_portfolio_risk,
            "max_position_size": self.max_position_size,
            "kelly_fraction_limit": self.kelly_fraction_limit,
            "kelly_safety_factor": self.kelly_safety_factor,
            "positions_count": len(self.positions),
            "risk_utilization": total_position_value / self.portfolio_value
            if self.portfolio_value > 0
            else 0,
        }

    def calculate_sl_tp_defaults(
        self, 
        symbol: str, 
        entry_price: float, 
        side: str, 
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        data_engine=None
    ) -> dict[str, float]:
        """Calculate default SL/TP using ATR if not provided or too close to entry.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price for the position
            side: 'buy' or 'sell'
            stop_loss: Existing stop loss (optional)
            take_profit: Existing take profit (optional)
            data_engine: Data engine for getting OHLCV data
            
        Returns:
            Dictionary with 'stop_loss' and 'take_profit' values
        """
        try:
            # Validate entry price first
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Invalid entry_price: {entry_price} for {symbol}. Cannot calculate SL/TP.")
                raise ValueError(f"Invalid entry_price: {entry_price}")
            
            # Calculate ATR if data engine is available
            atr = None
            if data_engine:
                try:
                    ohlcv_data = data_engine.get_clean_ohlcv(symbol, "1h", 20)
                    if ohlcv_data:
                        high = [candle['high'] for candle in ohlcv_data]
                        low = [candle['low'] for candle in ohlcv_data]
                        close = [candle['close'] for candle in ohlcv_data]
                        
                        from ..indicators import safe_atr
                        atr = safe_atr(high, low, close, period=14, symbol=symbol, logger=self.logger)
                except Exception as e:
                    self.logger.debug(f"ATR calculation failed for {symbol}: {e}")
                    atr = None
            
            # Use the new derive_sl_tp method
            result = self.derive_sl_tp(
                entry_price=entry_price,
                side=side,
                atr=atr,
                strategy_sl=stop_loss,
                strategy_tp=take_profit,
                symbol=symbol
            )
            
            # Log the result with source information
            source = result.get('source', 'unknown')
            sl = result['stop_loss']
            tp = result['take_profit']
            atr_val = result.get('atr')
            
            # Safe formatting with None checks
            sl_str = f"{sl:.6f}" if sl is not None else "None"
            tp_str = f"{tp:.6f}" if tp is not None else "None"
            atr_str = f"{atr_val:.6f}" if atr_val is not None else "NA"
            
            self.logger.info(f"sl_tp_src={source} sl={sl_str} tp={tp_str} atr={atr_str} for {symbol}")
            
            return {
                'stop_loss': sl,
                'take_profit': tp
            }
            
        except Exception as e:
            self.logger.error(f"Error in calculate_sl_tp_defaults for {symbol}: {e}")
            
            # Check if entry_price is valid for emergency fallback
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Cannot use emergency fallback with invalid entry_price: {entry_price}")
                raise ValueError(f"Invalid entry_price for emergency fallback: {entry_price}")
            
            # Emergency fallback
            if side.lower() == 'buy':
                emergency_sl = entry_price * 0.98  # 2% below entry
                emergency_tp = entry_price * 1.04  # 4% above entry
            else:
                emergency_sl = entry_price * 1.02  # 2% above entry
                emergency_tp = entry_price * 0.96  # 4% below entry
            
            self.logger.info(f"sl_tp_src=emergency sl={emergency_sl:.6f} tp={emergency_tp:.6f} atr=NA for {symbol}")
            return {
                'stop_loss': emergency_sl,
                'take_profit': emergency_tp
            }

    def derive_sl_tp(
        self,
        entry_price: float,
        side: str,
        atr: Optional[float] = None,
        strategy_sl: Optional[float] = None,
        strategy_tp: Optional[float] = None,
        symbol: str = "unknown"
    ) -> dict[str, Any]:
        """Derive SL/TP with guaranteed fallback in order of preference: Strategy → ATR-based → Percent fallback.
        
        Args:
            entry_price: Entry price for the position
            side: 'buy' or 'sell'
            atr: ATR value (optional)
            strategy_sl: Strategy-provided stop loss (optional)
            strategy_tp: Strategy-provided take profit (optional)
            symbol: Trading symbol for logging (optional)
            
        Returns:
            Dictionary with 'stop_loss', 'take_profit', and 'source' information
        """
        try:
            # Validate entry price first
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Invalid entry_price: {entry_price} for {symbol}. Cannot derive SL/TP.")
                raise ValueError(f"Invalid entry_price: {entry_price}")
            
            # Get SL/TP configuration with defaults
            sl_tp_config = self.config.get("risk", {}).get("sl_tp", {})
            atr_mult_sl = sl_tp_config.get("atr_mult_sl", 1.2)
            atr_mult_tp = sl_tp_config.get("atr_mult_tp", 2.0)
            fallback_pct_sl = sl_tp_config.get("fallback_pct_sl", 0.02)
            fallback_pct_tp = sl_tp_config.get("fallback_pct_tp", 0.04)
            min_sl_abs = sl_tp_config.get("min_sl_abs", 0.001)
            min_tp_abs = sl_tp_config.get("min_tp_abs", 0.002)
            
            # Get fallback configuration
            enable_percent_fallback = self.config.get("risk", {}).get("enable_percent_fallback", True)
            
            # Priority 1: Strategy-provided SL/TP (if valid)
            if (strategy_sl is not None and strategy_sl > 0 and 
                strategy_tp is not None and strategy_tp > 0):
                
                # Validate strategy SL/TP distances
                sl_distance = abs(entry_price - strategy_sl) / entry_price
                tp_distance = abs(entry_price - strategy_tp) / entry_price
                min_distance = 0.001  # 0.1% minimum distance
                
                if sl_distance >= min_distance and tp_distance >= min_distance:
                    # Validate logical consistency
                    if self._validate_sl_tp_logic(entry_price, strategy_sl, strategy_tp, side):
                        self.logger.debug(f"Using strategy SL/TP for {symbol}: SL={strategy_sl:.6f}, TP={strategy_tp:.6f}")
                        return {
                            'stop_loss': strategy_sl,
                            'take_profit': strategy_tp,
                            'source': 'strategy',
                            'atr': atr
                        }
            
            # Priority 2: ATR-based SL/TP (if ATR is valid)
            if atr is not None and atr > 0:
                if side.lower() == 'buy':
                    # Long position: SL below entry, TP above entry
                    atr_sl = entry_price - (atr_mult_sl * atr)
                    atr_tp = entry_price + (atr_mult_tp * atr)
                else:
                    # Short position: SL above entry, TP below entry  
                    atr_sl = entry_price + (atr_mult_sl * atr)
                    atr_tp = entry_price - (atr_mult_tp * atr)
                
                # Enforce minimum absolute distances
                atr_sl = self._enforce_min_distance(entry_price, atr_sl, min_sl_abs, side, 'sl')
                atr_tp = self._enforce_min_distance(entry_price, atr_tp, min_tp_abs, side, 'tp')
                
                # Validate logical consistency
                if self._validate_sl_tp_logic(entry_price, atr_sl, atr_tp, side):
                    self.logger.debug(f"Using ATR-based SL/TP for {symbol}: ATR={atr:.6f}, SL={atr_sl:.6f}, TP={atr_tp:.6f}")
                    return {
                        'stop_loss': atr_sl,
                        'take_profit': atr_tp,
                        'source': 'atr',
                        'atr': atr
                    }
            
            # Priority 3: Percent fallback (if enabled)
            if enable_percent_fallback:
                if side.lower() == 'buy':
                    # Long position: SL below entry, TP above entry
                    pct_sl = entry_price * (1 - fallback_pct_sl)
                    pct_tp = entry_price * (1 + fallback_pct_tp)
                else:
                    # Short position: SL above entry, TP below entry
                    pct_sl = entry_price * (1 + fallback_pct_sl)
                    pct_tp = entry_price * (1 - fallback_pct_tp)
                
                # Enforce minimum absolute distances
                pct_sl = self._enforce_min_distance(entry_price, pct_sl, min_sl_abs, side, 'sl')
                pct_tp = self._enforce_min_distance(entry_price, pct_tp, min_tp_abs, side, 'tp')
                
                # Final validation and adjustment if needed
                final_sl, final_tp = self._ensure_logical_consistency(entry_price, pct_sl, pct_tp, side, min_sl_abs, min_tp_abs)
                
                self.logger.debug(f"Using percent fallback SL/TP for {symbol}: SL={final_sl:.6f}, TP={final_tp:.6f}")
                return {
                    'stop_loss': final_sl,
                    'take_profit': final_tp,
                    'source': 'pct',
                    'atr': atr
                }
            else:
                # Percent fallback disabled and ATR failed - skip trade
                self.logger.warning(f"No valid SL/TP derivation for {symbol}: ATR={atr}, fallback disabled")
                raise ValueError("no_atr_no_fallback")
            
        except Exception as e:
            self.logger.error(f"Error in derive_sl_tp for {symbol}: {e}")
            
            # Check if entry_price is valid for emergency fallback
            if entry_price is None or entry_price <= 0:
                self.logger.error(f"Cannot use emergency fallback with invalid entry_price: {entry_price}")
                raise ValueError(f"Invalid entry_price for emergency fallback: {entry_price}")
            
            # Emergency fallback - use simple percentage defaults
            if side.lower() == 'buy':
                emergency_sl = entry_price * 0.98  # 2% below entry
                emergency_tp = entry_price * 1.04  # 4% above entry
            else:
                emergency_sl = entry_price * 1.02  # 2% above entry
                emergency_tp = entry_price * 0.96  # 4% below entry
            
            return {
                'stop_loss': emergency_sl,
                'take_profit': emergency_tp,
                'source': 'emergency',
                'atr': atr
            }

    def _validate_sl_tp_logic(self, entry_price: float, sl: float, tp: float, side: str) -> bool:
        """Validate that SL/TP logic is correct for the given side.
        
        Args:
            entry_price: Entry price
            sl: Stop loss price
            tp: Take profit price
            side: 'buy' or 'sell'
            
        Returns:
            True if logical consistency is maintained
        """
        if side.lower() == 'buy':
            # Long: SL should be below entry, TP above entry
            return sl < entry_price < tp
        else:
            # Short: TP should be below entry, SL above entry
            return tp < entry_price < sl

    def _enforce_min_distance(self, entry_price: float, price: float, min_abs: float, side: str, sl_or_tp: str) -> float:
        """Enforce minimum absolute distance from entry price.
        
        Args:
            entry_price: Entry price
            price: Current SL or TP price
            min_abs: Minimum absolute distance
            side: 'buy' or 'sell'
            sl_or_tp: 'sl' or 'tp'
            
        Returns:
            Adjusted price with minimum distance enforced
        """
        current_distance = abs(entry_price - price)
        if current_distance < min_abs:
            if side.lower() == 'buy':
                if sl_or_tp == 'sl':
                    # SL should be below entry
                    return entry_price - min_abs
                else:
                    # TP should be above entry
                    return entry_price + min_abs
            else:
                if sl_or_tp == 'sl':
                    # SL should be above entry
                    return entry_price + min_abs
                else:
                    # TP should be below entry
                    return entry_price - min_abs
        return price

    def _ensure_logical_consistency(self, entry_price: float, sl: float, tp: float, side: str, min_sl_abs: float, min_tp_abs: float) -> tuple[float, float]:
        """Ensure final SL/TP values maintain logical consistency.
        
        Args:
            entry_price: Entry price
            sl: Stop loss price
            tp: Take profit price
            side: 'buy' or 'sell'
            min_sl_abs: Minimum absolute distance for SL
            min_tp_abs: Minimum absolute distance for TP
            
        Returns:
            Tuple of (adjusted_sl, adjusted_tp)
        """
        if side.lower() == 'buy':
            # Long: SL < entry < TP
            if sl >= entry_price:
                sl = entry_price - min_sl_abs
            if tp <= entry_price:
                tp = entry_price + min_tp_abs
        else:
            # Short: TP < entry < SL
            if tp >= entry_price:
                tp = entry_price - min_tp_abs
            if sl <= entry_price:
                sl = entry_price + min_sl_abs
        
        return sl, tp

    def compute_rr(
        self,
        entry: float,
        sl: float,
        tp: float,
        side: str,
        fee_bps: float = 10.0,
        slip_bps: float = 5.0
    ) -> float:
        """Compute robust risk-reward ratio accounting for fees/slippage and validating distances.
        
        Args:
            entry: Entry price
            sl: Stop loss price
            tp: Take profit price
            side: 'buy' or 'sell'
            fee_bps: Fee in basis points (default 10 bps = 0.1%)
            slip_bps: Slippage in basis points (default 5 bps = 0.05%)
            
        Returns:
            Risk-reward ratio (reward/risk) as float
            
        Raises:
            ValueError: If any input is invalid (None, negative, etc.)
        """
        # Convert to floats and validate inputs
        try:
            entry_float = float(entry)
            sl_float = float(sl)
            tp_float = float(tp)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid price inputs: entry={entry}, sl={sl}, tp={tp}") from e
        
        # Validate prices are positive
        if entry_float <= 0 or sl_float <= 0 or tp_float <= 0:
            raise ValueError(f"Prices must be positive: entry={entry_float}, sl={sl_float}, tp={tp_float}")
        
        # Get minimum SL absolute distance from config
        sl_tp_config = self.config.get("risk", {}).get("sl_tp", {})
        min_sl_abs = sl_tp_config.get("min_sl_abs", 0.001)
        
        # Calculate effective prices with slippage and fees
        if side.lower() == 'buy':
            # Long position: entry with slippage (buy higher), TP with fees (sell lower), SL unchanged
            entry_eff = entry_float * (1 + slip_bps / 1e4)
            tp_eff = tp_float * (1 - fee_bps / 1e4)
            sl_eff = sl_float
        else:
            # Short position: entry with slippage (sell lower), TP with fees (buy higher), SL unchanged
            entry_eff = entry_float * (1 - slip_bps / 1e4)
            tp_eff = tp_float * (1 + fee_bps / 1e4)
            sl_eff = sl_float
        
        # Calculate reward and risk
        reward = abs(tp_eff - entry_eff)
        risk = abs(entry_eff - sl_eff)
        
        # Guard against tiny risk values
        if risk < 1e-9:
            risk = min_sl_abs
        
        # Ensure minimum risk distance
        if risk < min_sl_abs:
            risk = min_sl_abs
        
        # Calculate RR ratio
        rr_ratio = reward / risk if risk > 0 else 0.0
        
        # Return max(RR, 0.0) to ensure non-negative
        return max(rr_ratio, 0.0)

    def calculate_risk_reward_ratio(
        self, 
        entry_price: float, 
        stop_loss: float, 
        take_profit: float, 
        side: str,
        estimated_fees: Optional[float] = None,
        estimated_slippage: Optional[float] = None
    ) -> float:
        """Calculate risk-reward ratio using the new compute_rr method with fallback.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            side: 'buy' or 'sell'
            estimated_fees: Estimated trading fees (optional, ignored - using bps)
            estimated_slippage: Estimated slippage (optional, ignored - using bps)
            
        Returns:
            Risk-reward ratio (reward/risk) including costs
        """
        try:
            # Use the new compute_rr method with default fee/slippage in basis points
            return self.compute_rr(entry_price, stop_loss, take_profit, side)
            
        except ValueError as e:
            self.logger.warning(f"RR calculation failed with ValueError: {e}")
            return 0.0
        except Exception as e:
            self.logger.error(f"Unexpected error in RR calculation: {e}")
            return 0.0

    def validate_trade_parameters(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str,
        composite_score: float,
        regime: Optional[str] = None,
        effective_threshold: Optional[float] = None,
        liquidity_ok: Optional[bool] = None
    ) -> dict[str, Any]:
        """Validate trade parameters and determine if trade should be executed.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            side: 'buy' or 'sell'
            composite_score: Composite signal score
            regime: Market regime ('trending', 'ranging', etc.)
            effective_threshold: Dynamic effective threshold (optional)
            liquidity_ok: Whether liquidity is sufficient (optional)
            
        Returns:
            Dictionary with validation results including skip_reason if applicable
        """
        try:
            # Calculate risk-reward ratio with robust error handling
            rr_ratio = 0.0
            rr_calculation_error = None
            
            try:
                # Try the new robust RR calculation
                rr_ratio = self.compute_rr(entry_price, stop_loss, take_profit, side)
            except ValueError as e:
                # RR calculation failed due to invalid inputs
                rr_calculation_error = str(e)
                self.logger.warning(f"RR calculation failed for {symbol}: {e}")
                
                # Fallback: use percent-based SL/TP then recompute RR
                try:
                    fallback_result = self.derive_sl_tp(
                        entry_price=entry_price,
                        side=side,
                        atr=None,  # Force percent fallback
                        strategy_sl=None,
                        strategy_tp=None,
                        symbol=symbol
                    )
                    
                    fallback_sl = fallback_result['stop_loss']
                    fallback_tp = fallback_result['take_profit']
                    
                    # Recompute RR with fallback SL/TP
                    rr_ratio = self.compute_rr(entry_price, fallback_sl, fallback_tp, side)
                    self.logger.info(f"Used fallback SL/TP for RR calculation: SL={fallback_sl:.6f}, TP={fallback_tp:.6f}, RR={rr_ratio:.2f}")
                    
                except Exception as fallback_error:
                    self.logger.error(f"Fallback RR calculation also failed for {symbol}: {fallback_error}")
                    rr_ratio = 0.0
            
            # Check RR threshold first - if RR < 1.30, skip regardless of score
            if rr_ratio < 1.30:
                skip_reason = f'rr_too_low ratio={rr_ratio:.2f}'
                if rr_calculation_error:
                    skip_reason = f'rr_error {rr_calculation_error}'
                
                return {
                    'valid': False,
                    'skip_reason': skip_reason,
                    'details': f"Risk-reward ratio {rr_ratio:.2f} below minimum 1.30" + (f" (error: {rr_calculation_error})" if rr_calculation_error else ""),
                    'risk_reward_ratio': rr_ratio
                }
            
            # Determine score floor based on RR and liquidity
            if effective_threshold is None:
                effective_threshold = 0.65  # Default threshold
            
            # New effective gate calculation with volatility-aware easing
            gate_cfg = self.config.get("risk", {}).get("entry_gate", {})
            gate_margin = gate_cfg.get("gate_margin", 0.01)
            hard_floor_min = gate_cfg.get("hard_floor_min", 0.53)
            
            # Base effective gate: adaptive threshold minus margin, but not below hard floor
            effective_gate = max(effective_threshold - gate_margin, hard_floor_min)
            
            # Optional volatility-aware easing
            if gate_cfg.get("enable_vol_gate_easing", True):
                # Try to get ATR context from signal metadata
                signal_metadata = signal.get("metadata", {})
                atr = signal_metadata.get("atr")
                atr_sma = signal_metadata.get("atr_sma")
                
                if atr is not None and atr_sma is not None and atr_sma > 1e-9:
                    vol_z = (atr / atr_sma) - 1.0
                    vol_z = max(-gate_cfg.get("vol_ease_max", 0.5), 
                               min(vol_z, gate_cfg.get("vol_ease_max", 0.5)))
                    vol_ease_adjustment = gate_cfg.get("vol_ease_k", 0.02) * vol_z
                    effective_gate = max(hard_floor_min, effective_gate - vol_ease_adjustment)
            
            # Legacy compatibility: keep score_floor for backward compatibility
            score_floor = effective_gate
            floor_reason = "effective_gate"
            
            # Check composite score against effective gate
            if composite_score < effective_gate:
                return {
                    'valid': False,
                    'skip_reason': f'low_score effective_gate={effective_gate:.3f} score={composite_score:.3f} thr={effective_threshold:.3f} floor={hard_floor_min:.3f} rr={rr_ratio:.2f}',
                    'details': f"Composite score {composite_score:.3f} below effective gate {effective_gate:.3f} (RR={rr_ratio:.2f})",
                    'risk_reward_ratio': rr_ratio,
                    'score_floor': score_floor,
                    'floor_reason': floor_reason,
                    'effective_gate': effective_gate
                }
            
            # All validations passed
            return {
                'valid': True,
                'risk_reward_ratio': rr_ratio,
                'score_floor': score_floor,
                'floor_reason': floor_reason,
                'details': f"Trade validated: score={composite_score:.3f}≥{score_floor:.3f}, RR={rr_ratio:.2f}"
            }
            
        except Exception as e:
            self.logger.error(f"Error validating trade parameters for {symbol}: {e}")
            return {
                'valid': False,
                'skip_reason': 'validation_error',
                'details': f"Validation error: {e}"
            }

    def build_exit_actions(self, portfolio: dict[str, Any], marks: dict[str, float]) -> List[ExitAction]:
        """Build exit action suggestions based on chandelier stops and time stops.
        
        Args:
            portfolio: Portfolio dictionary with positions
            marks: Current market prices for symbols
            
        Returns:
            List of ExitAction suggestions
        """
        exit_actions = []
        
        try:
            # Get exit configuration with safe defaults
            exit_cfg = self.config.get("risk", {}).get("exits", {})
            enable_chandelier = exit_cfg.get("enable_chandelier", True)
            chandelier_n_atr = exit_cfg.get("chandelier_n_atr", 2.5)
            time_stop_bars = exit_cfg.get("time_stop_bars", 60)
            min_qty = exit_cfg.get("min_qty", 1e-9)
            
            positions = portfolio.get("positions", {})
            
            for symbol, position in positions.items():
                try:
                    # Skip if no current price available
                    if symbol not in marks or marks[symbol] <= 0:
                        continue
                        
                    mark = marks[symbol]
                    qty = position.get("quantity", 0)
                    
                    # Skip if quantity is too small
                    if abs(qty) <= min_qty:
                        continue
                    
                    # Get position metadata
                    meta = position.get("meta", {})
                    entry_price = position.get("entry_price", position.get("avg_price", mark))
                    
                    # Fetch ATR(14) - try to get from existing indicator access
                    atr = self._get_atr_for_symbol(symbol, mark)
                    
                    # Chandelier Stop Logic
                    if enable_chandelier:
                        chandelier_action = self._check_chandelier_stop(
                            symbol, position, mark, atr, chandelier_n_atr
                        )
                        if chandelier_action:
                            exit_actions.append(chandelier_action)
                    
                    # Time Stop Logic
                    time_action = self._check_time_stop(
                        symbol, position, mark, atr, time_stop_bars
                    )
                    if time_action:
                        exit_actions.append(time_action)
                        
                except Exception as e:
                    self.logger.warning(f"Error processing exit for {symbol}: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error in build_exit_actions: {e}")
            
        return exit_actions
    
    def _get_atr_for_symbol(self, symbol: str, fallback_price: float) -> float:
        """Get ATR(14) for symbol with fallback.
        
        Args:
            symbol: Trading symbol
            fallback_price: Fallback price for ATR calculation
            
        Returns:
            ATR value
        """
        try:
            # Try to get ATR from data engine if available
            # This is a placeholder - in real implementation, you'd access the data engine
            # For now, use fallback calculation
            fallback_atr = 0.005 * fallback_price  # 0.5% of price as fallback
            return fallback_atr
        except Exception as e:
            self.logger.debug(f"ATR calculation failed for {symbol}: {e}")
            return 0.005 * fallback_price
    
    def _check_chandelier_stop(
        self, 
        symbol: str, 
        position: dict[str, Any], 
        mark: float, 
        atr: float, 
        n_atr: float
    ) -> Optional[ExitAction]:
        """Check chandelier stop conditions.
        
        Args:
            symbol: Trading symbol
            position: Position data
            mark: Current market price
            atr: ATR value
            n_atr: ATR multiplier
            
        Returns:
            ExitAction if stop triggered, None otherwise
        """
        try:
            qty = position.get("quantity", 0)
            entry_price = position.get("entry_price", position.get("avg_price", mark))
            meta = position.get("meta", {})
            
            # Determine position side
            is_long = qty > 0
            
            if is_long:
                # LONG position: stop = high_since_entry - n_atr * atr
                high_since_entry = meta.get("high_since_entry", entry_price)
                stop_price = float(high_since_entry) - (n_atr * atr)
                
                if mark <= stop_price:
                    return ExitAction(
                        symbol=symbol,
                        qty=abs(qty),
                        reason=f"chandelier_stop @{stop_price:.6f}",
                        price_hint=mark
                    )
            else:
                # SHORT position: stop = low_since_entry + n_atr * atr
                low_since_entry = meta.get("low_since_entry", entry_price)
                stop_price = float(low_since_entry) + (n_atr * atr)
                
                if mark >= stop_price:
                    return ExitAction(
                        symbol=symbol,
                        qty=abs(qty),
                        reason=f"chandelier_stop @{stop_price:.6f}",
                        price_hint=mark
                    )
                    
        except Exception as e:
            self.logger.warning(f"Error checking chandelier stop for {symbol}: {e}")
            
        return None
    
    def _check_time_stop(
        self, 
        symbol: str, 
        position: dict[str, Any], 
        mark: float, 
        atr: float, 
        time_stop_bars: int
    ) -> Optional[ExitAction]:
        """Check time stop conditions.
        
        Args:
            symbol: Trading symbol
            position: Position data
            mark: Current market price
            atr: ATR value
            time_stop_bars: Time stop threshold in bars
            
        Returns:
            ExitAction if time stop triggered, None otherwise
        """
        try:
            qty = position.get("quantity", 0)
            entry_price = position.get("entry_price", position.get("avg_price", mark))
            meta = position.get("meta", {})
            
            bars_since_entry = meta.get("bars_since_entry", 0)
            
            # Check if time stop threshold reached
            if bars_since_entry >= time_stop_bars:
                # Check if unrealized progress < 0.5 * atr
                unrealized_progress = abs(mark - entry_price)
                progress_threshold = 0.5 * atr
                
                if unrealized_progress < progress_threshold:
                    return ExitAction(
                        symbol=symbol,
                        qty=abs(qty),
                        reason=f"time_stop_{bars_since_entry}bars",
                        price_hint=mark
                    )
                    
        except Exception as e:
            self.logger.warning(f"Error checking time stop for {symbol}: {e}")
            
        return None

    def check_daily_loss_limit(
        self, 
        state_store: Optional[Any] = None, 
        session_id: Optional[str] = None,
        current_equity: Optional[float] = None,
        is_first_cycle: bool = False
    ) -> tuple[bool, str]:
        """Check if daily loss limit has been exceeded and manage halt flag.
        
        Args:
            state_store: StateStore instance for session metadata
            session_id: Current session identifier
            current_equity: Current equity value for loss calculation
            is_first_cycle: Whether this is the first trading cycle
            
        Returns:
            Tuple of (should_halt_new_entries, reason)
        """
        if not state_store or not session_id:
            return False, "no_state_store_or_session"
        
        # Check if already halted
        halt_flag = state_store.get_session_metadata(
            session_id, "halt_new_entries_today", False
        )
        if halt_flag:
            return True, "already_halted"
        
        if current_equity is None:
            return False, "no_equity_data"
        
        # First-cycle bypass: Skip daily loss limit check if no trades have been executed yet
        if is_first_cycle:
            # Check if any trades have been executed in this session
            try:
                # Get trade count from state store or trade ledger
                trades_executed = state_store.get_session_metadata(
                    session_id, "trades_executed_count", 0
                )
                if trades_executed == 0:
                    self.logger.info("DAILY_LOSS_CHECK: Skipping first cycle - no trades executed yet")
                    return False, "first_cycle_no_trades"
            except Exception as e:
                self.logger.warning(f"Error checking trade count for first cycle bypass: {e}")
                # Continue with normal check if we can't determine trade count
        
        # Get session start equity (assuming it's stored or can be calculated)
        session_start_equity = state_store.get_session_metadata(
            session_id, "session_start_equity", current_equity
        )
        
        # Edge case check: if current_equity == 0.0 and session_start_equity > 0, return False (no halt)
        if current_equity == 0.0 and session_start_equity > 0:
            self.logger.info(f"DAILY_LOSS_CHECK: current_equity=$0.00 but session_start_equity=${session_start_equity:.2f} - skipping halt (likely initialization issue)")
            return False, "zero_equity_with_start_capital"
        
        # Edge case check: if no trades have been executed in this session, return False (no halt)
        try:
            trades_executed = state_store.get_session_metadata(
                session_id, "trades_executed_count", 0
            )
            if trades_executed == 0:
                self.logger.info(f"DAILY_LOSS_CHECK: No trades executed in session - skipping halt")
                return False, "no_trades_executed"
        except Exception as e:
            self.logger.warning(f"Error checking trade count for daily loss limit: {e}")
            # Continue with normal check if we can't determine trade count
        
        # Calculate daily loss
        daily_loss = session_start_equity - current_equity
        daily_loss_pct = daily_loss / session_start_equity if session_start_equity > 0 else 0.0
        
        # Enhanced logging with all key values
        self.logger.info(f"DAILY_LOSS_CHECK: current=${current_equity:.2f}, start=${session_start_equity:.2f}, loss_pct={daily_loss_pct:.3f}")
        self.logger.debug(
            f"DAILY_LOSS_CHECK: start_equity=${session_start_equity:.2f} "
            f"current_equity=${current_equity:.2f} loss=${daily_loss:.2f} "
            f"loss_pct={daily_loss_pct:.3f} limit={self.daily_max_loss_pct:.3f}"
        )
        
        # Check if daily loss limit exceeded - only trigger halt if: loss_pct >= limit AND trades_executed > 0
        if daily_loss_pct >= self.daily_max_loss_pct:
            # Double-check that trades have been executed before halting
            try:
                trades_executed = state_store.get_session_metadata(
                    session_id, "trades_executed_count", 0
                )
                if trades_executed > 0:
                    # Set halt flag
                    state_store.set_session_metadata(
                        session_id, "halt_new_entries_today", True
                    )
                    
                    self.logger.warning(
                        f"HALT: daily max loss reached - loss_pct={daily_loss_pct:.3f} "
                        f"limit={self.daily_max_loss_pct:.3f} loss=${daily_loss:.2f} trades={trades_executed}"
                    )
                    
                    return True, "daily_loss_limit_exceeded"
                else:
                    self.logger.info(f"DAILY_LOSS_CHECK: Loss limit exceeded but no trades executed - skipping halt")
                    return False, "loss_limit_exceeded_but_no_trades"
            except Exception as e:
                self.logger.warning(f"Error checking trade count for halt decision: {e}")
                # If we can't determine trade count, err on the side of caution and don't halt
                return False, "error_checking_trades"
        
        return False, "within_limits"


# Legacy RiskManager class for backward compatibility
class RiskManager(ProfitOptimizedRiskManager):
    """Legacy risk manager for backward compatibility."""

    def __init__(self, config: dict[str, Any]):
        """Initialize legacy risk manager."""
        super().__init__(config)
        # Map legacy config keys to new structure
        self.max_drawdown = config.get("max_drawdown", 0.15)
        self.max_correlation = config.get("max_correlation", 0.7)
        self.var_confidence = config.get("var_confidence", 0.95)
        self.var_horizon = config.get("var_horizon", 1)
        self.max_sector_exposure = config.get("max_sector_exposure", 0.3)
        self.max_currency_exposure = config.get("max_currency_exposure", 0.4)
        self.max_leverage = config.get("max_leverage", 2.0)
        self.global_stop_loss = config.get("global_stop_loss", 0.10)
        self.trailing_stop = config.get("trailing_stop", 0.05)
        self.time_based_stop = config.get("time_based_stop", 24)

        # Risk tracking
        self.risk_metrics: dict[str, RiskMetrics] = {}
        self.alert_thresholds: dict[str, float] = {}

    def calculate_var(
        self, returns: list[float], confidence: float = 0.95, horizon: int = 1
    ) -> float:
        """Calculate Value at Risk (VaR)."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        var_percentile = (1 - confidence) * 100
        var_value = np.percentile(returns_array, var_percentile)
        return var_value * np.sqrt(horizon)

    def calculate_max_drawdown(self, returns: list[float]) -> float:
        """Calculate maximum drawdown."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        cumulative_returns = np.cumprod(1 + returns_array)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        return abs(np.min(drawdown))

    def calculate_sharpe_ratio(
        self, returns: list[float], risk_free_rate: float = 0.02
    ) -> float:
        """Calculate Sharpe ratio."""
        if not returns:
            return 0.0

        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate / 252
        if np.std(excess_returns) == 0:
            return 0.0
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)

"""
Composite signal engine for profit-maximizing trading decisions.
"""

import statistics
from datetime import datetime
from typing import Any, Optional

from ..core.logging_utils import LoggerMixin
from .arbitrage import ArbitrageStrategy
from .base import Strategy
from .breakout import BreakoutStrategy
from .correlation import CorrelationStrategy
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy
from .news_driven import NewsDrivenStrategy
from .on_chain import OnChainStrategy
from .sentiment import SentimentStrategy
from .volatility import VolatilityStrategy
from .whale_tracking import WhaleTrackingStrategy


class ProfitMaximizingSignalEngine(LoggerMixin):
    """
    Composite signal engine that combines multiple strategies to generate
    profit-maximizing trading signals.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None, state_store=None):
        """Initialize the composite signal engine.

        Args:
            config: Configuration dictionary (optional)
            state_store: State store instance for signal windows (optional)
        """
        super().__init__()
        self.config = config or {}
        self.strategies: dict[str, Strategy] = {}
        self.strategy_weights: dict[str, float] = {}
        self.state_store = state_store
        self.initialized = False
        
        # Rolling window configuration
        self.window_size = self.config.get("window_size", 200)
        self.dynamic_threshold_enabled = self.config.get("dynamic_threshold_enabled", True)

        # Default strategy weights (can be overridden by config)
        self.default_weights = {
            "momentum": 0.15,
            "breakout": 0.15,
            "mean_reversion": 0.10,
            "arbitrage": 0.20,  # Higher weight for arbitrage (direct profit)
            "sentiment": 0.10,
            "volatility": 0.10,
            "correlation": 0.05,
            "whale_tracking": 0.05,
            "news_driven": 0.05,
            "on_chain": 0.05,
        }

    def initialize(self) -> None:
        """Initialize all individual strategies."""
        if self.initialized:
            self.logger.info("ProfitMaximizingSignalEngine already initialized")
            return

        self.logger.info("Initializing ProfitMaximizingSignalEngine")

        # Initialize all strategies
        strategy_classes = {
            "momentum": MomentumStrategy,
            "breakout": BreakoutStrategy,
            "mean_reversion": MeanReversionStrategy,
            "arbitrage": ArbitrageStrategy,
            "sentiment": SentimentStrategy,
            "volatility": VolatilityStrategy,
            "correlation": CorrelationStrategy,
            "whale_tracking": WhaleTrackingStrategy,
            "news_driven": NewsDrivenStrategy,
            "on_chain": OnChainStrategy,
        }

        for name, strategy_class in strategy_classes.items():
            try:
                # Get strategy-specific config
                strategy_config = self.config.get(name, {})
                self.strategies[name] = strategy_class(strategy_config)
                self.logger.debug(f"Initialized strategy: {name}")
            except Exception as e:
                self.logger.error(f"Failed to initialize strategy {name}: {e}")
                # Continue with other strategies even if one fails

        # Set strategy weights
        self.strategy_weights = self.config.get(
            "strategy_weights", self.default_weights.copy()
        )

        # Normalize weights to sum to 1.0
        total_weight = sum(self.strategy_weights.values())
        if total_weight > 0:
            self.strategy_weights = {
                name: weight / total_weight
                for name, weight in self.strategy_weights.items()
            }

        self.initialized = True
        self.logger.info(
            f"Initialized {len(self.strategies)} strategies with weights: {self.strategy_weights}"
        )
    
    def set_data_engine(self, data_engine) -> None:
        """Set data engine for all strategies that need market data.
        
        Args:
            data_engine: Data engine instance for fetching OHLCV and market data
        """
        for name, strategy in self.strategies.items():
            try:
                # Set data_engine on all strategies (Python allows dynamic attributes)
                # Strategies that don't use it will simply ignore it
                strategy.data_engine = data_engine
                self.logger.debug(f"Set data_engine for {name} strategy")
            except Exception as e:
                # Strategy doesn't support setting attributes - skip it
                self.logger.debug(f"Couldn't set data_engine for {name}: {e}")

    async def generate_composite_signals(
        self, symbol: str, timeframe: Optional[str] = None
    ) -> dict[str, Any]:
        """Generate composite trading signals by combining all individual strategies.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (optional)

        Returns:
            Dictionary containing:
            - individual_signals: Dict of signals from each strategy
            - composite_score: Combined score (-1 to 1)
            - profit_probability: Probability of profit (0 to 1)
            - risk_adjusted_return: Risk-adjusted return estimate
            - confidence: Overall confidence in the signal (0 to 1)
            - metadata: Additional analysis data
        """
        if not self.initialized:
            self.initialize()

        timeframe = timeframe or "default"
        
        self.logger.debug(
            f"Generating composite signals for {symbol} on {timeframe} timeframe"
        )

        # Collect signals from all strategies
        individual_signals = {}
        strategy_scores = []
        strategy_confidences = []
        strategy_weights = []
        normalized_scores = []

        for name, strategy in self.strategies.items():
            try:
                signal = strategy.analyze(symbol, timeframe)
                
                # Safety check: ensure signal is a dict
                if signal is None or not isinstance(signal, dict):
                    self.logger.warning(f"Strategy {name} returned invalid signal: {type(signal)}")
                    signal = {
                        "score": 0.0,
                        "signal_strength": 0.0,
                        "confidence": 0.0,
                        "error": "invalid_return_type"
                    }
                
                individual_signals[name] = signal

                raw_score = signal.get("score", 0.0)
                confidence = signal.get("confidence", 0.0)
                weight = self.strategy_weights.get(name, 0.0)

                # Normalize the signal using rolling window
                normalized_score = self._normalize_signal(symbol, timeframe, name, raw_score)
                
                # Store in rolling window
                if self.state_store:
                    self.state_store.save_signal_window(symbol, timeframe, name, raw_score)

                strategy_scores.append(raw_score)
                normalized_scores.append(normalized_score)
                strategy_confidences.append(confidence)
                strategy_weights.append(weight)

                self.logger.debug(
                    f"Strategy {name}: raw={raw_score:.3f}, norm={normalized_score:.3f}, confidence={confidence:.3f}, weight={weight:.3f}"
                )

            except Exception as e:
                self.logger.warning(f"Failed to get signal from strategy {name}: {e}")
                # Use neutral values for failed strategies
                individual_signals[name] = {
                    "score": 0.0,
                    "signal_strength": 0.0,
                    "confidence": 0.0,
                    "error": str(e),
                }
                strategy_scores.append(0.0)
                normalized_scores.append(0.0)
                strategy_confidences.append(0.0)
                strategy_weights.append(0.0)

        # Calculate composite metrics using normalized scores
        raw_composite_score = self._calculate_profit_weighted_score(
            strategy_scores, strategy_weights
        )
        normalized_composite_score = self._calculate_profit_weighted_score(
            normalized_scores, strategy_weights
        )
        
        # Calculate dynamic threshold
        effective_threshold = self._calculate_dynamic_threshold(
            symbol, timeframe, normalized_composite_score
        )
        
        # Determine market regime (simplified)
        regime = self._determine_regime(symbol, timeframe)
        
        # Store composite signal in rolling window
        if self.state_store:
            self.state_store.save_composite_signal_window(
                symbol, timeframe, raw_composite_score, 
                normalized_composite_score, effective_threshold, regime
            )
        
        # Use normalized composite score for final calculations
        composite_score = normalized_composite_score
        profit_probability = self._calculate_profit_probability(
            normalized_scores, strategy_confidences, strategy_weights
        )
        risk_adjusted_return = self._calculate_risk_adjusted_return(
            normalized_scores, strategy_confidences, strategy_weights
        )
        confidence = self._calculate_confidence(
            normalized_scores, strategy_confidences, strategy_weights
        )

        # Generate metadata
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_count": len(self.strategies),
            "active_strategies": len(
                [s for s in individual_signals.values() if "error" not in s]
            ),
            "strategy_weights": self.strategy_weights.copy(),
            "signal_distribution": {
                "positive_signals": len([s for s in normalized_scores if s > 0.1]),
                "negative_signals": len([s for s in normalized_scores if s < -0.1]),
                "neutral_signals": len(
                    [s for s in normalized_scores if -0.1 <= s <= 0.1]
                ),
            },
            "normalization": {
                "raw_composite_score": raw_composite_score,
                "normalized_composite_score": normalized_composite_score,
                "effective_threshold": effective_threshold,
                "regime": regime,
                "window_size": self.window_size,
            },
        }

        result = {
            "individual_signals": individual_signals,
            "composite_score": composite_score,
            "profit_probability": profit_probability,
            "risk_adjusted_return": risk_adjusted_return,
            "confidence": confidence,
            "metadata": metadata,
        }

        self.logger.info(
            f"Generated composite signal for {symbol}: raw={raw_composite_score:.3f}, "
            f"norm={normalized_composite_score:.3f}, thr={effective_threshold:.3f}, "
            f"regime={regime}, profit_prob={profit_probability:.3f}, confidence={confidence:.3f}"
        )

        return result

    def _calculate_profit_weighted_score(
        self, scores: list[float], weights: list[float]
    ) -> float:
        """Calculate profit-weighted composite score.

        Args:
            scores: List of strategy scores
            weights: List of strategy weights

        Returns:
            Weighted composite score (-1 to 1)
        """
        if not scores or not weights or len(scores) != len(weights):
            return 0.0

        # Calculate weighted average
        weighted_sum = sum(score * weight for score, weight in zip(scores, weights))
        total_weight = sum(weights)

        if total_weight == 0:
            return 0.0

        weighted_score = weighted_sum / total_weight

        # Apply profit maximization bias
        # Boost positive signals and dampen negative signals slightly
        if weighted_score > 0:
            # Amplify positive signals for profit maximization
            profit_bias = 1.1
        else:
            # Slightly dampen negative signals to avoid over-selling
            profit_bias = 0.95

        final_score = weighted_score * profit_bias

        # Ensure score stays within bounds
        return max(-1.0, min(1.0, final_score))

    def _calculate_profit_probability(
        self, scores: list[float], confidences: list[float], weights: list[float]
    ) -> float:
        """Calculate probability of profit based on strategy signals.

        Args:
            scores: List of strategy scores
            confidences: List of strategy confidences
            weights: List of strategy weights

        Returns:
            Profit probability (0 to 1)
        """
        if not scores or not confidences or not weights:
            return 0.5  # Neutral probability

        # Calculate weighted confidence
        weighted_confidence = sum(
            conf * weight for conf, weight in zip(confidences, weights)
        )
        total_weight = sum(weights)

        if total_weight == 0:
            return 0.5

        avg_confidence = weighted_confidence / total_weight

        # Calculate signal strength
        positive_signals = sum(1 for score in scores if score > 0.1)
        negative_signals = sum(1 for score in scores if score < -0.1)
        total_signals = len(scores)

        if total_signals == 0:
            return 0.5

        signal_ratio = positive_signals / total_signals

        # Combine confidence and signal ratio
        # Higher confidence and more positive signals = higher profit probability
        profit_probability = (signal_ratio * 0.6) + (avg_confidence * 0.4)

        # Apply profit maximization adjustment
        # Slightly boost probability for positive signals
        if signal_ratio > 0.5:
            profit_probability *= 1.05

        return max(0.0, min(1.0, profit_probability))

    def _calculate_risk_adjusted_return(
        self, scores: list[float], confidences: list[float], weights: list[float]
    ) -> float:
        """Calculate risk-adjusted return estimate.

        Args:
            scores: List of strategy scores
            confidences: List of strategy confidences
            weights: List of strategy weights

        Returns:
            Risk-adjusted return estimate
        """
        if not scores or not confidences or not weights:
            return 0.0

        # Calculate weighted score and confidence
        weighted_score = sum(score * weight for score, weight in zip(scores, weights))
        weighted_confidence = sum(
            conf * weight for conf, weight in zip(confidences, weights)
        )
        total_weight = sum(weights)

        if total_weight == 0:
            return 0.0

        avg_score = weighted_score / total_weight
        avg_confidence = weighted_confidence / total_weight

        # Calculate signal consistency (lower variance = higher consistency)
        score_variance = (
            sum(
                (score - avg_score) ** 2 * weight
                for score, weight in zip(scores, weights)
            )
            / total_weight
        )
        consistency = 1.0 / (
            1.0 + score_variance
        )  # Higher variance = lower consistency

        # Risk-adjusted return = expected return * confidence * consistency
        expected_return = avg_score * 0.1  # Assume 10% max return per signal
        risk_adjusted_return = expected_return * avg_confidence * consistency

        return risk_adjusted_return

    def _calculate_confidence(
        self, scores: list[float], confidences: list[float], weights: list[float]
    ) -> float:
        """Calculate overall confidence in the composite signal.

        Args:
            scores: List of strategy scores
            confidences: List of strategy confidences
            weights: List of strategy weights

        Returns:
            Overall confidence (0 to 1)
        """
        if not scores or not confidences or not weights:
            return 0.0

        # Calculate weighted confidence
        weighted_confidence = sum(
            conf * weight for conf, weight in zip(confidences, weights)
        )
        total_weight = sum(weights)

        if total_weight == 0:
            return 0.0

        avg_confidence = weighted_confidence / total_weight

        # Calculate signal agreement (how many strategies agree on direction)
        positive_count = sum(1 for score in scores if score > 0.1)
        negative_count = sum(1 for score in scores if score < -0.1)
        total_count = len(scores)

        if total_count == 0:
            return avg_confidence

        # Agreement ratio (higher when more strategies agree)
        max_agreement = max(positive_count, negative_count)
        agreement_ratio = max_agreement / total_count

        # Calculate signal strength (how strong the signals are)
        avg_signal_strength = sum(abs(score) for score in scores) / total_count

        # Combine confidence, agreement, and signal strength
        # Agreement and signal strength boost confidence
        confidence_boost = (agreement_ratio * 0.3) + (avg_signal_strength * 0.2)
        final_confidence = avg_confidence + confidence_boost

        return max(0.0, min(1.0, final_confidence))

    def get_strategy_performance(self) -> dict[str, Any]:
        """Get performance summary of all strategies.

        Returns:
            Dictionary with strategy performance metrics
        """
        if not self.initialized:
            return {"error": "Engine not initialized"}

        performance = {}
        for name, strategy in self.strategies.items():
            try:
                performance[name] = strategy.get_performance_summary()
            except Exception as e:
                performance[name] = {"error": str(e)}

        return performance

    def update_strategy_weights(self, new_weights: dict[str, float]) -> None:
        """Update strategy weights dynamically.

        Args:
            new_weights: New weight configuration
        """
        self.strategy_weights.update(new_weights)

        # Normalize weights
        total_weight = sum(self.strategy_weights.values())
        if total_weight > 0:
            self.strategy_weights = {
                name: weight / total_weight
                for name, weight in self.strategy_weights.items()
            }

        self.logger.info(f"Updated strategy weights: {self.strategy_weights}")

    def get_available_strategies(self) -> list[str]:
        """Get list of available strategy names.

        Returns:
            List of strategy names
        """
        return list(self.strategies.keys())

    def get_strategy_info(self, strategy_name: str) -> dict[str, Any]:
        """Get information about a specific strategy.

        Args:
            strategy_name: Name of the strategy

        Returns:
            Strategy information dictionary
        """
        if strategy_name not in self.strategies:
            return {"error": f"Strategy {strategy_name} not found"}

        strategy = self.strategies[strategy_name]
        return {
            "name": strategy.name,
            "class": strategy.__class__.__name__,
            "weight": self.strategy_weights.get(strategy_name, 0.0),
            "enabled": strategy.enabled,
            "required_data": strategy.get_required_data(),
        }

    def _normalize_signal(
        self, symbol: str, timeframe: str, strategy_name: str, raw_score: float
    ) -> float:
        """Normalize signal using z-score or min-max normalization.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            strategy_name: Strategy name
            raw_score: Raw signal score
            
        Returns:
            Normalized signal score
        """
        if not self.state_store:
            return raw_score  # No normalization without state store
            
        try:
            # Get signal window stats
            stats = self.state_store.get_signal_window_stats(symbol, timeframe, strategy_name)
            
            if stats["count"] < 2:
                return raw_score  # Not enough data for normalization
            
            mean_val = stats["mean"]
            std_val = stats["std"]
            
            # Use z-score normalization if std > 0.01, otherwise min-max
            if std_val > 0.01:
                # Z-score normalization
                normalized = (raw_score - mean_val) / std_val
                # Clamp to reasonable range
                normalized = max(-3.0, min(3.0, normalized))
                return normalized
            else:
                # Min-max normalization (0-1 range)
                min_val = stats["min"]
                max_val = stats["max"]
                if max_val > min_val:
                    normalized = (raw_score - min_val) / (max_val - min_val)
                    # Scale to -1 to 1 range
                    normalized = (normalized - 0.5) * 2
                    return max(-1.0, min(1.0, normalized))
                else:
                    return raw_score
                    
        except Exception as e:
            self.logger.warning(f"Failed to normalize signal for {symbol}/{timeframe}/{strategy_name}: {e}")
            return raw_score

    def _calculate_dynamic_threshold(
        self, symbol: str, timeframe: str, composite_score: float
    ) -> float:
        """Calculate dynamic threshold based on quantiles of composite signal window.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            composite_score: Current composite score
            
        Returns:
            Effective threshold value
        """
        if not self.dynamic_threshold_enabled or not self.state_store:
            return 0.65  # Default static threshold
            
        try:
            # Get composite signal window
            window_data = self.state_store.get_composite_signal_window(symbol, timeframe)
            
            if len(window_data) < 10:
                return 0.65  # Not enough data, use default
            
            # Extract normalized scores
            normalized_scores = [item["normalized_score"] for item in window_data]
            
            # Calculate quantiles
            sorted_scores = sorted(normalized_scores)
            n = len(sorted_scores)
            
            # 90th percentile (q90)
            q90_idx = int(0.9 * n)
            q90 = sorted_scores[q90_idx] if q90_idx < n else sorted_scores[-1]
            
            # 85th percentile (q85)
            q85_idx = int(0.85 * n)
            q85 = sorted_scores[q85_idx] if q85_idx < n else sorted_scores[-1]
            
            # Determine regime
            regime = self._determine_regime(symbol, timeframe)
            
            # Calculate dynamic threshold based on regime
            if regime == "trending":
                dyn_thr = max(0.48, q85)
            else:
                dyn_thr = max(0.50, q90)
            
            # Apply hard ceiling at 0.65
            effective_thr = min(0.65, dyn_thr)
            
            self.logger.debug(
                f"Dynamic threshold for {symbol}/{timeframe}: q90={q90:.3f}, q85={q85:.3f}, "
                f"regime={regime}, dyn_thr={dyn_thr:.3f}, effective_thr={effective_thr:.3f}"
            )
            
            return effective_thr
            
        except Exception as e:
            self.logger.warning(f"Failed to calculate dynamic threshold for {symbol}/{timeframe}: {e}")
            return 0.65  # Fallback to default

    def _determine_regime(self, symbol: str, timeframe: str) -> str:
        """Determine market regime (trending vs ranging).
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            
        Returns:
            Market regime string ('trending' or 'ranging')
        """
        if not self.state_store:
            return "ranging"  # Default regime
            
        try:
            # Get recent composite signals to determine regime
            window_data = self.state_store.get_composite_signal_window(symbol, timeframe, limit=20)
            
            if len(window_data) < 5:
                return "ranging"
            
            # Extract recent scores
            recent_scores = [item["normalized_score"] for item in window_data[:5]]
            
            # Calculate trend strength (simplified)
            score_variance = statistics.variance(recent_scores) if len(recent_scores) > 1 else 0.0
            score_range = max(recent_scores) - min(recent_scores)
            
            # Simple regime detection: low variance and high range = trending
            if score_variance < 0.1 and score_range > 0.3:
                return "trending"
            else:
                return "ranging"
                
        except Exception as e:
            self.logger.warning(f"Failed to determine regime for {symbol}/{timeframe}: {e}")
            return "ranging"

    def set_state_store(self, state_store) -> None:
        """Set the state store for signal windows.
        
        Args:
            state_store: State store instance
        """
        self.state_store = state_store
        self.logger.info("State store set for signal windows")

    def get_signal_window_info(self, symbol: str, timeframe: str) -> dict[str, Any]:
        """Get information about signal windows for a symbol/timeframe.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            
        Returns:
            Dictionary with window information
        """
        if not self.state_store:
            return {"error": "State store not available"}
            
        try:
            info = {}
            
            # Get info for each strategy
            for strategy_name in self.strategies.keys():
                stats = self.state_store.get_signal_window_stats(symbol, timeframe, strategy_name)
                info[strategy_name] = stats
            
            # Get composite window info
            composite_window = self.state_store.get_composite_signal_window(symbol, timeframe, limit=1)
            if composite_window:
                info["composite"] = {
                    "latest_score": composite_window[0]["normalized_score"],
                    "latest_threshold": composite_window[0]["effective_threshold"],
                    "latest_regime": composite_window[0]["regime"],
                }
            
            return info
            
        except Exception as e:
            self.logger.error(f"Failed to get signal window info: {e}")
            return {"error": str(e)}

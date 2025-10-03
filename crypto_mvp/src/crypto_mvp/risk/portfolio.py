"""
Advanced portfolio management with Markowitz optimization.
"""

from typing import Any, Optional

import numpy as np

from ..core.logging_utils import LoggerMixin


class AdvancedPortfolioManager(LoggerMixin):
    """
    Advanced portfolio manager using Markowitz optimization for optimal asset allocation.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the advanced portfolio manager.

        Args:
            config: Portfolio management configuration (optional)
        """
        super().__init__()
        self.config = config or {}

        # Portfolio constraints
        self.max_positions = self.config.get("max_positions", 10)
        self.min_position_weight = self.config.get(
            "min_position_weight", 0.01
        )  # 1% minimum
        self.max_position_weight = self.config.get(
            "max_position_weight", 0.30
        )  # 30% maximum
        self.target_volatility = self.config.get(
            "target_volatility", 0.15
        )  # 15% target volatility
        
        # Correlation and exposure guardrails
        self.max_correlation = self.config.get("max_correlation", 0.7)  # 70% max correlation
        self.max_portfolio_risk = self.config.get("max_portfolio_risk", 0.05)  # 5% max portfolio risk
        self.sector_caps = self.config.get("sector_caps", {})  # Sector-specific caps
        self.asset_sectors = self.config.get("asset_sectors", {})  # Asset to sector mapping

        # Optimization parameters
        self.risk_aversion = self.config.get(
            "risk_aversion", 1.0
        )  # Risk aversion parameter
        self.correlation_penalty = self.config.get(
            "correlation_penalty", 0.5
        )  # Correlation penalty factor
        self.expected_return_boost = self.config.get(
            "expected_return_boost", 1.2
        )  # Return boost factor

        # Fallback parameters
        self.default_volatility = self.config.get(
            "default_volatility", 0.20
        )  # 20% default volatility
        self.default_correlation = self.config.get(
            "default_correlation", 0.3
        )  # 30% default correlation

        self.initialized = False

    def initialize(self) -> None:
        """Initialize the portfolio manager."""
        if self.initialized:
            self.logger.info("AdvancedPortfolioManager already initialized")
            return

        self.logger.info("Initializing AdvancedPortfolioManager")
        self.logger.info(f"Max positions: {self.max_positions}")
        self.logger.info(f"Target volatility: {self.target_volatility:.1%}")
        self.logger.info(f"Risk aversion: {self.risk_aversion}")

        self.initialized = True

    def optimize_portfolio_allocation(
        self,
        available_capital: float,
        signals: dict[str, dict[str, Any]],
        current_positions: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Optimize portfolio allocation using Markowitz optimization.

        Args:
            available_capital: Available capital for investment
            signals: Dictionary of signals for each asset
            current_positions: Current position sizes (optional)

        Returns:
            Dictionary containing:
            - optimal_weights: Dict of optimal weights for each asset
            - expected_return: Expected portfolio return
            - expected_volatility: Expected portfolio volatility
            - sharpe_ratio: Expected Sharpe ratio
            - metadata: Additional optimization details
        """
        if not self.initialized:
            self.initialize()

        self.logger.debug(f"Optimizing portfolio allocation for {len(signals)} assets")

        # Filter signals to max_positions
        filtered_signals = self._filter_signals(signals)

        if not filtered_signals:
            return self._empty_portfolio_result()

        # Calculate expected returns
        expected_returns = self._calculate_expected_return(filtered_signals)

        # Calculate correlation matrix
        correlation_matrix = self._calculate_correlation_matrix(filtered_signals)

        # Calculate covariance matrix
        covariance_matrix = self._calculate_covariance_matrix(
            filtered_signals, correlation_matrix
        )

        # Perform Markowitz optimization
        optimal_weights = self._markowitz_optimization(
            expected_returns, covariance_matrix, filtered_signals
        )

        # Calculate portfolio metrics
        portfolio_metrics = self._calculate_portfolio_metrics(
            optimal_weights, expected_returns, covariance_matrix
        )

        # Generate metadata
        metadata = {
            "total_assets": len(filtered_signals),
            "available_capital": available_capital,
            "optimization_method": "markowitz",
            "risk_aversion": self.risk_aversion,
            "target_volatility": self.target_volatility,
            "correlation_penalty": self.correlation_penalty,
            "expected_return_boost": self.expected_return_boost,
            "filtered_assets": list(filtered_signals.keys()),
            "excluded_assets": list(set(signals.keys()) - set(filtered_signals.keys())),
        }

        result = {
            "optimal_weights": optimal_weights,
            "expected_return": portfolio_metrics["expected_return"],
            "expected_volatility": portfolio_metrics["expected_volatility"],
            "sharpe_ratio": portfolio_metrics["sharpe_ratio"],
            "metadata": metadata,
        }

        # Validate weights sum to approximately 1.0
        weight_sum = sum(optimal_weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            self.logger.warning(f"Portfolio weights sum to {weight_sum:.3f}, not 1.0")

        self.logger.info(
            f"Portfolio optimization complete: {len(optimal_weights)} positions, "
            f"expected return {portfolio_metrics['expected_return']:.1%}, "
            f"volatility {portfolio_metrics['expected_volatility']:.1%}"
        )

        return result

    def _calculate_expected_return(
        self, signals: dict[str, dict[str, Any]]
    ) -> dict[str, float]:
        """Calculate expected returns from signal data.

        Args:
            signals: Dictionary of signals for each asset

        Returns:
            Dictionary of expected returns for each asset
        """
        expected_returns = {}

        for asset, signal_data in signals.items():
            # Extract signal information
            signal_score = signal_data.get("score", 0.0)
            signal_confidence = signal_data.get("confidence", 0.0)
            signal_strength = signal_data.get("signal_strength", 0.0)

            # Base expected return from signal strength and confidence
            base_return = (signal_strength + signal_confidence) / 2

            # Adjust based on signal score direction
            if signal_score > 0:
                # Positive signal - boost expected return
                score_adjustment = signal_score * 0.1  # Up to 10% additional return
            else:
                # Negative signal - reduce expected return
                score_adjustment = signal_score * 0.05  # Up to 5% reduction

            # Apply return boost factor
            expected_return = (
                base_return + score_adjustment
            ) * self.expected_return_boost

            # Clamp to reasonable bounds
            expected_return = max(-0.20, min(0.30, expected_return))  # -20% to +30%

            expected_returns[asset] = expected_return

        return expected_returns

    def _calculate_correlation_matrix(
        self, signals: dict[str, dict[str, Any]]
    ) -> np.ndarray:
        """Calculate correlation matrix from signal data.

        Args:
            signals: Dictionary of signals for each asset

        Returns:
            Correlation matrix (numpy array)
        """
        n_assets = len(signals)
        asset_names = list(signals.keys())

        if n_assets <= 1:
            return np.array([[1.0]])

        # Initialize correlation matrix
        correlation_matrix = np.eye(n_assets)

        # Extract correlation data from signals
        correlations = {}
        for asset, signal_data in signals.items():
            correlation_data = signal_data.get("correlation", {})
            if isinstance(correlation_data, dict):
                correlations[asset] = correlation_data
            else:
                # Single correlation value
                correlations[asset] = {
                    other_asset: correlation_data
                    for other_asset in asset_names
                    if other_asset != asset
                }

        # Fill correlation matrix
        for i, asset1 in enumerate(asset_names):
            for j, asset2 in enumerate(asset_names):
                if i != j:
                    # Try to get correlation from signal data
                    correlation = None

                    if asset1 in correlations and asset2 in correlations[asset1]:
                        correlation = correlations[asset1][asset2]
                    elif asset2 in correlations and asset1 in correlations[asset2]:
                        correlation = correlations[asset2][asset1]

                    if correlation is not None:
                        # Clamp correlation to valid range
                        correlation = max(-1.0, min(1.0, correlation))
                    else:
                        # Use default correlation
                        correlation = self.default_correlation

                    correlation_matrix[i, j] = correlation

        # Ensure matrix is symmetric
        correlation_matrix = (correlation_matrix + correlation_matrix.T) / 2

        # Ensure diagonal is 1.0
        np.fill_diagonal(correlation_matrix, 1.0)

        return correlation_matrix

    def _calculate_covariance_matrix(
        self, signals: dict[str, dict[str, Any]], correlation_matrix: np.ndarray
    ) -> np.ndarray:
        """Calculate covariance matrix from volatilities and correlations.

        Args:
            signals: Dictionary of signals for each asset
            correlation_matrix: Correlation matrix

        Returns:
            Covariance matrix (numpy array)
        """
        n_assets = len(signals)
        asset_names = list(signals.keys())

        # Extract volatilities
        volatilities = []
        for asset in asset_names:
            signal_data = signals[asset]
            volatility = signal_data.get("volatility", self.default_volatility)
            volatilities.append(volatility)

        volatilities = np.array(volatilities)

        # Calculate covariance matrix: Cov = Corr * Std * Std^T
        std_matrix = np.outer(volatilities, volatilities)
        covariance_matrix = correlation_matrix * std_matrix

        return covariance_matrix

    def _markowitz_optimization(
        self,
        expected_returns: dict[str, float],
        covariance_matrix: np.ndarray,
        signals: dict[str, dict[str, Any]],
    ) -> dict[str, float]:
        """Perform Markowitz optimization with correlation penalties.

        Args:
            expected_returns: Expected returns for each asset
            covariance_matrix: Covariance matrix
            signals: Signal data for additional constraints

        Returns:
            Dictionary of optimal weights
        """
        n_assets = len(expected_returns)
        asset_names = list(expected_returns.keys())

        if n_assets == 0:
            return {}

        if n_assets == 1:
            # Single asset - allocate 100%
            return {asset_names[0]: 1.0}

        # Convert to numpy arrays
        mu = np.array([expected_returns[asset] for asset in asset_names])
        Sigma = covariance_matrix

        # Apply correlation penalty to covariance matrix
        Sigma_penalized = self._apply_correlation_penalty(Sigma, signals)

        # Simple heuristic optimization (convex approximation)
        # Objective: maximize (expected_return - risk_aversion * variance)

        # Calculate risk-adjusted returns
        risk_adjusted_returns = mu - self.risk_aversion * np.diag(Sigma_penalized)

        # Apply signal confidence weighting
        confidence_weights = np.array(
            [signals[asset].get("confidence", 0.5) for asset in asset_names]
        )

        # Combine risk-adjusted returns with confidence
        combined_scores = risk_adjusted_returns * confidence_weights

        # Softmax-like allocation (exponential weighting)
        # Add temperature parameter to control concentration
        temperature = 2.0
        exp_scores = np.exp(combined_scores * temperature)

        # Normalize to get weights
        weights = exp_scores / np.sum(exp_scores)

        # Apply position constraints
        weights = self._apply_position_constraints(weights, asset_names, signals)

        # Convert back to dictionary
        optimal_weights = {asset_names[i]: weights[i] for i in range(n_assets)}

        return optimal_weights

    def _apply_correlation_penalty(
        self, covariance_matrix: np.ndarray, signals: dict[str, dict[str, Any]]
    ) -> np.ndarray:
        """Apply correlation penalty to covariance matrix.

        Args:
            covariance_matrix: Original covariance matrix
            signals: Signal data

        Returns:
            Penalized covariance matrix
        """
        n_assets = covariance_matrix.shape[0]
        asset_names = list(signals.keys())

        # Create penalty matrix
        penalty_matrix = np.ones_like(covariance_matrix)

        # Apply correlation penalty to off-diagonal elements
        for i in range(n_assets):
            for j in range(n_assets):
                if i != j:
                    correlation = covariance_matrix[i, j] / (
                        np.sqrt(covariance_matrix[i, i] * covariance_matrix[j, j])
                    )
                    # Higher correlation = higher penalty
                    penalty = 1.0 + self.correlation_penalty * abs(correlation)
                    penalty_matrix[i, j] = penalty

        # Apply penalties
        penalized_covariance = covariance_matrix * penalty_matrix

        return penalized_covariance

    def _apply_position_constraints(
        self,
        weights: np.ndarray,
        asset_names: list[str],
        signals: dict[str, dict[str, Any]],
    ) -> np.ndarray:
        """Apply position size constraints.

        Args:
            weights: Raw weights
            asset_names: List of asset names
            signals: Signal data

        Returns:
            Constrained weights
        """
        # Apply minimum position weight constraint
        weights = np.maximum(weights, 0.0)  # Ensure non-negative

        # Remove positions below minimum threshold
        min_threshold = self.min_position_weight
        weights[weights < min_threshold] = 0.0

        # Apply maximum position weight constraint
        max_threshold = self.max_position_weight
        weights = np.minimum(weights, max_threshold)

        # Limit to max_positions
        if len(weights) > self.max_positions:
            # Keep only top max_positions
            top_indices = np.argsort(weights)[-self.max_positions :]
            new_weights = np.zeros_like(weights)
            new_weights[top_indices] = weights[top_indices]
            weights = new_weights

        # Renormalize to sum to 1.0
        weight_sum = np.sum(weights)
        if weight_sum > 0:
            weights = weights / weight_sum
        else:
            # If all weights are zero, distribute equally among top assets
            top_assets = min(self.max_positions, len(asset_names))
            weights = np.zeros_like(weights)
            if top_assets > 0:
                weights[:top_assets] = 1.0 / top_assets

        return weights

    def _calculate_portfolio_metrics(
        self,
        weights: dict[str, float],
        expected_returns: dict[str, float],
        covariance_matrix: np.ndarray,
    ) -> dict[str, float]:
        """Calculate portfolio metrics.

        Args:
            weights: Portfolio weights
            expected_returns: Expected returns
            covariance_matrix: Covariance matrix

        Returns:
            Dictionary of portfolio metrics
        """
        if not weights:
            return {
                "expected_return": 0.0,
                "expected_volatility": 0.0,
                "sharpe_ratio": 0.0,
            }

        asset_names = list(weights.keys())
        n_assets = len(asset_names)

        # Convert to numpy arrays
        w = np.array([weights[asset] for asset in asset_names])
        mu = np.array([expected_returns[asset] for asset in asset_names])

        # Calculate expected return
        expected_return = np.dot(w, mu)

        # Calculate expected volatility
        if n_assets == 1:
            expected_volatility = np.sqrt(covariance_matrix[0, 0])
        else:
            expected_volatility = np.sqrt(np.dot(w, np.dot(covariance_matrix, w)))

        # Calculate Sharpe ratio (assuming risk-free rate of 2%)
        risk_free_rate = 0.02
        sharpe_ratio = (
            (expected_return - risk_free_rate) / expected_volatility
            if expected_volatility > 0
            else 0.0
        )

        return {
            "expected_return": expected_return,
            "expected_volatility": expected_volatility,
            "sharpe_ratio": sharpe_ratio,
        }

    def _filter_signals(
        self, signals: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Filter signals with correlation and exposure guardrails.

        Args:
            signals: All available signals

        Returns:
            Filtered signals respecting all constraints
        """
        if not signals:
            return {}

        self.logger.debug(f"Filtering {len(signals)} signals with guardrails")
        
        # Step 1: Apply sector caps
        sector_filtered = self._apply_sector_caps(signals)
        self.logger.debug(f"After sector caps: {len(sector_filtered)} signals")
        
        # Step 2: Apply correlation constraints
        correlation_filtered = self._apply_correlation_constraints(sector_filtered)
        self.logger.debug(f"After correlation constraints: {len(correlation_filtered)} signals")
        
        # Step 3: Apply position limits
        position_filtered = self._apply_position_limits(correlation_filtered)
        self.logger.debug(f"After position limits: {len(position_filtered)} signals")
        
        # Step 4: Apply risk budget constraints
        risk_filtered = self._apply_risk_budget_constraints(position_filtered)
        self.logger.debug(f"After risk budget constraints: {len(risk_filtered)} signals")
        
        return risk_filtered

    def _apply_sector_caps(self, signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Apply sector caps to limit exposure to specific sectors.
        
        Args:
            signals: All available signals
            
        Returns:
            Signals filtered by sector caps
        """
        if not self.sector_caps or not self.asset_sectors:
            return signals
        
        # Group assets by sector
        sector_assets = {}
        for asset, signal_data in signals.items():
            sector = self.asset_sectors.get(asset, "unknown")
            if sector not in sector_assets:
                sector_assets[sector] = []
            sector_assets[sector].append((asset, signal_data))
        
        filtered_signals = {}
        
        for sector, assets in sector_assets.items():
            sector_cap = self.sector_caps.get(sector, 1.0)  # Default 100% if no cap
            
            if sector_cap >= 1.0:
                # No cap, include all assets in this sector
                for asset, signal_data in assets:
                    filtered_signals[asset] = signal_data
            else:
                # Apply sector cap - select best assets up to the cap
                max_assets_in_sector = max(1, int(len(assets) * sector_cap))
                
                # Score assets in this sector
                sector_scores = []
                for asset, signal_data in assets:
                    score = self._calculate_signal_score(signal_data)
                    sector_scores.append((asset, signal_data, score))
                
                # Sort by score and take top assets
                sector_scores.sort(key=lambda x: x[2], reverse=True)
                for asset, signal_data, _ in sector_scores[:max_assets_in_sector]:
                    filtered_signals[asset] = signal_data
                
                self.logger.debug(f"Sector {sector}: {len(assets)} -> {max_assets_in_sector} assets (cap: {sector_cap:.1%})")
        
        return filtered_signals

    def _apply_correlation_constraints(self, signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Apply correlation constraints to reduce highly correlated positions.
        
        Args:
            signals: Signals to filter
            
        Returns:
            Signals filtered by correlation constraints
        """
        if len(signals) <= 1:
            return signals
        
        # Calculate correlation matrix
        correlation_matrix = self._calculate_correlation_matrix(signals)
        assets = list(signals.keys())
        
        # Find highly correlated pairs
        highly_correlated = []
        for i, asset1 in enumerate(assets):
            for j, asset2 in enumerate(assets[i+1:], i+1):
                # Get correlation from numpy array
                correlation = abs(correlation_matrix[i, j])
                if correlation > self.max_correlation:
                    highly_correlated.append((asset1, asset2, correlation))
        
        if not highly_correlated:
            return signals
        
        self.logger.debug(f"Found {len(highly_correlated)} highly correlated pairs (>{self.max_correlation:.1%})")
        
        # Create conflict graph and resolve conflicts
        filtered_signals = signals.copy()
        
        for asset1, asset2, correlation in highly_correlated:
            if asset1 in filtered_signals and asset2 in filtered_signals:
                # Keep the asset with higher signal score
                score1 = self._calculate_signal_score(filtered_signals[asset1])
                score2 = self._calculate_signal_score(filtered_signals[asset2])
                
                if score1 >= score2:
                    removed_asset = asset2
                    kept_asset = asset1
                else:
                    removed_asset = asset1
                    kept_asset = asset2
                
                del filtered_signals[removed_asset]
                self.logger.debug(f"Removed {removed_asset} (correlation {correlation:.1%} with {kept_asset})")
        
        return filtered_signals

    def _apply_position_limits(self, signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Apply maximum position limits.
        
        Args:
            signals: Signals to filter
            
        Returns:
            Signals filtered by position limits
        """
        if len(signals) <= self.max_positions:
            return signals
        
        # Score all signals
        signal_scores = []
        for asset, signal_data in signals.items():
            score = self._calculate_signal_score(signal_data)
            signal_scores.append((asset, signal_data, score))
        
        # Sort by score and keep top max_positions
        signal_scores.sort(key=lambda x: x[2], reverse=True)
        top_signals = signal_scores[:self.max_positions]
        
        filtered_signals = {asset: signal_data for asset, signal_data, _ in top_signals}
        
        self.logger.debug(f"Position limit: {len(signals)} -> {len(filtered_signals)} assets")
        
        return filtered_signals

    def _apply_risk_budget_constraints(self, signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Apply portfolio risk budget constraints.
        
        Args:
            signals: Signals to filter
            
        Returns:
            Signals filtered by risk budget constraints
        """
        if not signals:
            return signals
        
        # Calculate individual asset risks
        asset_risks = {}
        for asset, signal_data in signals.items():
            # Estimate risk from signal volatility or use default
            volatility = signal_data.get("volatility", self.default_volatility)
            confidence = signal_data.get("confidence", 0.5)
            
            # Risk scales with volatility and inversely with confidence
            estimated_risk = volatility * (1.0 - confidence * 0.5)
            asset_risks[asset] = estimated_risk
        
        # Sort by risk-adjusted score (score / risk)
        risk_adjusted_scores = []
        for asset, signal_data in signals.items():
            score = self._calculate_signal_score(signal_data)
            risk = asset_risks[asset]
            risk_adjusted_score = score / max(risk, 0.01)  # Avoid division by zero
            risk_adjusted_scores.append((asset, signal_data, risk_adjusted_score, risk))
        
        # Greedily select assets while respecting risk budget
        selected_signals = {}
        total_risk = 0.0
        
        risk_adjusted_scores.sort(key=lambda x: x[2], reverse=True)
        
        for asset, signal_data, risk_adjusted_score, risk in risk_adjusted_scores:
            if total_risk + risk <= self.max_portfolio_risk:
                selected_signals[asset] = signal_data
                total_risk += risk
            else:
                self.logger.debug(f"Risk budget exceeded, skipping {asset} (risk: {risk:.1%})")
        
        self.logger.debug(f"Risk budget: {total_risk:.1%} / {self.max_portfolio_risk:.1%}")
        
        return selected_signals

    def _calculate_signal_score(self, signal_data: dict[str, Any]) -> float:
        """Calculate a combined signal score for ranking.
        
        Args:
            signal_data: Signal data dictionary
            
        Returns:
            Combined signal score
        """
        score = signal_data.get("score", 0.0)
        confidence = signal_data.get("confidence", 0.0)
        signal_strength = signal_data.get("signal_strength", 0.0)
        
        # Combined score with weights
        combined_score = abs(score) * 0.4 + confidence * 0.3 + signal_strength * 0.3
        
        return combined_score

    def _empty_portfolio_result(self) -> dict[str, Any]:
        """Return empty portfolio result.

        Returns:
            Empty portfolio result
        """
        return {
            "optimal_weights": {},
            "expected_return": 0.0,
            "expected_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "metadata": {
                "total_assets": 0,
                "available_capital": 0.0,
                "optimization_method": "markowitz",
                "risk_aversion": self.risk_aversion,
                "target_volatility": self.target_volatility,
                "correlation_penalty": self.correlation_penalty,
                "expected_return_boost": self.expected_return_boost,
                "filtered_assets": [],
                "excluded_assets": [],
            },
        }

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get portfolio manager summary.

        Returns:
            Portfolio manager summary
        """
        return {
            "max_positions": self.max_positions,
            "min_position_weight": self.min_position_weight,
            "max_position_weight": self.max_position_weight,
            "target_volatility": self.target_volatility,
            "risk_aversion": self.risk_aversion,
            "correlation_penalty": self.correlation_penalty,
            "expected_return_boost": self.expected_return_boost,
            "default_volatility": self.default_volatility,
            "default_correlation": self.default_correlation,
        }

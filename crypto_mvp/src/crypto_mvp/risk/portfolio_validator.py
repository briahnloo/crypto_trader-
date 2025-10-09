"""
Portfolio Validator with Auto-Reconciliation.

This module provides intelligent validation that:
1. Logs exact reasons and diffs (cash Δ, positions Δ, fee calc, rounding deltas)
2. Uses adaptive epsilon tolerance: max($0.02, 3 * price_step * qty)
3. Auto-reconciles non-critical mismatches and commits
4. Only hard-fails on negative balances or cross-symbol leaks
5. Marks reconciliations as RECONCILED in logs
"""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

from ..core.money import D, q_money, to_dec, ZERO, get_exchange_steps, quantize_price, ensure_decimal
from ..core.logging_utils import LoggerMixin

logger = logging.getLogger(__name__)


@dataclass
class ValidationDiff:
    """Detailed differences for validation logging."""
    cash_delta: Decimal
    positions_value_delta: Decimal
    realized_pnl_delta: Decimal
    total_equity_delta: Decimal
    fee_discrepancy: Decimal
    rounding_delta: Decimal
    per_symbol_deltas: Dict[str, Decimal]


@dataclass
class ValidationResult:
    """Result of portfolio validation."""
    is_valid: bool
    is_reconciled: bool
    should_commit: bool
    severity: str  # "ok", "reconciled", "warning", "critical"
    reason: str
    diff: Optional[ValidationDiff]
    epsilon_used: Decimal
    

class PortfolioValidator(LoggerMixin):
    """
    Portfolio validator with auto-reconciliation for non-critical mismatches.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize portfolio validator.
        
        Args:
            config: Configuration dictionary
        """
        super().__init__()
        self.config = config or {}
        
        # Base tolerance
        self.base_epsilon = to_dec("0.02")  # $0.02 base tolerance
        
        # Reconciliation settings
        self.auto_reconcile_enabled = self.config.get("auto_reconcile_enabled", True)
        self.max_auto_reconcile_pct = to_dec(self.config.get("max_auto_reconcile_pct", 0.001))  # 0.1%
        
        logger.info(
            f"PortfolioValidator initialized: "
            f"base_epsilon=${float(self.base_epsilon):.2f}, "
            f"auto_reconcile={self.auto_reconcile_enabled}"
        )
    
    def calculate_adaptive_epsilon(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal
    ) -> Decimal:
        """
        Calculate adaptive epsilon tolerance based on symbol and quantity.
        
        Formula: max($0.02, 3 * price_step * qty)
        
        Args:
            symbol: Trading symbol
            quantity: Position quantity
            price: Current price
            
        Returns:
            Epsilon tolerance as Decimal
        """
        # Get exchange steps
        steps = get_exchange_steps(symbol)
        price_step = steps["price_step"]
        
        # Calculate quantity-based epsilon
        qty_epsilon = to_dec("3") * price_step * abs(quantity)
        
        # Take maximum of base epsilon and quantity-based epsilon
        epsilon = max(self.base_epsilon, qty_epsilon)
        
        logger.debug(
            f"Adaptive epsilon for {symbol}: ${float(epsilon):.4f} "
            f"(base=${float(self.base_epsilon):.2f}, "
            f"3*price_step*qty=${float(qty_epsilon):.4f})"
        )
        
        return epsilon
    
    def validate_portfolio_state(
        self,
        expected_cash: Decimal,
        actual_cash: Decimal,
        expected_positions_value: Decimal,
        actual_positions_value: Decimal,
        expected_realized_pnl: Decimal,
        actual_realized_pnl: Decimal,
        previous_equity: Decimal,
        positions: Dict[str, Dict[str, Any]],
        fees_charged: Decimal
    ) -> ValidationResult:
        """
        Validate portfolio state with detailed diff logging and auto-reconciliation.
        
        Args:
            expected_cash: Expected cash balance
            actual_cash: Actual cash balance
            expected_positions_value: Expected total positions value
            actual_positions_value: Actual total positions value
            expected_realized_pnl: Expected realized P&L
            actual_realized_pnl: Actual realized P&L
            previous_equity: Previous cycle's equity
            positions: Current positions dictionary
            fees_charged: Total fees charged this cycle
            
        Returns:
            ValidationResult with decision and details
        """
        # Ensure all inputs are Decimal
        expected_cash = D(expected_cash)
        actual_cash = D(actual_cash)
        expected_positions_value = D(expected_positions_value)
        actual_positions_value = D(actual_positions_value)
        expected_realized_pnl = D(expected_realized_pnl)
        actual_realized_pnl = D(actual_realized_pnl)
        previous_equity = D(previous_equity)
        fees_charged = D(fees_charged)
        
        # Calculate deltas
        cash_delta = abs(expected_cash - actual_cash)
        positions_delta = abs(expected_positions_value - actual_positions_value)
        realized_pnl_delta = abs(expected_realized_pnl - actual_realized_pnl)
        
        # Calculate equity with q_money for consistent precision
        expected_equity = q_money(expected_cash + expected_positions_value + expected_realized_pnl)
        actual_equity = q_money(actual_cash + actual_positions_value + actual_realized_pnl)
        equity_delta = abs(expected_equity - actual_equity)
        
        # Calculate adaptive epsilon based on positions
        total_quantity_epsilon = ZERO
        per_symbol_deltas = {}
        
        for symbol, position in positions.items():
            qty = to_dec(position.get("quantity", 0))
            price = to_dec(position.get("current_price", position.get("entry_price", 0)))
            
            if qty != ZERO and price != ZERO:
                symbol_epsilon = self.calculate_adaptive_epsilon(symbol, qty, price)
                total_quantity_epsilon += symbol_epsilon
                
                # Calculate per-symbol delta for detailed logging
                expected_value = qty * price
                actual_value = to_dec(position.get("value", 0))
                per_symbol_deltas[symbol] = abs(expected_value - actual_value)
        
        # Use maximum of base epsilon and quantity-based epsilon
        epsilon = max(self.base_epsilon, total_quantity_epsilon)
        
        # Estimate fee discrepancy
        fee_discrepancy = ZERO  # Placeholder for fee calculation differences
        
        # Estimate rounding delta (sum of per-symbol rounding)
        rounding_delta = sum(per_symbol_deltas.values(), ZERO)
        
        # Create diff object
        diff = ValidationDiff(
            cash_delta=cash_delta,
            positions_value_delta=positions_delta,
            realized_pnl_delta=realized_pnl_delta,
            total_equity_delta=equity_delta,
            fee_discrepancy=fee_discrepancy,
            rounding_delta=rounding_delta,
            per_symbol_deltas=per_symbol_deltas
        )
        
        # Log detailed diff
        self._log_validation_diff(diff, epsilon)
        
        # Check for critical errors that should hard-fail
        critical_errors = self._check_critical_errors(
            actual_cash, actual_equity, positions, per_symbol_deltas
        )
        
        if critical_errors:
            self.logger.error(f"VALIDATION_CRITICAL: {', '.join(critical_errors)}")
            return ValidationResult(
                is_valid=False,
                is_reconciled=False,
                should_commit=False,
                severity="critical",
                reason="; ".join(critical_errors),
                diff=diff,
                epsilon_used=epsilon
            )
        
        # Check if within tolerance
        if equity_delta <= epsilon:
            # Within tolerance - all good
            return ValidationResult(
                is_valid=True,
                is_reconciled=False,
                should_commit=True,
                severity="ok",
                reason="within_tolerance",
                diff=diff,
                epsilon_used=epsilon
            )
        
        # Outside tolerance - check if reconcilable
        if self.auto_reconcile_enabled:
            # Calculate reconciliation percentage
            reconcile_pct = equity_delta / max(previous_equity, to_dec("1"))
            
            if reconcile_pct <= self.max_auto_reconcile_pct:
                # Non-critical mismatch - auto-reconcile
                self.logger.warning(
                    f"RECONCILED: Portfolio mismatch ${float(equity_delta):.4f} "
                    f"({float(reconcile_pct * to_dec('100')):.4f}%) auto-reconciled and committed"
                )
                
                return ValidationResult(
                    is_valid=True,
                    is_reconciled=True,
                    should_commit=True,
                    severity="reconciled",
                    reason=f"auto_reconciled_delta_{float(equity_delta):.4f}",
                    diff=diff,
                    epsilon_used=epsilon
                )
            else:
                # Mismatch too large for auto-reconcile
                self.logger.error(
                    f"VALIDATION_FAILED: Mismatch ${float(equity_delta):.4f} "
                    f"({float(reconcile_pct * to_dec('100')):.4f}%) exceeds auto-reconcile limit "
                    f"({float(self.max_auto_reconcile_pct * to_dec('100')):.4f}%)"
                )
                
                return ValidationResult(
                    is_valid=False,
                    is_reconciled=False,
                    should_commit=False,
                    severity="warning",
                    reason=f"mismatch_too_large_{float(reconcile_pct * to_dec('100')):.4f}pct",
                    diff=diff,
                    epsilon_used=epsilon
                )
        else:
            # Auto-reconcile disabled - fail validation
            self.logger.error(
                f"VALIDATION_FAILED: Mismatch ${float(equity_delta):.4f} "
                f"(auto-reconcile disabled)"
            )
            
            return ValidationResult(
                is_valid=False,
                is_reconciled=False,
                should_commit=False,
                severity="warning",
                reason="validation_failed_reconcile_disabled",
                diff=diff,
                epsilon_used=epsilon
            )
    
    def _check_critical_errors(
        self,
        cash: Decimal,
        equity: Decimal,
        positions: Dict[str, Dict[str, Any]],
        per_symbol_deltas: Dict[str, Decimal]
    ) -> List[str]:
        """
        Check for critical errors that should hard-fail.
        
        Args:
            cash: Current cash balance
            equity: Current total equity
            positions: Current positions
            per_symbol_deltas: Per-symbol deltas
            
        Returns:
            List of critical error messages (empty if no critical errors)
        """
        errors = []
        
        # Check for negative balances
        if cash < ZERO:
            errors.append(f"negative_cash_balance_{float(cash):.2f}")
        
        if equity < ZERO:
            errors.append(f"negative_equity_{float(equity):.2f}")
        
        # Check for cross-symbol leaks (position quantity mismatches across symbols)
        for symbol, position in positions.items():
            qty = to_dec(position.get("quantity", 0))
            value = to_dec(position.get("value", 0))
            price = to_dec(position.get("current_price", position.get("entry_price", 0)))
            
            if qty != ZERO and price != ZERO:
                expected_value = qty * price
                value_diff = abs(value - expected_value)
                
                # Check if difference is too large (>1% of expected value)
                if expected_value != ZERO and value_diff / expected_value > to_dec("0.01"):
                    errors.append(f"cross_symbol_leak_{symbol}_diff_{float(value_diff):.2f}")
        
        return errors
    
    def _log_validation_diff(self, diff: ValidationDiff, epsilon: Decimal) -> None:
        """
        Log detailed validation differences.
        
        Args:
            diff: ValidationDiff object with all deltas
            epsilon: Epsilon tolerance used
        """
        self.logger.info("=" * 80)
        self.logger.info("VALIDATION_DIFF_REPORT:")
        self.logger.info(f"  Epsilon tolerance: ${float(epsilon):.4f}")
        self.logger.info(f"  Cash Δ: ${float(diff.cash_delta):.4f}")
        self.logger.info(f"  Positions Value Δ: ${float(diff.positions_value_delta):.4f}")
        self.logger.info(f"  Realized P&L Δ: ${float(diff.realized_pnl_delta):.4f}")
        self.logger.info(f"  Total Equity Δ: ${float(diff.total_equity_delta):.4f}")
        self.logger.info(f"  Fee Discrepancy: ${float(diff.fee_discrepancy):.4f}")
        self.logger.info(f"  Rounding Δ: ${float(diff.rounding_delta):.4f}")
        
        if diff.per_symbol_deltas:
            self.logger.info("  Per-Symbol Deltas:")
            for symbol, delta in diff.per_symbol_deltas.items():
                if delta > ZERO:
                    self.logger.info(f"    {symbol}: ${float(delta):.4f}")
        
        self.logger.info("=" * 80)
    
    def get_validation_summary(self, result: ValidationResult) -> str:
        """Get formatted validation summary."""
        if result.severity == "ok":
            return f"VALIDATION_OK: within tolerance (Δ=${float(result.diff.total_equity_delta):.4f} ≤ ε=${float(result.epsilon_used):.4f})"
        elif result.severity == "reconciled":
            return f"RECONCILED: auto-reconciled and committed (Δ=${float(result.diff.total_equity_delta):.4f}, reason={result.reason})"
        elif result.severity == "critical":
            return f"VALIDATION_CRITICAL: {result.reason} - changes discarded"
        else:
            return f"VALIDATION_FAILED: {result.reason} (Δ=${float(result.diff.total_equity_delta):.4f})"


def validate_and_reconcile(
    expected_cash: float,
    actual_cash: float,
    expected_positions_value: float,
    actual_positions_value: float,
    expected_realized_pnl: float,
    actual_realized_pnl: float,
    previous_equity: float,
    positions: Dict[str, Dict[str, Any]],
    fees_charged: float,
    config: Optional[Dict[str, Any]] = None
) -> ValidationResult:
    """
    Convenience function for portfolio validation with auto-reconciliation.
    
    Args:
        expected_cash: Expected cash balance
        actual_cash: Actual cash balance
        expected_positions_value: Expected positions value
        actual_positions_value: Actual positions value
        expected_realized_pnl: Expected realized P&L
        actual_realized_pnl: Actual realized P&L
        previous_equity: Previous cycle's equity
        positions: Current positions dictionary
        fees_charged: Total fees charged
        config: Configuration dictionary
        
    Returns:
        ValidationResult with decision
    """
    validator = PortfolioValidator(config)
    
    return validator.validate_portfolio_state(
        expected_cash=to_dec(expected_cash),
        actual_cash=to_dec(actual_cash),
        expected_positions_value=to_dec(expected_positions_value),
        actual_positions_value=to_dec(actual_positions_value),
        expected_realized_pnl=to_dec(expected_realized_pnl),
        actual_realized_pnl=to_dec(actual_realized_pnl),
        previous_equity=to_dec(previous_equity),
        positions=positions,
        fees_charged=to_dec(fees_charged)
    )


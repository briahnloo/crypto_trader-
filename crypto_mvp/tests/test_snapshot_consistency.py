#!/usr/bin/env python3
"""
Test snapshot consistency for crypto trading bot.

This module tests that all panels pull consistent counts and P&L numbers
from the same snapshot source.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from portfolio.ledger import create_empty_ledger, Fill, Position, Ledger
from portfolio.snapshot import snapshot_from_ledger, PortfolioSnapshot
from src.crypto_mvp.ui_panels import (
    trades_today, trades_this_cycle, positions_count,
    format_cycle_header, format_valuation_block, format_daily_summary,
    format_position_breakdown, validate_counters_consistency, log_cycle_summary
)


class TestSnapshotConsistency:
    """Test snapshot consistency across all panels."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.initial_cash = 10000.0
        self.ledger = create_empty_ledger(self.initial_cash)
        
        # Create some mock fills
        self.fill1 = Fill(
            symbol="BTC/USDT",
            side="BUY",
            qty=0.002,
            price=50000.0,
            fees=2.50,
            ts=datetime.now(timezone.utc),
            sl=47750.0,
            tp=54230.0,
            strategy="test",
            meta={"mode": "atr"}
        )
        
        self.fill2 = Fill(
            symbol="ETH/USDT",
            side="BUY",
            qty=0.033,
            price=3000.0,
            fees=1.25,
            ts=datetime.now(timezone.utc),
            sl=2910.0,
            tp=3088.0,
            strategy="test",
            meta={"mode": "atr"}
        )
        
        # Add fills to ledger
        self.ledger.fills.append(self.fill1)
        self.ledger.fills.append(self.fill2)
        
        # Create positions
        self.ledger.positions["BTC/USDT"] = Position(
            symbol="BTC/USDT",
            qty=0.002,
            avg_cost=50000.0
        )
        
        self.ledger.positions["ETH/USDT"] = Position(
            symbol="ETH/USDT",
            qty=0.033,
            avg_cost=3000.0
        )
        
        # Mock marks
        self.marks = {
            "BTC/USDT": 50100.0,  # Slightly up
            "ETH/USDT": 2995.0    # Slightly down
        }
        
        # Create snapshot
        self.snapshot = snapshot_from_ledger(self.ledger, self.marks)
        
        # Mock session metrics
        self.session_metrics = {
            "session_id": "test_session",
            "start_time": datetime.now(timezone.utc)
        }
    
    def test_trades_today_count(self):
        """Test trades_today function counts correctly."""
        # Arrange
        today = datetime.now(timezone.utc).date()
        
        # Act
        count = trades_today(self.ledger)
        
        # Assert
        assert count == 2, f"Should count 2 trades today, got {count}"
        
        # Test with empty ledger
        empty_ledger = create_empty_ledger(1000.0)
        empty_count = trades_today(empty_ledger)
        assert empty_count == 0, f"Empty ledger should have 0 trades, got {empty_count}"
    
    def test_trades_this_cycle_count(self):
        """Test trades_this_cycle function counts correctly."""
        # Arrange
        committed_fills = [self.fill1, self.fill2]
        
        # Act
        count = trades_this_cycle(committed_fills)
        
        # Assert
        assert count == 2, f"Should count 2 trades this cycle, got {count}"
        
        # Test with empty list
        empty_count = trades_this_cycle([])
        assert empty_count == 0, f"Empty fills should have 0 trades, got {empty_count}"
    
    def test_positions_count(self):
        """Test positions_count function counts correctly."""
        # Act
        count = positions_count(self.snapshot)
        
        # Assert
        assert count == 2, f"Should count 2 positions, got {count}"
        
        # Test with empty snapshot
        empty_ledger = create_empty_ledger(1000.0)
        empty_snapshot = snapshot_from_ledger(empty_ledger, {})
        empty_count = positions_count(empty_snapshot)
        assert empty_count == 0, f"Empty snapshot should have 0 positions, got {empty_count}"
    
    def test_cycle_header_consistency(self):
        """Test cycle header uses consistent counters."""
        # Arrange
        cycle_id = 1
        duration = 0.5
        committed_fills = [self.fill1, self.fill2]
        
        # Act
        header = format_cycle_header(cycle_id, duration, self.snapshot, committed_fills)
        
        # Assert
        assert "Trading cycle #1 completed in 0.50s" in header
        assert "Trades: 2" in header
        assert "Positions: 2" in header
        assert "Equity: $" in header
    
    def test_valuation_block_consistency(self):
        """Test valuation block uses consistent position count."""
        # Act
        valuation = format_valuation_block(self.snapshot)
        
        # Assert
        assert "VALUATION:" in valuation
        assert "positions=2" in valuation
        assert "equity=$" in valuation
        assert "cash=$" in valuation
    
    def test_daily_summary_consistency(self):
        """Test daily summary uses ledger as source of truth."""
        # Act
        summary = format_daily_summary(self.ledger, self.session_metrics)
        
        # Assert
        assert "Daily Summary:" in summary
        assert "2 total trades" in summary
        assert "volume=" in summary
        assert "fees=$" in summary
        assert "notional=$" in summary
    
    def test_position_breakdown_consistency(self):
        """Test position breakdown uses snapshot data consistently."""
        # Act
        breakdown = format_position_breakdown(self.snapshot)
        
        # Assert
        assert "Positions (2):" in breakdown
        assert "BTC/USDT" in breakdown
        assert "ETH/USDT" in breakdown
        assert "qty=" in breakdown
        assert "avg_cost=" in breakdown
        assert "value=" in breakdown
        assert "pnl=" in breakdown
    
    def test_counter_consistency_validation(self):
        """Test that validate_counters_consistency works correctly."""
        # Arrange
        committed_fills = [self.fill1, self.fill2]
        
        # Act
        is_consistent = validate_counters_consistency(self.snapshot, committed_fills, self.ledger)
        
        # Assert
        assert is_consistent, "Counters should be consistent"
    
    def test_counter_consistency_with_mismatch(self):
        """Test counter consistency validation catches mismatches."""
        # Arrange - Create inconsistent state
        inconsistent_snapshot = PortfolioSnapshot(
            ts=datetime.now(timezone.utc),
            cash=9000.0,
            positions={"BTC/USDT": Position("BTC/USDT", 0.002, 50000.0)},
            marks={"BTC/USDT": 50000.0},
            equity=9100.0,
            unrealized_pnl=0.0,
            priced_positions=1  # Only 1 position with a mark
        )
        
        # Create a ledger with different number of fills
        inconsistent_ledger = create_empty_ledger(1000.0)
        inconsistent_ledger.fills = [self.fill1]  # Only 1 fill in ledger
        
        committed_fills = [self.fill1, self.fill2]  # 2 fills committed this cycle
        
        # Act
        is_consistent = validate_counters_consistency(inconsistent_snapshot, committed_fills, inconsistent_ledger)
        
        # Assert
        assert not is_consistent, "Should detect counter inconsistency"
    
    def test_mock_ledger_with_sol_position(self):
        """Test with mock ledger containing SOL position."""
        # Arrange
        sol_ledger = create_empty_ledger(5000.0)
        
        # Add SOL fill
        sol_fill = Fill(
            symbol="SOL/USDT",
            side="BUY",
            qty=1.0,
            price=100.0,
            fees=0.5,
            ts=datetime.now(timezone.utc),
            sl=98.0,
            tp=102.0,
            strategy="test",
            meta={"mode": "atr"}
        )
        
        sol_ledger.fills.append(sol_fill)
        sol_ledger.positions["SOL/USDT"] = Position(
            symbol="SOL/USDT",
            qty=1.0,
            avg_cost=100.0
        )
        
        sol_marks = {"SOL/USDT": 101.0}  # Slightly up
        sol_snapshot = snapshot_from_ledger(sol_ledger, sol_marks)
        
        # Act & Assert
        assert trades_today(sol_ledger) == 1, "Should count 1 SOL trade"
        assert positions_count(sol_snapshot) == 1, "Should count 1 SOL position"
        
        # Test all panels
        header = format_cycle_header(1, 0.1, sol_snapshot, [sol_fill])
        assert "Trades: 1" in header
        assert "Positions: 1" in header
        
        valuation = format_valuation_block(sol_snapshot)
        assert "positions=1" in valuation
        
        summary = format_daily_summary(sol_ledger, {})
        assert "1 total trades" in summary
        
        breakdown = format_position_breakdown(sol_snapshot)
        assert "Positions (1):" in breakdown
        assert "SOL/USDT" in breakdown
    
    def test_log_cycle_summary_integration(self):
        """Test complete cycle summary integration."""
        # Arrange
        cycle_id = 1
        duration = 0.3
        committed_fills = [self.fill1, self.fill2]
        
        # Mock logger to capture output
        import logging
        logger = logging.getLogger('test_logger')
        
        with patch('src.crypto_mvp.ui_panels.logger', logger):
            # Act
            log_cycle_summary(
                cycle_id=cycle_id,
                duration=duration,
                snapshot=self.snapshot,
                committed_fills=committed_fills,
                ledger=self.ledger,
                session_metrics=self.session_metrics
            )
        
        # Assert - This test mainly ensures no exceptions are thrown
        # In a real test, you'd capture logger output and verify content
        assert True, "Cycle summary should complete without errors"
    
    def test_edge_cases(self):
        """Test edge cases for consistency."""
        # Test with zero positions
        empty_ledger = create_empty_ledger(1000.0)
        empty_snapshot = snapshot_from_ledger(empty_ledger, {})
        
        assert positions_count(empty_snapshot) == 0
        assert trades_today(empty_ledger) == 0
        assert trades_this_cycle([]) == 0
        
        # Test with fractional positions (should count as 0 if very small)
        fractional_ledger = create_empty_ledger(1000.0)
        fractional_ledger.positions["BTC/USDT"] = Position(
            symbol="BTC/USDT",
            qty=1e-10,  # Very small
            avg_cost=50000.0
        )
        
        fractional_marks = {"BTC/USDT": 50000.0}
        fractional_snapshot = snapshot_from_ledger(fractional_ledger, fractional_marks)
        
        # Position with very small quantity should not count
        assert positions_count(fractional_snapshot) == 0, "Very small positions should not count"


if __name__ == "__main__":
    # Run tests
    test_instance = TestSnapshotConsistency()
    
    print("Running snapshot consistency tests...")
    
    test_instance.setup_method()
    
    try:
        test_instance.test_trades_today_count()
        print("✓ Test 1 PASSED: trades_today count")
        
        test_instance.test_trades_this_cycle_count()
        print("✓ Test 2 PASSED: trades_this_cycle count")
        
        test_instance.test_positions_count()
        print("✓ Test 3 PASSED: positions_count")
        
        test_instance.test_cycle_header_consistency()
        print("✓ Test 4 PASSED: cycle header consistency")
        
        test_instance.test_valuation_block_consistency()
        print("✓ Test 5 PASSED: valuation block consistency")
        
        test_instance.test_daily_summary_consistency()
        print("✓ Test 6 PASSED: daily summary consistency")
        
        test_instance.test_position_breakdown_consistency()
        print("✓ Test 7 PASSED: position breakdown consistency")
        
        test_instance.test_counter_consistency_validation()
        print("✓ Test 8 PASSED: counter consistency validation")
        
        test_instance.test_counter_consistency_with_mismatch()
        print("✓ Test 9 PASSED: counter consistency mismatch detection")
        
        test_instance.test_mock_ledger_with_sol_position()
        print("✓ Test 10 PASSED: mock ledger with SOL position")
        
        test_instance.test_log_cycle_summary_integration()
        print("✓ Test 11 PASSED: cycle summary integration")
        
        test_instance.test_edge_cases()
        print("✓ Test 12 PASSED: edge cases")
        
        print("\n🎉 All snapshot consistency tests passed!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

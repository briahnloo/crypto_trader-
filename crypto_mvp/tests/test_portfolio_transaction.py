"""
Test cases for PortfolioTransaction system.

Tests transactional portfolio mutations, validation epsilon handling,
and large interim swings scenarios.
"""

import pytest
import tempfile
import os
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.crypto_mvp.risk.portfolio_transaction import (
    PortfolioTransaction,
    portfolio_transaction,
    StagedCash,
    StagedPosition,
    StagedLotBook,
    StagedRealizedPnl
)
from src.crypto_mvp.risk.portfolio import AdvancedPortfolioManager
from src.crypto_mvp.state.store import StateStore


class TestPortfolioTransaction:
    """Test cases for PortfolioTransaction class."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        yield db_path
        
        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass
    
    @pytest.fixture
    def state_store(self, temp_db):
        """Create StateStore instance."""
        store = StateStore(temp_db)
        store.initialize()
        return store
    
    @pytest.fixture
    def portfolio_manager(self):
        """Create PortfolioManager instance."""
        return AdvancedPortfolioManager()
    
    @pytest.fixture
    def session_id(self):
        """Generate test session ID."""
        return "test_session_123"
    
    @pytest.fixture
    def setup_session(self, state_store, session_id):
        """Setup test session with initial state."""
        # Create new session with $100,000 starting capital
        initial_cash = 100000.0
        state_store.save_cash_equity(
            cash_balance=initial_cash,
            total_equity=initial_cash,
            total_fees=0.0,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            session_id=session_id,
            previous_equity=initial_cash
        )
        
        # Add some test positions
        state_store.save_position(
            symbol="BTC/USDT",
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            strategy="test_strategy",
            session_id=session_id
        )
        
        return initial_cash
    
    def test_validation_epsilon_calculation(self):
        """Test validation epsilon calculation."""
        # Test with different previous equity values
        test_cases = [
            (100000.0, 10.0),  # 0.0001 * 100000 = 10.0, max(1.0, 10.0) = 10.0
            (5000.0, 5.0),     # 0.0001 * 5000 = 0.5, max(1.0, 0.5) = 1.0
            (1000.0, 1.0),     # 0.0001 * 1000 = 0.1, max(1.0, 0.1) = 1.0
            (0.0, 1.0),        # 0.0001 * 0 = 0.0, max(1.0, 0.0) = 1.0
        ]
        
        for previous_equity, expected_epsilon in test_cases:
            transaction = PortfolioTransaction(
                state_store=Mock(),
                portfolio_manager=Mock(),
                previous_equity=previous_equity,
                session_id="test",
                validation_epsilon=None  # Auto-calculate
            )
            assert transaction.validation_epsilon == expected_epsilon, \
                f"Expected epsilon {expected_epsilon} for equity {previous_equity}, got {transaction.validation_epsilon}"
    
    def test_custom_validation_epsilon(self):
        """Test custom validation epsilon."""
        transaction = PortfolioTransaction(
            state_store=Mock(),
            portfolio_manager=Mock(),
            previous_equity=100000.0,
            session_id="test",
            validation_epsilon=50.0
        )
        assert transaction.validation_epsilon == 50.0
    
    def test_staging_mechanisms(self, state_store, portfolio_manager, session_id, setup_session):
        """Test all staging mechanisms work correctly."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage cash changes
            tx.stage_cash_delta(-5000.0, fees=25.0)  # Buy order
            tx.stage_cash_delta(3000.0, fees=15.0)   # Sell order
            
            # Stage position changes
            tx.stage_position_delta("BTC/USDT", 0.1, entry_price=50000.0, current_price=51000.0)
            tx.stage_position_delta("ETH/USDT", 10.0, entry_price=3000.0, current_price=3100.0)
            
            # Stage lot changes
            tx.stage_lot_add("BTC/USDT", {
                "lot_id": "btc_lot_1",
                "quantity": 0.1,
                "cost_price": 50000.0,
                "fee": 25.0,
                "timestamp": datetime.now(timezone.utc)
            })
            
            # Stage realized P&L
            tx.stage_realized_pnl_delta(500.0)
            
            # Verify staged changes
            assert tx.staged_cash.delta == -2000.0  # -5000 + 3000
            assert tx.staged_cash.fees == 40.0      # 25 + 15
            assert tx.staged_realized_pnl.delta == 500.0
            
            assert "BTC/USDT" in tx.staged_positions
            assert "ETH/USDT" in tx.staged_positions
            assert tx.staged_positions["BTC/USDT"].quantity_delta == 0.1
            
            assert "BTC/USDT" in tx.staged_lotbooks
            assert len(tx.staged_lotbooks["BTC/USDT"].lots_to_add) == 1
    
    def test_successful_commit(self, state_store, portfolio_manager, session_id, setup_session):
        """Test successful transaction commit."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage reasonable changes within validation epsilon
            tx.stage_cash_delta(-1000.0, fees=5.0)  # Small buy order
            tx.stage_realized_pnl_delta(100.0)      # Small profit
            
            # Commit with current mark prices
            mark_prices = {"BTC/USDT": 51000.0}
            success = tx.commit(mark_prices)
            
            assert success, "Transaction should commit successfully"
            assert tx.committed, "Transaction should be marked as committed"
            
            # Verify changes were applied to state store
            latest_cash_equity = state_store.get_latest_cash_equity(session_id)
            assert latest_cash_equity["cash_balance"] == 98995.0  # 100000 - 1000 - 5
            assert latest_cash_equity["total_realized_pnl"] == 100.0
    
    def test_validation_failure_rollback(self, state_store, portfolio_manager, session_id, setup_session):
        """Test transaction rollback on validation failure."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage large changes that exceed validation epsilon
            # With previous_equity=100000, epsilon=10.0
            tx.stage_cash_delta(-50000.0, fees=250.0)  # Large buy order
            tx.stage_realized_pnl_delta(10000.0)       # Large profit
            
            # Attempt commit - should fail validation
            mark_prices = {"BTC/USDT": 50000.0}
            success = tx.commit(mark_prices)
            
            assert not success, "Transaction should fail validation"
            assert tx.rolled_back, "Transaction should be rolled back"
            assert not tx.committed, "Transaction should not be committed"
            
            # Verify no changes were applied to state store
            latest_cash_equity = state_store.get_latest_cash_equity(session_id)
            assert latest_cash_equity["cash_balance"] == 100000.0  # Unchanged
            assert latest_cash_equity["total_realized_pnl"] == 0.0  # Unchanged
    
    def test_large_interim_swings_scenario(self, state_store, portfolio_manager, session_id, setup_session):
        """Test large interim swings before pricing - should not cause premature errors."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Simulate large interim swings during staging
            # These would cause validation errors if checked immediately
            
            # Stage massive buy order (would fail if validated immediately)
            tx.stage_cash_delta(-80000.0, fees=400.0)  # 80% of portfolio
            
            # Stage massive position changes
            tx.stage_position_delta("BTC/USDT", 5.0, entry_price=50000.0)  # $250k position
            tx.stage_position_delta("ETH/USDT", 100.0, entry_price=3000.0)  # $300k position
            
            # Stage large realized P&L swing
            tx.stage_realized_pnl_delta(50000.0)  # Massive profit
            
            # At this point, if we validated immediately, it would fail
            # But we don't validate until commit with final mark prices
            
            # Now apply final mark prices that make the transaction valid
            # Assume prices moved significantly in our favor
            final_mark_prices = {
                "BTC/USDT": 60000.0,  # BTC up 20%
                "ETH/USDT": 3500.0    # ETH up 16.7%
            }
            
            # Commit should succeed because final staged state is valid
            success = tx.commit(final_mark_prices)
            
            assert success, "Transaction should commit successfully with final mark prices"
            assert tx.committed, "Transaction should be marked as committed"
            
            # Verify the large changes were applied
            latest_cash_equity = state_store.get_latest_cash_equity(session_id)
            assert latest_cash_equity["cash_balance"] == 19599.0  # 100000 - 80000 - 400 + 50000
            assert latest_cash_equity["total_realized_pnl"] == 50000.0
            
            # Verify positions were updated
            positions = state_store.get_positions(session_id)
            btc_pos = next((p for p in positions if p["symbol"] == "BTC/USDT"), None)
            eth_pos = next((p for p in positions if p["symbol"] == "ETH/USDT"), None)
            
            assert btc_pos is not None
            assert btc_pos["quantity"] == 6.0  # 1.0 original + 5.0 staged
            assert eth_pos is not None
            assert eth_pos["quantity"] == 100.0
    
    def test_exception_during_transaction_rollback(self, state_store, portfolio_manager, session_id, setup_session):
        """Test that exceptions during transaction cause rollback."""
        previous_equity = setup_session
        
        try:
            with portfolio_transaction(
                state_store=state_store,
                portfolio_manager=portfolio_manager,
                previous_equity=previous_equity,
                session_id=session_id
            ) as tx:
                # Stage some changes
                tx.stage_cash_delta(-1000.0, fees=5.0)
                
                # Simulate an exception (e.g., network error, validation error)
                raise ValueError("Simulated error during transaction")
                
        except ValueError:
            pass  # Expected
        
        # Verify no changes were applied due to rollback
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        assert latest_cash_equity["cash_balance"] == 100000.0  # Unchanged
    
    def test_context_manager_without_commit(self, state_store, portfolio_manager, session_id, setup_session):
        """Test that context manager rollback works when no commit is called."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage changes but don't commit
            tx.stage_cash_delta(-1000.0, fees=5.0)
            tx.stage_realized_pnl_delta(100.0)
            
            # Context manager should auto-rollback on exit
        
        # Verify no changes were applied
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        assert latest_cash_equity["cash_balance"] == 100000.0  # Unchanged
        assert latest_cash_equity["total_realized_pnl"] == 0.0  # Unchanged
    
    def test_lotbook_staging_and_commit(self, state_store, portfolio_manager, session_id, setup_session):
        """Test lotbook staging and commit functionality."""
        previous_equity = setup_session
        
        # Add some initial lots
        state_store.save_lot(
            symbol="BTC/USDT",
            lot_id="btc_lot_1",
            quantity=1.0,
            cost_price=50000.0,
            fee=25.0,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id
        )
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage lot additions
            tx.stage_lot_add("BTC/USDT", {
                "lot_id": "btc_lot_2",
                "quantity": 0.5,
                "cost_price": 51000.0,
                "fee": 12.5,
                "timestamp": datetime.now(timezone.utc)
            })
            
            # Stage lot updates
            tx.stage_lot_update("BTC/USDT", "btc_lot_1", {"quantity": 0.8})  # Partial consumption
            
            # Stage lot removals
            tx.stage_lot_remove("BTC/USDT", "btc_lot_1")
            
            # Commit
            mark_prices = {"BTC/USDT": 52000.0}
            success = tx.commit(mark_prices)
            
            assert success, "Lotbook transaction should commit successfully"
        
        # Verify lotbook changes
        lotbook = state_store.get_lotbook("BTC/USDT", session_id)
        
        # Should have one remaining lot (btc_lot_2)
        assert len(lotbook) == 1
        assert lotbook[0]["lot_id"] == "btc_lot_2"
        assert lotbook[0]["quantity"] == 0.5
    
    def test_multiple_symbols_staging(self, state_store, portfolio_manager, session_id, setup_session):
        """Test staging changes across multiple symbols."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage changes for multiple symbols
            symbols = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT"]
            
            for symbol in symbols:
                tx.stage_position_delta(symbol, 1.0, entry_price=100.0, current_price=105.0)
                tx.stage_lot_add(symbol, {
                    "lot_id": f"{symbol}_lot_1",
                    "quantity": 1.0,
                    "cost_price": 100.0,
                    "fee": 1.0,
                    "timestamp": datetime.now(timezone.utc)
                })
            
            # Commit with mark prices for all symbols
            mark_prices = {symbol: 105.0 for symbol in symbols}
            mark_prices["BTC/USDT"] = 51000.0  # BTC has different price scale
            
            success = tx.commit(mark_prices)
            assert success, "Multi-symbol transaction should commit successfully"
        
        # Verify all symbols have positions
        positions = state_store.get_positions(session_id)
        position_symbols = {pos["symbol"] for pos in positions}
        
        for symbol in symbols:
            assert symbol in position_symbols, f"Position for {symbol} should exist"
    
    def test_edge_case_zero_validation_epsilon(self, state_store, portfolio_manager, session_id, setup_session):
        """Test edge case with zero validation epsilon."""
        previous_equity = setup_session
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id,
            validation_epsilon=0.0  # Zero tolerance
        ) as tx:
            # Any change should fail validation
            tx.stage_cash_delta(-0.01, fees=0.0)  # Tiny change
            
            mark_prices = {"BTC/USDT": 50000.0}
            success = tx.commit(mark_prices)
            
            assert not success, "Transaction should fail with zero validation epsilon"
            assert tx.rolled_back, "Transaction should be rolled back"
    
    def test_validation_epsilon_scaling(self):
        """Test validation epsilon scales appropriately with portfolio size."""
        test_cases = [
            (1000.0, 1.0),      # Small portfolio
            (10000.0, 1.0),     # Medium portfolio  
            (100000.0, 10.0),   # Large portfolio
            (1000000.0, 100.0), # Very large portfolio
        ]
        
        for previous_equity, expected_epsilon in test_cases:
            transaction = PortfolioTransaction(
                state_store=Mock(),
                portfolio_manager=Mock(),
                previous_equity=previous_equity,
                session_id="test"
            )
            assert transaction.validation_epsilon == expected_epsilon, \
                f"Epsilon scaling failed for equity {previous_equity}"


class TestPortfolioTransactionIntegration:
    """Integration tests for portfolio transaction system."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        yield db_path
        
        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass
    
    @pytest.fixture
    def state_store(self, temp_db):
        """Create StateStore instance."""
        store = StateStore(temp_db)
        store.initialize()
        return store
    
    @pytest.fixture
    def portfolio_manager(self):
        """Create PortfolioManager instance."""
        return AdvancedPortfolioManager()
    
    def test_realistic_trading_scenario(self, state_store, portfolio_manager):
        """Test realistic trading scenario with multiple operations."""
        session_id = "realistic_test_session"
        
        # Setup initial portfolio
        initial_cash = 50000.0
        state_store.save_cash_equity(
            cash_balance=initial_cash,
            total_equity=initial_cash,
            total_fees=0.0,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            session_id=session_id,
            previous_equity=initial_cash
        )
        
        # Simulate a trading cycle with multiple operations
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=initial_cash,
            session_id=session_id
        ) as tx:
            # 1. Buy BTC position
            btc_quantity = 0.5
            btc_price = 45000.0
            btc_fees = 22.5
            
            tx.stage_cash_delta(-(btc_quantity * btc_price), fees=btc_fees)
            tx.stage_position_delta("BTC/USDT", btc_quantity, entry_price=btc_price, current_price=btc_price)
            tx.stage_lot_add("BTC/USDT", {
                "lot_id": "btc_buy_1",
                "quantity": btc_quantity,
                "cost_price": btc_price,
                "fee": btc_fees,
                "timestamp": datetime.now(timezone.utc)
            })
            
            # 2. Buy ETH position
            eth_quantity = 10.0
            eth_price = 2800.0
            eth_fees = 14.0
            
            tx.stage_cash_delta(-(eth_quantity * eth_price), fees=eth_fees)
            tx.stage_position_delta("ETH/USDT", eth_quantity, entry_price=eth_price, current_price=eth_price)
            tx.stage_lot_add("ETH/USDT", {
                "lot_id": "eth_buy_1",
                "quantity": eth_quantity,
                "cost_price": eth_price,
                "fee": eth_fees,
                "timestamp": datetime.now(timezone.utc)
            })
            
            # 3. Partial BTC sell with realized P&L
            btc_sell_quantity = 0.1
            btc_sell_price = 46000.0
            btc_sell_fees = 4.6
            btc_realized_pnl = (btc_sell_price - btc_price) * btc_sell_quantity - btc_sell_fees
            
            tx.stage_cash_delta(btc_sell_quantity * btc_sell_price, fees=btc_sell_fees)
            tx.stage_position_delta("BTC/USDT", -btc_sell_quantity)
            tx.stage_realized_pnl_delta(btc_realized_pnl)
            
            # Commit with current mark prices
            mark_prices = {
                "BTC/USDT": 46000.0,
                "ETH/USDT": 2850.0
            }
            
            success = tx.commit(mark_prices)
            assert success, "Realistic trading scenario should commit successfully"
        
        # Verify final state
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        positions = state_store.get_positions(session_id)
        
        # Calculate expected cash
        expected_cash = (
            initial_cash
            - (btc_quantity * btc_price) - btc_fees
            - (eth_quantity * eth_price) - eth_fees
            + (btc_sell_quantity * btc_sell_price) - btc_sell_fees
        )
        
        assert abs(latest_cash_equity["cash_balance"] - expected_cash) < 0.01
        assert latest_cash_equity["total_realized_pnl"] == btc_realized_pnl
        
        # Verify positions
        btc_pos = next((p for p in positions if p["symbol"] == "BTC/USDT"), None)
        eth_pos = next((p for p in positions if p["symbol"] == "ETH/USDT"), None)
        
        assert btc_pos is not None
        assert btc_pos["quantity"] == 0.4  # 0.5 - 0.1
        
        assert eth_pos is not None
        assert eth_pos["quantity"] == 10.0


if __name__ == "__main__":
    pytest.main([__file__])

"""
Example demonstrating PortfolioTransaction usage.

This example shows how to use the transactional portfolio system
to handle large interim swings and validate only the final staged state.
"""

import tempfile
import os
from datetime import datetime, timezone

from src.crypto_mvp.risk.portfolio_transaction import portfolio_transaction
from src.crypto_mvp.risk.portfolio import AdvancedPortfolioManager
from src.crypto_mvp.state.store import StateStore


def main():
    """Demonstrate portfolio transaction usage."""
    
    # Setup
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        # Initialize components
        state_store = StateStore(db_path)
        state_store.initialize()
        
        portfolio_manager = AdvancedPortfolioManager()
        portfolio_manager.initialize()
        
        session_id = "example_session"
        previous_equity = 100000.0  # $100k starting capital
        
        # Create initial session
        state_store.save_cash_equity(
            cash_balance=previous_equity,
            total_equity=previous_equity,
            total_fees=0.0,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            session_id=session_id,
            previous_equity=previous_equity
        )
        
        print("=== Portfolio Transaction Example ===")
        print(f"Starting equity: ${previous_equity:,.2f}")
        
        # Example 1: Simple successful transaction
        print("\n--- Example 1: Simple Successful Transaction ---")
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=previous_equity,
            session_id=session_id
        ) as tx:
            # Stage small changes within validation epsilon
            tx.stage_cash_delta(-1000.0, fees=5.0)  # Small buy order
            tx.stage_position_delta("BTC/USDT", 0.02, entry_price=50000.0, current_price=51000.0)
            tx.stage_realized_pnl_delta(50.0)  # Small profit
            
            # Commit with current mark prices
            mark_prices = {"BTC/USDT": 51000.0}
            success = tx.commit(mark_prices)
            
            print(f"Transaction success: {success}")
            if success:
                print("✅ Transaction committed successfully")
            else:
                print("❌ Transaction failed validation")
        
        # Example 2: Large interim swings scenario
        print("\n--- Example 2: Large Interim Swings Scenario ---")
        
        # Get current state after first transaction
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        current_equity = latest_cash_equity["total_equity"]
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=current_equity,
            session_id=session_id
        ) as tx:
            # Stage massive changes that would fail if validated immediately
            print("Staging large interim swings...")
            
            # Massive buy orders
            tx.stage_cash_delta(-50000.0, fees=250.0)  # 50% of portfolio
            tx.stage_cash_delta(-20000.0, fees=100.0)  # Additional 20%
            
            # Large position changes
            tx.stage_position_delta("BTC/USDT", 1.0, entry_price=50000.0)  # $50k position
            tx.stage_position_delta("ETH/USDT", 20.0, entry_price=3000.0)  # $60k position
            
            # Large realized P&L swing
            tx.stage_realized_pnl_delta(25000.0)  # Massive profit
            
            print("Interim state would fail validation, but we don't validate until commit...")
            
            # Apply final mark prices that make the transaction valid
            # Assume prices moved significantly in our favor
            final_mark_prices = {
                "BTC/USDT": 60000.0,  # BTC up 20%
                "ETH/USDT": 3500.0    # ETH up 16.7%
            }
            
            print("Committing with final mark prices...")
            success = tx.commit(final_mark_prices)
            
            print(f"Transaction success: {success}")
            if success:
                print("✅ Large swings transaction committed successfully")
                print("   Final staged state was valid despite interim swings")
            else:
                print("❌ Transaction failed validation")
        
        # Example 3: Validation failure scenario
        print("\n--- Example 3: Validation Failure Scenario ---")
        
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        current_equity = latest_cash_equity["total_equity"]
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=current_equity,
            session_id=session_id
        ) as tx:
            # Stage changes that exceed validation epsilon
            # With current_equity, epsilon = max(1.0, 0.0001 * current_equity)
            epsilon = max(1.0, 0.0001 * current_equity)
            print(f"Validation epsilon: ${epsilon:.2f}")
            
            # Stage changes that exceed epsilon
            tx.stage_cash_delta(-epsilon * 2, fees=epsilon * 0.1)
            tx.stage_realized_pnl_delta(epsilon * 2)
            
            # Commit with mark prices
            mark_prices = {"BTC/USDT": 60000.0, "ETH/USDT": 3500.0}
            success = tx.commit(mark_prices)
            
            print(f"Transaction success: {success}")
            if success:
                print("✅ Transaction committed successfully")
            else:
                print("❌ Transaction failed validation (expected)")
                print("   Changes exceeded validation epsilon")
        
        # Example 4: Exception handling and rollback
        print("\n--- Example 4: Exception Handling and Rollback ---")
        
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        current_equity = latest_cash_equity["total_equity"]
        
        try:
            with portfolio_transaction(
                state_store=state_store,
                portfolio_manager=portfolio_manager,
                previous_equity=current_equity,
                session_id=session_id
            ) as tx:
                # Stage some changes
                tx.stage_cash_delta(-5000.0, fees=25.0)
                tx.stage_realized_pnl_delta(100.0)
                
                print("Simulating exception during transaction...")
                # Simulate an exception (e.g., network error, validation error)
                raise ValueError("Simulated error during transaction")
                
        except ValueError as e:
            print(f"Exception caught: {e}")
            print("✅ Transaction was automatically rolled back")
        
        # Verify no changes were applied due to rollback
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        print(f"Equity after rollback: ${latest_cash_equity['total_equity']:,.2f}")
        
        # Example 5: Multiple symbol staging
        print("\n--- Example 5: Multiple Symbol Staging ---")
        
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        current_equity = latest_cash_equity["total_equity"]
        
        with portfolio_transaction(
            state_store=state_store,
            portfolio_manager=portfolio_manager,
            previous_equity=current_equity,
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
            mark_prices["BTC/USDT"] = 60000.0  # BTC has different price scale
            mark_prices["ETH/USDT"] = 3500.0   # ETH has different price scale
            
            success = tx.commit(mark_prices)
            
            print(f"Multi-symbol transaction success: {success}")
            if success:
                print("✅ Multi-symbol transaction committed successfully")
                
                # Verify positions were created
                positions = state_store.get_positions(session_id)
                print(f"Positions created: {len(positions)}")
                for pos in positions:
                    print(f"  {pos['symbol']}: {pos['quantity']} @ ${pos['entry_price']:.2f}")
        
        # Final state summary
        print("\n=== Final State Summary ===")
        latest_cash_equity = state_store.get_latest_cash_equity(session_id)
        positions = state_store.get_positions(session_id)
        
        print(f"Final equity: ${latest_cash_equity['total_equity']:,.2f}")
        print(f"Cash balance: ${latest_cash_equity['cash_balance']:,.2f}")
        print(f"Total realized P&L: ${latest_cash_equity['total_realized_pnl']:,.2f}")
        print(f"Total fees: ${latest_cash_equity['total_fees']:,.2f}")
        print(f"Active positions: {len(positions)}")
        
        print("\n✅ Portfolio transaction examples completed successfully!")
        
    finally:
        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()

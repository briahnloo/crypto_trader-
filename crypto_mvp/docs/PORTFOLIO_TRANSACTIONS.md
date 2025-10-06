# Portfolio Transaction System

## Overview

The Portfolio Transaction System provides transactional portfolio mutations with staged state validation. This system ensures that portfolio changes are validated only against the final staged state, preventing premature validation errors during large interim swings.

## Key Features

### 1. Transactional Context Manager
- **Staging**: All portfolio changes (cash, positions, lotbook) are staged in temporary state
- **Validation**: Only the final staged state is validated against previous equity
- **Atomic Operations**: Either all changes commit or all are rolled back
- **Exception Safety**: Automatic rollback on exceptions

### 2. Validation Epsilon
- **Dynamic Calculation**: `validation_epsilon = max(1.00, 0.0001 * previous_equity)`
- **Intra-cycle Tolerance**: Allows reasonable portfolio fluctuations within trading cycles
- **Configurable**: Custom epsilon can be provided for specific use cases

### 3. Staging Mechanisms
- **Cash Changes**: Stage cash deltas and fees separately
- **Position Changes**: Stage quantity deltas with entry/current prices
- **Lot Book Changes**: Stage lot additions, removals, and updates
- **Realized P&L**: Stage realized P&L changes

## Usage

### Basic Usage

```python
from src.crypto_mvp.risk.portfolio_transaction import portfolio_transaction

with portfolio_transaction(
    state_store=state_store,
    portfolio_manager=portfolio_manager,
    previous_equity=previous_equity,
    session_id=session_id
) as tx:
    # Stage changes
    tx.stage_cash_delta(-1000.0, fees=5.0)
    tx.stage_position_delta("BTC/USDT", 0.02, entry_price=50000.0)
    tx.stage_realized_pnl_delta(50.0)
    
    # Commit with final mark prices
    mark_prices = {"BTC/USDT": 51000.0}
    success = tx.commit(mark_prices)
```

### Large Interim Swings Scenario

```python
with portfolio_transaction(
    state_store=state_store,
    portfolio_manager=portfolio_manager,
    previous_equity=previous_equity,
    session_id=session_id
) as tx:
    # Stage massive changes (would fail if validated immediately)
    tx.stage_cash_delta(-50000.0, fees=250.0)
    tx.stage_position_delta("BTC/USDT", 1.0, entry_price=50000.0)
    tx.stage_realized_pnl_delta(25000.0)
    
    # Commit with final mark prices that make transaction valid
    final_mark_prices = {"BTC/USDT": 60000.0}  # 20% price increase
    success = tx.commit(final_mark_prices)
```

## Implementation Details

### Core Components

#### PortfolioTransaction Class
- **Context Manager**: Implements `__enter__` and `__exit__` for automatic cleanup
- **Staging**: Maintains staged changes in memory until commit
- **Validation**: Computes staged total and validates against epsilon
- **Commit/Rollback**: Atomic operations for state persistence

#### Staging Data Structures
- **StagedCash**: Cash deltas and fees
- **StagedPosition**: Position quantity deltas and pricing
- **StagedLotBook**: Lot additions, removals, updates
- **StagedRealizedPnl**: Realized P&L changes

### Validation Logic

```python
def _validate_staged_state(self, mark_prices: Dict[str, float]) -> Tuple[bool, float]:
    """Validate final staged state against previous equity."""
    staged_total = self._compute_staged_total(mark_prices)
    delta = abs(staged_total - self.previous_equity)
    is_valid = delta <= self.validation_epsilon
    return is_valid, staged_total
```

### Integration with Trading System

The trading system now uses transactional portfolio updates:

```python
def _commit_portfolio_transaction(self, mark_prices: dict[str, float]) -> bool:
    """Commit portfolio changes using transactional approach."""
    with portfolio_transaction(
        state_store=self.state_store,
        portfolio_manager=self.portfolio_manager,
        previous_equity=self._previous_equity,
        session_id=self.current_session_id
    ) as tx:
        success = tx.commit(mark_prices)
        if success:
            # Update _previous_equity for next cycle
            latest_cash_equity = self.state_store.get_latest_cash_equity(self.current_session_id)
            if latest_cash_equity:
                self._previous_equity = latest_cash_equity["total_equity"]
        return success
```

## Logging

### Commit Logs
```
PORTFOLIO_COMMIT: cash=$105000.00, positions=$50000.00, total=$155000.00 (Δ=$55000.00, ε=$10.00)
```

### Discard Logs
```
PORTFOLIO_DISCARD: reason=validation_failed Δ=$15000.00, ε=$10.00
```

## Testing

### Test Scenarios

1. **Validation Epsilon Calculation**: Tests epsilon scaling with portfolio size
2. **Successful Commit**: Tests normal transaction flow
3. **Validation Failure**: Tests rollback on validation failure
4. **Large Interim Swings**: Tests handling of massive interim changes
5. **Exception Handling**: Tests automatic rollback on exceptions
6. **Multi-symbol Staging**: Tests complex multi-asset scenarios

### Running Tests

```bash
cd crypto_mvp
python -m pytest tests/test_portfolio_transaction.py -v
```

### Example Usage

```bash
cd crypto_mvp
python examples/portfolio_transaction_example.py
```

## Benefits

### 1. Prevents Premature Validation Errors
- Large interim swings during staging don't cause validation failures
- Only final staged state is validated against previous equity

### 2. Atomic Operations
- Either all changes commit or all are rolled back
- Prevents partial state corruption

### 3. Exception Safety
- Automatic rollback on exceptions
- Consistent state even during errors

### 4. Flexible Validation
- Dynamic epsilon based on portfolio size
- Configurable validation tolerance

### 5. Comprehensive Logging
- Detailed commit/discard logs
- Clear validation failure reasons

## Configuration

### Validation Epsilon
- **Default**: `max(1.00, 0.0001 * previous_equity)`
- **Custom**: Can be overridden per transaction
- **Scaling**: Automatically scales with portfolio size

### Session Management
- **Session ID**: Required for all transactions
- **State Isolation**: Transactions are isolated per session
- **Persistence**: All changes persist to StateStore

## Future Enhancements

1. **Nested Transactions**: Support for transaction nesting
2. **Optimistic Locking**: Prevent concurrent modification conflicts
3. **Batch Operations**: Optimize multiple small transactions
4. **Metrics**: Transaction performance and validation statistics
5. **Recovery**: Automatic recovery from failed transactions

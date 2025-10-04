# Edge After Costs Guard Implementation

## Overview

This implementation adds a pre-trade guard that prevents money-losing entries by calculating the expected edge after accounting for spread and fees. The guard rejects trades where the edge after costs is below the minimum threshold.

## Formula

```
edge_after_costs_bps = expected_move_bps - (spread_bps + 2*fee_bps)
```

Where:
- `expected_move_bps`: Expected price movement in basis points
- `spread_bps`: Bid-ask spread in basis points
- `fee_bps`: Trading fee in basis points (multiplied by 2 for entry + exit)
- `edge_after_costs_bps`: Net edge after all costs

## Configuration

Added to `config/profit_optimized.yaml`:

```yaml
execution:
  # Edge after costs guard
  require_edge_after_costs: true  # Enable edge after costs guard
  min_edge_after_costs_bps: 10  # Minimum 10 bps edge after costs
```

## Files Modified

### 1. Configuration
- `config/profit_optimized.yaml`: Added edge guard configuration options

### 2. Core Implementation
- `src/crypto_mvp/execution/edge_guard.py`: New module implementing the edge guard logic
- `execution/engine.py`: Integrated edge guard into execution pipeline
- `app.py`: Added ticker data callback and updated execution engine initialization

### 3. Tests
- `tests/test_execution_flow.py`: Updated to handle new execution engine parameters

## Key Features

### EdgeAfterCostsGuard Class
- **Configuration-driven**: Can be enabled/disabled via config
- **Flexible fee handling**: Supports both maker and taker fees
- **Comprehensive logging**: Logs all components of the calculation
- **Robust error handling**: Gracefully handles missing data

### Integration Points
- **Pre-trade check**: Runs before order execution
- **Ticker data integration**: Uses real bid/ask spread data
- **Signal-based expected moves**: Estimates expected moves from trading signals
- **Fallback handling**: Continues trading if edge guard fails

## Usage Example

```python
# Initialize guard
config = {
    "require_edge_after_costs": True,
    "min_edge_after_costs_bps": 10,
    "maker_fee_bps": 10,
    "taker_fee_bps": 20
}
guard = EdgeAfterCostsGuard(config)

# Check trade
ticker_data = {"bid": 49995.0, "ask": 50005.0}
signal = {"expected_move": 0.006, "confidence": 0.8}
should_skip, reason, details = guard.should_skip_trade("BTC/USDT", ticker_data, signal)
```

## Logging Output

The guard provides detailed logging:

```
EDGE_CHECK: BTC/USDT PASSED - expected_move=60.0bps, spread=2.0bps, fees=20bps, edge_after_costs=18.0bps (threshold=10bps)
```

Or for rejected trades:

```
EDGE_CHECK: BTC/USDT REJECTED - expected_move=10.0bps, spread=20.0bps, fees=20bps, edge_after_costs=-30.0bps (threshold=10bps)
```

## Benefits

1. **Prevents money-losing trades**: Rejects trades where costs exceed expected profit
2. **Configurable thresholds**: Can be adjusted based on market conditions
3. **Real-time spread awareness**: Uses actual bid/ask spreads, not estimates
4. **Comprehensive cost accounting**: Includes both spread and fees
5. **Non-blocking**: If guard fails, trading continues (fail-safe)

## Testing

The implementation includes comprehensive test scenarios:
- Good edge scenarios (should pass)
- Poor edge scenarios (should fail)
- Missing data scenarios (should fail gracefully)
- Disabled guard scenarios (should pass)

## Future Enhancements

1. **Dynamic thresholds**: Adjust minimum edge based on market volatility
2. **Maker vs taker logic**: Different logic for maker vs taker orders
3. **Historical spread analysis**: Use historical data to estimate spreads
4. **Multi-timeframe expected moves**: More sophisticated expected move estimation
5. **Risk-adjusted thresholds**: Adjust thresholds based on position size and risk

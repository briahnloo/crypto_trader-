# Market Data Filter Implementation

## Overview

This implementation adds a market data freshness and spread filter that enforces strict quality requirements before allowing any trading decisions. The filter ensures trades only execute on fresh, tight spreads, preventing losses from stale data or unfavorable market conditions.

## Key Features

### Spread Filtering
- **Maximum spread enforcement**: Configurable maximum spread in basis points
- **Real-time calculation**: Calculates spread as `(ask - bid) / mid * 10000` bps
- **Automatic rejection**: Skips trades when spread exceeds threshold
- **Detailed logging**: Logs spread values and rejection reasons

### Quote Freshness Validation
- **Timestamp validation**: Requires valid timestamp in ticker data
- **Age calculation**: Calculates quote age in milliseconds
- **Maximum age enforcement**: Configurable maximum quote age (default 200ms)
- **Multiple timestamp formats**: Supports Unix timestamps, datetime objects, and ISO strings

### Data Structure Validation
- **Required fields**: Validates presence of bid, ask, and timestamp
- **Value validation**: Ensures bid/ask are positive numbers
- **Logical validation**: Ensures ask > bid
- **Type checking**: Validates data types for all fields

## Configuration

Added to `config/profit_optimized.yaml`:

```yaml
# Market Data Configuration
market_data:
  max_spread_bps: 3              # Maximum spread in basis points (0.03%)
  max_quote_age_ms: 200          # Maximum quote age in milliseconds
```

## Files Modified

### 1. Configuration
- `config/profit_optimized.yaml`: Added market data configuration options

### 2. Core Implementation
- `src/crypto_mvp/execution/market_data_filter.py`: New market data filter module
- `execution/engine.py`: Integrated market data filter into execution pipeline
- `app.py`: Updated ticker data to include timestamps and simulate market conditions

### 3. Architecture Integration
- Market data filter initialized in execution engine
- Filter applied before any trading decisions
- Comprehensive error handling and logging
- Integration with existing edge guard and post-only router

## Filter Logic Flow

### 1. Data Availability Check
```
Ticker Data Available? → No → REJECT (no_ticker_data)
                      → Yes → Continue
```

### 2. Structure Validation
```
Required Fields Present? → No → REJECT (invalid_ticker_structure)
                        → Yes → Continue
```

### 3. Value Validation
```
Valid Bid/Ask Values? → No → REJECT (invalid_bid_ask_values)
                     → Yes → Continue
```

### 4. Logical Validation
```
Ask > Bid? → No → REJECT (ask_not_greater_than_bid)
          → Yes → Continue
```

### 5. Quote Age Check
```
Quote Age < Max Age? → No → REJECT (stale_quote)
                    → Yes → Continue
```

### 6. Spread Check
```
Spread < Max Spread? → No → REJECT (spread_too_wide)
                    → Yes → PASS
```

## Spread Calculation

### Formula
```
Mid Price = (Bid + Ask) / 2
Spread (bps) = ((Ask - Bid) / Mid Price) * 10000
```

### Example
```
Bid: $49,995
Ask: $50,005
Mid Price: $50,000
Spread: ((50,005 - 49,995) / 50,000) * 10000 = 2.0 bps
```

## Quote Age Calculation

### Supported Timestamp Formats
1. **Unix timestamp (seconds)**: `1759547677.986`
2. **Unix timestamp (milliseconds)**: `1759547677986`
3. **Datetime object**: `datetime(2025, 10, 3, 14, 13, 37)`
4. **ISO string**: `"2025-10-03T14:13:37.986Z"`

### Age Calculation
```
Current Time - Quote Time = Age (seconds)
Age (seconds) * 1000 = Age (milliseconds)
```

## Logging Output

### Successful Validation
```
MARKET_DATA_OK: BTC/USDT spread=2.00bps age=50ms
```

### Rejection Reasons
```
REJECTED: BTC/USDT (reason=market_data_spread_too_wide, spread=20.00bps, max=3bps)
REJECTED: BTC/USDT (reason=market_data_stale_quote, age=500ms, max=200ms)
REJECTED: BTC/USDT (reason=market_data_no_ticker_data)
REJECTED: BTC/USDT (reason=market_data_invalid_ticker_structure, missing=['timestamp'])
REJECTED: BTC/USDT (reason=market_data_invalid_bid_ask_values, bid=invalid, ask=50005.0)
REJECTED: BTC/USDT (reason=market_data_ask_not_greater_than_bid, bid=50005.0, ask=49995.0)
```

## Integration Points

### Execution Engine Integration
- **Pre-trade filtering**: Applied before any trading decisions
- **Step 1.6**: Market data filter check in execution pipeline
- **Error handling**: Graceful failure with detailed logging
- **Performance**: Minimal overhead with efficient validation

### Ticker Data Requirements
- **Timestamp inclusion**: All ticker data must include timestamps
- **Real-time simulation**: Mock data simulates various market conditions
- **Spread simulation**: Different spread scenarios for testing
- **Age simulation**: Fresh and stale data scenarios

## Market Conditions Simulation

### Normal Conditions (85% of time)
- **BTC/USDT**: 2 bps spread, 50ms age
- **ETH/USDT**: 13 bps spread, 50ms age
- **BNB/USDT**: 33 bps spread, 50ms age
- **ADA/USDT**: 40 bps spread, 50ms age
- **SOL/USDT**: 40 bps spread, 50ms age

### Wide Spread Conditions (15% of time)
- **BTC/USDT**: 10 bps spread (rejected)
- **ETH/USDT**: 50 bps spread (rejected)
- **BNB/USDT**: 100 bps spread (rejected)
- **ADA/USDT**: 100 bps spread (rejected)
- **SOL/USDT**: 100 bps spread (rejected)

### Stale Data Conditions (10% of time)
- **All symbols**: 500ms age (rejected)

## Benefits

### 1. Risk Mitigation
- **Prevents stale data trading**: Avoids trading on outdated information
- **Controls spread costs**: Ensures favorable execution costs
- **Data quality assurance**: Validates all market data before use

### 2. Performance Optimization
- **Early rejection**: Fails fast on poor market conditions
- **Reduced slippage**: Only trades on tight spreads
- **Better execution**: Ensures fresh, accurate pricing

### 3. Operational Safety
- **Comprehensive validation**: Multiple layers of data validation
- **Detailed logging**: Full audit trail of rejections
- **Graceful degradation**: Continues operation if filter fails

## Testing

The implementation includes comprehensive test scenarios:
- Valid ticker data (should pass)
- Wide spread conditions (should fail)
- Stale quote data (should fail)
- Missing ticker data (should fail)
- Invalid data structure (should fail)
- Invalid bid/ask values (should fail)
- Logical validation (ask > bid)
- Multiple timestamp formats
- Market data summary generation
- Ticker data validation

## Example Usage

```python
# Initialize market data filter
config = {
    "market_data": {
        "max_spread_bps": 3,
        "max_quote_age_ms": 200
    }
}
filter_obj = MarketDataFilter(config)

# Check if trade should be skipped
should_skip, reason, details = filter_obj.should_skip_trade(
    symbol="BTC/USDT",
    ticker_data={
        "bid": 49995.0,
        "ask": 50005.0,
        "timestamp": time.time() - 0.05
    }
)

# Get market data summary
summary = filter_obj.get_market_data_summary("BTC/USDT", ticker_data)
```

## Configuration Options

### max_spread_bps
- **Default**: 3 basis points (0.03%)
- **Purpose**: Maximum allowed spread for trading
- **Impact**: Lower values = stricter filtering, higher values = more permissive

### max_quote_age_ms
- **Default**: 200 milliseconds
- **Purpose**: Maximum age of market data
- **Impact**: Lower values = stricter filtering, higher values = more permissive

## Future Enhancements

1. **Dynamic thresholds**: Adjust limits based on market volatility
2. **Symbol-specific settings**: Different limits for different trading pairs
3. **Time-based filtering**: Different limits for different market hours
4. **Volume-based filtering**: Consider trading volume in decisions
5. **Advanced timestamp parsing**: Support for more timestamp formats
6. **Performance metrics**: Track filter effectiveness and market conditions

## Compliance

This implementation ensures:
- **Data quality**: Only trades on validated, fresh market data
- **Risk control**: Prevents trading on unfavorable spreads
- **Audit trail**: Comprehensive logging of all filtering decisions
- **Fail-safe operation**: Continues trading if filter fails
- **Performance**: Minimal overhead with efficient validation

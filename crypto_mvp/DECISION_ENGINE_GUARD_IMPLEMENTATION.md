# Decision Engine Guard Implementation

## Overview

This implementation adds a decision engine guard that requires top-of-book mid prices from the same venue as execution, with strict quote age and bid/ask validation requirements. The guard ensures decision-making is based on fresh, venue-consistent market data.

## Key Features

### L2 Mid Price Validation
- **Top-of-book requirement**: Ensures decisions use top-of-book mid prices
- **Venue consistency**: Requires same venue for ticker data and execution
- **Quote age enforcement**: Maximum 200ms quote age (configurable)
- **Bid/ask validation**: Ensures valid best bid/ask availability

### Stale Tick Detection
- **Age validation**: Rejects quotes older than configured threshold
- **Stale tick logging**: Logs `stale_tick=true` when guard fails
- **Timestamp parsing**: Supports multiple timestamp formats
- **Comprehensive validation**: Multiple layers of data validation

## Configuration

Added to `config/profit_optimized.yaml`:

```yaml
# Market Data Configuration
market_data:
  max_spread_bps: 3              # Maximum spread in basis points (0.03%)
  max_quote_age_ms: 200          # Maximum quote age in milliseconds
  require_l2_mid: true           # Require top-of-book mid from same venue as execution
```

## Files Modified

### 1. Configuration
- `config/profit_optimized.yaml`: Added `require_l2_mid` configuration option

### 2. Core Implementation
- `src/crypto_mvp/execution/decision_engine_guard.py`: New decision engine guard module
- `execution/engine.py`: Integrated decision engine guard into execution pipeline
- `app.py`: Updated ticker data to include venue information

### 3. Architecture Integration
- Decision engine guard initialized in execution engine
- Guard applied as Step 1.7 in execution pipeline
- Comprehensive error handling and logging
- Integration with existing execution flow

## Guard Logic Flow

### 1. L2 Mid Requirement Check
```
require_l2_mid enabled? → No → PASS (l2_mid_not_required)
                        → Yes → Continue
```

### 2. Ticker Data Availability
```
Ticker Data Available? → No → REJECT (no_ticker_data, stale_tick=true)
                      → Yes → Continue
```

### 3. Structure Validation
```
Required Fields Present? → No → REJECT (invalid_ticker_structure, stale_tick=true)
                        → Yes → Continue
```

### 4. Value Validation
```
Valid Bid/Ask Values? → No → REJECT (invalid_bid_ask_values, stale_tick=true)
                     → Yes → Continue
```

### 5. Logical Validation
```
Ask > Bid? → No → REJECT (ask_not_greater_than_bid, stale_tick=true)
          → Yes → Continue
```

### 6. Venue Consistency Check
```
Ticker Venue == Execution Venue? → No → REJECT (venue_mismatch, stale_tick=true)
                                → Yes → Continue
```

### 7. Quote Age Check
```
Quote Age < Max Age? → No → REJECT (stale_quote, stale_tick=true)
                    → Yes → PASS (valid)
```

## L2 Mid Price Calculation

### Formula
```
L2 Mid = (Best Bid + Best Ask) / 2
```

### Example
```
Best Bid: $49,995
Best Ask: $50,005
L2 Mid: ($49,995 + $50,005) / 2 = $50,000
```

## Required Ticker Data Structure

### Fields
- **bid**: Best bid price (numeric, positive)
- **ask**: Best ask price (numeric, positive, > bid)
- **timestamp**: Quote timestamp (Unix timestamp, datetime, or ISO string)
- **venue**: Data source venue (string, must match execution venue)

### Example
```python
ticker_data = {
    "bid": 49995.0,
    "ask": 50005.0,
    "timestamp": 1759551119.231894,
    "venue": "binance"
}
```

## Logging Output

### Successful Validation
```
DECISION_DATA_OK: BTC/USDT l2_mid=$50000.0000 venue=binance age=50ms
```

### Rejection Reasons
```
REJECTED: BTC/USDT BUY (reason=decision_guard_stale_quote, stale_tick=true)
REJECTED: BTC/USDT BUY (reason=decision_guard_venue_mismatch, stale_tick=true)
REJECTED: BTC/USDT BUY (reason=decision_guard_no_ticker_data, stale_tick=true)
REJECTED: BTC/USDT BUY (reason=decision_guard_invalid_ticker_structure, stale_tick=true)
REJECTED: BTC/USDT BUY (reason=decision_guard_invalid_bid_ask_values, stale_tick=true)
REJECTED: BTC/USDT BUY (reason=decision_guard_ask_not_greater_than_bid, stale_tick=true)
```

## Integration Points

### Execution Engine Integration
- **Pre-decision filtering**: Applied before any trading decisions
- **Step 1.7**: Decision engine guard check in execution pipeline
- **Error handling**: Graceful failure with detailed logging
- **Performance**: Minimal overhead with efficient validation

### Venue Management
- **Venue consistency**: Ensures ticker data and execution use same venue
- **Default venue**: Uses "binance" as default execution venue
- **Configurable**: Easy to modify execution venue
- **Validation**: Comprehensive venue matching validation

## Benefits

### 1. Data Quality Assurance
- **Fresh data**: Ensures decisions based on recent market data
- **Venue consistency**: Prevents cross-venue data inconsistencies
- **L2 accuracy**: Uses top-of-book prices for precise mid calculation
- **Stale detection**: Identifies and rejects stale market data

### 2. Risk Mitigation
- **Execution accuracy**: Ensures decisions match execution venue
- **Data integrity**: Validates all required fields and values
- **Age control**: Prevents trading on outdated information
- **Venue alignment**: Eliminates venue-related execution risks

### 3. Operational Safety
- **Comprehensive validation**: Multiple layers of data validation
- **Detailed logging**: Full audit trail of guard decisions
- **Fail-safe design**: Continues trading if guard fails
- **Configurable**: Easy to enable/disable and adjust parameters

## Testing

The implementation includes comprehensive test scenarios:
- Valid decision data (should pass)
- Stale quote (should fail)
- Venue mismatch (should fail)
- Missing ticker data (should fail)
- Invalid ticker structure (should fail)
- Invalid bid/ask values (should fail)
- Ask not greater than bid (should fail)
- Decision summary generation
- Ticker data validation
- L2 mid disabled behavior
- Timestamp parsing with different formats
- Venue consistency validation

## Example Usage

```python
# Initialize decision engine guard
config = {
    "market_data": {
        "require_l2_mid": True,
        "max_quote_age_ms": 200
    }
}
guard = DecisionEngineGuard(config)

# Validate decision data
is_valid, reason, details = guard.validate_decision_data(
    symbol="BTC/USDT",
    ticker_data={
        "bid": 49995.0,
        "ask": 50005.0,
        "timestamp": time.time() - 0.05,
        "venue": "binance"
    },
    execution_venue="binance"
)

# Get decision summary
summary = guard.get_decision_summary(
    symbol="BTC/USDT",
    ticker_data=ticker_data,
    execution_venue="binance"
)
```

## Configuration Options

### require_l2_mid
- **Default**: true
- **Purpose**: Enable/disable L2 mid price requirement
- **Impact**: Controls whether decision engine guard is active

### max_quote_age_ms
- **Default**: 200 milliseconds
- **Purpose**: Maximum age of market data for decisions
- **Impact**: Lower values = stricter filtering, higher values = more permissive

## Venue Management

### Supported Venues
- **binance**: Binance exchange
- **coinbase**: Coinbase Pro
- **kraken**: Kraken exchange
- **custom**: Any custom venue identifier

### Venue Consistency
- **Ticker venue**: Venue where market data originates
- **Execution venue**: Venue where trades will be executed
- **Requirement**: Both must match for valid decisions
- **Validation**: Strict venue matching enforced

## Timestamp Support

### Supported Formats
1. **Unix timestamp (seconds)**: `1759551119.231894`
2. **Unix timestamp (milliseconds)**: `1759551119231.894`
3. **ISO string**: `"2025-10-03T21:11:59.231894Z"`
4. **Datetime object**: `datetime(2025, 10, 3, 21, 11, 59)`

### Age Calculation
```
Current Time - Quote Time = Age (seconds)
Age (seconds) * 1000 = Age (milliseconds)
```

## Future Enhancements

1. **Multi-venue support**: Support for multiple execution venues
2. **Dynamic venue selection**: Automatic venue selection based on conditions
3. **Advanced timestamp parsing**: Support for more timestamp formats
4. **Venue-specific settings**: Different requirements for different venues
5. **Real-time venue monitoring**: Monitor venue health and availability
6. **Cross-venue arbitrage**: Support for cross-venue trading strategies

## Compliance

This implementation ensures:
- **Data freshness**: Only decisions based on recent market data
- **Venue consistency**: Ticker data and execution from same venue
- **L2 accuracy**: Top-of-book mid prices for precise decisions
- **Comprehensive validation**: Multiple layers of data validation
- **Audit trail**: Full logging of all guard decisions
- **Fail-safe operation**: Continues trading if guard fails

# Order Precision and Quantization System

## Overview

The Order Precision and Quantization System prevents PRECISION_FAIL errors by enforcing exchange-specific precision requirements and automatically quantizing orders to meet symbol rules.

## Key Features

### 1. Symbol Rules Enforcement
- **Dynamic Rules Retrieval**: Fetches symbol-specific trading rules from exchange APIs
- **Caching**: Caches rules per symbol to minimize API calls
- **Fallback Rules**: Provides default rules when API is unavailable

### 2. Order Quantization
- **Price Rounding**: Rounds prices to exchange-specific tick sizes
- **Quantity Quantization**: Rounds quantities to exchange-specific step sizes
- **Conservative Approach**: Uses round-down for quantities to prevent over-allocation

### 3. Auto-Bump Logic
- **Minimum Quantity**: Automatically bumps to minimum quantity when required
- **Minimum Notional**: Automatically bumps to minimum notional when required
- **Retry Logic**: One retry with adjusted values before hard failure

### 4. Validation and Error Handling
- **Precision Validation**: Validates orders against symbol rules
- **Clear Error Messages**: Provides specific reasons for order failures
- **Graceful Degradation**: Falls back to default rules when needed

## Implementation

### Core Components

#### CoinbaseConnector Symbol Rules
```python
def get_symbol_rules(self, symbol: str) -> Dict[str, Any]:
    """Get symbol trading rules for order precision requirements."""
    # Check cache first
    if coinbase_symbol in self._symbol_rules_cache:
        return self._symbol_rules_cache[coinbase_symbol]
    
    # Fetch from API or use defaults
    rules = self._get_symbol_rules_from_api(coinbase_symbol)
    self._symbol_rules_cache[coinbase_symbol] = rules
    return rules
```

#### OrderBuilder Quantization
```python
def build_order(self, symbol: str, raw_price: float, target_notional: float, 
                symbol_rules: Dict[str, Any], max_retries: int = 1):
    """Build a quantized order with precision compliance."""
    # Step 1: Round price to tick size
    quantized_price = self._round_to_tick(raw_price, price_tick)
    
    # Step 2: Calculate raw quantity from target notional
    qty_raw = target_notional / quantized_price
    
    # Step 3: Round quantity down to step size
    quantized_qty = self._round_down_to_step(qty_raw, qty_step)
    
    # Step 4: Check minimum constraints and auto-bump if needed
    # Step 5: Retry logic with adjusted values
```

#### OrderManager Integration
```python
def check_budget_constraints(self, symbol: str, side: OrderSide, 
                           quantity: float, price: float):
    """Check budget constraints using order builder quantization."""
    # Get symbol rules from connector
    symbol_rules = self._get_symbol_rules(symbol)
    
    # Build quantized order
    order_data, error_reason = self.order_builder.build_order(
        symbol=symbol,
        raw_price=price,
        target_notional=quantity * price,
        symbol_rules=symbol_rules,
        max_retries=1
    )
    
    if order_data is None:
        return False, 0.0, "precision_fail"
    
    return True, order_data["quantity"], ""
```

## Symbol Rules

### BTC/USDT Example
```python
{
    "price_tick": 0.01,           # 2 decimal places
    "qty_step": 0.00000001,       # 8 decimal places  
    "min_qty": 0.00000001,        # Minimum quantity
    "min_notional": 10.0,         # Minimum order value
}
```

### ETH/USDT Example
```python
{
    "price_tick": 0.01,           # 2 decimal places
    "qty_step": 0.00000001,       # 8 decimal places
    "min_qty": 0.00000001,        # Minimum quantity
    "min_notional": 10.0,         # Minimum order value
}
```

### SOL/USDT Example
```python
{
    "price_tick": 0.01,           # 2 decimal places
    "qty_step": 0.01,             # 2 decimal places (different from BTC/ETH)
    "min_qty": 0.01,              # Minimum quantity
    "min_notional": 10.0,         # Minimum order value
}
```

## Usage Examples

### Basic Order Quantization
```python
from src.crypto_mvp.execution.order_builder import OrderBuilder

order_builder = OrderBuilder()

# BTC/USDT at ~$123,791 with $50 slice
order_data, error_reason = order_builder.build_order(
    symbol="BTC/USDT",
    raw_price=123791.0,
    target_notional=50.0,
    symbol_rules={
        "price_tick": 0.01,
        "qty_step": 0.00000001,
        "min_qty": 0.00000001,
        "min_notional": 10.0,
    },
    max_retries=1
)

if order_data:
    print(f"Quantized Price: ${order_data['price']:,.2f}")
    print(f"Quantized Quantity: {order_data['quantity']:.8f} BTC")
    print(f"Final Notional: ${order_data['notional']:.2f}")
```

### Auto-Bump Scenario
```python
# Small target notional that gets auto-bumped
order_data, error_reason = order_builder.build_order(
    symbol="BTC/USDT",
    raw_price=50000.0,
    target_notional=5.0,  # Below minimum
    symbol_rules={
        "price_tick": 0.01,
        "qty_step": 0.00000001,
        "min_qty": 0.00000001,
        "min_notional": 10.0,  # Higher than target
    },
    max_retries=1
)

# Result: order_data['notional'] >= 10.0 (auto-bumped)
```

### Precision Validation
```python
# Validate existing order
is_valid, error = order_builder.validate_order_precision(
    symbol="BTC/USDT",
    price=123.45,  # Must be aligned to tick size
    quantity=0.123,  # Must be aligned to step size
    symbol_rules={
        "price_tick": 0.01,
        "qty_step": 0.001,
        "min_qty": 0.001,
        "min_notional": 10.0,
    }
)

if not is_valid:
    print(f"Order validation failed: {error}")
```

## Logging

### Quantization Logs
```
ORDER_QUANTIZE: tick=0.01, step=0.00000001, min_qty=0.00000001, min_notional=10.0, in: price=123791.00000000, qty_raw=0.00040384, out: price=123791.00000000, qty=0.00040400
```

### Error Logs
```
⏭️ SKIP BTC/USDT reason=precision_fail quantity=0.00040384 rounded=0.00000000 step_size=0.00000001
```

## Testing

### Test Scenarios

1. **BTC/USDT Precision**: Tests the specific scenario mentioned in requirements
2. **Auto-Bump Logic**: Tests minimum notional auto-bump functionality
3. **Precision Validation**: Tests order validation against symbol rules
4. **Retry Logic**: Tests retry mechanism with adjusted values
5. **Per-Trade Cap**: Tests per-trade cap constraint handling
6. **Different Precision**: Tests symbols with different precision requirements

### Running Tests

```bash
cd crypto_mvp
python -m pytest tests/test_order_precision.py -v
```

### Example Usage

```bash
cd crypto_mvp
python examples/order_precision_example.py
```

## Configuration

### Symbol Rules Sources

1. **Exchange API**: Primary source for real-time rules
2. **Default Rules**: Fallback when API is unavailable
3. **Symbol-Specific**: Different rules for different asset types

### Precision Parameters

- **Price Tick**: Minimum price increment (e.g., 0.01 for 2 decimal places)
- **Quantity Step**: Minimum quantity increment (e.g., 0.00000001 for 8 decimal places)
- **Minimum Quantity**: Smallest allowed order quantity
- **Minimum Notional**: Smallest allowed order value

### Retry Configuration

- **Max Retries**: Number of retry attempts (default: 1)
- **Auto-Bump**: Whether to auto-bump to minimum constraints
- **Per-Trade Cap**: Maximum notional per trade

## Benefits

### 1. Prevents PRECISION_FAIL Errors
- Automatic quantization to exchange requirements
- Validation before order submission
- Clear error messages for debugging

### 2. Exchange Compliance
- Enforces exchange-specific precision rules
- Handles different symbols with different requirements
- Maintains compatibility across exchanges

### 3. Robust Error Handling
- Graceful fallback to default rules
- Retry logic with adjusted values
- Clear error messages and logging

### 4. Performance Optimization
- Caching of symbol rules
- Efficient quantization algorithms
- Minimal API calls

## Integration Points

### OrderManager Integration
- Replaces existing precision handling
- Uses order builder for all order creation
- Maintains backward compatibility

### Connector Integration
- Coinbase connector provides symbol rules
- Extensible to other exchanges
- Fallback to default rules

### Trading System Integration
- Seamless integration with existing order flow
- No changes required to calling code
- Enhanced error reporting

## Future Enhancements

1. **Multi-Exchange Support**: Extend to other exchanges beyond Coinbase
2. **Dynamic Rule Updates**: Real-time rule updates from exchange APIs
3. **Advanced Retry Logic**: More sophisticated retry strategies
4. **Performance Metrics**: Track quantization performance and accuracy
5. **Rule Validation**: Validate rules against exchange documentation

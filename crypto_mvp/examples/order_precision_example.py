"""
Example demonstrating order precision and quantization system.

This example shows how the system prevents PRECISION_FAIL errors
through proper order quantization and symbol rules enforcement.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from crypto_mvp.execution.order_builder import OrderBuilder
from crypto_mvp.data.connectors.coinbase import CoinbaseConnector


def main():
    """Demonstrate order precision system."""
    
    print("=== Order Precision and Quantization Example ===")
    
    # Initialize components
    order_builder = OrderBuilder()
    coinbase_connector = CoinbaseConnector()
    
    # Example 1: BTC/USDT ~$123,791 with $50 slice
    print("\n--- Example 1: BTC/USDT Precision Scenario ---")
    
    btc_price = 123791.0
    target_notional = 50.0
    
    # Get BTC/USDT symbol rules from Coinbase
    try:
        btc_rules = coinbase_connector.get_symbol_rules("BTC/USDT")
        print(f"BTC/USDT Symbol Rules: {btc_rules}")
    except Exception as e:
        print(f"Using default BTC rules (API unavailable): {e}")
        btc_rules = {
            "price_tick": 0.01,
            "qty_step": 0.00000001,
            "min_qty": 0.00000001,
            "min_notional": 10.0,
        }
    
    # Build quantized order
    order_data, error_reason = order_builder.build_order(
        symbol="BTC/USDT",
        raw_price=btc_price,
        target_notional=target_notional,
        symbol_rules=btc_rules,
        max_retries=1
    )
    
    if order_data:
        print("✅ Order built successfully!")
        print(f"  Raw Price: ${btc_price:,.2f}")
        print(f"  Quantized Price: ${order_data['price']:,.2f}")
        print(f"  Target Notional: ${target_notional:.2f}")
        print(f"  Quantized Quantity: {order_data['quantity']:.8f} BTC")
        print(f"  Final Notional: ${order_data['notional']:.2f}")
        print(f"  Price Tick: {btc_rules['price_tick']}")
        print(f"  Quantity Step: {btc_rules['qty_step']}")
    else:
        print(f"❌ Order build failed: {error_reason}")
    
    # Example 2: ETH/USDT with small target notional (auto-bump scenario)
    print("\n--- Example 2: ETH/USDT Auto-Bump Scenario ---")
    
    eth_price = 3500.0
    small_target = 5.0  # Below typical minimum notional
    
    try:
        eth_rules = coinbase_connector.get_symbol_rules("ETH/USDT")
    except Exception:
        eth_rules = {
            "price_tick": 0.01,
            "qty_step": 0.00000001,
            "min_qty": 0.00000001,
            "min_notional": 10.0,
        }
    
    order_data, error_reason = order_builder.build_order(
        symbol="ETH/USDT",
        raw_price=eth_price,
        target_notional=small_target,
        symbol_rules=eth_rules,
        max_retries=1
    )
    
    if order_data:
        print("✅ Order built with auto-bump!")
        print(f"  Raw Price: ${eth_price:,.2f}")
        print(f"  Target Notional: ${small_target:.2f}")
        print(f"  Final Notional: ${order_data['notional']:.2f}")
        print(f"  Auto-bumped: {order_data['notional'] >= small_target}")
        print(f"  Quantity: {order_data['quantity']:.8f} ETH")
    else:
        print(f"❌ Order build failed: {error_reason}")
    
    # Example 3: SOL/USDT with different precision requirements
    print("\n--- Example 3: SOL/USDT Different Precision ---")
    
    sol_price = 200.0
    sol_target = 100.0
    
    # SOL typically has different step size (2 decimal places vs 8 for BTC/ETH)
    sol_rules = {
        "price_tick": 0.01,
        "qty_step": 0.01,       # 2 decimal places
        "min_qty": 0.01,
        "min_notional": 10.0,
    }
    
    order_data, error_reason = order_builder.build_order(
        symbol="SOL/USDT",
        raw_price=sol_price,
        target_notional=sol_target,
        symbol_rules=sol_rules,
        max_retries=1
    )
    
    if order_data:
        print("✅ SOL order built successfully!")
        print(f"  Raw Price: ${sol_price:.2f}")
        print(f"  Quantized Price: ${order_data['price']:.2f}")
        print(f"  Target Notional: ${sol_target:.2f}")
        print(f"  Quantized Quantity: {order_data['quantity']:.2f} SOL")
        print(f"  Final Notional: ${order_data['notional']:.2f}")
        print(f"  Quantity Step: {sol_rules['qty_step']} (2 decimal places)")
    else:
        print(f"❌ Order build failed: {error_reason}")
    
    # Example 4: Precision validation
    print("\n--- Example 4: Precision Validation ---")
    
    # Test various precision scenarios
    test_cases = [
        {
            "name": "Valid Order",
            "price": 123.45,
            "quantity": 0.123,
            "rules": {"price_tick": 0.01, "qty_step": 0.001, "min_qty": 0.001, "min_notional": 10.0}
        },
        {
            "name": "Invalid Price (not aligned to tick)",
            "price": 123.456,
            "quantity": 0.123,
            "rules": {"price_tick": 0.01, "qty_step": 0.001, "min_qty": 0.001, "min_notional": 10.0}
        },
        {
            "name": "Invalid Quantity (not aligned to step)",
            "price": 123.45,
            "quantity": 0.1234,
            "rules": {"price_tick": 0.01, "qty_step": 0.001, "min_qty": 0.001, "min_notional": 10.0}
        },
        {
            "name": "Below Minimum Quantity",
            "price": 123.45,
            "quantity": 0.0005,
            "rules": {"price_tick": 0.01, "qty_step": 0.001, "min_qty": 0.001, "min_notional": 10.0}
        },
        {
            "name": "Below Minimum Notional",
            "price": 123.45,
            "quantity": 0.05,
            "rules": {"price_tick": 0.01, "qty_step": 0.001, "min_qty": 0.001, "min_notional": 10.0}
        }
    ]
    
    for test_case in test_cases:
        is_valid, error = order_builder.validate_order_precision(
            symbol="TEST/USDT",
            price=test_case["price"],
            quantity=test_case["quantity"],
            symbol_rules=test_case["rules"]
        )
        
        status = "✅ Valid" if is_valid else "❌ Invalid"
        print(f"  {test_case['name']}: {status}")
        if not is_valid:
            print(f"    Error: {error}")
    
    # Example 5: Retry logic demonstration
    print("\n--- Example 5: Retry Logic with Minimum Constraints ---")
    
    # Scenario that requires retry due to minimum constraints
    retry_price = 100000.0
    retry_target = 5.0  # Very small, below minimum
    
    retry_rules = {
        "price_tick": 0.01,
        "qty_step": 0.00000001,
        "min_qty": 0.00000001,
        "min_notional": 15.0,  # Higher than target
    }
    
    order_data, error_reason = order_builder.build_order(
        symbol="BTC/USDT",
        raw_price=retry_price,
        target_notional=retry_target,
        symbol_rules=retry_rules,
        max_retries=2
    )
    
    if order_data:
        print("✅ Order built after retry!")
        print(f"  Original Target: ${retry_target:.2f}")
        print(f"  Final Notional: ${order_data['notional']:.2f}")
        print(f"  Retry Attempts: {order_data['attempt']}")
        print(f"  Quantity: {order_data['quantity']:.8f} BTC")
    else:
        print(f"❌ Order build failed after retries: {error_reason}")
    
    print("\n=== Order Precision Examples Completed ===")
    print("\nKey Benefits:")
    print("✅ Prevents PRECISION_FAIL errors through proper quantization")
    print("✅ Auto-bumps to minimum notional when required")
    print("✅ Enforces exchange-specific precision requirements")
    print("✅ Provides clear error messages for debugging")
    print("✅ Supports retry logic with adjusted values")


if __name__ == "__main__":
    main()

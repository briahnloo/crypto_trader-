#!/usr/bin/env python3
"""
Test to reproduce and fix the side/target inversion issue in DECISION_TRACE.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager
import logging

# Set up logging to see debug output
logging.basicConfig(level=logging.DEBUG)

def test_side_inversion():
    """Test the side inversion issue with a simple BUY scenario."""
    
    # Create a minimal config
    config = {
        "trading": {
            "initial_capital": 100000.0,
            "live_mode": False
        },
        "risk": {
            "sl_tp": {
                "atr_mult_sl": 1.2,
                "atr_mult_tp": 2.0,
                "fallback_pct_sl": 0.02,
                "fallback_pct_tp": 0.04,
                "min_sl_abs": 0.001,
                "min_tp_abs": 0.002
            },
            "enable_percent_fallback": True
        }
    }
    
    # Create risk manager
    risk_manager = ProfitOptimizedRiskManager(config)
    
    # Create a BUY signal with positive composite_score
    signals = {
        "BTC/USDT": {
            "composite_score": 0.5,  # Positive score should be BUY
            "current_price": 50000.0,
            "metadata": {
                "regime": "trending"
            }
        }
    }
    
    print("=== Testing BUY Signal ===")
    print(f"Composite score: {signals['BTC/USDT']['composite_score']}")
    print(f"Expected side: BUY")
    
    # Test the side determination logic directly
    composite_score = signals["BTC/USDT"]["composite_score"]
    side = "buy" if composite_score > 0 else "sell"
    print(f"Calculated side: {side}")
    
    # Test SL/TP derivation
    entry_price = 50000.0
    sl_tp_result = risk_manager.derive_sl_tp(
        entry_price=entry_price,
        side=side,
        atr=None,
        strategy_sl=None,
        strategy_tp=None,
        symbol="BTC/USDT"
    )
    
    print(f"Entry price: {entry_price}")
    print(f"Stop loss: {sl_tp_result['stop_loss']}")
    print(f"Take profit: {sl_tp_result['take_profit']}")
    print(f"Source: {sl_tp_result['source']}")
    
    # Check if SL/TP are correct for BUY
    stop_loss = sl_tp_result['stop_loss']
    take_profit = sl_tp_result['take_profit']
    
    print(f"\n=== Validation ===")
    print(f"SL < entry? {stop_loss < entry_price} (should be True for BUY)")
    print(f"TP > entry? {take_profit > entry_price} (should be True for BUY)")
    
    if stop_loss < entry_price and take_profit > entry_price:
        print("✅ SL/TP values are correct for BUY position")
    else:
        print("❌ SL/TP values are INCORRECT for BUY position")
        print(f"   This suggests the side was wrong or SL/TP calculation failed")
    
    print("\n" + "="*50)
    print("=== Testing SELL Signal ===")
    
    # Test SELL scenario
    composite_score_sell = -0.5  # Negative score should be SELL
    side_sell = "buy" if composite_score_sell > 0 else "sell"
    print(f"Composite score: {composite_score_sell}")
    print(f"Expected side: SELL")
    print(f"Calculated side: {side_sell}")
    
    sl_tp_result_sell = risk_manager.derive_sl_tp(
        entry_price=entry_price,
        side=side_sell,
        atr=None,
        strategy_sl=None,
        strategy_tp=None,
        symbol="BTC/USDT"
    )
    
    print(f"Entry price: {entry_price}")
    print(f"Stop loss: {sl_tp_result_sell['stop_loss']}")
    print(f"Take profit: {sl_tp_result_sell['take_profit']}")
    print(f"Source: {sl_tp_result_sell['source']}")
    
    # Check if SL/TP are correct for SELL
    stop_loss_sell = sl_tp_result_sell['stop_loss']
    take_profit_sell = sl_tp_result_sell['take_profit']
    
    print(f"\n=== Validation ===")
    print(f"SL > entry? {stop_loss_sell > entry_price} (should be True for SELL)")
    print(f"TP < entry? {take_profit_sell < entry_price} (should be True for SELL)")
    
    if stop_loss_sell > entry_price and take_profit_sell < entry_price:
        print("✅ SL/TP values are correct for SELL position")
    else:
        print("❌ SL/TP values are INCORRECT for SELL position")
        print(f"   This suggests the side was wrong or SL/TP calculation failed")
    
    return side, sl_tp_result

if __name__ == "__main__":
    test_side_inversion()

#!/usr/bin/env python3
"""
Test script to debug the side inversion issue in decision trace logging.
This reproduces the exact scenario where BUY fills show as SELL in decision trace.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager
def test_side_inversion_debug():
    """Test the side inversion issue step by step."""
    
    # Setup basic logging
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Create risk manager
    config = {
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
    
    risk_manager = ProfitOptimizedRiskManager(config)
    risk_manager.initialize()
    
    # Test scenario: BUY signal with positive composite score
    print("=== Testing BUY Signal Scenario ===")
    
    # Simulate the exact scenario from the user's report
    entry_price = 5000.0
    composite_score = 0.5  # Positive score should result in BUY
    side = "buy" if composite_score > 0 else "sell"
    
    print(f"Entry price: {entry_price}")
    print(f"Composite score: {composite_score}")
    print(f"Determined side: {side}")
    print(f"Expected action: {side.upper()}")
    
    # Derive SL/TP
    try:
        sl_tp_result = risk_manager.derive_sl_tp(
            entry_price=entry_price,
            side=side,
            atr=None,  # Force percent fallback
            strategy_sl=None,
            strategy_tp=None,
            symbol="BTC/USDT"
        )
        
        stop_loss = sl_tp_result["stop_loss"]
        take_profit = sl_tp_result["take_profit"]
        source = sl_tp_result["source"]
        
        print(f"SL/TP Source: {source}")
        print(f"Stop Loss: {stop_loss}")
        print(f"Take Profit: {take_profit}")
        
        # Validate SL/TP logic
        if side == "buy":
            sl_correct = stop_loss < entry_price
            tp_correct = take_profit > entry_price
            print(f"SL < entry? {sl_correct} (should be True for BUY)")
            print(f"TP > entry? {tp_correct} (should be True for BUY)")
            
            if sl_correct and tp_correct:
                print("✅ SL/TP values are correct for BUY position")
            else:
                print("❌ SL/TP values are INCORRECT for BUY position")
        else:
            sl_correct = stop_loss > entry_price
            tp_correct = take_profit < entry_price
            print(f"SL > entry? {sl_correct} (should be True for SELL)")
            print(f"TP < entry? {tp_correct} (should be True for SELL)")
            
            if sl_correct and tp_correct:
                print("✅ SL/TP values are correct for SELL position")
            else:
                print("❌ SL/TP values are INCORRECT for SELL position")
        
        # Simulate the decision trace logging
        print("\n=== Simulating Decision Trace ===")
        print(f"Action parameter: {side.upper()}")
        print(f"Stop Loss: {stop_loss}")
        print(f"Take Profit: {take_profit}")
        
        # This is what should appear in the decision trace
        decision_trace = {
            "final_action": side.upper(),
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4)
        }
        
        print(f"Decision trace: {decision_trace}")
        
        # Check if this matches the user's reported issue
        if side == "buy" and decision_trace["final_action"] == "SELL":
            print("❌ ISSUE FOUND: BUY signal showing as SELL in decision trace!")
        elif side == "buy" and decision_trace["final_action"] == "BUY":
            print("✅ Correct: BUY signal showing as BUY in decision trace")
        elif side == "sell" and decision_trace["final_action"] == "BUY":
            print("❌ ISSUE FOUND: SELL signal showing as BUY in decision trace!")
        elif side == "sell" and decision_trace["final_action"] == "SELL":
            print("✅ Correct: SELL signal showing as SELL in decision trace")
        
    except Exception as e:
        print(f"Error in SL/TP derivation: {e}")
        import traceback
        traceback.print_exc()

def test_several_scenarios():
    """Test multiple scenarios to identify the pattern."""
    
    print("\n" + "="*60)
    print("TESTING MULTIPLE SCENARIOS")
    print("="*60)
    
    scenarios = [
        {"composite_score": 0.5, "expected_side": "buy"},
        {"composite_score": -0.3, "expected_side": "sell"},
        {"composite_score": 1.2, "expected_side": "buy"},
        {"composite_score": -0.8, "expected_side": "sell"},
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n--- Scenario {i} ---")
        composite_score = scenario["composite_score"]
        expected_side = scenario["expected_side"]
        
        side = "buy" if composite_score > 0 else "sell"
        print(f"Composite score: {composite_score}")
        print(f"Expected side: {expected_side}")
        print(f"Calculated side: {side}")
        print(f"Match? {side == expected_side}")
        
        if side != expected_side:
            print("❌ SIDE CALCULATION ERROR!")

if __name__ == "__main__":
    test_side_inversion_debug()
    test_several_scenarios()

#!/usr/bin/env python3
"""
Test script to debug the decision trace logging specifically.
This focuses on the exact issue reported by the user.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager
import logging

def test_decision_trace_debug():
    """Test the decision trace logging to identify the side inversion issue."""
    
    # Setup logging
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
    
    print("=== Testing Decision Trace Logging ===")
    
    # Test multiple scenarios to identify the pattern
    test_cases = [
        {"composite_score": 0.5, "expected_side": "buy", "expected_action": "BUY"},
        {"composite_score": -0.3, "expected_side": "sell", "expected_action": "SELL"},
        {"composite_score": 1.2, "expected_side": "buy", "expected_action": "BUY"},
        {"composite_score": -0.8, "expected_side": "sell", "expected_action": "SELL"},
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n--- Test Case {i} ---")
        
        composite_score = test_case["composite_score"]
        expected_side = test_case["expected_side"]
        expected_action = test_case["expected_action"]
        
        # Step 1: Determine side (line 1245 in trading_system.py)
        side = "buy" if composite_score > 0 else "sell"
        print(f"Composite score: {composite_score}")
        print(f"Expected side: {expected_side}")
        print(f"Calculated side: {side}")
        print(f"Side match: {side == expected_side}")
        
        # Step 2: Derive SL/TP
        try:
            sl_tp_result = risk_manager.derive_sl_tp(
                entry_price=5000.0,
                side=side,
                atr=None,
                strategy_sl=None,
                strategy_tp=None,
                symbol="BTC/USDT"
            )
            
            stop_loss = sl_tp_result["stop_loss"]
            take_profit = sl_tp_result["take_profit"]
            
            print(f"SL/TP derived: SL={stop_loss}, TP={take_profit}")
            
            # Step 3: Create candidate (simulate lines 1305-1317)
            candidate = {
                "symbol": "BTC/USDT",
                "signal": {"composite_score": composite_score, "confidence": 0.8},
                "current_price": 5000.0,
                "composite_score": composite_score,
                "side": side,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "sl_tp_src": sl_tp_result["source"],
                "risk_reward_ratio": 2.0,
                "regime": "trending"
            }
            
            print(f"Candidate side: {candidate['side']}")
            
            # Step 4: Extract variables from candidate (lines 1572-1577)
            signal = candidate["signal"]
            current_price = candidate["current_price"]
            composite_score = candidate["composite_score"]
            side = candidate["side"]  # This is the critical line
            stop_loss = candidate["stop_loss"]
            take_profit = candidate["take_profit"]
            
            print(f"Extracted side: {side}")
            
            # Step 5: Simulate decision trace logging (lines 1705-1715)
            action = side.upper()  # This is line 1709
            
            print(f"Action for decision trace: {action}")
            print(f"Expected action: {expected_action}")
            print(f"Action match: {action == expected_action}")
            
            # Validate SL/TP logic
            if side == "buy":
                sl_correct = stop_loss < current_price
                tp_correct = take_profit > current_price
                print(f"SL < entry? {sl_correct} (should be True for BUY)")
                print(f"TP > entry? {tp_correct} (should be True for BUY)")
                sl_tp_correct = sl_correct and tp_correct
            else:
                sl_correct = stop_loss > current_price
                tp_correct = take_profit < current_price
                print(f"SL > entry? {sl_correct} (should be True for SELL)")
                print(f"TP < entry? {tp_correct} (should be True for SELL)")
                sl_tp_correct = sl_correct and tp_correct
            
            # Final validation
            if action == expected_action and sl_tp_correct:
                print("✅ PASS: Side and SL/TP are correct")
            else:
                print("❌ FAIL: Side or SL/TP is incorrect")
                if action != expected_action:
                    print(f"   Side issue: Expected {expected_action}, got {action}")
                if not sl_tp_correct:
                    print(f"   SL/TP issue: SL={stop_loss}, TP={take_profit}, Entry={current_price}")
            
        except Exception as e:
            print(f"Error in test case {i}: {e}")
            import traceback
            traceback.print_exc()

def test_specific_user_scenario():
    """Test the specific scenario mentioned by the user."""
    
    print("\n" + "="*60)
    print("TESTING USER'S SPECIFIC SCENARIO")
    print("="*60)
    
    # User reported: "After two BUY fills" but decision trace shows "SELL"
    # This suggests the actual trades are BUY (position_size > 0) but decision trace is wrong
    
    print("Simulating: BUY fills with positive position_size but wrong decision trace")
    
    # Scenario 1: Normal BUY case
    composite_score = 0.5
    side = "buy" if composite_score > 0 else "sell"
    position_size = 0.2  # Positive position size indicates BUY
    
    print(f"Scenario 1 - Normal BUY:")
    print(f"  Composite score: {composite_score}")
    print(f"  Side: {side}")
    print(f"  Position size: {position_size}")
    print(f"  Expected action: BUY")
    print(f"  Actual action: {side.upper()}")
    print(f"  Match: {side.upper() == 'BUY'}")
    
    # Scenario 2: What if side is somehow inverted?
    print(f"\nScenario 2 - Side inversion (hypothetical):")
    print(f"  Composite score: {composite_score}")
    print(f"  Side: {side}")
    print(f"  Position size: {position_size}")
    print(f"  Expected action: BUY")
    
    # Simulate what would happen if side was inverted
    inverted_side = "sell" if side == "buy" else "buy"
    print(f"  Inverted side: {inverted_side}")
    print(f"  Inverted action: {inverted_side.upper()}")
    print(f"  This would cause the issue: BUY fills showing as SELL in decision trace")

if __name__ == "__main__":
    test_decision_trace_debug()
    test_specific_user_scenario()

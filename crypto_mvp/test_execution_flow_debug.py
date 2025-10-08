#!/usr/bin/env python3
"""
Test script to debug the execution flow and identify where the side inversion occurs.
This simulates the exact execution flow from candidate creation to decision trace logging.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from crypto_mvp.risk.risk_manager import ProfitOptimizedRiskManager
from crypto_mvp.execution.order_manager import OrderManager, OrderSide
from crypto_mvp.state.store import StateStore
import logging

def test_execution_flow_debug():
    """Test the complete execution flow to identify the side inversion issue."""
    
    # Setup logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Create components
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
            "enable_percent_fallback": True,
            "sizing": {
                "max_position_size": 0.1,
                "min_position_size": 0.01
            }
        }
    }
    
    risk_manager = ProfitOptimizedRiskManager(config)
    risk_manager.initialize()
    
    # Create state store and order manager
    state_store = StateStore(":memory:")
    order_manager = OrderManager(config)
    order_manager.set_state_store(state_store)
    
    print("=== Testing Complete Execution Flow ===")
    
    # Simulate the exact scenario from the user's report
    symbol = "BTC/USDT"
    current_price = 5000.0
    composite_score = 0.5  # Positive score should result in BUY
    
    print(f"Symbol: {symbol}")
    print(f"Current price: {current_price}")
    print(f"Composite score: {composite_score}")
    
    # Step 1: Determine side based on composite score (line 1245)
    side = "buy" if composite_score > 0 else "sell"
    print(f"Step 1 - Determined side: {side}")
    print(f"Expected action: {side.upper()}")
    
    # Step 2: Derive SL/TP (lines 1253-1260)
    try:
        sl_tp_result = risk_manager.derive_sl_tp(
            entry_price=current_price,
            side=side,
            atr=None,  # Force percent fallback
            strategy_sl=None,
            strategy_tp=None,
            symbol=symbol
        )
        
        stop_loss = sl_tp_result["stop_loss"]
        take_profit = sl_tp_result["take_profit"]
        sl_tp_src = sl_tp_result["source"]
        
        print(f"Step 2 - SL/TP derived:")
        print(f"  Stop Loss: {stop_loss}")
        print(f"  Take Profit: {take_profit}")
        print(f"  Source: {sl_tp_src}")
        
        # Validate SL/TP logic
        if side == "buy":
            sl_correct = stop_loss < current_price
            tp_correct = take_profit > current_price
            print(f"  SL < entry? {sl_correct} (should be True for BUY)")
            print(f"  TP > entry? {tp_correct} (should be True for BUY)")
        else:
            sl_correct = stop_loss > current_price
            tp_correct = take_profit < current_price
            print(f"  SL > entry? {sl_correct} (should be True for SELL)")
            print(f"  TP < entry? {tp_correct} (should be True for SELL)")
        
    except Exception as e:
        print(f"Error in SL/TP derivation: {e}")
        return
    
    # Step 3: Create candidate (lines 1305-1317)
    candidate = {
        "symbol": symbol,
        "signal": {"composite_score": composite_score, "confidence": 0.8},
        "current_price": current_price,
        "composite_score": composite_score,
        "side": side,  # This should be "buy"
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sl_tp_src": sl_tp_src,
        "risk_reward_ratio": 2.0,
        "regime": "trending"
    }
    
    print(f"Step 3 - Candidate created:")
    print(f"  Candidate side: {candidate['side']}")
    print(f"  Candidate stop_loss: {candidate['stop_loss']}")
    print(f"  Candidate take_profit: {candidate['take_profit']}")
    
    # Step 4: Extract variables from candidate (lines 1572-1577)
    signal = candidate["signal"]
    current_price = candidate["current_price"]
    composite_score = candidate["composite_score"]
    side = candidate["side"]  # This should still be "buy"
    stop_loss = candidate["stop_loss"]
    take_profit = candidate["take_profit"]
    sl_tp_src = candidate["sl_tp_src"]
    rr_ratio = candidate["risk_reward_ratio"]
    regime = candidate["regime"]
    
    print(f"Step 4 - Variables extracted from candidate:")
    print(f"  side: {side}")
    print(f"  stop_loss: {stop_loss}")
    print(f"  take_profit: {take_profit}")
    
    # Step 5: Simulate order execution (lines 1638-1647)
    try:
        execution_result = order_manager.execute_by_slices(
            symbol=symbol,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            target_notional=1000.0,
            current_price=current_price,
            strategy="composite",
            is_pilot=False,
            cfg=config.get("risk", {}).get("sizing", {})
        )
        
        print(f"Step 5 - Order execution result:")
        print(f"  Executed notional: {execution_result['executed_notional']}")
        print(f"  Slices executed: {execution_result['slices_executed']}")
        
        # Step 6: Convert to trade result (lines 1650-1658)
        if execution_result["executed_notional"] > 0:
            trade_result = {
                "status": "executed",
                "position_size": execution_result["executed_notional"] / current_price,
                "entry_price": current_price,
                "notional_value": execution_result["executed_notional"],
                "slices_executed": execution_result["slices_executed"],
                "execution_ratio": execution_result["execution_ratio"]
            }
            
            print(f"Step 6 - Trade result:")
            print(f"  Position size: {trade_result['position_size']}")
            print(f"  Entry price: {trade_result['entry_price']}")
            
            # Step 7: Add SL/TP info to trade result (lines 1684-1688)
            trade_result["stop_loss"] = stop_loss
            trade_result["take_profit"] = take_profit
            trade_result["risk_reward_ratio"] = rr_ratio
            trade_result["sl_tp_src"] = sl_tp_src
            
            print(f"Step 7 - SL/TP added to trade result:")
            print(f"  Trade result stop_loss: {trade_result['stop_loss']}")
            print(f"  Trade result take_profit: {trade_result['take_profit']}")
            
            # Step 8: Simulate decision trace logging (lines 1705-1715)
            position_size = trade_result.get("position_size", 0)
            
            print(f"Step 8 - Decision trace logging:")
            print(f"  symbol: {symbol}")
            print(f"  side: {side}")
            print(f"  composite_score: {composite_score}")
            print(f"  position_size: {position_size}")
            print(f"  entry_price: {current_price}")
            print(f"  stop_loss: {stop_loss}")
            print(f"  take_profit: {take_profit}")
            print(f"  action parameter: {side.upper()}")
            
            # This is what would be logged in the decision trace
            decision_trace = {
                "final_action": side.upper(),
                "stop_loss": round(stop_loss, 4),
                "take_profit": round(take_profit, 4)
            }
            
            print(f"Step 9 - Final decision trace:")
            print(f"  {decision_trace}")
            
            # Check for the issue
            if side == "buy" and decision_trace["final_action"] == "SELL":
                print("❌ ISSUE FOUND: BUY signal showing as SELL in decision trace!")
            elif side == "buy" and decision_trace["final_action"] == "BUY":
                print("✅ Correct: BUY signal showing as BUY in decision trace")
            elif side == "sell" and decision_trace["final_action"] == "BUY":
                print("❌ ISSUE FOUND: SELL signal showing as BUY in decision trace!")
            elif side == "sell" and decision_trace["final_action"] == "SELL":
                print("✅ Correct: SELL signal showing as SELL in decision trace")
            
            # Check SL/TP values
            if side == "buy":
                if stop_loss < current_price and take_profit > current_price:
                    print("✅ SL/TP values are correct for BUY position")
                else:
                    print("❌ SL/TP values are INCORRECT for BUY position")
            else:
                if stop_loss > current_price and take_profit < current_price:
                    print("✅ SL/TP values are correct for SELL position")
                else:
                    print("❌ SL/TP values are INCORRECT for SELL position")
        
        else:
            print("No execution - trade was rejected")
            
    except Exception as e:
        print(f"Error in order execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_execution_flow_debug()

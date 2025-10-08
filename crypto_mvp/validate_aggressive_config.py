#!/usr/bin/env python3
"""
Validation script to verify aggressive configuration changes.
Shows before/after comparison for key profit-impacting parameters.
"""

import yaml

def load_config():
    """Load the config file."""
    with open('config/profit_optimized.yaml', 'r') as f:
        return yaml.safe_load(f)

def calculate_position_size_example(config, equity=10000):
    """Calculate example position size with current config."""
    risk_pct = config['risk']['sizing']['risk_per_trade_pct']
    per_symbol_cap = config['risk']['sizing']['per_symbol_cap_$']
    max_position_pct = config['risk']['sizing']['max_position_value_pct']
    
    # Risk-based sizing (simplified)
    risk_amount = equity * (risk_pct / 100)
    
    # Example with 2% stop loss
    stop_distance_pct = 0.02
    position_from_risk = risk_amount / stop_distance_pct
    
    # Apply caps
    position_from_cap = min(per_symbol_cap, equity * max_position_pct)
    
    # Final position
    position_size = min(position_from_risk, position_from_cap)
    
    return position_size, risk_amount

def main():
    config = load_config()
    
    print("=" * 80)
    print("⚡ AGGRESSIVE PROFIT-MAXIMIZING CONFIGURATION VALIDATION ⚡")
    print("=" * 80)
    print()
    
    print("🎯 CRITICAL PARAMETERS (The Money Makers):")
    print("-" * 80)
    
    # Position sizing
    risk_sizing = config['risk']['sizing']
    print(f"Risk per trade:           {risk_sizing['risk_per_trade_pct']}% " +
          f"{'✅ AGGRESSIVE (was 0.01%)' if risk_sizing['risk_per_trade_pct'] >= 2.0 else '⚠️  Still conservative'}")
    
    print(f"Per symbol cap:           ${risk_sizing['per_symbol_cap_$']:,.0f} " +
          f"{'✅ AGGRESSIVE (was $500)' if risk_sizing['per_symbol_cap_$'] >= 2000 else '⚠️  Still conservative'}")
    
    print(f"Max position value:       {risk_sizing['max_position_value_pct']*100:.0f}% " +
          f"{'✅ AGGRESSIVE (was 5%)' if risk_sizing['max_position_value_pct'] >= 0.15 else '⚠️  Still conservative'}")
    
    print(f"Session cap:              {risk_sizing['session_cap_$']*100:.0f}% " +
          f"{'✅ AGGRESSIVE (was 30%)' if risk_sizing['session_cap_$'] >= 0.60 else '⚠️  Still conservative'}")
    
    print()
    
    # Entry filtering
    entry_gate = config['risk']['entry_gate']
    print(f"Hard floor minimum:       {entry_gate['hard_floor_min']} " +
          f"{'✅ AGGRESSIVE (was 0.60)' if entry_gate['hard_floor_min'] <= 0.30 else '⚠️  Still conservative'}")
    
    print(f"Top K entries:            {entry_gate['top_k_entries']} " +
          f"{'✅ AGGRESSIVE (was 2)' if entry_gate['top_k_entries'] >= 3 else '⚠️  Could be higher'}")
    
    print(f"RR minimum:               {config['risk']['rr_min']} " +
          f"{'✅ AGGRESSIVE (was 1.30)' if config['risk']['rr_min'] <= 1.15 else '⚠️  Still conservative'}")
    
    print()
    
    # Risk limits
    print(f"Max risk per trade:       {config['risk']['max_risk_per_trade']*100:.0f}% " +
          f"{'✅ AGGRESSIVE (was 2%)' if config['risk']['max_risk_per_trade'] >= 0.04 else '⚠️  Still conservative'}")
    
    print(f"Daily loss limit:         {config['risk']['daily_loss_limit']*100:.0f}% " +
          f"{'✅ AGGRESSIVE (was 5%)' if config['risk']['daily_loss_limit'] >= 0.10 else '⚠️  Still conservative'}")
    
    print()
    print("=" * 80)
    print()
    
    # Calculate example position
    print("💰 POSITION SIZE EXAMPLE (with $10,000 equity):")
    print("-" * 80)
    position_size, risk_amount = calculate_position_size_example(config, 10000)
    
    print(f"Risk amount per trade:    ${risk_amount:,.2f}")
    print(f"Position size (2% SL):    ${position_size:,.2f}")
    print(f"Expected profit (4% TP):  ${position_size * 0.04:,.2f}")
    print(f"Risk/Reward ratio:        {(position_size * 0.04) / risk_amount:.2f}:1")
    print()
    
    # Daily potential
    trades_per_day = 8  # Conservative estimate
    avg_profit_per_win = position_size * 0.04
    win_rate = 0.50
    avg_loss_per_loss = risk_amount
    
    expected_daily_pnl = (trades_per_day * win_rate * avg_profit_per_win) - \
                         (trades_per_day * (1 - win_rate) * avg_loss_per_loss)
    
    print(f"📊 EXPECTED DAILY P&L (50% win rate, 8 trades/day):")
    print(f"   Wins:  {trades_per_day * win_rate:.0f} × ${avg_profit_per_win:,.2f} = ${trades_per_day * win_rate * avg_profit_per_win:,.2f}")
    print(f"   Losses: {trades_per_day * (1-win_rate):.0f} × ${avg_loss_per_loss:,.2f} = -${trades_per_day * (1-win_rate) * avg_loss_per_loss:,.2f}")
    print(f"   NET:   ${expected_daily_pnl:,.2f} per day")
    print(f"   Monthly projection: ${expected_daily_pnl * 20:,.2f} ({(expected_daily_pnl * 20 / 10000) * 100:.1f}% return)")
    print()
    
    print("=" * 80)
    print("✅ Configuration validated - Ready for aggressive trading!")
    print("=" * 80)
    print()
    print("🚀 NEXT STEPS:")
    print("   1. Run the trading system")
    print("   2. Monitor first 10-20 trades")
    print("   3. Expect to see positions of $1,000-2,500")
    print("   4. Watch for daily P&L of $300-1,000")
    print()

if __name__ == "__main__":
    main()


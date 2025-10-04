#!/usr/bin/env python3
"""
Fix indentation in trading_system.py
"""

# Read the file
with open("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/src/crypto_mvp/trading_system.py", "r") as f:
    lines = f.readlines()

# Fix the indentation issues
fixed_lines = []
for i, line in enumerate(lines):
    line_num = i + 1
    
    # Fix line 183 - should be indented under else block
    if line_num == 183:
        fixed_lines.append("                    self.portfolio[\"cash_balance\"] = latest_cash_equity[\"cash_balance\"]\n")
    # Fix line 184 - should be indented under else block  
    elif line_num == 184:
        fixed_lines.append("                    self.portfolio[\"total_fees\"] = latest_cash_equity[\"total_fees\"]\n")
    # Fix line 186 - should be indented under else block
    elif line_num == 186:
        fixed_lines.append("                    # Load positions into memory cache (positions are already in store)\n")
    # Fix line 187 - should be indented under else block
    elif line_num == 187:
        fixed_lines.append("                    self.portfolio[\"positions\"] = {}\n")
    # Fix line 188 - should be indented under else block
    elif line_num == 188:
        fixed_lines.append("                    for pos in existing_positions:\n")
    # Fix line 198 - should be indented under else block
    elif line_num == 198:
        fixed_lines.append("                    # Calculate equity using current mark prices (not stored outdated value)\n")
    # Fix line 199 - should be indented under else block
    elif line_num == 199:
        fixed_lines.append("                    stored_equity = latest_cash_equity[\"total_equity\"]\n")
    # Fix line 200 - should be indented under else block
    elif line_num == 200:
        fixed_lines.append("                    current_equity = self._get_total_equity()\n")
    # Fix line 201 - should be indented under else block
    elif line_num == 201:
        fixed_lines.append("                    self.portfolio[\"equity\"] = current_equity\n")
    # Fix line 203 - should be indented under else block
    elif line_num == 203:
        fixed_lines.append("                    # Log the difference between stored and calculated equity\n")
    # Fix line 204 - should be indented under else block
    elif line_num == 204:
        fixed_lines.append("                    equity_change = current_equity - stored_equity\n")
    # Fix line 205 - should be indented under else block
    elif line_num == 205:
        fixed_lines.append("                    equity_change_pct = (equity_change / stored_equity * 100) if stored_equity > 0 else 0\n")
    # Fix line 207 - should be indented under else block
    elif line_num == 207:
        fixed_lines.append("                    self.logger.info(f\"Loaded existing portfolio from store: cash=${self.portfolio['cash_balance']:,.2f}, equity=${current_equity:,.2f} (was ${stored_equity:,.2f} stored, {equity_change:+.2f} {equity_change_pct:+.1f}%), positions={len(existing_positions)}\")\n")
    else:
        fixed_lines.append(line)

# Write the fixed file
with open("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/src/crypto_mvp/trading_system.py", "w") as f:
    f.writelines(fixed_lines)

print("Fixed indentation issues in trading_system.py")

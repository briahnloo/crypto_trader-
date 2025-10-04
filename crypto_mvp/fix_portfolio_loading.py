#!/usr/bin/env python3
"""
Fix the portfolio loading section in trading_system.py
"""

# Read the file
with open("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/src/crypto_mvp/trading_system.py", "r") as f:
    lines = f.readlines()

# Find the problematic section and replace it
new_lines = []
in_problematic_section = False
skip_until_line = None

for i, line in enumerate(lines):
    line_num = i + 1
    
    # Start of problematic section
    if "Load existing state from store (no significant capital change)" in line:
        in_problematic_section = True
        new_lines.append(line)  # Keep the comment
        # Add the properly indented code
        new_lines.append("                    self.portfolio[\"cash_balance\"] = latest_cash_equity[\"cash_balance\"]\n")
        new_lines.append("                    self.portfolio[\"total_fees\"] = latest_cash_equity[\"total_fees\"]\n")
        new_lines.append("                    \n")
        new_lines.append("                    # Load positions into memory cache (positions are already in store)\n")
        new_lines.append("                    self.portfolio[\"positions\"] = {}\n")
        new_lines.append("                    for pos in existing_positions:\n")
        new_lines.append("                        symbol = pos[\"symbol\"]\n")
        new_lines.append("                        self.portfolio[\"positions\"][symbol] = {\n")
        new_lines.append("                            \"quantity\": pos[\"quantity\"],\n")
        new_lines.append("                            \"entry_price\": pos[\"entry_price\"],\n")
        new_lines.append("                            \"current_price\": pos[\"current_price\"],\n")
        new_lines.append("                            \"unrealized_pnl\": pos[\"unrealized_pnl\"],\n")
        new_lines.append("                            \"strategy\": pos[\"strategy\"]\n")
        new_lines.append("                        }\n")
        new_lines.append("                    \n")
        new_lines.append("                    # Calculate equity using current mark prices (not stored outdated value)\n")
        new_lines.append("                    stored_equity = latest_cash_equity[\"total_equity\"]\n")
        new_lines.append("                    current_equity = self._get_total_equity()\n")
        new_lines.append("                    self.portfolio[\"equity\"] = current_equity\n")
        new_lines.append("                    \n")
        new_lines.append("                    # Log the difference between stored and calculated equity\n")
        new_lines.append("                    equity_change = current_equity - stored_equity\n")
        new_lines.append("                    equity_change_pct = (equity_change / stored_equity * 100) if stored_equity > 0 else 0\n")
        new_lines.append("                    \n")
        new_lines.append("                    self.logger.info(f\"Loaded existing portfolio from store: cash=${self.portfolio['cash_balance']:,.2f}, equity=${current_equity:,.2f} (was ${stored_equity:,.2f} stored, {equity_change:+.2f} {equity_change_pct:+.1f}%), positions={len(existing_positions)}\")\n")
        skip_until_line = 208  # Skip until we get to the else clause for the next section
        continue
    
    # Skip lines in the problematic section
    if in_problematic_section and line_num <= skip_until_line:
        continue
    
    # End of problematic section
    if in_problematic_section and line_num > skip_until_line:
        in_problematic_section = False
    
    new_lines.append(line)

# Write the fixed file
with open("/Users/bzliu/Desktop/EXTRANEOUS_CODE/Cryto trader/crypto_mvp/src/crypto_mvp/trading_system.py", "w") as f:
    f.writelines(new_lines)

print("Fixed portfolio loading section in trading_system.py")

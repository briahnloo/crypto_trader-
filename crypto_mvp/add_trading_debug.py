import re

# Read the file
with open('src/crypto_mvp/trading_system.py', 'r') as f:
    content = f.read()

# Add debug logging after get_mark_price call
content = re.sub(
    r'(mark_price = get_mark_price\(\n                    canonical_symbol, \n                    self\.data_engine, \n                    live_mode=self\.config\.get\("trading", \{\}\)\.get\("live_mode", False\)\n                \)\)\n',
    r'\1                \n                # DEBUG: Log what get_mark_price returned\n                self.logger.info(f"EQUITY_DEBUG: {canonical_symbol} - get_mark_price() returned: {mark_price}")\n',
    content
)

# Add debug logging for validation
content = re.sub(
    r'(if mark_price and validate_mark_price\(mark_price, canonical_symbol\):)\n',
    r'\1\n                # DEBUG: Log validation result\n                validation_result = validate_mark_price(mark_price, canonical_symbol)\n                self.logger.info(f"EQUITY_DEBUG: {canonical_symbol} - validate_mark_price({mark_price}) returned: {validation_result}")\n',
    content
)

# Write the modified content back
with open('src/crypto_mvp/trading_system.py', 'w') as f:
    f.write(content)

print("Trading system debug logging added successfully")

import re

# Read the file
with open('src/crypto_mvp/core/utils.py', 'r') as f:
    content = f.read()

# Fix the f-string syntax error by using different quotes
content = re.sub(
    r'logger\.info\(f"MARK_PRICE_DEBUG: \{canonical_symbol\} - Step 2: last=\{ticker_data\.get\("last"\)\}, mark_price=\{mark_price\}, source=\{source_name\}"\)',
    'logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - Step 2: last={ticker_data.get(\'last\')}, mark_price={mark_price}, source={source_name}")',
    content
)

content = re.sub(
    r'logger\.info\(f"MARK_PRICE_DEBUG: \{canonical_symbol\} - Step 3: price=\{ticker_data\.get\("price"\)\}, mark_price=\{mark_price\}, source=\{source_name\}"\)',
    'logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - Step 3: price={ticker_data.get(\'price\')}, mark_price={mark_price}, source={source_name}")',
    content
)

# Write the fixed content back
with open('src/crypto_mvp/core/utils.py', 'w') as f:
    f.write(content)

print("Syntax errors fixed")

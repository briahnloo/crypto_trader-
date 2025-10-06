import re

# Read the file
with open('src/crypto_mvp/core/utils.py', 'r') as f:
    content = f.read()

# Add debug logging after ticker_data retrieval
content = re.sub(
    r'(ticker_data = data_engine\.get_ticker\(canonical_symbol\))\n',
    r'\1\n        \n        # DEBUG: Log ticker data contents\n        logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - ticker_data keys: {list(ticker_data.keys()) if ticker_data else None}")\n        if ticker_data:\n            logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - ticker_data: {ticker_data}")\n        else:\n            logger.warning(f"MARK_PRICE_DEBUG: {canonical_symbol} - ticker_data is None or empty")\n',
    content
)

# Add debug logging for each price extraction step
content = re.sub(
    r'(if bid and ask and bid > 0 and ask > 0:)\n',
    r'\1\n            # DEBUG: Log price extraction attempt\n            logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - Step 1: bid={bid}, ask={ask}, mark_price={mark_price}, source={source_name}")\n',
    content
)

content = re.sub(
    r'(if ticker_data\.get\(\'last\'\) and ticker_data\[\'last\'\] > 0:)\n',
    r'\1\n            # DEBUG: Log price extraction attempt\n            logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - Step 2: last={ticker_data.get(\'last\')}, mark_price={mark_price}, source={source_name}")\n',
    content
)

content = re.sub(
    r'(if ticker_data\.get\(\'price\'\) and ticker_data\[\'price\'\] > 0:)\n',
    r'\1\n            # DEBUG: Log price extraction attempt\n            logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - Step 3: price={ticker_data.get(\'price\')}, mark_price={mark_price}, source={source_name}")\n',
    content
)

# Add debug logging for validation results
content = re.sub(
    r'(if validate_mark_price\(mark_price, canonical_symbol\):)\n',
    r'\1\n                # DEBUG: Log validation result\n                validation_result = validate_mark_price(mark_price, canonical_symbol)\n                logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - validation_result={validation_result} for price={mark_price}")\n',
    content
)

# Add debug logging for final result
content = re.sub(
    r'(return float\(mark_price\))\n',
    r'\1\n                # DEBUG: Log final result\n                logger.info(f"MARK_PRICE_DEBUG: {canonical_symbol} - FINAL RESULT: returning {mark_price} from {source_name}")\n',
    content
)

# Add debug logging for exception
content = re.sub(
    r'(logger\.error\(f"Error getting mark price for \{symbol\}: \{e\}"\))\n',
    r'\1\n        # DEBUG: Log exception details\n        logger.error(f"MARK_PRICE_DEBUG: {canonical_symbol} - EXCEPTION: {type(e).__name__}: {e}")\n',
    content
)

# Write the modified content back
with open('src/crypto_mvp/core/utils.py', 'w') as f:
    f.write(content)

print("Debug logging added successfully")

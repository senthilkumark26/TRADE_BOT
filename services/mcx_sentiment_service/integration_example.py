"""
Integration Example: How to add MCX Sentiment to single_strike_trader.py
This shows where and how to integrate the MCX sentiment service
"""

# IN single_strike_trader.py __init__ method:

# 1. Add import at the top:
# from services.mcx_sentiment_service.service import get_mcx_sentiment_service

# 2. Initialize service in __init__ (after other services):
# self.mcx_sentiment_service = get_mcx_sentiment_service()
# logger.info("MCX Sentiment Service initialized (optional NSE confirmation)")

# 3. Use in trade decision logic (in run_trading_day method):

# Example integration in trade selection:
"""
# Get MCX sentiment for NSE confirmation (optional)
mcx_confirmation = None
if self.mcx_sentiment_service.is_enabled():
    mcx_confirmation = self.mcx_sentiment_service.get_sentiment_for_nse_confirmation(direction)
    
    if mcx_confirmation['recommendation'] == 'REJECT':
        logger.warning(f"MCX sentiment REJECTS trade: {mcx_confirmation['reasoning']}")
        skip_reason = f"MCX sentiment conflict: {mcx_confirmation['reasoning']}"
        trade_taken = False
    elif mcx_confirmation['recommendation'] == 'CONFIRM':
        logger.info(f"MCX sentiment CONFIRMS trade: {mcx_confirmation['reasoning']}")
    else:
        logger.info(f"MCX sentiment NEUTRAL: {mcx_confirmation['reasoning']}")
"""

# 4. Add to decision logging:
"""
print(f"""
MCX Confirmation: {mcx_confirmation}
Decision: {"EXECUTED" if trade_taken else "SKIPPED"}
""")
"""

# 5. To enable/disable dynamically:
# self.mcx_sentiment_service.enable()  # Enable MCX confirmation
# self.mcx_sentiment_service.disable()  # Disable MCX confirmation

# 6. Add to command-line interface (if interactive):
# "enable mcx sentiment" - Enable MCX sentiment confirmation
# "disable mcx sentiment" - Disable MCX sentiment confirmation
# "mcx sentiment status" - Show MCX sentiment status

print("Integration example completed. See comments above for implementation details.")

"""
Simple test script to execute a single trade for testing purposes
"""

import json
import time
import logging
from single_strike_trader import SingleStrikeTrader

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_single_trade():
    """Test single trade execution with forced parameters"""
    logger.info("="*80)
    logger.info("TESTING SINGLE TRADE EXECUTION")
    logger.info("="*80)
    
    # Initialize trader in demo mode
    trader = SingleStrikeTrader(investment_amount=30000, demo_mode=True)
    
    # Force a trade with specific parameters
    symbol = "NIFTY"
    strike = 2400
    direction = "CALL"
    option_price = 150.0  # Fixed price for testing
    
    logger.info(f"Executing test trade: {symbol} {strike} {direction} @ ₹{option_price}")
    
    # Execute the trade
    success = trader.execute_trade(symbol, strike, direction, option_price)
    
    if success:
        logger.info("✅ Trade executed successfully")
        
        # Monitor the trade for a few cycles
        logger.info("Monitoring trade for 3 cycles...")
        for i in range(3):
            logger.info(f"Cycle {i+1}/3")
            should_continue = trader.monitor_trade()
            if not should_continue:
                logger.info("Trade closed during monitoring")
                break
            time.sleep(2)
        
        # Force close the trade for testing
        if trader.trade_active:
            logger.info("Force closing trade for testing...")
            current_price = trader.get_option_price(symbol, strike, direction)
            
            # Fallback: if price not available, use a simulated price for testing
            if current_price is None:
                logger.warning("Could not get current price, using simulated price for testing")
                # Simulate a small profit for testing
                if direction == "CALL":
                    current_price = trader.entry_price + 10  # 10 point profit
                else:
                    current_price = trader.entry_price - 10  # 10 point profit
            
            pnl = current_price - trader.entry_price if direction == "CALL" else trader.entry_price - current_price
            trader.close_trade("TEST_COMPLETE", current_price, pnl)
        
        # Show trade history
        logger.info("="*80)
        logger.info("TRADE HISTORY")
        logger.info("="*80)
        for trade in trader.trade_history:
            logger.info(f"Symbol: {trade['symbol']}")
            logger.info(f"Strike: {trade['strike']}")
            logger.info(f"Direction: {trade['direction']}")
            logger.info(f"Entry: {trade['entry_price']}")
            logger.info(f"Exit: {trade['exit_price']}")
            logger.info(f"P&L: {trade['total_pnl']:+.2f}")
            logger.info(f"Capital: {trade['capital_after']:.2f}")
        
        logger.info("="*80)
        logger.info("TEST COMPLETED SUCCESSFULLY")
        logger.info("="*80)
        
    else:
        logger.error("❌ Trade execution failed")

if __name__ == "__main__":
    test_single_trade()
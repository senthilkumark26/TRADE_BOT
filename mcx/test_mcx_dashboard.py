"""
Quick MCX Dashboard Test
"""

import sys
import logging
from kite.kite_client import KiteClient
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_mcx_dashboard():
    """Test MCX data fetching and dashboard"""
    logger.info("="*80)
    logger.info("MCX DASHBOARD TEST")
    logger.info("="*80)
    
    try:
        # Load config
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        api_key = config.get('api_key')
        access_token = config.get('access_token')
        
        # Initialize Kite Client
        logger.info("Initializing Kite Client...")
        kite_client = KiteClient(api_key=api_key, access_token=access_token, paper_trading=True)
        
        # Get CRUDEOIL MINI contract
        logger.info("\nGetting CRUDEOIL MINI contract...")
        contract = kite_client.get_nearest_mcx_contract("CRUDEOILM")
        
        if not contract:
            logger.error("No CRUDEOIL contract found")
            return False
        
        logger.info(f"Contract: {contract['tradingsymbol']}")
        logger.info(f"Token: {contract['instrument_token']}")
        logger.info(f"Expiry: {contract.get('expiry', 'N/A')}")
        
        # Get quote
        logger.info("\nFetching quote...")
        token = contract['instrument_token']
        quote = kite_client.kite.quote([token])  # Try without MCX prefix
        
        if not quote or str(token) not in quote:
            logger.error("No quote data received")
            return False
        
        data = quote[str(token)]
        price = data.get('last_price', 0)
        oi = data.get('oi', 0)
        volume = data.get('volume', 0)
        
        logger.info(f"Price: {price}")
        logger.info(f"OI: {oi}")
        logger.info(f"Volume: {volume}")
        
        # Print MCX dashboard
        print(f"""
================================================================================
 MCX LIVE - CRUDEOIL MINI
================================================================================
 Price    : {price:<10.2f}    OI       : {oi:<15.0f}
 Volume   : {volume:<10.0f}    Trend    : {"BULLISH" if oi > 0 else "BEARISH":<15}
================================================================================
 Opening Range (First 5 Min)
 High     : 0.00        Low      : 0.00
================================================================================
 Trading Signals
 BUY  Signal  : NO
 SELL Signal  : NO
================================================================================
 Risk Management
 Stop Loss  : 15 points     Target   : 30-50 points
================================================================================
""")
        
        logger.info("\nMCX Dashboard Test Completed")
        return True
        
    except Exception as e:
        logger.error(f"MCX Dashboard Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_mcx_dashboard()
    sys.exit(0 if success else 1)

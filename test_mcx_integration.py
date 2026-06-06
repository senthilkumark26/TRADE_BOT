"""
MCX Integration Test Script
Tests MCX instrument loading and contract selection
"""

import sys
import logging
from kiteconnect import KiteConnect
from kite_client import KiteClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_mcx_integration():
    """Test MCX integration"""
    logger.info("="*80)
    logger.info("MCX INTEGRATION TEST")
    logger.info("="*80)
    
    try:
        # Load config
        import json
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        api_key = config.get('api_key')
        access_token = config.get('access_token')
        
        # Initialize Kite Client
        logger.info("Initializing Kite Client...")
        kite_client = KiteClient(api_key=api_key, access_token=access_token, paper_trading=True)
        
        # Test 1: Load MCX instruments
        logger.info("\n" + "="*80)
        logger.info("TEST 1: Load MCX Instruments")
        logger.info("="*80)
        
        mcx_instruments = kite_client.load_instruments_optimized("MCX")
        logger.info(f"Loaded {len(mcx_instruments)} MCX symbols")
        
        if mcx_instruments:
            logger.info("MCX Symbols found:")
            for symbol in list(mcx_instruments.keys())[:10]:  # Show first 10
                logger.info(f"  - {symbol}")
        
        # Test 2: Get MCX contracts for CRUDEOIL
        logger.info("\n" + "="*80)
        logger.info("TEST 2: Get MCX Contracts for CRUDEOIL")
        logger.info("="*80)
        
        crude_contracts = kite_client.get_mcx_contracts("CRUDEOIL")
        logger.info(f"Found {len(crude_contracts)} CRUDEOIL contracts")
        
        if crude_contracts:
            logger.info("CRUDEOIL Contracts:")
            for contract in crude_contracts[:5]:  # Show first 5
                logger.info(f"  - {contract['tradingsymbol']} (Expiry: {contract.get('expiry', 'N/A')})")
        
        # Test 3: Get nearest MCX contract
        logger.info("\n" + "="*80)
        logger.info("TEST 3: Get Nearest MCX Contract")
        logger.info("="*80)
        
        nearest_contract = kite_client.get_nearest_mcx_contract("CRUDEOIL")
        
        if nearest_contract:
            logger.info("Nearest Contract Details:")
            logger.info(f"  Symbol: {nearest_contract['name']}")
            logger.info(f"  Trading Symbol: {nearest_contract['tradingsymbol']}")
            logger.info(f"  Instrument Token: {nearest_contract['instrument_token']}")
            logger.info(f"  Expiry: {nearest_contract.get('expiry', 'N/A')}")
            logger.info(f"  Lot Size: {nearest_contract.get('lot_size', 'N/A')}")
            logger.info(f"  Tick Size: {nearest_contract.get('tick_size', 'N/A')}")
            logger.info(f"  Exchange: {nearest_contract['exchange']}")
        else:
            logger.warning("No nearest contract found")
        
        # Test 4: Get MCX contracts for NATGAS
        logger.info("\n" + "="*80)
        logger.info("TEST 4: Get MCX Contracts for NATGAS")
        logger.info("="*80)
        
        natgas_contracts = kite_client.get_mcx_contracts("NATURALGAS")
        logger.info(f"Found {len(natgas_contracts)} NATURALGAS contracts")
        
        if natgas_contracts:
            logger.info("NATURALGAS Contracts:")
            for contract in natgas_contracts[:5]:  # Show first 5
                logger.info(f"  - {contract['tradingsymbol']} (Expiry: {contract.get('expiry', 'N/A')})")
        
        # Test 5: Get nearest NATGAS contract
        logger.info("\n" + "="*80)
        logger.info("TEST 5: Get Nearest NATGAS Contract")
        logger.info("="*80)
        
        nearest_natgas = kite_client.get_nearest_mcx_contract("NATURALGAS")
        
        if nearest_natgas:
            logger.info("Nearest NATGAS Contract Details:")
            logger.info(f"  Symbol: {nearest_natgas['name']}")
            logger.info(f"  Trading Symbol: {nearest_natgas['tradingsymbol']}")
            logger.info(f"  Instrument Token: {nearest_natgas['instrument_token']}")
            logger.info(f"  Expiry: {nearest_natgas.get('expiry', 'N/A')}")
            logger.info(f"  Lot Size: {nearest_natgas.get('lot_size', 'N/A')}")
            logger.info(f"  Tick Size: {nearest_natgas.get('tick_size', 'N/A')}")
            logger.info(f"  Exchange: {nearest_natgas['exchange']}")
        else:
            logger.warning("No nearest NATGAS contract found")
        
        logger.info("\n" + "="*80)
        logger.info("MCX INTEGRATION TEST COMPLETED")
        logger.info("="*80)
        
        return True
        
    except Exception as e:
        logger.error(f"MCX Integration Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_mcx_integration()
    sys.exit(0 if success else 1)

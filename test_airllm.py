"""
Test script for AirLLM integration
"""
import sys
import logging
from airllm_integration import AirLLMIntegration

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_airllm_basic():
    """Test basic AirLLM functionality"""
    logger.info("Testing AirLLM integration...")
    
    try:
        # Initialize AirLLM with the model from documentation
        # Using the exact model from AirLLM docs
        logger.info("Initializing AirLLM with test model...")
        
        airllm = AirLLMIntegration(
            model_path="garage-bAInd/Platypus2-70B-instruct",  # From AirLLM docs
            compression="4bit",  # Enable compression for speed
            max_length=128,
            fast_mode=True
        )
        
        # Test simple generation
        logger.info("Testing simple text generation...")
        test_prompt = "What is 2+2? Answer with just the number."
        
        response = airllm.generate(
            prompt=test_prompt,
            max_new_tokens=10,
            timeout=60.0
        )
        
        if response:
            logger.info(f"✓ Generation successful: {response}")
        else:
            logger.error("✗ Generation failed")
            return False
        
        # Test trading data analysis
        logger.info("Testing trading data analysis...")
        test_market_data = {
            "direction": "CALL",
            "strike": 22000,
            "entry": 150.5,
            "target": 180.0,
            "stoploss": 130.0,
            "spot": 21950,
            "vwap": 21900,
            "support": 21800,
            "resistance": 22100,
            "optionstar_reason": "Strong bullish momentum with OI buildup",
            "symbol": "BANKNIFTY"
        }
        
        analysis = airllm.analyze_trading_data(test_market_data, "entry")
        
        if analysis:
            logger.info(f"✓ Trading analysis successful: {analysis}")
        else:
            logger.error("✗ Trading analysis failed")
            return False
        
        logger.info("✓ All AirLLM tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"✗ AirLLM test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if 'airllm' in locals():
            airllm.cleanup()

def test_airllm_with_config():
    """Test AirLLM with configuration from config.json"""
    logger.info("Testing AirLLM with config.json settings...")
    
    try:
        import json
        
        # Load config
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        airllm_config = config.get("airllm", {})
        
        if not airllm_config.get("enabled", False):
            logger.warning("AirLLM is disabled in config.json")
            return True
        
        # Initialize with config settings
        airllm = AirLLMIntegration(
            model_path=airllm_config.get("model_path", "garage-bAInd/Platypus2-70B-instruct"),
            compression=airllm_config.get("compression"),
            max_length=airllm_config.get("max_length", 128),
            fast_mode=airllm_config.get("fast_mode", True),
            layer_shards_saving_path=airllm_config.get("layer_shards_saving_path"),
            hf_token=airllm_config.get("hf_token")
        )
        
        logger.info("✓ AirLLM initialized with config settings")
        return True
        
    except Exception as e:
        logger.error(f"✗ Config test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting AirLLM integration tests...")
    
    # Test 1: Basic functionality
    test1_passed = test_airllm_basic()
    
    # Test 2: Config integration
    test2_passed = test_airllm_with_config()
    
    if test1_passed and test2_passed:
        logger.info("✓ All tests passed!")
        sys.exit(0)
    else:
        logger.error("✗ Some tests failed")
        sys.exit(1)
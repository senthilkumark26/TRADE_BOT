"""
AirLLM Performance Test - Measure response time for trading decisions
"""
import time
import logging
from airllm_integration import AirLLMIntegration

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_airllm_response_time():
    """Test AirLLM response time for trading decisions"""
    logger.info("Testing AirLLM Response Time for Trading Decisions")
    logger.info("=" * 80)
    
    try:
        # Initialize AirLLM with phi-2 model
        logger.info("Initializing AirLLM with microsoft/phi-2...")
        airllm = AirLLMIntegration(
            model_path="microsoft/phi-2",
            compression=None,
            max_length=128,
            fast_mode=True
        )
        
        # Test 1: Model Loading Time
        logger.info("\n" + "=" * 80)
        logger.info("TEST 1: Model Loading Time")
        logger.info("=" * 80)
        
        start_time = time.time()
        logger.info("Loading model (this includes download if first time)...")
        # Force model load by calling a simple generation
        test_load = airllm.generate("test", max_new_tokens=1, timeout=300)
        load_time = time.time() - start_time
        logger.info(f"✓ Model loaded in {load_time:.2f} seconds")
        
        # Test 2: Simple Question Response Time
        logger.info("\n" + "=" * 80)
        logger.info("TEST 2: Simple Question Response Time")
        logger.info("=" * 80)
        
        simple_questions = [
            "What is 2+2?",
            "What is the capital of France?",
            "Yes or no: Is the sky blue?"
        ]
        
        simple_times = []
        for i, question in enumerate(simple_questions, 1):
            start_time = time.time()
            response = airllm.generate(question, max_new_tokens=10, timeout=60)
            elapsed = time.time() - start_time
            simple_times.append(elapsed)
            logger.info(f"Q{i}: {question}")
            logger.info(f"Response: {response[:50] if response else 'No response'}...")
            logger.info(f"Time: {elapsed:.2f}s")
        
        avg_simple = sum(simple_times) / len(simple_times)
        logger.info(f"Average simple response time: {avg_simple:.2f}s")
        
        # Test 3: Trading Decision Response Time
        logger.info("\n" + "=" * 80)
        logger.info("TEST 3: Trading Decision Response Time")
        logger.info("=" * 80)
        
        trading_data = {
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
        
        trading_times = []
        for i in range(3):
            start_time = time.time()
            analysis = airllm.analyze_trading_data(trading_data, "entry")
            elapsed = time.time() - start_time
            trading_times.append(elapsed)
            
            if analysis:
                logger.info(f"Trade {i+1}: Decision={analysis.get('decision')}, Signal={analysis.get('signal')}")
            else:
                logger.info(f"Trade {i+1}: No analysis returned")
            
            logger.info(f"Time: {elapsed:.2f}s")
        
        avg_trading = sum(trading_times) / len(trading_times)
        logger.info(f"Average trading decision time: {avg_trading:.2f}s")
        
        # Test 4: Fast Mode vs Normal Mode
        logger.info("\n" + "=" * 80)
        logger.info("TEST 4: Fast Mode vs Normal Mode")
        logger.info("=" * 80)
        
        # Test with fast mode
        airllm_fast = AirLLMIntegration(
            model_path="microsoft/phi-2",
            compression=None,
            max_length=128,
            fast_mode=True
        )
        
        start_time = time.time()
        fast_response = airllm_fast.generate("What is 2+2?", max_new_tokens=5, timeout=60)
        fast_time = time.time() - start_time
        logger.info(f"Fast mode time: {fast_time:.2f}s")
        
        # Test with normal mode
        airllm_normal = AirLLMIntegration(
            model_path="microsoft/phi-2",
            compression=None,
            max_length=128,
            fast_mode=False
        )
        
        start_time = time.time()
        normal_response = airllm_normal.generate("What is 2+2?", max_new_tokens=20, timeout=60)
        normal_time = time.time() - start_time
        logger.info(f"Normal mode time: {normal_time:.2f}s")
        logger.info(f"Speed improvement: {(normal_time/fast_time):.2f}x")
        
        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("PERFORMANCE SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Model Load Time: {load_time:.2f}s")
        logger.info(f"Simple Questions Avg: {avg_simple:.2f}s")
        logger.info(f"Trading Decisions Avg: {avg_trading:.2f}s")
        logger.info(f"Fast Mode: {fast_time:.2f}s")
        logger.info(f"Normal Mode: {normal_time:.2f}s")
        
        # Trading suitability assessment
        logger.info("\n" + "=" * 80)
        logger.info("TRADING SUITABILITY ASSESSMENT")
        logger.info("=" * 80)
        
        if avg_trading < 5.0:
            logger.info("✅ EXCELLENT: Very fast for real-time trading")
        elif avg_trading < 10.0:
            logger.info("✅ GOOD: Suitable for real-time trading")
        elif avg_trading < 30.0:
            logger.info("⚠️ MODERATE: May be slow for high-frequency trading")
        else:
            logger.info("❌ SLOW: Not suitable for real-time trading")
        
        logger.info(f"\nRecommendation: AirLLM with phi-2 is {'SUITABLE' if avg_trading < 10.0 else 'MAY BE SLOW'} for your trading bot")
        
        # Cleanup
        airllm.cleanup()
        airllm_fast.cleanup()
        airllm_normal.cleanup()
        
        return True
        
    except Exception as e:
        logger.error(f"Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_airllm_response_time()
    if success:
        logger.info("\n✅ AirLLM performance test completed successfully")
    else:
        logger.error("\n❌ AirLLM performance test failed")
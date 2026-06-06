"""
Simple AirLLM import test
"""
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_airllm_import():
    """Test if AirLLM can be imported"""
    try:
        import airllm
        logger.info("✓ AirLLM imported successfully")
        logger.info(f"AirLLM version: {airllm.__version__ if hasattr(airllm, '__version__') else 'unknown'}")
        return True
    except ImportError as e:
        logger.error(f"✗ Failed to import AirLLM: {e}")
        return False

def test_torch_import():
    """Test if PyTorch can be imported"""
    try:
        import torch
        logger.info("✓ PyTorch imported successfully")
        logger.info(f"PyTorch version: {torch.__version__}")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")
        return True
    except ImportError as e:
        logger.error(f"✗ Failed to import PyTorch: {e}")
        return False

def test_transformers_import():
    """Test if transformers can be imported"""
    try:
        import transformers
        logger.info("✓ Transformers imported successfully")
        logger.info(f"Transformers version: {transformers.__version__}")
        return True
    except ImportError as e:
        logger.error(f"✗ Failed to import transformers: {e}")
        return False

if __name__ == "__main__":
    logger.info("Testing AirLLM dependencies...")
    
    torch_ok = test_torch_import()
    transformers_ok = test_transformers_import()
    airllm_ok = test_airllm_import()
    
    if torch_ok and transformers_ok and airllm_ok:
        logger.info("✓ All dependencies installed correctly")
        logger.info("Note: Windows PyTorch may have shared memory issues")
        logger.info("Consider using CPU-only mode or fixing PyTorch installation")
        sys.exit(0)
    else:
        logger.error("✗ Some dependencies are missing or broken")
        sys.exit(1)
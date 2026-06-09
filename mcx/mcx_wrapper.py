"""
MCX Signal Wrapper - Clean interface for MCX Signal Engine
This provides a simple interface to get MCX-specific signals
"""

import json
import logging

logger = logging.getLogger(__name__)

# Global MCX engine instance (lazy loaded)
mcx_engine = None
mcx_disabled = False

def load_config():
    """Load config to check MCX enabled status"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return None

def disable_mcx_service():
    """Disable MCX service"""
    global mcx_disabled
    mcx_disabled = True
    logger.info("MCX Service disabled (mcx_enabled=false in config)")

def initialize_mcx_engine():
    """Initialize MCX Signal Engine only if enabled"""
    global mcx_engine, mcx_disabled
    
    # Check if MCX is disabled in config
    config = load_config()
    if config and not config.get("mcx_enabled", True):
        disable_mcx_service()
        return None
    
    # Initialize MCX Signal Engine
    try:
        from mcx.services.service import get_mcx_signal_engine
        mcx_engine = get_mcx_signal_engine()
        logger.info("MCX Signal Engine initialized")
        return mcx_engine
    except Exception as e:
        logger.error(f"Error initializing MCX Signal Engine: {e}")
        disable_mcx_service()
        return None

def get_mcx_signal(symbol: str, price: float, oi: float = 0, volume: float = 0):
    """
    Get MCX-specific trading signal
    
    This is additional intelligence that works alongside your main system.
    It does NOT replace MarketAnalyzer, Consensus, or LLM.
    
    Args:
        symbol: Commodity symbol (e.g., "CRUDEOILM", "NATURALGAS")
        price: Current price
        oi: Open interest (optional)
        volume: Trading volume (optional)
        
    Returns:
        MCX signal dictionary with:
        - signal: "LONG", "SHORT", or "NEUTRAL"
        - confidence: 0.0 to 1.0
        - reasoning: List of reasons
        - mcx_specific: Commodity-specific analysis
        Returns None if MCX service is disabled
    """
    global mcx_engine
    
    # Check if MCX is disabled
    if mcx_disabled:
        logger.debug("MCX service disabled, returning None")
        return None
    
    # Lazy initialize MCX engine
    if mcx_engine is None:
        mcx_engine = initialize_mcx_engine()
        if mcx_engine is None:
            return None
    
    return mcx_engine.generate_mcx_signal(symbol, price, oi, volume)

def get_mcx_commodity_profile(symbol: str):
    """
    Get commodity-specific profile
    
    Args:
        symbol: Commodity symbol
        
    Returns:
        Commodity profile with volatility, key levels, etc.
        Returns None if MCX service is disabled
    """
    global mcx_engine
    
    # Check if MCX is disabled
    if mcx_disabled:
        logger.debug("MCX service disabled, returning None")
        return None
    
    # Lazy initialize MCX engine
    if mcx_engine is None:
        mcx_engine = initialize_mcx_engine()
        if mcx_engine is None:
            return None
    
    return mcx_engine.get_commodity_profile(symbol)

def get_mcx_support_resistance(symbol: str, current_price: float):
    """
    Get MCX support/resistance using HYBRID approach:
    - PRIMARY: Price-based dynamic levels (swing low/high)
    - SECONDARY: Psychological levels (round numbers + key_levels)
    - FINAL: Confidence scoring based on alignment
    
    Args:
        symbol: Commodity symbol
        current_price: Current price
        
    Returns:
        MCX support/resistance dictionary with strength and confidence
        Returns None if MCX service is disabled
    """
    global mcx_engine
    
    # Check if MCX is disabled
    if mcx_disabled:
        logger.debug("MCX service disabled, returning None")
        return None
    
    # Lazy initialize MCX engine
    if mcx_engine is None:
        mcx_engine = initialize_mcx_engine()
        if mcx_engine is None:
            return None
    
    # Update price history before calculating S/R
    mcx_engine.update_price_history(symbol, current_price)
    
    # Calculate support/resistance
    return mcx_engine.calculate_mcx_support_resistance(symbol, current_price)
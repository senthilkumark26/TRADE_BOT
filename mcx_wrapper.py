"""
MCX Signal Wrapper - Clean interface for MCX Signal Engine
This provides a simple interface to get MCX-specific signals
"""

from services.mcx_signal_engine import get_mcx_signal_engine

# Initialize MCX Signal Engine
mcx_engine = get_mcx_signal_engine()

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
    """
    return mcx_engine.generate_mcx_signal(symbol, price, oi, volume)

def get_mcx_commodity_profile(symbol: str):
    """
    Get commodity-specific profile
    
    Args:
        symbol: Commodity symbol
        
    Returns:
        Commodity profile with volatility, key levels, etc.
    """
    return mcx_engine.get_commodity_profile(symbol)
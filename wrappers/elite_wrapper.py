"""
Elite Strike Wrapper - Non-intrusive integration layer
Wraps Elite Strike Service for clean integration without modifying core logic
"""

from services.elite_strike_service import EliteStrikeService

# Initialize Elite Strike Service
elite = EliteStrikeService()


def get_elite_strike(symbol: str, decision: dict, spot: float, ranked_strikes: list) -> dict:
    """
    Get elite-optimized strike without modifying original decision.
    
    Args:
        symbol: Trading symbol
        decision: Execution brain decision dictionary
        spot: Current spot price
        ranked_strikes: List of ranked strikes from Strike Selector
        
    Returns:
        Enhanced decision with optimized strike and lot size
    """
    # Only optimize for EXECUTE or PROBING actions
    if decision.get("action") not in ["EXECUTE", "PROBING"]:
        return decision
    
    try:
        # Extract required fields
        signal = decision.get("direction") or decision.get("signal")
        strike = decision.get("strike")
        score = decision.get("score", 0)
        
        if not signal or not strike:
            logger.warning(f"[ELITE WRAPPER] Missing signal or strike in decision")
            return decision
        
        # Format strike for optimization
        if isinstance(strike, (int, float)):
            strike_str = f"{int(strike)} {'CE' if signal == 'CALL' else 'PE'}"
        else:
            strike_str = str(strike)
        
        # Optimize using Elite Strike Service
        optimized = elite.optimize(
            symbol=symbol,
            signal=signal,
            strike=strike_str,
            spot=spot,
            ranked_strikes=ranked_strikes,
            score=score
        )
        
        # DO NOT MODIFY ORIGINAL — JUST ENHANCE
        # Store original for reference
        decision["original_strike"] = decision.get("strike")
        decision["original_lot_size"] = decision.get("lot_size", 1)
        
        # Apply optimizations
        decision["strike"] = optimized["strike"]
        decision["lot_size"] = optimized["lot"]
        
        # Add metadata
        decision["elite_optimized"] = True
        decision["gamma_preferred"] = optimized.get("gamma_preferred")
        decision["strike_adjusted"] = optimized.get("adjusted", False)
        
        logger.info(f"[ELITE WRAPPER] {symbol} - Strike optimized: {decision['original_strike']} -> {decision['strike']}, Lot: {decision['lot_size']}")
        
        return decision
        
    except Exception as e:
        logger.error(f"[ELITE WRAPPER] Error optimizing strike: {e}")
        return decision


def start_elite_service():
    """Start the Elite Strike Service"""
    elite.start()
    logger.info("Elite Strike Service started via wrapper")


def stop_elite_service():
    """Stop the Elite Strike Service"""
    elite.stop()
    logger.info("Elite Strike Service stopped via wrapper")


def get_elite_statistics():
    """Get Elite Strike Service statistics"""
    return elite.get_statistics()

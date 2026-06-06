"""
Breakout Entry Service - Microservice for breakout detection and entry timing
Handles: Breakout detection, strength classification, entry timing, strike selection
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class BreakoutEntryService:
    """
    Breakout Entry Timing Service - Standalone microservice for entry optimization.
    Handles: Breakout detection, strength classification, entry timing, strike selection.
    
    This service is decoupled from Engine1 to allow independent updates and testing.
    """
    
    def __init__(self):
        """Initialize the Breakout Entry Service"""
        self.prev_breakout = {}  # symbol -> previous breakout state
        self.service_name = "breakout_entry_service"
        self.version = "1.0.0"
        self.dependencies = []  # No dependencies
        self.dependents = ["engine1_market_analyzer", "trading_bot", "market_analyzer"]
        self.protection_level = "CRITICAL"
        
        logger.info(f"Breakout Entry Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
    
    def confirm_breakout(self, symbol: str, breakout: str) -> str:
        """
        2-tick confirmation for moderate breakouts.
        Returns: Confirmed breakout or "NONE"
        
        Args:
            symbol: Trading symbol
            breakout: Current breakout direction (BULLISH/BEARISH/NONE)
            
        Returns:
            Confirmed breakout direction or "NONE"
        """
        if symbol not in self.prev_breakout:
            self.prev_breakout[symbol] = breakout
            return "NONE"
        
        if breakout != "NONE" and breakout == self.prev_breakout[symbol]:
            return breakout
        
        self.prev_breakout[symbol] = breakout
        return "NONE"
    
    def get_entry(self, symbol: str, breakout: str, strength: str, spot: float, vwap: float) -> Dict:
        """
        Entry decision based on breakout strength.
        Returns: Entry decision dict with signal, entry_type, strike
        
        Args:
            symbol: Trading symbol
            breakout: Breakout direction (BULLISH/BEARISH/NONE)
            strength: Breakout strength (STRONG/MODERATE/WEAK)
            spot: Current spot price
            vwap: Current VWAP
            
        Returns:
            Dictionary with signal, entry_type, and strike
        """
        # No breakout
        if breakout == "NONE":
            return {"signal": "NO TRADE", "entry_type": None, "strike": None}
        
        # STRONG BREAKOUT → EARLY ENTRY
        if strength == "STRONG":
            if breakout == "BULLISH":
                return {
                    "signal": "BUY CE",
                    "entry_type": "EARLY",
                    "strike": "OTM"
                }
            elif breakout == "BEARISH":
                return {
                    "signal": "BUY PE",
                    "entry_type": "EARLY",
                    "strike": "OTM"
                }
        
        # MODERATE BREAKOUT → CONFIRMED ENTRY
        if strength == "MODERATE":
            confirmed = self.confirm_breakout(symbol, breakout)
            
            if confirmed == "NONE":
                return {"signal": "WAIT", "entry_type": None, "strike": None}
            
            if confirmed == "BULLISH":
                return {
                    "signal": "BUY CE",
                    "entry_type": "CONFIRMED",
                    "strike": "ATM"
                }
            elif confirmed == "BEARISH":
                return {
                    "signal": "BUY PE",
                    "entry_type": "CONFIRMED",
                    "strike": "ATM"
                }
        
        # WEAK BREAKOUT → NO TRADE
        return {"signal": "NO TRADE", "entry_type": None, "strike": None}
    
    def get_service_info(self) -> Dict:
        """
        Get service information for service discovery.
        
        Returns:
            Dictionary with service metadata
        """
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "breakout_detection",
                "strength_classification", 
                "entry_timing",
                "strike_selection",
                "confirmation_logic"
            ]
        }

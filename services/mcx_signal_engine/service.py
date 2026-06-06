"""
MCX Signal Engine - Commodity-specific signal generation
---------------------------------------------------
This is a separate service that provides MCX-specific intelligence.
It does NOT replace existing services - it enhances them.

MCX-specific behavior:
- Faster price movements
- Different volatility patterns
- Commodity-specific technical analysis
- Oil/gas specific seasonality
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MCXSignalEngine:
    """
    MCX Signal Engine - Commodity-specific signal generation
    
    This service provides MCX-specific intelligence that works alongside
    the existing unified system (MarketAnalyzer, Consensus, LLM).
    
    It does NOT replace existing services - it enhances them.
    """
    
    def __init__(self):
        """Initialize MCX Signal Engine"""
        self.service_name = "mcx_signal_engine"
        self.version = "1.0.0"
        self.dependencies = []  # Independent service
        self.dependents = ["unified_trader"]
        self.protection_level = "STANDARD"
        
        # MCX-specific parameters
        self.commodity_profiles = {
            "CRUDEOIL": {
                "volatility_factor": 1.5,  # Higher volatility
                "trend_persistence": 0.7,  # Trends persist longer
                "session_hours": (9, 23),  # Extended hours
                "optimal_timeframes": ["5min", "15min"],
                "key_levels": [100, 105, 110, 115, 120]  # Psychological levels
            },
            "CRUDEOILM": {
                "volatility_factor": 1.6,  # Even higher volatility (mini)
                "trend_persistence": 0.65,
                "session_hours": (9, 23),
                "optimal_timeframes": ["5min", "15min"],
                "key_levels": [50, 52.5, 55, 57.5, 60]
            },
            "NATURALGAS": {
                "volatility_factor": 2.0,  # Very high volatility
                "trend_persistence": 0.5,  # Less persistent trends
                "session_hours": (9, 23),
                "optimal_timeframes": ["5min", "15min"],
                "key_levels": [200, 220, 240, 260, 280]
            },
            "GOLD": {
                "volatility_factor": 0.8,  # Lower volatility (safe haven)
                "trend_persistence": 0.8,  # Very persistent trends
                "session_hours": (9, 23),
                "optimal_timeframes": ["15min", "30min"],
                "key_levels": [60000, 61000, 62000, 63000, 64000]
            },
            "SILVER": {
                "volatility_factor": 1.2,  # Moderate volatility
                "trend_persistence": 0.75,
                "session_hours": (9, 23),
                "optimal_timeframes": ["15min", "30min"],
                "key_levels": [70000, 72000, 74000, 76000, 78000]
            }
        }
        
        # Price history for technical analysis
        self.price_history = {}  # symbol -> list of recent prices
        self.history_window = 20  # Keep last 20 price points
        
        logger.info(f"MCX Signal Engine initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"Supported Commodities: {list(self.commodity_profiles.keys())}")
    
    def get_commodity_profile(self, symbol: str) -> Dict:
        """
        Get commodity-specific profile
        
        Args:
            symbol: Commodity symbol
            
        Returns:
            Commodity profile dictionary
        """
        # Normalize symbol name (remove trailing 'M' only)
        normalized = symbol.upper()
        if normalized.endswith("M"):
            normalized = normalized[:-1]  # CRUDEOILM -> CRUDEOIL
        return self.commodity_profiles.get(normalized, self.commodity_profiles.get("CRUDEOIL", {}))
    
    def update_price_history(self, symbol: str, price: float):
        """
        Update price history for technical analysis
        
        Args:
            symbol: Commodity symbol
            price: Current price
        """
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        
        self.price_history[symbol].append(price)
        
        # Keep only recent history
        if len(self.price_history[symbol]) > self.history_window:
            self.price_history[symbol] = self.price_history[symbol][-self.history_window:]
    
    def calculate_momentum(self, symbol: str) -> float:
        """
        Calculate price momentum (rate of change)
        
        Args:
            symbol: Commodity symbol
            
        Returns:
            Momentum score (-1 to 1)
        """
        if symbol not in self.price_history or len(self.price_history[symbol]) < 5:
            return 0.0
        
        prices = self.price_history[symbol]
        recent = prices[-1]
        previous = prices[-5]
        
        if previous == 0:
            return 0.0
        
        momentum = (recent - previous) / previous
        return max(min(momentum, 1.0), -1.0)  # Clamp between -1 and 1
    
    def calculate_volatility(self, symbol: str) -> float:
        """
        Calculate recent volatility
        
        Args:
            symbol: Commodity symbol
            
        Returns:
            Volatility score
        """
        if symbol not in self.price_history or len(self.price_history[symbol]) < 5:
            return 0.0
        
        prices = self.price_history[symbol]
        returns = []
        
        for i in range(1, len(prices)):
            if prices[i-1] != 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(abs(ret))
        
        if not returns:
            return 0.0
        
        return sum(returns) / len(returns)
    
    def check_key_levels(self, symbol: str, price: float) -> Dict:
        """
        Check if price is near key psychological levels
        
        Args:
            symbol: Commodity symbol
            price: Current price
            
        Returns:
            Key level analysis
        """
        profile = self.get_commodity_profile(symbol)
        key_levels = profile.get("key_levels", [])
        
        nearest_level = None
        distance_to_level = float('inf')
        
        for level in key_levels:
            distance = abs(price - level)
            if distance < distance_to_level:
                distance_to_level = distance
                nearest_level = level
        
        # Consider within 2% as "near"
        is_near_level = (distance_to_level / price) < 0.02 if price > 0 else False
        
        return {
            "nearest_level": nearest_level,
            "distance_to_level": distance_to_level,
            "is_near_level": is_near_level,
            "support": nearest_level if price > nearest_level else None,
            "resistance": nearest_level if price < nearest_level else None
        }
    
    def generate_mcx_signal(self, symbol: str, price: float, oi: float, 
                          volume: float) -> Dict:
        """
        Generate MCX-specific trading signal
        
        This is NOT a replacement for your main system - it's additional
        intelligence that works alongside MarketAnalyzer, Consensus, and LLM.
        
        Args:
            symbol: Commodity symbol
            price: Current price
            oi: Open interest
            volume: Trading volume
            
        Returns:
            MCX signal dictionary with confidence and reasoning
        """
        try:
            # Update price history
            self.update_price_history(symbol, price)
            
            # Get commodity profile
            profile = self.get_commodity_profile(symbol)
            volatility_factor = profile.get("volatility_factor", 1.0)
            
            # Calculate MCX-specific indicators
            momentum = self.calculate_momentum(symbol)
            volatility = self.calculate_volatility(symbol)
            key_levels = self.check_key_levels(symbol, price)
            
            # Volume analysis (commodities are volume-sensitive)
            volume_signal = "HIGH" if volume > 10000 else "NORMAL"
            
            # OI analysis (commodities have different OI behavior)
            oi_signal = "BUILDUP" if oi > 0 else "NEUTRAL"
            
            # Generate signal based on MCX-specific logic
            signal_strength = 0
            signal_direction = "NEUTRAL"
            reasoning = []
            
            # Momentum signal
            if momentum > 0.02:  # Strong upward momentum
                signal_strength += 2
                signal_direction = "LONG"
                reasoning.append(f"Strong upward momentum ({momentum:.3f})")
            elif momentum < -0.02:  # Strong downward momentum
                signal_strength += 2
                signal_direction = "SHORT"
                reasoning.append(f"Strong downward momentum ({momentum:.3f})")
            
            # Volatility adjustment
            if volatility > 0.01 * volatility_factor:
                signal_strength -= 1  # Reduce signal in high volatility
                reasoning.append(f"High volatility detected ({volatility:.3f})")
            
            # Key level proximity
            if key_levels["is_near_level"]:
                signal_strength += 1
                if key_levels["support"]:
                    reasoning.append(f"Near support at {key_levels['support']}")
                elif key_levels["resistance"]:
                    reasoning.append(f"Near resistance at {key_levels['resistance']}")
            
            # Volume confirmation
            if volume_signal == "HIGH":
                signal_strength += 1
                reasoning.append("High volume confirms move")
            
            # OI confirmation
            if oi_signal == "BUILDUP":
                signal_strength += 1
                reasoning.append("OI buildup supports trend")
            
            # Normalize signal strength
            max_strength = 5
            confidence = min(signal_strength / max_strength, 1.0)
            
            # Final signal
            if confidence < 0.3:
                final_signal = "NEUTRAL"
            elif signal_direction == "LONG":
                final_signal = "LONG"
            elif signal_direction == "SHORT":
                final_signal = "SHORT"
            else:
                final_signal = "NEUTRAL"
            
            result = {
                "signal": final_signal,
                "confidence": confidence,
                "direction": signal_direction,
                "reasoning": reasoning,
                "mcx_specific": {
                    "momentum": momentum,
                    "volatility": volatility,
                    "key_levels": key_levels,
                    "volume_signal": volume_signal,
                    "oi_signal": oi_signal,
                    "commodity_profile": profile.get("volatility_factor", 1.0)
                },
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"MCX Signal Generated: {symbol} | {final_signal} | Confidence: {confidence:.2f}")
            logger.info(f"Reasoning: {reasoning}")
            
            return result
        
        except Exception as e:
            logger.error(f"Error generating MCX signal: {e}")
            return {
                "signal": "NEUTRAL",
                "confidence": 0.0,
                "error": str(e)
            }


# Global service instance
_mcx_signal_engine = None

def get_mcx_signal_engine() -> MCXSignalEngine:
    """
    Get the global MCX Signal Engine instance
    
    Returns:
        MCXSignalEngine instance
    """
    global _mcx_signal_engine
    if _mcx_signal_engine is None:
        _mcx_signal_engine = MCXSignalEngine()
    return _mcx_signal_engine
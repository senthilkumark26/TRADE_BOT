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
        self.version = "2.0.0"  # Updated for hybrid S/R support
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
            "GOLDM": {
                "volatility_factor": 1.0,  # Medium volatility (mini)
                "trend_persistence": 0.75,
                "session_hours": (9, 23),
                "optimal_timeframes": ["5min", "15min"],
                "key_levels": [30000, 31000, 32000, 33000, 34000]
            },
            "SILVER": {
                "volatility_factor": 1.2,  # Moderate volatility
                "trend_persistence": 0.75,
                "session_hours": (9, 23),
                "optimal_timeframes": ["15min", "30min"],
                "key_levels": [70000, 72000, 74000, 76000, 78000]
            },
            "SILVERM": {
                "volatility_factor": 1.4,  # Higher volatility (mini)
                "trend_persistence": 0.7,
                "session_hours": (9, 23),
                "optimal_timeframes": ["5min", "15min"],
                "key_levels": [35000, 36000, 37000, 38000, 39000]
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
    
    def calculate_mcx_support_resistance(self, symbol: str, current_price: float) -> Dict[str, Any]:
        """
        Calculate MCX support/resistance using HYBRID approach:
        1. PRIMARY: Price-based dynamic levels (swing low/high)
        2. SECONDARY: Psychological levels (round numbers + key_levels)
        3. FINAL: Confidence scoring based on alignment
        
        Args:
            symbol: Commodity symbol
            current_price: Current price
            
        Returns:
            Dictionary with support, resistance, strength, confidence
        """
        try:
            # Get commodity profile
            profile = self.get_commodity_profile(symbol)
            key_levels = profile.get("key_levels", [])
            
            # --- PRIMARY: Price-based dynamic levels ---
            price_history = self.price_history.get(symbol, [])
            
            if len(price_history) < 5:
                # Not enough history - use simple range
                support = current_price * 0.99  # 1% below
                resistance = current_price * 1.01  # 1% above
                swing_support = support
                swing_resistance = resistance
            else:
                # Calculate swing low/high from recent history
                recent_prices = price_history[-10:]  # Last 10 prices
                swing_low = min(recent_prices)
                swing_high = max(recent_prices)
                
                # Use swing levels as primary S/R
                swing_support = swing_low
                swing_resistance = swing_high
                
                # Adjust to be outside current price
                if swing_support >= current_price:
                    swing_support = current_price * 0.99
                if swing_resistance <= current_price:
                    swing_resistance = current_price * 1.01
            
            # --- SECONDARY: Psychological levels ---
            # Find nearest psychological level (round numbers)
            price_rounded = round(current_price / 50) * 50  # Round to nearest 50
            psych_levels = [
                price_rounded - 100,
                price_rounded - 50,
                price_rounded,
                price_rounded + 50,
                price_rounded + 100
            ]
            
            # Find nearest psychological support (below price)
            psych_support_candidates = [level for level in psych_levels if level < current_price]
            psych_support = max(psych_support_candidates) if psych_support_candidates else current_price * 0.99
            
            # Find nearest psychological resistance (above price)
            psych_resistance_candidates = [level for level in psych_levels if level > current_price]
            psych_resistance = min(psych_resistance_candidates) if psych_resistance_candidates else current_price * 1.01
            
            # Combine with existing key_levels
            all_secondary_levels = psych_levels + key_levels
            
            # --- FINAL DECISION: Confidence scoring ---
            # Check if swing support aligns with psychological levels
            support_alignment = False
            resistance_alignment = False
            
            # Support alignment check (within 10 points)
            for level in all_secondary_levels:
                if abs(swing_support - level) <= 10:
                    support_alignment = True
                    break
            
            # Resistance alignment check (within 10 points)
            for level in all_secondary_levels:
                if abs(swing_resistance - level) <= 10:
                    resistance_alignment = True
                    break
            
            # Calculate strength
            if support_alignment and resistance_alignment:
                strength = "VERY STRONG"
                confidence = 0.9
            elif support_alignment or resistance_alignment:
                strength = "STRONG"
                confidence = 0.7
            else:
                strength = "NORMAL"
                confidence = 0.5
            
            # Final support/resistance (use swing levels, psychological as filter)
            final_support = swing_support
            final_resistance = swing_resistance
            
            logger.info(f"[MCX S/R] {symbol} - Support: {final_support:.2f} (Swing: {swing_support:.2f}, Psych: {psych_support:.2f}), "
                       f"Resistance: {final_resistance:.2f} (Swing: {swing_resistance:.2f}, Psych: {psych_resistance:.2f}), "
                       f"Strength: {strength}, Confidence: {confidence:.2f}")
            
            return {
                "support": {
                    "swing_level": swing_support,
                    "psych_level": psych_support,
                    "final_level": final_support,
                    "alignment": support_alignment
                },
                "resistance": {
                    "swing_level": swing_resistance,
                    "psych_level": psych_resistance,
                    "final_level": final_resistance,
                    "alignment": resistance_alignment
                },
                "strength": strength,
                "confidence": confidence,
                "key_levels": key_levels,
                "psych_levels": psych_levels,
                "service_metadata": {
                    "service": self.service_name,
                    "version": self.version,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error calculating MCX support/resistance: {e}")
            return {
                "error": str(e),
                "support": {"final_level": current_price * 0.99},
                "resistance": {"final_level": current_price * 1.01},
                "strength": "ERROR",
                "confidence": 0.0
            }
    
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
            
            # Detailed MCX Analysis Logging
            logger.info("=" * 80)
            logger.info(f"MCX DETAILED ANALYSIS: {symbol}")
            logger.info("=" * 80)
            logger.info(f"Current Price: {price:.2f}")
            logger.info(f"Momentum: {momentum:.4f} ({'UP' if momentum > 0 else 'DOWN' if momentum < 0 else 'FLAT'})")
            logger.info(f"Volatility: {volatility:.4f} (Factor: {profile.get('volatility_factor', 1.0)}x)")
            logger.info(f"Volume Signal: {volume_signal} (Volume: {volume:.0f})")
            logger.info(f"OI Signal: {oi_signal} (OI: {oi:.0f})")
            logger.info(f"Key Levels Analysis:")
            logger.info(f"  - Nearest Level: {key_levels['nearest_level']}")
            logger.info(f"  - Distance: {key_levels['distance_to_level']:.2f}")
            logger.info(f"  - Support: {key_levels['support']}")
            logger.info(f"  - Resistance: {key_levels['resistance']}")
            logger.info(f"Signal Generation:")
            logger.info(f"  - Signal Strength: {signal_strength}/{5}")
            logger.info(f"  - Direction: {signal_direction}")
            logger.info(f"  - Final Signal: {final_signal}")
            logger.info(f"  - Confidence: {confidence:.2f}")
            logger.info(f"Reasoning: {reasoning}")
            logger.info("=" * 80)
            
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
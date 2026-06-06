"""
Market Analyzer Service - Independent market analysis for trading opportunities
Identifies: PCR bias, OI build-up, VWAP analysis, adaptive thresholds
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketAnalyzerService:
    """
    Market Analyzer Service - Standalone microservice for market analysis.
    Identifies trading opportunities based on PCR, OI, VWAP, and adaptive thresholds.
    
    This service operates independently and identifies potential strikes.
    It does not make final trading decisions - that's done by consensus + LLM.
    """
    
    def __init__(self, optionstar_service=None):
        """Initialize the Market Analyzer Service"""
        self.service_name = "market_analyzer_service"
        self.version = "1.0.0"
        self.dependencies = []  # No dependencies
        self.dependents = ["trading_bot", "llm_analyzer"]
        self.protection_level = "CRITICAL"
        
        # Reference to OptionStar Service (independent)
        self.optionstar_service = optionstar_service
        
        # Volatility tracking for adaptive thresholds
        self.volatility_history = {}  # symbol -> list of recent price changes
        self.volatility_window = 10  # Track last 10 price changes
        
        # OI history for analysis
        self.oi_history = {}  # symbol -> list of recent OI values
        
        logger.info(f"Market Analyzer Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"OptionStar Service: {'Connected' if optionstar_service else 'Not connected'}")
    
    def analyze_market(self, symbol: str, spot_price: float, vwap: float, 
                      price_change: float, delta_oi: int, pcr: float,
                      option_chain: Dict) -> Dict:
        """
        Analyze market conditions and identify potential trading opportunities.
        
        Args:
            symbol: Trading symbol
            spot_price: Current spot price
            vwap: Current VWAP
            price_change: Recent price change
            delta_oi: Change in open interest
            pcr: Put-Call Ratio
            option_chain: Option chain data
            
        Returns:
            Dictionary with market analysis and potential strikes
        """
        # Calculate adaptive thresholds
        adaptive_thresholds = self.calculate_adaptive_thresholds(
            symbol, spot_price, price_change, delta_oi
        )
        
        # Analyze PCR bias
        pcr_bias = self.analyze_pcr_bias(pcr)
        
        # Analyze OI build-up
        oi_analysis = self.analyze_oi_buildup(delta_oi, price_change)
        
        # Analyze VWAP position
        vwap_analysis = self.analyze_vwap_position(spot_price, vwap, adaptive_thresholds)
        
        # Get OptionStar support/resistance data
        optionstar_analysis = self._analyze_optionstar_data(symbol, spot_price)
        
        # Identify potential strikes (using OptionStar data)
        potential_strikes = self.identify_potential_strikes(
            option_chain, spot_price, adaptive_thresholds, optionstar_analysis
        )
        
        # Calculate market strength (including OptionStar)
        market_strength = self.calculate_market_strength(
            price_change, delta_oi, adaptive_thresholds, vwap_analysis, optionstar_analysis
        )
        
        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "market_analysis": {
                "pcr": pcr,
                "pcr_bias": pcr_bias,
                "oi_analysis": oi_analysis,
                "vwap_analysis": vwap_analysis,
                "optionstar_analysis": optionstar_analysis,
                "adaptive_thresholds": adaptive_thresholds,
                "market_strength": market_strength
            },
            "potential_strikes": potential_strikes,
            "confidence": self.calculate_confidence(market_strength, pcr_bias, optionstar_analysis)
        }
    
    def _analyze_optionstar_data(self, symbol: str, spot_price: float) -> Dict:
        """Analyze OptionStar support/resistance data"""
        if not self.optionstar_service:
            return {
                "support": 0,
                "resistance": 0,
                "bias": "NEUTRAL",
                "near_support": False,
                "near_resistance": False
            }
        
        try:
            current_walls = self.optionstar_service.get_current_walls(symbol)
            support = current_walls.get("support", {}).get("strike", 0)
            resistance = current_walls.get("resistance", {}).get("strike", 0)
            bias = current_walls.get("trend_bias", "NEUTRAL")
            
            near_support = self.optionstar_service.is_near_support(symbol, spot_price)
            near_resistance = self.optionstar_service.is_near_resistance(symbol, spot_price)
            
            return {
                "support": support,
                "resistance": resistance,
                "bias": bias,
                "near_support": near_support,
                "near_resistance": near_resistance
            }
        except Exception as e:
            logger.error(f"Error analyzing OptionStar data: {e}")
            return {
                "support": 0,
                "resistance": 0,
                "bias": "NEUTRAL",
                "near_support": False,
                "near_resistance": False
            }
    
    def calculate_adaptive_thresholds(self, symbol: str, spot_price: float, 
                                      price_change: float, delta_oi: int) -> Dict:
        """Calculate adaptive thresholds based on volatility and time"""
        try:
            # Update volatility history
            if symbol not in self.volatility_history:
                self.volatility_history[symbol] = []
            
            self.volatility_history[symbol].append(abs(price_change))
            
            # Keep only last 10 volatility readings
            if len(self.volatility_history[symbol]) > self.volatility_window:
                self.volatility_history[symbol].pop(0)
            
            # Update OI history
            if symbol not in self.oi_history:
                self.oi_history[symbol] = []
            
            self.oi_history[symbol].append(delta_oi)
            
            # Keep only last 5 OI readings
            if len(self.oi_history[symbol]) > 5:
                self.oi_history[symbol].pop(0)
            
            # Calculate average volatility
            if len(self.volatility_history[symbol]) > 0:
                avg_volatility = sum(self.volatility_history[symbol]) / len(self.volatility_history[symbol])
            else:
                avg_volatility = 1.0
            
            # Get time factor
            time_factor = self._get_time_factor()
            
            # Base thresholds (fallback values)
            base_price_threshold = 5.0
            base_oi_threshold = 20000
            
            # Calculate adaptive thresholds
            price_threshold = max(base_price_threshold * avg_volatility * time_factor, 1.0)
            oi_threshold = max(base_oi_threshold * time_factor, 5000)
            vwap_threshold = price_threshold * 0.6
            
            return {
                "price_threshold": price_threshold,
                "oi_threshold": oi_threshold,
                "vwap_threshold": vwap_threshold,
                "time_factor": time_factor,
                "avg_volatility": avg_volatility
            }
            
        except Exception as e:
            logger.error(f"Error calculating adaptive thresholds: {e}")
            return {
                "price_threshold": 5.0,
                "oi_threshold": 20000,
                "vwap_threshold": 3.0,
                "time_factor": 1.0,
                "avg_volatility": 1.0
            }
    
    def _get_time_factor(self) -> float:
        """Calculate time factor based on current time"""
        current_hour = datetime.now().hour
        
        if 9 <= current_hour < 11:
            return 1.0  # Morning - full threshold
        elif 11 <= current_hour < 14:
            return 0.7  # Midday - reduced threshold
        elif 14 <= current_hour < 15:
            return 0.9  # Afternoon - slightly reduced
        else:
            return 0.5  # Close - very reduced
    
    def analyze_pcr_bias(self, pcr: float) -> str:
        """Analyze PCR bias"""
        if pcr >= 1.3:
            return "OVERBULLISH"
        elif pcr >= 1.1:
            return "BULLISH"
        elif pcr >= 0.9:
            return "NEUTRAL"
        elif pcr >= 0.7:
            return "BEARISH"
        else:
            return "STRONG_BEARISH"
    
    def analyze_oi_buildup(self, delta_oi: int, price_change: float) -> Dict:
        """Analyze OI build-up patterns"""
        if price_change > 0 and delta_oi > 0:
            oi_signal = "LONG_BUILDUP"
        elif price_change < 0 and delta_oi > 0:
            oi_signal = "SHORT_BUILDUP"
        elif price_change > 0 and delta_oi < 0:
            oi_signal = "SHORT_COVERING"
        elif price_change < 0 and delta_oi < 0:
            oi_signal = "LONG_UNWINDING"
        else:
            oi_signal = "NEUTRAL"
        
        return {
            "oi_signal": oi_signal,
            "delta_oi": delta_oi,
            "price_change": price_change,
            "strength_valid": oi_signal in ["LONG_BUILDUP", "SHORT_BUILDUP"]
        }
    
    def analyze_vwap_position(self, spot_price: float, vwap: float, 
                            adaptive_thresholds: Dict) -> Dict:
        """Analyze VWAP position"""
        vwap_diff = abs(spot_price - vwap)
        vwap_threshold = adaptive_thresholds["vwap_threshold"]
        
        if spot_price > vwap:
            position = "ABOVE_VWAP"
        else:
            position = "BELOW_VWAP"
        
        return {
            "position": position,
            "vwap_diff": vwap_diff,
            "vwap_threshold": vwap_threshold,
            "above_threshold": vwap_diff >= vwap_threshold
        }
    
    def identify_potential_strikes(self, option_chain: Dict, spot_price: float,
                                  adaptive_thresholds: Dict, optionstar_analysis: Dict) -> List[Dict]:
        """Identify potential trading strikes from option chain"""
        potential_strikes = []
        
        support = optionstar_analysis.get("support", 0)
        resistance = optionstar_analysis.get("resistance", 0)
        
        # This is a simplified version - in production, you'd analyze each strike
        # based on OI, liquidity, distance from ATM, etc.
        
        for strike_data in option_chain.get("strikes", []):
            strike = strike_data.get("strike")
            oi = strike_data.get("oi", 0)
            
            # Simple filtering logic
            if oi > adaptive_thresholds["oi_threshold"]:
                # Check if strike is near support/resistance
                near_support = abs(strike - support) <= 50 if support > 0 else False
                near_resistance = abs(strike - resistance) <= 50 if resistance > 0 else False
                
                potential_strikes.append({
                    "strike": strike,
                    "oi": oi,
                    "distance_from_atm": abs(strike - spot_price),
                    "near_support": near_support,
                    "near_resistance": near_resistance,
                    "recommendation": "POTENTIAL"
                })
        
        return potential_strikes
    
    def calculate_market_strength(self, price_change: float, delta_oi: int,
                                adaptive_thresholds: Dict, vwap_analysis: Dict, 
                                optionstar_analysis: Dict) -> int:
        """Calculate overall market strength (0-4)"""
        strength = 0
        
        # Price condition
        if abs(price_change) >= adaptive_thresholds["price_threshold"]:
            strength += 1
        
        # OI condition
        if abs(delta_oi) >= adaptive_thresholds["oi_threshold"]:
            strength += 1
        
        # VWAP condition
        if vwap_analysis["above_threshold"]:
            strength += 1
        
        # OptionStar condition (near support/resistance)
        if optionstar_analysis.get("near_support") or optionstar_analysis.get("near_resistance"):
            strength += 1
        
        return strength
    
    def calculate_confidence(self, market_strength: int, pcr_bias: str, 
                           optionstar_analysis: Dict) -> float:
        """Calculate confidence score (0.0-1.0)"""
        base_confidence = market_strength / 4.0  # Now out of 4
        
        # Adjust based on PCR bias
        if pcr_bias in ["OVERBULLISH", "STRONG_BEARISH"]:
            base_confidence *= 1.2
        elif pcr_bias in ["BULLISH", "BEARISH"]:
            base_confidence *= 1.1
        elif pcr_bias == "NEUTRAL":
            base_confidence *= 0.9
        
        # Adjust based on OptionStar bias
        optionstar_bias = optionstar_analysis.get("bias", "NEUTRAL")
        if optionstar_bias in ["BULLISH", "BEARISH"]:
            base_confidence *= 1.1
        
        return min(base_confidence, 1.0)
    
    def get_service_info(self) -> Dict:
        """Get service information for service discovery"""
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "market_analysis",
                "adaptive_thresholds",
                "pcr_analysis",
                "oi_analysis",
                "vwap_analysis",
                "strike_identification"
            ]
        }

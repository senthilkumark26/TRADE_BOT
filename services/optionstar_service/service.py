"""
OptionStar Service - Protected Microservice
Institutional OI Analysis Engine with Dependency Management
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class OptionStarService:
    """
    OptionStar Institutional OI Analysis Service
    
    Protected microservice that provides:
    - Institutional support/resistance detection
    - OI-based trend bias analysis
    - Dealer positioning intelligence
    - Dependency tracking with Engine1
    
    This service is protected from deletion and requires approval for modification.
    """
    
    def __init__(self):
        """Initialize OptionStar Service."""
        self.service_name = "optionstar_service"
        self.version = "2.0.0"  # Updated version for continuous monitoring
        self.dependencies = []  # Independent service - no dependencies
        self.dependents = ["market_analyzer_service", "breakout_entry_service", "consensus_service"]
        self.protection_level = "CRITICAL"
        self.last_health_check = None
        self.health_status = "UNKNOWN"
        
        # Continuous monitoring data
        self.support_resistance_history = {}  # symbol -> list of historical support/resistance
        self.monitoring_active = False
        self.monitoring_interval = 5  # seconds
        self.current_walls = {}  # symbol -> current support/resistance
        
        logger.info(f"OptionStar Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"Continuous Monitoring: Enabled")
    
    def calculate_institutional_walls(self, option_chain_data: Dict[str, Any], spot_price: float) -> Dict[str, Any]:
        """
        Calculate institutional support/resistance using Option Chain Open Interest.

        Args:
            option_chain_data: Dict containing option chain (calls + puts)
            spot_price: Current underlying price

        Returns:
            Dict with support/resistance levels and bias
        """

        try:
            calls = option_chain_data.get("calls", [])
            puts = option_chain_data.get("puts", [])

            if not calls or not puts:
                return {"error": "Invalid option chain data"}

            # --- Find Max Call OI (Resistance Wall)
            max_call = max(calls, key=lambda x: x.get("openInterest", 0))
            call_resistance = max_call.get("strikePrice")
            max_call_oi = max_call.get("openInterest", 0)

            # --- Find Max Put OI (Support Wall)
            max_put = max(puts, key=lambda x: x.get("openInterest", 0))
            put_support = max_put.get("strikePrice")
            max_put_oi = max_put.get("openInterest", 0)

            # --- Distance Calculation
            distance_to_resistance = call_resistance - spot_price
            distance_to_support = spot_price - put_support

            # --- Trend Bias Logic
            if max_put_oi > max_call_oi:
                bias = "BULLISH"
            elif max_call_oi > max_put_oi:
                bias = "BEARISH"
            else:
                bias = "NEUTRAL"

            return {
                "spot_price": spot_price,
                "resistance": {
                    "strike": call_resistance,
                    "oi": max_call_oi,
                    "distance": distance_to_resistance
                },
                "support": {
                    "strike": put_support,
                    "oi": max_put_oi,
                    "distance": distance_to_support
                },
                "trend_bias": bias,
                "service_metadata": {
                    "service": self.service_name,
                    "version": self.version,
                    "timestamp": datetime.now().isoformat()
                }
            }

        except Exception as e:
            logger.error(f"Error calculating institutional walls: {e}")
            return {"error": str(e)}
    
    def generate_trade(self, current_price: float, vwap: float, option_chain: list, symbol: str) -> Dict[str, Any]:
        """
        Generate trade setup using institutional OI analysis.
        
        Args:
            current_price: Current spot price
            vwap: Volume weighted average price
            option_chain: Option chain data list
            symbol: Instrument symbol
            
        Returns:
            Trade setup dictionary with direction, strike, support, resistance
        """
        try:
            # Convert option chain format to OptionStar format
            calls = []
            puts = []
            
            for item in option_chain:
                if item.get('type') == 'CE':
                    calls.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('call_oi', 0)
                    })
                elif item.get('type') == 'PE':
                    puts.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('put_oi', 0)
                    })
            
            option_chain_data = {
                "calls": calls,
                "puts": puts
            }
            
            # Calculate institutional walls
            institutional_data = self.calculate_institutional_walls(option_chain_data, current_price)
            
            if "error" in institutional_data:
                logger.error(f"OptionStar error for {symbol}: {institutional_data['error']}")
                return None
            
            # Determine direction based on bias and VWAP
            bias = institutional_data["trend_bias"]
            
            # At market open (VWAP ≈ spot), use OI bias
            # During trading, use VWAP trend
            if abs(current_price - vwap) < 5:  # Near VWAP (market open condition)
                direction = "CALL" if bias == "BULLISH" else "PUT" if bias == "BEARISH" else None
            else:
                # Use VWAP trend during regular trading
                direction = "CALL" if current_price > vwap else "PUT"
            
            if not direction:
                return None
            
            # Select strike based on institutional walls
            support = institutional_data["support"]["strike"]
            resistance = institutional_data["resistance"]["strike"]
            
            # Choose strike closer to current price but respecting institutional walls
            if direction == "CALL":
                # For CALL, select strike between current and resistance
                strike = min(resistance, current_price + 50)  # Conservative: 50 points above current
            else:
                # For PUT, select strike between current and support  
                strike = max(support, current_price - 50)  # Conservative: 50 points below current
            
            # Generate reason
            reason = f"OI {bias} bias - Support: {support}, Resistance: {resistance}"
            
            return {
                "direction": direction,
                "strike": strike,
                "spot": current_price,
                "vwap": vwap,
                "support": support,
                "resistance": resistance,
                "reason": reason,
                "institutional_data": institutional_data,
                "service_metadata": {
                    "service": self.service_name,
                    "version": self.version,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating trade for {symbol}: {e}")
            return None
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the service.
        
        Returns:
            Health status dictionary
        """
        self.last_health_check = datetime.now().isoformat()
        
        health_status = {
            "service": self.service_name,
            "version": self.version,
            "status": "HEALTHY",
            "protection_level": self.protection_level,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "last_check": self.last_health_check
        }
        
        self.health_status = health_status["status"]
        return health_status
    
    def get_service_info(self) -> Dict[str, Any]:
        """
        Get service information and metadata.
        
        Returns:
            Service information dictionary
        """
        return {
            "service_name": self.service_name,
            "version": self.version,
            "protection_level": self.protection_level,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check,
            "description": "Institutional OI Analysis Engine - Calculates support/resistance using option chain open interest data",
            "criticality": "CRITICAL - Required for Engine1 operation and trade safety"
        }


# Global service instance
_optionstar_service = None

def get_optionstar_service() -> OptionStarService:
    """
    Get the global OptionStar service instance.
    
    Returns:
        OptionStarService instance
    """
    global _optionstar_service
    if _optionstar_service is None:
        _optionstar_service = OptionStarService()
    return _optionstar_service


# Convenience functions that delegate to the service
def calculate_institutional_walls(option_chain_data: Dict[str, Any], spot_price: float) -> Dict[str, Any]:
    """Convenience function for calculate_institutional_walls"""
    service = get_optionstar_service()
    return service.calculate_institutional_walls(option_chain_data, spot_price)


def generate_trade(current_price: float, vwap: float, option_chain: list, symbol: str) -> Dict[str, Any]:
    """Convenience function for generate_trade"""
    service = get_optionstar_service()
    return service.generate_trade(current_price, vwap, option_chain, symbol)





# Continuous Monitoring Methods (Class Methods)
def start_continuous_monitoring(self, symbols: list, option_chain_provider):
    """
    Start continuous monitoring of support/resistance levels.
    
    Args:
        symbols: List of symbols to monitor
        option_chain_provider: Function to get option chain data for a symbol
    """
    import threading
    import time
    
    self.monitoring_active = True
    self.option_chain_provider = option_chain_provider
    
    def monitor_loop():
        while self.monitoring_active:
            for symbol in symbols:
                try:
                    # Get current option chain
                    option_chain = self.option_chain_provider(symbol)
                    if option_chain:
                        # Calculate support/resistance
                        walls = self.calculate_institutional_walls(option_chain, 0)
                        
                        # Store current walls
                        self.current_walls[symbol] = walls
                        
                        # Update history
                        if symbol not in self.support_resistance_history:
                            self.support_resistance_history[symbol] = []
                        
                        self.support_resistance_history[symbol].append({
                            "timestamp": datetime.now().isoformat(),
                            "support": walls.get("support", {}).get("strike", 0),
                            "resistance": walls.get("resistance", {}).get("strike", 0),
                            "bias": walls.get("trend_bias", "NEUTRAL")
                        })
                        
                        # Keep only last 20 readings
                        if len(self.support_resistance_history[symbol]) > 20:
                            self.support_resistance_history[symbol].pop(0)
                        
                        logger.info(f"[OPTIONSTAR] {symbol} - Support: {walls.get('support', {}).get('strike', 0)}, "
                                   f"Resistance: {walls.get('resistance', {}).get('strike', 0)}, "
                                   f"Bias: {walls.get('trend_bias', 'NEUTRAL')}")
                
                except Exception as e:
                    logger.error(f"[OPTIONSTAR] Error monitoring {symbol}: {e}")
            
            time.sleep(self.monitoring_interval)
    
    # Start monitoring thread
    self.monitoring_thread = threading.Thread(target=monitor_loop, daemon=True)
    self.monitoring_thread.start()
    logger.info(f"[OPTIONSTAR] Continuous monitoring started for {len(symbols)} symbols")


def stop_continuous_monitoring(self):
    """Stop continuous monitoring."""
    self.monitoring_active = False
    if hasattr(self, 'monitoring_thread'):
        self.monitoring_thread.join(timeout=5)
    logger.info("[OPTIONSTAR] Continuous monitoring stopped")


def get_current_walls(self, symbol: str) -> Dict:
    """
    Get current support/resistance levels for a symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Dictionary with current support/resistance levels
    """
    return self.current_walls.get(symbol, {})


def get_walls_history(self, symbol: str) -> list:
    """
    Get historical support/resistance levels for a symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        List of historical support/resistance readings
    """
    return self.support_resistance_history.get(symbol, [])


def is_near_support(self, symbol: str, current_price: float, tolerance: float = 0.005) -> bool:
    """
    Check if current price is near support level.
    
    Args:
        symbol: Trading symbol
        current_price: Current spot price
        tolerance: Tolerance percentage (default 0.5%)
        
    Returns:
        True if near support
    """
    walls = self.get_current_walls(symbol)
    support = walls.get("support", {}).get("strike", 0)
    
    if support == 0:
        return False
    
    distance = abs(current_price - support) / current_price
    return distance <= tolerance


def is_near_resistance(self, symbol: str, current_price: float, tolerance: float = 0.005) -> bool:
    """
    Check if current price is near resistance level.
    
    Args:
        symbol: Trading symbol
        current_price: Current spot price
        tolerance: Tolerance percentage (default 0.5%)
        
    Returns:
        True if near resistance
    """
    walls = self.get_current_walls(symbol)
    resistance = walls.get("resistance", {}).get("strike", 0)
    
    if resistance == 0:
        return False
    
    distance = abs(current_price - resistance) / current_price
    return distance <= tolerance


# Add methods to the class
OptionStarService.start_continuous_monitoring = start_continuous_monitoring
OptionStarService.stop_continuous_monitoring = stop_continuous_monitoring
OptionStarService.get_current_walls = get_current_walls
OptionStarService.get_walls_history = get_walls_history
OptionStarService.is_near_support = is_near_support
OptionStarService.is_near_resistance = is_near_resistance
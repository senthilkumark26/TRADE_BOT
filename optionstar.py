"""
OptionStar - Institutional OI Analysis Engine (Protected Service Wrapper)
Calculates support/resistance using Option Chain Open Interest
Identifies dealer positioning and liquidity walls

This file is a protected wrapper that delegates to the OptionStar microservice.
The actual implementation is in services/optionstar_service/service.py
This wrapper maintains backward compatibility while protecting the core service.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Import from the protected microservice
try:
    from services.optionstar_service import (
        calculate_institutional_walls as _calculate_institutional_walls,
        generate_trade as _generate_trade,
        get_optionstar_service
    )
    logger.info("OptionStar: Using protected microservice")
except ImportError as e:
    logger.warning(f"OptionStar: Microservice not available, using fallback: {e}")
    
    # Fallback implementations (should not happen in production)
    def _calculate_institutional_walls(option_chain_data: Dict[str, Any], spot_price: float) -> Dict[str, Any]:
        """Fallback implementation"""
        return {"error": "OptionStar microservice not available"}
    
    def _generate_trade(current_price: float, vwap: float, option_chain: list, symbol: str) -> Dict[str, Any]:
        """Fallback implementation"""
        return None
    
    def get_optionstar_service():
        """Fallback implementation"""
        return None


# Public API (maintains backward compatibility)
def calculate_institutional_walls(option_chain_data: Dict[str, Any], spot_price: float) -> Dict[str, Any]:
    """
    Calculate institutional support/resistance using Option Chain Open Interest.
    
    Delegates to the protected OptionStar microservice.
    
    Args:
        option_chain_data: Dict containing option chain (calls + puts)
        spot_price: Current underlying price

    Returns:
        Dict with support/resistance levels and bias
    """
    return _calculate_institutional_walls(option_chain_data, spot_price)


def generate_trade(current_price: float, vwap: float, option_chain: list, symbol: str) -> Dict[str, Any]:
    """
    Generate trade setup using institutional OI analysis.
    
    Delegates to the protected OptionStar microservice.
    
    Args:
        current_price: Current spot price
        vwap: Volume weighted average price
        option_chain: Option chain data list
        symbol: Instrument symbol
        
    Returns:
        Trade setup dictionary with direction, strike, support, resistance
    """
    return _generate_trade(current_price, vwap, option_chain, symbol)


def get_service_info() -> Dict[str, Any]:
    """
    Get OptionStar service information.
    
    Returns:
        Service information dictionary
    """
    service = get_optionstar_service()
    if service:
        return service.get_service_info()
    else:
        return {
            "service": "optionstar_service",
            "status": "UNAVAILABLE",
            "error": "Microservice not loaded"
        }
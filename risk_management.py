"""
Risk Management - Protected Service Wrapper
Capital protection and risk management for trading systems

This file is a protected wrapper that delegates to the Risk Management microservice.
The actual implementation is in services/risk_management_service/service.py
This wrapper maintains backward compatibility while protecting the core service.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Import from the protected microservice
try:
    from services.risk_management_service import (
        get_risk_management_service,
        RiskManagementService
    )
    logger.info("Risk Management: Using protected microservice")
except ImportError as e:
    logger.warning(f"Risk Management: Microservice not available, using fallback: {e}")
    
    # Fallback implementations (should not happen in production)
    def get_risk_management_service(start_capital: float = 30000):
        """Fallback implementation"""
        logger.error("Risk Management microservice not available - risk protection disabled")
        return None


# Public API (maintains backward compatibility)
def calculate_position_size(option_price: float, lot_size: int, current_capital: float) -> Dict[str, Any]:
    """
    Calculate optimal position size based on capital and risk.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        option_price: Current option price
        lot_size: Lot size for the instrument
        current_capital: Current available capital
        
    Returns:
        Dictionary with position size details
    """
    service = get_risk_management_service()
    if service:
        return service.calculate_position_size(option_price, lot_size, current_capital)
    else:
        # Fallback: simple calculation
        cost_per_lot = option_price * lot_size
        max_lots = int(current_capital / cost_per_lot) if cost_per_lot > 0 else 0
        actual_lots = 1 if max_lots >= 1 else 0
        return {
            "success": actual_lots > 0,
            "actual_lots": actual_lots,
            "cost_per_lot": cost_per_lot,
            "total_cost": cost_per_lot * actual_lots
        }


def calculate_risk_parameters(option_price: float, actual_lots: int, direction: str, current_capital: float) -> Dict[str, Any]:
    """
    Calculate risk parameters (stop-loss, target) based on risk management rules.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        option_price: Current option price
        actual_lots: Number of lots
        direction: Trade direction (CALL/PUT)
        current_capital: Current available capital
        
    Returns:
        Dictionary with risk parameters
    """
    service = get_risk_management_service()
    if service:
        return service.calculate_risk_parameters(option_price, actual_lots, direction, current_capital)
    else:
        # Fallback: simple calculation
        risk_amount = current_capital * 0.02
        risk_per_option = risk_amount / actual_lots
        if direction == "CALL":
            stoploss_price = option_price - risk_per_option
            target_price = option_price + (risk_per_option * 5)
        else:
            stoploss_price = option_price + risk_per_option
            target_price = option_price - (risk_per_option * 5)
        return {
            "success": True,
            "risk_amount": risk_amount,
            "stoploss_price": stoploss_price,
            "target_price": target_price
        }


def check_daily_loss_limit(current_capital: float) -> Dict[str, Any]:
    """
    Check if daily loss limit has been reached.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        current_capital: Current capital amount
        
    Returns:
        Dictionary with limit check result
    """
    service = get_risk_management_service()
    if service:
        return service.check_daily_loss_limit(current_capital)
    else:
        # Fallback: no limit check
        return {
            "limit_reached": False,
            "daily_loss": 0,
            "daily_loss_percent": 0,
            "trading_enabled": True
        }


def check_capital_protection(current_capital: float, demo_mode: bool = False) -> Dict[str, Any]:
    """
    Check capital protection limits.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        current_capital: Current capital amount
        demo_mode: Whether in demo mode
        
    Returns:
        Dictionary with protection check result
    """
    service = get_risk_management_service()
    if service:
        return service.check_capital_protection(current_capital, demo_mode)
    else:
        # Fallback: no protection check
        return {
            "protection_triggered": False,
            "capital_loss_percent": 0,
            "current_capital": current_capital
        }


def update_daily_pnl(pnl: float) -> Dict[str, Any]:
    """
    Update daily P&L tracking.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        pnl: Profit/loss from trade
        
    Returns:
        Dictionary with updated P&L info
    """
    service = get_risk_management_service()
    if service:
        return service.update_daily_pnl(pnl)
    else:
        # Fallback: no tracking
        return {
            "daily_pnl": pnl,
            "daily_loss": abs(pnl) if pnl < 0 else 0,
            "daily_trades": 1
        }


def update_capital(pnl: float) -> float:
    """
    Update capital after trade.
    
    Delegates to the protected Risk Management microservice.
    
    Args:
        pnl: Profit/loss from trade
        
    Returns:
        Updated capital amount
    """
    service = get_risk_management_service()
    if service:
        return service.update_capital(pnl)
    else:
        # Fallback: return None (no tracking)
        return None


def can_open_new_trade() -> Dict[str, Any]:
    """
    Check if new trade can be opened based on risk limits.
    
    Delegates to the protected Risk Management microservice.
    
    Returns:
        Dictionary with permission status
    """
    service = get_risk_management_service()
    if service:
        return service.can_open_new_trade()
    else:
        # Fallback: always allow
        return {
            "can_trade": True,
            "reason": "Risk management service not available - allowing trade"
        }


def get_service_info() -> Dict[str, Any]:
    """
    Get Risk Management service information.
    
    Returns:
        Service information dictionary
    """
    service = get_risk_management_service()
    if service:
        return service.get_service_info()
    else:
        return {
            "service": "risk_management_service",
            "status": "UNAVAILABLE",
            "error": "Microservice not loaded"
        }
"""
Risk Management Service - Protected Microservice
Capital protection and risk management for trading systems
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RiskManagementService:
    """
    Risk Management Service - Capital Protection and Risk Control
    
    Protected microservice that provides:
    - Daily loss limit enforcement
    - Capital protection mechanisms
    - Stop-loss validation
    - Position sizing calculations
    - Risk per trade calculations
    
    This service is protected from deletion and requires approval for modification.
    """
    
    def __init__(self, start_capital: float = 30000):
        """
        Initialize Risk Management Service.
        
        Args:
            start_capital: Initial capital amount
        """
        self.service_name = "risk_management_service"
        self.version = "1.0.0"
        self.dependencies = []
        self.dependents = ["single_strike_trader", "trading_bot"]
        self.protection_level = "CRITICAL"
        
        # Risk parameters
        self.start_capital = start_capital
        self.current_capital = start_capital
        self.risk_per_trade = 0.02  # 2% risk per trade
        self.rr_ratio = 5  # 1:5 risk-reward
        self.max_daily_loss = 0.10  # 10% max daily loss
        self.max_capital_loss = 0.50  # 50% max capital loss
        
        # Tracking
        self.daily_loss = 0.0
        self.daily_trades = 0
        self.daily_pnl = 0.0
        
        # State
        self.trading_enabled = True
        self.last_health_check = None
        self.health_status = "UNKNOWN"
        
        logger.info(f"Risk Management Service initialized (v{self.version})")
        logger.info(f"Start Capital: ₹{start_capital}")
        logger.info(f"Risk per Trade: {self.risk_per_trade * 100}%")
        logger.info(f"Risk-Reward Ratio: 1:{self.rr_ratio}")
        logger.info(f"Max Daily Loss: {self.max_daily_loss * 100}%")
        logger.info(f"Max Capital Loss: {self.max_capital_loss * 100}%")
        logger.info(f"Protection Level: {self.protection_level}")
    
    def calculate_position_size(self, option_price: float, lot_size: int, current_capital: float) -> Dict[str, Any]:
        """
        Calculate optimal position size based on capital and risk.
        
        Args:
            option_price: Current option price
            lot_size: Lot size for the instrument
            current_capital: Current available capital
            
        Returns:
            Dictionary with position size details
        """
        try:
            cost_per_lot = option_price * lot_size
            max_lots = int(current_capital / cost_per_lot) if cost_per_lot > 0 else 0
            
            # Conservative: Use 1 lot minimum
            actual_lots = 1 if max_lots >= 1 else 0
            
            if actual_lots == 0:
                return {
                    "success": False,
                    "error": "Cannot afford even 1 lot",
                    "cost_per_lot": cost_per_lot,
                    "capital": current_capital
                }
            
            total_cost = cost_per_lot * actual_lots
            capital_utilization = (total_cost / current_capital) * 100
            
            return {
                "success": True,
                "actual_lots": actual_lots,
                "cost_per_lot": cost_per_lot,
                "total_cost": total_cost,
                "capital_utilization": capital_utilization,
                "remaining_capital": current_capital - total_cost
            }
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def calculate_risk_parameters(self, option_price: float, actual_lots: int, direction: str, current_capital: float) -> Dict[str, Any]:
        """
        Calculate risk parameters (stop-loss, target) based on risk management rules.
        
        Args:
            option_price: Current option price
            actual_lots: Number of lots
            direction: Trade direction (CALL/PUT)
            current_capital: Current available capital
            
        Returns:
            Dictionary with risk parameters
        """
        try:
            # Calculate risk amount (2% of current capital)
            risk_amount = current_capital * self.risk_per_trade
            
            # Calculate risk per option unit (not per lot)
            risk_per_option = risk_amount / actual_lots
            
            # Calculate stop-loss and target
            if direction == "CALL":
                stoploss_price = option_price - risk_per_option
                target_price = option_price + (risk_per_option * self.rr_ratio)
            else:  # PUT
                stoploss_price = option_price + risk_per_option
                target_price = option_price - (risk_per_option * self.rr_ratio)
            
            # Validate stop-loss is reasonable
            sl_distance = abs(stoploss_price - option_price)
            sl_validation = self._validate_stop_loss(option_price, sl_distance)
            
            if not sl_validation["valid"]:
                stoploss_price = sl_validation["adjusted_stoploss"]
                logger.warning(f"Stop-loss adjusted: {sl_validation['reason']}")
            
            return {
                "success": True,
                "risk_amount": risk_amount,
                "risk_per_option": risk_per_option,
                "stoploss_price": stoploss_price,
                "target_price": target_price,
                "sl_distance": sl_distance,
                "sl_validation": sl_validation
            }
            
        except Exception as e:
            logger.error(f"Error calculating risk parameters: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _validate_stop_loss(self, option_price: float, sl_distance: float) -> Dict[str, Any]:
        """
        Validate stop-loss distance is reasonable.
        
        Args:
            option_price: Option price
            sl_distance: Stop-loss distance from entry
            
        Returns:
            Validation result with adjusted stop-loss if needed
        """
        # Reasonable range: 5% to 20% of option price
        min_sl = option_price * 0.05
        max_sl = option_price * 0.20
        
        if sl_distance < min_sl:
            # Too tight - widen to 5%
            adjusted_sl = option_price * 0.95
            return {
                "valid": False,
                "reason": f"Too tight ({sl_distance:.2f}), widening to 5%",
                "adjusted_stoploss": adjusted_sl
            }
        elif sl_distance > max_sl:
            # Too wide - tighten to 20%
            adjusted_sl = option_price * 0.80
            return {
                "valid": False,
                "reason": f"Too wide ({sl_distance:.2f}), tightening to 20%",
                "adjusted_stoploss": adjusted_sl
            }
        else:
            return {
                "valid": True,
                "reason": "Stop-loss within reasonable range"
            }
    
    def check_daily_loss_limit(self, current_capital: float) -> Dict[str, Any]:
        """
        Check if daily loss limit has been reached.
        
        Args:
            current_capital: Current capital amount
            
        Returns:
            Dictionary with limit check result
        """
        try:
            daily_loss_percent = self.daily_loss / self.start_capital
            limit_reached = daily_loss_percent >= self.max_daily_loss
            
            return {
                "limit_reached": limit_reached,
                "daily_loss": self.daily_loss,
                "daily_loss_percent": daily_loss_percent,
                "max_daily_loss_percent": self.max_daily_loss,
                "trading_enabled": not limit_reached
            }
            
        except Exception as e:
            logger.error(f"Error checking daily loss limit: {e}")
            return {
                "limit_reached": True,  # Conservative: stop on error
                "error": str(e)
            }
    
    def check_capital_protection(self, current_capital: float, demo_mode: bool = False) -> Dict[str, Any]:
        """
        Check capital protection limits.
        
        Args:
            current_capital: Current capital amount
            demo_mode: Whether in demo mode
            
        Returns:
            Dictionary with protection check result
        """
        try:
            capital_loss_percent = (self.start_capital - current_capital) / self.start_capital
            protection_triggered = current_capital < (self.start_capital * (1 - self.max_capital_loss))
            
            result = {
                "protection_triggered": protection_triggered,
                "capital_loss_percent": capital_loss_percent,
                "max_capital_loss_percent": self.max_capital_loss,
                "current_capital": current_capital,
                "start_capital": self.start_capital
            }
            
            if protection_triggered:
                if demo_mode:
                    # In demo mode, reset capital
                    self.current_capital = self.start_capital
                    result["action"] = "capital_reset"
                    result["reason"] = "Demo mode: Capital reset to starting amount"
                else:
                    # In live mode, stop trading
                    result["action"] = "stop_trading"
                    result["reason"] = "Live mode: Trading stopped to prevent further loss"
                    logger.error("CRITICAL: Capital protection triggered - MANUAL INTERVENTION REQUIRED")
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking capital protection: {e}")
            return {
                "protection_triggered": True,  # Conservative: stop on error
                "error": str(e)
            }
    
    def update_daily_pnl(self, pnl: float) -> Dict[str, Any]:
        """
        Update daily P&L tracking.
        
        Args:
            pnl: Profit/loss from trade
            
        Returns:
            Dictionary with updated P&L info
        """
        try:
            self.daily_pnl += pnl
            self.daily_trades += 1
            
            if pnl < 0:
                self.daily_loss += abs(pnl)
            
            daily_pnl_percent = (self.daily_pnl / self.start_capital) * 100
            
            return {
                "daily_pnl": self.daily_pnl,
                "daily_loss": self.daily_loss,
                "daily_trades": self.daily_trades,
                "daily_pnl_percent": daily_pnl_percent
            }
            
        except Exception as e:
            logger.error(f"Error updating daily P&L: {e}")
            return {
                "error": str(e)
            }
    
    def update_capital(self, pnl: float) -> float:
        """
        Update capital after trade.
        
        Args:
            pnl: Profit/loss from trade
            
        Returns:
            Updated capital amount
        """
        try:
            self.current_capital += pnl
            return self.current_capital
        except Exception as e:
            logger.error(f"Error updating capital: {e}")
            return self.current_capital
    
    def can_open_new_trade(self) -> Dict[str, Any]:
        """
        Check if new trade can be opened based on risk limits.
        
        Returns:
            Dictionary with permission status
        """
        try:
            # Check daily loss limit
            daily_check = self.check_daily_loss_limit(self.current_capital)
            if daily_check.get("limit_reached"):
                return {
                    "can_trade": False,
                    "reason": f"Daily loss limit reached ({daily_check['daily_loss_percent']:.1%})",
                    "limit_type": "daily_loss"
                }
            
            # Check capital protection
            capital_check = self.check_capital_protection(self.current_capital, demo_mode=False)
            if capital_check.get("protection_triggered"):
                return {
                    "can_trade": False,
                    "reason": f"Capital protection triggered ({capital_check['capital_loss_percent']:.1%} loss)",
                    "limit_type": "capital_protection"
                }
            
            return {
                "can_trade": True,
                "reason": "All risk limits within acceptable range"
            }
            
        except Exception as e:
            logger.error(f"Error checking trade permission: {e}")
            return {
                "can_trade": False,
                "reason": f"Error checking risk limits: {str(e)}",
                "limit_type": "system_error"
            }
    
    def reset_daily_tracking(self):
        """Reset daily tracking for new trading day."""
        self.daily_loss = 0.0
        self.daily_trades = 0
        self.daily_pnl = 0.0
        logger.info("Daily tracking reset for new trading day")
    
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
            "last_check": self.last_health_check,
            "current_capital": self.current_capital,
            "start_capital": self.start_capital,
            "daily_loss": self.daily_loss,
            "trading_enabled": self.trading_enabled
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
            "description": "Risk Management Service - Capital protection and risk control for trading systems",
            "criticality": "CRITICAL - Required for capital protection and risk management",
            "features": [
                "Daily loss limit enforcement",
                "Capital protection mechanisms", 
                "Stop-loss validation",
                "Position sizing calculations",
                "Risk per trade calculations"
            ]
        }


# Global service instance
_risk_management_service = None

def get_risk_management_service(start_capital: float = 30000) -> RiskManagementService:
    """
    Get the global Risk Management service instance.
    
    Args:
        start_capital: Initial capital amount
        
    Returns:
        RiskManagementService instance
    """
    global _risk_management_service
    if _risk_management_service is None:
        _risk_management_service = RiskManagementService(start_capital)
    return _risk_management_service
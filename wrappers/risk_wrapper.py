from services.risk_management_service.service import RiskManagementService

# Initialize with default capital (can be configured)
risk = RiskManagementService(start_capital=100000)

def get_position_size(stop_loss_points):
    """Calculate position size based on stop loss points"""
    # RiskManagementService uses different method signature
    return risk.calculate_position_size(100, 65, 100000)  # Placeholder

def update_trade_result(pnl):
    """Update trade result with P&L"""
    risk.update_daily_pnl(pnl)

def can_execute_trade():
    """Check if trading is allowed"""
    result = risk.can_open_new_trade()
    return result.get('can_trade', True)

def reset_daily_limits():
    """Reset daily risk limits (call once per day)"""
    risk.reset_daily_tracking()

def get_risk_status():
    """Get current risk status"""
    return risk.health_check()
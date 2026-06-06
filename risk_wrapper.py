from services.risk_manager import RiskManager

# Initialize with default capital (can be configured)
risk = RiskManager(capital=100000)

def get_position_size(stop_loss_points):
    """Calculate position size based on stop loss points"""
    return risk.calculate_lot_size(stop_loss_points)

def update_trade_result(pnl):
    """Update trade result with P&L"""
    risk.update_trade(pnl)

def can_execute_trade():
    """Check if trading is allowed"""
    return risk.can_trade()

def reset_daily_limits():
    """Reset daily risk limits (call once per day)"""
    risk.reset_daily()

def get_risk_status():
    """Get current risk status"""
    return {
        'capital': risk.capital,
        'daily_loss': risk.daily_loss,
        'trade_count': risk.trade_count,
        'stop_trading': risk.stop_trading,
        'can_trade': risk.can_trade()
    }
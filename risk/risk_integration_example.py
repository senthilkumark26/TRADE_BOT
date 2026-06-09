"""
RISK MANAGER INTEGRATION EXAMPLE
Shows how to integrate the new Risk Manager into your trading bot
"""

import sys
import os

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from wrappers.risk_wrapper import (
    get_position_size,
    update_trade_result,
    can_execute_trade,
    reset_daily_limits,
    get_risk_status
)

def example_trading_integration():
    """
    Example showing the 3-line integration into your trading bot
    """
    
    print("="*80)
    print("RISK MANAGER INTEGRATION EXAMPLE")
    print("="*80)
    
    # ========================================
    # BEFORE ENTRY - Check if trading allowed
    # ========================================
    print("\n1. BEFORE ENTRY - Check trading permission")
    if not can_execute_trade():
        print("[X] Trading stopped by Risk Manager - DO NOT TRADE")
        return
    else:
        print("[OK] Trading allowed by Risk Manager")
    
    # ========================================
    # CALCULATE POSITION SIZE
    # ========================================
    print("\n2. CALCULATE POSITION SIZE")
    stop_loss_points = 15  # Your analysis says 15 points SL
    lot_size = get_position_size(stop_loss_points)
    print(f"Stop Loss: {stop_loss_points} points")
    print(f"Risk Manager calculated lot size: {lot_size}")
    
    # ========================================
    # EXECUTE TRADE (Your existing logic)
    # ========================================
    print("\n3. EXECUTE TRADE")
    print("Place order with lot size:", lot_size)
    # ... your existing order execution code ...
    
    # ========================================
    # AFTER TRADE - Update result
    # ========================================
    print("\n4. AFTER TRADE - Update Risk Manager")
    trade_pnl = -1200  # Example: This trade lost ₹1200
    update_trade_result(trade_pnl)
    
    # ========================================
    # CHECK STATUS
    # ========================================
    print("\n5. CURRENT RISK STATUS")
    status = get_risk_status()
    print(f"Daily Loss: {status['daily_loss']}")
    print(f"Trade Count: {status['trade_count']}")
    print(f"Still Trading: {status['can_trade']}")
    
    print("\n" + "="*80)
    print("INTEGRATION EXAMPLE COMPLETED")
    print("="*80)

def daily_reset_routine():
    """
    Call this once at the start of each trading day
    """
    print("\n" + "="*80)
    print("DAILY RESET ROUTINE")
    print("="*80)
    reset_daily_limits()
    print("[OK] Risk limits reset for new trading day")
    print("="*80)

if __name__ == "__main__":
    # Example 1: Normal trading integration
    example_trading_integration()
    
    # Example 2: Daily reset (call this once per day)
    daily_reset_routine()
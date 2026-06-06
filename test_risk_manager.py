"""
Test the new Risk Manager Service
Demonstrates the clean, plug-and-play risk management system
"""

from risk_wrapper import (
    get_position_size,
    update_trade_result,
    can_execute_trade,
    reset_daily_limits,
    get_risk_status
)

def test_risk_manager():
    print("="*80)
    print("TESTING NEW RISK MANAGER SERVICE")
    print("="*80)
    
    # Test 1: Check initial status
    print("\n1. INITIAL STATUS")
    status = get_risk_status()
    print(f"Capital: {status['capital']}")
    print(f"Daily Loss: {status['daily_loss']}")
    print(f"Trade Count: {status['trade_count']}")
    print(f"Can Trade: {status['can_trade']}")
    
    # Test 2: Calculate position sizes
    print("\n2. POSITION SIZE CALCULATION")
    sl_10 = get_position_size(stop_loss_points=10)
    sl_20 = get_position_size(stop_loss_points=20)
    sl_5 = get_position_size(stop_loss_points=5)
    print(f"SL 10 points -> Lot size: {sl_10}")
    print(f"SL 20 points -> Lot size: {sl_20}")
    print(f"SL 5 points -> Lot size: {sl_5}")
    
    # Test 3: Simulate winning trade
    print("\n3. WINNING TRADE")
    if can_execute_trade():
        print("Trade allowed: YES")
        update_trade_result(pnl=1500)
    else:
        print("Trade allowed: NO (Risk Manager blocked)")
    
    # Test 4: Simulate losing trade
    print("\n4. LOSING TRADE")
    if can_execute_trade():
        print("Trade allowed: YES")
        update_trade_result(pnl=-800)
    else:
        print("Trade allowed: NO (Risk Manager blocked)")
    
    # Test 5: Simulate more losing trades to trigger limits
    print("\n5. MULTIPLE LOSING TRADES")
    for i in range(4):
        if can_execute_trade():
            print(f"Trade {i+1} allowed: YES")
            update_trade_result(pnl=-1000)
        else:
            print(f"Trade {i+1} allowed: NO (Risk Manager blocked)")
            break
    
    # Test 6: Check final status
    print("\n6. FINAL STATUS")
    status = get_risk_status()
    print(f"Capital: {status['capital']}")
    print(f"Daily Loss: {status['daily_loss']}")
    print(f"Trade Count: {status['trade_count']}")
    print(f"Stop Trading: {status['stop_trading']}")
    print(f"Can Trade: {status['can_trade']}")
    
    # Test 7: Try to trade when stopped
    print("\n7. ATTEMPT TRADE WHEN STOPPED")
    if can_execute_trade():
        print("Trade allowed: YES")
    else:
        print("Trade allowed: NO (Risk Manager blocked - CORRECT!)")
    
    # Test 8: Reset daily limits
    print("\n8. RESET DAILY LIMITS")
    reset_daily_limits()
    status = get_risk_status()
    print(f"After reset - Can Trade: {status['can_trade']}")
    print(f"After reset - Daily Loss: {status['daily_loss']}")
    print(f"After reset - Trade Count: {status['trade_count']}")
    
    print("\n" + "="*80)
    print("RISK MANAGER TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    test_risk_manager()
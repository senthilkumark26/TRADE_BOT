"""
Test script to demonstrate the live trade dashboard
"""

from services.trade_manager_service import TradeManagerService
import time

# Initialize Trade Manager
manager = TradeManagerService(max_daily_loss=3000)

print("Starting Trade Manager Dashboard Test...")
print("=" * 84)

# Add a test trade
test_trade = {
    'signal': 'CALL',
    'strike': 23500,
    'entry': 120.0,
    'sl': 114.0,
    'target': 138.0,
    'execution_score': 85,
    'lot_size': 1
}

print("\nAdding test trade...")
manager.add_trade('NIFTY', test_trade)
time.sleep(2)

# Simulate price updates
print("\nSimulating price updates...")
prices = [122, 125, 128, 130, 135, 140, 138, 136, 132, 128]

for i, price in enumerate(prices):
    print(f"\nUpdate {i+1}: Price = {price}")
    manager.update_price('NIFTY', price)
    manager.render_dashboard()
    time.sleep(1.5)

print("\nTest complete!")

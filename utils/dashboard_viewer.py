"""
Dashboard Viewer - Separate terminal dashboard for trade monitoring
Run this in a separate terminal to see the live dashboard without log interference
"""

import json
import time
import os
import sys
from datetime import datetime

# Shared data file
DASHBOARD_DATA_FILE = "dashboard_data.json"

def read_dashboard_data():
    """Read dashboard data from shared file"""
    try:
        if os.path.exists(DASHBOARD_DATA_FILE):
            with open(DASHBOARD_DATA_FILE, 'r') as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"Error reading dashboard data: {e}")
        return None

def render_dashboard():
    """Render live trade dashboard"""
    # Clear screen for better visibility
    os.system('cls' if os.name == 'nt' else 'clear')
    
    data = read_dashboard_data()
    
    if not data:
        print("\n" + "=" * 84)
        print(" DASHBOARD VIEWER - WAITING FOR DATA...")
        print("=" * 84)
        print("Make sure the trading bot is running and writing to dashboard_data.json")
        print("=" * 84)
        return
    
    trades = data.get("active", {})
    closed_trades = data.get("closed", [])
    total_pnl = data.get("total_pnl", 0)
    max_daily_loss = data.get("max_daily_loss", -3000)
    status = data.get("status", "UNKNOWN")
    last_update = data.get("last_update", "N/A")
    
    print("\n" + "=" * 84)
    print(" LIVE TRADE DASHBOARD (SEPARATE VIEWER)")
    print("=" * 84)
    print(f"Last Update: {last_update}")
    print("=" * 84)
    
    if not trades:
        print("NO ACTIVE TRADES - SYSTEM SCANNING FOR OPPORTUNITIES...")
    else:
        print(f"{'SYM':<8}{'SIG':<6}{'STRIKE':<12}{'EXPIRY':<12}{'ENTRY':<8}{'LTP':<8}{'P&L':<10}{'SL':<8}{'TSL':<8}{'TGT':<8}{'STATUS':<10}")
        print("-" * 84)
        
        for symbol, t in trades.items():
            tsl = t.get('tsl', t.get('sl', 0))
            print(f"{symbol:<8}{t['signal']:<6}{t['strike']:<12}{t.get('expiry', 'N/A'):<12}{t['entry']:<8.2f}{t['ltp']:<8.2f}{t['pnl']:<10.2f}{t.get('sl', 0):<8.2f}{tsl:<8.2f}{t.get('target', 0):<8.2f}{t['status']:<10}")
    
    print("-" * 84)
    print(f"TOTAL P&L: {total_pnl:.2f}")
    print(f"MAX LOSS LIMIT: {max_daily_loss:.2f}")
    print(f"STATUS: {status}")
    print("=" * 84)
    
    # Show closed trades if any
    if closed_trades:
        print("\n" + "=" * 84)
        print(" RECENTLY CLOSED TRADES")
        print("=" * 84)
        print(f"{'SYM':<8}{'SIG':<6}{'STRIKE':<12}{'ENTRY':<8}{'EXIT':<8}{'P&L':<10}{'REASON':<15}")
        print("-" * 84)
        
        # Show last 5 closed trades
        for trade in closed_trades[-5:]:
            print(f"{trade.get('symbol', 'N/A'):<8}{trade.get('signal', 'N/A'):<6}{trade.get('strike', 'N/A'):<12}{trade.get('entry', 0):<8.2f}{trade.get('ltp', 0):<8.2f}{trade.get('pnl', 0):<10.2f}{trade.get('close_reason', 'N/A'):<15}")
        print("=" * 84)

def main():
    """Main dashboard viewer loop"""
    print("Starting Dashboard Viewer...")
    print(f"Reading from: {DASHBOARD_DATA_FILE}")
    print("Press Ctrl+C to exit")
    print()
    
    try:
        while True:
            render_dashboard()
            time.sleep(2)  # Refresh every 2 seconds
    except KeyboardInterrupt:
        print("\nDashboard Viewer stopped.")

if __name__ == "__main__":
    main()
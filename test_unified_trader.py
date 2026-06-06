"""
Test Unified Trading System
Demonstrates how NSE and MCX use the same services and risk management
"""

from unified_trader import UnifiedTrader
from risk_wrapper import get_risk_status

def test_nse_integration():
    """Test NSE integration with shared services"""
    print("="*80)
    print("TESTING NSE INTEGRATION")
    print("="*80)
    
    # Initialize NSE trader
    nse_trader = UnifiedTrader(
        market_type="NSE",
        symbol="NIFTY",
        capital=100000
    )
    
    print("\n1. NSE Market Data")
    nse_data = nse_trader.get_market_data()
    print(f"NSE Data: {str(nse_data)[:200]}")  # Limit output to avoid unicode issues
    
    print("\n2. NSE Analysis (using shared MarketAnalyzer)")
    if nse_data:
        nse_analysis = nse_trader.analyze_trading_opportunity(nse_data)
        print(f"NSE Analysis: {str(nse_analysis)[:200]}")
    
    print("\n3. Risk Manager Status (Universal)")
    risk_status = get_risk_status()
    print(f"Risk Status: {risk_status}")
    
    print("\n" + "="*80)
    print("NSE INTEGRATION TEST COMPLETED")
    print("="*80)

def test_mcx_integration():
    """Test MCX integration with shared services"""
    print("\n" + "="*80)
    print("TESTING MCX INTEGRATION")
    print("="*80)
    
    # Initialize MCX trader
    mcx_trader = UnifiedTrader(
        market_type="MCX",
        symbol="CRUDEOILM",
        capital=100000
    )
    
    print("\n1. MCX Market Data")
    mcx_data = mcx_trader.get_market_data()
    print(f"MCX Data: {str(mcx_data)[:200]}")
    
    print("\n2. MCX Analysis (using shared MarketAnalyzer)")
    if mcx_data:
        mcx_analysis = mcx_trader.analyze_trading_opportunity(mcx_data)
        print(f"MCX Analysis: {str(mcx_analysis)[:200]}")
    
    print("\n3. Risk Manager Status (Universal)")
    risk_status = get_risk_status()
    print(f"Risk Status: {risk_status}")
    
    print("\n" + "="*80)
    print("MCX INTEGRATION TEST COMPLETED")
    print("="*80)

def test_unified_risk_management():
    """Test that risk management works for both markets"""
    print("\n" + "="*80)
    print("TESTING UNIVERSAL RISK MANAGEMENT")
    print("="*80)
    
    print("\n1. Initial Risk Status")
    from risk_wrapper import get_risk_status
    status = get_risk_status()
    print(f"Daily Loss: {status['daily_loss']}")
    print(f"Trade Count: {status['trade_count']}")
    print(f"Can Trade: {status['can_trade']}")
    
    print("\n2. Simulate NSE Trade Loss")
    from risk_wrapper import update_trade_result
    update_trade_result(-1500)
    
    print("\n3. Simulate MCX Trade Loss")
    update_trade_result(-1200)
    
    print("\n4. Updated Risk Status (Both markets affected)")
    status = get_risk_status()
    print(f"Daily Loss: {status['daily_loss']}")
    print(f"Trade Count: {status['trade_count']}")
    print(f"Can Trade: {status['can_trade']}")
    
    print("\n" + "="*80)
    print("UNIVERSAL RISK MANAGEMENT TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    print("="*80)
    print("UNIFIED TRADING SYSTEM TEST")
    print("="*80)
    print("This test demonstrates:")
    print("1. NSE uses shared services + universal risk management")
    print("2. MCX uses shared services + universal risk management")
    print("3. Risk Manager is universal across all markets")
    print("="*80)
    
    # Test NSE
    test_nse_integration()
    
    # Test MCX
    test_mcx_integration()
    
    # Test universal risk management
    test_unified_risk_management()
    
    print("\n" + "="*80)
    print("ALL TESTS COMPLETED")
    print("="*80)
"""
Test Unified Trader with MCX Signal Engine
Demonstrates the complete integration: MCX Signal Engine + Unified System
"""

from unified_trader import UnifiedTrader

def test_unified_mcx_integration():
    """Test Unified Trader with MCX Signal Engine integration"""
    print("="*80)
    print("UNIFIED TRADER + MCX SIGNAL ENGINE INTEGRATION TEST")
    print("="*80)
    
    # Initialize MCX trader (now includes MCX Signal Engine)
    mcx_trader = UnifiedTrader(
        market_type="MCX",
        symbol="CRUDEOILM",
        capital=100000
    )
    
    print("\n1. MCX MARKET DATA")
    mcx_data = mcx_trader.get_market_data()
    print(f"MCX Data: {str(mcx_data)[:200]}")
    
    print("\n2. MCX ANALYSIS (using shared MarketAnalyzer)")
    if mcx_data:
        mcx_analysis = mcx_trader.analyze_trading_opportunity(mcx_data)
        print(f"MCX Analysis: {str(mcx_analysis)[:200]}")
        
        print("\n3. EXECUTE TRADE (with MCX Signal Engine)")
        # This will now use MCX Signal Engine internally
        result = mcx_trader.execute_trade(mcx_analysis, mcx_data)
        print(f"Trade Result: {result}")
        
        if result.get('mcx_signal'):
            print("\n[MCX SIGNAL ENGINE OUTPUT]")
            mcx_signal = result['mcx_signal']
            print(f"  Signal: {mcx_signal.get('signal')}")
            print(f"  Confidence: {mcx_signal.get('confidence', 0):.2f}")
            print(f"  Reasoning: {mcx_signal.get('reasoning', [])}")
    
    print("\n" + "="*80)
    print("INTEGRATION TEST COMPLETED")
    print("="*80)

def test_nse_still_works():
    """Test that NSE still works without MCX Signal Engine"""
    print("\n" + "="*80)
    print("NSE INTEGRATION TEST (No MCX Signal Engine)")
    print("="*80)
    
    # Initialize NSE trader (should NOT use MCX Signal Engine)
    nse_trader = UnifiedTrader(
        market_type="NSE",
        symbol="NIFTY",
        capital=100000
    )
    
    print("\n1. NSE MARKET DATA")
    nse_data = nse_trader.get_market_data()
    print(f"NSE Data: {str(nse_data)[:200]}")
    
    print("\n2. NSE ANALYSIS (using shared MarketAnalyzer)")
    if nse_data:
        nse_analysis = nse_trader.analyze_trading_opportunity(nse_data)
        print(f"NSE Analysis: {str(nse_analysis)[:200]}")
        
        print("\n3. EXECUTE TRADE (NO MCX Signal Engine - should be None)")
        result = nse_trader.execute_trade(nse_analysis, nse_data)
        print(f"Trade Result: {result}")
        
        if result.get('mcx_signal') is None:
            print("\n[CORRECT] NSE does not use MCX Signal Engine")
        else:
            print("\n[ERROR] NSE should not use MCX Signal Engine")
    
    print("\n" + "="*80)
    print("NSE TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    print("="*80)
    print("COMPLETE INTEGRATION TEST")
    print("="*80)
    print("This test demonstrates:")
    print("1. MCX uses MCX Signal Engine + Unified System")
    print("2. NSE uses only Unified System (no MCX Signal Engine)")
    print("3. MCX Signal Engine enhances but does not replace existing system")
    print("="*80)
    
    # Test MCX integration
    test_unified_mcx_integration()
    
    # Test NSE still works
    test_nse_still_works()
    
    print("\n" + "="*80)
    print("ALL INTEGRATION TESTS COMPLETED")
    print("="*80)
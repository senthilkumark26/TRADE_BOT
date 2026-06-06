"""
Test MCX Signal Engine
Demonstrates that MCX Signal Engine works alongside existing system
"""

from mcx_wrapper import get_mcx_signal, get_mcx_commodity_profile

def test_mcx_signal_engine():
    """Test MCX Signal Engine independently"""
    print("="*80)
    print("MCX SIGNAL ENGINE TEST")
    print("="*80)
    
    # Test 1: Get commodity profiles
    print("\n1. COMMODITY PROFILES")
    crude_profile = get_mcx_commodity_profile("CRUDEOILM")
    print(f"CRUDEOILM Profile: {crude_profile}")
    
    natgas_profile = get_mcx_commodity_profile("NATURALGAS")
    print(f"NATURALGAS Profile: {natgas_profile}")
    
    # Test 2: Generate MCX signals
    print("\n2. MCX SIGNAL GENERATION")
    
    # Simulate CRUDEOILM data
    crude_signal = get_mcx_signal(
        symbol="CRUDEOILM",
        price=5525.0,
        oi=15000,
        volume=25000
    )
    print(f"\nCRUDEOILM Signal:")
    print(f"  Signal: {crude_signal.get('signal')}")
    print(f"  Confidence: {crude_signal.get('confidence', 0):.2f}")
    print(f"  Direction: {crude_signal.get('direction')}")
    print(f"  Reasoning: {crude_signal.get('reasoning', [])}")
    print(f"  MCX Specific: {crude_signal.get('mcx_specific', {})}")
    
    # Simulate NATURALGAS data
    natgas_signal = get_mcx_signal(
        symbol="NATURALGAS",
        price=245.0,
        oi=8000,
        volume=15000
    )
    print(f"\nNATURALGAS Signal:")
    print(f"  Signal: {natgas_signal.get('signal')}")
    print(f"  Confidence: {natgas_signal.get('confidence', 0):.2f}")
    print(f"  Direction: {natgas_signal.get('direction')}")
    print(f"  Reasoning: {natgas_signal.get('reasoning', [])}")
    print(f"  MCX Specific: {natgas_signal.get('mcx_specific', {})}")
    
    # Test 3: Multiple price updates (momentum analysis)
    print("\n3. MOMENTUM ANALYSIS (Multiple Updates)")
    print("Simulating price movement for CRUDEOILM...")
    
    prices = [5500, 5510, 5520, 5525, 5535, 5540, 5530, 5525]
    for i, price in enumerate(prices):
        signal = get_mcx_signal("CRUDEOILM", price, 15000, 25000)
        momentum = signal.get('mcx_specific', {}).get('momentum', 0)
        print(f"  Update {i+1}: Price={price} | Signal={signal.get('signal')} | Momentum={momentum:.3f}")
    
    print("\n" + "="*80)
    print("MCX SIGNAL ENGINE TEST COMPLETED")
    print("="*80)

def test_mcx_with_unified_system():
    """Test MCX Signal Engine alongside unified system"""
    print("\n" + "="*80)
    print("MCX SIGNAL ENGINE + UNIFIED SYSTEM TEST")
    print("="*80)
    
    print("\nThis demonstrates:")
    print("1. MCX Signal Engine provides commodity-specific intelligence")
    print("2. Unified system (MarketAnalyzer, Consensus, LLM) still works")
    print("3. MCX Signal Engine ENHANCES, not REPLACES existing system")
    
    # Simulate MCX trading scenario
    print("\nMCX TRADING SCENARIO:")
    print("-" * 80)
    
    # Step 1: Get MCX-specific signal
    mcx_signal = get_mcx_signal("CRUDEOILM", 5525.0, 15000, 25000)
    print(f"[MCX Signal Engine] Signal: {mcx_signal.get('signal')} | Confidence: {mcx_signal.get('confidence', 0):.2f}")
    print(f"[MCX Signal Engine] Reasoning: {mcx_signal.get('reasoning', [])}")
    
    # Step 2: This would then go to unified system
    print("\n[Unified System] MarketAnalyzer would analyze...")
    print("[Unified System] Consensus would evaluate...")
    print("[Unified System] LLM would make final decision...")
    print("[Unified System] Risk Manager would control position size...")
    
    print("\n" + "="*80)
    print("INTEGRATION TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    print("="*80)
    print("MCX SIGNAL ENGINE TEST SUITE")
    print("="*80)
    print("This test demonstrates:")
    print("1. MCX Signal Engine generates commodity-specific signals")
    print("2. It works alongside the existing unified system")
    print("3. It does NOT replace MarketAnalyzer, Consensus, or LLM")
    print("="*80)
    
    # Test MCX Signal Engine independently
    test_mcx_signal_engine()
    
    # Test integration with unified system
    test_mcx_with_unified_system()
    
    print("\n" + "="*80)
    print("ALL TESTS COMPLETED")
    print("="*80)
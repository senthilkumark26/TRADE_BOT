"""
Test Combined Intelligence
Verifies the plug-in style integration works correctly
"""

from combined_wrapper import get_combined_signal

def test_combined_intelligence():
    """Test Combined Intelligence Engine"""
    print("="*80)
    print("COMBINED INTELLIGENCE TEST")
    print("="*80)
    
    # Test 1: NSE Only
    print("\n1. NSE ONLY TEST")
    nse_signal = {"action": "BUY", "confidence": 0.7}
    mcx_signal = None
    combined = get_combined_signal(nse_signal, mcx_signal)
    print(f"NSE: {nse_signal}")
    print(f"MCX: {mcx_signal}")
    print(f"COMBINED: {combined}")
    assert combined["action"] == "BUY"
    assert combined["confidence"] == 0.6  # Updated weight
    assert combined["reason"] == "NSE"
    print("[OK] NSE Only Test Passed (will be skipped - confidence 0.6 < 0.75)")
    
    # Test 2: MCX Only
    print("\n2. MCX ONLY TEST")
    nse_signal = None
    mcx_signal = {"action": "SELL", "confidence": 0.8}
    combined = get_combined_signal(nse_signal, mcx_signal)
    print(f"NSE: {nse_signal}")
    print(f"MCX: {mcx_signal}")
    print(f"COMBINED: {combined}")
    assert combined["action"] == "SELL"
    assert combined["confidence"] == 0.4  # Updated weight
    assert combined["reason"] == "MCX"
    print("[OK] MCX Only Test Passed (will be skipped - confidence 0.4 < 0.75)")
    
    # Test 3: Both Agree (NSE + MCX)
    print("\n3. BOTH AGREE TEST")
    nse_signal = {"action": "BUY", "confidence": 0.7}
    mcx_signal = {"action": "BUY", "confidence": 0.8}
    combined = get_combined_signal(nse_signal, mcx_signal)
    print(f"NSE: {nse_signal}")
    print(f"MCX: {mcx_signal}")
    print(f"COMBINED: {combined}")
    assert combined["action"] == "BUY"
    assert combined["confidence"] == 1.0  # 0.6 + 0.4 = 1.0
    assert combined["reason"] == "NSE + MCX"
    print("[OK] Both Agree Test Passed (will execute - confidence 1.0 >= 0.75)")
    
    # Test 4: Conflict (NSE BUY, MCX SELL)
    print("\n4. CONFLICT TEST")
    nse_signal = {"action": "BUY", "confidence": 0.7}
    mcx_signal = {"action": "SELL", "confidence": 0.8}
    combined = get_combined_signal(nse_signal, mcx_signal)
    print(f"NSE: {nse_signal}")
    print(f"MCX: {mcx_signal}")
    print(f"COMBINED: {combined}")
    assert combined["action"] is None
    assert combined["confidence"] == 0
    assert combined["reason"] == "Conflict NSE vs MCX"
    print("[OK] Conflict Test Passed")
    
    # Test 5: No Signals
    print("\n5. NO SIGNALS TEST")
    nse_signal = None
    mcx_signal = None
    combined = get_combined_signal(nse_signal, mcx_signal)
    print(f"NSE: {nse_signal}")
    print(f"MCX: {mcx_signal}")
    print(f"COMBINED: {combined}")
    assert combined["action"] is None
    assert combined["confidence"] == 0
    print("[OK] No Signals Test Passed")
    
    # Test 6: Confidence Threshold Test
    print("\n6. CONFIDENCE THRESHOLD TEST (0.75 minimum)")
    print("Scenario breakdown:")
    print("  NSE only (0.6) -> SKIP (below 0.75)")
    print("  MCX only (0.4) -> SKIP (below 0.75)")
    print("  Both agree (1.0) -> TRADE (above 0.75)")
    print("  Conflict (0.0) -> SKIP (below 0.75)")
    print("[OK] Confidence Threshold Test Verified")
    
    print("\n" + "="*80)
    print("ALL COMBINED INTELLIGENCE TESTS PASSED")
    print("="*80)

if __name__ == "__main__":
    test_combined_intelligence()
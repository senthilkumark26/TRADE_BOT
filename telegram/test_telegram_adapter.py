"""
Test Telegram Signal Adapter
Verifies STRICT validation and signal parsing
"""

import re

def adapt_signal(message: str):
    """Copy of signal adapter for testing without telethon dependency"""
    message = message.upper()

    try:
        # SYMBOL
        symbol_match = re.search(r'(NIFTY|BANKNIFTY|FINNIFTY|SENSEX)', message)
        if not symbol_match:
            return None
        symbol = symbol_match.group(1)

        # STRIKE + TYPE
        strike_match = re.search(r'(\d{4,5})\s*(CE|PE)', message)
        if not strike_match:
            return None
        strike = int(strike_match.group(1))
        option_type = strike_match.group(2)

        # ENTRY
        entry_match = re.search(r'(ABOVE|ABV|@|AT)\s*(\d+)', message)
        if not entry_match:
            return None
        entry = float(entry_match.group(2))

        # SL
        sl_match = re.search(r'(SL|STOPLOSS)\s*(\d+)', message)
        if not sl_match:
            return None
        sl = float(sl_match.group(2))

        # TARGET
        target_match = re.search(r'(TARGET|TGT)\s*(\d+)', message)
        if not target_match:
            return None
        target = float(target_match.group(2))

        # STRICT VALIDATION
        if not (symbol and strike and option_type and entry and sl and target):
            return None

        return {
            "symbol": symbol,
            "strike": strike,
            "option_type": option_type,
            "entry": entry,
            "sl": sl,
            "target": target,
            "source": "TELEGRAM"
        }

    except Exception as e:
        print(f"[ADAPTER ERROR] {e}")
        return None

def test_signal_adapter():
    """Test the signal adapter with various inputs"""
    
    print("=" * 80)
    print("TESTING TELEGRAM SIGNAL ADAPTER")
    print("=" * 80)
    
    # Test 1: Valid signal
    print("\nTest 1: Valid NIFTY CE signal")
    signal1 = adapt_signal("NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180")
    print(f"Input: 'NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180'")
    print(f"Output: {signal1}")
    assert signal1 is not None, "Valid signal should not return None"
    assert signal1["symbol"] == "NIFTY", "Symbol should be NIFTY"
    assert signal1["strike"] == 23450, "Strike should be 23450"
    assert signal1["option_type"] == "CE", "Option type should be CE"
    assert signal1["entry"] == 150.0, "Entry should be 150.0"
    assert signal1["sl"] == 140.0, "SL should be 140.0"
    assert signal1["target"] == 180.0, "Target should be 180.0"
    assert signal1["source"] == "TELEGRAM", "Source should be TELEGRAM"
    print("[PASSED]")
    
    # Test 2: Valid BANKNIFTY PE signal
    print("\nTest 2: Valid BANKNIFTY PE signal")
    signal2 = adapt_signal("BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250")
    print(f"Input: 'BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250'")
    print(f"Output: {signal2}")
    assert signal2 is not None, "Valid signal should not return None"
    assert signal2["symbol"] == "BANKNIFTY", "Symbol should be BANKNIFTY"
    assert signal2["option_type"] == "PE", "Option type should be PE"
    print("[PASSED]")
    
    # Test 3: Invalid signal - missing symbol
    print("\nTest 3: Invalid signal - missing symbol")
    signal3 = adapt_signal("23450 CE ABOVE 150 SL 140 TARGET 180")
    print(f"Input: '23450 CE ABOVE 150 SL 140 TARGET 180'")
    print(f"Output: {signal3}")
    assert signal3 is None, "Invalid signal should return None"
    print("[PASSED]")
    
    # Test 4: Invalid signal - missing strike
    print("\nTest 4: Invalid signal - missing strike")
    signal4 = adapt_signal("NIFTY CE ABOVE 150 SL 140 TARGET 180")
    print(f"Input: 'NIFTY CE ABOVE 150 SL 140 TARGET 180'")
    print(f"Output: {signal4}")
    assert signal4 is None, "Invalid signal should return None"
    print("[PASSED]")
    
    # Test 5: Invalid signal - missing SL
    print("\nTest 5: Invalid signal - missing SL")
    signal5 = adapt_signal("NIFTY 23450 CE ABOVE 150 TARGET 180")
    print(f"Input: 'NIFTY 23450 CE ABOVE 150 TARGET 180'")
    print(f"Output: {signal5}")
    assert signal5 is None, "Invalid signal should return None"
    print("[PASSED]")
    
    # Test 6: Invalid signal - missing target
    print("\nTest 6: Invalid signal - missing target")
    signal6 = adapt_signal("NIFTY 23450 CE ABOVE 150 SL 140")
    print(f"Input: 'NIFTY 23450 CE ABOVE 150 SL 140'")
    print(f"Output: {signal6}")
    assert signal6 is None, "Invalid signal should return None"
    print("[PASSED]")
    
    # Test 7: Case insensitive
    print("\nTest 7: Case insensitive input")
    signal7 = adapt_signal("nifty 23450 ce above 150 sl 140 target 180")
    print(f"Input: 'nifty 23450 ce above 150 sl 140 target 180'")
    print(f"Output: {signal7}")
    assert signal7 is not None, "Valid signal should not return None"
    assert signal7["symbol"] == "NIFTY", "Symbol should be uppercase NIFTY"
    assert signal7["option_type"] == "CE", "Option type should be uppercase CE"
    print("[PASSED]")
    
    # Test 8: Different entry keywords
    print("\nTest 8: Different entry keywords (@)")
    signal8 = adapt_signal("NIFTY 23450 CE @ 150 SL 140 TARGET 180")
    print(f"Input: 'NIFTY 23450 CE @ 150 SL 140 TARGET 180'")
    print(f"Output: {signal8}")
    assert signal8 is not None, "Valid signal should not return None"
    assert signal8["entry"] == 150.0, "Entry should be 150.0"
    print("[PASSED]")
    
    # Test 9: Different SL keywords
    print("\nTest 9: Different SL keywords (STOPLOSS)")
    signal9 = adapt_signal("NIFTY 23450 CE ABOVE 150 STOPLOSS 140 TARGET 180")
    print(f"Input: 'NIFTY 23450 CE ABOVE 150 STOPLOSS 140 TARGET 180'")
    print(f"Output: {signal9}")
    assert signal9 is not None, "Valid signal should not return None"
    assert signal9["sl"] == 140.0, "SL should be 140.0"
    print("[PASSED]")
    
    # Test 10: Different target keywords
    print("\nTest 10: Different target keywords (TGT)")
    signal10 = adapt_signal("NIFTY 23450 CE ABOVE 150 SL 140 TGT 180")
    print(f"Input: 'NIFTY 23450 CE ABOVE 150 SL 140 TGT 180'")
    print(f"Output: {signal10}")
    assert signal10 is not None, "Valid signal should not return None"
    assert signal10["target"] == 180.0, "Target should be 180.0"
    print("[PASSED]")
    
    print("\n" + "=" * 80)
    print("ALL TESTS PASSED [SUCCESS]")
    print("=" * 80)
    print("\nSignal adapter is working correctly with STRICT validation")
    print("Ready for integration with Execution Brain")

if __name__ == "__main__":
    test_signal_adapter()

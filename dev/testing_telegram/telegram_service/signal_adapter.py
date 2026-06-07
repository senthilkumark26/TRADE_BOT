import re
import time

def adapt_signal(message: str):

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
            "source": "TELEGRAM",
            "timestamp": time.time()  # Add timestamp for expiry check
        }

    except Exception as e:
        print(f"[ADAPTER ERROR] {e}")
        return None

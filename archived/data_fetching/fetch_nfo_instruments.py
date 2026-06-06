"""
Fetch NFO (NSE & BSE) instruments from Zerodha and create option token mapping
This will allow us to use instrument tokens for LTP API calls instead of option symbols
"""

import json
from kiteconnect import KiteConnect

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

api_key = config.get('api_key', '')
access_token = config.get('access_token', '')

print("="*70)
print("ZERODHA NFO INSTRUMENTS FETCHER")
print("="*70)
print(f"API Key: {api_key}")
print(f"Access Token: {access_token[:20]}...")
print()

try:
    # Initialize Kite Connect
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    print("Fetching NFO instruments...")
    nfo_instruments = kite.instruments("NFO")
    print(f"Fetched {len(nfo_instruments)} NFO instruments")

    # Check available segments
    segments = set(inst.get('segment', 'UNKNOWN') for inst in nfo_instruments)
    print(f"Available segments in NFO: {segments}")

    # Filter for options only (NFO-OPT segment)
    nfo_options = [inst for inst in nfo_instruments if inst.get('segment') == 'NFO-OPT']
    print(f"Filtered to {len(nfo_options)} NFO options")

    # Use NFO options directly
    all_instruments = nfo_options
    
    print(f"\nTotal NFO instruments: {len(all_instruments)}")
    
    # Create option token mapping
    option_token_map = {}
    
    for instrument in all_instruments:
        try:
            name = instrument.get('name', '')
            strike = instrument.get('strike', 0)
            instrument_type = instrument.get('instrument_type', '')  # CE or PE
            expiry = instrument.get('expiry', '')
            instrument_token = instrument.get('instrument_token', '')
            trading_symbol = instrument.get('tradingsymbol', '')
            
            # Create option symbol key
            if name and strike and instrument_type:
                # Format: SYMBOLSTRIKECE (e.g., ITC2500CE)
                option_key = f"{name}{int(strike)}{instrument_type}"
                option_token_map[option_key] = {
                    'instrument_token': str(instrument_token),
                    'trading_symbol': trading_symbol,
                    'expiry': str(expiry) if expiry else None,  # Convert date to string
                    'name': name,
                    'strike': strike,
                    'type': instrument_type
                }
        except Exception as e:
            continue
    
    print(f"Created option token mapping: {len(option_token_map)} entries")

    # Save mapping to file
    with open('option_token_map.json', 'w') as f:
        json.dump(option_token_map, f, indent=4)

    print(f"Saved option token mapping to option_token_map.json")
    
    # Show some examples
    print("\n" + "="*70)
    print("OPTION TOKEN MAPPING EXAMPLES")
    print("="*70)
    
    count = 0
    for key, value in option_token_map.items():
        if count < 10:
            print(f"{key} -> Token: {value['instrument_token']} ({value['trading_symbol']})")
            count += 1
    
    print("="*70)
    print("SUCCESS! Option token mapping created")
    print("="*70)
    
except Exception as e:
    print(f"ERROR: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
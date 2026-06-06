"""
Update config.json with live instrument details from Zerodha NFO segment
Filters for current expiry (nearest to hardcoded current date)
"""

import json
from datetime import date
from kite_client import KiteClient

def update_config_from_zerodha_nfo():
    """Fetch live instrument details from NFO segment and update config.json"""

    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Initialize KiteClient
    kite_client = KiteClient(
        api_key=config.get("api_key", ""),
        access_token=config.get("access_token", "")
    )

    # Get instruments from NFO segment (FUTURES only, not options)
    print("Fetching instruments from Zerodha NFO segment...")
    instruments_list = kite_client.kite.instruments("NFO")
    
    # Filter for futures only (NFO-FUT segment), exclude options (NFO-OPT)
    futures_list = [inst for inst in instruments_list if inst.get('segment') == 'NFO-FUT']
    print(f"Filtered to {len(futures_list)} futures instruments (excluded options)")

    # Use system date (Zerodha returns all expiries, we filter to nearest)
    today = date.today()
    print(f"Using current date: {today}")

    # Map of our symbols to NFO trading symbols
    symbol_mapping = {
        "NIFTY": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "HDFCBANK": "HDFCBANK",
        "ICICIBANK": "ICICIBANK",
        "SBIN": "SBIN",
        "AXISBANK": "AXISBANK",
        "KOTAKBANK": "KOTAKBANK",
        "INFY": "INFY",
        "TCS": "TCS",
        "WIPRO": "WIPRO",
        "HCLTECH": "HCLTECH",
        "ITC": "ITC",
        "HINDUNILVR": "HINDUNILVR",
        "ONGC": "ONGC"
    }

    # Update config with live data
    updated_instruments = {}

    for symbol, name in symbol_mapping.items():
        # Find instrument in NFO futures list with nearest expiry
        matching_instruments = [inst for inst in futures_list if inst['name'] == name]
        
        if not matching_instruments:
            print(f"[X] {symbol}: No instruments found in NFO")
            continue
        
        # Sort by expiry distance from today
        def expiry_distance(inst):
            try:
                expiry = inst.get('expiry')
                if expiry:
                    return abs((expiry - today).days)
                return 999
            except:
                return 999
        
        matching_instruments.sort(key=expiry_distance)
        best_instrument = matching_instruments[0]
        
        # Get expiry info
        expiry = best_instrument.get('expiry')
        days_to_expiry = (expiry - today).days if expiry else 0
        
        updated_instruments[symbol] = {
            "lot_size": best_instrument['lot_size'],
            "tick_size": best_instrument['tick_size'],
            "exchange": best_instrument['exchange'],
            "symbol": best_instrument['tradingsymbol'],
            "instrument_token": best_instrument['instrument_token'],
            "expiry_type": "monthly",
            "expiry_day": "Tuesday"
        }
        
        print(f"[OK] {symbol}: {best_instrument['tradingsymbol']} | Expiry: {expiry} ({days_to_expiry} days) | Token: {best_instrument['instrument_token']}")

    # Update config
    config['instruments'] = updated_instruments

    # Save updated config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print("="*80)
    print("Config updated with live Zerodha NFO instrument details")
    print(f"Updated {len(updated_instruments)} instruments with current expiry")
    print("="*80)

    return config

if __name__ == "__main__":
    update_config_from_zerodha_nfo()
"""
Update config.json with live instrument details from Zerodha SDK
"""

import json
from kite.kite_client import KiteClient

def update_config_from_zerodha():
    """Fetch live instrument details and update config.json"""

    # Load config
    import os
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Initialize KiteClient
    kite_client = KiteClient(
        api_key=config.get("api_key", ""),
        access_token=config.get("access_token", "")
    )

    # Get instruments from Zerodha
    print("Fetching instruments from Zerodha SDK...")
    instruments_list = kite_client.kite.instruments()

    # Map of our symbols to Zerodha trading symbols
    symbol_mapping = {
        "NIFTY": "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
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

    for symbol, trading_symbol in symbol_mapping.items():
        # Find instrument in Zerodha list
        for instrument in instruments_list:
            if instrument['tradingsymbol'] == trading_symbol:
                updated_instruments[symbol] = {
                    "lot_size": instrument['lot_size'],
                    "tick_size": instrument['tick_size'],
                    "exchange": instrument['exchange'],
                    "symbol": instrument['tradingsymbol'],
                    "instrument_token": instrument['instrument_token']
                }
                print(f"[OK] {symbol}: Lot Size={instrument['lot_size']}, Tick Size={instrument['tick_size']}")
                break
        else:
            print(f"[X] {symbol}: Not found in Zerodha instruments")

    # Update config
    config['instruments'] = updated_instruments

    # Save updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print("="*80)
    print("Config updated with live Zerodha instrument details")
    print(f"Updated {len(updated_instruments)} instruments")

    return config

if __name__ == "__main__":
    update_config_from_zerodha()
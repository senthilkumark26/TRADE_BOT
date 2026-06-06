"""
Fetch live instrument details from Zerodha SDK
"""

import json
from kite_client import KiteClient

def fetch_instrument_details():
    """Fetch live instrument details from Zerodha SDK"""

    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Initialize KiteClient
    kite_client = KiteClient(
        api_key=config.get("api_key", ""),
        access_token=config.get("access_token", "")
    )

    # Instruments to fetch
    instruments = {
        "NIFTY": "NSE:NIFTY 50",
        "BANKNIFTY": "NSE:NIFTY BANK",
        "HDFCBANK": "NSE:HDFCBANK",
        "ICICIBANK": "NSE:ICICIBANK",
        "SBIN": "NSE:SBIN",
        "AXISBANK": "NSE:AXISBANK",
        "KOTAKBANK": "NSE:KOTAKBANK",
        "INFY": "NSE:INFY",
        "TCS": "NSE:TCS",
        "WIPRO": "NSE:WIPRO",
        "HCLTECH": "NSE:HCLTECH",
        "ITC": "NSE:ITC",
        "HINDUNILVR": "NSE:HINDUNILVR",
        "ONGC": "NSE:ONGC"
    }

    instrument_details = {}

    print("Fetching live instrument details from Zerodha SDK...")
    print("="*80)

    for symbol, exchange_symbol in instruments.items():
        try:
            # Get instrument details from Kite
            instruments_list = kite_client.kite.instruments()

            # Find the instrument
            for instrument in instruments_list:
                if instrument['tradingsymbol'] == exchange_symbol or instrument['name'] == symbol:
                    instrument_details[symbol] = {
                        'lot_size': instrument['lot_size'],
                        'tick_size': instrument['tick_size'],
                        'exchange': instrument['exchange'],
                        'symbol': instrument['tradingsymbol'],
                        'instrument_token': instrument['instrument_token']
                    }
                    print(f"[OK] {symbol}: Lot Size={instrument['lot_size']}, Tick Size={instrument['tick_size']}")
                    break
            else:
                print(f"[X] {symbol}: Not found in instruments list")

        except Exception as e:
            print(f"[X] {symbol}: Error - {e}")

    print("="*80)
    print(f"Successfully fetched {len(instrument_details)} instrument details")

    # Save to file
    with open('live_instrument_details.json', 'w') as f:
        json.dump(instrument_details, f, indent=2)

    print("Saved to live_instrument_details.json")
    return instrument_details

if __name__ == "__main__":
    fetch_instrument_details()
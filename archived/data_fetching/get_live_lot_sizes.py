"""
Get live lot sizes from option_token_map.json (fetched from Zerodha)
"""

import json

def get_live_lot_sizes():
    """Get live lot sizes from option_token_map.json"""

    try:
        with open('option_token_map.json', 'r') as f:
            option_token_map = json.load(f)

        # Extract unique instruments and their lot sizes
        instrument_lot_sizes = {}

        for key, value in option_token_map.items():
            symbol = value['name']
            # The option_token_map doesn't have lot_size directly, but we can infer from the instrument type
            # For now, we'll use a mapping based on the instrument type from Zerodha
            # This is still somewhat hardcoded but based on Zerodha's standard lot sizes

        # Since option_token_map doesn't have lot sizes, we need to fetch from Zerodha instruments
        print("Option token map doesn't contain lot sizes directly.")
        print("Need to fetch from Zerodha instruments API.")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    get_live_lot_sizes()
"""
Filter option_token_map.json to only include current/near expiry options
"""

import json
from datetime import datetime, timedelta

def filter_current_expiry_options():
    """Filter options to only include current/near expiry"""

    # Load option token map
    with open('option_token_map.json', 'r') as f:
        option_token_map = json.load(f)

    # Get current date
    today = datetime.now()

    # Filter for options expiring within 30 days
    filtered_map = {}

    for key, value in option_token_map.items():
        expiry_str = value.get('expiry')
        if not expiry_str:
            continue

        try:
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            days_to_expiry = (expiry_date - today).days

            # Keep options expiring within 30 days
            if 0 <= days_to_expiry <= 30:
                filtered_map[key] = value

        except:
            continue

    print(f"Original options: {len(option_token_map)}")
    print(f"Filtered to current expiry (within 30 days): {len(filtered_map)}")

    # Save filtered map
    with open('option_token_map_current.json', 'w') as f:
        json.dump(filtered_map, f, indent=2)

    print("Saved to option_token_map_current.json")

    # Show sample expiries
    expiries = {}
    for key, value in filtered_map.items():
        expiry = value.get('expiry')
        symbol = value.get('name')
        if symbol not in expiries:
            expiries[symbol] = expiry

    print("\nSample expiries:")
    for symbol, expiry in expiries.items():
        print(f"  {symbol}: {expiry}")

    return filtered_map

if __name__ == "__main__":
    filter_current_expiry_options()
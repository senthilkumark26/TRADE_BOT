"""
Select best expiry options - nearest expiry with strikes close to spot price
"""

import json
from datetime import datetime, timedelta

def get_best_expiry_options():
    """Select options from nearest expiry that has strikes close to current spot"""

    # Load option token map
    with open('option_token_map.json', 'r') as f:
        option_token_map = json.load(f)

    # Get current date
    today = datetime.now()

    # Group options by expiry
    expiry_groups = {}
    for key, value in option_token_map.items():
        expiry_str = value.get('expiry')
        if not expiry_str:
            continue

        try:
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            days_to_expiry = (expiry_date - today).days

            # Only consider expiries within 90 days
            if 0 <= days_to_expiry <= 90:
                if expiry_str not in expiry_groups:
                    expiry_groups[expiry_str] = []
                expiry_groups[expiry_str].append(value)

        except:
            continue

    print(f"Found {len(expiry_groups)} expiry groups within 90 days")

    # For each instrument, find the best expiry
    instruments = ['NIFTY', 'BANKNIFTY', 'HDFCBANK', 'ICICIBANK', 'SBIN',
                   'AXISBANK', 'KOTAKBANK', 'INFY', 'TCS', 'WIPRO', 'HCLTECH',
                   'ITC', 'HINDUNILVR', 'ONGC']

    best_map = {}

    for instrument in instruments:
        best_expiry = None
        best_distance = float('inf')

        for expiry_str, options in expiry_groups.items():
            # Get strikes for this instrument and expiry
            strikes = [opt['strike'] for opt in options if opt['name'] == instrument]

            if not strikes:
                continue

            # Get current spot price (approximate from middle of strike range)
            min_strike = min(strikes)
            max_strike = max(strikes)
            mid_strike = (min_strike + max_strike) / 2

            # Calculate distance from expected spot (use mid_strike as proxy)
            # For now, we'll prefer nearer expiry with reasonable strike range
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            days_to_expiry = (expiry_date - today).days

            # Score: prefer nearer expiry, but also want good strike coverage
            score = days_to_expiry

            if score < best_distance:
                best_distance = score
                best_expiry = expiry_str

        if best_expiry:
            # Add all options for this instrument from best expiry
            for opt in expiry_groups[best_expiry]:
                if opt['name'] == instrument:
                    key = f"{opt['name']}{int(opt['strike'])}{opt['type']}"
                    best_map[key] = opt

            print(f"{instrument}: Best expiry = {best_expiry} ({best_distance} days)")

    print(f"\nFiltered to best expiry: {len(best_map)} contracts")

    # Save filtered map
    with open('option_token_map_best.json', 'w') as f:
        json.dump(best_map, f, indent=2)

    print("Saved to option_token_map_best.json")
    return best_map

if __name__ == "__main__":
    get_best_expiry_options()
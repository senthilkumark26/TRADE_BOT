"""
Filter options by expiry type based on config (2026 NSE Structure):
- NIFTY: Weekly expiry (every Tuesday) - from config expiry_type: "weekly"
- Other instruments: Monthly expiry (last Tuesday of month) - from config expiry_type: "monthly"
Note: In 2026, NSE changed expiry day from Thursday to Tuesday for all contracts
"""

import json
from datetime import datetime, timedelta

def filter_options_by_expiry_type():
    """Filter options based on instrument expiry_type from config"""

    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)

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

    # Filter for each instrument based on config expiry_type
    filtered_map = {}

    instruments_config = config.get('instruments', {})

    for instrument, instrument_config in instruments_config.items():
        expiry_type = instrument_config.get('expiry_type', 'monthly')
        best_expiry = None
        best_distance = float('inf')

        for expiry_str, options in expiry_groups.items():
            # Get strikes for this instrument and expiry
            strikes = [opt['strike'] for opt in options if opt['name'] == instrument]

            if not strikes:
                continue

            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            days_to_expiry = (expiry_date - today).days

            # Score based on expiry_type preference
            if expiry_type == 'weekly':
                # For weekly (Tuesday expiry in 2026), prefer 1-7 days
                if 1 <= days_to_expiry <= 7:
                    score = days_to_expiry
                else:
                    score = days_to_expiry + 50  # Penalize non-weekly
            else:  # monthly
                # For monthly (Tuesday expiry in 2026), prefer 20-40 days
                if 20 <= days_to_expiry <= 40:
                    score = days_to_expiry
                else:
                    score = days_to_expiry + 50  # Penalize non-monthly

            if score < best_distance:
                best_distance = score
                best_expiry = expiry_str

        if best_expiry:
            # Add all options for this instrument from best expiry
            for opt in expiry_groups[best_expiry]:
                if opt['name'] == instrument:
                    key = f"{opt['name']}{int(opt['strike'])}{opt['type']}"
                    filtered_map[key] = opt

            print(f"{instrument} ({expiry_type}): Best expiry = {best_expiry} ({best_distance} days)")

    print(f"\nFiltered to {len(filtered_map)} contracts (based on config expiry_type)")

    # Save filtered map
    with open('option_token_map_filtered.json', 'w') as f:
        json.dump(filtered_map, f, indent=2)

    print("Saved to option_token_map_filtered.json")

    # Show summary
    weekly_count = 0
    monthly_count = 0

    for key in filtered_map.keys():
        # Extract instrument name from key (e.g., "NIFTY23450CE" -> "NIFTY")
        instrument_name = None
        for inst in instruments_config.keys():
            if key.startswith(inst):
                instrument_name = inst
                break

        if instrument_name:
            expiry_type = instruments_config[instrument_name].get('expiry_type', 'monthly')
            if expiry_type == 'weekly':
                weekly_count += 1
            else:
                monthly_count += 1

    print(f"\nSummary:")
    print(f"  Weekly options: {weekly_count}")
    print(f"  Monthly options: {monthly_count}")

    return filtered_map

if __name__ == "__main__":
    filter_options_by_expiry_type()
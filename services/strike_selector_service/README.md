# Strike Selector Service

## Overview
Professional-grade strike selection engine that automatically selects the best option contracts for trading.

## Features
- **Automatic Expiry Selection**: Chooses between weekly/monthly expiries based on liquidity
- **Liquidity Filtering**: Avoids illiquid options with low OI/volume
- **Smart Ranking**: Ranks strikes by OI + Volume with ATM preference boost
- **Support/Resistance Alignment**: Aligns with OptionStar institutional levels
- **Professional Execution**: Only trades liquid, tradeable contracts

## Key Functions

### `select_best_expiry(instruments, symbol)`
- Analyzes all available expiries
- Ranks by liquidity (OI proxy)
- Selects best expiry automatically

### `filter_liquid_strikes(option_chain, spot)`
- Filters to ATM range (3%)
- Applies minimum OI threshold (10,000)
- Applies minimum volume threshold (500)
- Returns only liquid strikes

### `rank_strikes(strikes, spot)`
- Calculates score = OI + Volume
- Applies 50% boost for ATM ± 100 points
- Returns ranked list

### `select_best_strike(ranked_strikes, signal, optionstar_data)`
- CALL: Selects strike above support
- PUT: Selects strike below resistance
- Returns formatted strike (e.g., "23350 CE")

### `select_strike_complete(...)`
- Complete selection flow
- Returns full strike information

## Configuration
- `atm_range_percent`: 0.03 (3% ATM range)
- `min_oi_threshold`: 10,000 (minimum OI)
- `min_volume_threshold`: 500 (minimum volume)
- `atm_boost_range`: 100 (ATM boost range)

## Integration
```python
from services.strike_selector_service import StrikeSelectorService

strike_selector = StrikeSelectorService()

result = strike_selector.select_strike_complete(
    instruments=instruments,
    symbol="NIFTY",
    option_chain=option_chain,
    spot=23350.0,
    signal="CALL",
    optionstar_data=optionstar_data
)
```

## Benefits
- ✅ Correct expiry selection
- ✅ High liquidity contracts only
- ✅ No illiquid options
- ✅ Aligned with institutional levels
- ✅ Professional execution quality

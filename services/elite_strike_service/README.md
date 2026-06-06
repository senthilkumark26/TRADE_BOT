# Elite Strike Service

## Overview
Professional strike optimization layer that enhances strike selection with smart shifting, gamma preference, and dynamic lot sizing. Works as a non-intrusive enhancer on top of Strike Selector Service.

## Features
- **Smart Strike Shifting**: Adjusts strike based on price movement (price run adjustment)
- **Gamma-Style Selection**: Prefers ATM strikes for better gamma exposure
- **Dynamic Lot Sizing**: Confidence-based lot sizing (1-3 lots based on score)
- **Non-Intrusive**: Enhances without modifying core logic
- **Independent Microservice**: Runs as separate service

## Key Functions

### `adjust_strike(signal, strike, spot)`
- Adjusts strike if price has moved significantly
- CALL: Shifts ITM to ATM if spot > strike
- PUT: Shifts ITM to ATM if spot < strike
- Shift step: 50 points

### `gamma_preference(strikes, spot)`
- Selects top N closest strikes to ATM
- Improves gamma exposure
- Default: Top 3 ATM strikes

### `dynamic_lot(score)`
- Calculates lot size based on confidence score
- Score ≥ 80: 3 lots (high confidence)
- Score ≥ 65: 2 lots (medium confidence)
- Score < 65: 1 lot (low confidence)

### `optimize(symbol, signal, strike, spot, ranked_strikes, score)`
- Main optimizer function
- Combines gamma preference, strike shifting, and dynamic lot sizing
- Returns optimized strike and lot size

## Architecture

**Flow:**
```
Strike Selector Service (Primary Selection)
    ↓
Execution Brain (Decision)
    ↓
Elite Strike Service (Optimization) ← NEW
    ↓
Trade Manager (Execution)
```

**Elite Strike Service Role:**
- Enhances already-selected strike
- Does NOT replace Strike Selector Service
- Non-intrusive optimization layer

## Configuration
- `strike_shift_step`: 50 (points to shift strike)
- `atm_preference_count`: 3 (number of ATM strikes to consider)
- `high_confidence_threshold`: 80 (score for 3 lots)
- `medium_confidence_threshold`: 65 (score for 2 lots)

## Integration
```python
from services.elite_strike_service import EliteStrikeService

elite_service = EliteStrikeService()
elite_service.start()

# After Execution Brain decision
optimized = elite_service.optimize(
    symbol="NIFTY",
    signal="CALL",
    strike="23500 CE",
    spot=23520,
    ranked_strikes=ranked_strikes,
    score=85
)

# Use optimized strike and lot
final_strike = optimized["strike"]
lot_size = optimized["lot"]
```

## Benefits
- ✅ Smart strike adjustment for price runs
- ✅ ATM-focused gamma selection
- ✅ Confidence-based lot sizing
- ✅ Non-intrusive enhancement
- ✅ Professional optimization layer
- ✅ No core logic modification

## Statistics
The service tracks:
- Total optimizations performed
- Strike shifts performed
- Lot size adjustments (1/2/3 lot counts)

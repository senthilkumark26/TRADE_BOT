# Breakout Entry Service

**Version:** 1.0.0  
**Protection Level:** CRITICAL  
**Status:** PRODUCTION READY

## Overview

Standalone microservice for breakout detection and entry timing. Decoupled from Engine1 to allow independent updates and testing without affecting the main market analyzer.

## Capabilities

- **Breakout Detection**: Identifies BULLISH/BEARISH/NONE breakout directions
- **Strength Classification**: Categorizes breakouts as STRONG/MODERATE/WEAK
- **Entry Timing**: Determines EARLY vs CONFIRMED entry points
- **Strike Selection**: Recommends OTM vs ATM strike selection
- **Confirmation Logic**: 2-tick confirmation for moderate breakouts

## Service Architecture

### Dependencies
- None (standalone service)

### Dependents
- engine1_market_analyzer
- trading_bot  
- market_analyzer

## API Methods

### `confirm_breakout(symbol, breakout)`
2-tick confirmation for moderate breakouts.

**Parameters:**
- `symbol` (str): Trading symbol
- `breakout` (str): Current breakout direction (BULLISH/BEARISH/NONE)

**Returns:**
- Confirmed breakout direction or "NONE"

### `get_entry(symbol, breakout, strength, spot, vwap)`
Entry decision based on breakout strength.

**Parameters:**
- `symbol` (str): Trading symbol
- `breakout` (str): Breakout direction (BULLISH/BEARISH/NONE)
- `strength` (str): Breakout strength (STRONG/MODERATE/WEAK)
- `spot` (float): Current spot price
- `vwap` (float): Current VWAP

**Returns:**
- Dictionary with `signal`, `entry_type`, and `strike`

## Entry Logic

### STRONG Breakouts
- **Entry Type**: EARLY
- **Strike**: OTM
- **Confirmation**: Not required

### MODERATE Breakouts  
- **Entry Type**: CONFIRMED
- **Strike**: ATM
- **Confirmation**: 2-tick confirmation required

### WEAK Breakouts
- **Entry Type**: NO TRADE
- **Strike**: None
- **Confirmation**: N/A

## Usage Example

```python
from services.breakout_entry_service import BreakoutEntryService

# Initialize service
breakout_service = BreakoutEntryService()

# Get entry decision
entry_decision = breakout_service.get_entry(
    symbol="NIFTY",
    breakout="BULLISH", 
    strength="STRONG",
    spot=23400.0,
    vwap=23380.0
)

# Result: {"signal": "BUY CE", "entry_type": "EARLY", "strike": "OTM"}
```

## Service Info

```python
service_info = breakout_service.get_service_info()
```

Returns:
```json
{
    "service_name": "breakout_entry_service",
    "version": "1.0.0",
    "dependencies": [],
    "dependents": ["engine1_market_analyzer", "trading_bot", "market_analyzer"],
    "protection_level": "CRITICAL",
    "capabilities": [
        "breakout_detection",
        "strength_classification",
        "entry_timing", 
        "strike_selection",
        "confirmation_logic"
    ]
}
```

## Benefits of Microservice Architecture

1. **Independent Updates**: Can enhance breakout logic without touching Engine1
2. **Isolated Testing**: Test breakout detection separately from market analysis
3. **Version Control**: Track changes to breakout logic independently
4. **Service Discovery**: Other services can discover and use this service
5. **Protection Level**: CRITICAL level ensures changes are carefully reviewed

## Future Enhancements

- Fake breakout detection
- Liquidity sweep identification  
- Momentum validation
- Multi-timeframe breakout confirmation

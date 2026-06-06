# OptionStar Service - Protected Microservice

## Overview
OptionStar is a **CRITICAL** protected microservice that provides institutional OI analysis for the trading system. It calculates support/resistance levels using option chain open interest data to identify dealer positioning and liquidity walls.

## Protection Level
**CRITICAL** - This service cannot be deleted without explicit approval and requires dependency resolution before modification.

## Dependencies
- `engine1_market_analyzer` - Engine1 uses OptionStar for institutional wall detection

## Dependents (Services that depend on OptionStar)
- `single_strike_trader` - Uses OptionStar for opportunity selection
- `trading_bot` - Uses OptionStar for trade generation
- `market_analyzer` - Uses OptionStar for market analysis
- `engine1_market_analyzer` - Uses OptionStar for signal generation

## Service Architecture

### Core Service
- **Location**: `services/optionstar_service/service.py`
- **Protection**: CRITICAL (cannot be deleted)
- **Operations**: READ only (no modifications allowed without approval)

### Public Wrapper
- **Location**: `optionstar.py`
- **Protection**: HIGH (can be modified but deletion requires approval)
- **Purpose**: Maintains backward compatibility while delegating to protected service

## API

### Main Functions

#### `calculate_institutional_walls(option_chain_data, spot_price)`
Calculates institutional support/resistance using Option Chain Open Interest.

**Returns:**
```python
{
    "spot_price": float,
    "resistance": {
        "strike": int,
        "oi": int,
        "distance": float
    },
    "support": {
        "strike": int,
        "oi": int,
        "distance": float
    },
    "trend_bias": str  # "BULLISH", "BEARISH", "NEUTRAL"
}
```

#### `generate_trade(current_price, vwap, option_chain, symbol)`
Generates trade setup using institutional OI analysis.

**Returns:**
```python
{
    "direction": str,  # "CALL" or "PUT"
    "strike": int,
    "spot": float,
    "vwap": float,
    "support": int,
    "resistance": int,
    "reason": str,
    "institutional_data": dict
}
```

#### `generate_mock_option_chain(current_price)`
Generates mock option chain for testing/paper trading.

## Service Health

### Health Check
```python
from services.optionstar_service import get_optionstar_service

service = get_optionstar_service()
health = service.health_check()
print(health)
```

### Service Info
```python
from services.optionstar_service import get_optionstar_service

service = get_optionstar_service()
info = service.get_service_info()
print(info)
```

## Dependency Management

### Adding New Dependencies
To add a new dependency to OptionStar:

1. Update `dependencies` list in `service.py`
2. Update Code Manager critical files registry
3. Ensure all dependents are notified
4. Test dependency resolution

### Removing Dependencies
To remove a dependency:

1. Check all dependents still work without the dependency
2. Update `dependencies` list in `service.py`
3. Update Code Manager registry
4. Get approval for modification (CRITICAL service)

## Code Manager Integration

### Registration
This service is registered with the Code Manager as:
- **Protection Level**: CRITICAL
- **Allowed Operations**: READ only
- **Dependencies**: Tracked and enforced
- **Dependents**: Tracked for impact analysis

### Deletion Protection
Any attempt to delete this service will:
1. Check for active dependents
2. Require explicit approval
3. Log to audit trail
4. Block deletion if dependents exist

### Modification Protection
Any attempt to modify this service will:
1. Check dependency impact
2. Require explicit approval
3. Log to audit trail
4. Validate changes don't break dependents

## Usage Examples

### Basic Usage
```python
from optionstar import calculate_institutional_walls

option_chain_data = {
    "calls": [{"strikePrice": 23500, "openInterest": 15000000}],
    "puts": [{"strikePrice": 23400, "openInterest": 12000000}]
}

walls = calculate_institutional_walls(option_chain_data, 23450)
print(f"Support: {walls['support']['strike']}")
print(f"Resistance: {walls['resistance']['strike']}")
print(f"Bias: {walls['trend_bias']}")
```

### Direct Service Access
```python
from services.optionstar_service import get_optionstar_service

service = get_optionstar_service()
trade = service.generate_trade(23450, 23450, option_chain, "NIFTY")
```

## Monitoring

### Service Status
The service automatically tracks:
- Health status
- Last health check time
- Dependency status
- Dependent status

### Logs
All service operations are logged with:
- Service name
- Version
- Timestamp
- Operation type

## Troubleshooting

### Service Not Available
If you see "OptionStar microservice not available":
1. Check if `services/optionstar_service/` directory exists
2. Verify service.py is present
3. Check Python path includes services directory
4. Review import errors in logs

### Dependency Issues
If dependency resolution fails:
1. Check if all dependencies are installed
2. Verify dependency versions are compatible
3. Review Code Manager dependency registry
4. Check for circular dependencies

## Version History
- **1.0.0** - Initial protected microservice implementation
  - Added institutional OI analysis
  - Added dependency tracking
  - Added Code Manager integration
  - Added health monitoring

## Support
For issues or questions about OptionStar service:
1. Check service health status
2. Review dependency configuration
3. Check Code Manager audit logs
4. Verify all dependents are compatible
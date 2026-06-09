# MCX Leverage Settings Summary

**Last Updated:** 2026-06-09  
**Purpose:** Document all leverage and risk management parameters for MCX commodities trading

## Quick Reference Table

| Commodity | Lot Size | Leverage | Risk/Trade | Max Lots | Margin/Lot | Max Trades/Day | Min Vol | Min OI | Max Spread |
|-----------|----------|----------|------------|----------|------------|----------------|---------|--------|------------|
| CRUDEOIL  | 100      | 10x      | 1%         | 5        | INR 50,000 | 2              | 10      | 100    | 10%        |
| NATGAS    | 1250     | 8x       | 0.8%       | 2        | INR 25,000 | 1              | 5       | 50     | 15%        |
| GOLDM     | 10       | 12x      | 1.5%       | 10       | INR 30,000 | 3              | 10      | 100    | 8%         |
| SILVERM   | 5        | 15x      | 1.2%       | 5        | INR 25,000 | 2              | 5       | 50     | 12%        |

## Detailed Settings

### CRUDEOIL (Crude Oil)
- **Lot Size:** 100 barrels per contract
- **Effective Leverage:** 10x
- **Risk Per Trade:** 1% of capital
- **Max Position:** 5 lots
- **Margin Required:** INR 50,000 per lot
- **Max Trades/Day:** 2
- **Volatility:** Base (1.0x multiplier)
- **Max Hold Time:** 30 minutes
- **Characteristics:** Moderate volatility, liquid
- **Outer Shell Thresholds:**
  - Min Volume: 10
  - Min OI: 100
  - Max Spread: 10%
  - Max Strike Distance: 10%

### NATGAS (Natural Gas)
- **Lot Size:** 1250 mmBtu per contract
- **Effective Leverage:** 8x (conservative)
- **Risk Per Trade:** 0.8% of capital (very conservative)
- **Max Position:** 2 lots (limited due to volatility)
- **Margin Required:** INR 25,000 per lot
- **Max Trades/Day:** 1 (limited due to high volatility)
- **Volatility:** High (1.5x multiplier)
- **Max Hold Time:** 15 minutes (fast moves)
- **Characteristics:** High volatility, less liquid
- **Outer Shell Thresholds:**
  - Min Volume: 5
  - Min OI: 50
  - Max Spread: 15%
  - Max Strike Distance: 15%

### GOLDM (Gold Mini)
- **Lot Size:** 10 grams per contract
- **Effective Leverage:** 12x
- **Risk Per Trade:** 1.5% of capital
- **Max Position:** 10 lots
- **Margin Required:** INR 30,000 per lot
- **Max Trades/Day:** 3
- **Volatility:** Low (0.8x multiplier)
- **Max Hold Time:** 45 minutes (slower moves)
- **Characteristics:** Lower volatility, stable
- **Outer Shell Thresholds:**
  - Min Volume: 10
  - Min OI: 100
  - Max Spread: 8%
  - Max Strike Distance: 8%

### SILVERM (Silver Mini)
- **Lot Size:** 5 kg per contract
- **Effective Leverage:** 15x (highest)
- **Risk Per Trade:** 1.2% of capital
- **Max Position:** 5 lots
- **Margin Required:** INR 25,000 per lot
- **Max Trades/Day:** 2
- **Volatility:** Base (1.0x multiplier)
- **Max Hold Time:** 30 minutes
- **Characteristics:** Moderate volatility, high leverage
- **Outer Shell Thresholds:**
  - Min Volume: 5
  - Min OI: 50
  - Max Spread: 12%
  - Max Strike Distance: 12%

## Global Risk Limits

### Capital Management
- **Total Capital:** INR 100,000
- **Max Total Risk:** 5% of capital (INR 5,000)
- **Max Total Exposure:** 20% of capital (INR 20,000)
- **Max Effective Leverage:** 15x across all positions
- **Margin Usage Limit:** 50% of capital

### Position Limits
- **Max Total Positions:** 4 across all symbols
- **Max Same Symbol Positions:** 1 per symbol
- **Max Concurrent Exposure:** 20% of capital

### Risk Controls
- **Daily Loss Limit:** INR -3,000 (kill switch)
- **Max Drawdown:** 10% of capital
- **Consecutive Loss Limit:** 3 trades
- **Leverage Reduction:** 50% after loss

## Position Sizing Example

**Example: CRUDEOIL Trade**
- Capital: INR 100,000
- Entry Price: INR 262.00
- Stop Loss: INR 222.70 (15%)
- Risk Per Trade: 1% = INR 1,000
- **Calculated Position:** 1 lot
- Total Margin: INR 50,000
- Margin Usage: 50%

## How to Adjust Leverage

### To Increase Leverage (More Aggressive)
1. Increase `max_position_size`
2. Increase `effective_leverage`
3. Decrease `risk_per_trade_pct`
4. Increase `max_trades_per_day`

### To Decrease Leverage (More Conservative)
1. Decrease `max_position_size`
2. Decrease `effective_leverage`
3. Increase `risk_per_trade_pct`
4. Decrease `max_trades_per_day`

### To Adjust Outer Shell Thresholds
1. **Min Volume:** Increase for stricter filtering, decrease for more opportunities
2. **Min OI:** Increase for stricter filtering, decrease for more opportunities
3. **Max Spread:** Decrease for tighter spread requirements, increase for more flexibility
4. **Max Strike Distance:** Decrease for ATM-focused trading, increase for wider strike selection

## Volatility Multipliers

The system adjusts TP/SL based on volatility:

- **NATGAS:** 1.5x (wider TP/SL for high volatility)
- **GOLDM:** 0.8x (tighter TP/SL for low volatility)
- **CRUDEOIL:** 1.0x (base volatility)
- **SILVERM:** 1.0x (base volatility)

## Safety Features

✅ **Position Limits** - Prevents overexposure  
✅ **Daily Limits** - Prevents overtrading  
✅ **Risk Limits** - Controls per-trade risk  
✅ **Leverage Limits** - Prevents excessive leverage  
✅ **Kill Switch** - Stops trading at daily loss limit  
✅ **Volatility Adjustment** - Adapts to market conditions  
✅ **Outer Shell Filters** - Volume, OI, spread, strike distance thresholds  

## Important Warnings

⚠️ **Leverage amplifies both profits AND losses**

- Higher leverage = Higher potential profit
- Higher leverage = Higher potential loss
- Always test with paper trading first
- Never risk more than you can afford to lose
- Commodity markets can be very volatile

## File Location

All leverage settings are stored in:
```
Leveraged/mcx_leverage_config.py
```

## Integration

The leverage config is used by:
- Market Config (`config/market_config.py`)
- Trade Manager (`services/trade_manager_service/service.py`)
- MCX Bot (`mcx_only_bot.py`)

## Testing

To test leverage calculations:
```bash
cd Leveraged
python mcx_leverage_config.py
```

## Support

For questions or adjustments:
1. Edit `Leveraged/mcx_leverage_config.py`
2. Restart the bot
3. Test with paper trading first
4. Monitor results before live trading
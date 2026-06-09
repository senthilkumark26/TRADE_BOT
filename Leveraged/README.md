# MCX Leverage Configuration

This directory contains all leverage and risk management settings for MCX commodities trading.

## Files

- **mcx_leverage_config.py** - Main leverage configuration file
- **README.md** - This file (documentation)

## How to Use

### 1. Understanding Leverage Settings

Each commodity has these leverage parameters:

```python
"CRUDEOIL": {
    "lot_size": 100,                    # Units per contract
    "risk_per_trade_pct": 0.01,        # 1% risk per trade
    "max_trades_per_day": 2,           # Daily trade limit
    "effective_leverage": 10,          # 10x leverage
    "margin_per_lot": 50000,           # Margin required per lot
    "max_position_size": 5,             # Maximum lots per trade
}
```

### 2. Modifying Leverage

**To increase leverage:**
- Increase `max_position_size`
- Increase `effective_leverage`
- Decrease `risk_per_trade_pct`

**To decrease leverage:**
- Decrease `max_position_size`
- Decrease `effective_leverage`
- Increase `risk_per_trade_pct`

### 3. Position Sizing

The system automatically calculates position size based on:

```python
risk_amount = capital * risk_per_trade_pct
optimal_lots = risk_amount / risk_per_lot
```

### 4. Testing Configuration

Run the leverage config directly:

```bash
cd Leveraged
python mcx_leverage_config.py
```

This will show:
- Leverage summary for each commodity
- Position sizing calculations
- Risk parameters

## Current Leverage Settings

| Commodity | Lot Size | Leverage | Risk/Trade | Max Lots |
|-----------|----------|----------|------------|----------|
| CRUDEOIL  | 100      | 10x      | 1%         | 5        |
| NATGAS    | 1250     | 8x       | 0.8%       | 2        |
| GOLDM     | 10       | 12x      | 1.5%       | 10       |
| SILVERM   | 5        | 15x      | 1.2%       | 5        |

## Risk Management

**Global Limits:**
- Maximum total risk: 5% of capital
- Maximum total exposure: 20% of capital
- Maximum effective leverage: 15x
- Daily loss limit: -₹3,000
- Maximum drawdown: 10%

**Per-Trade Limits:**
- CRUDEOIL: 1% risk, max 5 lots
- NATGAS: 0.8% risk, max 2 lots (conservative due to volatility)
- GOLDM: 1.5% risk, max 10 lots
- SILVERM: 1.2% risk, max 5 lots

## Volatility Adjustments

Each commodity has a volatility multiplier:

- **NATGAS: 1.5x** (High volatility - wider TP/SL)
- **GOLDM: 0.8x** (Low volatility - tighter TP/SL)
- **CRUDEOIL: 1.0x** (Base volatility)
- **SILVERM: 1.0x** (Base volatility)

## Safety Features

1. **Position Limits** - Maximum lots per trade
2. **Daily Limits** - Maximum trades per day
3. **Risk Limits** - Maximum risk per trade
4. **Leverage Limits** - Maximum effective leverage
5. **Kill Switch** - Stops trading at daily loss limit

## How to Integrate

The leverage config is used by:

1. **Market Config** (`config/market_config.py`)
2. **Trade Manager** (`services/trade_manager_service/service.py`)
3. **MCX Bot** (`mcx_only_bot.py`)

## Important Notes

⚠️ **WARNING: Leverage amplifies both profits AND losses**

- Higher leverage = Higher potential profit
- Higher leverage = Higher potential loss
- Always test with paper trading first
- Never risk more than you can afford to lose

## Support

If you need to adjust leverage settings:

1. Edit `mcx_leverage_config.py`
2. Restart the bot
3. Monitor with paper trading first
4. Gradually increase to live trading

## Last Updated

2026-06-09 - Initial configuration with conservative leverage settings

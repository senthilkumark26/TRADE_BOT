# 9:15 Market Open Analysis Feature

## Overview
The trading bot now includes an automated 9:15 market open analysis feature that uses OptionStar to analyze the market and select optimal strikes based on option chain data.

## Features

### 1. Automatic 9:15 Trigger
- The bot automatically detects when it's 9:15 AM (market open time)
- Performs a comprehensive analysis of all instruments in the watchlist
- Uses OptionStar rule-based engine to select optimal strikes

### 2. OptionStar Analysis at Market Open
- At market open, VWAP equals spot price (no price history yet)
- The system uses OI (Open Interest) bias to determine market direction
- **BULLISH bias**: When Put OI > Call OI (suggests support)
- **BEARISH bias**: When Call OI > Put OI (suggests resistance)
- **Equal OI**: Uses random bias (can be customized)

### 3. Strike Selection Logic
- Uses option chain data to identify support/resistance levels
- Selects strikes based on proximity to key OI levels
- More lenient distance threshold at market open (200 points vs 100 points)
- Stores selected strikes for use during the trading session

### 4. Pre-selected Strike Usage
- During regular trading, the bot uses pre-selected strikes from 9:15 analysis
- Ensures consistency in trading approach
- Reduces computational overhead during market hours

## How to Use

### Automatic Mode
1. Start the bot normally: `python trading_bot.py`
2. At 9:15 AM, the bot will automatically trigger market open analysis
3. Selected strikes will be displayed in the logs and stored for use

### Manual Trigger (Testing)
You can manually trigger the 9:15 analysis at any time for testing:

```
Command: analyze 9:15
```

### View Selected Strikes
To see the strikes selected from the 9:15 analysis:

```
Command: show strikes
```

## Example Output

### 9:15 Analysis Summary
```
================================================================================
9:15 MARKET OPEN ANALYSIS SUMMARY
================================================================================
Instruments analyzed: 14
Strikes selected: 14

Selected Strikes:
  BANKNIFTY: 23600 (CALL) - OI BULLISH bias + near support (22.0 points away)
  NIFTY: 23600 (CALL) - OI BULLISH bias + near support (12.0 points away)
  HDFCBANK: 2500 (CALL) - OI BULLISH bias + near support (39.0 points away)
  ICICIBANK: 2600 (PUT) - OI BEARISH bias + near resistance (11.0 points away)
  ...
```

## Technical Details

### OptionStar Market Open Logic
The OptionStar engine has been enhanced to handle the market open scenario:

1. **Normal Trading**: Uses VWAP to determine trend
   - Spot > VWAP → BULLISH
   - Spot < VWAP → BEARISH

2. **Market Open (Spot = VWAP)**: Uses OI bias
   - Put OI > Call OI → BULLISH (support)
   - Call OI > Put OI → BEARISH (resistance)
   - Equal OI → Random selection

### Key Components

#### 1. `is_market_open_time()`
Checks if current time is within 2 minutes of 9:15 AM

#### 2. `perform_market_open_analysis()`
Main analysis method that:
- Iterates through all instruments in watchlist
- Fetches current spot prices
- Generates option chain data
- Applies OptionStar logic with OI bias
- Stores selected strikes

#### 3. `get_option_chain()`
Fetches option chain data (currently uses mock data, can be replaced with real broker API)

#### 4. Strike Storage
Selected strikes are stored in `self.selected_strikes` dictionary:
```python
{
  "BANKNIFTY": {
    "strike": 23600,
    "direction": "CALL",
    "spot": 23622,
    "vwap": 23622,
    "support": 23600,
    "resistance": 23600,
    "reason": "OI BULLISH bias + near support (22.0 points away)",
    "timestamp": "2026-06-02T09:15:00"
  }
}
```

## Configuration

### Paper Trading Mode
For testing, enable paper trading mode:
```
Command: enable paper trade
```

This uses mock price data instead of live broker data.

### Watchlist
The instruments analyzed are determined by your config.json watchlist. Ensure your desired instruments are included.

## Future Enhancements

1. **Real Option Chain Data**: Replace mock data with real broker API calls
2. **Customizable Time Window**: Allow configuration of analysis time window
3. **Multiple Timeframes**: Add support for different analysis timeframes
4. **Strike Validation**: Add validation logic to ensure selected strikes are tradeable
5. **Historical Performance**: Track performance of 9:15 selected strikes

## Testing

A test script is provided: `test_915_analysis.py`

```bash
python test_915_analysis.py
```

This will:
- Initialize the bot
- Enable paper trading mode
- Trigger the 9:15 analysis
- Display selected strikes
- Verify the functionality

## Integration with Main Bot

The 9:15 analysis is integrated into the main event loop:

```python
# In run_event_loop()
if self.is_market_open_time():
    logger.info("🔔 Market open time detected (9:15) - performing OptionStar analysis...")
    self.perform_market_open_analysis()
```

The analysis runs once per day when the market opens, then the bot continues with normal scanning using the pre-selected strikes.

## Troubleshooting

### No Strikes Selected
- Ensure paper trading is enabled if not using live data
- Check that instruments are properly configured in config.json
- Verify option chain data is being generated

### Analysis Not Triggering
- Check system time is correct
- Ensure bot is running before 9:17 AM (2-minute window)
- Use manual trigger: `analyze 9:15`

### OI Bias Issues
- At market open, OI bias is used instead of VWAP
- If OI data is equal, random bias is applied
- Consider implementing custom bias logic for your strategy

## Summary

The 9:15 market open analysis feature provides:
- ✅ Automated market open analysis
- ✅ OptionStar-based strike selection
- ✅ OI bias for trend determination at open
- ✅ Pre-selected strike storage and usage
- ✅ Manual trigger capability for testing
- ✅ Integration with existing bot infrastructure

This feature enhances the bot's ability to make informed trading decisions right at market open, using option chain data and OI analysis to select optimal strikes.
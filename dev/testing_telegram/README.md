# Telegram Integration Testing

## Overview
This folder contains the Telegram integration for testing and validation phase.

## Files

### Core Telegram Service
- `telegram_service/` - Telegram service module
  - `telegram_service.py` - Main Telegram listener and handler
  - `signal_adapter.py` - Signal validation and parsing
  - `__init__.py` - Module initialization
  - `README.md` - Service documentation

### Bot Scripts
- `telegram_bot.py` - Telegram-only trading bot
- `run_telegram_bot.py` - Entry point script

## How to Run

### 1. Test Telegram Login
```bash
python test_telegram_login.py
```

### 2. Test Group Discovery
```bash
python test_telegram_login.py group
```

### 3. Test Full Integration
```bash
python test_telegram_integration.py
```

### 4. Run Telegram Bot (Paper Trading)
```bash
python run_telegram_bot.py --investment 30000
```

### 5. Run Telegram Bot (Live Trading)
```bash
python run_telegram_bot.py --investment 30000 --live
```

## Signal Format

Valid Telegram signals must follow this format:
```
SYMBOL STRIKE OPTION_TYPE ENTRY_KEYWORD ENTRY_PRICE SL_KEYWORD SL_PRICE TARGET_KEYWORD TARGET_PRICE
```

### Example:
```
NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180
BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250
```

## CSV Tracking

All Telegram calls are tracked in `telegram_calls.csv` with:
- Signal details
- Execution status
- Decision quality matrix
- Source tagging

## Decision Quality Matrix

After collecting 20-30 signals, tag outcomes as GOOD_TRADE or BAD_TRADE to analyze:
- EXECUTED + GOOD_TRADE (Perfect)
- EXECUTED + BAD_TRADE (Over-trade)
- BLOCKED + GOOD_TRADE (Acceptable miss)
- BLOCKED + BAD_TRADE (Correct filter)

## Tagging Outcomes

```bash
python tag_outcomes.py --csv telegram_calls.csv
```

## Validation Phase

**STRICT RULE:** No changes until minimum 20-30 samples

1. Run bot during market hours (09:15-15:30)
2. Collect 20-30 signals
3. Tag outcomes honestly
4. Analyze decision quality matrix
5. Come back with matrix data

## Configuration

Telegram credentials in `config.json`:
```json
{
  "telegram": {
    "enabled": true,
    "api_id": 38954330,
    "api_hash": "6a888b3abbdefb849eee4a49cbd21567",
    "group_id": -1001459973127,
    "phone_number": "+919940260160",
    "signal_timeout": 300,
    "max_recent_signals": 100
  }
}
```

## Safety Features

- Duplicate signal protection
- Time-based signal expiry (5 minutes)
- STRICT signal validation
- Paper trading mode (default)
- Risk management integration

## Next Steps

After validation phase, this will be integrated into main codebase:
- Merge telegram_service into services/
- Add Telegram option to main bot
- Enable hybrid mode (internal + external signals)

## Documentation

- `CSV_TRACKING_GUIDE.md` - Complete CSV tracking guide
- `VALIDATION_PHASE_GUIDE.md` - Validation phase instructions
- `FINAL_ARCHITECTURE.md` - System architecture documentation

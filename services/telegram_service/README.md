# Telegram Service

## Overview
Telegram Service - External signal input for the trading engine.

## Architecture
```
Telegram Signal → Telegram Service → Signal Adapter → Execution Brain → Trade Manager → Execution
```

## Components

### 1. Telegram Service (`telegram_service.py`)
- Listens for Telegram messages from specified group
- Parses incoming messages
- Forwards validated signals to Execution Brain

### 2. Signal Adapter (`signal_adapter.py`)
- STRICT validation of incoming signals
- Parses message format to extract trade parameters
- Returns None for invalid signals (safety mechanism)

### 3. Execution Brain Hook
- Added `process_external_signal()` method to Execution Brain Service
- Reuses existing evaluation pipeline
- Treats external signals as high-confidence inputs

## Signal Format

### Expected Telegram Message Format:
```
NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180
```

### Required Fields:
- **Symbol**: NIFTY, BANKNIFTY, FINNIFTY, SENSEX
- **Strike**: 4-5 digit number
- **Option Type**: CE or PE
- **Entry**: ABOVE/ABV/@/AT followed by price
- **Stop Loss**: SL/STOPLOSS followed by price
- **Target**: TARGET/TGT followed by price

### Valid Examples:
- "NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180"
- "BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250"
- "FINNIFTY 21000 CE @ 100 SL 90 TARGET 130"

## Configuration

Add to `config.json`:
```json
{
  "telegram": {
    "enabled": true,
    "api_id": "YOUR_TELEGRAM_API_ID",
    "api_hash": "YOUR_TELEGRAM_API_HASH",
    "group_id": "YOUR_GROUP_ID",
    "phone_number": "YOUR_PHONE_NUMBER"
  }
}
```

## Usage

### Basic Integration:
```python
from services.telegram_service.telegram_service import TelegramService
from services.execution_brain_service.service import ExecutionBrainService

# Initialize Execution Brain
execution_brain = ExecutionBrainService()

# Initialize Telegram Service
telegram_service = TelegramService(
    api_id=config["telegram"]["api_id"],
    api_hash=config["telegram"]["api_hash"],
    group_id=config["telegram"]["group_id"],
    execution_brain=execution_brain
)

# Start Telegram Service (async)
import asyncio
asyncio.run(telegram_service.start())
```

## Safety Features

1. **STRICT Validation**: Invalid signals are rejected immediately
2. **Missing Field Check**: All required fields must be present
3. **Error Handling**: Adapter returns None on any parsing error
4. **Source Tagging**: All signals tagged with source="TELEGRAM"
5. **Existing Pipeline**: Reuses all existing risk and execution logic

## Flow

1. **Telegram Message Received**
   - Telegram Service captures message

2. **Signal Adapter Validation**
   - Parses message format
   - Validates all required fields
   - Returns None if invalid

3. **Execution Brain Processing**
   - Builds signal package for external signal
   - Evaluates using existing pipeline
   - Returns execution decision

4. **Trade Manager**
   - Executes trade if decision is EXECUTE
   - Monitors position
   - Manages SL/TP

## Testing

### Test Signal Adapter:
```python
from services.telegram_service.signal_adapter import adapt_signal

# Valid signal
signal = adapt_signal("NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180")
print(signal)  # Should return valid signal dict

# Invalid signal
signal = adapt_signal("INVALID MESSAGE")
print(signal)  # Should return None
```

## Important Notes

1. **Paper Trading First**: Always test in paper trading mode
2. **Telegram Credentials**: Get from https://my.telegram.org
3. **Group ID**: Must be numeric ID (not username)
4. **No Architecture Changes**: This is purely an input layer
5. **Existing Logic**: All trading logic remains unchanged

## Dependencies

- `telethon`: Telegram client library
- Install: `pip install telethon`

## Future Enhancements (NOT NOW)

- Signal quality scoring
- Historical performance tracking
- Hybrid mode (internal + external signals)
- Advanced signal enrichment

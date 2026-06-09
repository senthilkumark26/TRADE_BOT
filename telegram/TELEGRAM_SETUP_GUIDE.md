# Telegram Integration Setup Guide

## Phase 1: Telegram Login Test

### Step 1: Get Telegram API Credentials
1. Go to https://my.telegram.org
2. Login with your phone number
3. Go to "API development tools"
4. Create a new application:
   - App title: Trading Bot (or any name)
   - Short name: trading_bot (or any short name)
   - Platform: Desktop
   - Description: Trading signal bot
5. Copy `api_id` and `api_hash`

### Step 2: Configure Credentials
Add to `config.json`:
```json
{
  "telegram": {
    "enabled": false,
    "api_id": 12345678,  // Your API ID (number)
    "api_hash": "your_api_hash_here",  // Your API hash (string)
    "group_id": "YOUR_GROUP_ID",
    "phone_number": "YOUR_PHONE_NUMBER",
    "signal_timeout": 300,
    "max_recent_signals": 100
  }
}
```

### Step 3: Test Login
```bash
python test_telegram_login.py
```

**First time only:**
- Enter your phone number (with country code, e.g., +919876543210)
- Enter OTP sent to your Telegram app
- Enter 2FA password if enabled

**Success indicators:**
- `[SUCCESS] Telegram login successful!`
- Session file created: `test_session.session`
- Next login will be automatic (no OTP required)

## Phase 2: Group ID Discovery

### Step 1: Join Your Signal Group
Make sure you're a member of the Telegram group/channel that sends trading signals.

### Step 2: Discover Group ID
```bash
python test_telegram_login.py group
```

### Step 3: Send Test Message
Send a message in your target signal group (any message).

### Step 4: Capture Group ID
The script will print:
```
[MESSAGE RECEIVED]
  Chat ID: -1001234567890
  Chat Title: Your Signal Group
  Message: Your test message...
```

Copy the `Chat ID` (negative number for groups/channels).

### Step 5: Update Config
Add the group ID to `config.json`:
```json
{
  "telegram": {
    "group_id": -1001234567890
  }
}
```

## Phase 3: Full Integration Test

### Step 1: Test Complete Flow
```bash
python test_telegram_integration.py
```

### Step 2: Send Test Signals
Send properly formatted signals in your Telegram group:
```
NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180
BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250
```

### Step 3: Monitor Output
Expected output:
```
[TG RECEIVED] NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180
[TG VALID SIGNAL] {'symbol': 'NIFTY', 'strike': 23450, ...}
[TG DECISION] {'action': 'EXECUTE', 'score': 85, ...}
```

### Step 4: Check Statistics
The script will show:
```
[CURRENT STATS]
  received: 5
  valid: 4
  invalid: 1
  duplicates: 0
  expired: 0
  executed: 3
```

## Signal Format Requirements

### Valid Format:
```
SYMBOL STRIKE OPTION_TYPE ENTRY_KEYWORD ENTRY_PRICE SL_KEYWORD SL_PRICE TARGET_KEYWORD TARGET_PRICE
```

### Required Components:
- **Symbol**: NIFTY, BANKNIFTY, FINNIFTY, SENSEX
- **Strike**: 4-5 digit number
- **Option Type**: CE or PE
- **Entry Keyword**: ABOVE, ABV, @, AT
- **Entry Price**: Number
- **SL Keyword**: SL or STOPLOSS
- **SL Price**: Number
- **Target Keyword**: TARGET or TGT
- **Target Price**: Number

### Valid Examples:
```
NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180
BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250
FINNIFTY 21000 CE @ 100 SL 90 TARGET 130
nifty 23450 ce above 150 sl 140 target 180  (case insensitive)
```

### Invalid Examples:
```
23450 CE ABOVE 150 SL 140 TARGET 180  (missing symbol)
NIFTY CE ABOVE 150 SL 140 TARGET 180  (missing strike)
NIFTY 23450 ABOVE 150 SL 140 TARGET 180  (missing option type)
```

## Safety Features

### 1. Duplicate Signal Protection
- Prevents executing the same trade multiple times
- Uses signal key: `symbol_strike_option_type`
- Automatically cleans old signals after 100 entries

### 2. Time-Based Expiry
- Rejects signals older than 5 minutes (configurable)
- Uses timestamp from signal adapter
- Prevents executing stale signals

### 3. Signal Statistics
- Tracks: received, valid, invalid, duplicates, expired, executed
- Helps assess signal quality
- Useful for optimization decisions

## Troubleshooting

### Login Issues:
**Problem:** Asks for OTP every time
**Solution:** Check if `test_session.session` file exists and is writable

**Problem:** Invalid API credentials
**Solution:** Verify api_id and api_hash from my.telegram.org

### Group Listening Issues:
**Problem:** Not receiving messages
**Solution:** 
- Verify group_id is correct (negative for groups)
- Ensure you're a member of the group
- Check if group is private (you need to be added)

**Problem:** Receiving messages from wrong group
**Solution:** Verify group_id matches your target group

### Signal Parsing Issues:
**Problem:** All signals marked as invalid
**Solution:** Check signal format matches requirements exactly

**Problem:** Valid signals not reaching Execution Brain
**Solution:** Check logs for specific error messages

## Integration with Main Trading Bot

Once testing is successful:

### Step 1: Enable Telegram in Config
```json
{
  "telegram": {
    "enabled": true
  }
}
```

### Step 2: Add to Main Bot
In your main trading bot initialization:
```python
from services.telegram_service.telegram_service import TelegramService

if config.get("telegram", {}).get("enabled", False):
    telegram_service = TelegramService(
        api_id=config["telegram"]["api_id"],
        api_hash=config["telegram"]["api_hash"],
        group_id=config["telegram"]["group_id"],
        execution_brain=execution_brain_instance
    )
    # Start in background
    import asyncio
    asyncio.create_task(telegram_service.start())
```

### Step 3: Paper Trading First
Always test in paper trading mode before live trading.

## Next Steps After Validation

Once you confirm "telegram listening working":

1. **Optimize parsing accuracy** for real-world noisy signals
2. **Handle edge cases** (malformed messages, partial data)
3. **Improve entry timing** (signal age vs. current market conditions)
4. **Add signal quality scoring** based on historical performance
5. **Implement hybrid mode** (internal + external signals)

## Important Notes

1. **Use User Account (Not Bot Token):** Telethon uses user client for better group access
2. **Session File Security:** Keep `test_session.session` file secure
3. **Paper Trading First:** Always test with paper trading before live trading
4. **Monitor Statistics:** Track signal quality metrics during validation phase
5. **Kill Switch:** Keep ability to disable Telegram quickly via config

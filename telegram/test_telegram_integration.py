"""
Phase 3 Test: Full Telegram Integration Test
Tests complete flow from Telegram message to Execution Brain decision
"""

import asyncio
import json
from telethon import TelegramClient, events
from services.telegram_service.signal_adapter import adapt_signal
from services.execution_brain_service.service import ExecutionBrainService

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Telegram credentials
api_id = config.get("telegram", {}).get("api_id")
api_hash = config.get("telegram", {}).get("api_hash")
group_id = config.get("telegram", {}).get("group_id")

print("=" * 80)
print("PHASE 3: FULL TELEGRAM INTEGRATION TEST")
print("=" * 80)

if not api_id or not api_hash or api_id == "YOUR_TELEGRAM_API_ID":
    print("ERROR: Telegram credentials not configured")
    exit(1)

if not group_id or group_id == "YOUR_GROUP_ID":
    print("ERROR: Group ID not configured")
    print("Run: python test_telegram_login.py group")
    print("To discover your group ID")
    exit(1)

print(f"API ID: {api_id}")
print(f"Group ID: {group_id}")
print()

# Initialize Execution Brain (for testing)
execution_brain = ExecutionBrainService()

# Safety features
recent_signals = set()
signal_timeout = 300  # 5 minutes
signal_stats = {
    "received": 0,
    "valid": 0,
    "invalid": 0,
    "duplicates": 0,
    "expired": 0,
    "executed": 0
}

def is_duplicate_signal(signal):
    """Check if signal is a duplicate"""
    signal_key = f"{signal['symbol']}_{signal['strike']}_{signal['option_type']}"
    
    if signal_key in recent_signals:
        return True
    
    recent_signals.add(signal_key)
    
    # Clean old signals from set
    if len(recent_signals) > 100:
        recent_signals.clear()
    
    return False

def is_expired_signal(signal):
    """Check if signal is too old"""
    import time
    if "timestamp" not in signal:
        return False
    
    signal_age = time.time() - signal["timestamp"]
    return signal_age > signal_timeout

def update_stats(stat_type):
    """Update signal statistics"""
    if stat_type in signal_stats:
        signal_stats[stat_type] += 1

async def test_full_integration():
    """Test complete integration flow"""
    
    print("Step 1: Creating Telegram client...")
    client = TelegramClient("test_session", api_id, api_hash)
    
    @client.on(events.NewMessage(chats=group_id))
    async def handler(event):
        message = event.raw_text
        update_stats("received")
        print(f"[TG RECEIVED] {message}")

        # Step 1: Adapt + Validate
        signal = adapt_signal(message)

        if not signal:
            update_stats("invalid")
            print("[TG SKIPPED] Invalid signal format")
            return

        update_stats("valid")
        print(f"[TG VALID SIGNAL] {signal}")

        # Step 2: Check for duplicates
        if is_duplicate_signal(signal):
            update_stats("duplicates")
            print("[TG SKIPPED] Duplicate signal")
            return

        # Step 3: Check for expired signals
        if is_expired_signal(signal):
            update_stats("expired")
            print("[TG SKIPPED] Expired signal")
            return

        # Step 4: Send to Execution Brain
        try:
            decision = execution_brain.process_external_signal(signal)
            
            if decision.get("action") == "EXECUTE":
                update_stats("executed")
            
            print(f"[TG DECISION] {decision}")
            print()
            print("[CURRENT STATS]")
            for key, value in signal_stats.items():
                print(f"  {key}: {value}")
            print()
            
        except Exception as e:
            print(f"[TG ERROR] Execution Brain failed: {e}")

    print("Step 2: Connecting to Telegram...")
    try:
        await client.start()
        print("[SUCCESS] Connected to Telegram")
        print()
        print(f"Listening to group: {group_id}")
        print(f"Signal timeout: {signal_timeout} seconds")
        print()
        print("Send test signals in your Telegram group:")
        print("  NIFTY 23450 CE ABOVE 150 SL 140 TARGET 180")
        print("  BANKNIFTY 45000 PE ABV 200 SL 190 TARGET 250")
        print()
        print("Press Ctrl+C to stop")
        print()
        print("=" * 80)
        
        await client.run_until_disconnected()
        
    except KeyboardInterrupt:
        print()
        print("[STOPPED] Test stopped by user")
        print()
        print("[FINAL STATS]")
        for key, value in signal_stats.items():
            print(f"  {key}: {value}")
        print()
        print("=" * 80)
        print("PHASE 3 COMPLETE")
        print("=" * 80)
        
        await client.disconnect()
        
    except Exception as e:
        print(f"[ERROR] Integration test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_full_integration())

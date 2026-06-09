"""
Phase 1 Test: Telegram Login & Basic Connectivity
Tests login, session creation, and basic Telegram connectivity
"""

import asyncio
from telethon import TelegramClient, events
import json

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Telegram credentials
api_id = config.get("telegram", {}).get("api_id")
api_hash = config.get("telegram", {}).get("api_hash")

print("=" * 80)
print("PHASE 1: TELEGRAM LOGIN TEST")
print("=" * 80)

if not api_id or not api_hash or api_id == "YOUR_TELEGRAM_API_ID":
    print("ERROR: Telegram credentials not configured in config.json")
    print("Please set:")
    print("  telegram.api_id")
    print("  telegram.api_hash")
    print("\nGet credentials from: https://my.telegram.org")
    exit(1)

print(f"API ID: {api_id}")
print(f"API Hash: {api_hash[:10]}...")  # Show partial for security
print()

async def test_login():
    """Test basic Telegram login"""
    
    print("Step 1: Creating Telegram client...")
    client = TelegramClient("test_session", api_id, api_hash)
    
    print("Step 2: Connecting to Telegram...")
    print("If this is your first time, you'll be asked for:")
    print("  - Phone number")
    print("  - OTP (sent to Telegram app)")
    print("  - 2FA password (if enabled)")
    print()
    
    try:
        await client.start()
        print("[SUCCESS] Telegram login successful!")
        print()
        
        # Get user info
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'N/A'})")
        print(f"Phone: {me.phone}")
        print()
        
        # Check session file
        import os
        if os.path.exists("test_session.session"):
            print("[SUCCESS] Session file created: test_session.session")
            print("Next login will be automatic (no OTP required)")
        else:
            print("[WARNING] Session file not found")
        
        print()
        print("=" * 80)
        print("PHASE 1 COMPLETE: Login successful")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. Run test_telegram_group.py to discover group ID")
        print("2. Update config.json with group_id")
        print("3. Run full integration test")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"[ERROR] Login failed: {e}")
        print("Please check:")
        print("  - API credentials are correct")
        print("  - Internet connection is stable")
        print("  - Telegram is accessible")

async def test_group_discovery():
    """Test group ID discovery (Phase 2)"""
    
    print("=" * 80)
    print("PHASE 2: GROUP ID DISCOVERY")
    print("=" * 80)
    print()
    print("This will listen to ALL your Telegram messages for 60 seconds")
    print("Send a message in your target signal group to discover its ID")
    print()
    
    client = TelegramClient("test_session", api_id, api_hash)
    
    @client.on(events.NewMessage)
    async def handler(event):
        print(f"[MESSAGE RECEIVED]")
        print(f"  Chat ID: {event.chat_id}")
        print(f"  Chat Title: {event.chat.title if hasattr(event.chat, 'title') else 'Private/Direct'}")
        print(f"  Message: {event.raw_text[:50]}...")
        print()
        
    print("Starting listener (60 seconds)...")
    print("Send a message in your target group now...")
    print()
    
    try:
        await client.start()
        print("[SUCCESS] Connected to Telegram")
        print("Listening for messages...")
        print()
        
        # Listen for 60 seconds
        await asyncio.sleep(60)
        
        print()
        print("[STOPPED] Listening period ended")
        print("Use the Chat ID from your target group in config.json")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"[ERROR] Group discovery failed: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "group":
        # Run group discovery
        asyncio.run(test_group_discovery())
    else:
        # Run login test
        asyncio.run(test_login())

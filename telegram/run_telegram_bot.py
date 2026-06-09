"""
Run Telegram-Only Trading Bot
Dedicated to executing Telegram signals only
"""

import sys
import subprocess
import argparse

def main():
    parser = argparse.ArgumentParser(description='Run Telegram-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    args = parser.parse_args()

    print("=" * 80)
    print("TELEGRAM-ONLY TRADING BOT")
    print("=" * 80)
    print(f"Investment: {args.investment}")
    print("Mode: PAPER TRADING (add --live for real trading)")
    print("Signal Source: Telegram Only")
    print("No internal signal generation")
    print("=" * 80)
    print()

    # Build command (run from telegram directory with parent in path)
    import os
    telegram_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(telegram_dir)
    
    # Set PYTHONPATH to include parent directory
    env = os.environ.copy()
    env['PYTHONPATH'] = parent_dir
    
    cmd = [sys.executable, "telegram_only_bot.py", "--investment", str(args.investment)]
    
    if args.live:
        cmd.append("--live")
        print("⚠️  WARNING: LIVE MODE ENABLED - REAL MONEY AT RISK!")
        print()
    
    # Run the telegram-only bot
    try:
        os.chdir(telegram_dir)  # Change to telegram directory
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\nTelegram-only bot stopped by user")

if __name__ == "__main__":
    main()

"""
Run MCX-Only Trading Bot
Dedicated to commodity trading (CRUDEOIL, NATGAS)
"""

import sys
import subprocess
import argparse

def main():
    parser = argparse.ArgumentParser(description='Run MCX-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    args = parser.parse_args()

    print("=" * 80)
    print("MCX-ONLY TRADING BOT")
    print("=" * 80)
    print(f"Investment: {args.investment}")
    print("Mode: PAPER TRADING (add --live for real trading)")
    print("Signal Source: MCX Engine Only")
    print("Instruments: CRUDEOIL, NATGAS")
    print("Market Hours: 09:00 - 23:30 (MCX)")
    print("=" * 80)
    print()

    # Build command (run from parent directory with PYTHONPATH set)
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Set PYTHONPATH to include parent directory
    env = os.environ.copy()
    env['PYTHONPATH'] = parent_dir
    
    cmd = [sys.executable, "mcx/mcx_only_bot.py", "--investment", str(args.investment)]
    
    if args.live:
        cmd.append("--live")
        print("⚠️  WARNING: LIVE MODE ENABLED - REAL MONEY AT RISK!")
        print()
    
    # Run the MCX-only bot
    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\nMCX-only bot stopped by user")

if __name__ == "__main__":
    main()

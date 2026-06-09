"""
Run Single Strike Focus Trader with command-line arguments
"""

import sys
import subprocess
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description='Run Single Strike Focus Trader')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    args = parser.parse_args()

    print("="*80)
    print("SINGLE STRIKE FOCUS TRADER")
    print("="*80)
    print(f"Investment: {args.investment}")
    print("Strategy:")
    print("1. Pick strike at market open")
    print("2. Stick to strike until SL/TP hit")
    print("3. After exit, select new strike")
    print("4. Repeat until market close")
    print("="*80)
    print()

    # Change to parent directory to run the bot
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(parent_dir)

    # Run the single strike trader with investment argument
    try:
        subprocess.run([sys.executable, "bots/single_strike_trader.py", "--investment", str(args.investment)])
    except KeyboardInterrupt:
        print("\nTrading stopped by user")

if __name__ == "__main__":
    main()
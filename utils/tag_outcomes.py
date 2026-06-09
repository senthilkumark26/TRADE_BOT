"""
Manual Outcome Tagging Script
Allows you to manually tag expected_outcome for Telegram calls
This enables Decision Quality Matrix analysis
"""

import csv
import sys
from datetime import datetime

def load_csv(csv_file='telegram_calls.csv'):
    """Load CSV file"""
    try:
        with open(csv_file, 'r', newline='') as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)
        return headers, rows
    except FileNotFoundError:
        print(f"Error: {csv_file} not found")
        print("Run the appropriate bot first to generate the CSV file")
        print("  - telegram_calls.csv: Run Telegram bot")
        print("  - mcx_calls.csv: Run MCX bot")
        sys.exit(1)

def display_un_tagged(headers, rows):
    """Display calls that need outcome tagging"""
    print("=" * 80)
    print("CALLS NEEDING OUTCOME TAGGING")
    print("=" * 80)
    
    untagged = []
    for i, row in enumerate(rows):
        if len(row) > 12 and row[12] == '':  # expected_outcome is empty
            untagged.append((i, row))
    
    if not untagged:
        print("No untagged calls found!")
        return untaged
    
    print(f"\nFound {len(untagged)} untaged calls:\n")
    
    for idx, (row_num, row) in enumerate(untagged[:10]):  # Show first 10
        print(f"{idx + 1}. {row[0]} | {row[1]} {row[2]} {row[3]} @ {row[4]} | Status: {row[7]}")
    
    if len(untagged) > 10:
        print(f"\n... and {len(untagged) - 10} more")
    
    return untagged

def tag_outcome(csv_file='telegram_calls.csv'):
    """Interactive outcome tagging"""
    headers, rows = load_csv(csv_file)
    
    print("\n" + "=" * 80)
    print("MANUAL OUTCOME TAGGING")
    print("=" * 80)
    print("\nThis helps you build the Decision Quality Matrix")
    print("Tag each call as GOOD_TRADE or BAD_TRADE")
    print("\nDecision Quality Matrix:")
    print("  EXECUTED + GOOD_TRADE  = Perfect")
    print("  EXECUTED + BAD_TRADE   = Over-trade")
    print("  BLOCKED + GOOD_TRADE   = Too strict")
    print("  BLOCKED + BAD_TRADE    = Correct filter")
    print()
    
    untagged = display_un_tagged(headers, rows)
    
    if not untagged:
        return
    
    print("\nTagging Options:")
    print("  1. Tag specific call (by number)")
    print("  2. Tag all EXECUTED as GOOD_TRADE")
    print("  3. Tag all BLOCKED as BAD_TRADE")
    print("  4. Exit")
    
    while True:
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == '1':
            # Tag specific call
            try:
                call_num = int(input("Enter call number: ")) - 1
                if 0 <= call_num < len(untagged):
                    row_num, row = untagged[call_num]
                    print(f"\nCall: {row[1]} {row[2]} {row[3]} @ {row[4]} | Status: {row[7]}")
                    outcome = input("Tag as (GOOD_TRADE/BAD_TRADE): ").strip().upper()
                    
                    if outcome in ['GOOD_TRADE', 'BAD_TRADE']:
                        rows[row_num][12] = outcome
                        print(f"Tagged as {outcome}")
                        
                        # Save immediately
                        with open(csv_file, 'w', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow(headers)
                            writer.writerows(rows)
                        print("CSV saved")
                    else:
                        print("Invalid outcome. Use GOOD_TRADE or BAD_TRADE")
                else:
                    print("Invalid call number")
            except ValueError:
                print("Invalid input")
        
        elif choice == '2':
            # Tag all EXECUTED as GOOD_TRADE
            count = 0
            for row in rows:
                if len(row) > 7 and row[7] == 'EXECUTED' and (len(row) <= 12 or row[12] == ''):
                    if len(row) <= 12:
                        row.append('GOOD_TRADE')
                    else:
                        row[12] = 'GOOD_TRADE'
                    count += 1
            
            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            
            print(f"Tagged {count} EXECUTED calls as GOOD_TRADE")
        
        elif choice == '3':
            # Tag all BLOCKED as BAD_TRADE
            count = 0
            for row in rows:
                if len(row) > 7 and row[7] == 'BLOCKED' and (len(row) <= 12 or row[12] == ''):
                    if len(row) <= 12:
                        row.append('BAD_TRADE')
                    else:
                        row[12] = 'BAD_TRADE'
                    count += 1
            
            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            
            print(f"Tagged {count} BLOCKED calls as BAD_TRADE")
        
        elif choice == '4':
            print("Exiting...")
            break
        
        else:
            print("Invalid choice")

def analyze_decision_quality(csv_file='telegram_calls.csv'):
    """Analyze decision quality matrix"""
    headers, rows = load_csv(csv_file)
    
    print("\n" + "=" * 80)
    print("DECISION QUALITY MATRIX")
    print("=" * 80)
    
    # Count each combination
    matrix = {
        'EXECUTED_GOOD_TRADE': 0,
        'EXECUTED_BAD_TRADE': 0,
        'BLOCKED_GOOD_TRADE': 0,
        'BLOCKED_BAD_TRADE': 0,
        'EXITED_GOOD_TRADE': 0,
        'EXITED_BAD_TRADE': 0
    }
    
    for row in rows:
        if len(row) > 12:
            status = row[7]
            outcome = row[12]
            key = f"{status}_{outcome}"
            if key in matrix:
                matrix[key] += 1
    
    print("\nDecision Quality Matrix:")
    print(f"  EXECUTED + GOOD_TRADE:  {matrix['EXECUTED_GOOD_TRADE']} (Perfect)")
    print(f"  EXECUTED + BAD_TRADE:   {matrix['EXECUTED_BAD_TRADE']} (Over-trade)")
    print(f"  BLOCKED + GOOD_TRADE:   {matrix['BLOCKED_GOOD_TRADE']} (Too strict)")
    print(f"  BLOCKED + BAD_TRADE:    {matrix['BLOCKED_BAD_TRADE']} (Correct filter)")
    print(f"  EXITED + GOOD_TRADE:    {matrix['EXITED_GOOD_TRADE']} (Winning)")
    print(f"  EXITED + BAD_TRADE:     {matrix['EXITED_BAD_TRADE']} (Losing)")
    
    # Calculate metrics
    total_tagged = sum(matrix.values())
    if total_tagged > 0:
        executed_good = matrix['EXECUTED_GOOD_TRADE'] + matrix['EXITED_GOOD_TRADE']
        executed_bad = matrix['EXECUTED_BAD_TRADE'] + matrix['EXITED_BAD_TRADE']
        blocked_good = matrix['BLOCKED_GOOD_TRADE']
        blocked_bad = matrix['BLOCKED_BAD_TRADE']
        
        print("\nMetrics:")
        print(f"  Decision Accuracy: {((executed_good + blocked_bad) / total_tagged * 100):.1f}%")
        print(f"  Execution Hit Rate: {(executed_good / (executed_good + executed_bad) * 100) if (executed_good + executed_bad) > 0 else 0:.1f}%")
        print(f"  Filter Accuracy: {(blocked_bad / (blocked_good + blocked_bad) * 100) if (blocked_good + blocked_bad) > 0 else 0:.1f}%")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Tag expected outcomes for calls')
    parser.add_argument('--csv', default='telegram_calls.csv', help='CSV file path (telegram_calls.csv or mcx_calls.csv)')
    parser.add_argument('--analyze', action='store_true', help='Analyze decision quality matrix')
    
    args = parser.parse_args()
    
    if args.analyze:
        analyze_decision_quality(args.csv)
    else:
        tag_outcome(args.csv)

if __name__ == "__main__":
    main()

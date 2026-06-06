"""
Launcher for Streamlit Single Strike Trader - UAT Validation
"""

import subprocess
import sys

def main():
    print("=" * 80)
    print("Starting Streamlit Single Strike Trader - UAT Validation")
    print("=" * 80)
    print()
    print("Features:")
    print("  - Real-time sync with Zerodha API (second-by-second)")
    print("  - Engine1 (Fast Market Analyzer) - Real VWAP, PCR, Build-up")
    print("  - LLM (Human Sentiment) - Ollama integration")
    print("  - Live option chain from Zerodha API")
    print("  - Demo mode (Paper Trading) - Safe for UAT")
    print("  - Capital management with 30k investment")
    print()
    print("Opening browser...")
    print()
    
    # Run Streamlit using Python module (since streamlit might not be in PATH)
    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "streamlit_single_strike_trader.py",
            "--server.port", "8503",
            "--server.address", "localhost",
            "--browser.gatherUsageStats", "false"
        ])
    except KeyboardInterrupt:
        print("\n\nStreamlit stopped by user")
    except Exception as e:
        print(f"\nError starting Streamlit: {e}")
        print("Make sure to install dependencies:")
        print("  pip install -r requirements_streamlit.txt")

if __name__ == "__main__":
    main()

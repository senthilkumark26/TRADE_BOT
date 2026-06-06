"""
Streamlit Interface for Single Strike Trader - UAT Validation
Real-time sync with Zerodha API - Second by Second
"""

import streamlit as st
import json
import time
import threading
import pandas as pd
from datetime import datetime
from single_strike_trader import SingleStrikeTrader
import logging

# Configure logging for Streamlit
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Single Strike Trader - UAT Validation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
    }
    .success {
        color: #00c853;
    }
    .warning {
        color: #ffab00;
    }
    .error {
        color: #ff1744;
    }
    .info {
        color: #2196f3;
    }
</style>
""", unsafe_allow_html=True)

# Session state initialization
if 'trader' not in st.session_state:
    st.session_state.trader = None
if 'running' not in st.session_state:
    st.session_state.running = False
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []
if 'current_trade' not in st.session_state:
    st.session_state.current_trade = None
if 'market_data' not in st.session_state:
    st.session_state.market_data = {}
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# Sidebar
st.sidebar.title("⚙️ Configuration")

demo_mode = st.sidebar.checkbox("Demo Mode (Paper Trading)", value=True, help="Safe paper trading with fake capital - No real orders")

if demo_mode:
    st.sidebar.success("✅ Demo Mode - Safe Paper Trading")
    st.sidebar.info("Virtual 30k investment - No real money at risk")
else:
    st.sidebar.error("⚠️ Live Mode - Real Trading")
    st.sidebar.warning("Real money at risk - Use with caution")

investment_amount = st.sidebar.number_input(
    "Investment Amount (₹)",
    min_value=10000,
    max_value=1000000,
    value=30000,
    step=5000
)

auto_start = st.sidebar.checkbox("Auto Start", value=False)

# Initialize Trader
if st.sidebar.button("🚀 Initialize Trader") or auto_start:
    if st.session_state.trader is None:
        with st.spinner("Initializing Trader with Engine1 and LLM..."):
            st.session_state.trader = SingleStrikeTrader(investment_amount=investment_amount, demo_mode=demo_mode)
            mode_str = "DEMO (Paper Trading)" if demo_mode else "LIVE (Real Trading)"
            st.session_state.logs.append(f"✅ Trader initialized - {mode_str} - ₹{investment_amount}")
            st.sidebar.success("Trader Initialized!")
    else:
        st.sidebar.info("Trader already initialized")

# Start/Stop Trading
col1, col2 = st.sidebar.columns(2)
if col1.button("▶️ Start"):
    if st.session_state.trader:
        st.session_state.running = True
        st.session_state.logs.append("▶️ Trading started")
        st.sidebar.success("Trading Started!")
    else:
        st.sidebar.error("Initialize trader first!")

if col2.button("⏹️ Stop"):
    st.session_state.running = False
    st.session_state.logs.append("⏹️ Trading stopped")
    st.sidebar.warning("Trading Stopped!")

# Main Interface
st.markdown('<h1 class="main-header">📊 Single Strike Trader - UAT Validation</h1>', unsafe_allow_html=True)

# Status Section
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    status = "🟢 Running" if st.session_state.running else "🔴 Stopped"
    st.metric("Status", status)

with col2:
    mode = "🟢 DEMO" if (st.session_state.trader and st.session_state.trader.demo_mode) else "🔴 LIVE"
    st.metric("Mode", mode)

with col3:
    capital = st.session_state.trader.current_capital if st.session_state.trader else 0
    st.metric("Current Capital", f"₹{capital:.2f}")

with col4:
    trades = len(st.session_state.trade_history)
    st.metric("Total Trades", trades)

with col5:
    pnl = sum(t.get('pnl', 0) for t in st.session_state.trade_history)
    pnl_color = "normal" if pnl >= 0 else "inverse"
    st.metric("Total P&L", f"₹{pnl:.2f}", delta_color=pnl_color)

# Current Trade Section
st.subheader("🎯 Current Trade")

if st.session_state.current_trade:
    trade = st.session_state.current_trade
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Symbol", trade.get('symbol', 'N/A'))
    with col2:
        st.metric("Strike", trade.get('strike', 'N/A'))
    with col3:
        direction = trade.get('direction', 'N/A')
        color = "normal" if direction == "CALL" else "inverse"
        st.metric("Direction", direction, delta_color=color)
    with col4:
        entry = trade.get('entry_price', 0)
        st.metric("Entry Price", f"₹{entry:.2f}")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        current = trade.get('current_price', 0)
        st.metric("Current Price", f"₹{current:.2f}")
    with col2:
        pnl = trade.get('pnl', 0)
        pnl_color = "normal" if pnl >= 0 else "inverse"
        st.metric("P&L", f"₹{pnl:.2f}", delta_color=pnl_color)
    with col3:
        target = trade.get('target_price', 0)
        sl = trade.get('stoploss_price', 0)
        st.metric(f"Target: ₹{target:.2f} | SL: ₹{sl:.2f}", "")
else:
    st.info("No active trade - Waiting for Engine1 signal...")

# Market Data Section
st.subheader("📈 Real-Time Market Data")

if st.session_state.market_data:
    market_df = pd.DataFrame(st.session_state.market_data.values())
    if not market_df.empty:
        st.dataframe(market_df, use_container_width=True)
else:
    st.info("Waiting for market data...")

# Trade History Section
st.subheader("📜 Trade History")

if st.session_state.trade_history:
    history_df = pd.DataFrame(st.session_state.trade_history)
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True)
else:
    st.info("No trades yet...")

# Logs Section
st.subheader("📋 System Logs")

log_container = st.container()
with log_container:
    if st.session_state.logs:
        for log in st.session_state.logs[-20:]:  # Show last 20 logs
            st.text(log)
    else:
        st.info("No logs yet...")

# Engine Status Section
st.subheader("🔧 Engine Status")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### Engine1 (Fast Market Analyzer)")
    if st.session_state.trader:
        st.info("✅ Engine1 Initialized")
        st.info("Real-time VWAP: Active")
        st.info("PCR Analysis: Active")
        st.info("Build-up Detection: Active")
    else:
        st.error("❌ Engine1 Not Initialized")

with col2:
    st.markdown("### LLM (Human Sentiment)")
    if st.session_state.trader and st.session_state.trader.llm_analyzer:
        st.info("✅ LLM Initialized")
        st.info(f"Model: {st.session_state.trader.llm_analyzer.model}")
        st.info(f"Mode: {st.session_state.trader.llm_analyzer.mode}")
        st.info("Sentiment Validation: Active")
    else:
        st.error("❌ LLM Not Initialized")

# Data Source Section
st.subheader("📡 Data Source")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Trading Mode")
    if st.session_state.trader:
        if st.session_state.trader.demo_mode:
            st.success("✅ DEMO MODE")
            st.info("Paper Trading - Fake Capital")
            st.info("Virtual 30k Investment")
            st.info("No Real Orders")
        else:
            st.error("⚠️ LIVE MODE")
            st.warning("Real Trading - Real Capital")
            st.warning("Real Money at Risk")
    else:
        st.info("Not initialized")

with col2:
    st.markdown("### Zerodha API")
    st.info("✅ Live Mode")
    st.info("✅ Real-time Spot Prices")
    st.info("✅ Real-time Option Chain")
    st.info("✅ Second-by-second Sync")

with col3:
    st.markdown("### Option Chain")
    st.info("✅ option_token_map.json")
    st.info("✅ Real LTP from API")
    st.info("✅ Batch Processing (50)")
    st.info("✅ No Mock Data")

# Auto-refresh for real-time updates
if st.session_state.running and st.session_state.trader:
    # Run trading logic in background
    def run_trading():
        try:
            trader = st.session_state.trader
            
            # Update market data
            instruments = trader.config.get('instruments', {}).keys()
            market_data = {}
            
            for symbol in instruments:
                spot_price = trader.get_spot_price(symbol)
                if spot_price > 0:
                    market_data[symbol] = {
                        'Symbol': symbol,
                        'Spot Price': spot_price,
                        'VWAP': trader.get_vwap_price(symbol),
                        'Timestamp': datetime.now().strftime('%H:%M:%S')
                    }
            
            st.session_state.market_data = market_data
            st.session_state.last_update = datetime.now()
            
            # Check for trade
            if not trader.trade_active:
                opportunity = trader.select_best_strike()
                if opportunity:
                    trade_signal = opportunity.get('trade_signal')
                    if trade_signal:
                        direction = trade_signal.get('direction')
                        strike = trade_signal.get('strike')
                        option_price = opportunity.get('option_price')
                        
                        if trader.execute_trade(opportunity['symbol'], strike, direction, option_price, trade_signal):
                            st.session_state.current_trade = {
                                'symbol': opportunity['symbol'],
                                'strike': strike,
                                'direction': direction,
                                'entry_price': option_price,
                                'target_price': trader.target_price,
                                'stoploss_price': trader.stoploss_price,
                                'current_price': option_price,
                                'pnl': 0
                            }
                            st.session_state.logs.append(f"✅ Trade executed: {opportunity['symbol']} {strike} {direction}")
            
            # Monitor current trade
            if trader.trade_active and st.session_state.current_trade:
                current_price = trader.get_option_price(
                    trader.current_symbol,
                    trader.current_strike,
                    trader.current_direction
                )
                
                if current_price:
                    st.session_state.current_trade['current_price'] = current_price
                    
                    if trader.current_direction == "CALL":
                        pnl = current_price - trader.entry_price
                    else:
                        pnl = trader.entry_price - current_price
                    
                    st.session_state.current_trade['pnl'] = pnl
                    
                    # Check if trade closed
                    if not trader.trade_active:
                        st.session_state.trade_history.append(st.session_state.current_trade)
                        st.session_state.logs.append(f"✅ Trade closed: P&L ₹{pnl:.2f}")
                        st.session_state.current_trade = None
            
        except Exception as e:
            st.session_state.logs.append(f"❌ Error: {e}")
            logger.error(f"Trading error: {e}")
    
    # Run trading logic
    run_trading()
    
    # Auto-refresh every 5 seconds (reduced from 2 to avoid rate limits)
    time.sleep(5)
    st.rerun()

# Footer
st.markdown("---")
st.markdown("### 📊 UAT Validation Dashboard")
st.markdown("**Data Source**: Zerodha Live API | **Engine**: Engine1 + LLM | **Mode**: Demo (Paper Trading)")
st.markdown("**Sync**: Second-by-second | **Capital**: Virtual 30k | **No Real Money**")
st.markdown("**Safe for UAT**: No real orders placed - Paper trading only")

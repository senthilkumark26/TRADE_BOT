"""
Single Strike Focus Trader - Picks one strike, trades until exit, then picks new strike
Interlinked with existing trading infrastructure
"""

import json
import time
import logging
import argparse
import random
from datetime import datetime, time as dt_time
import sys
import os

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from kite.kite_client import KiteClient
from kite.upstox_client import UpstoxClient, get_upstox_client
from engines.engine1_market_analyzer import Engine1MarketAnalyzer
from ai.llm_market_analyzer import LLMMarketAnalyzer
from utils.optionstar import calculate_institutional_walls
from risk.risk_management import get_risk_management_service
from wrappers.risk_wrapper import (
    get_position_size,
    update_trade_result,
    can_execute_trade,
    reset_daily_limits,
    get_risk_status
)
# MCX imports removed - NSE-only trading
from services.market_analyzer_service import MarketAnalyzerService
from services.optionstar_service.service import OptionStarService  # PRODUCTION FIX: Added OptionStar import
from services.mcx_sentiment_service.service import get_mcx_sentiment_service
from services.watchdog_service.service import get_watchdog_service
from services.breakout_entry_service import BreakoutEntryService
from services.execution_brain_service import ExecutionBrainService
from services.trade_manager_service import TradeManagerService
from services.smart_strike_service import SmartStrikeService
from data_layer.websocket_client import WebSocketClient
from data_layer.state_manager import StateManager
from data_layer.options_websocket import OptionsWebSocket

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SingleStrikeTrader:
    def __init__(self, investment_amount=30000, paper_trading=None, symbols=None):
        # Load config
        with open('config.json', 'r') as f:
            self.config = json.load(f)
        
        # Set symbols to trade (optional parameter, defaults to all instruments from config)
        if symbols is None:
            self.symbols = None  # Use all instruments from config
        else:
            self.symbols = symbols

        # Paper Trading with Real Data mode (best for testing)
        # Uses real Zerodha API data but doesn't place real orders
        if paper_trading is None:
            paper_trading = self.config.get("paper_trading", False)
        
        self.paper_trading = paper_trading
        
        # OBSERVATION MODE - Minimal execution path for market behavior analysis
        # Skips all intelligence filters, forces direct trade execution
        self.observation_mode = self.config.get("observation_mode", False)
        
        # Paper trading mode - uses real data but doesn't place real orders
        if self.paper_trading:
            logger.info("=" * 80)
            logger.info("PAPER TRADING MODE - Real Market Data, No Real Orders")
            logger.info("=" * 80)
            logger.info("Using REAL Zerodha API data for testing")
            logger.info("NO real orders will be placed")
            logger.info("Virtual capital for paper trading")
            logger.info("=" * 80)
        else:
            logger.info("LIVE MODE - Real Trading with Real Capital")
            logger.warning("REAL MONEY AT RISK!")
        
        # Observation mode logging
        if self.observation_mode:
            logger.info("=" * 80)
            logger.info("OBSERVATION MODE ENABLED - Minimal Execution Path")
            logger.info("=" * 80)
            logger.info("SKIPPING: Execution Brain filters")
            logger.info("FORCING: Direct trade execution after strike selection")
            logger.info("GOAL: Observe real TP/SL behavior and market mechanics")
            logger.info("=" * 80)

        # Ensure authentication before starting
        logger.info("Checking authentication status...")
        from kite.login_manager import ensure_authenticated_bot
        
        auth_result = ensure_authenticated_bot()
        
        if not auth_result['success']:
            logger.error(f"Authentication failed: {auth_result['message']}")
            logger.error("Bot cannot start without valid authentication")
            raise Exception(f"Authentication required: {auth_result['message']}")
        
        # Use authenticated Kite client
        self.kite_client = auth_result['kite_client']
        logger.info("✓ Kite client authenticated successfully")
        
        # Initialize Upstox client if configured as data source
        self.upstox_client = None
        if self.config.get("data_source") == "upstox":
            try:
                self.upstox_client = UpstoxClient(self.config)
                logger.info("✓ Upstox client initialized as data source")
            except Exception as e:
                logger.error(f"Failed to initialize Upstox client: {e}")
                logger.warning("Falling back to Kite client for data")
                self.upstox_client = None
        
        # PRODUCTION FIX: Rate limiting and caching
        self.last_api_call_time = 0
        self.api_call_interval = 2.0  # Minimum 2 seconds between API calls
        self.spot_price_cache = {}
        self.spot_price_cache_time = {}
        self.spot_price_cache_duration = 10.0  # Cache spot price for 10 seconds
        
        # PRODUCTION FIX: Option chain caching (use existing cache variables)
        self.cached_option_chain = None
        self.cached_option_chain_time = 0
        # Set cache duration based on data source
        if self.config.get("data_source") == "upstox":
            self.option_chain_cache_duration = 15  # Upstox: 15 seconds (faster refresh needed)
        else:
            self.option_chain_cache_duration = 30  # Zerodha: 30 seconds (no rate limiting)
        
        # PRODUCTION FIX: Explicit API failure fallback cache
        self.cached_spot_price = None
        self.last_spot_time = 0
        self.spot_api_failure_count = 0
        self.max_api_failures = 3
        
        # Initialize Risk Management Service (initialize early - needed by run_trading_day)
        try:
            self.risk_service = get_risk_management_service(investment_amount)
            logger.info("Risk Management Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Risk Management Service: {e}")
            logger.warning("Continuing without Risk Management - trading will NOT have risk protection!")
            self.risk_service = None
        
        # Trading parameters (initialize early - needed by run_trading_day)
        self.start_capital = investment_amount
        self.current_capital = investment_amount
        logger.info(f"Capital initialized: ₹{self.start_capital}")
        
        # Market hours (NSE-only - NSE hours: 09:15-15:30)
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        logger.info(f"Market hours (NSE): {self.market_open} - {self.market_close}")
        
        # Current trade state (initialize early - needed by run_trading_day)
        self.current_strike = None
        self.current_symbol = None
        self.current_direction = None
        self.entry_price = None
        self.target_price = None
        self.stoploss_price = None
        self.actual_lots = 1  # Position size
        self.trade_active = False
        self.current_expiry = None  # Current option expiry
        self.entry_time = None  # Track entry time for duration analysis

        # Trade history
        self.trade_history = []

        # Trade metrics for analysis (captured at entry)
        self.current_trade_metrics = {}

        # Store option chain for monitoring (single source of truth)
        self.current_option_chain = None
        
        # PRODUCTION FIX: Cache option chain to avoid redundant API calls (data-source aware)
        self.cached_option_chain = None
        self.cached_option_chain_time = 0
        # Set cache duration based on data source
        if self.config.get("data_source") == "upstox":
            self.option_chain_cache_duration = 15  # Upstox: 15 seconds (faster refresh needed)
        else:
            self.option_chain_cache_duration = 30  # Zerodha: 30 seconds (no rate limiting)
        
        # PRODUCTION FIX: Rate limiting guard for API calls (data-source aware)
        self.last_api_call_time = 0
        # Set rate limiting based on data source
        if self.config.get("data_source") == "upstox":
            self.api_call_cooldown = 1.0  # Upstox needs rate limiting (1 second)
        else:
            self.api_call_cooldown = 0.0  # Zerodha has no rate limiting
        
        # Initialize Engine1 for historical data and VWAP calculation (data layer only)
        self.engine1 = Engine1MarketAnalyzer(self.kite_client, debug_instrument=None)
        logger.info("Engine 1 (Data Layer) initialized for historical data and VWAP")
        
        # Initialize State Manager for WebSocket data
        self.state_manager = StateManager(max_history=30)  # PRODUCTION FIX: Reduced from 100 to 30 for memory
        logger.info("State Manager initialized for WebSocket data")
        
        # Initialize Spot WebSocket for real-time spot prices (NSE)
        self.ws_client = WebSocketClient(
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            state_manager=self.state_manager
        )
        logger.info("Spot WebSocket Client initialized")
        
        # Initialize Options WebSocket for real-time OI/Volume (NFO)
        self.options_ws_client = OptionsWebSocket(
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            state=self.state_manager
        )
        logger.info("Options WebSocket Client initialized")
        
        # Load instruments cache at startup (CRITICAL - do this once!)
        logger.info("Loading instruments cache at startup...")
        
        # PRODUCTION FIX: Load only necessary instruments to reduce memory
        if self.symbols and len(self.symbols) == 1 and self.symbols[0] == "NIFTY":
            logger.info("Loading NIFTY instruments only (memory optimization)")
            self.kite_client.load_instruments_optimized("NFO")  # Still need NFO for options
            # Skip full NSE load for memory
        else:
            self.kite_client.load_instruments_optimized("NFO")
            self.kite_client.load_nse_instruments()  # Load NSE for stock fallback
        
        logger.info("Instruments cache loaded successfully")
        
        # Initialize WebSocket connection for real-time data
        logger.info("Initializing WebSocket for real-time market data...")
        
        # Initialize Consensus Architecture Services
        logger.info("Initializing Consensus Architecture Services...")
        
        # Initialize independent services
        try:
            self.optionstar_service = OptionStarService()
            logger.info("OptionStar Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize OptionStar Service: {e}")
            logger.warning("Continuing without OptionStar - institutional walls analysis will be disabled!")
            self.optionstar_service = None
        
        try:
            self.market_analyzer_service = MarketAnalyzerService(optionstar_service=self.optionstar_service)
            logger.info("Market Analyzer Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Market Analyzer Service: {e}")
            logger.warning("Continuing without Market Analyzer - market analysis will be limited!")
            self.market_analyzer_service = None
        
        try:
            self.breakout_entry_service = BreakoutEntryService()
            logger.info("Breakout Entry Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Breakout Entry Service: {e}")
            logger.warning("Continuing without Breakout Entry - breakout detection will be disabled!")
            self.breakout_entry_service = None
        
        try:
            self.execution_brain_service = ExecutionBrainService()
            logger.info("Execution Brain Service initialized (Final Authority)")
        except Exception as e:
            logger.error(f"Failed to initialize Execution Brain Service: {e}")
            logger.warning("Continuing without Execution Brain - final trade execution logic will be limited!")
            self.execution_brain_service = None
        
        try:
            self.trade_manager_service = TradeManagerService(max_daily_loss=3000, config=self.config)
            logger.info("Trade Manager Service initialized (Live Dashboard)")
        except Exception as e:
            logger.error(f"Failed to initialize Trade Manager Service: {e}")
            logger.warning("Continuing without Trade Manager - trade monitoring and dashboard will be limited!")
            self.trade_manager_service = None
        
        try:
            self.smart_strike_service = SmartStrikeService()
            logger.info("Smart Strike Service initialized (Combined Strike Selector + Elite Strike)")
        except Exception as e:
            logger.error(f"Failed to initialize Smart Strike Service: {e}")
            logger.warning("Continuing without Smart Strike - strike selection will use basic fallback!")
            self.smart_strike_service = None
        
        # Start Smart Strike Service
        if self.smart_strike_service:
            try:
                self.smart_strike_service.start()
                logger.info("Smart Strike Service started (combined selection + optimization)")
            except Exception as e:
                logger.error(f"Failed to start Smart Strike Service: {e}")
                logger.warning("Continuing without Smart Strike Service")
        
        # Initialize MCX Sentiment Service (optional filter layer)
        # PRODUCTION FIX: Disabled for memory optimization
        try:
            self.mcx_sentiment_service = None  # PRODUCTION FIX: Disabled for memory
            logger.info("MCX Sentiment Service disabled (memory optimization)")
        except Exception as e:
            logger.error(f"Failed to initialize MCX Sentiment Service: {e}")
            logger.warning("Continuing without MCX Sentiment - MCX confirmation filter will be disabled!")
            self.mcx_sentiment_service = None
        
        # Initialize Watchdog Service (health monitoring - enabled by default)
        # PRODUCTION FIX: Disabled for memory optimization
        try:
            self.watchdog_service = None  # PRODUCTION FIX: Disabled for memory
            logger.info("Watchdog Service disabled (memory optimization)")
        except Exception as e:
            logger.error(f"Failed to initialize Watchdog Service: {e}")
            logger.warning("Continuing without Watchdog - health monitoring will be disabled!")
            self.watchdog_service = None
        
        logger.info("Clean Architecture ready (5 core services + optional boosters)")
        
        # Start OptionStar continuous monitoring
        if self.optionstar_service:
            symbols_to_monitor = self.symbols if self.symbols else list(self.config.get('instruments', {}).keys())
            # Filter out MCX symbols for OptionStar (NSE only)
            mcx_symbols = ['CRUDEOIL', 'NATGAS', 'GOLDM', 'SILVERM', 'NATURALGAS', 'COPPER', 'ZINC', 'LEAD', 'ALUMINIUM']
            symbols_to_monitor = [sym for sym in symbols_to_monitor if sym not in mcx_symbols]
            self.optionstar_service.start_continuous_monitoring(
                symbols=symbols_to_monitor,
                option_chain_provider=self.get_option_chain_for_optionstar
            )
            logger.info(f"OptionStar continuous monitoring started for {len(symbols_to_monitor)} NSE symbols")

        
        # Initialize historical data for all configured instruments (best effort)
        logger.info("Initializing historical data for Engine 1...")
        all_instruments = self.symbols if self.symbols else self.config.get('instruments', {}).keys()
        for symbol in all_instruments:
            try:
                self.engine1.initialize_historical_data(symbol)
            except Exception as e:
                logger.debug(f"Could not initialize historical data for {symbol}: {e} (will use live data)")
        logger.info("Historical data initialization complete (some instruments may use live data only)")
        
        logger.info(f"Single Strike Trader initialized with ₹{investment_amount} investment")
        
        # Get symbols to monitor
        if self.symbols:
            monitor_symbols = self.symbols
        else:
            # Use all instruments from config (NSE-only - filter out MCX)
            all_instruments = list(self.config.get('instruments', {}).keys())
            # Filter out MCX symbols - keep only NSE symbols
            mcx_symbols = ['CRUDEOIL', 'NATGAS', 'GOLDM', 'SILVERM', 'NATURALGAS', 'COPPER', 'ZINC', 'LEAD', 'ALUMINIUM']
            monitor_symbols = [sym for sym in all_instruments if sym not in mcx_symbols]
            logger.info(f"NSE-only mode: Filtered out MCX symbols. Trading {len(monitor_symbols)} NSE instruments: {monitor_symbols}")

        
        # ========================================
        # SPOT WEBSOCKET (NSE) - For spot prices
        # ========================================
        logger.info(f"Loading Spot WebSocket tokens for {len(monitor_symbols)} symbols...")
        spot_tokens = self.ws_client.load_tokens(monitor_symbols)
        
        # PRODUCTION FIX: Skip Zerodha WebSocket when using Upstox as data source
        if self.config.get("data_source") == "upstox":
            logger.info("[UPSTOX] Skipping Zerodha WebSocket - using Upstox API for market data")
            logger.info("[UPSTOX] Market data will be fetched from Upstox REST API")
            spot_tokens = []  # Skip WebSocket connection
        else:
            if spot_tokens:
                logger.info(f"Connecting to Spot WebSocket with {len(spot_tokens)} tokens...")
                self.ws_client.connect(spot_tokens)
                logger.info("Spot WebSocket connected successfully - Real-time spot prices streaming")
                
                # PRODUCTION FIX: Longer wait to avoid rapid WebSocket connections
                logger.info("[PERF] Waiting 10 seconds before Options WebSocket to avoid rate limiting...")
                time.sleep(10)
            else:
                logger.warning("No Spot WebSocket tokens loaded - falling back to REST API")
        
        # ========================================
        # OPTIONS WEBSOCKET (NFO) - For OI/Volume
        # PRODUCTION FIX: Temporarily disabled to avoid rate limiting
        # ========================================
        logger.info("[PERF] Options WebSocket temporarily disabled to avoid rate limiting")
        logger.info("[PERF] Using REST API fallback for OI/Volume data")
        
        # Skip Options WebSocket for now
        all_option_tokens = []
        
        # Skip option token loading since Options WebSocket is disabled
        
        # Skip Options WebSocket connection since it's disabled
        logger.info("[PERF] Options WebSocket connection skipped")
        
        # Update WebSocket status
        self.state_manager.set_websocket_connected(len(spot_tokens) > 0 or len(all_option_tokens) > 0)
        
        logger.info("WebSocket initialization complete - Starting trading loop")

        # Initialize OI metrics variables
        self.current_pcr = 0
        self.current_delta_data = {}
        self.current_atm = 0
        
        # Institutional walls cache (OptionStar data)
        self.institutional_walls = {}  # symbol -> institutional data
        
        # Price tracking for price change calculation
        self.previous_prices = {}  # symbol -> previous spot price
        
        # Initialize OI metrics variables
        self.market_snapshot = {}  # symbol -> market data
        
        # Enhanced state tracking for better data resolution
        self.price_history = {}  # symbol -> list of last 5 prices
        self.oi_history = {}  # symbol -> list of last 5 OI values
        self.max_history_length = 5  # Keep last 5 data points
    
    def check_rate_limit(self):
        """Check if we can make an API call based on rate limiting"""
        current_time = time.time()
        if current_time - self.last_api_call_time < self.api_call_cooldown:
            wait_time = self.api_call_cooldown - (current_time - self.last_api_call_time)
            logger.warning(f"[RATE LIMIT] API call blocked, wait {wait_time:.1f}s")
            return False
        return True
    
    def record_api_call(self):
        """Record that an API call was made"""
        self.last_api_call_time = time.time()
    
    # -------------------------
    # PRINT CLEAN DASHBOARD
    # -------------------------
    def print_clean_dashboard(self):
        """Print human-readable market snapshot table"""
        print("\n" + "=" * 100)
        print(" LIVE MARKET SNAPSHOT (CLEAN VIEW)")
        print("=" * 100)
        
        header = f"{'SYMBOL':<10}{'SPOT':<10}{'ATM':<10}{'PCR':<8}{'BIAS':<10}{'SUPPORT':<10}{'RESIST':<10}{'SIGNAL':<10}"
        print(header)
        print("-" * 100)
        
        if not hasattr(self, 'market_snapshot') or not self.market_snapshot:
            print("No market data available yet - waiting for data...")
        else:
            for symbol, data in self.market_snapshot.items():
                print(f"{symbol:<10}"
                      f"{data.get('spot', '-'):<10.2f}"
                      f"{data.get('atm', '-'):<10.0f}"
                      f"{data.get('pcr', '-'):<8.2f}"
                      f"{data.get('bias', '-'):<10}"
                      f"{data.get('support', '-'):<10.0f}"
                      f"{data.get('resistance', '-'):<10.0f}"
                      f"{data.get('signal', 'NONE'):<10}")
        
        print("=" * 100)

    def update_market_snapshot(self):
        """Update market snapshot with current data for all symbols (NSE-only)"""
        instruments = self.symbols if self.symbols else self.config.get('instruments', {}).keys()
        
        for symbol in instruments:
            try:
                # NFO/NSE logic only
                spot_price = self.get_spot_price(symbol, bypass_cache=True)
                if spot_price == 0:
                    continue
                
                # Get option chain for PCR calculation
                option_chain = self.get_option_chain_for_optionstar(symbol)
                if not option_chain:
                    continue
                
                # Calculate PCR
                total_ce_oi = sum(item.get('oi', 0) for item in option_chain if item.get('type') == 'CE')  # FIX: Upstox uses 'oi'
                total_pe_oi = sum(item.get('oi', 0) for item in option_chain if item.get('type') == 'PE')  # FIX: Upstox uses 'oi'
                pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
                
                # Calculate institutional walls
                calls = []
                puts = []
                for item in option_chain:
                    if item.get('type') == 'CE':
                        calls.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('oi', 0)  # FIX: Upstox uses 'oi', not 'call_oi'
                            })
                    elif item.get('type') == 'PE':
                        puts.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('oi', 0)  # FIX: Upstox uses 'oi', not 'put_oi'
                        })
                
                option_chain_data = {"calls": calls, "puts": puts}
                institutional_data = calculate_institutional_walls(option_chain_data, spot_price, symbol)
                
                if "error" not in institutional_data:
                    self.market_snapshot[symbol] = {
                        "spot": spot_price,
                        "atm": spot_price,
                        "pcr": pcr,
                        "bias": institutional_data.get("trend_bias", "NEUTRAL"),
                        "support": institutional_data.get("support", {}).get("strike", 0),
                        "resistance": institutional_data.get("resistance", {}).get("strike", 0),
                        "signal": self.market_snapshot.get(symbol, {}).get("signal", "NONE")
                    }
            except Exception as e:
                logger.debug(f"Could not update market snapshot for {symbol}: {e}")

    def is_market_open(self):
        """Check if market is currently open"""
        now = datetime.now().time()
        return self.market_open <= now <= self.market_close

    def init_llm_analyzer(self):
        """Initialize LLM analyzer based on config (DEPRECATED - using independent service)"""
        # This method is deprecated - we now use self.llm_analyzer_service
        # Keeping this for backward compatibility, but it does nothing
        logger.info("LLM Analyzer initialization handled by independent service (llm_analyzer_service)")
        pass

    def _rate_limit_guard(self):
        """PRODUCTION FIX: Rate limit API calls to avoid 429 errors"""
        import time
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call_time
        
        if time_since_last_call < self.api_call_interval:
            sleep_time = self.api_call_interval - time_since_last_call
            logger.debug(f"[RATE LIMIT] Sleeping {sleep_time:.2f}s to respect rate limit")
            time.sleep(sleep_time)
        
        self.last_api_call_time = time.time()
    
    def get_spot_price(self, symbol, bypass_cache=False):
        """Get current spot price for symbol with caching and rate limiting"""
        import time
        
        # PRODUCTION FIX: Check cache first
        current_time = time.time()
        if not bypass_cache and symbol in self.spot_price_cache:
            cache_age = current_time - self.spot_price_cache_time[symbol]
            if cache_age < self.spot_price_cache_duration:
                logger.debug(f"[CACHE] Using cached spot price for {symbol} (age: {cache_age:.1f}s)")
                return self.spot_price_cache[symbol]
        
        # DATA SOURCE SEPARATION: Use correct data source based on config
        if self.config.get("data_source") == "upstox":
            # UPSTOX PATH: Completely independent of Zerodha
            if self.upstox_client:
                self._rate_limit_guard()  # PRODUCTION FIX: Rate limit before API call
                logger.info(f"[UPSTOX] Using Upstox client for {symbol}")
                price = self._get_spot_price_upstox(symbol)
                
                # PRODUCTION FIX: Cache the result
                if price and price > 0:
                    self.spot_price_cache[symbol] = price
                    self.spot_price_cache_time[symbol] = current_time
                
                return price
            else:
                logger.error(f"[UPSTOX] Upstox client not available for {symbol}")
                return 0
        else:
            # ZERODHA PATH: Use WebSocket data
            try:
                price = self.state_manager.get_latest_price(symbol)
                
                if price is None:
                    logger.warning(f"[WS ONLY] WebSocket data not available for {symbol} - skipping (no REST fallback)")
                    return 0
            
                # PRODUCTION FIX: Cache the WebSocket result
                if price and price > 0:
                    self.spot_price_cache[symbol] = price
                    self.spot_price_cache_time[symbol] = current_time
                
                return price
                
            except Exception as e:
                logger.error(f"Error getting spot price from WebSocket: {e}")
                return 0
    
    def _get_spot_price_upstox(self, symbol):
        """Get spot price from Upstox API with rate limiting, key format handling, and API failure fallback"""
        import time
        
        try:
            # PRODUCTION FIX: Stop API spam - check if we have recent cached data
            current_time = time.time()
            if self.cached_spot_price and (current_time - self.last_spot_time) < 10:
                logger.debug(f"[API SPAM GUARD] Using cached spot price (age: {current_time - self.last_spot_time:.1f}s)")
                return self.cached_spot_price
            
            if not self.upstox_client:
                logger.warning("[UPSTOX] Upstox client not available")
                # PRODUCTION FIX: Fallback to cached price
                if self.cached_spot_price:
                    logger.warning("[UPSTOX] Using cached spot price as fallback")
                    return self.cached_spot_price
                return 0
            
            # PRODUCTION FIX: Rate limit before API call
            self._rate_limit_guard()
            
            # Map symbol to Upstox instrument key
            # NOTE: Upstox API uses both PIPE (|) and COLON (:) in response keys - handle both
            if symbol == "NIFTY":
                instrument_key_request = "NSE_INDEX|Nifty 50"  # For API request
                possible_response_keys = ["NSE_INDEX|Nifty 50", "NSE_INDEX:Nifty 50"]  # For response parsing
            elif symbol == "BANKNIFTY":
                instrument_key_request = "NSE_INDEX|Nifty Bank"
                possible_response_keys = ["NSE_INDEX|Nifty Bank", "NSE_INDEX:Nifty Bank"]
            else:
                instrument_key_request = f"NSE_EQ|{symbol}"
                possible_response_keys = [f"NSE_EQ|{symbol}", f"NSE_EQ:{symbol}"]
            
            # Get market quote from Upstox
            quote_data = self.upstox_client.get_market_quote(instrument_key_request)
            
            # PRODUCTION FIX: HARD GUARD for API failure
            if not quote_data or "data" not in quote_data:
                logger.warning("[UPSTOX] API failed or rate limited (429) - using cached spot price")
                self.spot_api_failure_count += 1
                if self.spot_api_failure_count >= self.max_api_failures:
                    logger.error(f"[UPSTOX] API failure count {self.spot_api_failure_count} - may be rate limited")
                # PRODUCTION FIX: Fallback to cached price
                if self.cached_spot_price:
                    logger.warning(f"[UPSTOX] Using cached spot price: {self.cached_spot_price}")
                    return self.cached_spot_price
                else:
                    logger.error("[UPSTOX] No cached price available - SKIP cycle")
                    return 0
            
            # PRODUCTION FIX: Try all possible key formats
            for key in possible_response_keys:
                if key in quote_data:
                    quote = quote_data[key]
                    if quote and "last_price" in quote:
                        price = quote["last_price"]
                        logger.info(f"[UPSTOX] Got price for {symbol}: {price}")
                        # PRODUCTION FIX: Cache successful API response
                        self.cached_spot_price = price
                        self.last_spot_time = current_time
                        self.spot_api_failure_count = 0  # Reset failure count on success
                        return price
            
            # PRODUCTION FIX: Key mismatch - fallback to cached price
            logger.warning(f"[UPSTOX] Key mismatch. Tried keys: {possible_response_keys}. Available: {list(quote_data.keys()) if quote_data else 'None'}")
            if self.cached_spot_price:
                logger.warning(f"[UPSTOX] Key mismatch - using cached spot price: {self.cached_spot_price}")
                return self.cached_spot_price
            
            return 0
            
        except Exception as e:
            logger.error(f"Error getting spot price from Upstox: {e}")
            return 0
    
    def _get_spot_price_rest(self, symbol, bypass_cache=False):
        """Fallback REST API method for spot price (rate-limited)"""
        try:
            if symbol == "NIFTY":
                instrument_token = "NSE:NIFTY 50"
            elif symbol == "BANKNIFTY":
                instrument_token = "NSE:NIFTY BANK"
            else:
                instrument_token = f"NSE:{symbol}"

            # Try cache first (NO API CALL)
            cached_price = self.kite_client.get_cached_ltp(instrument_token)
            if cached_price and not bypass_cache:
                # Handle both dict and float returns
                if isinstance(cached_price, dict):
                    return cached_price.get('last_price', 0)
                return cached_price
            
            # Fallback to safe API fetch with rate limiting
            ltp_data = self.kite_client.safe_ltp_fetch([instrument_token])
            if ltp_data and instrument_token in ltp_data:
                # Handle both dict and float returns
                price = ltp_data[instrument_token]
                if isinstance(price, dict):
                    return price.get('last_price', 0)
                return price
        except Exception as e:
            logger.error(f"Error getting spot price (REST fallback) for {symbol}: {e}")
        return 0

    def get_vwap_price(self, symbol):
        """Get real VWAP price from Engine1 (not approximation)"""
        spot_price = self.get_spot_price(symbol)
        if spot_price == 0:
            return 0

        # Use Engine1 to calculate real VWAP from price history
        if not hasattr(self, 'engine1'):
            logger.warning("Engine1 not initialized, using spot price as VWAP")
            return spot_price
        vwap = self.engine1.update_price(symbol, spot_price)
        return vwap

    def get_option_chain_for_optionstar(self, symbol):
        """Get option chain data for OptionStar continuous monitoring"""
        try:
            spot_price = self.get_spot_price(symbol, bypass_cache=True)
            if spot_price == 0:
                return None
            
            option_chain = self.get_real_option_chain(symbol, spot_price)
            if not option_chain:
                return None
            
            # CRITICAL FIX: Handle both data formats (Zerodha uses call_oi/put_oi, Upstox uses oi)
            # Convert to OptionStar format
            calls = []
            puts = []
            for item in option_chain:
                if item.get('type') == 'CE':
                    # Try both field names for compatibility
                    oi_value = item.get('oi', 0) or item.get('call_oi', 0)
                    
                    calls.append({
                        'strikePrice': item.get('strike'),
                        'lastPrice': item.get('last_price', 0),
                        'openInterest': oi_value
                    })
                    
                    # DEBUG: Log OI extraction
                    logger.info(f"[DEBUG FIX] CE Strike {item.get('strike')} OI: {oi_value}")
                    
                elif item.get('type') == 'PE':
                    # Try both field names for compatibility
                    oi_value = item.get('oi', 0) or item.get('put_oi', 0)
                    
                    puts.append({
                        'strikePrice': item.get('strike'),
                        'lastPrice': item.get('last_price', 0),
                        'openInterest': oi_value
                    })
                    
                    # DEBUG: Log OI extraction
                    logger.info(f"[DEBUG FIX] PE Strike {item.get('strike')} OI: {oi_value}")
            
            # DEBUG: Verify total OI before sending to OptionStar
            total_ce_oi = sum(call.get('openInterest', 0) for call in calls)
            total_pe_oi = sum(put.get('openInterest', 0) for put in puts)
            logger.info(f"[DEBUG FIX] Total CE OI: {total_ce_oi}, Total PE OI: {total_pe_oi}")
            
            return {
                'calls': calls,
                'puts': puts,
                'spotPrice': spot_price
            }
            
        except Exception as e:
            logger.error(f"Error getting option chain for OptionStar: {e}")
            return None
    
    def get_upstox_option_chain(self, symbol, expiry_date):
        """Get option chain data from Upstox API with rate limiting"""
        try:
            if not self.upstox_client:
                logger.warning("[UPSTOX] Upstox client not available")
                return None
            
            # PRODUCTION FIX: Rate limit before API call
            self._rate_limit_guard()
            
            # Map symbol to Upstox instrument key
            if symbol == "NIFTY":
                instrument_key = "NSE_INDEX|Nifty 50"
            elif symbol == "BANKNIFTY":
                instrument_key = "NSE_INDEX|Nifty Bank"
            else:
                instrument_key = f"NSE_EQ|{symbol}"
            
            logger.info(f"[UPSTOX] Fetching option chain for {instrument_key} expiry {expiry_date}")
            
            # Fetch option chain from Upstox
            option_chain_data = self.upstox_client.get_option_chain(instrument_key, expiry_date)
            
            if not option_chain_data:
                logger.error(f"[UPSTOX] No option chain data returned")
                return None
            
            # Parse Upstox option chain format and convert to internal format
            parsed_chain = self.parse_upstox_option_chain(option_chain_data)
            
            logger.info(f"[UPSTOX] Parsed {len(parsed_chain)} strikes from option chain")
            return parsed_chain
            
        except Exception as e:
            logger.error(f"[UPSTOX] Error fetching option chain: {e}")
            return None
    
    def parse_upstox_option_chain(self, upstox_data):
        """Parse Upstox option chain data into internal format based on actual API response"""
        try:
            parsed_chain = []
            
            # Upstox returns data in this format based on API documentation:
            # {
            #   "status": "success",
            #   "data": [
            #     {
            #       "expiry": "2025-02-13",
            #       "pcr": 7515.3,
            #       "strike_price": 21100,
            #       "underlying_spot_price": 22976.2,
            #       "call_options": {
            #         "instrument_key": "NSE_FO|51059",
            #         "market_data": { "ltp": 2449.9, "volume": 0, "oi": 750, ... },
            #         "option_greeks": { "delta": 0.743, "iv": 262.31, ... }
            #       },
            #       "put_options": {
            #         "instrument_key": "NSE_FO|51060",
            #         "market_data": { "ltp": 0.3, "volume": 22315725, "oi": 5636475, ... },
            #         "option_greeks": { "delta": -0.0013, "iv": 50.78, ... }
            #       }
            #     }
            #   ]
            # }
            
            if isinstance(upstox_data, list):
                for strike_data in upstox_data:
                    strike = strike_data.get("strike_price")
                    spot_price = strike_data.get("underlying_spot_price")
                    pcr = strike_data.get("pcr")
                    expiry = strike_data.get("expiry", "")  # FIX: Extract expiry from Upstox data
                    
                    # Call option data
                    call_options = strike_data.get("call_options", {})
                    if call_options:
                        call_market_data = call_options.get("market_data", {})
                        call_greeks = call_options.get("option_greeks", {})
                        
                        parsed_chain.append({
                            'strike': strike,
                            'type': 'CE',
                            'last_price': call_market_data.get("ltp", 0),
                            'oi': call_market_data.get("oi", 0),
                            'volume': call_market_data.get("volume", 0),
                            'iv': call_greeks.get("iv", 0),
                            'delta': call_greeks.get("delta", 0),
                            'gamma': call_greeks.get("gamma", 0),
                            'theta': call_greeks.get("theta", 0),
                            'vega': call_greeks.get("vega", 0),
                            'pop': call_greeks.get("pop", 0),
                            'instrument_key': call_options.get("instrument_key", ""),
                            'instrument_token': call_options.get("instrument_key", ""),  # FIX: Map instrument_key to instrument_token for Zerodha compatibility
                            'bid_price': call_market_data.get("bid_price", 0),
                            'ask_price': call_market_data.get("ask_price", 0),
                            'close_price': call_market_data.get("close_price", 0),
                            'prev_oi': call_market_data.get("prev_oi", 0),
                            'spot_price': spot_price,
                            'pcr': pcr,
                            'expiry': expiry  # FIX: Add expiry field
                        })
                    
                    # Put option data
                    put_options = strike_data.get("put_options", {})
                    if put_options:
                        put_market_data = put_options.get("market_data", {})
                        put_greeks = put_options.get("option_greeks", {})
                        
                        parsed_chain.append({
                            'strike': strike,
                            'type': 'PE',
                            'last_price': put_market_data.get("ltp", 0),
                            'oi': put_market_data.get("oi", 0),
                            'volume': put_market_data.get("volume", 0),
                            'iv': put_greeks.get("iv", 0),
                            'delta': put_greeks.get("delta", 0),
                            'gamma': put_greeks.get("gamma", 0),
                            'theta': put_greeks.get("theta", 0),
                            'vega': put_greeks.get("vega", 0),
                            'pop': put_greeks.get("pop", 0),
                            'instrument_key': put_options.get("instrument_key", ""),
                            'instrument_token': put_options.get("instrument_key", ""),  # FIX: Map instrument_key to instrument_token for Zerodha compatibility
                            'bid_price': put_market_data.get("bid_price", 0),
                            'ask_price': put_market_data.get("ask_price", 0),
                            'close_price': put_market_data.get("close_price", 0),
                            'prev_oi': put_market_data.get("prev_oi", 0),
                            'spot_price': spot_price,
                            'pcr': pcr,
                            'expiry': expiry  # FIX: Add expiry field
                        })
            
            logger.info(f"[UPSTOX] Parsed option chain: {len(parsed_chain)} contracts")
            return parsed_chain
            
        except Exception as e:
            logger.error(f"[UPSTOX] Error parsing option chain: {e}")
            return []

    def get_real_option_chain(self, symbol, spot_price):
        """Fetch real option chain using optimized architecture (Upstox preferred, Zerodha fallback)"""
        try:
            # PRODUCTION FIX: Use cached option chain to avoid redundant API calls
            current_time = time.time()
            if (self.cached_option_chain and 
                current_time - self.cached_option_chain_time < self.option_chain_cache_duration):
                
                # CRITICAL FIX: Validate cached data before using it
                total_ce_oi = sum(item.get('oi', 0) for item in self.cached_option_chain if item.get('type') == 'CE')
                total_pe_oi = sum(item.get('oi', 0) for item in self.cached_option_chain if item.get('type') == 'PE')
                
                if total_ce_oi == 0 and total_pe_oi == 0:
                    logger.warning(f"[CACHE BUG] Invalid OI detected in cache (CE: {total_ce_oi}, PE: {total_pe_oi}) - refetching")
                    logger.warning(f"[CACHE BUG] Cache contains wrong format data - forcing refresh")
                    # Force refresh by skipping cache
                    pass
                else:
                    logger.info(f"[PERF] Using cached option chain (age: {current_time - self.cached_option_chain_time:.1f}s)")
                    logger.info(f"[CACHE VALID] Cached OI check - CE: {total_ce_oi}, PE: {total_pe_oi}")
                    return self.cached_option_chain
            
            # PRODUCTION FIX: Rate limit before API call
            self._rate_limit_guard()
            
            # PRODUCTION FIX: Use Upstox if configured as data source
            if self.config.get("data_source") == "upstox" and self.upstox_client:
                logger.info(f"[UPSTOX] Fetching option chain from Upstox API for {symbol}")
                
                # First, get available expiries from Upstox contracts API
                if symbol == "NIFTY":
                    instrument_key = "NSE_INDEX|Nifty 50"
                elif symbol == "BANKNIFTY":
                    instrument_key = "NSE_INDEX|Nifty Bank"
                else:
                    instrument_key = f"NSE_EQ|{symbol}"
                
                # Get available contracts to find valid expiry
                # PRODUCTION FIX: Rate limit before API call
                self._rate_limit_guard()
                contracts = self.upstox_client.get_option_contracts(instrument_key)
                
                if contracts:
                    # Get the nearest expiry WITHIN 7 DAYS (weekly expiry only)
                    from datetime import datetime, timedelta
                    today = datetime.now().date()
                    
                    expiries = sorted(set([c.get('expiry') for c in contracts if c.get('expiry')]))
                    # Filter to only expiries within 7 days (weekly/near-term)
                    valid_expiries = [
                        exp for exp in expiries
                        if (datetime.strptime(exp, '%Y-%m-%d').date() - today).days <= 7
                    ]
                    
                    if valid_expiries:
                        # Use the first (nearest) valid expiry
                        expiry_date = valid_expiries[0]
                        logger.info(f"[UPSTOX] Using nearest valid expiry: {expiry_date}")
                        
                        # Fetch from Upstox
                        upstox_chain = self.get_upstox_option_chain(symbol, expiry_date)
                        
                        if upstox_chain:
                            # CRITICAL FIX: Convert Upstox format to OptionStar-compatible format before caching
                            option_chain_converted = []
                            for item in upstox_chain:
                                if item.get('type') == 'CE':
                                    oi_value = item.get('oi', 0)
                                    option_chain_converted.append({
                                        'strike': item.get('strike'),
                                        'expiry': item.get('expiry', ''),
                                        'call_oi': oi_value,
                                        'put_oi': 0,
                                        'last_price': item.get('last_price', 0),
                                        'type': 'CE',
                                        'oi': oi_value,  # Add unified 'oi' field for OptionStar
                                        'instrument_token': item.get('instrument_token'),
                                        'tradingsymbol': item.get('tradingsymbol')
                                    })
                                elif item.get('type') == 'PE':
                                    oi_value = item.get('oi', 0)
                                    option_chain_converted.append({
                                        'strike': item.get('strike'),
                                        'expiry': item.get('expiry', ''),
                                        'call_oi': 0,
                                        'put_oi': oi_value,
                                        'last_price': item.get('last_price', 0),
                                        'type': 'PE',
                                        'oi': oi_value,  # Add unified 'oi' field for OptionStar
                                        'instrument_token': item.get('instrument_token'),
                                        'tradingsymbol': item.get('tradingsymbol')
                                    })
                            
                            # Cache the converted format (not raw format)
                            self.cached_option_chain = option_chain_converted
                            self.cached_option_chain_time = current_time
                            logger.info(f"[UPSTOX] Successfully fetched and cached option chain with {len(option_chain_converted)} contracts")
                            
                            # DEBUG: Verify OI extraction from converted format
                            if option_chain_converted:
                                sample_ce = next((item for item in option_chain_converted if item.get('type') == 'CE'), None)
                                sample_pe = next((item for item in option_chain_converted if item.get('type') == 'PE'), None)
                                if sample_ce:
                                    logger.info(f"[FIX OI] CE Strike {sample_ce.get('strike')} OI: {sample_ce.get('oi', 0)}")
                                if sample_pe:
                                    logger.info(f"[FIX OI] PE Strike {sample_pe.get('strike')} OI: {sample_pe.get('oi', 0)}")
                            
                            return option_chain_converted
                        else:
                            logger.warning(f"[UPSTOX] Failed to fetch option chain, falling back to Zerodha")
                    else:
                        logger.warning(f"[UPSTOX] No valid expiries within 7 days, falling back to Zerodha")
                else:
                    logger.warning(f"[UPSTOX] No contracts found, falling back to Zerodha")
            
            # Fallback to Zerodha API
            logger.info(f"[ZERODHA] Fetching optimized option chain from Zerodha API for {symbol}")

            # PRODUCTION FIX: Check rate limit before API call
            if not self.check_rate_limit():
                logger.warning(f"[RATE LIMIT] Option chain fetch blocked, using cached data")
                return self.cached_option_chain
            
            # Record API call
            self.record_api_call()

            # Use optimized option chain (Prop-Desk Level)
            chain, pcr, delta_data, atm = self.kite_client.get_option_chain_optimized(symbol, spot_price)

            if not chain:
                logger.warning(f"{symbol}: No option chain data from optimized API")
                return None

            # FIX: Get the original options data to preserve instrument_token and tradingsymbol
            # Load instruments to map strike back to instrument data
            option_map = self.kite_client.load_instruments_optimized("NFO")
            if symbol not in option_map:
                logger.warning(f"No options found for {symbol}")
                return None
            
            all_options = option_map[symbol]
            
            # DEBUG: Log what we have in all_options
            logger.info(f"[DEBUG] Total options for {symbol}: {len(all_options)}")
            if all_options:
                logger.info(f"[DEBUG] Sample option data: {all_options[0]}")
            
            # Create a mapping from (strike, type, expiry) to instrument data
            # FIX: Add expiry to key to avoid picking wrong expiry
            instrument_map = {}
            for opt in all_options:
                strike = opt.get("strike", 0)
                expiry = opt.get("expiry")
                # Use tradingsymbol to determine type (CE/PE)
                tradingsymbol = opt.get("tradingsymbol", "")
                typ = "CE" if "CE" in tradingsymbol else "PE"
                instrument_map[(strike, typ, expiry)] = opt
            
            # DEBUG: Log instrument_map sample
            if instrument_map:
                sample_key = list(instrument_map.keys())[0]
                logger.info(f"[DEBUG] Sample instrument_map key: {sample_key}, value: {instrument_map[sample_key]}")

            # Convert optimized chain to Engine1 format with instrument data
            # Engine1 expects: [{'strike': x, 'call_oi': y, 'put_oi': z, 'last_price': w, 'type': 'CE/PE', 'instrument_token': ..., 'tradingsymbol': ...}]
            option_chain = []

            for strike, data in chain.items():
                ce_data = data.get("CE", {})
                pe_data = data.get("PE", {})
                expiry = ce_data.get("expiry", pe_data.get("expiry", ""))  # Add expiry field

                if ce_data and ce_data.get("ltp", 0) > 0:
                    # Get instrument data for this strike and expiry
                    ce_instrument = instrument_map.get((strike, "CE", expiry), {})
                    option_chain.append({
                        'strike': strike,
                        'expiry': expiry,
                        'call_oi': ce_data.get("oi", 0),
                        'put_oi': 0,
                        'last_price': ce_data.get("ltp", 0),
                        'type': 'CE',
                        'instrument_token': ce_instrument.get("instrument_token"),
                        'tradingsymbol': ce_instrument.get("tradingsymbol")
                    })

                if pe_data and pe_data.get("ltp", 0) > 0:
                    # Get instrument data for this strike and expiry
                    pe_instrument = instrument_map.get((strike, "PE", expiry), {})
                    option_chain.append({
                        'strike': strike,
                        'expiry': expiry,
                        'call_oi': 0,
                        'put_oi': pe_data.get("oi", 0),
                        'last_price': pe_data.get("ltp", 0),
                        'type': 'PE',
                        'instrument_token': pe_instrument.get("instrument_token"),
                        'tradingsymbol': pe_instrument.get("tradingsymbol")
                    })

            logger.info(f"Built option chain with {len(option_chain)} strikes from optimized API for {symbol}")
            logger.info(f"Optimized metrics - PCR: {pcr:.2f}, ATM: {atm}, ΔOI available: {len(delta_data)} strikes")
            logger.info(f"Option chain includes REAL OI data from Zerodha API with ΔOI tracking")

            # Store PCR and delta_data for Engine1 to use
            self.current_pcr = pcr
            self.current_delta_data = delta_data
            self.current_atm = atm

            # CRITICAL FIX: Cache the option chain in OptionStar-compatible format
            # Convert to OptionStar format before caching to avoid OI = 0 issues
            option_chain_converted = []
            for item in option_chain:
                # Convert Zerodha format (call_oi/put_oi) to OptionStar format (oi)
                if item.get('type') == 'CE':
                    oi_value = item.get('oi', 0) or item.get('call_oi', 0)
                    option_chain_converted.append({
                        'strike': item.get('strike'),
                        'expiry': item.get('expiry'),
                        'call_oi': oi_value,  # Keep original field for Engine1
                        'put_oi': 0,
                        'last_price': item.get('last_price', 0),
                        'type': 'CE',
                        'oi': oi_value,  # Add unified 'oi' field for OptionStar
                        'instrument_token': item.get('instrument_token'),
                        'tradingsymbol': item.get('tradingsymbol')
                    })
                elif item.get('type') == 'PE':
                    oi_value = item.get('oi', 0) or item.get('put_oi', 0)
                    option_chain_converted.append({
                        'strike': item.get('strike'),
                        'expiry': item.get('expiry'),
                        'call_oi': 0,
                        'put_oi': oi_value,  # Keep original field for Engine1
                        'last_price': item.get('last_price', 0),
                        'type': 'PE',
                        'oi': oi_value,  # Add unified 'oi' field for OptionStar
                        'instrument_token': item.get('instrument_token'),
                        'tradingsymbol': item.get('tradingsymbol')
                    })
            
            # Cache the converted format (not raw format)
            self.cached_option_chain = option_chain_converted
            self.cached_option_chain_time = current_time
            logger.info(f"[PERF] Cached option chain (duration: {self.option_chain_cache_duration}s)")
            
            # Return the converted format for consistency
            option_chain = option_chain_converted

            # DEBUG: Log option chain structure before return
            logger.info(f"[DEBUG] Option chain keys: {list(set([o.get('strike') for o in option_chain]))[:5]}")
            logger.info(f"[DEBUG] Option chain total contracts: {len(option_chain)}")
            
            return option_chain

        except Exception as e:
            logger.error(f"Error fetching optimized option chain for {symbol}: {e}")
            return None

    def select_best_strike(self):
        """Select the best strike using Strike Selector Service (Professional-grade selection)"""
        # Use specific symbols if provided, otherwise use all instruments from config
        if self.symbols:
            instruments = self.symbols
            logger.info(f"Trading specific symbols: {instruments}")
        else:
            instruments = self.config.get('instruments', {}).keys()
            logger.info(f"Trading all instruments from config")

        best_opportunity = None
        best_score = 0

        # FIX: Initialize execution_decision to prevent control-flow bug
        execution_decision = {"action": "SKIP", "score": 0}

        logger.info(f"Selecting best opportunity with current capital: ₹{self.current_capital:.2f}")
        logger.info("Using Strike Selector Service - Professional expiry & liquidity selection")

        for symbol in instruments:
            try:
                spot_price = self.get_spot_price(symbol, bypass_cache=False)  # Use WebSocket data
                if spot_price == 0:
                    continue

                # Enhanced price tracking using history (last 5 points)
                if symbol not in self.price_history:
                    self.price_history[symbol] = []
                
                self.price_history[symbol].append(spot_price)
                
                # Keep only last 5 prices
                if len(self.price_history[symbol]) > self.max_history_length:
                    self.price_history[symbol].pop(0)
                
                # Calculate price change using history (first to last in window)
                if len(self.price_history[symbol]) >= 2:
                    price_change = self.price_history[symbol][-1] - self.price_history[symbol][0]
                else:
                    price_change = 0  # Not enough history yet

                # Fetch REAL option chain from Zerodha API
                option_chain = self.get_real_option_chain(symbol, spot_price)
                
                if not option_chain:
                    logger.warning(f"{symbol}: No real option chain data from API, skipping")
                    continue

                # Calculate Institutional Walls (OptionStar)
                calls = []
                puts = []
                for item in option_chain:
                    if item.get('type') == 'CE':
                        calls.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('oi', 0)  # FIX: Upstox uses 'oi', not 'call_oi'
                        })
                    elif item.get('type') == 'PE':
                        puts.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('oi', 0)  # FIX: Upstox uses 'oi', not 'put_oi'
                        })
                
                option_chain_data = {"calls": calls, "puts": puts}
                institutional_data = calculate_institutional_walls(option_chain_data, spot_price, symbol)
                
                if "error" in institutional_data:
                    logger.warning(f"{symbol}: Could not calculate institutional walls, skipping")
                    continue
                
                self.institutional_walls[symbol] = institutional_data
                
                # ========================================
                # UPDATE MARKET SNAPSHOT FOR DASHBOARD
                # ========================================
                self.market_snapshot[symbol] = {
                    "spot": spot_price,
                    "atm": spot_price,  # Will be updated with actual ATM
                    "pcr": pcr if 'pcr' in locals() else 0,
                    "bias": institutional_data.get("trend_bias", "NEUTRAL"),
                    "support": institutional_data.get("support", {}).get("strike", 0),
                    "resistance": institutional_data.get("resistance", {}).get("strike", 0),
                    "signal": "NONE"
                }
                
                # Update Engine1 for VWAP and price tracking (Engine 1 still needed for data layer)
                if hasattr(self, 'engine1'):
                    self.engine1.update_option_chain(symbol, option_chain)
                    self.engine1.update_price(symbol, spot_price)
                    vwap = self.engine1.get_vwap(symbol)
                else:
                    logger.warning("Engine1 not initialized, using spot price as VWAP")
                    vwap = spot_price
                
                # Calculate PCR and delta OI
                total_ce_oi = sum(item.get('oi', 0) for item in option_chain if item.get('type') == 'CE')  # FIX: Upstox uses 'oi'
                total_pe_oi = sum(item.get('oi', 0) for item in option_chain if item.get('type') == 'PE')  # FIX: Upstox uses 'oi'
                pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
                
                # Update market snapshot with actual PCR
                if symbol in self.market_snapshot:
                    self.market_snapshot[symbol]["pcr"] = pcr
                    self.market_snapshot[symbol]["atm"] = spot_price  # Update ATM with current spot
                
                total_oi = sum(item.get('oi', 0) for item in option_chain)  # FIX: Upstox uses 'oi'
                if symbol not in self.oi_history:
                    self.oi_history[symbol] = []
                
                self.oi_history[symbol].append(total_oi)
                if len(self.oi_history[symbol]) > self.max_history_length:
                    self.oi_history[symbol].pop(0)
                
                if len(self.oi_history[symbol]) >= 2:
                    delta_oi = self.oi_history[symbol][-1] - self.oi_history[symbol][0]
                else:
                    delta_oi = 0
                
                # Market Analyzer Service
                if not self.market_analyzer_service:
                    logger.warning(f"{symbol}: Market Analyzer Service not available, skipping")
                    continue
                
                market_analysis = self.market_analyzer_service.analyze_market(
                    symbol=symbol,
                    spot_price=spot_price,
                    vwap=vwap,
                    price_change=price_change,
                    delta_oi=delta_oi,
                    pcr=pcr,
                    option_chain={"strikes": [
                        {"strike": item.get('strike'), "oi": item.get('oi', 0)}  # FIX: Upstox uses 'oi'
                        for item in option_chain
                    ]}
                )
                
                # Breakout Entry Service
                if spot_price > vwap and price_change > 0:
                    breakout = "BULLISH"
                elif spot_price < vwap and price_change < 0:
                    breakout = "BEARISH"
                else:
                    breakout = "NONE"
                
                # DEBUG: Log breakout conditions
                logger.info(f"[DEBUG] {symbol} - Spot: {spot_price}, VWAP: {vwap}, Change: {price_change}, Breakout: {breakout}")
                
                if market_analysis['market_analysis']['market_strength'] >= 3:
                    strength = "STRONG"
                elif market_analysis['market_analysis']['market_strength'] >= 2:
                    strength = "MODERATE"
                else:
                    strength = "WEAK"
                
                # DEBUG: Log market strength
                logger.info(f"[DEBUG] {symbol} - Market Strength: {market_analysis['market_analysis']['market_strength']} ({strength})")
                
                if not self.breakout_entry_service:
                    logger.warning(f"{symbol}: Breakout Entry Service not available, using basic breakout")
                    breakout_entry = {
                        "entry_signal": breakout,
                        "entry_timing": "IMMEDIATE",
                        "confidence": strength
                    }
                else:
                    breakout_entry = self.breakout_entry_service.get_entry(
                    symbol=symbol,
                    breakout=breakout,
                    strength=strength,
                    spot=spot_price,
                    vwap=vwap
                )
                
                # Determine direction from institutional bias (not breakout)
                # Use trend_bias from institutional walls for direction
                trend_bias = institutional_data.get("trend_bias", "NEUTRAL")
                if trend_bias == "BULLISH":
                    direction = "CALL"
                elif trend_bias == "BEARISH":
                    direction = "PUT"
                else:
                    # Fallback to breakout if bias is neutral
                    direction = "CALL" if breakout == "BULLISH" else "PUT" if breakout == "BEARISH" else None
                
                # DEBUG: Log direction determination
                logger.info(f"[DEBUG] {symbol} - Trend Bias: {trend_bias}, Direction: {direction}, Breakout: {breakout}")
                
                if not direction:
                    logger.info(f"{symbol}: No clear breakout direction, skipping")
                    continue
                
                # Update market snapshot with signal
                if symbol in self.market_snapshot:
                    self.market_snapshot[symbol]["signal"] = direction
                
                # ========================================
                # SMART STRIKE SERVICE - Combined Selection + Optimization
                # ========================================
                logger.info(f"[SMART STRIKE] Calling smart strike service for {symbol}")
                
                if not self.smart_strike_service:
                    logger.warning(f"{symbol}: Smart Strike Service not available, using basic selection")
                    # Fallback to basic selection
                    strike_selection = {
                        "strike": f"{int(spot_price)} CE" if direction == "CALL" else f"{int(spot_price)} PE",
                        "expiry": "N/A",
                        "signal": direction,
                        "lot_size": 1,
                        "original_strike": f"{int(spot_price)} CE" if direction == "CALL" else f"{int(spot_price)} PE"
                    }
                else:
                    logger.info(f"[SMART STRIKE] Using combined selection + optimization for {symbol}")
                    
                    # DEBUG: Log option chain being passed to Smart Strike
                    logger.info(f"[DEBUG] Passing option chain to SmartStrike: {len(option_chain)} contracts")
                    
                    strike_selection = self.smart_strike_service.select_strike_complete(
                        instruments=[],  # Not needed for expiry selection (API already filtered)
                        symbol=symbol,
                        option_chain=option_chain,
                        spot=spot_price,
                        signal=direction,
                        optionstar_data=institutional_data,
                        confidence_score=execution_decision.get('score', 75)  # Use execution decision score
                    )
                
                if not strike_selection or "error" in strike_selection:
                    logger.warning(f"{symbol}: Smart strike service failed, skipping")
                    continue
                
                # Get optimized strike from single call
                elite_strike = strike_selection['strike']  # Already optimized
                # FIX: Don't expect lot_size from smart strike - get from config
                elite_lot = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                selected_expiry = strike_selection.get('expiry', None)
                selected_contract = strike_selection.get('selected_contract', None)
                
                logger.info(f"[SMART STRIKE] Optimized result: {elite_strike}, Lot: {elite_lot}, Shifted: {strike_selection.get('shifted', False)}")
                
                # Parse the optimized strike
                strike_price = int(elite_strike.split()[0])
                direction_formatted = "CE" if direction == "CALL" else "PE"
                
                # CRITICAL FIX: Use selected_contract directly if available, otherwise find matching contract
                if selected_contract:
                    instrument_token = selected_contract.get('instrument_token') or selected_contract.get('instrument_key')  # FIX: Fallback to instrument_key
                    tradingsymbol = selected_contract.get('tradingsymbol', '')
                    contract_expiry = selected_contract.get('expiry')
                    logger.info(f"Using selected contract: {tradingsymbol} (Token: {instrument_token}, Expiry: {contract_expiry})")
                else:
                    # Find matching contract for optimized strike
                    elite_matching_option = None
                    for opt in option_chain:
                        if (opt.get('strike') == strike_price and
                            opt.get('type') == direction_formatted and
                            opt.get('name') == symbol):
                            elite_matching_option = opt
                            break
                    
                    if elite_matching_option:
                        selected_contract = elite_matching_option
                        instrument_token = elite_matching_option.get('instrument_token') or elite_matching_option.get('instrument_key')  # FIX: Fallback to instrument_key
                        tradingsymbol = elite_matching_option.get('tradingsymbol', '')
                        contract_expiry = elite_matching_option.get('expiry')
                        logger.info(f"Found matching contract for optimized strike: {tradingsymbol}")
                    else:
                        logger.warning(f"No matching contract found for optimized strike {elite_strike}")
                        continue

                # CRITICAL FIX: Use selected_contract directly instead of searching again
                if selected_contract:
                    instrument_token = selected_contract.get('instrument_token') or selected_contract.get('instrument_key')  # FIX: Fallback to instrument_key
                    tradingsymbol = selected_contract.get('tradingsymbol', '')
                    contract_expiry = selected_contract.get('expiry')

                    # DEBUG: Log what we received from Smart Strike
                    logger.info(f"[DEBUG] selected_contract from Smart Strike: {selected_contract}")

                    # FIX: Initialize option_price to prevent reference errors
                    option_price = None

                    # FIX: Validate instrument_token before proceeding
                    if not instrument_token:
                        logger.warning(f"Selected contract missing instrument_token, searching in option_chain")
                        # Fallback: Find matching contract in option_chain
                        matching_contract = None
                        for opt in option_chain:
                            if (opt.get('strike') == strike_price and 
                                opt.get('type') == direction_formatted and
                                opt.get('expiry') == selected_expiry):
                                matching_contract = opt
                                break
                        
                        if matching_contract:
                            instrument_token = matching_contract.get('instrument_token') or matching_contract.get('instrument_key')  # FIX: Fallback to instrument_key
                            tradingsymbol = matching_contract.get('tradingsymbol', '')
                            logger.info(f"[DEBUG] Found matching contract in option_chain: {tradingsymbol} (Token: {instrument_token})")
                            logger.info(f"[DEBUG] Full matching contract data: {matching_contract}")
                        else:
                            logger.warning(f"No matching contract found in option_chain for {elite_strike}")
                            option_price = None
                    
                    if instrument_token:
                        logger.info(f"Using selected contract: {tradingsymbol} (Token: {instrument_token}, Expiry: {contract_expiry})")

                        # PRODUCTION FIX: Use WebSocket state_manager instead of REST API
                        # This eliminates rate limiting issues
                        logger.info(f"[PERF] Getting price from WebSocket state_manager for token: {instrument_token}")
                        
                        # Try WebSocket first (single source of truth)
                        try:
                            option_price = self.state_manager.get_option_price(instrument_token)
                        except AttributeError:
                            # FIX: StateManager doesn't have get_option_price, use last_price from contract
                            logger.warning(f"[PERF] StateManager doesn't have get_option_price, using last_price from contract")
                            option_price = selected_contract.get('last_price', 0)
                        
                        if option_price and option_price > 0:
                            logger.info(f"[PERF] Price available: {option_price}")
                            expiry = contract_expiry
                        else:
                            logger.warning(f"[PERF] Price not available, skipping this cycle")
                            option_price = None
                            # Skip this trade cycle instead of making REST API call
                else:
                    # Fallback to old method if selected_contract not available
                    logger.warning("Selected contract not available, using fallback method")
                    option_price, expiry = self.get_option_price(symbol, strike_price, direction, selected_expiry, option_chain)

                # CRITICAL FIX: Check if price is None before proceeding
                if option_price is None or option_price == 0:
                    logger.warning(f"{symbol}: Could not get valid option price for {elite_strike} (price: {option_price}), skipping")
                    continue
                
                # Build trade signal
                trade_signal = {
                    'strike': strike_price,
                    'expiry': expiry,
                    'direction': direction,
                    'pcr': pcr,
                    'pcr_bias': market_analysis['market_analysis']['pcr_bias'],
                    'buildup_pattern': market_analysis['market_analysis']['oi_analysis']['oi_signal'],
                    'strength': market_analysis['market_analysis']['market_strength'],
                    'vwap': vwap,
                    'entry': option_price,  # FIX: Use actual option_price instead of 0
                    'spot_price': spot_price,  # FIX: Add spot_price
                    'trade_mode': 'EXECUTE',
                    'execution_score': 85,  # High score for professional selection
                    'lot_size': self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                }
                
                # Execution Brain approval (timing and momentum filters)
                if not self.execution_brain_service:
                    logger.warning(f"{symbol}: Execution Brain Service not available, auto-approving")
                    execution_decision = {"action": "EXECUTE", "score": 85}
                else:
                    # FIX: Use evaluate_execution() instead of should_execute()
                    
                    # DEBUG: Log entry_price before sending to Execution Brain
                    logger.info(f"[DEBUG] Sending entry_price to ExecutionBrain: {option_price}")
                    
                    signal_package = {
                        "bias": market_analysis.get("bias", {}),
                        "breakout": market_analysis.get("breakout", {}),
                        "oi_signal": market_analysis.get("oi_signal", {}),
                        "levels": institutional_data,
                        "spot": trade_signal.get("spot_price", 0),
                        "vwap": trade_signal.get("vwap", 0),
                        "entry": trade_signal.get("entry", 0),
                        "price_history": self.state_manager.get_price_history(symbol),
                        "momentum_strength": "STRONG" if market_analysis.get('market_analysis', {}).get('market_strength', 0) >= 3 else "WEAK"
                    }
                    execution_decision = self.execution_brain_service.evaluate_execution(signal_package)
                
                # Allow EXECUTE, PROBING, and LLM_REVIEW (treat LLM_REVIEW as EXECUTE for single strike trader)
                if execution_decision['action'] not in ['EXECUTE', 'PROBING', 'LLM_REVIEW']:
                    logger.info(f"[PROP DESK] {symbol} rejected by Execution Brain: {execution_decision['action']}")
                    continue
                
                # Treat LLM_REVIEW as EXECUTE for single strike trader
                if execution_decision['action'] == 'LLM_REVIEW':
                    logger.info(f"[PROP DESK] {symbol} LLM_REVIEW - treating as EXECUTE for single strike trader")
                    execution_decision['action'] = 'EXECUTE'

                # NOTE: Momentum filter is now in Execution Brain Service - removed duplicate here

                # ========================================
                # CAPTURE TRADE METRICS - For performance analysis
                # ========================================
                confidence = institutional_data.get('confidence', {}).get('level', 'UNKNOWN')
                oi = institutional_data.get('support', {}).get('oi', 0) + institutional_data.get('resistance', {}).get('oi', 0)
                pcr_bias = market_analysis.get('market_analysis', {}).get('pcr_bias', 'NEUTRAL')

                self.current_trade_metrics = {
                    'confidence': confidence,
                    'oi': oi,
                    'momentum': momentum,  # Already calculated above
                    'pcr_bias': pcr_bias,
                    'spot': spot_price,
                    'vwap': vwap
                }

                # ========================================
                # TRADE FREQUENCY CONTROL - Max 1 active trade
                # ========================================
                if self.trade_active:
                    logger.info(f"[TRADE CONTROL] {symbol} SKIP: Already have active trade ({self.current_symbol} {self.current_strike})")
                    continue
                
                # ========================================
                # GET OPTION PRICE FOR OPTIMIZED STRIKE
                # ========================================
                # Get LTP from Kite using rate-limited fetch for optimized strike
                ltp_response = self.kite_client.safe_ltp_fetch([instrument_token])
                if ltp_response and instrument_token in ltp_response:
                    price = ltp_response[instrument_token]
                    # Handle both dict and float returns
                    if isinstance(price, dict):
                        option_price = price.get('last_price', 0)
                    else:
                        option_price = price
                    logger.info(f"Option price for {elite_strike}: ₹{option_price}")
                else:
                    logger.warning(f"Could not get LTP for {tradingsymbol}")
                    continue
                
                # Update trade signal with smart strike optimizations
                trade_signal['strike'] = strike_price
                trade_signal['expiry'] = selected_expiry
                trade_signal['lot_size'] = elite_lot
                trade_signal['elite_optimized'] = strike_selection.get('shifted', False)
                trade_signal['original_strike'] = strike_selection.get('original_strike', elite_strike)
                
                # Check affordability with optimized lot size
                lot_size = elite_lot
                cost_per_lot = option_price * lot_size
                can_afford = cost_per_lot <= self.current_capital
                
                if not can_afford:
                    logger.warning(f"[PROP DESK] {symbol} cannot afford trade - Cost: ₹{cost_per_lot}, Capital: ₹{self.current_capital}")
                    continue
                
                # Score calculation
                # SAFE CHECK: Ensure execution_decision is set before using it
                if execution_decision is None:
                    logger.warning(f"[PROP DESK] {symbol} Execution decision not set, using default score")
                    score = 50  # Default middle score
                else:
                    score = execution_decision['score']
                
                if score > best_score:
                    best_score = score
                    best_opportunity = {
                        'symbol': symbol,
                        'strike': strike_price,
                        'expiry': selected_expiry,
                        'direction': direction,
                        'spot': spot_price,
                        'option_price': option_price,
                        'cost_per_lot': cost_per_lot,
                        'lot_size': self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50),  # FIX: Add lot_size with fallback
                        'can_afford': can_afford,
                        'pcr': pcr,
                        'buildup_pattern': trade_signal['buildup_pattern'],
                        'strength': trade_signal['strength'],
                        'trade_signal': trade_signal,
                        'support': institutional_data.get('support', {}).get('strike', 0),
                        'resistance': institutional_data.get('resistance', {}).get('strike', 0),
                        'trend_bias': institutional_data.get('trend_bias', 'NEUTRAL'),
                        'vwap': vwap,
                        'price_change': price_change,
                        'delta_oi': delta_oi
                    }
                    
                    logger.info(f"[PROP DESK] New best opportunity: {symbol} {elite_strike} {direction} @ ₹{option_price} (Score: {score}/100, Lot: {elite_lot})")
                    
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
        
        if best_opportunity:
            logger.info(f"[PROP DESK] Best opportunity selected: {best_opportunity['symbol']} {best_opportunity['strike']} {best_opportunity['direction']} "
                       f"(Score: {best_score}, PCR: {best_opportunity['pcr']:.2f}, Buildup: {best_opportunity['buildup_pattern']}, "
                       f"Mode: {best_opportunity['trade_signal']['trade_mode']})")
        else:
            logger.warning("[PROP DESK] No suitable opportunity found")
        return best_opportunity

    def get_option_price(self, symbol, strike, direction, selected_expiry=None, option_chain=None):
        """
        Get current option price using option chain as source of truth.

        CRITICAL FIX: Build token map from option chain to ensure expiry/strike match.
        No more dependency on cached option_token_map.json file.

        Args:
            symbol: Underlying symbol
            strike: Strike price
            direction: CALL or PUT
            selected_expiry: Selected expiry date
            option_chain: Fresh option chain data (source of truth)

        Returns:
            (option_price, expiry) tuple
        """
        try:
            if not option_chain:
                logger.warning("No option chain provided for price lookup")
                return None, None

            # CRITICAL FIX: Build token map directly from option chain (single source of truth)
            option_token_map = {}
            for opt in option_chain:
                tradingsymbol = opt.get('tradingsymbol', '')
                if tradingsymbol:
                    option_token_map[tradingsymbol] = {
                        'instrument_token': opt.get('instrument_token'),
                        'expiry': opt.get('expiry'),
                        'strike': opt.get('strike'),
                        'type': opt.get('type')
                    }

            logger.info(f"Built token map from option chain: {len(option_token_map)} contracts")

            # CRITICAL FIX: Use tradingsymbol from option chain instead of manual construction
            # Find the matching option from option chain by strike and type
            direction_formatted = "CE" if direction == "CALL" else "PE"
            matching_option = None

            for opt in option_chain:
                if (opt.get('strike') == strike and 
                    opt.get('type') == direction_formatted and
                    opt.get('name') == symbol):
                    matching_option = opt
                    break

            if not matching_option:
                logger.warning(f"No matching option found in option chain for {symbol} {strike} {direction_formatted}")
                return None, None

            # Use actual tradingsymbol and instrument_token from option chain
            tradingsymbol = matching_option.get('tradingsymbol', '')
            instrument_token = matching_option.get('instrument_token') or matching_option.get('instrument_key')  # FIX: Fallback to instrument_key
            map_expiry = matching_option.get('expiry')

            logger.info(f"Using tradingsymbol from option chain: {tradingsymbol} (Token: {instrument_token})")

            # Validate expiry matches selected expiry
            if selected_expiry and selected_expiry != "N/A":
                if map_expiry != selected_expiry:
                    logger.warning(f"Expiry note: Chain has {map_expiry}, selected {selected_expiry}")
                else:
                    logger.info(f"Expiry MATCHED: {map_expiry} == {selected_expiry}")
            else:
                logger.info(f"Using expiry from option chain: {map_expiry}")

            # Get LTP from Kite using rate-limited fetch
            ltp_response = self.kite_client.safe_ltp_fetch([instrument_token])
            if ltp_response and instrument_token in ltp_response:
                price = ltp_response[instrument_token]
                # Handle both dict and float returns
                if isinstance(price, dict):
                    return price.get('last_price', 0), map_expiry
                return price, map_expiry
            else:
                logger.warning(f"Could not get LTP for {option_key}")
                return None, None

        except Exception as e:
            logger.error(f"Error getting option price: {e}")
            return None, None

    def execute_trade(self, symbol, strike, direction, option_price=None, trade_signal=None, option_chain=None):
        """Execute a trade on the selected strike using engine signal for target/stop-loss"""
        try:
            # UNIVERSAL RISK MANAGER CHECK (NEW - for all markets)
            if not can_execute_trade():
                logger.warning("UNIVERSAL RISK MANAGER BLOCKED TRADE - Trading stopped")
                return False

            # Extract expiry from trade_signal if available
            selected_expiry = trade_signal.get('expiry') if trade_signal else None

            # Get option price and expiry if not provided
            if not option_price:
                # CRITICAL FIX: Pass option_chain for single source of truth
                option_price, expiry = self.get_option_price(symbol, strike, direction, selected_expiry, option_chain)
                # CRITICAL FIX: Check for None price
                if option_price is None or option_price == 0:
                    logger.error(f"Could not get valid option price for {symbol} {strike} {direction} (price: {option_price})")
                    return False
            else:
                # If option_price is provided, still get expiry with validation using option_chain
                _, expiry = self.get_option_price(symbol, strike, direction, selected_expiry, option_chain)

            # Use engine signal for target/stop-loss if available
            lot_size = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 1)

            # FIXED: Calculate risk parameters FIRST (to get SL distance for precise position sizing)
            # Use temporary 1 lot for risk parameter calculation
            temp_risk_params = self.risk_service.calculate_risk_parameters(option_price, 1, direction, self.current_capital, symbol)

            if not temp_risk_params.get("success"):
                logger.error(f"Risk parameter calculation failed: {temp_risk_params.get('error')}")
                return False

            sl_distance = temp_risk_params["sl_distance"]

            # FIXED: Now calculate position size with PRECISE risk control using SL distance
            position_calc = self.risk_service.calculate_position_size(option_price, lot_size, self.current_capital, sl_distance)

            if not position_calc.get("success"):
                logger.error(f"Position sizing failed: {position_calc.get('error')}")
                return False

            actual_lots = position_calc["actual_lots"]
            lot_size_from_risk = position_calc.get("lot_size", lot_size)  # FIX: Get lot_size from risk calculation
            cost_per_lot = position_calc["cost_per_lot"]
            total_cost = position_calc["total_cost"]

            logger.info(f"Position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")
            logger.info(f"Lot size: {lot_size_from_risk}, Total quantity: {actual_lots * lot_size_from_risk}")
            logger.info(f"Risk precision: Actual ₹{position_calc.get('actual_risk', 0):.2f} vs Desired ₹{position_calc.get('desired_risk', 0):.2f} ({position_calc.get('risk_utilization', 0):.1f}%)")

            # Recalculate risk parameters with actual lots
            risk_params = self.risk_service.calculate_risk_parameters(option_price, actual_lots, direction, self.current_capital, symbol)

            if not risk_params.get("success"):
                logger.error(f"Risk parameter calculation failed: {risk_params.get('error')}")
                return False

            self.stoploss_price = risk_params["stoploss_price"]
            self.target_price = risk_params["target_price"]
            risk_amount = risk_params["risk_amount"]

            logger.info(f"Risk parameters: SL ₹{self.stoploss_price}, Target ₹{self.target_price}, Risk ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.1%})")

            # Set trade state
            self.current_symbol = symbol
            self.current_strike = strike
            self.current_direction = direction
            self.current_expiry = expiry
            self.entry_price = option_price
            self.actual_lots = actual_lots
            self.trade_active = True
            self.entry_time = time.time()  # Capture entry time for duration analysis

            # CRITICAL FIX: Add trade to Trade Manager for proper monitoring and time-based exit
            if self.trade_manager_service:
                trade_data = {
                    "signal": direction,
                    "entry": option_price,
                    "sl": self.stoploss_price,
                    "target": self.target_price,
                    "expiry": expiry,
                    "lot_size": actual_lots
                }
                self.trade_manager_service.add_trade(symbol, trade_data)
                logger.info(f"[TRADE MANAGER] Trade added to manager for monitoring")

            # CRITICAL FIX: Store option chain for monitoring (single source of truth)
            # We need to find which option_chain was used for this trade
            # This is passed from the calling context, so we'll store it when execute_trade is called

            logger.info("="*80)
            logger.info("TRADE EXECUTED")
            logger.info("="*80)
            
            if self.paper_trading:
                logger.info("MODE: PAPER TRADING (Real Market Data, No Real Order)")
            else:
                logger.info("MODE: LIVE (Real Trading - Real Order)")
            
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Strike: {strike}")
            logger.info(f"Expiry: {expiry}")
            logger.info(f"Direction: {direction}")
            logger.info(f"Entry: {option_price}")
            logger.info(f"Target: {self.target_price}")
            logger.info(f"Stop Loss: {self.stoploss_price}")
            logger.info(f"Lot Size: {lot_size}")
            logger.info(f"Current Capital: {self.current_capital:.2f}")
            logger.info(f"Risk Amount (2%): {risk_amount:.2f}")
            logger.info(f"Position Size: {actual_lots} lot(s)")
            logger.info(f"Max Risk per Trade: {risk_amount:.2f}")
            logger.info("="*80)

            return True

        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False

    def monitor_trade(self):
        """Monitor current trade until SL/TP hit"""
        if not self.trade_active:
            return False

        try:
            # Check daily loss limit using Risk Management Service
            daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)
            
            if daily_check.get("limit_reached"):
                logger.error(f"Daily loss limit reached during monitoring ({daily_check['daily_loss_percent']:.1%}). Closing trade immediately.")
                # CRITICAL FIX: Use stored option chain for single source of truth
                current_price, _ = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction, self.current_expiry, self.current_option_chain)
                if current_price:
                    pnl = current_price - self.entry_price if self.current_direction == "CALL" else self.entry_price - current_price
                    self.close_trade("DAILY LOSS LIMIT", current_price, pnl)
                return False

            # Get current option price (with stored expiry and option chain for validation)
            # CRITICAL FIX: Use stored option chain for single source of truth
            current_price, _ = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction, self.current_expiry, self.current_option_chain)
            if not current_price:
                logger.warning("Could not get current price, skipping this check")
                return True  # Continue monitoring

            # Calculate P&L
            # CRITICAL FIX: For BUYING options (both CALL and PUT), P&L is always (current - entry)
            # Whether CALL or PUT, if we're buying the option, we profit when premium increases
            pnl = current_price - self.entry_price
            pnl_percentage = (pnl / self.entry_price * 100) if self.entry_price > 0 else 0

            logger.info(f"[MONITOR] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Entry: {self.entry_price}, Current: {current_price}, P&L: {pnl:+.2f} ({pnl_percentage:+.2f}%)")
            
            # INTELLIGENT EXIT: Time + Weak Market = Exit (Pro-Level Logic)
            # Time alone should NOT close trade
            # Time + Weak Market = Exit
            # NSE ONLY - single_strike_trader.py is NSE-only bot
            if self.entry_time:
                trade_duration = (datetime.now() - self.entry_time).total_seconds() / 60  # in minutes
                
                if trade_duration > 45:  # 45-minute threshold
                    # Calculate momentum strength
                    momentum_strength = abs(pnl_percentage) / 100  # Convert percentage to decimal
                    
                    # Check if trade is NOT working
                    exit_reason = None
                    
                    # Condition 1: No momentum (price stuck near entry)
                    if momentum_strength < 0.003:  # Less than 0.3% move in 45 min
                        exit_reason = "Time + No Momentum (sideways)"
                    
                    # Condition 2: Negative momentum (trade going against)
                    elif pnl_percentage < -1.0:  # Losing more than 1%
                        exit_reason = "Time + Negative Momentum"
                    
                    # Condition 3: Weak positive momentum (not enough progress)
                    elif pnl_percentage > 0 and pnl_percentage < 0.5:  # Positive but weak (<0.5% in 45 min)
                        exit_reason = "Time + Weak Momentum"
                    
                    # Exit if trade is NOT working
                    if exit_reason:
                        logger.warning(f"[INTELLIGENT EXIT] {self.current_symbol} - {exit_reason} (duration: {trade_duration:.1f} min, P&L: {pnl_percentage:+.2f}%)")
                        self.close_trade(exit_reason, current_price, pnl)
                        return False
                    else:
                        # Trade IS working - let it run
                        logger.info(f"[INTELLIGENT EXIT] {self.current_symbol} - Trade working (momentum: {pnl_percentage:+.2f}%, duration: {trade_duration:.1f} min) - HOLDING")
            
            # Update Trade Manager with live price
            self.trade_manager_service.update_price(self.current_symbol, current_price)
            
            # External dashboard only (no console rendering to preserve logs)
            # Dashboard data is written to dashboard_data.json automatically
            # Run dashboard_viewer.py in separate terminal to see the dashboard

            # Use LLM for sentiment-based exit decision (every 5 cycles to avoid too many LLM calls)
            should_use_llm = random.randint(1, 5) == 1  # 20% chance

            if self.llm_analyzer_service and should_use_llm:
                try:
                    # Prepare trade context for LLM
                    trade_context = {
                        "symbol": self.current_symbol,
                        "direction": self.current_direction,
                        "strike": self.current_strike,
                        "expiry": self.current_expiry,
                        "entry": self.entry_price,
                        "current": current_price,
                        "pnl": pnl,
                        "pnl_percent": pnl_percentage,
                        "target": self.target_price,
                        "stoploss": self.stoploss_price,
                        "capital": self.current_capital
                    }

                    logger.info(f"Using LLM Analyzer Service for sentiment-based exit analysis...")
                    # Use LLM service for exit decision
                    llm_payload = {
                        "request_type": "EXIT_DECISION",
                        "timestamp": datetime.now().isoformat(),
                        "trade_context": trade_context,
                        "context": {
                            "decision_type": "EXIT",
                            "reason": "Sentiment-based exit analysis"
                        }
                    }
                    
                    llm_analysis = self.llm_analyzer_service.evaluate_consensus_trade(llm_payload)

                    if llm_analysis:
                        llm_signal = llm_analysis.get('decision', 'HOLD')
                        llm_confidence = llm_analysis.get('confidence', 0)
                        llm_reason = llm_analysis.get('reason', '')

                        logger.info(f"LLM Exit Analysis: {llm_signal} (Confidence: {llm_confidence}%) - {llm_reason}")

                        if llm_signal == 'SKIP' and llm_confidence > 70:
                            logger.info("LLM recommends exit - closing trade")
                            self.close_trade("LLM Sentiment Exit", current_price, pnl)
                            return False
                except Exception as e:
                    logger.error(f"LLM exit analysis error: {e}")
                    # Fall back to technical analysis

            # Check TP/SL
            if self.current_direction == "CALL":
                if current_price >= self.target_price:
                    logger.info(f"[TARGET HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Profit: {pnl:+.2f}")
                    self.close_trade("TARGET_HIT", current_price, pnl)
                    return False
                elif current_price <= self.stoploss_price:
                    logger.info(f"[STOP LOSS HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Loss: {pnl:+.2f}")
                    self.close_trade("SL_HIT", current_price, pnl)
                    return False
            else:  # PUT
                # CRITICAL FIX: For BUYING PUT options, we want premium to go UP (same as CALL)
                # Target hit when premium goes UP, SL hit when premium goes DOWN
                if current_price >= self.target_price:
                    logger.info(f"[TARGET HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Profit: {pnl:+.2f}")
                    self.close_trade("TARGET_HIT", current_price, pnl)
                    return False
                elif current_price <= self.stoploss_price:
                    logger.info(f"[STOP LOSS HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Loss: {pnl:+.2f}")
                    self.close_trade("SL_HIT", current_price, pnl)
                    return False

            return True  # Continue monitoring

        except Exception as e:
            logger.error(f"Error monitoring trade: {e}")
            return True  # Continue monitoring despite error

    def close_trade(self, exit_reason, exit_price, pnl):
        """Close current trade and update capital with proper money management"""
        # Use actual position size for P&L calculation
        total_pnl = pnl * self.actual_lots

        # UNIVERSAL RISK MANAGER UPDATE (NEW - for all markets)
        update_trade_result(total_pnl)
        logger.info(f"UNIVERSAL RISK MANAGER: Updated with P&L: {total_pnl}")

        # Update capital using Risk Management Service
        self.current_capital = self.risk_service.update_capital(total_pnl, self.current_capital)
        
        # Update daily P&L using Risk Management Service
        pnl_update = self.risk_service.update_daily_pnl(total_pnl)
        
        # Check capital protection using Risk Management Service
        capital_check = self.risk_service.check_capital_protection(self.current_capital, self.paper_trading)
        
        if capital_check.get("protection_triggered"):
            logger.error(f"Capital protection triggered: {capital_check['reason']}")
            if capital_check.get("action") == "stop_trading":
                self.trade_active = False  # Prevent further trades
        
        # Check daily loss limit using Risk Management Service
        daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)
        
        if daily_check.get("limit_reached"):
            logger.error(f"Daily loss limit reached: {daily_check['daily_loss_percent']:.1%}")
            self.trade_active = False  # Prevent further trades

        # Save to trade history with enhanced metrics
        pnl_pct = (pnl / self.entry_price * 100) if self.entry_price > 0 else 0

        # Calculate trade duration (in minutes)
        trade_duration_minutes = 0
        if self.entry_time:
            trade_duration_seconds = time.time() - self.entry_time
            trade_duration_minutes = trade_duration_seconds / 60

        trade_record = {
            'symbol': self.current_symbol,
            'strike': self.current_strike,
            'direction': self.current_direction,
            'expiry': self.current_expiry,
            'entry_price': self.entry_price,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl_per_lot': pnl,
            'pnl_pct': pnl_pct,
            'total_pnl': total_pnl,
            'lot_size': self.actual_lots,  # Actual position size
            'trade_duration_minutes': trade_duration_minutes,  # NEW: Time-based analysis
            'timestamp': datetime.now().isoformat(),
            'capital_before': self.current_capital - total_pnl,
            'capital_after': self.current_capital,
            # Enhanced metrics for analysis
            'entry_metrics': self.current_trade_metrics
        }
        self.trade_history.append(trade_record)

        logger.info("="*80)
        logger.info("TRADE CLOSED")
        logger.info("="*80)
        logger.info(f"Exit Reason: {exit_reason}")
        logger.info(f"Exit Price: {exit_price}")
        logger.info(f"Trade P&L (per lot): {pnl:+.2f}")
        logger.info(f"Total P&L ({self.actual_lots} lot(s)): {total_pnl:+.2f}")
        logger.info(f"Capital Before: {self.current_capital - total_pnl:+.2f}")
        logger.info(f"Capital After: {self.current_capital:+.2f}")
        logger.info(f"Capital Change: {total_pnl:+.2f} ({(total_pnl/self.start_capital*100):+.2f}%)")
        logger.info("="*80)

        # Reset trade state
        self.trade_active = False
        
        # CRITICAL FIX: Close trade in Trade Manager
        if self.trade_manager_service and self.current_symbol:
            closed_trade = self.trade_manager_service.get_closed_trade(self.current_symbol)
            if closed_trade:
                logger.info(f"[TRADE MANAGER] Trade closed via manager: {closed_trade.get('reason', 'UNKNOWN')}")
        
        self.current_strike = None
        self.current_symbol = None
        self.current_direction = None
        self.entry_price = None
        self.target_price = None
        self.stoploss_price = None
        self.current_expiry = None
        self.entry_time = None
        self.current_option_chain = None  # CRITICAL FIX: Clear stored option chain
        self.actual_lots = 1
    
    def execute_observation_trade(self, symbol, strike, direction, entry_price, tp_price, sl_price, lot_size, expiry, instrument_token, tradingsymbol):
        """
        Execute trade in observation mode - minimal execution path
        Skips all filters, forces execution, tracks TP/SL behavior
        """
        try:
            logger.info("=" * 80)
            logger.info(f"[OBSERVATION TRADE] EXECUTING: {symbol} {strike}")
            logger.info("=" * 80)
            
            # Set current trade state (for compatibility with other parts of system)
            self.current_symbol = symbol
            self.current_strike = strike
            self.current_direction = direction
            self.entry_price = entry_price
            self.target_price = tp_price
            self.stoploss_price = sl_price
            self.actual_lots = lot_size
            self.current_expiry = expiry
            self.entry_time = datetime.now()
            # Note: trade_active not used for monitoring control anymore - using local trade['status'] instead
            
            # Calculate risk parameters (FIXED for both CALL and PUT)
            price_diff = abs(entry_price - sl_price)
            risk_amount = price_diff * lot_size
            reward_diff = abs(tp_price - entry_price)
            reward_amount = reward_diff * lot_size
            risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            logger.info(f"[OBSERVATION TRADE] Entry: ₹{entry_price:.2f}")
            logger.info(f"[OBSERVATION TRADE] TP: ₹{tp_price:.2f} (Target: +{((tp_price - entry_price) / entry_price * 100):.1f}%)")
            logger.info(f"[OBSERVATION TRADE] SL: ₹{sl_price:.2f} (Risk: -{((entry_price - sl_price) / entry_price * 100):.1f}%)")
            logger.info(f"[OBSERVATION TRADE] Lot Size: {lot_size}")
            logger.info(f"[OBSERVATION TRADE] Risk: ₹{risk_amount:.2f} | Reward: ₹{reward_amount:.2f} | R:R: 1:{risk_reward_ratio:.1f}")
            logger.info(f"[OBSERVATION TRADE] Entry Time: {self.entry_time.strftime('%H:%M:%S')}")
            
            # Track trade for observation
            observation_trade = {
                "symbol": symbol,
                "strike": strike,
                "direction": direction,
                "entry_price": entry_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "lot_size": lot_size,
                "entry_time": self.entry_time.isoformat(),
                "instrument_token": instrument_token,
                "tradingsymbol": tradingsymbol,
                "expiry": expiry,
                "risk_amount": risk_amount,
                "reward_amount": reward_amount,
                "risk_reward_ratio": risk_reward_ratio,
                "status": "ACTIVE",
                "current_price": entry_price,
                "pnl": 0.0,
                "pnl_percentage": 0.0,
                "highest_price": entry_price,
                "lowest_price": entry_price,
                "tp_hit": False,
                "sl_hit": False,
                "exit_reason": None,
                "exit_price": None,
                "exit_time": None
            }
            
            # Add to active trades
            self.active_trades[symbol] = observation_trade
            
            # Start monitoring loop for this trade in background thread (CRITICAL FIX)
            # This allows bot to continue scanning for new trades instead of blocking
            monitoring_thread = threading.Thread(
                target=self.monitor_observation_trade,
                args=(observation_trade, instrument_token),
                daemon=True
            )
            monitoring_thread.start()
            logger.info("[OBSERVATION TRADE] Monitoring started in background thread")
            
        except Exception as e:
            logger.error(f"[OBSERVATION TRADE] Error executing trade: {e}")
            # trade_active not used for monitoring control anymore
    
    def monitor_observation_trade(self, trade, instrument_token):
        """
        Monitor observation trade - track TP/SL behavior in real-time
        Minimal monitoring to observe market mechanics
        """
        try:
            logger.info("[OBSERVATION TRADE] Starting monitoring...")
            
            monitoring_duration = 300  # Monitor for 5 minutes max
            check_interval = 5  # Check every 5 seconds
            elapsed = 0
            
            while elapsed < monitoring_duration and trade['status'] == "ACTIVE":
                # Use WebSocket price instead of API fetch (CRITICAL FIX - much faster)
                current_price = self.state_manager.get_ltp(instrument_token)
                
                if current_price and current_price > 0:
                        # Update trade
                        trade['current_price'] = current_price
                        
                        # Calculate P&L
                        pnl = (current_price - trade['entry_price']) * trade['lot_size']
                        pnl_percentage = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
                        trade['pnl'] = pnl
                        trade['pnl_percentage'] = pnl_percentage
                        
                        # Update highest/lowest
                        if current_price > trade['highest_price']:
                            trade['highest_price'] = current_price
                        if current_price < trade['lowest_price']:
                            trade['lowest_price'] = current_price
                        
                        # Check TP
                        if current_price >= trade['tp_price']:
                            trade['tp_hit'] = True
                            trade['status'] = 'TP_HIT'
                            trade['exit_reason'] = 'Target Hit'
                            trade['exit_price'] = current_price
                            trade['exit_time'] = datetime.now().isoformat()
                            logger.info("=" * 80)
                            logger.info(f"[OBSERVATION TRADE] TP HIT! 🎯")
                            logger.info(f"[OBSERVATION TRADE] Entry: ₹{trade['entry_price']:.2f} → Exit: ₹{current_price:.2f}")
                            logger.info(f"[OBSERVATION TRADE] P&L: ₹{pnl:.2f} ({pnl_percentage:.1f}%)")
                            logger.info(f"[OBSERVATION TRADE] Duration: {elapsed:.0f}s")
                            logger.info("=" * 80)
                            break
                        
                        # Check SL
                        if current_price <= trade['sl_price']:
                            trade['sl_hit'] = True
                            trade['status'] = 'SL_HIT'
                            trade['exit_reason'] = 'Stop Loss Hit'
                            trade['exit_price'] = current_price
                            trade['exit_time'] = datetime.now().isoformat()
                            logger.info("=" * 80)
                            logger.info(f"[OBSERVATION TRADE] SL HIT! 🛑")
                            logger.info(f"[OBSERVATION TRADE] Entry: ₹{trade['entry_price']:.2f} → Exit: ₹{current_price:.2f}")
                            logger.info(f"[OBSERVATION TRADE] P&L: ₹{pnl:.2f} ({pnl_percentage:.1f}%)")
                            logger.info(f"[OBSERVATION TRADE] Duration: {elapsed:.0f}s")
                            logger.info("=" * 80)
                            break
                        
                        # Log status every 30 seconds
                        if elapsed % 30 == 0 and elapsed > 0:
                            logger.info(f"[OBSERVATION TRADE] {elapsed}s elapsed | Price: ₹{current_price:.2f} | P&L: ₹{pnl:.2f} ({pnl_percentage:.1f}%) | TP: {trade['tp_price']:.2f} | SL: {trade['sl_price']:.2f}")
                
                # Wait for next check
                time.sleep(check_interval)
                elapsed += check_interval
            
            # If monitoring ended without TP/SL
            if trade['status'] == 'ACTIVE':
                trade['status'] = 'TIMEOUT'
                trade['exit_reason'] = 'Monitoring Timeout'
                trade['exit_price'] = trade['current_price']
                trade['exit_time'] = datetime.now().isoformat()
                logger.info(f"[OBSERVATION TRADE] Monitoring timeout after {elapsed}s")
                logger.info(f"[OBSERVATION TRADE] Final Price: ₹{trade['current_price']:.2f} | P&L: ₹{trade['pnl']:.2f}")
            
            # Save to observation history
            self.save_observation_result(trade)
            
        except Exception as e:
            logger.error(f"[OBSERVATION TRADE] Error monitoring: {e}")
            # Mark trade as failed
            trade['status'] = 'ERROR'
            trade['exit_reason'] = f"Monitoring Error: {str(e)}"
            trade['exit_time'] = datetime.now().isoformat()
            self.save_observation_result(trade)
    
    def save_observation_result(self, trade):
        """Save observation trade result to file for analysis"""
        try:
            import os
            observation_file = os.path.join(current_dir, 'observation_results.json')
            
            # Load existing results
            if os.path.exists(observation_file):
                with open(observation_file, 'r') as f:
                    results = json.load(f)
            else:
                results = []
            
            # Add new result
            results.append(trade)
            
            # Save back
            with open(observation_file, 'w') as f:
                json.dump(results, f, indent=4)
            
            logger.info(f"[OBSERVATION TRADE] Result saved to {observation_file}")
            
        except Exception as e:
            logger.error(f"[OBSERVATION TRADE] Error saving result: {e}")

    def run_trading_day(self):
        """Run single strike focus trading for the entire day"""
        logger.info("="*80)
        logger.info("SINGLE STRIKE FOCUS TRADER STARTED")
        logger.info("="*80)
        logger.info(f"Starting Capital: {self.start_capital}")
        logger.info(f"Market Hours: {self.market_open} - {self.market_close}")
        logger.info("All services will run continuously until market close")
        logger.info("="*80)
        
        # UNIVERSAL RISK MANAGER RESET (NEW - for all markets)
        reset_daily_limits()
        logger.info("UNIVERSAL RISK MANAGER: Daily limits reset")
        risk_status = get_risk_status()
        logger.info(f"UNIVERSAL RISK MANAGER: {risk_status}")
        logger.info("="*80)
        
        # Check WebSocket status
        if self.config.get("data_source") == "upstox":
            logger.info("Data Source: UPSTOX - Using Upstox API for market data (no WebSocket needed)")
        elif self.state_manager.is_websocket_connected():
            logger.info("Data Source: ZERODHA WEBSOCKET - Real-time data streaming active")
        else:
            logger.warning("Data Source: ZERODHA WEBSOCKET - DISCONNECTED (Trading Paused)")
        
        logger.info("="*80)
        
        trade_count = 0
        cycle_count = 0
        option_chain_cycle = 0  # Separate counter for option chain refresh

        while self.is_market_open():
            cycle_count += 1
            
            # PRODUCTION FIX: WebSocket hard guard - skip execution without WebSocket
            # EXCEPTION: Allow execution when using Upstox as data source
            if not self.config.get("data_source") == "upstox" and not self.state_manager.is_websocket_connected():
                logger.warning("[WS GUARD] WebSocket not connected - skipping trading cycle")
                logger.warning("[WS GUARD] Waiting for WebSocket connection before trading")
                time.sleep(10)  # Wait longer for WebSocket to connect
                continue
            
            # Update market snapshot every cycle (every 5 seconds)
            if cycle_count % 12 == 0:  # Every 60 seconds
                self.update_market_snapshot()
            
            # Log status every 60 cycles (approx every 5 minutes)
            if cycle_count % 60 == 0:
                current_time = datetime.now().time()
                if self.config.get("data_source") == "upstox":
                    data_status = "UPSTOX API (No Rate Limiting)"
                else:
                    data_status = "CONNECTED" if self.state_manager.is_websocket_connected() else "DISCONNECTED (Trading Paused)"
                logger.info(f"[MARKET STATUS] Current Time: {current_time} | Market Open: {self.is_market_open()} | Trade Active: {self.trade_active}")
                logger.info(f"[SERVICE STATUS] OptionStar: Monitoring | Market Analyzer: Active | Breakout Service: Active | Execution Brain: Active | LLM: Advisory | Trade Manager: Active | Watchdog: Monitoring")
                logger.info(f"[DATA STATUS] Data Source: {data_status} | Option Chain Refresh: Every 60 sec | REST Fallback: DISABLED")
                
                # Print clean dashboard periodically
                self.print_clean_dashboard()
            
            # Check if new trades can be opened using Risk Management Service
            trade_permission = self.risk_service.can_open_new_trade()
            
            if not trade_permission.get("can_trade"):
                logger.error(f"Trading blocked: {trade_permission['reason']}")
                time.sleep(60)  # Wait before checking again
                continue
            
            # If no active trade, select new strike
            if not self.trade_active:
                option_chain_cycle += 1
                
                # CRITICAL FIX: Reset cycle counter to prevent infinite growth
                max_cycle = 100  # Reset after 100 cycles to prevent overflow
                if option_chain_cycle >= max_cycle:
                    option_chain_cycle = 0
                    logger.info("[CYCLE FIX] Reset option chain cycle counter")
                
                # Set option chain refresh cycle based on data source
                if self.config.get("data_source") == "upstox":
                    refresh_cycle = 3  # Upstox: 9 seconds (3 cycles) due to rate limiting
                else:
                    refresh_cycle = 10  # Zerodha: 30 seconds (10 cycles) - no rate limiting needed
                
                if option_chain_cycle % refresh_cycle == 0:
                    logger.info("[FIX] Calling select_best_strike() - option chain refresh cycle")
                    
                    # PRODUCTION FIX: Fail-safe wrapper for symbol processing
                    try:
                        opportunity = self.select_best_strike()
                    except Exception as e:
                        logger.error(f"[FAIL-SAFE] Symbol processing failed: {e}")
                        logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                        time.sleep(15)  # Wait before retry
                        continue
                else:
                    # Set option chain refresh cycle based on data source
                    if self.config.get("data_source") == "upstox":
                        refresh_cycle = 3  # Upstox: 9 seconds (3 cycles) due to rate limiting
                    else:
                        refresh_cycle = 10  # Zerodha: 30 seconds (10 cycles) - no rate limiting needed
                    
                    logger.info(f"[FIX] Waiting for option chain refresh (cycle {option_chain_cycle}/{refresh_cycle})")
                    time.sleep(3)  # PRODUCTION FIX: Reduced from 15 to 3 seconds for responsive trading
                    continue

                if opportunity:
                    # PRODUCTION FIX: Fail-safe wrapper for opportunity processing
                    try:
                        # ========================================
                        # OBSERVATION MODE: MINIMAL EXECUTION PATH
                        # ========================================
                        if self.observation_mode:
                            logger.info("=" * 80)
                            logger.info("[OBSERVATION MODE] MINIMAL EXECUTION PATH ACTIVATED")
                            logger.info("=" * 80)
                        
                        # Extract basic trade data from opportunity
                        direction = opportunity['direction']
                        option_price = opportunity['option_price']
                        expiry = opportunity.get('expiry', 'N/A')
                        symbol = opportunity['symbol']
                        spot = opportunity['spot']
                        
                        # Use Smart Strike Service for selection (keep this)
                        logger.info(f"[OBSERVATION MODE] Selecting strike for {symbol}...")
                        
                        # Get option chain for smart strike service
                        option_chain = self.get_option_chain_for_optionstar(symbol)
                        if not option_chain:
                            logger.warning(f"[OBSERVATION MODE] No option chain for {symbol}")
                            time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                            continue
                        
                        # Get institutional data
                        institutional_data = calculate_institutional_walls(
                            {"calls": [], "puts": []}, spot, symbol
                        )  # Simplified for observation mode
                        
                        # Use Smart Strike Service
                        if self.smart_strike_service:
                            # DEBUG: Log option chain being passed to Smart Strike
                            logger.info(f"[DEBUG] Passing option chain to SmartStrike: {len(option_chain)} contracts")
                            
                            strike_selection = self.smart_strike_service.select_strike_complete(
                                instruments=[],
                                symbol=symbol,
                                option_chain=option_chain,
                                spot=spot,
                                signal=direction,
                                optionstar_data=institutional_data,
                                confidence_score=75  # Fixed medium confidence for observation
                            )
                            
                            if strike_selection and "error" not in strike_selection:
                                elite_strike = strike_selection['strike']
                                # FIX: Don't expect lot_size from smart strike - get from config
                                elite_lot = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                                selected_contract = strike_selection.get('selected_contract', None)
                                
                                logger.info(f"[OBSERVATION MODE] Selected: {elite_strike}, Lot: {elite_lot}")
                                
                                # Get option price using WebSocket (FIXED - faster)
                                if selected_contract:
                                    instrument_token = selected_contract.get('instrument_token') or selected_contract.get('instrument_key')  # FIX: Fallback to instrument_key
                                    final_option_price = self.state_manager.get_ltp(instrument_token)
                                    
                                    if final_option_price is None or final_option_price == 0:
                                        logger.warning(f"[WS ONLY] Could not get LTP from WebSocket - skipping trade (no REST fallback)")
                                        # PRODUCTION FIX: Skip REST fallback to avoid rate limiting
                                        continue
                                else:
                                    logger.warning(f"[OBSERVATION MODE] No selected contract")
                                    continue
                                
                                # ========================================
                                # FORCE EXECUTION - SKIP ALL FILTERS
                                # ========================================
                                logger.info("[OBSERVATION MODE] SKIPPING ALL FILTERS - FORCING EXECUTION")
                                
                                # Calculate simple TP/SL (FIXED - more realistic levels)
                                tp_price = final_option_price * 1.10  # 10% target (more realistic)
                                sl_price = final_option_price * 0.95  # 5% stop loss (more realistic)
                                
                                logger.info(f"[OBSERVATION MODE] Trade: {elite_strike}")
                                logger.info(f"[OBSERVATION MODE] Entry: ₹{final_option_price:.2f}")
                                logger.info(f"[OBSERVATION MODE] TP: ₹{tp_price:.2f} (+10%)")
                                logger.info(f"[OBSERVATION MODE] SL: ₹{sl_price:.2f} (-5%)")
                                logger.info(f"[OBSERVATION MODE] Lot: {elite_lot}")
                                logger.info("=" * 80)
                                
                                # Execute trade directly
                                self.execute_observation_trade(
                                    symbol=symbol,
                                    strike=elite_strike,
                                    direction=direction,
                                    entry_price=final_option_price,
                                    tp_price=tp_price,
                                    sl_price=sl_price,
                                    lot_size=elite_lot,
                                    expiry=expiry,
                                    instrument_token=instrument_token,
                                    tradingsymbol=selected_contract.get('tradingsymbol', '')
                                )
                                
                                # Continue immediately (FIXED - removed blocking sleep)
                                # Bot continues scanning for new opportunities
                                continue
                            else:
                                logger.warning("[OBSERVATION MODE] Smart strike failed")
                                continue
                        else:
                            logger.warning("[OBSERVATION MODE] Smart strike service not available")
                            continue
                    
                    except Exception as e:
                        logger.error(f"[FAIL-SAFE] Observation mode failed: {e}")
                        logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                        import traceback
                        logger.error(f"[FAIL-SAFE] Traceback: {traceback.format_exc()}")
                        time.sleep(15)
                        continue
                    
                    # ========================================
                    # NORMAL MODE: Full Intelligence Pipeline
                    # ========================================
                    
                    try:
                        # Update market snapshot before trade selection
                        self.update_market_snapshot()
                        
                        # Use direction, option_price, expiry, and trade_signal from Engine1
                        direction = opportunity['direction']
                        option_price = opportunity['option_price']
                        expiry = opportunity.get('expiry', 'N/A')
                        trade_signal = opportunity['trade_signal']
                        
                        # NSE-only decision logic
                        trade_taken = True  # Default to execute if we have a signal
                        skip_reason = None
                        
                        # Simple confidence check based on trade signal strength
                        if trade_signal and trade_signal.get('strength', 0) < 2:
                            skip_reason = f"Weak signal strength {trade_signal.get('strength', 0)} (requires 2+)"
                            trade_taken = False
                        
                        # MCX Sentiment Filter Layer (optional multi-market confirmation)
                        mcx_confirmation = None
                        if trade_taken and self.mcx_sentiment_service and self.mcx_sentiment_service.is_enabled():
                            try:
                                mcx_confirmation = self.mcx_sentiment_service.get_sentiment_for_nse_confirmation(direction)
                                
                                if mcx_confirmation['recommendation'] == 'REJECT':
                                    skip_reason = f"MCX sentiment conflict: {mcx_confirmation['reasoning']}"
                                    trade_taken = False
                                    logger.warning(f"[MCX FILTER] {skip_reason}")
                                elif mcx_confirmation['recommendation'] == 'CONFIRM':
                                    logger.info(f"[MCX FILTER] MCX sentiment confirms trade: {mcx_confirmation['reasoning']}")
                                else:
                                    logger.info(f"[MCX FILTER] MCX sentiment neutral: {mcx_confirmation['reasoning']}")
                            except Exception as e:
                                logger.error(f"[MCX FILTER] Error getting MCX sentiment: {e}")
                                # Continue without MCX filter if error occurs
                        
                        if not trade_taken:
                            logger.warning(f"SKIPPING TRADE - {skip_reason}")
                            time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                            continue
                        
                        # Print clean dashboard
                        self.print_clean_dashboard()
                        
                        logger.info(f"Selected: {opportunity['symbol']} {opportunity['strike']} {direction} @ ₹{option_price} (Expiry: {expiry}, PCR: {opportunity['pcr']:.2f}, Buildup: {opportunity['buildup_pattern']}, Strength: {opportunity['strength']})")
                        
                        # Log MCX filter decision
                        if mcx_confirmation:
                            logger.info(f"[MCX FILTER] Decision: {mcx_confirmation['recommendation']} | Reason: {mcx_confirmation['reasoning']}")

                        # CRITICAL FIX: Store option chain before execution for monitoring
                        self.current_option_chain = option_chain

                        if self.execute_trade(opportunity['symbol'], opportunity['strike'], direction, option_price, trade_signal, option_chain):
                            trade_count += 1
                        else:
                            logger.error("Failed to execute trade, will retry in 5 seconds")
                            time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                            continue
                    
                    except Exception as e:
                        logger.error(f"[FAIL-SAFE] Normal mode processing failed: {e}")
                        logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                        import traceback
                        logger.error(f"[FAIL-SAFE] Traceback: {traceback.format_exc()}")
                        time.sleep(15)
                        continue
                else:
                    logger.warning("No suitable opportunity found, waiting 5 seconds")
                    time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                    continue

            # Monitor active trade
            if self.trade_active:
                try:
                    should_continue = self.monitor_trade()
                    if not should_continue:
                        # Trade closed, wait before selecting new strike
                        logger.info("Trade closed, waiting 5 seconds before selecting new strike...")
                        time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                    else:
                        # Continue monitoring, check every 5 seconds
                        time.sleep(15)  # PRODUCTION FIX: Increased from 5 to 15 seconds to avoid rate limiting
                except Exception as e:
                    logger.error(f"[FAIL-SAFE] Trade monitoring failed: {e}")
                    logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                    import traceback
                    logger.error(f"[FAIL-SAFE] Traceback: {traceback.format_exc()}")
                    time.sleep(15)  # Wait before retry
                    continue

        # Market closed - save trade history
        self.save_trade_history()
        
        # Stop watchdog monitoring
        if self.watchdog_service:
            try:
                self.watchdog_service.stop_monitoring()
                logger.info("Watchdog monitoring stopped")
            except Exception as e:
                logger.error(f"Error stopping watchdog: {e}")

        # Market closed
        logger.info("="*80)
        logger.info("MARKET CLOSED - TRADING DAY ENDED")
        logger.info("="*80)
        logger.info(f"Total Trades: {trade_count}")
        logger.info(f"Starting Capital: {self.start_capital}")
        logger.info(f"Ending Capital: {self.current_capital}")
        logger.info(f"Day P&L: {self.current_capital - self.start_capital:+.2f}")
        logger.info("="*80)

    def calculate_performance_metrics(self):
        """Calculate key performance metrics from trade history"""
        if not self.trade_history:
            return {}

        try:
            wins = [t for t in self.trade_history if t['total_pnl'] > 0]
            losses = [t for t in self.trade_history if t['total_pnl'] <= 0]

            total_trades = len(self.trade_history)
            win_count = len(wins)
            loss_count = len(losses)

            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

            avg_win = sum(t['total_pnl'] for t in wins) / win_count if win_count > 0 else 0
            avg_loss = sum(t['total_pnl'] for t in losses) / loss_count if loss_count > 0 else 0

            # Expectancy: (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            win_rate_decimal = win_rate / 100 if win_count > 0 else 0
            expectancy = (win_rate_decimal * avg_win) - ((1 - win_rate_decimal) * abs(avg_loss))

            # Analyze by confidence level
            confidence_performance = {}
            for confidence in ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']:
                conf_trades = [t for t in self.trade_history if t.get('entry_metrics', {}).get('confidence') == confidence]
                if conf_trades:
                    conf_wins = [t for t in conf_trades if t['total_pnl'] > 0]
                    conf_win_rate = len(conf_wins) / len(conf_trades) * 100
                    conf_pnl = sum(t['total_pnl'] for t in conf_trades)
                    confidence_performance[confidence] = {
                        'trades': len(conf_trades),
                        'win_rate': conf_win_rate,
                        'total_pnl': conf_pnl
                    }

            # Analyze by exit reason
            exit_reason_performance = {}
            for reason in ['TP_HIT', 'SL_HIT', 'TIME_EXIT', 'MANUAL']:
                reason_trades = [t for t in self.trade_history if t['exit_reason'] == reason]
                if reason_trades:
                    reason_pnl = sum(t['total_pnl'] for t in reason_trades)
                    reason_duration = sum(t.get('trade_duration_minutes', 0) for t in reason_trades) / len(reason_trades)
                    exit_reason_performance[reason] = {
                        'trades': len(reason_trades),
                        'total_pnl': reason_pnl,
                        'avg_duration_minutes': reason_duration
                    }

            # Time-based analysis (winning vs losing trade duration)
            winning_durations = [t.get('trade_duration_minutes', 0) for t in wins if t.get('trade_duration_minutes')]
            losing_durations = [t.get('trade_duration_minutes', 0) for t in losses if t.get('trade_duration_minutes')]

            avg_win_duration = sum(winning_durations) / len(winning_durations) if winning_durations else 0
            avg_loss_duration = sum(losing_durations) / len(losing_durations) if losing_durations else 0

            return {
                'total_trades': total_trades,
                'wins': win_count,
                'losses': loss_count,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'expectancy': expectancy,
                'total_pnl': self.current_capital - self.start_capital,
                'confidence_performance': confidence_performance,
                'exit_reason_performance': exit_reason_performance,
                'time_analysis': {
                    'avg_win_duration_minutes': avg_win_duration,
                    'avg_loss_duration_minutes': avg_loss_duration,
                    'duration_ratio': avg_win_duration / avg_loss_duration if avg_loss_duration > 0 else 0
                }
            }
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {}

    def save_trade_history(self):
        """Save trade history to file for EOD analysis"""
        try:
            metrics = self.calculate_performance_metrics()

            with open('single_strike_trade_history.json', 'w') as f:
                json.dump({
                    'trading_session': {
                        'start_capital': self.start_capital,
                        'end_capital': self.current_capital,
                        'total_pnl': self.current_capital - self.start_capital,
                        'total_trades': len(self.trade_history),
                        'date': datetime.now().strftime('%Y-%m-%d')
                    },
                    'performance_metrics': metrics,
                    'trades': self.trade_history
                }, f, indent=2)
            logger.info("Trade history saved to single_strike_trade_history.json")

            # Log performance summary
            if metrics:
                logger.info("="*80)
                logger.info("PERFORMANCE METRICS")
                logger.info("="*80)
                logger.info(f"Total Trades: {metrics['total_trades']}")
                logger.info(f"Win Rate: {metrics['win_rate']:.1f}%")
                logger.info(f"Average Win: ₹{metrics['avg_win']:.2f}")
                logger.info(f"Average Loss: ₹{metrics['avg_loss']:.2f}")
                logger.info(f"Expectancy: ₹{metrics['expectancy']:.2f}")
                logger.info(f"Total P&L: ₹{metrics['total_pnl']:.2f}")
                logger.info("="*80)
        except Exception as e:
            logger.error(f"Error saving trade history: {e}")

    def show_current_performance(self):
        """Show current performance metrics on demand"""
        metrics = self.calculate_performance_metrics()
        if metrics:
            logger.info("="*80)
            logger.info("CURRENT PERFORMANCE SNAPSHOT")
            logger.info("="*80)
            logger.info(f"Total Trades: {metrics['total_trades']}")
            logger.info(f"Win Rate: {metrics['win_rate']:.1f}% ({metrics['wins']}W/{metrics['losses']}L)")
            logger.info(f"Average Win: ₹{metrics['avg_win']:.2f}")
            logger.info(f"Average Loss: ₹{metrics['avg_loss']:.2f}")
            logger.info(f"Expectancy: ₹{metrics['expectancy']:.2f} per trade")
            logger.info(f"Total P&L: ₹{metrics['total_pnl']:.2f}")

            if metrics.get('confidence_performance'):
                logger.info("\nBy Confidence Level:")
                for conf, data in metrics['confidence_performance'].items():
                    logger.info(f"  {conf}: {data['trades']} trades, {data['win_rate']:.1f}% win rate, ₹{data['total_pnl']:.2f} P&L")

            if metrics.get('exit_reason_performance'):
                logger.info("\nBy Exit Reason:")
                for reason, data in metrics['exit_reason_performance'].items():
                    logger.info(f"  {reason}: {data['trades']} trades, ₹{data['total_pnl']:.2f} P&L, {data['avg_duration_minutes']:.1f} min avg")

            if metrics.get('time_analysis'):
                time_data = metrics['time_analysis']
                logger.info("\nTime Analysis:")
                logger.info(f"  Avg Win Duration: {time_data['avg_win_duration_minutes']:.1f} min")
                logger.info(f"  Avg Loss Duration: {time_data['avg_loss_duration_minutes']:.1f} min")
                logger.info(f"  Duration Ratio (Win/Loss): {time_data['duration_ratio']:.2f}x")

            logger.info("="*80)
        else:
            logger.info("No trades yet - performance metrics unavailable")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Single Strike Focus Trader')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')

    parser.add_argument('--paper-trading', action='store_true',
                       help='Paper trading with REAL market data but NO real orders (recommended for testing)')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    parser.add_argument('--symbols', type=str, default=None,
                       help='Comma-separated list of symbols to trade (optional, default: all instruments from config)')
    parser.add_argument('--enable-mcx-filter', action='store_true',
                       help='Enable MCX sentiment filter for NSE trade confirmation')
    parser.add_argument('--disable-mcx-filter', action='store_true',
                       help='Disable MCX sentiment filter')
    parser.add_argument('--disable-watchdog', action='store_true',
                       help='Disable watchdog monitoring (enabled by default)')
    args = parser.parse_args()

    # Determine mode based on arguments
    paper_trading = None
    
    if args.paper_trading:
        paper_trading = True
    elif args.live:
        paper_trading = False

    # Parse symbols (only if provided)
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]
    
    # Initialize trader with investment amount and optional symbols
    trader = SingleStrikeTrader(investment_amount=args.investment, paper_trading=paper_trading, symbols=symbols)
    
    # Handle MCX filter enable/disable
    if args.enable_mcx_filter and trader.mcx_sentiment_service:
        trader.mcx_sentiment_service.enable()
        logger.info("MCX sentiment filter enabled via command line")
    elif args.disable_mcx_filter and trader.mcx_sentiment_service:
        trader.mcx_sentiment_service.disable()
        logger.info("MCX sentiment filter disabled via command line")
    
    # Handle watchdog disable (enabled by default)
    if args.disable_watchdog and trader.watchdog_service:
        trader.watchdog_service.stop_monitoring()
        logger.info("Watchdog monitoring disabled via command line")
    
    trader.run_trading_day()
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
import threading

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

# CRITICAL FIX: Logs to file (DEBUG) + console (INFO+)

# Disable default logging handler (prevents encoding errors)
logging.getLogger().handlers.clear()
logging.lastResort = None  # Disable lastResort handler
logging.raiseExceptions = False  # Don't raise exceptions for logging errors

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# File handler - ALL logs (DEBUG+) go to file with UTF-8 encoding
file_handler = logging.FileHandler("trading.log", encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

# Console handler - INFO+ logs to console (important events only)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

# Force immediate flush for both handlers
class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

# Replace handlers with flushing versions
file_handler = FlushFileHandler("trading.log", encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = FlushStreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

# Add both handlers
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Get module logger (inherits from root)
logger = logging.getLogger(__name__)
logger.propagate = True  # Ensure propagation to root logger

# CRITICAL: Configure external modules to prevent them from adding extra handlers
for module_name in ['data_layer', 'kiteconnect', 'twisted', 'autobahn']:
    module_logger = logging.getLogger(module_name)
    module_logger.handlers.clear()
    module_logger.propagate = True  # Propagate to root logger

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

# CRITICAL FIX: Silent logging already setup above - no basicConfig needed

class SingleStrikeTrader:
    # REMOVED: Symbol blacklist - using timeout instead
    
    # Thread management settings
    MAX_ACTIVE_THREADS = 10  # Maximum concurrent threads for institutional walls
    THREAD_COUNT_WARNING_THRESHOLD = 8  # Warning threshold for active threads
    
    # Execution ID tracking to prevent stale thread results
    _current_execution_id = 0  # Class-level execution counter
    
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
        
        # Execution ID for this instance (prevents stale thread results from affecting decisions)
        self._execution_id = 0
        
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

        # CRITICAL FIX: Parallel queue collection flag
        self.parallel_queue_active = False  # Track if parallel queue collection is running
        
        # PRODUCTION FIX: Option chain caching (symbol-specific to prevent data cross-contamination)
        self.cached_option_chains = {}  # symbol -> option_chain
        self.cached_option_chain_times = {}  # symbol -> timestamp
        
        # CRITICAL FIX: REST fallback rate limiting to prevent continuous use
        self.rest_fallback_count = 0  # Track total REST fallback calls
        self.rest_fallback_start_time = None  # Track when REST fallback started
        self.max_continuous_rest_fallback = 10  # Max continuous REST calls before forcing WebSocket wait
        self.rest_fallback_cooldown = 30  # Seconds to wait after max REST calls reached
        
        # CRITICAL FIX: Option price cache to avoid repeated API calls
        self.option_price_cache = {}  # instrument_token -> (price, timestamp)
        self.option_price_cache_duration = 5.0  # Cache option prices for 5 seconds
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
        logger.info(f"Capital initialized: Rs.{self.start_capital}")
        
        # Market hours (NSE-only - NSE hours: 09:15-15:30)
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        logger.info(f"Market hours (NSE): {self.market_open} - {self.market_close}")
        
        # Current trade state (initialize early - needed by run_trading_day)
        self.current_strike = None
        self.current_symbol = None
        self.current_direction = None
        self.current_tradingsymbol = None  # CRITICAL FIX: Store tradingsymbol for reliable price lookup
        self.entry_price = None
        self.target_price = None
        self.stoploss_price = None
        self.actual_lots = 1  # Position size
        self.current_expiry = None  # Current option expiry
        self.entry_time = None  # Track entry time for duration analysis
        self.current_instrument_token = None  # Instrument token for StateManager UI updates

        # Trade history
        self.trade_history = []

        # Trade metrics for analysis (captured at entry)
        self.current_trade_metrics = {}

        # CRITICAL FIX: Initialize llm_analyzer_service to prevent monitor crash
        self.llm_analyzer_service = None

        # EXECUTION QUEUE: Dynamic unique queue for trade opportunities
        self.trade_queue = {}  # trade_id -> opportunity (dict-based, no duplicates)
        self.queue_max_size = 5  # Keep only top 5 trades
        self.queue_stale_seconds = 60  # Remove trades older than 60 seconds
        self.executed_trades = set()  # Track executed trade IDs to prevent duplicates
        
        # Tick confirmation rejection tracking (prevent repeated symbol selection)
        self.tick_rejected_symbols = {}  # symbol -> {'last_rejected': timestamp, 'retry_count': int, 'last_price': float}
        self.tick_rejection_cooldown = 60  # Cooldown period in seconds (increased for execution failures)
        self.max_retry_attempts = 2  # Max retry attempts before permanent skip

        # CRITICAL FIX: Thread-safe shared data structures for parallel queue collection
        self.parallel_queue_results = []  # Shared list for collected opportunities
        self.parallel_queue_lock = threading.Lock()  # Lock for thread-safe access (initialized once)
        self.parallel_queue_active = False  # Flag to indicate parallel thread is running
        self.parallel_thread = None  # Thread reference for lifecycle management

        # Store option chain for monitoring (single source of truth)
        self.current_option_chain = None
        
        # PRODUCTION FIX: Cache option chain to avoid redundant API calls (data-source aware)
        self.cached_option_chains = {}  # symbol -> option_chain
        self.cached_option_chain_times = {}  # symbol -> timestamp
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
            kite_client=self.kite_client,
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            state=self.state_manager,
            token_manager=self.ws_client.token_manager  # CRITICAL: Use ws_client's token manager for instrument access
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
        
        # CRITICAL FIX: DO NOT start OptionStar monitoring here - will start after data readiness
        # OptionStar monitoring will be started in run_trading_day() after WebSocket data is available
        logger.info("[STARTUP DELAY] OptionStar monitoring deferred until data readiness confirmed")

        
        # Initialize historical data for all configured instruments (best effort)
        logger.info("Initializing historical data for Engine 1...")
        all_instruments = self.symbols if self.symbols else self.config.get('instruments', {}).keys()
        for symbol in all_instruments:
            try:
                self.engine1.initialize_historical_data(symbol)
            except Exception as e:
                logger.debug(f"Could not initialize historical data for {symbol}: {e} (will use live data)")
        logger.info("Historical data initialization complete (some instruments may use live data only)")
        
        logger.info(f"Single Strike Trader initialized with Rs.{investment_amount} investment")
        
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
        
        # CRITICAL FIX: Ensure self.symbols is always set to monitor_symbols
        self.symbols = monitor_symbols

        
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
            else:
                logger.warning("No Spot WebSocket tokens loaded - falling back to REST API")
        
        # ========================================
        # OPTIONS WEBSOCKET (NFO) - For OI/Volume
        # CRITICAL FIX: Re-enabled for real trading behavior
        # ========================================
        logger.info("="*80)
        logger.info("INITIALIZING OPTIONS WEBSOCKET FOR REAL-TIME DATA")
        logger.info("="*80)
        logger.debug(f"[DEBUG] Options WebSocket client exists: {hasattr(self, 'options_ws_client')}")
        logger.debug(f"[DEBUG] Options WebSocket client type: {type(self.options_ws_client) if hasattr(self, 'options_ws_client') else 'N/A'}")
        logger.debug(f"[DEBUG] WS Client token manager exists: {hasattr(self.ws_client, 'token_manager')}")
        logger.debug(f"[DEBUG] Token manager type: {type(self.ws_client.token_manager) if hasattr(self.ws_client, 'token_manager') else 'N/A'}")
        
        # CRITICAL FIX: Wait for Spot WebSocket to stabilize before starting Options WebSocket
        # This prevents rate limiting issues
        logger.info("[PERF] Waiting 10 seconds before Options WebSocket to avoid rate limiting...")
        time.sleep(10)
        
        # Load option tokens for all symbols
        all_option_tokens = []
        try:
            logger.debug(f"[DEBUG] Starting token loading for {len(monitor_symbols)} symbols: {monitor_symbols}")
            # Use Options WebSocket to load option tokens
            for symbol in monitor_symbols:
                try:
                    # Get option tokens for this symbol using Options WebSocket
                    logger.info(f"[OPTIONS WS] Loading tokens for {symbol}...")
                    logger.debug(f"[DEBUG] Calling load_option_tokens with token_manager: {self.ws_client.token_manager}")
                    option_tokens = self.options_ws_client.load_option_tokens(symbol, token_manager=self.ws_client.token_manager)
                    logger.debug(f"[DEBUG] load_option_tokens returned: {type(option_tokens)}, length: {len(option_tokens) if option_tokens else 0}")
                    all_option_tokens.extend(option_tokens)
                    logger.info(f"[OPTIONS WS] Loaded {len(option_tokens)} option tokens for {symbol}")
                    logger.debug(f"[DEBUG] Total tokens so far: {len(all_option_tokens)}")
                except Exception as e:
                    logger.error(f"[OPTIONS WS] FAILED to load option tokens for {symbol}: {e}")
                    import traceback
                    logger.error(f"[OPTIONS WS] Traceback: {traceback.format_exc()}")
            
            logger.info(f"[OPTIONS WS] Total option tokens loaded: {len(all_option_tokens)}")
            logger.debug(f"[DEBUG] Token list sample: {all_option_tokens[:5] if all_option_tokens else 'EMPTY'}")
        except Exception as e:
            logger.error(f"[OPTIONS WS] CRITICAL ERROR loading option tokens: {e}")
            import traceback
            logger.error(f"[OPTIONS WS] Traceback: {traceback.format_exc()}")
            all_option_tokens = []
        
        # Connect to Options WebSocket if tokens are available
        logger.debug(f"[DEBUG] Checking if tokens available for connection: {len(all_option_tokens)} tokens")
        if all_option_tokens:
            try:
                logger.info(f"[OPTIONS WS] Connecting to Options WebSocket with {len(all_option_tokens)} tokens...")
                logger.debug(f"[DEBUG] Options WebSocket client before connect: {self.options_ws_client}")
                logger.debug(f"[DEBUG] Options WebSocket has connect method: {hasattr(self.options_ws_client, 'connect')}")
                
                self.options_ws_client.connect(all_option_tokens)
                logger.info("[OPTIONS WS] Options WebSocket connection initiated")
                logger.info("[OPTIONS WS] Waiting for connection callback...")
                
                # Wait a bit for connection to establish
                time.sleep(3)
                
                # Check if connection was successful
                logger.debug(f"[DEBUG] Checking connection status...")
                logger.debug(f"[DEBUG] Has connected attribute: {hasattr(self.options_ws_client, 'connected')}")
                if hasattr(self.options_ws_client, 'connected'):
                    logger.debug(f"[DEBUG] Connected status: {self.options_ws_client.connected}")
                
                if hasattr(self.options_ws_client, 'connected') and self.options_ws_client.connected:
                    logger.info("[OPTIONS WS] ✓ Options WebSocket connected successfully")
                else:
                    logger.warning("[OPTIONS WS] Options WebSocket connection status unclear - will proceed")
            except Exception as e:
                logger.error(f"[OPTIONS WS] CRITICAL ERROR connecting to Options WebSocket: {e}")
                import traceback
                logger.error(f"[OPTIONS WS] Traceback: {traceback.format_exc()}")
                logger.warning("[OPTIONS WS] Will continue with REST API fallback for option data")
        else:
            logger.warning("[OPTIONS WS] No option tokens available - Options WebSocket not started")
            logger.warning("[OPTIONS WS] Will use REST API fallback for option data")
        
        logger.debug(f"[DEBUG] Final WebSocket status update - Spot tokens: {len(spot_tokens)}, Option tokens: {len(all_option_tokens)}")
        logger.info("="*80)
        
        # CRITICAL FIX: Store option tokens for later use in option chain filtering
        self.subscribed_option_tokens = all_option_tokens
        logger.debug(f"[DEBUG] Stored {len(self.subscribed_option_tokens)} option tokens for filtering")
        
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
        
        # Active trades tracking for observation mode
        self.active_trades = {}  # symbol -> observation trade data
    
    def _increment_execution_id(self):
        """Increment execution ID to prevent stale thread results from affecting decisions."""
        SingleStrikeTrader._current_execution_id += 1
        self._execution_id = SingleStrikeTrader._current_execution_id
        logger.debug(f"[EXECUTION ID] Incremented to {self._execution_id}")
        return self._execution_id
    
    def _get_current_execution_id(self):
        """Get the current execution ID."""
        return self._execution_id
    
    def _validate_execution_id(self, returned_execution_id):
        """Validate that the returned execution ID matches the current one."""
        current_id = self._get_current_execution_id()
        if returned_execution_id != current_id:
            logger.warning(f"[STALE RESULT] Ignoring result from old execution {returned_execution_id} (current: {current_id})")
            return False
        return True

    def confirm_entry_with_ticks(self, symbol, direction, signal_type="MOMENTUM"):
        """
        Strategy-aware micro-confirmation using WebSocket ticks (no blocking delays).
        
        Args:
            symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            direction: CALL or PUT
            signal_type: "RANGE" or "MOMENTUM" (from Execution Brain)
            
        Returns:
            True if ticks confirm direction, False otherwise
        """
        try:
            # Record start time for time window validation
            start_time = time.time()
            
            # Get last 3 price ticks from state_manager
            price_history = self.state_manager.get_price_history(symbol, count=3)
            
            # Minimum tick validation (require 3 ticks for reliable decision)
            if len(price_history) < 3:
                logger.warning(f"[TICK CONFIRM] Insufficient ticks for {symbol}: {len(price_history)}/3 - allowing trade")
                return True
            
            # Time window validation: reject ultra-fast noise (< 500ms)
            time_span = time.time() - start_time
            if time_span == 0:
                logger.warning(f"[TICK CONFIRM] No tick data for {symbol} (time_span=0) - allowing trade (fallback)")
                return True  # No data available, allow trade
            elif time_span < 0.5:
                logger.warning(f"[TICK CONFIRM] Ultra-fast ticks for {symbol}: {time_span*1000:.0f}ms - ignoring noise")
                return False
            
            # Extract first and last price
            p1 = price_history[0]
            p_last = price_history[-1]
            
            # Dynamic tolerance (0.1%)
            tolerance = p1 * 0.001
            max_allowed_move = tolerance * 2
            
            # Intra-move validation: catch spikes
            max_price = max(price_history)
            min_price = min(price_history)
            
            # Stale flat price check: reject dead zones / low liquidity
            price_range = max_price - min_price
            if price_range < (tolerance * 0.2):
                logger.warning(f"[TICK CONFIRM] Stale flat price for {symbol}: range {price_range:.4f} < {tolerance * 0.2:.4f} - no real activity")
                return False
            
            # -----------------------------
            # MOMENTUM LOGIC (STRICT)
            # -----------------------------
            if signal_type == "MOMENTUM":
                if direction == "CALL":
                    confirmed = p_last > p1 + tolerance
                    logger.info(f"[TICK CONFIRM] MOMENTUM CALL {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | CONFIRMED: {confirmed}")
                elif direction == "PUT":
                    confirmed = p_last < p1 - tolerance
                    logger.info(f"[TICK CONFIRM] MOMENTUM PUT {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | CONFIRMED: {confirmed}")
                else:
                    confirmed = False
                return confirmed
            
            # -----------------------------
            # RANGE LOGIC (SMART)
            # -----------------------------
            elif signal_type == "RANGE":
                if direction == "CALL":
                    # Reject: strong downward spike
                    if min_price < p1 - tolerance:
                        confirmed = False
                        logger.info(f"[TICK CONFIRM] RANGE CALL {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | REJECTED (downward spike)")
                    # Reject: slow upward drift beyond allowed range
                    elif p_last > p1 + max_allowed_move:
                        confirmed = False
                        logger.info(f"[TICK CONFIRM] RANGE CALL {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | REJECTED (excessive upward drift)")
                    else:
                        confirmed = True  # flat or small movement allowed
                        logger.info(f"[TICK CONFIRM] RANGE CALL {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | ALLOWED (safe range)")
                
                elif direction == "PUT":
                    # Reject: strong upward spike
                    if max_price > p1 + tolerance:
                        confirmed = False
                        logger.info(f"[TICK CONFIRM] RANGE PUT {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | REJECTED (upward spike)")
                    # Reject: slow downward drift beyond allowed range
                    elif p_last < p1 - max_allowed_move:
                        confirmed = False
                        logger.info(f"[TICK CONFIRM] RANGE PUT {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | REJECTED (excessive downward drift)")
                    else:
                        confirmed = True  # flat or small movement allowed
                        logger.info(f"[TICK CONFIRM] RANGE PUT {symbol}: {p1} -> {p_last} (max: {max_price}, min: {min_price}, time: {time_span*1000:.0f}ms) | ALLOWED (safe range)")
                else:
                    confirmed = False
                return confirmed
            
            # Default safety (fallback to MOMENTUM logic)
            else:
                logger.warning(f"[TICK CONFIRM] Unknown signal_type: {signal_type}, using MOMENTUM logic")
                if direction == "CALL":
                    confirmed = p_last > p1 + tolerance
                elif direction == "PUT":
                    confirmed = p_last < p1 - tolerance
                else:
                    confirmed = False
                return confirmed
            
        except Exception as e:
            logger.error(f"[TICK CONFIRM] Error: {e}")
            return True  # Fail-safe: allow trade on error

    def check_rate_limit(self):
        """Check if we can make an API call based on rate limiting"""
        current_time = time.time()
        if current_time - self.last_api_call_time < self.api_call_cooldown:
            wait_time = self.api_call_cooldown - (current_time - self.last_api_call_time)
            logger.warning(f"[RATE LIMIT] API call blocked, wait {wait_time:.1f}s")
            return False
        return True
    
    def is_symbol_in_cooldown(self, symbol, current_price=None):
        """
        Check if symbol is in cooldown due to tick confirmation rejection.
        
        Args:
            symbol: Symbol to check
            current_price: Current price (optional, for price change validation)
            
        Returns:
            True if in cooldown, False otherwise
        """
        if symbol not in self.tick_rejected_symbols:
            return False
        
        rejection_data = self.tick_rejected_symbols[symbol]
        current_time = time.time()
        
        # Check cooldown period
        time_since_rejection = current_time - rejection_data['last_rejected']
        if time_since_rejection < self.tick_rejection_cooldown:
            logger.info(f"[TICK COOLDOWN] {symbol} in cooldown ({time_since_rejection:.0f}s < {self.tick_rejection_cooldown}s)")
            return True
        
        # Check retry count
        if rejection_data['retry_count'] >= self.max_retry_attempts:
            logger.info(f"[TICK COOLDOWN] {symbol} max retries reached ({self.max_retry_attempts}), permanently skipping")
            return True
        
        # Check price change (if current price provided)
        if current_price is not None and 'last_price' in rejection_data:
            price_change_pct = abs(current_price - rejection_data['last_price']) / rejection_data['last_price'] * 100
            if price_change_pct < 0.1:  # Less than 0.1% change
                logger.info(f"[TICK COOLDOWN] {symbol} price unchanged ({price_change_pct:.3f}% < 0.1%), keeping in cooldown")
                return True
        
        # Cooldown expired, allow retry
        logger.info(f"[TICK COOLDOWN] {symbol} cooldown expired, allowing retry")
        del self.tick_rejected_symbols[symbol]
        return False
    
    def update_tick_rejection(self, symbol, current_price):
        """
        Update tick rejection tracking for a symbol.
        
        Args:
            symbol: Rejected symbol
            current_price: Current price at rejection
        """
        current_time = time.time()
        
        if symbol in self.tick_rejected_symbols:
            # Update existing entry
            self.tick_rejected_symbols[symbol]['last_rejected'] = current_time
            self.tick_rejected_symbols[symbol]['retry_count'] += 1
            self.tick_rejected_symbols[symbol]['last_price'] = current_price
            logger.info(f"[TICK REJECTION] Updated {symbol}: retry {self.tick_rejected_symbols[symbol]['retry_count']}/{self.max_retry_attempts}")
        else:
            # Create new entry
            self.tick_rejected_symbols[symbol] = {
                'last_rejected': current_time,
                'retry_count': 1,
                'last_price': current_price
            }
            logger.info(f"[TICK REJECTION] Added {symbol} to cooldown (retry 1/{self.max_retry_attempts})")
    
    def cleanup_tick_rejections(self):
        """Clean up old tick rejection entries to prevent memory bloat"""
        current_time = time.time()
        symbols_to_remove = []
        
        for symbol, data in self.tick_rejected_symbols.items():
            # Remove entries older than 5 minutes or with max retries
            if (current_time - data['last_rejected'] > 300) or (data['retry_count'] >= self.max_retry_attempts):
                symbols_to_remove.append(symbol)
        
        for symbol in symbols_to_remove:
            del self.tick_rejected_symbols[symbol]
            logger.debug(f"[TICK COOLDOWN] Cleaned up {symbol} from rejection tracking")
    
    def record_api_call(self):
        """Record that an API call was made"""
        self.last_api_call_time = time.time()
    
    # -------------------------
    # PRINT CLEAN DASHBOARD
    # -------------------------
    def print_clean_dashboard(self):
        """Print human-readable market snapshot table (DISABLED in PRO MODE - only monitor shown)"""
        # CRITICAL FIX: Silent logging - no console output
        logger.debug("[DEBUG] print_clean_dashboard() called - DISABLED in PRO MODE")
        return

    def print_trade_monitor(self, active_trades_only=True):
        """
        Print professional trading terminal dashboard with active/closed trades (MCX-style)
        
        Args:
            active_trades_only: If True, only show active trades (OPEN status)
        """
        # ANSI color codes
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        CYAN = '\033[96m'
        WHITE = '\033[97m'
        RESET = '\033[0m'
        
        if not self.state_manager:
            print(f"{WHITE}No state_manager available{RESET}")
            return
        
        # CRITICAL FIX: Combine active trades and trade history for full view
        # Get all trades from StateManager (active trades)
        active_trades = self.state_manager.get_active_trades()
        
        # Combine with trade_history (closed trades)
        all_trades = active_trades + self.trade_history
        
        # Sort chronologically by entry_time (oldest first)
        all_trades.sort(key=lambda t: t.get('entry_time', t.get('timestamp', 0)))
        
        if not all_trades:
            return
        
        # Clear screen for clean terminal view
        print("\033c", end="")
        
        print(f"{WHITE}{'='*80}{RESET}")
        print(f"{WHITE} LIVE TRADING TERMINAL (NSE){RESET}")
        print(f"{WHITE}{'='*80}{RESET}")
        print(f"{WHITE}Session Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Capital: Rs.{self.current_capital:.2f} | Total Trades: {len(all_trades)}{RESET}")
        print(f"{WHITE}{'='*80}{RESET}")
        
        # ALL TRADES SECTION (Active + Closed)
        print(f"\n{WHITE}ALL TRADES (Active + History){RESET}")
        print(f"{WHITE}{'-'*80}{RESET}")
        print(f"{WHITE}{'SYMBOL':<12}{'STRIKE':<8}{'TYPE':<6}{'ENTRY':<8}{'LTP':<8}{'PnL%':<8}{'SL':<8}{'TP':<8}{'DURATION':<10}{'STATE':<6}{'STATUS'}{RESET}")
        print(f"{WHITE}{'-'*80}{RESET}")
        
        total_pnl = 0
        total_investment_all = 0
        
        for trade in all_trades:
            symbol = trade.get('symbol', 'N/A')
            strike = trade.get('strike', 0)
            option_type = trade.get('type', 'N/A') or trade.get('direction', 'N/A')
            entry = trade.get('entry_price', 0)
            
            # For closed trades, use exit_price as current price
            if trade.get('status') == 'CLOSED':
                current_price = trade.get('exit_price', entry)
            else:
                current_price = trade.get('current_price', entry)
            
            target = trade.get('target', 0)
            sl = trade.get('stop_loss', 0)
            
            # For closed trades, use stored PnL
            if trade.get('status') == 'CLOSED':
                pnl = trade.get('pnl', 0)
            else:
                pnl = trade.get('pnl', 0)
            
            status = trade.get('status', 'UNKNOWN')
            quantity = trade.get('quantity', trade.get('lot_size', 1))
            is_stale = trade.get('is_stale', False)  # Get stale flag from trade data
            
            # Determine price state
            if trade.get('status') == 'CLOSED':
                price_state = "CLOSED"
                state_color = CYAN
            elif current_price == 0 or current_price is None:
                price_state = "DEAD"
                state_color = RED
            elif is_stale:
                price_state = "STALE"
                state_color = YELLOW
            else:
                price_state = "LIVE"
                state_color = GREEN
            
            # FIXED: Calculate PnL% based on total investment (entry * quantity), not entry price per share
            total_investment = entry * quantity
            pnl_pct = (pnl / total_investment * 100) if total_investment > 0 else 0
            
            # Accumulate for total calculation
            total_pnl += pnl
            total_investment_all += total_investment
            
            # Calculate duration
            entry_time = trade.get('entry_time')
            duration_str = "00:00"
            
            if trade.get('status') == 'CLOSED':
                # For closed trades, use exit_time - entry_time
                exit_time = trade.get('exit_time') or trade.get('timestamp')
                if entry_time and exit_time:
                    if isinstance(entry_time, datetime):
                        entry_ts = entry_time.timestamp()
                    else:
                        entry_ts = entry_time
                    
                    if isinstance(exit_time, datetime):
                        exit_ts = exit_time.timestamp()
                    elif isinstance(exit_time, str):
                        # Try to parse string timestamp
                        try:
                            exit_ts = datetime.fromisoformat(exit_time).timestamp()
                        except:
                            exit_ts = time.time()
                    else:
                        exit_ts = exit_time
                    
                    duration = (exit_ts - entry_ts) / 60
                    minutes = int(duration)
                    seconds = int((duration - minutes) * 60)
                    duration_str = f"{minutes:02}:{seconds:02}"
            elif entry_time:
                # For active trades, use current time - entry_time
                if isinstance(entry_time, datetime):
                    duration = (datetime.now() - entry_time).total_seconds() / 60
                else:
                    duration = (time.time() - entry_time) / 60
                minutes = int(duration)
                seconds = int((duration - minutes) * 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            
            # Status
            if trade.get('status') == 'CLOSED':
                # For closed trades, show exit reason
                status_display = trade.get('exit_reason', 'CLOSED')[:10]  # Truncate to fit
            elif current_price <= sl:
                status_display = "SL HIT"
            elif current_price >= target:
                status_display = "TP HIT"
            else:
                # For active trades, show "ACTIVE" (not PROFIT/LOSS)
                status_display = "ACTIVE"
            
            # Color coding
            pnl_color = GREEN if pnl >= 0 else RED
            status_color = YELLOW if status == 'OPEN' else CYAN if status == 'CLOSED' else WHITE
            
            print(f"{WHITE}{symbol:<12}{strike:<8.0f}{option_type:<6}{entry:<8.2f}{current_price:<8.2f}"
                  f"{pnl_color}{pnl_pct:<+8.1f}{RESET}{sl:<8.2f}{target:<8.2f}{duration_str:<10}"
                  f"{state_color}{price_state:<6}{RESET}{status_color}{status_display}{RESET}")
        
        print(f"{WHITE}{'-'*80}{RESET}")
        # FIXED: Calculate total PnL% based on total PnL and total investment
        total_pnl_pct = (total_pnl / total_investment_all * 100) if total_investment_all > 0 else 0
        total_color = GREEN if total_pnl_pct >= 0 else RED
        print(f"{WHITE}TOTAL PnL%: {total_color}{total_pnl_pct:+.2f}%{RESET}")
        print(f"{WHITE}{'-'*80}{RESET}")
        
        # Session summary
        total_trades = len(all_trades)
        active_trades_count = len([t for t in all_trades if t.get('status') == 'OPEN'])
        closed_trades_count = len([t for t in all_trades if t.get('status') == 'CLOSED'])
        winning_trades = sum(1 for t in all_trades if t.get('pnl', 0) > 0)
        losing_trades = sum(1 for t in all_trades if t.get('pnl', 0) < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        print(f"{WHITE}Session: {total_trades} trades ({active_trades_count} active, {closed_trades_count} closed) | {winning_trades}W {losing_trades}L | Win Rate: {win_rate:.1f}%{RESET}")
        print(f"{WHITE}{'='*80}{RESET}")

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
                institutional_data = self.safe_calculate_institutional_walls(option_chain_data, spot_price, symbol, timeout=2)
                
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
        # In paper trading mode, always return True for testing
        if self.paper_trading:
            return True
        
        now = datetime.now().time()
        return self.market_open <= now <= self.market_close
    
    def check_rest_fallback_allowed(self):
        """
        Check if REST fallback is allowed based on usage patterns.
        Prevents continuous REST fallback usage to ensure WebSocket stabilization.
        
        Returns:
            bool: True if REST fallback allowed, False otherwise
        """
        current_time = time.time()
        
        # Reset counter if cooldown period passed
        if self.rest_fallback_start_time and (current_time - self.rest_fallback_start_time) > self.rest_fallback_cooldown:
            logger.info("[REST FALLBACK] Cooldown period passed - resetting REST fallback counter")
            self.rest_fallback_count = 0
            self.rest_fallback_start_time = None
            return True
        
        # Check if max continuous REST calls reached
        if self.rest_fallback_count >= self.max_continuous_rest_fallback:
            logger.warning(f"[REST FALLBACK] Max continuous REST calls reached ({self.rest_fallback_count})")
            logger.warning(f"[REST FALLBACK] Forcing WebSocket wait - REST fallback blocked for {self.rest_fallback_cooldown} seconds")
            return False
        
        # Track REST fallback usage
        if self.rest_fallback_start_time is None:
            self.rest_fallback_start_time = current_time
        
        self.rest_fallback_count += 1
        logger.info(f"[REST FALLBACK] REST fallback call #{self.rest_fallback_count}/{self.max_continuous_rest_fallback}")
        
        return True

    def safe_calculate_institutional_walls(self, option_chain_data, spot_price, symbol, timeout=2):
        """
        SAFE WRAPPER: Calculate institutional walls with threading timeout and fallback.
        Prevents deadlocks and blocking of the symbol loop.
        
        Args:
            option_chain_data: Option chain data
            spot_price: Current spot price
            symbol: Symbol name
            timeout: Timeout in seconds (default: 2 second - strict execution guard)
            
        Returns:
            dict: Institutional walls data or fallback values if timeout/error
        """
        # CRITICAL: Get execution ID for this call (prevents stale thread results)
        execution_id = self._get_current_execution_id()
        logger.debug(f"[EXECUTION ID] Processing {symbol} with execution_id: {execution_id}")
        
        # CRITICAL: Thread management - check active thread count
        active_threads = threading.active_count()
        logger.debug(f"[THREAD COUNT] Active threads: {active_threads} (threshold: {self.THREAD_COUNT_WARNING_THRESHOLD})")
        
        if active_threads >= self.THREAD_COUNT_WARNING_THRESHOLD:
            logger.warning(f"[THREAD LIMIT] Too many active threads ({active_threads}) - skipping institutional_walls for {symbol}")
            return self._get_fallback_institutional_walls(spot_price, symbol)
        
        # CRITICAL: Execution guard - must not block main thread
        logger.debug(f"[EXECUTION GUARD] Starting calculate_institutional_walls for {symbol} (timeout: {timeout}s)")
        
        result = [None]
        exception = [None]
        returned_execution_id = [None]
        
        def worker():
            try:
                from services.optionstar_service.service import calculate_institutional_walls
                result[0] = calculate_institutional_walls(option_chain_data, spot_price, symbol)
                returned_execution_id[0] = execution_id  # Tag result with execution ID
            except Exception as e:
                exception[0] = e
        
        # Start worker thread (daemon=True ensures cleanup on exit)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        
        # Wait with timeout
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            # Thread still running - timeout
            logger.error(f"[TIMEOUT] calculate_institutional_walls timed out for {symbol} after {timeout}s - using fallback")
            logger.warning(f"[THREAD LEAK] Thread still alive for {symbol} - daemon thread will be cleaned up on exit")
            logger.warning(f"[STALE THREAD] Late result from execution {execution_id} will be ignored when it returns")
            # Daemon thread will be automatically killed when main process exits
            return self._get_fallback_institutional_walls(spot_price, symbol)
        
        if exception[0] is not None:
            logger.error(f"[ERROR] calculate_institutional_walls failed for {symbol}: {exception[0]} - using fallback")
            return self._get_fallback_institutional_walls(spot_price, symbol)
        
        if result[0] is not None:
            # CRITICAL: Validate execution ID to prevent stale results
            if not self._validate_execution_id(returned_execution_id[0]):
                logger.warning(f"[STALE RESULT] Ignoring institutional_walls result for {symbol} - using fallback")
                return self._get_fallback_institutional_walls(spot_price, symbol)
            
            logger.debug(f"[EXECUTION GUARD] calculate_institutional_walls completed for {symbol} (execution_id: {returned_execution_id[0]})")
            logger.debug(f"[THREAD COUNT] Post-execution active threads: {threading.active_count()}")
            return result[0]
        
        # No result - use fallback
        logger.warning(f"[FALLBACK] calculate_institutional_walls for {symbol} returned None - using fallback")
        return self._get_fallback_institutional_walls(spot_price, symbol)
    
    def _get_fallback_institutional_walls(self, spot_price, symbol):
        """
        Fallback institutional walls when calculate_institutional_walls fails/times out.
        Uses market-driven defaults to prevent trading blockage.
        
        Args:
            spot_price: Current spot price
            symbol: Symbol name
            
        Returns:
            dict: Fallback institutional walls data
        """
        logger.warning(f"[FALLBACK] Using default institutional walls for {symbol}")
        
        # Calculate fallback support/resistance based on spot price
        support = spot_price - (spot_price * 0.02)  # 2% below spot
        resistance = spot_price + (spot_price * 0.02)  # 2% above spot
        
        return {
            "spot_price": spot_price,
            "resistance": {
                "strike": resistance,
                "oi": 0,  # No OI data in fallback
                "distance": resistance - spot_price
            },
            "support": {
                "strike": support,
                "oi": 0,  # No OI data in fallback
                "distance": spot_price - support
            },
            "trend_bias": "NEUTRAL",  # Neutral bias in fallback
            "confidence": {
                "level": "LOW",
                "score": 0.3,
                "oi_gap_percentage": 0,
                "oi_gap": 0
            },
            "service_metadata": {
                "service": "optionstar_service",
                "version": "2.0.0",
                "timestamp": datetime.now().isoformat(),
                "warning": "FALLBACK_USED - calculate_institutional_walls timed out or failed"
            }
        }

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
            # ZERODHA PATH: Use WebSocket data with REST fallback
            try:
                price = self.state_manager.get_latest_price(symbol)
                
                if price is None:
                    logger.warning(f"[WS FALLBACK] WebSocket data not available for {symbol} - checking REST fallback allowance")
                    # CRITICAL FIX: Check REST fallback allowance before using
                    if not self.check_rest_fallback_allowed():
                        logger.warning(f"[WS FALLBACK] REST fallback blocked for {symbol} - forcing WebSocket wait")
                        # Use cache if available, otherwise return 0 to force wait
                        if symbol in self.spot_price_cache:
                            cache_age = current_time - self.spot_price_cache_time.get(symbol, 0)
                            if cache_age < 60:  # Use cache if less than 60 seconds old
                                logger.info(f"[CACHE FALLBACK] Using cached price for {symbol} (age: {cache_age:.1f}s)")
                                return self.spot_price_cache[symbol]
                        return 0
                    
                    # CRITICAL FIX: Use REST API fallback instead of skipping
                    try:
                        self._rate_limit_guard()
                        quote = self.kite_client.quote([f"NSE:{symbol}"])
                        if quote and f"NSE:{symbol}" in quote:
                            price = quote[f"NSE:{symbol}"].get("last_price")
                            if price and price > 0:
                                logger.info(f"[REST FALLBACK] Got price from REST API for {symbol}: {price}")
                                # Cache the REST result
                                self.spot_price_cache[symbol] = price
                                self.spot_price_cache_time[symbol] = current_time
                                return price
                    except Exception as e:
                        logger.error(f"[REST FALLBACK] Failed to get price from REST API for {symbol}: {e}")
                    
                    logger.warning(f"[WS FALLBACK] Both WebSocket and REST failed for {symbol} - using cached price if available")
                    # Final fallback to cache
                    if symbol in self.spot_price_cache:
                        cache_age = current_time - self.spot_price_cache_time.get(symbol, 0)
                        if cache_age < 60:  # Use cache if less than 60 seconds old
                            logger.info(f"[CACHE FALLBACK] Using cached price for {symbol} (age: {cache_age:.1f}s)")
                            return self.spot_price_cache[symbol]
                    
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

    @property
    def trade_active(self):
        """Derived property - single source of truth is active_trades"""
        return len(self.active_trades) > 0

    def filter_trade_queue(self):
        """Filter trade queue: keep top 5, remove stale trades (>60s)"""
        import time
        now = time.time()

        # Remove stale trades
        self.trade_queue = {
            k: v for k, v in self.trade_queue.items()
            if now - v.get('timestamp', now) < self.queue_stale_seconds
        }

        # Keep only top 5 by score
        if len(self.trade_queue) > self.queue_max_size:
            sorted_trades = sorted(self.trade_queue.items(), key=lambda x: x[1].get('score', 0), reverse=True)
            self.trade_queue = dict(sorted_trades[:self.queue_max_size])

        logger.debug(f"[QUEUE FILTER] Queue size after filter: {len(self.trade_queue)}")

    def add_to_queue(self, opportunity):
        """Add opportunity to queue (update if exists, no duplicates)"""
        # Create unique trade_id
        trade_id = f"{opportunity['symbol']}_{opportunity['strike']}_{opportunity['direction']}"

        # Add timestamp if not present
        if 'timestamp' not in opportunity:
            import time
            opportunity['timestamp'] = time.time()

        # CRITICAL FIX: Skip if already executed
        if trade_id in self.executed_trades:
            logger.warning(f"[QUEUE] Skipping {opportunity['symbol']} - already executed")
            return

        # Insert/Update (dict ensures no duplicates)
        self.trade_queue[trade_id] = opportunity

        # Filter queue
        self.filter_trade_queue()

        logger.debug(f"[QUEUE] Added {trade_id} to queue. Queue size: {len(self.trade_queue)}")

    def collect_queue_opportunities(self):
        """Collect opportunities for queue during active trade (NO execution)"""
        import time
        # Use specific symbols if provided, otherwise use all instruments from config
        if self.symbols:
            instruments = self.symbols
        else:
            instruments = self.config.get('instruments', {}).keys()

        logger.info(f"[QUEUE COLLECTION] Starting queue collection for {len(instruments)} symbols")

        for symbol in instruments:
            try:
                # Process each symbol to collect opportunities
                # This is similar to select_best_strike but only for queue collection
                # Simplified version - just check if score >= 70 and add to queue
                logger.debug(f"[QUEUE COLLECTION] Processing {symbol}")

                # Get option chain
                option_chain = self.get_option_chain_for_optionstar(symbol)
                if not option_chain:
                    logger.debug(f"[QUEUE COLLECTION] No option chain for {symbol}")
                    continue

                # Get spot price
                spot_price = self.get_spot_price(symbol)
                if not spot_price:
                    logger.debug(f"[QUEUE COLLECTION] No spot price for {symbol}")
                    continue

                # Get PCR and buildup
                pcr, buildup_pattern = self.get_pcr_and_buildup(option_chain)

                # Simple scoring for queue collection
                # If PCR is bullish or bearish with buildup, add to queue
                score = 0
                direction = None

                if pcr > 1.2 and buildup_pattern == "LONG_BUILDUP":
                    direction = "PUT"
                    score = 70
                elif pcr < 0.8 and buildup_pattern == "LONG_BUILDUP":
                    direction = "CALL"
                    score = 70

                if score >= 70 and direction:
                    # Get option price
                    option_price, expiry, _ = self.get_option_price(symbol, spot_price, direction, None, option_chain)

                    if option_price and option_price > 0:
                        # Create opportunity for queue
                        opportunity = {
                            'symbol': symbol,
                            'strike': int(spot_price),  # Simplified - use spot as strike
                            'direction': direction,
                            'option_price': option_price,
                            'score': score,
                            'timestamp': time.time()
                        }

                        # Add to queue (method handles filtering and validation)
                        self.add_to_queue(opportunity)
                        logger.info(f"[QUEUE COLLECTION] Added {symbol} to queue (Score: {score}/100)")

            except Exception as e:
                logger.error(f"[QUEUE COLLECTION] Error processing {symbol}: {e}")
                continue

        logger.info(f"[QUEUE COLLECTION] Completed. Queue size: {len(self.trade_queue)}")

    def is_opportunity_still_valid(self, opportunity):
        """Revalidate opportunity before execution (production-grade safeguard)"""
        try:
            symbol = opportunity['symbol']
            strike = opportunity['strike']
            direction = opportunity['direction']
            original_score = opportunity['score']

            # Re-fetch latest option chain
            option_chain = self.get_option_chain_for_optionstar(symbol)
            if not option_chain:
                logger.warning(f"[VALIDATION] No option chain for revalidation of {symbol}")
                return False

            # Re-check price
            option_price, _, _ = self.get_option_price(symbol, strike, direction, opportunity.get('expiry'), option_chain)
            if not option_price or option_price == 0:
                logger.warning(f"[VALIDATION] Price invalid for {symbol}: {option_price}")
                return False

            # Re-check PCR (simple validation - if PCR moved significantly, skip)
            pcr, _ = self.get_pcr_and_buildup(option_chain)
            if pcr == 0:
                logger.warning(f"[VALIDATION] PCR invalid for {symbol}: {pcr}")
                return False

            # Re-check score (simple validation - if score dropped significantly, skip)
            # This is a simplified check - in production, you might re-run full scoring
            if option_price:
                # Simple price change check - if price moved > 10%, signal might be stale
                original_price = opportunity['option_price']
                price_change_pct = abs((option_price - original_price) / original_price) * 100 if original_price > 0 else 0
                if price_change_pct > 20:
                    logger.warning(f"[VALIDATION] Price changed too much for {symbol}: {price_change_pct:.1f}% (original: {original_price}, current: {option_price})")
                    return False

            logger.info(f"[VALIDATION] Opportunity still valid for {symbol}: Price={option_price}, PCR={pcr:.2f}")
            return True

        except Exception as e:
            logger.error(f"[VALIDATION] Error revalidating {symbol}: {e}")
            return False

    def calculate_atm_strike(self, symbol, spot_price):
        """Calculate ATM strike for a symbol based on spot price"""
        try:
            # Get step size from config or use default
            instrument_config = self.config.get('instruments', {}).get(symbol, {})
            step_size = instrument_config.get('step_size', 50)  # Default step size
            
            # Calculate nearest strike
            atm_strike = round(spot_price / step_size) * step_size
            logger.info(f"[ATM CALC] Symbol: {symbol}, Spot: {spot_price}, Step: {step_size}, ATM: {atm_strike}")
            return int(atm_strike)
        except Exception as e:
            logger.error(f"[ATM CALC] Error calculating ATM strike for {symbol}: {e}")
            return int(spot_price)  # Fallback to spot price

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
        """Get option chain data for OptionStar continuous monitoring (Smart Strike format)
        
        CRITICAL FIX: Returns cached option chain in Smart Strike format (flat list)
        NOT OptionStar format (dict with calls/puts) - that was causing Smart Strike to fail
        """
        try:
            spot_price = self.get_spot_price(symbol, bypass_cache=True)
            if spot_price == 0:
                return None
            
            # CRITICAL FIX: Return cached option chain directly (already in Smart Strike format)
            # The cached option chain is a flat list of contracts, which is what Smart Strike expects
            option_chain = self.get_real_option_chain(symbol, spot_price)
            if not option_chain:
                return None
            
            # CRITICAL FIX: Return the flat list format, NOT OptionStar dict format
            # Smart Strike expects: [{'strike': x, 'type': 'CE/PE', 'oi': y, ...}, ...]
            # OptionStar expects: {'calls': [...], 'puts': [...], 'spotPrice': x}
            # We need Smart Strike format here
            return option_chain
            
        except Exception as e:
            logger.error(f"Error getting option chain for OptionStar: {e}")
            return None
    
    def get_option_chain_for_optionstar_dict_format(self, symbol):
        """Get option chain data in OptionStar dict format (for OptionStar service)
        
        Returns: {'calls': [...], 'puts': [...], 'spotPrice': x}
        """
        try:
            spot_price = self.get_spot_price(symbol, bypass_cache=True)
            if spot_price == 0:
                return None
            
            option_chain = self.get_real_option_chain(symbol, spot_price)
            if not option_chain:
                return None
            
            # Convert to OptionStar format (dict with calls/puts)
            calls = []
            puts = []
            for item in option_chain:
                if item.get('type') == 'CE':
                    oi_value = item.get('oi', 0) or item.get('call_oi', 0)
                    calls.append({
                        'strikePrice': item.get('strike'),
                        'lastPrice': item.get('last_price', 0),
                        'openInterest': oi_value
                    })
                elif item.get('type') == 'PE':
                    oi_value = item.get('oi', 0) or item.get('put_oi', 0)
                    puts.append({
                        'strikePrice': item.get('strike'),
                        'lastPrice': item.get('last_price', 0),
                        'openInterest': oi_value
                    })
            
            return {
                'calls': calls,
                'puts': puts,
                'spotPrice': spot_price
            }
            
        except Exception as e:
            logger.error(f"Error getting option chain in OptionStar dict format: {e}")
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
            # PRODUCTION FIX: Use symbol-specific cached option chain to avoid redundant API calls
            current_time = time.time()
            symbol_cache = self.cached_option_chains.get(symbol)
            symbol_cache_time = self.cached_option_chain_times.get(symbol, 0)
            
            if (symbol_cache and 
                current_time - symbol_cache_time < self.option_chain_cache_duration):
                
                # CRITICAL FIX: Validate cached data before using it
                total_ce_oi = sum(item.get('oi', 0) for item in symbol_cache if item.get('type') == 'CE')
                total_pe_oi = sum(item.get('oi', 0) for item in symbol_cache if item.get('type') == 'PE')
                
                if total_ce_oi == 0 and total_pe_oi == 0:
                    logger.warning(f"[CACHE BUG] Invalid OI detected in cache for {symbol} (CE: {total_ce_oi}, PE: {total_pe_oi}) - refetching")
                    logger.warning(f"[CACHE BUG] Cache contains wrong format data - forcing refresh")
                    # Force refresh by skipping cache
                    pass
                else:
                    logger.debug(f"[PERF] Using cached option chain for {symbol} (age: {current_time - symbol_cache_time:.1f}s)")
                    logger.debug(f"[CACHE VALID] Cached OI check for {symbol} - CE: {total_ce_oi}, PE: {total_pe_oi}")
                    return symbol_cache
            
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
                            
                            # Cache the converted format (not raw format) - symbol-specific
                            self.cached_option_chains[symbol] = option_chain_converted
                            self.cached_option_chain_times[symbol] = current_time
                            logger.info(f"[UPSTOX] Successfully fetched and cached option chain for {symbol} with {len(option_chain_converted)} contracts")
                            
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
            logger.debug(f"[ZERODHA] Fetching optimized option chain from Zerodha API for {symbol}")

            # PRODUCTION FIX: Check rate limit before API call
            if not self.check_rate_limit():
                logger.warning(f"[RATE LIMIT] Option chain fetch blocked for {symbol}, using cached data")
                return self.cached_option_chains.get(symbol, [])
            
            # Record API call
            self.record_api_call()

            # Use optimized option chain (Prop-Desk Level)
            # CRITICAL FIX: Pass subscribed_option_tokens for proper filtering
            subscribed_tokens = getattr(self, 'subscribed_option_tokens', [])
            logger.debug(f"[DEBUG] Calling get_option_chain_optimized with {len(subscribed_tokens)} subscribed tokens")
            chain, pcr, delta_data, atm = self.kite_client.get_option_chain_optimized(symbol, spot_price, state_manager=self.state_manager, subscribed_tokens=subscribed_tokens)

            if not chain:
                logger.warning(f"{symbol}: No option chain data from optimized API")
                return None

            # PERFORMANCE FIX: Filter chain to only include strikes around ATM (±10 steps)
            # This reduces processing from 200+ options to ~40 options
            logger.debug(f"[PERFORMANCE] Filtering option chain around ATM: {atm}")
            
            # Calculate strike step (assume 5 for most indices, fallback to 10)
            strike_step = 5 if symbol in ["NIFTY", "BANKNIFTY"] else 10
            
            # Calculate bounds
            lower_bound = atm - (strike_step * 10)
            upper_bound = atm + (strike_step * 10)
            
            logger.debug(f"[PERFORMANCE] Strike range: {lower_bound} to {upper_bound} (ATM: {atm}, Step: {strike_step})")
            
            # Filter chain to only include strikes within bounds
            original_chain_size = len(chain)
            chain = {
                strike: data 
                for strike, data in chain.items() 
                if lower_bound <= strike <= upper_bound
            }
            
            filtered_chain_size = len(chain)
            logger.debug(f"[PERFORMANCE] Filtered chain: {original_chain_size} → {filtered_chain_size} strikes ({filtered_chain_size/original_chain_size*100:.1f}% retained)")
            
            if filtered_chain_size > 50:
                logger.warning(f"[PERFORMANCE] Too many strikes after filtering ({filtered_chain_size}) - check logic")
                logger.warning(f"[PERFORMANCE] Expected ~40 strikes, got {filtered_chain_size}")

            # FIX: Get the original options data to preserve instrument_token and tradingsymbol
            # Load instruments to map strike back to instrument data
            option_map = self.kite_client.load_instruments_optimized("NFO")
            if symbol not in option_map:
                logger.warning(f"No options found for {symbol}")
                return None
            
            all_options = option_map[symbol]
            
            # PERFORMANCE FIX: Filter all_options to only include strikes in filtered chain
            # This reduces instrument_map size from 200+ to ~40
            filtered_strikes = set(chain.keys())
            all_options = [opt for opt in all_options if opt.get("strike", 0) in filtered_strikes]
            
            logger.info(f"[PERFORMANCE] Filtered all_options: {len(option_map[symbol])} → {len(all_options)} contracts")
            
            # DEBUG: Log what we have in all_options
            logger.debug(f"[DEBUG] Total options for {symbol}: {len(all_options)}")
            if all_options:
                logger.debug(f"[DEBUG] Sample option data: {all_options[0]}")
            
            # CRITICAL FIX: Verify data source contains BOTH CE and PE
            ce_count_input = len([opt for opt in all_options if "CE" in opt.get("tradingsymbol", "")])
            pe_count_input = len([opt for opt in all_options if "PE" in opt.get("tradingsymbol", "")])
            logger.debug(f"[DATA SOURCE CHECK] Input data - CE: {ce_count_input}, PE: {pe_count_input}")
            
            if pe_count_input == 0:
                logger.error(f"CRITICAL: Input data has NO PE contracts for {symbol} - upstream filtering is wrong")
                logger.error(f"CRITICAL: This will cause PE lookups to fail")
                # Continue anyway to see what happens, but log the error
            
            # Create a mapping from (strike, type, expiry) to instrument data
            # FIX: Add expiry to key to avoid picking wrong expiry
            # CRITICAL FIX: Filter instrument_map to only include contracts for the target expiry
            # Get the target expiry from the chain data
            target_expiry = None
            if chain:
                first_strike_data = next(iter(chain.values()))
                ce_data = first_strike_data.get("CE", {})
                pe_data = first_strike_data.get("PE", {})
                target_expiry = ce_data.get("expiry", pe_data.get("expiry"))
            
            # STEP 3: NORMALIZE EXPIRY FORMAT (CRITICAL FIX)
            # Ensure BOTH expiry and target_expiry are datetime.date
            def normalize_expiry(expiry):
                if isinstance(expiry, str):
                    try:
                        from datetime import datetime
                        return datetime.strptime(expiry, "%Y-%m-%d").date()
                    except Exception as e:
                        logger.warning(f"[EXPIRY PARSE] Failed to parse expiry '{expiry}': {e}")
                        return None
                return expiry
            
            target_expiry = normalize_expiry(target_expiry)
            logger.debug(f"[TARGET EXPIRY] {target_expiry} (type: {type(target_expiry)})")
            
            instrument_map = {}
            filtered_ce = 0
            filtered_pe = 0
            added_ce = 0
            added_pe = 0
            
            for opt in all_options:
                strike = opt.get("strike", 0)
                expiry = opt.get("expiry")
                tradingsymbol = opt.get("tradingsymbol", "")
                
                # CRITICAL FIX: Use endswith instead of 'in' to correctly identify CE/PE
                # Previous bug: "CE" in tradingsymbol matched both CE and PE (e.g., "PE" contains "E")
                typ = "CE" if tradingsymbol.endswith("CE") else "PE"
                
                # STEP 6: OPTIONAL HARDENING - Normalize strike to avoid float mismatch
                strike = round(float(strike), 2)
                
                # STEP 3: Normalize expiry format
                expiry = normalize_expiry(expiry)
                if expiry is None:
                    logger.warning(f"[EXPIRY SKIP] Skipping {tradingsymbol} - expiry normalization failed")
                    continue
                
                # STEP 2: LOG ACTUAL VALUES (NO ASSUMPTIONS)
                logger.debug(f"[EXPIRY RAW] {tradingsymbol} -> expiry: {expiry} (type: {type(expiry)}), type: {typ}")
                
                # STEP 4: RE-ENABLE SAFE FILTER (POST NORMALIZATION)
                if target_expiry and expiry != target_expiry:
                    logger.debug(f"[FILTER] Skipping {typ} {strike} due to expiry mismatch: {expiry} != {target_expiry}")
                    if typ == "CE":
                        filtered_ce += 1
                    else:
                        filtered_pe += 1
                    continue
                
                # Add to map
                instrument_map[(strike, typ, expiry)] = opt
                if typ == "CE":
                    added_ce += 1
                else:
                    added_pe += 1
            
            logger.debug(f"[DEBUG] Filtering stats - Filtered CE: {filtered_ce}, Filtered PE: {filtered_pe}")
            logger.debug(f"[DEBUG] Filtering stats - Added CE: {added_ce}, Added PE: {added_pe}")
            
            logger.debug(f"[DEBUG] Instrument_map built with {len(instrument_map)} contracts for expiry {target_expiry}")
            
            # STEP 5: VALIDATE instrument_map (MANDATORY)
            ce_count = len([k for k in instrument_map.keys() if k[1] == "CE"])
            pe_count = len([k for k in instrument_map.keys() if k[1] == "PE"])
            
            logger.debug(f"[MAP CHECK] CE: {ce_count}, PE: {pe_count}")
            
            if pe_count == 0:
                logger.error("CRITICAL: PE missing after map build - ABORTING")
                logger.error(f"CRITICAL: Input had PE: {pe_count_input}, but map has PE: {pe_count}")
                logger.error(f"CRITICAL: This indicates a filtering bug in instrument_map creation")
                return None

            # Convert optimized chain to Engine1 format with instrument data
            # Engine1 expects: [{'strike': x, 'call_oi': y, 'put_oi': z, 'last_price': w, 'type': 'CE/PE', 'instrument_token': ..., 'tradingsymbol': ...}]
            option_chain = []
            
            logger.debug(f"[OPTION CHAIN] Processing {len(chain)} strikes for {symbol} (filtered from {original_chain_size} total)")

            for strike, data in chain.items():
                ce_data = data.get("CE", {})
                pe_data = data.get("PE", {})
                expiry = ce_data.get("expiry", pe_data.get("expiry", ""))  # Add expiry field
                
                # CRITICAL FIX: Standardize expiry format BEFORE lookup
                # instrument_map uses expiry as datetime.date, but API returns string
                if isinstance(expiry, str):
                    from datetime import datetime
                    try:
                        expiry = datetime.strptime(expiry, "%Y-%m-%d").date()
                    except:
                        logger.warning(f"[EXPIRY DEBUG] Failed to parse expiry: {expiry}")
                        expiry = datetime.now().date()

                if ce_data and ce_data.get("ltp", 0) > 0:
                    # Get instrument data for this strike and expiry
                    # CRITICAL FIX: Ensure lookup matches exact type (strike as float)
                    ce_instrument = instrument_map.get((float(strike), "CE", expiry), {})
                    
                    # REMOVED: Debug logging for every strike (was causing massive log spam)
                    # Only log if lookup fails (debug level only)
                    if not ce_instrument or not ce_instrument.get("instrument_token"):
                        logger.debug(f"[EXPIRY DEBUG] CE instrument_map lookup failed for strike={strike}, expiry={expiry}")
                        logger.debug(f"[EXPIRY DEBUG] Available Keys Sample: {list(instrument_map.keys())[:5]}")
                    
                    # CRITICAL FIX: Add safety check
                    if not ce_instrument:
                        logger.error("CRITICAL: CE Instrument lookup failed - expiry mismatch")
                        continue
                    
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
                    # CRITICAL FIX: Ensure lookup matches exact type (strike as float)
                    pe_instrument = instrument_map.get((float(strike), "PE", expiry), {})
                    
                    # REMOVED: Debug logging for every strike (was causing massive log spam)
                    # Only log if lookup fails (debug level only)
                    if not pe_instrument or not pe_instrument.get("instrument_token"):
                        logger.debug(f"[EXPIRY DEBUG] PE instrument_map lookup failed for strike={strike}, expiry={expiry}")
                        logger.debug(f"[EXPIRY DEBUG] Available Keys Sample: {list(instrument_map.keys())[:5]}")
                    
                    # CRITICAL FIX: Add safety check
                    if not pe_instrument:
                        logger.error("CRITICAL: PE Instrument lookup failed - expiry mismatch")
                        continue
                    
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

            logger.debug(f"Built option chain with {len(option_chain)} strikes from optimized API for {symbol}")
            logger.debug(f"Optimized metrics - PCR: {pcr:.2f}, ATM: {atm}, DeltaOI available: {len(delta_data)} strikes")
            logger.debug(f"Option chain includes REAL OI data from Zerodha API with DeltaOI tracking")

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
            
            # Cache the converted format (not raw format) - symbol-specific
            self.cached_option_chains[symbol] = option_chain_converted
            self.cached_option_chain_times[symbol] = current_time
            logger.info(f"[PERF] Cached option chain for {symbol} (duration: {self.option_chain_cache_duration}s)")
            
            # Return the converted format for consistency
            option_chain = option_chain_converted

            # DEBUG: Log option chain structure before return
            logger.debug(f"[DEBUG] Option chain keys: {list(set([o.get('strike') for o in option_chain]))[:5]}")
            logger.debug(f"[DEBUG] Option chain total contracts: {len(option_chain)}")
            
            return option_chain

        except Exception as e:
            logger.error(f"Error fetching optimized option chain for {symbol}: {e}")
            return None

    def fetch_option_chain_for_monitoring(self, symbol):
        """
        Fetch option chain in background for monitoring.
        This allows immediate execution without waiting for option chain fetch.
        """
        try:
            logger.info(f"[MONITORING FETCH DEBUG] Starting background option chain fetch for {symbol}")
            logger.info(f"[MONITORING FETCH DEBUG] Current self.current_option_chain before fetch: {'Available' if hasattr(self, 'current_option_chain') and self.current_option_chain else 'None'}")
            option_chain = self.get_option_chain_for_optionstar(symbol)
            logger.info(f"[MONITORING FETCH DEBUG] get_option_chain_for_optionstar returned: {'Success' if option_chain else 'None'}")
            if option_chain:
                self.current_option_chain = option_chain
                logger.info(f"[MONITORING FETCH DEBUG] Option chain fetched and stored for {symbol} monitoring: {len(option_chain)} contracts")
                logger.info(f"[MONITORING FETCH DEBUG] self.current_option_chain after fetch: {len(self.current_option_chain)} contracts")
            else:
                logger.warning(f"[MONITORING FETCH DEBUG] Failed to fetch option chain for {symbol}")
        except Exception as e:
            logger.error(f"[MONITORING FETCH DEBUG] Error fetching option chain for {symbol}: {e}")
            import traceback
            logger.error(f"[MONITORING FETCH DEBUG] Traceback: {traceback.format_exc()}")

    def parallel_queue_collection(self, symbols_to_process, executed_symbol):
        """
        Run queue collection in parallel thread while trade executes.
        Processes remaining symbols and adds to queue based on simple PCR/buildup scoring.
        Runs continuously while trade is active with rate limiting.

        CRITICAL ISOLATION RULES:
        - Uses thread-safe storage with parallel_queue_lock
        - Does NOT modify active_trades
        - Does NOT modify current_symbol/current_option_chain
        - Does NOT trigger execution
        - Does NOT interfere with monitor
        - Stores results in parallel_queue_results with max size limit

        Args:
            symbols_to_process: List of symbols to analyze
            executed_symbol: Symbol that was already executed (skip this one)
        """
        logger.info(f"[PARALLEL QUEUE] Starting continuous background queue collection for {len(symbols_to_process)} symbols")
        logger.info(f"[PARALLEL QUEUE] Skipping executed symbol: {executed_symbol}")

        max_queue_size = 5  # Limit to 5 opportunities in shared results
        loop_count = 0
        max_loops = 1000  # Fail-safe: prevent infinite loop (1000 cycles = ~2.7 hours)

        while self.trade_active and loop_count < max_loops:
            try:
                loop_count += 1
                collected_opportunities = []

                for symbol in symbols_to_process:
                    # Skip the symbol that was already executed
                    if symbol == executed_symbol:
                        logger.debug(f"[PARALLEL QUEUE] Skipping executed symbol: {symbol}")
                        continue

                    # Stop if we've collected enough opportunities in this cycle
                    if len(collected_opportunities) >= max_queue_size:
                        logger.debug(f"[PARALLEL QUEUE] Collected {max_queue_size} opportunities this cycle, stopping scan")
                        break

                    logger.debug(f"[PARALLEL QUEUE] Processing symbol: {symbol}")

                    try:
                        # Get option chain
                        option_chain = self.get_option_chain_for_optionstar(symbol)
                        if not option_chain:
                            logger.debug(f"[PARALLEL QUEUE] No option chain for {symbol}, skipping")
                            continue

                        # Get spot price
                        spot_price = self.get_spot_price(symbol)
                        if not spot_price:
                            logger.debug(f"[PARALLEL QUEUE] No spot price for {symbol}, skipping")
                            continue

                        # Get PCR and buildup
                        pcr, buildup_pattern = self.get_pcr_and_buildup(option_chain)

                        # Simple scoring for queue collection
                        score = 0
                        direction = None

                        if pcr > 1.2 and buildup_pattern == "LONG_BUILDUP":
                            direction = "PUT"
                            score = 70
                        elif pcr < 0.8 and buildup_pattern == "LONG_BUILDUP":
                            direction = "CALL"
                            score = 70

                        if score >= 70 and direction:
                            # Get option price
                            option_price, expiry, _ = self.get_option_price(symbol, spot_price, direction, None, option_chain)

                            if option_price and option_price > 0:
                                opportunity = {
                                    'symbol': symbol,
                                    'strike': int(spot_price),
                                    'direction': direction,
                                    'option_price': option_price,
                                    'score': score,
                                    'timestamp': time.time()
                                }
                                collected_opportunities.append(opportunity)
                                logger.debug(f"[PARALLEL QUEUE] Collected {symbol} (Score: {score}/100)")

                    except Exception as e:
                        logger.error(f"[PARALLEL QUEUE] Error processing {symbol}: {e}")
                        continue

                # Thread-safe storage with size limit
                if collected_opportunities:
                    with self.parallel_queue_lock:
                        # Enforce max size limit
                        current_size = len(self.parallel_queue_results)
                        if current_size < max_queue_size:
                            # Add only up to the limit
                            available_slots = max_queue_size - current_size
                            opportunities_to_add = collected_opportunities[:available_slots]
                            self.parallel_queue_results.extend(opportunities_to_add)
                            logger.info(f"[PARALLEL QUEUE] Added {len(opportunities_to_add)} opportunities to shared results (Total: {len(self.parallel_queue_results)}/{max_queue_size})")
                        else:
                            logger.debug(f"[PARALLEL QUEUE] Shared results full ({current_size}/{max_queue_size}), skipping this cycle")

                # Rate limiting - wait before next cycle
                time.sleep(10)

            except Exception as e:
                logger.error(f"[PARALLEL QUEUE] Error in collection loop: {e}")
                import traceback
                logger.error(f"[PARALLEL QUEUE] Traceback: {traceback.format_exc()}")
                time.sleep(10)
                continue

        if loop_count >= max_loops:
            logger.warning(f"[PARALLEL QUEUE] Fail-safe triggered: reached max loop count ({max_loops}), stopping collection")
        else:
            logger.info(f"[PARALLEL QUEUE] Trade no longer active, stopping continuous collection")

    def parallel_queue_collection_with_result(self, symbols_to_process, executed_symbol):
        """
        Wrapper for parallel_queue_collection that runs continuous collection.
        This method is called by the parallel thread and handles flag reset on completion.

        Args:
            symbols_to_process: List of symbols to analyze
            executed_symbol: Symbol that was already executed (skip this one)
        """
        try:
            # Call the continuous collection method (stores results internally)
            self.parallel_queue_collection(symbols_to_process, executed_symbol)

        except Exception as e:
            logger.error(f"[PARALLEL QUEUE] Error in parallel_queue_collection_with_result: {e}")
            import traceback
            logger.error(f"[PARALLEL QUEUE] Traceback: {traceback.format_exc()}")
        finally:
            # Reset flag and thread reference when thread completes (trade closed or error)
            self.parallel_queue_active = False
            self.parallel_thread = None
            logger.info(f"[PARALLEL QUEUE] Background queue collection thread completed, reset parallel_queue_active flag and thread reference")

    def get_pcr_and_buildup(self, option_chain):
        """
        Calculate PCR and determine buildup pattern from option chain.
        Used by queue collection methods.

        Args:
            option_chain: Option chain data

        Returns:
            (pcr, buildup_pattern) tuple
        """
        try:
            # Calculate PCR
            total_ce_oi = sum(opt.get('oi', 0) for opt in option_chain if opt.get('type') == 'CE')
            total_pe_oi = sum(opt.get('oi', 0) for opt in option_chain if opt.get('type') == 'PE')
            if total_ce_oi > 0:
                pcr = total_pe_oi / total_ce_oi
            else:
                pcr = 0.5

            # Determine buildup pattern (simplified)
            # In a real implementation, this would compare current OI with previous OI
            buildup_pattern = "NEUTRAL"  # Default

            return pcr, buildup_pattern
        except Exception as e:
            logger.warning(f"Error calculating PCR and buildup: {e}")
            return 0.5, "NEUTRAL"

    def calculate_pcr(self, option_chain):
        """Calculate PCR from option chain."""
        try:
            total_ce_oi = sum(opt.get('oi', 0) for opt in option_chain if opt.get('type') == 'CE')
            total_pe_oi = sum(opt.get('oi', 0) for opt in option_chain if opt.get('type') == 'PE')
            if total_ce_oi > 0:
                return total_pe_oi / total_ce_oi
            return 0.5
        except Exception as e:
            logger.warning(f"Error calculating PCR: {e}")
            return 0.5

    def calculate_score(self, pcr, execution_decision):
        """Calculate score from PCR and execution decision."""
        try:
            base_score = 50
            pcr_score = (pcr * 20) if pcr <= 1 else (100 - pcr * 20)
            strength = execution_decision.get('strength', 0)
            score = base_score + pcr_score + strength
            return min(100, max(0, score))
        except Exception as e:
            logger.warning(f"Error calculating score: {e}")
            return 50

    def select_best_strike(self):
        """Select the best strike using Strike Selector Service (Professional-grade selection)"""
        # CRITICAL: Increment execution ID to prevent stale thread results
        self._increment_execution_id()
        logger.debug(f"[THREAD MONITOR] Starting select_best_strike - Active threads: {threading.active_count()}, Execution ID: {self._get_current_execution_id()}")
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

        # FIX: Collect all EXECUTE opportunities for global selection
        execute_opportunities = []

        # CRITICAL FIX: Add execution_done flag for immediate execution (>=80)
        execution_done = False

        # CRITICAL FIX: Add parallel_queue_active flag to skip main thread queue collection
        parallel_queue_active = False

        # CRITICAL FIX: Add quality tracking for tiered selection
        best_candidate = None  # Track best 75-79
        best_candidate_score = 0
        HIGH_CONF_THRESHOLD = 80  # High-confidence threshold (immediate execution)

        logger.info(f"Selecting best opportunity with current capital: Rs.{self.current_capital:.2f}")
        logger.info("Using Strike Selector Service - Professional expiry & liquidity selection")
        logger.info(f"[SYMBOL PROCESSING] Starting evaluation for {len(instruments)} symbols: {list(instruments)}")

        processed_count = 0
        skipped_count = 0
        skipped_symbols = []

        # CRITICAL FIX: HARD LOCK - Monitor-ONLY mode during active trade
        # When trade is active, skip all symbol processing and API calls
        # Only monitor thread runs, ensuring clean execution flow
        if self.trade_active:
            logger.debug("[MODE] MONITOR ONLY - Trade active, skipping symbol loop")
            logger.debug("[MODE] Parallel queue collection may still be running")
            time.sleep(1)
            return None  # Skip entire symbol loop

        for symbol in instruments:
            print(f"Processing {symbol}...")
            logger.info(f"[LOOP START] Processing symbol: {symbol}")
            try:
                # CRITICAL FIX: Token resolution validation BEFORE processing
                # Check if we can resolve the symbol to an instrument token
                instrument_token = None
                try:
                    # Try to get token from WebSocket client
                    if hasattr(self.ws_client, 'get_token'):
                        instrument_token = self.ws_client.get_token(symbol)
                    
                    # Try alternative token resolution methods
                    if not instrument_token:
                        # Try to get from instruments cache
                        if hasattr(self, 'instruments_cache') and symbol in self.instruments_cache:
                            instrument_token = self.instruments_cache[symbol].get('instrument_token')
                    
                    # Try to get from kite client instruments
                    if not instrument_token and hasattr(self.kite_client, 'instruments'):
                        for instrument in self.kite_client.instruments:
                            if instrument.get('tradingsymbol') == symbol or instrument.get('name') == symbol:
                                instrument_token = instrument.get('instrument_token')
                                break
                except Exception as e:
                    logger.error(f"[TOKEN RESOLUTION] Error resolving token for {symbol}: {e}")
                
                if not instrument_token:
                    logger.error(f"[TOKEN RESOLUTION] CRITICAL: Could not resolve instrument token for {symbol} - BLOCKING symbol")
                    skipped_count += 1
                    skipped_symbols.append(f"{symbol} (no token)")
                    continue  # Block symbol completely if token cannot be resolved
                
                logger.info(f"[TOKEN RESOLUTION] {symbol} -> Token: {instrument_token}")
                
                # Check cooldown before processing symbol (prevent repeated rejected symbols)
                if self.is_symbol_in_cooldown(symbol):
                    logger.info(f"[TICK COOLDOWN] Skipping {symbol} - in rejection cooldown")
                    skipped_count += 1
                    skipped_symbols.append(f"{symbol} (cooldown)")
                    continue
                
                spot_price = self.get_spot_price(symbol, bypass_cache=False)  # Use WebSocket data
                if spot_price == 0:
                    logger.warning(f"[PRICE CHECK] {symbol} spot price is 0 - skipping")
                    skipped_count += 1
                    skipped_symbols.append(f"{symbol} (price=0)")
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
                logger.info(f"[PIPELINE] {symbol} - Fetching option chain from API...")
                option_chain = self.get_real_option_chain(symbol, spot_price)
                
                if not option_chain:
                    logger.warning(f"[PIPELINE SKIP] {symbol} - No real option chain data from API")
                    skipped_count += 1
                    skipped_symbols.append(f"{symbol} (no option chain)")
                    continue
                logger.info(f"[PIPELINE] {symbol} - Option chain fetched successfully")

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
                logger.debug(f"[DEBUG INST WALLS] About to call calculate_institutional_walls for {symbol}")
                
                # CRITICAL FIX: Use multiprocessing timeout wrapper (1 second execution guard)
                institutional_data = self.safe_calculate_institutional_walls(option_chain_data, spot_price, symbol, timeout=2)
                logger.debug(f"[DEBUG INST WALLS] calculate_institutional_walls returned for {symbol}")
                
                if "error" in institutional_data:
                    logger.warning(f"[PIPELINE SKIP] {symbol} - Could not calculate institutional walls")
                    skipped_count += 1
                    skipped_symbols.append(f"{symbol} (inst walls error)")
                    continue
                logger.info(f"[PIPELINE] {symbol} - Institutional walls calculated: Support {institutional_data.get('support', {}).get('strike', 0)}, Resistance {institutional_data.get('resistance', {}).get('strike', 0)}")
                
                processed_count += 1
                
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
                    logger.warning(f"[PIPELINE SKIP] {symbol} - Market Analyzer Service not available")
                    continue
                
                logger.info(f"[PIPELINE] {symbol} - Running market analysis...")
                logger.info(f"[ENTRY] market_analyzer_service.analyze_market({symbol})")
                market_analysis = self.market_analyzer_service.analyze_market(
                    symbol=symbol,
                    spot_price=spot_price,
                    vwap=vwap,
                    price_change=price_change,
                    delta_oi=delta_oi,
                    pcr=pcr,
                    option_chain={"strikes": [
                        {  # CRITICAL FIX: Preserve complete instrument data including instrument_token and tradingsymbol
                            "strike": item.get('strike'),
                            "oi": item.get('oi', 0),  # Upstox uses 'oi'
                            "instrument_token": item.get('instrument_token'),
                            "tradingsymbol": item.get('tradingsymbol'),
                            "type": item.get('type'),
                            "expiry": item.get('expiry'),
                            "last_price": item.get('last_price')
                        }
                        for item in option_chain
                    ]}
                )
                logger.info(f"[EXIT] market_analyzer_service.analyze_market({symbol}) returned")
                logger.info(f"[PIPELINE] {symbol} - Market analysis complete: Strength {market_analysis.get('market_analysis', {}).get('market_strength', 0)}")
                
                # Breakout Entry Service
                if spot_price > vwap and price_change > 0:
                    breakout = "BULLISH"
                elif spot_price < vwap and price_change < 0:
                    breakout = "BEARISH"
                else:
                    breakout = "NONE"
                
                # DEBUG: Log breakout conditions
                logger.debug(f"[DEBUG] {symbol} - Spot: {spot_price}, VWAP: {vwap}, Change: {price_change}, Breakout: {breakout}")
                
                if market_analysis['market_analysis']['market_strength'] >= 3:
                    strength = "STRONG"
                elif market_analysis['market_analysis']['market_strength'] >= 2:
                    strength = "MODERATE"
                else:
                    strength = "WEAK"
                
                # DEBUG: Log market strength
                logger.debug(f"[DEBUG] {symbol} - Market Strength: {market_analysis['market_analysis']['market_strength']} ({strength})")
                
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
                logger.info(f"[PIPELINE] {symbol} - Trend Bias: {trend_bias}, Direction: {direction}, Breakout: {breakout}")
                
                if not direction:
                    logger.warning(f"[PIPELINE SKIP] {symbol} - No clear direction determined (Bias: {trend_bias}, Breakout: {breakout})")
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
                    logger.debug(f"[DEBUG] Passing option chain to SmartStrike: {len(option_chain)} contracts")
                    if option_chain and len(option_chain) > 0:
                        logger.debug(f"[DEBUG] Sample option chain item: {option_chain[0]}")
                        logger.debug(f"[DEBUG] Option chain has instrument_token: {'instrument_token' in option_chain[0]}")
                        logger.debug(f"[DEBUG] Option chain has tradingsymbol: {'tradingsymbol' in option_chain[0]}")
                    
                    logger.info(f"[ENTRY] smart_strike_service.select_strike_complete({symbol})")
                    try:
                        strike_selection = self.smart_strike_service.select_strike_complete(
                            instruments=[],  # Not needed for expiry selection (API already filtered)
                            symbol=symbol,
                            option_chain=option_chain,
                            spot=spot_price,
                            signal=direction,
                            optionstar_data=institutional_data,
                            confidence_score=execution_decision.get('score', 75)  # Use execution decision score
                        )
                    except Exception as e:
                        logger.error(f"{symbol}: Smart Strike raised exception: {e}")
                        logger.warning(f"{symbol}: Using ATM fallback due to Smart Strike error")
                        # Calculate ATM strike as fallback
                        atm_strike = self.calculate_atm_strike(symbol, spot_price)
                        logger.info(f"{symbol}: ATM strike: {atm_strike}")

                        # Find ATM contract from option chain
                        if option_chain:
                            direction_type = "CE" if direction == "CALL" else "PE"
                            atm_contract = None
                            for opt in option_chain:
                                if (opt.get('strike') == atm_strike and
                                    opt.get('type') == direction_type):
                                    atm_contract = opt
                                    break

                            if atm_contract:
                                logger.info(f"{symbol}: Found ATM contract: {atm_contract.get('tradingsymbol')}")
                                strike_selection = {
                                    'strike': atm_strike,
                                    'selected_contract': atm_contract,
                                    'fallback': True
                                }
                                # CRITICAL FIX: Log execution proceeding after fallback
                                logger.info(f"[EXECUTION] {symbol}: Proceeding with strike: {atm_strike} {direction_type} after Smart Strike fallback")
                            else:
                                logger.error(f"{symbol}: ATM contract not found for {atm_strike} {direction_type}")
                                # CRITICAL FIX: Fail instead of using invalid fallback contract
                                raise Exception(f"CRITICAL: Cannot find valid ATM contract for {symbol} {direction_type}")
                        else:
                            logger.error(f"{symbol}: No option chain for ATM fallback")
                            continue

                if not strike_selection:
                    logger.warning(f"{symbol}: No valid strike selection available, skipping")
                    continue

                # CRITICAL FIX: Extract selected_contract - Smart Strike now raises exception if missing
                selected_contract = strike_selection.get('selected_contract', None)

                # CRITICAL FIX: Validate selected_contract has instrument_token (including fallback cases)
                if not selected_contract or not selected_contract.get('instrument_token'):
                    raise Exception(f"CRITICAL: selected_contract missing instrument_token for {symbol}. Strike selection: {strike_selection}")

                if not selected_contract.get('tradingsymbol'):
                    raise Exception(f"CRITICAL: selected_contract missing tradingsymbol for {symbol}. Contract: {selected_contract}")
                
                # Get optimized strike from single call
                elite_strike = strike_selection['strike']  # Already optimized
                # FIX: Don't expect lot_size from smart strike - get from config
                elite_lot = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                selected_expiry = strike_selection.get('expiry', None)

                logger.info(f"[SMART STRIKE] Optimized result: {elite_strike}, Lot: {elite_lot}, Shifted: {strike_selection.get('shifted', False)}")
                
                # CRITICAL FIX: Log execution proceeding after Smart Strike selection
                if strike_selection.get('fallback'):
                    logger.info(f"[EXECUTION] {symbol}: Proceeding with strike: {elite_strike} after Smart Strike fallback")
                else:
                    logger.info(f"[EXECUTION] {symbol}: Proceeding with strike: {elite_strike} after Smart Strike selection")
                
                # Parse the optimized strike
                strike_price = int(elite_strike.split()[0])
                direction_formatted = "CE" if direction == "CALL" else "PE"
                
                # CRITICAL FIX: Use selected_contract directly if available, otherwise find matching contract
                if selected_contract:
                    # CRITICAL FIX: Validate CE/PE consistency before using selected_contract
                    contract_type = selected_contract.get('type', selected_contract.get('instrument_type', ''))
                    expected_type = "CE" if direction == "CALL" else "PE"
                    
                    logger.info(f"[CE/PE VALIDATION] Direction: {direction} -> Expected type: {expected_type}")
                    logger.info(f"[CE/PE VALIDATION] selected_contract type: {contract_type}")
                    logger.info(f"[CE/PE VALIDATION] selected_contract tradingsymbol: {selected_contract.get('tradingsymbol', 'N/A')}")
                    
                    # CRITICAL FIX: Check both type field AND tradingsymbol suffix
                    type_mismatch = contract_type != expected_type
                    tradingsymbol_mismatch = False
                    if selected_contract.get('tradingsymbol'):
                        contract_tradingsymbol = selected_contract.get('tradingsymbol', '')
                        tradingsymbol_mismatch = not contract_tradingsymbol.endswith(expected_type)
                    
                    if type_mismatch or tradingsymbol_mismatch:
                        logger.error(f"[CRITICAL] CE/PE MISMATCH DETECTED!")
                        logger.error(f"[CRITICAL] Direction: {direction} (Expected: {expected_type})")
                        logger.error(f"[CRITICAL] selected_contract type: {contract_type}")
                        logger.error(f"[CRITICAL] selected_contract tradingsymbol: {selected_contract.get('tradingsymbol', '')}")
                        logger.error(f"[CRITICAL] Type mismatch: {type_mismatch}, Tradingsymbol mismatch: {tradingsymbol_mismatch}")
                        
                        # CRITICAL FIX: Find correct contract instead of using mismatched one
                        logger.warning(f"[CRITICAL] Searching for correct {expected_type} contract in option chain...")
                        elite_matching_option = None
                        for opt in option_chain:
                            if (opt.get('strike') == strike_price and
                                opt.get('type') == expected_type and
                                opt.get('name') == symbol):
                                elite_matching_option = opt
                                break
                        
                        if elite_matching_option:
                            selected_contract = elite_matching_option
                            logger.info(f"[CRITICAL FIX] Found correct {expected_type} contract: {elite_matching_option.get('tradingsymbol')}")
                        else:
                            logger.error(f"[CRITICAL] No {expected_type} contract found for {symbol} {strike_price}")
                            continue
                    
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
                # selected_contract is already validated at source (lines 2182-2191)
                if selected_contract:
                    instrument_token = selected_contract.get('instrument_token') or selected_contract.get('instrument_key')  # FIX: Fallback to instrument_key
                    tradingsymbol = selected_contract.get('tradingsymbol', '')
                    contract_expiry = selected_contract.get('expiry')

                    # DEBUG: Log what we received from Smart Strike
                    logger.debug(f"[DEBUG] selected_contract from Smart Strike: {selected_contract}")

                    # FIX: Initialize option_price to prevent reference errors
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
                            logger.warning(f"[PERF] Price not available from WebSocket - using REST API fallback")
                            # CRITICAL FIX: Use REST API fallback instead of skipping
                            try:
                                tradingsymbol = selected_contract.get('tradingsymbol', '')
                                if tradingsymbol:
                                    self._rate_limit_guard()
                                    quote = self.kite_client.quote([f"NFO:{tradingsymbol}"])
                                    if quote and f"NFO:{tradingsymbol}" in quote:
                                        option_price = quote[f"NFO:{tradingsymbol}"].get("last_price")
                                        if option_price and option_price > 0:
                                            logger.info(f"[REST FALLBACK] Got option price from REST API: {option_price}")
                                            expiry = contract_expiry
                                        else:
                                            logger.warning(f"[REST FALLBACK] REST API returned invalid price: {option_price}")
                                            option_price = None
                                    else:
                                        logger.warning(f"[REST FALLBACK] REST API quote failed for {tradingsymbol}")
                                        option_price = None
                                else:
                                    logger.warning(f"[REST FALLBACK] No tradingsymbol available for REST fallback")
                                    option_price = None
                            except Exception as e:
                                logger.error(f"[REST FALLBACK] Failed to get option price from REST API: {e}")
                                option_price = None
                else:
                    # Fallback to old method if selected_contract not available
                    logger.warning("Selected contract not available, using fallback method")
                    option_price, expiry, _ = self.get_option_price(symbol, strike_price, direction, selected_expiry, option_chain)

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
                    logger.debug(f"[DEBUG] Sending entry_price to ExecutionBrain: {option_price}")
                    
                    # FIX: Calculate OI bias from FULL option chain (not just support/resistance)
                    total_ce_oi = 0
                    total_pe_oi = 0
                    for strike_data in option_chain:
                        if strike_data.get('type') == 'CE':
                            total_ce_oi += strike_data.get('oi', 0)
                        elif strike_data.get('type') == 'PE':
                            total_pe_oi += strike_data.get('oi', 0)
                    
                    # Calculate OI bias: +1 for bullish (PE > CE), -1 for bearish (CE > PE), 0 for neutral
                    if total_pe_oi > total_ce_oi:
                        oi_bias = 1  # Bullish - more PE OI
                    elif total_ce_oi > total_pe_oi:
                        oi_bias = -1  # Bearish - more CE OI
                    else:
                        oi_bias = 0  # Neutral - equal OI
                    
                    logger.info(f"[OI BIAS] Total CE OI: {total_ce_oi}, Total PE OI: {total_pe_oi}, Bias: {oi_bias}")
                    
                    # FIX: Construct oi_signal with PCR and OI bias (from full chain, not just support/resistance)
                    market_data = market_analysis.get("market_analysis", {})
                    oi_signal = {
                        "pcr": market_data.get("pcr", 0),
                        "oi_gap": market_data.get("oi_analysis", {}).get("oi_gap", 0),  # Keep old gap for backward compatibility
                        "oi_bias": oi_bias,  # NEW: Actual OI bias from full chain
                        "total_ce_oi": total_ce_oi,  # NEW: Full chain CE OI
                        "total_pe_oi": total_pe_oi   # NEW: Full chain PE OI
                    }
                    
                    # FIX: Construct bias dictionary with trend_bias and market_type for Execution Brain
                    bias = {
                        "trend_bias": institutional_data.get("trend_bias", "NEUTRAL"),
                        "market_type": "TRENDING" if institutional_data.get("trend_bias") in ["BULLISH", "BEARISH"] else "SIDEWAYS"
                    }
                    
                    # FIX: Construct breakout dictionary with direction and strength for Execution Brain
                    breakout_dict = {
                        "direction": breakout,
                        "strength": strength
                    }
                    
                    signal_package = {
                        "bias": bias,  # FIX: Pass constructed bias dictionary
                        "breakout": breakout_dict,  # FIX: Pass constructed breakout dictionary
                        "oi_signal": oi_signal,  # FIX: Pass constructed oi_signal with PCR/OI data
                        "levels": institutional_data,
                        "spot": trade_signal.get("spot_price", 0),
                        "vwap": trade_signal.get("vwap", 0),
                        "entry": trade_signal.get("entry", 0),
                        "price_history": self.state_manager.get_price_history(symbol),
                        "momentum_strength": "STRONG" if market_analysis.get('market_analysis', {}).get('market_strength', 0) >= 3 else "WEAK"
                    }
                    
                    # CRITICAL DEBUG: Log Execution Brain evaluation
                    logger.info(f"[EXECUTION BRAIN] Evaluating {symbol} - PCR: {oi_signal.get('pcr', 0):.2f}, Trend Bias: {bias.get('trend_bias', 'NEUTRAL')}, WebSocket Connected: {self.state_manager.is_websocket_connected()}")
                    logger.info(f"[ENTRY] execution_brain_service.evaluate_execution({symbol})")
                    execution_decision = self.execution_brain_service.evaluate_execution(signal_package)
                    logger.info(f"[EXIT] execution_brain_service.evaluate_execution({symbol}) returned")
                    logger.info(f"[EXECUTION RESULT] {symbol} - {execution_decision['action']} (Score: {execution_decision.get('score', 0)}/100, Reason: {execution_decision.get('reason', 'N/A')})")
                
                # Allow EXECUTE, PROBING, and LLM_REVIEW (treat LLM_REVIEW as EXECUTE for single strike trader)
                if execution_decision['action'] not in ['EXECUTE', 'PROBING', 'LLM_REVIEW']:
                    logger.info(f"[EXECUTION SKIP] {symbol} - Rejected by Execution Brain: {execution_decision['action']} (Score: {execution_decision.get('score', 0)}/100)")
                    logger.debug(f"[DEBUG SKIP] {symbol} NOT added to execute_opportunities (decision: {execution_decision['action']})")
                    continue
                
                # Treat LLM_REVIEW as EXECUTE for single strike trader
                if execution_decision['action'] == 'LLM_REVIEW':
                    logger.info(f"[PROP DESK] {symbol} LLM_REVIEW - treating as EXECUTE for single strike trader")
                    execution_decision['action'] = 'EXECUTE'

                # STRATEGY-AWARE: Extract signal_type from Execution Brain for tick confirmation
                signal_type = execution_decision.get('signal_type', 'MOMENTUM')
                trade_signal['signal_type'] = signal_type
                logger.info(f"[STRATEGY-AWARE] Signal type for {symbol}: {signal_type}")

                # NOTE: Momentum filter is now in Execution Brain Service - removed duplicate here

                # ========================================
                # CAPTURE TRADE METRICS - For performance analysis
                # ========================================
                confidence = institutional_data.get('confidence', {}).get('level', 'UNKNOWN')
                oi = institutional_data.get('support', {}).get('oi', 0) + institutional_data.get('resistance', {}).get('oi', 0)
                pcr_bias = market_analysis.get('market_analysis', {}).get('pcr_bias', 'NEUTRAL')
                
                # Calculate momentum from price change (as percentage of spot price)
                momentum = (price_change / spot_price * 100) if spot_price > 0 else 0

                self.current_trade_metrics = {
                    'confidence': confidence,
                    'oi': oi,
                    'momentum': momentum,  # Calculated from price change
                    'pcr_bias': pcr_bias,
                    'spot': spot_price,
                    'vwap': vwap
                }

                # ========================================
                # TRADE FREQUENCY CONTROL - Max 1 active trade
                # ========================================
                if self.trade_active:
                    logger.info(f"[TRADE CONTROL] {symbol} SKIP: Already have active trade ({self.current_symbol} {self.current_strike})")
                    logger.debug(f"[DEBUG SKIP TRADE] {symbol} NOT added to execute_opportunities (active trade exists)")
                    continue
                
                # ========================================
                # GET OPTION PRICE FOR OPTIMIZED STRIKE
                # ========================================
                # CRITICAL FIX: Multiple fallback strategies for option price
                option_price = None
                price_source = None  # Track data source for entry validation
                
                # Strategy 0: Check cache first (avoid repeated API calls)
                current_time = time.time()
                if instrument_token in self.option_price_cache:
                    cached_price, cache_time = self.option_price_cache[instrument_token]
                    cache_age = current_time - cache_time
                    if cache_age < self.option_price_cache_duration:
                        option_price = cached_price
                        price_source = "CACHE"
                        logger.info(f"[PRICE FETCH] Got price from cache: Rs.{option_price} (age: {cache_age:.1f}s)")
                    else:
                        logger.info(f"[PRICE FETCH] Cache expired (age: {cache_age:.1f}s), fetching fresh price")
                else:
                    logger.info(f"[PRICE FETCH] No cache hit, fetching fresh price")
                
                # Strategy 1: Try WebSocket/StateManager first (real-time)
                if not option_price:
                    logger.info(f"[PRICE FETCH] Attempting to get option price for {elite_strike} (Token: {instrument_token})")
                    ws_price = self.state_manager.get_latest_price(instrument_token)
                    if ws_price and ws_price > 0:
                        option_price = ws_price
                        price_source = "WEBSOCKET"
                        # Update cache
                        self.option_price_cache[instrument_token] = (option_price, current_time)
                        logger.info(f"[PRICE FETCH] Got price from WebSocket/StateManager: Rs.{option_price}")
                    else:
                        logger.info(f"[PRICE FETCH] WebSocket price not available, trying REST API...")
                
                # Strategy 2: Try REST API LTP fetch (rate-limited)
                if not option_price:
                    ltp_response = self.kite_client.safe_ltp_fetch([instrument_token])
                    if ltp_response and instrument_token in ltp_response:
                        price = ltp_response[instrument_token]
                        # Handle both dict and float returns
                        if isinstance(price, dict):
                            option_price = price.get('last_price', 0)
                        else:
                            option_price = price
                        price_source = "REST"
                        # Update cache
                        self.option_price_cache[instrument_token] = (option_price, current_time)
                        logger.info(f"[PRICE FETCH] Got price from REST API LTP: Rs.{option_price}")
                    else:
                        logger.warning(f"[PRICE FETCH] REST API LTP fetch failed or rate-limited")
                
                # Strategy 3: Use option chain price as fallback (already fetched)
                if not option_price:
                    logger.info(f"[PRICE FETCH] Trying option chain price as fallback...")
                    # Find the option in the option chain
                    if option_chain:
                        for opt in option_chain:
                            if opt.get('instrument_token') == instrument_token or opt.get('instrument_key') == str(instrument_token):
                                chain_price = opt.get('last_price', 0)
                                if chain_price and chain_price > 0:
                                    option_price = chain_price
                                    price_source = "OPTION_CHAIN"
                                    # Update cache
                                    self.option_price_cache[instrument_token] = (option_price, current_time)
                                    logger.info(f"[PRICE FETCH] Got price from option chain: Rs.{option_price}")
                                    break
                                else:
                                    logger.warning(f"[PRICE FETCH] Option chain price is 0 or missing")
                    else:
                        logger.warning(f"[PRICE FETCH] No option chain available for fallback")
                
                # Final validation
                if not option_price or option_price == 0:
                    logger.error(f"[PRICE FETCH] CRITICAL: Could not get option price for {tradingsymbol} (Token: {instrument_token})")
                    logger.error(f"[PRICE FETCH] All strategies failed - skipping this trade opportunity")
                    logger.debug(f"[DEBUG SKIP PRICE] {symbol} NOT added to execute_opportunities (price: {option_price})")
                    continue
                
                logger.info(f"[PRICE FETCH] Final option price for {elite_strike}: Rs.{option_price} (Source: {price_source})")
                
                # CRITICAL FIX: Log entry data source to identify stale trade selection
                # Classify as LIVE if from WebSocket/Cache, STALE if from REST/OptionChain
                if price_source == "WEBSOCKET" or price_source == "CACHE":
                    entry_source = "LIVE"
                else:
                    entry_source = "STALE"
                logger.info(f"[ENTRY DATA SOURCE] {symbol} {strike_price} {direction} | Token: {instrument_token} | Source: {entry_source} ({price_source}) | Price: Rs.{option_price}")
                if entry_source == "STALE":
                    logger.warning(f"[ENTRY DATA SOURCE WARNING] Trade entry using STALE price - WebSocket not receiving ticks for this token!")
                    logger.warning(f"[ENTRY DATA SOURCE WARNING] This trade will likely show STALE in monitor initially")
                    logger.info(f"[ENTRY DATA SOURCE] Allowing STALE entry with safeguards - WebSocket subscription will be attempted")
                    
                    # OPTIONAL: Restrict STALE entries to high OI/liquid contracts only
                    # Check OI from option_chain
                    oi = 0
                    if option_chain:
                        for opt in option_chain:
                            if opt.get('instrument_token') == instrument_token or opt.get('instrument_key') == str(instrument_token):
                                oi = opt.get('oi', 0)
                                break
                    
                    if oi > 0:
                        logger.info(f"[ENTRY DATA SOURCE] STALE entry allowed - OI: {oi} (liquid contract)")
                    else:
                        logger.warning(f"[ENTRY DATA SOURCE] STALE entry with low/zero OI: {oi} - may be illiquid")
                        # Still allow but with warning
                
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
                    logger.warning(f"[PROP DESK] {symbol} cannot afford trade - Cost: Rs.{cost_per_lot}, Capital: Rs.{self.current_capital}")
                    logger.debug(f"[DEBUG SKIP AFFORD] {symbol} NOT added to execute_opportunities (cost: Rs.{cost_per_lot}, capital: Rs.{self.current_capital})")
                    continue
                
                # Score calculation
                # SAFE CHECK: Ensure execution_decision is set before using it
                if execution_decision is None:
                    logger.warning(f"[PROP DESK] {symbol} Execution decision not set, using default score")
                    score = 50  # Default middle score
                else:
                    score = execution_decision['score']
                
                # FIX: Add to execute_opportunities instead of updating best_opportunity immediately
                logger.debug(f"[DEBUG ADD] Adding {symbol} to execute_opportunities (decision: {execution_decision['action']}, score: {execution_decision.get('score', 0)})")
                
                # CRITICAL FIX: Validate CE/PE consistency before adding to opportunities
                expected_type = "CE" if direction == "CALL" else "PE"
                if tradingsymbol:
                    # CRITICAL FIX: Check if tradingsymbol ends with expected type
                    if not tradingsymbol.endswith(expected_type):
                        logger.error(f"[CRITICAL] CE/PE MISMATCH in opportunity creation!")
                        logger.error(f"[CRITICAL] Direction: {direction} -> Expected type: {expected_type}")
                        logger.error(f"[CRITICAL] tradingsymbol: {tradingsymbol} (does not end with {expected_type})")
                        logger.error(f"[CRITICAL] tradingsymbol ends with: {tradingsymbol[-2:]}")
                        logger.error(f"[CRITICAL] selected_contract type: {selected_contract.get('type', 'N/A') if selected_contract else 'N/A'}")
                        logger.error(f"[CRITICAL] Skipping this opportunity to prevent execution error")
                        continue
                    logger.info(f"[CE/PE VALIDATION] Opportunity validated: {direction} -> {tradingsymbol} (ends with {expected_type})")
                else:
                    logger.warning(f"[CE/PE VALIDATION] tradingsymbol is None, skipping validation")
                
                execute_opportunities.append({
                    'symbol': symbol,
                    'strike': strike_price,
                    'expiry': selected_expiry,
                    'direction': direction,
                    'spot': spot_price,
                    'option_price': option_price,
                    'cost_per_lot': cost_per_lot,
                    'lot_size': self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50),
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
                    'delta_oi': delta_oi,
                    'entry_source': entry_source,  # CRITICAL: Track if entry was LIVE or STALE
                    'instrument_token': instrument_token,  # CRITICAL: Add instrument_token
                    'tradingsymbol': tradingsymbol,  # CRITICAL: Add tradingsymbol
                    'selected_contract': selected_contract  # CRITICAL: Add selected_contract
                })

                # CRITICAL FIX: HYBRID EXECUTION MODEL (speed + quality + freshness)
                # Score >= 80: Execute IMMEDIATELY (return immediately, start parallel queue collection)
                if not self.trade_active and not execution_done and score >= HIGH_CONF_THRESHOLD:
                    logger.info(f"[IMMEDIATE EXECUTION] Very strong signal: {symbol} (Score: {score}/100 >= {HIGH_CONF_THRESHOLD})")
                    # Execute immediately (create explicit opportunity)
                    best_opportunity = {
                        'symbol': symbol,
                        'strike': strike_price,  # CRITICAL FIX: Use numeric strike (not "1300 PE")
                        'direction': direction,
                        'option_price': option_price,
                        'score': score,
                        'instrument_token': instrument_token,
                        'tradingsymbol': tradingsymbol,
                        'expiry': selected_expiry,
                        'selected_contract': selected_contract,
                        'trade_signal': trade_signal,
                        'entry_source': entry_source,  # CRITICAL: Track if entry was LIVE or STALE
                        # CRITICAL FIX: Add option_chain ONLY for immediate execution (monitor needs it)
                        'option_chain': option_chain,
                        # CRITICAL FIX: Add missing fields required by execution phase
                        'pcr': pcr,
                        'buildup_pattern': execution_decision.get('buildup_pattern', 'N/A'),
                        'strength': execution_decision.get('strength', 0)
                    }
                    execution_done = True

                    logger.info(f"[IMMEDIATE EXECUTION] Executed {symbol}, RETURNING immediately")
                    return best_opportunity  # RETURN IMMEDIATELY
                # Score 75-79: Track best candidate (quality selection)
                elif score >= 75:
                    logger.info(f"[CANDIDATE TRACKING] Tracking candidate: {symbol} (Score: {score}/100)")
                    # Update best_candidate if this is better
                    if score > best_candidate_score:
                        best_candidate = {
                            'symbol': symbol,
                            'strike': strike_price,  # CRITICAL FIX: Use numeric strike (not "1300 PE")
                            'direction': direction,
                            'option_price': option_price,
                            'score': score,
                            'instrument_token': instrument_token,
                            'tradingsymbol': tradingsymbol,
                            'expiry': selected_expiry,
                            'selected_contract': selected_contract,
                            'trade_signal': trade_signal,
                            'entry_source': entry_source,  # CRITICAL: Track if entry was LIVE or STALE
                            # CRITICAL FIX: DO NOT store option_chain (memory optimization - fetch in monitor)
                            # CRITICAL FIX: Add missing fields required by execution phase
                            'pcr': pcr,
                            'buildup_pattern': execution_decision.get('buildup_pattern', 'N/A'),
                            'strength': execution_decision.get('strength', 0)
                        }
                        best_candidate_score = score
                        logger.info(f"[CANDIDATE TRACKING] New best candidate: {symbol} (Score: {score}/100)")
                    # Don't add to execute_opportunities (candidate tracking mode)
                    execute_opportunities.pop()
                # Score 70-74: Add to queue with priority (score + timestamp)
                elif score >= 70:
                    logger.info(f"[QUEUE COLLECTION] Adding {symbol} to queue (Score: {score}/100)")
                    # Add timestamp for priority sorting
                    queue_opportunity = execute_opportunities[-1].copy()
                    queue_opportunity['timestamp'] = time.time()
                    # CRITICAL FIX: DO NOT store option_chain (memory optimization - fetch in monitor)
                    # CRITICAL FIX: Add missing fields required by execution phase
                    queue_opportunity['pcr'] = pcr
                    queue_opportunity['buildup_pattern'] = execution_decision.get('buildup_pattern', 'N/A')
                    queue_opportunity['strength'] = execution_decision.get('strength', 0)
                    queue_opportunity['entry_source'] = entry_source  # CRITICAL: Track if entry was LIVE or STALE
                    self.add_to_queue(queue_opportunity)
                    # Don't add to execute_opportunities if going to queue
                    execute_opportunities.pop()
                    logger.info(f"[QUEUE COLLECTION] {symbol} added to queue with timestamp")
                # Score < 70: ignore (no redundant batch path)
                else:
                    logger.info(f"[IGNORE] {symbol} score too low ({score}/100), ignoring")
                    execute_opportunities.pop()  # Remove from execute_opportunities

                logger.info(f"[PROP DESK] EXECUTE opportunity: {symbol} {elite_strike} {direction} @ Rs.{option_price} (Score: {score}/100, Lot: {elite_lot})")

                # ARCHITECTURE FIX: HYBRID EXECUTION MODEL (speed + quality + freshness)
                # - Score >= 80: Execute IMMEDIATELY and RETURN (no queue collection)
                # - Score 75-79: Track best candidate
                # - Score 70-74: Add to queue (priority: score + timestamp)
                # - Score < 70: Ignore
                # EXECUTE best after loop (if no immediate execution)
                
                # CRITICAL FIX: Log evaluation completion for each symbol
                logger.info(f"[EVALUATION COMPLETE] {symbol} processed - PCR: {pcr:.2f}, Score: {score}/100, Direction: {direction}, Decision: {execution_decision.get('action', 'N/A')}")
                
                # DEBUG: Log opportunity creation
                logger.debug(f"[DEBUG A] Opportunity created for {symbol}: {elite_strike} {direction}")
                
                logger.info(f"[LOOP SUCCESS] {symbol} processed successfully")
                print(f"✓ {symbol} completed")
                    
            except Exception as e:
                logger.error(f"[LOOP ERROR] {symbol} failed during processing: {e}")
                import traceback
                logger.error(f"[LOOP ERROR] Traceback: {traceback.format_exc()}")
                logger.info(f"[LOOP CONTINUE] {symbol} - continuing to next symbol")
                continue

        # DEBUG: Log end of symbol loop (OUTSIDE try/except to catch unhandled exceptions)
        logger.debug(f"[DEBUG B] Symbol loop completed. execute_opportunities count: {len(execute_opportunities)}")
        logger.info(f"[LOOP COMPLETE] Symbol loop finished. Processed: {processed_count}/{len(instruments)}")
        logger.info(f"[SYMBOL PROCESSING SUMMARY] Processed: {processed_count}/{len(instruments)}, Skipped: {skipped_count}")
        if skipped_symbols:
            logger.info(f"[SYMBOL PROCESSING SUMMARY] Skipped symbols: {', '.join(skipped_symbols)}")

        # DEBUG: Log total opportunities before selection
        logger.debug(f"[DEBUG TOTAL] Total EXECUTE opportunities collected: {len(execute_opportunities)}")

        # CRITICAL FIX: HYBRID EXECUTION MODEL - After loop selection
        # 1. If execution_done == True (>=80 executed): skip
        if execution_done:
            logger.info("[IMMEDIATE EXECUTION] Very strong signal already executed, skipping after-loop selection")
        # 2. Else if best_candidate exists (75-79): execute best candidate
        elif best_candidate:
            logger.info(f"[CANDIDATE EXECUTION] Executing best candidate: {best_candidate['symbol']} (Score: {best_candidate_score}/100)")
            best_opportunity = best_candidate
        # 3. Else if queue not empty (70-74): execute best from queue (priority-based)
        elif self.trade_queue:
            logger.info(f"[QUEUE EXECUTION] No immediate execution or candidate, executing best from queue (priority-based)")
            # Priority-based sorting: score first, then timestamp (newer first)
            sorted_trades = sorted(
                self.trade_queue.values(),
                key=lambda x: (x.get('score', 0), x.get('timestamp', 0)),
                reverse=True
            )
            if sorted_trades:
                best_opportunity = sorted_trades[0]
                logger.info(f"[QUEUE EXECUTION] Selected from queue: {best_opportunity['symbol']} (Score: {best_opportunity.get('score', 0)}/100, Timestamp: {best_opportunity.get('timestamp', 0)})")
        # 4. No valid opportunity
        else:
            logger.info("[SELECTION] No valid opportunity found (no immediate execution, candidate, or queue)")
            best_opportunity = None
            # Only log warning if execute_opportunities is also empty
            if not execute_opportunities:
                logger.warning(f"[NO EXECUTE OPPORTUNITIES] No symbols returned EXECUTE decision from Execution Brain")
                logger.warning(f"[NO EXECUTE OPPORTUNITIES] All symbols were rejected or scored below threshold")
                logger.warning(f"[NO EXECUTE OPPORTUNITIES] Check individual symbol logs above for specific rejection reasons")

        if best_opportunity:
            logger.info(f"[FINAL SELECTION] Best opportunity selected: {best_opportunity['symbol']} {best_opportunity['strike']} {best_opportunity['direction']} "
                           f"(Score: {best_opportunity['score']}, PCR: {best_opportunity['pcr']:.2f}, Buildup: {best_opportunity['buildup_pattern']})")
            logger.debug(f"[DEBUG] Best opportunity details: symbol={best_opportunity['symbol']}, strike={best_opportunity['strike']}, direction={best_opportunity['direction']}, score={best_opportunity['score']}")
        else:
            logger.warning("[FINAL SELECTION] No suitable opportunity found")

        # DEBUG: Log before return
        logger.debug(f"[DEBUG C] About to return from select_best_strike(). best_opportunity: {best_opportunity['symbol'] if best_opportunity else None}")
        logger.info(f"[FINAL] Opportunities found: {len(execute_opportunities)}, Best: {best_opportunity['symbol'] if best_opportunity else 'None'}")
        logger.debug(f"[THREAD MONITOR] Ending select_best_strike - Active threads: {threading.active_count()}, Execution ID: {self._get_current_execution_id()}")
        
        if best_opportunity:
            logger.info(f"[RETURN] Returning opportunity: {best_opportunity['symbol']} {best_opportunity['strike']} {best_opportunity['direction']} @ Rs.{best_opportunity['option_price']} (Score: {best_opportunity['score']}/100)")
        else:
            logger.warning("[RETURN] No opportunity to return - best_opportunity is None")
        
        return best_opportunity

    def get_option_price(self, symbol, strike, direction, selected_expiry=None, option_chain=None, tradingsymbol=None):
        """
        Get current option price using tradingsymbol as PRIMARY key (most reliable).

        CRITICAL FIX: Use tradingsymbol matching instead of strike+type matching.
        tradingsymbol is the unique identifier and is guaranteed to match.

        Args:
            symbol: Underlying symbol
            strike: Strike price (legacy parameter, not used for matching)
            direction: CALL or PUT (legacy parameter, not used for matching)
            selected_expiry: Selected expiry date
            option_chain: Fresh option chain data (source of truth)
            tradingsymbol: Trading symbol (PRIMARY key for price lookup)

        Returns:
            (option_price, expiry, is_stale) tuple
            is_stale: True if price is from fallback (not real-time WebSocket)
        """
        try:
            # CRITICAL FIX: tradingsymbol is REQUIRED for reliable price lookup
            if not tradingsymbol:
                logger.warning("[PRICE LOOKUP] No tradingsymbol provided - cannot perform reliable lookup")
                # Fallback: Try to find by strike+type (unreliable)
                if not option_chain:
                    logger.warning("[PRICE LOOKUP] No option chain provided for fallback lookup")
                    return None, None, True

                direction_formatted = "CE" if direction == "CALL" else "PE"
                logger.info(f"[PRICE LOOKUP] Attempting fallback: strike={strike}, type={direction_formatted}, symbol={symbol}")

                matching_option = None
                for opt in option_chain:
                    if (opt.get('strike') == strike and
                        opt.get('type') == direction_formatted and
                        opt.get('name') == symbol):
                        matching_option = opt
                        break

                if not matching_option:
                    logger.warning(f"[PRICE LOOKUP] Fallback failed - no matching option found for {symbol} {strike} {direction_formatted}")
                    return None, None, True

                tradingsymbol = matching_option.get('tradingsymbol', '')
                logger.info(f"[PRICE LOOKUP] Fallback succeeded - found tradingsymbol: {tradingsymbol}")

            # CRITICAL FIX: Use tradingsymbol as PRIMARY key for matching
            logger.info(f"[PRICE LOOKUP] Using tradingsymbol as PRIMARY key: {tradingsymbol}")

            # Build token map from option chain (for instrument_token lookup)
            instrument_token = None
            map_expiry = None

            if option_chain:
                # DEBUG LOGS: Show available tradingsymbols for debugging
                available_symbols = [opt.get('tradingsymbol', '') for opt in option_chain[:10]]
                logger.info(f"[PRICE LOOKUP DEBUG] Looking for: {tradingsymbol}")
                logger.info(f"[PRICE LOOKUP DEBUG] Available symbols (first 10): {available_symbols}")

                # Find matching option by tradingsymbol (PRIMARY KEY)
                matching_option = None
                for opt in option_chain:
                    if opt.get('tradingsymbol') == tradingsymbol:
                        matching_option = opt
                        break

                if not matching_option:
                    logger.warning(f"[PRICE LOOKUP] No matching tradingsymbol found in option chain: {tradingsymbol}")
                    logger.warning(f"[PRICE LOOKUP] This indicates a data inconsistency - tradingsymbol not in option chain")
                    return None, None

                # Extract instrument_token and expiry from matching option
                instrument_token = matching_option.get('instrument_token') or matching_option.get('instrument_key')
                map_expiry = matching_option.get('expiry')
                logger.info(f"[PRICE LOOKUP] Found matching option: Token={instrument_token}, Expiry={map_expiry}")

                # Validate expiry matches selected expiry
                if selected_expiry and selected_expiry != "N/A":
                    if map_expiry != selected_expiry:
                        logger.warning(f"[PRICE LOOKUP] Expiry note: Chain has {map_expiry}, selected {selected_expiry}")
                    else:
                        logger.info(f"[PRICE LOOKUP] Expiry MATCHED: {map_expiry} == {selected_expiry}")
                else:
                    logger.info(f"[PRICE LOOKUP] Using expiry from option chain: {map_expiry}")
            else:
                logger.warning("[PRICE LOOKUP] No option chain provided - cannot get instrument_token")
                return None, None

            # CRITICAL FIX: Multiple fallback strategies for option price
            option_price = None
            is_stale = False  # Track if price is from fallback (not real-time WebSocket)

            # Strategy 1: Try WebSocket/StateManager first (real-time)
            logger.info(f"[PRICE FETCH] Trying WebSocket for {tradingsymbol} (Token: {instrument_token})")
            ws_price = self.state_manager.get_latest_price(instrument_token)
            if ws_price and ws_price > 0:
                option_price = ws_price
                is_stale = False  # WebSocket price is fresh
                logger.info(f"[PRICE FETCH] Got price from WebSocket: Rs.{option_price}")
            else:
                logger.info(f"[PRICE FETCH] WebSocket not available, trying REST...")

            # Strategy 2: Try REST API LTP fetch (rate-limited)
            if not option_price:
                ltp_response = self.kite_client.safe_ltp_fetch([instrument_token])
                if ltp_response and instrument_token in ltp_response:
                    price = ltp_response[instrument_token]
                    # Handle both dict and float returns
                    if isinstance(price, dict):
                        option_price = price.get('last_price', 0)
                    else:
                        option_price = price
                    is_stale = True  # REST API is not real-time
                    logger.info(f"[PRICE FETCH] Got price from REST API: Rs.{option_price}")
                else:
                    logger.warning(f"[PRICE FETCH] REST API LTP failed or rate-limited")

            # Strategy 3: Use option chain price as fallback (already fetched)
            if not option_price:
                logger.info(f"[PRICE FETCH] Using option chain price as fallback")
                logger.warning(f"[MONITOR WARNING] Using STALE fallback price (WS missing) - option_chain")
                chain_price = matching_option.get('last_price', 0)
                if chain_price and chain_price > 0:
                    option_price = chain_price
                    is_stale = True  # Option chain is stale
                    logger.info(f"[PRICE FETCH] Got price from option chain: Rs.{option_price}")
                else:
                    logger.warning(f"[PRICE FETCH] Option chain price not available")

            # Strategy 4: ABSOLUTE LAST RESORT - Use entry price if available (prevents blocking)
            # This ensures monitor NEVER blocks waiting for WebSocket tick
            if not option_price and hasattr(self, 'entry_price') and self.entry_price:
                logger.warning(f"[PRICE FETCH] ABSOLUTE FALLBACK - Using entry price: Rs.{self.entry_price}")
                logger.warning(f"[MONITOR WARNING] Using STALE fallback price (WS missing) - entry_price")
                logger.warning(f"[PRICE FETCH] This should only happen if all data sources fail")
                option_price = self.entry_price
                is_stale = True  # Entry price is stale

            if not option_price:
                logger.error(f"[PRICE LOOKUP] All price lookup strategies failed for {tradingsymbol}")
                logger.error(f"[PRICE LOOKUP] CRITICAL: Monitor cannot function without price data")
                logger.error(f"[PRICE LOOKUP] This should never happen if option_chain is provided")
                return None, None, True

            logger.info(f"[PRICE LOOKUP SUCCESS] Price for {tradingsymbol}: Rs.{option_price} (Stale: {is_stale})")
            return option_price, map_expiry, is_stale

        except Exception as e:
            logger.error(f"[PRICE LOOKUP] Error in get_option_price: {e}")
            import traceback
            logger.error(f"[PRICE LOOKUP] Traceback: {traceback.format_exc()}")
            return None, None, True

    def execute_trade(self, symbol, strike, direction, option_price=None, trade_signal=None, option_chain=None, selected_contract=None, instrument_token=None, tradingsymbol=None):
        """Execute a trade on the selected strike using engine signal for target/stop-loss"""
        # DEBUG: Log entry into execute_trade
        logger.debug(f"[DEBUG G] execute_trade() ENTERED for {symbol} {strike} {direction}")
        
        try:
            # CRITICAL VALIDATION: Ensure selected_contract has required data
            if selected_contract:
                if not selected_contract.get('tradingsymbol'):
                    logger.error(f"[EXECUTION VALIDATION] selected_contract missing tradingsymbol for {symbol}")
                    logger.error(f"[EXECUTION VALIDATION] Contract data: {selected_contract}")
                    return False
                if not selected_contract.get('instrument_token'):
                    logger.error(f"[EXECUTION VALIDATION] selected_contract missing instrument_token for {symbol}")
                    logger.error(f"[EXECUTION VALIDATION] Contract data: {selected_contract}")
                    return False
            
            # CRITICAL VALIDATION: Ensure tradingsymbol is available
            if not tradingsymbol and selected_contract:
                tradingsymbol = selected_contract.get('tradingsymbol')
            if not tradingsymbol:
                logger.error(f"[EXECUTION VALIDATION] No tradingsymbol available for {symbol}")
                return False
            
            # CRITICAL VALIDATION: Ensure instrument_token is available
            if not instrument_token and selected_contract:
                instrument_token = selected_contract.get('instrument_token')
            if not instrument_token:
                logger.error(f"[EXECUTION VALIDATION] No instrument_token available for {symbol}")
                return False
            
            # UNIVERSAL RISK MANAGER CHECK (NEW - for all markets)
            if not can_execute_trade():
                logger.warning("UNIVERSAL RISK MANAGER BLOCKED TRADE - Trading stopped")
                return False

            # Extract expiry from trade_signal if available
            selected_expiry = trade_signal.get('expiry') if trade_signal else None

            # Get option price and expiry if not provided
            if not option_price:
                # CRITICAL FIX: Pass option_chain for single source of truth
                option_price, expiry, _ = self.get_option_price(symbol, strike, direction, selected_expiry, option_chain)
                # CRITICAL FIX: Check for None price
                if option_price is None or option_price == 0:
                    logger.error(f"Could not get valid option price for {symbol} {strike} {direction} (price: {option_price})")
                    return False
            else:
                # If option_price is provided, still get expiry with validation using option_chain
                _, expiry, _ = self.get_option_price(symbol, strike, direction, selected_expiry, option_chain)

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

            logger.info(f"Position sizing: {actual_lots} lot(s) @ Rs.{cost_per_lot}/lot = Rs.{total_cost} total")
            logger.info(f"Lot size: {lot_size_from_risk}, Total quantity: {actual_lots * lot_size_from_risk}")
            logger.info(f"Risk precision: Actual Rs.{position_calc.get('actual_risk', 0):.2f} vs Desired Rs.{position_calc.get('desired_risk', 0):.2f} ({position_calc.get('risk_utilization', 0):.1f}%)")

            # Recalculate risk parameters with actual lots
            risk_params = self.risk_service.calculate_risk_parameters(option_price, actual_lots, direction, self.current_capital, symbol)

            if not risk_params.get("success"):
                logger.error(f"Risk parameter calculation failed: {risk_params.get('error')}")
                return False

            self.stoploss_price = risk_params["stoploss_price"]
            self.target_price = risk_params["target_price"]
            risk_amount = risk_params["risk_amount"]

            logger.info(f"Risk parameters: SL Rs.{self.stoploss_price}, Target Rs.{self.target_price}, Risk Rs.{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.1%})")

            # Set trade state
            self.current_symbol = symbol
            self.current_strike = strike
            self.current_direction = direction
            self.current_expiry = expiry
            self.current_tradingsymbol = tradingsymbol  # CRITICAL FIX: Store tradingsymbol for reliable price lookup
            self.entry_price = option_price
            self.actual_lots = actual_lots
            self.entry_time = time.time()  # Capture entry time for duration analysis
            
            # Clear cooldown for this symbol (successful execution)
            if symbol in self.tick_rejected_symbols:
                del self.tick_rejected_symbols[symbol]
                logger.info(f"[TICK COOLDOWN] Cleared cooldown for {symbol} - trade executed successfully")

            # CRITICAL FIX: Use instrument_token and tradingsymbol from opportunity - DO NOT recompute
            # Priority 1: Use provided instrument_token from opportunity
            if instrument_token is None:
                logger.error(f"[CRITICAL] Instrument token is None - cannot execute trade without proper instrument mapping")
                logger.error(f"[CRITICAL] Symbol: {symbol}, Strike: {strike}, Direction: {direction}")
                return False

            # CRITICAL FIX: Validate CE/PE consistency in tradingsymbol
            expected_type = "CE" if direction == "CALL" else "PE"
            logger.info(f"[CE/PE VALIDATION] Checking: direction={direction}, expected_type={expected_type}, tradingsymbol={tradingsymbol}")
            
            if tradingsymbol:
                # CRITICAL FIX: Check both start and end of tradingsymbol
                # Tradingsymbol format: SYMBOL26JUNSTRIKECE or SYMBOL26JUNSTRIKEPE
                # Check if it ends with the expected type
                if not tradingsymbol.endswith(expected_type):
                    logger.error(f"[CRITICAL] CE/PE MISMATCH in tradingsymbol!")
                    logger.error(f"[CRITICAL] Direction: {direction} -> Expected type: {expected_type}")
                    logger.error(f"[CRITICAL] tradingsymbol: {tradingsymbol} (does not end with {expected_type})")
                    logger.error(f"[CRITICAL] tradingsymbol ends with: {tradingsymbol[-2:]}")
                    logger.error(f"[CRITICAL] Symbol: {symbol}, Strike: {strike}")
                    return False
                logger.info(f"[CE/PE VALIDATION] tradingsymbol matches direction: {tradingsymbol} (ends with {expected_type})")
            else:
                logger.warning(f"[CE/PE VALIDATION] tradingsymbol is None, skipping validation")

            # Priority 2: Use provided tradingsymbol from opportunity
            if tradingsymbol is None and selected_contract:
                tradingsymbol = selected_contract.get('tradingsymbol', '')
                logger.debug(f"[UI UPDATE] Using tradingsymbol from selected_contract: {tradingsymbol}")

            # CRITICAL VALIDATION: Ensure instrument_token is valid
            if not instrument_token or instrument_token == 0:
                logger.error(f"[CRITICAL] Instrument token is invalid: {instrument_token}")
                logger.error(f"[CRITICAL] Symbol: {symbol}, Strike: {strike}, Direction: {direction}")
                return False

            logger.debug(f"[UI UPDATE] Using instrument_token from opportunity: {instrument_token}")

            # CRITICAL FIX: Ensure expiry is not None
            if expiry is None and selected_contract:
                expiry = selected_contract.get('expiry')
                logger.debug(f"[UI UPDATE] Using expiry from selected_contract: {expiry}")

            if expiry is None or expiry == 'N/A':
                logger.debug(f"[UI UPDATE] Expiry is still None or N/A - using current date + 7 days")
                from datetime import datetime, timedelta
                expiry = (datetime.now() + timedelta(days=7)).date()

            self.current_instrument_token = instrument_token  # Store for later use

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

            # CRITICAL FIX: Add trade to StateManager for Pro Monitor UI live updates
            # Trade Token at Execution
            logger.info(f"[TRADE TOKEN] {symbol} {strike} {direction} Token: {instrument_token}")
            logger.info(f"[TRADE TOKEN] Tradingsymbol: {tradingsymbol}")
            
            # WebSocket Assignment - Which WebSocket will handle this token?
            if hasattr(self, 'options_ws_client') and self.options_ws_client:
                logger.info(f"[WS ASSIGNMENT] Token {instrument_token} assigned to OPTIONS WebSocket")
            else:
                logger.info(f"[WS ASSIGNMENT] Token {instrument_token} assigned to SPOT WebSocket (options_ws_client not available)")

            # Subscribe to instrument token for live price updates
            self.state_manager.subscribe_token(instrument_token)
            logger.info(f"[WS SUBSCRIPTION] Subscribed to token {instrument_token}")
            logger.info(f"[WS SUBSCRIPTION] Token in subscribed_tokens: {instrument_token in self.state_manager.subscribed_tokens}")
            
            # CRITICAL FIX: Actually subscribe to the token in the WebSocket
            # StateManager.subscribe_token only tracks locally, doesn't send to Kite
            if hasattr(self, 'ws_client') and self.ws_client:
                # Set active trade token for targeted debugging
                self.ws_client.set_active_trade_token(instrument_token)
                
                subscribe_success = self.ws_client.subscribe_tokens([instrument_token])
                if subscribe_success:
                    logger.info(f"[WS SUBSCRIPTION] Successfully sent subscription request to Kite for token {instrument_token}")
                    logger.info(f"[WS POST-TRADE SUBSCRIBE] Token {instrument_token} sent to Kite after trade execution")
                else:
                    logger.error(f"[WS SUBSCRIPTION] Failed to send subscription request to Kite for token {instrument_token}")
            
            # Also set in options websocket if available
            if hasattr(self, 'options_ws_client') and self.options_ws_client:
                self.options_ws_client.set_active_trade_token(instrument_token)
                logger.info(f"[WS SUBSCRIPTION] Active trade token set in Options WebSocket: {instrument_token}")
            else:
                logger.warning(f"[WS SUBSCRIPTION] No WebSocket client available, cannot send subscription to Kite")
            
            # CRITICAL FIX: Validate subscription was successful
            if instrument_token not in self.state_manager.subscribed_tokens:
                logger.error(f"[WS SUBSCRIPTION FAILED] Token {instrument_token} NOT in subscribed_tokens list after subscription!")
                logger.error(f"[WS SUBSCRIPTION FAILED] Subscribed tokens: {len(self.state_manager.subscribed_tokens)}")
                logger.error(f"[WS SUBSCRIPTION FAILED] Current subscribed_tokens: {list(self.state_manager.subscribed_tokens)[:10]}...")
            else:
                logger.info(f"[WS SUBSCRIPTION VALIDATED] Token {instrument_token} successfully in subscribed_tokens list")
                logger.info(f"[WS SUBSCRIPTION VALIDATED] Total subscribed tokens: {len(self.state_manager.subscribed_tokens)}")
                logger.info(f"[WS SUBSCRIPTION VALIDATED] Sample subscribed tokens: {list(self.state_manager.subscribed_tokens)[:5]}")

            # CRITICAL FIX: Add trade to self.active_trades for monitor trigger
            # This is required for the monitor to detect active trades
            trade_record = {
                "symbol": symbol,
                "strike": strike,
                "type": direction,  # For monitor compatibility
                "direction": direction,  # Keep for backward compatibility
                "entry_price": option_price,
                "current_price": option_price,  # Initialize with entry price
                "target": self.target_price,
                "stop_loss": self.stoploss_price,
                "quantity": actual_lots * lot_size_from_risk,
                "instrument_token": instrument_token,
                "tradingsymbol": tradingsymbol,
                "expiry": expiry,
                "entry_time": time.time(),
                "pnl": 0,  # Initialize P&L to 0
                "status": "OPEN",  # For monitor compatibility
                "is_stale": False  # Initialize as not stale
            }
            self.active_trades[symbol] = trade_record
            logger.info(f"[ACTIVE TRADES] Trade added to self.active_trades: {symbol}")
            logger.info(f"[ACTIVE TRADES] Total active trades: {len(self.active_trades)}")

            # CRITICAL FIX: Store option chain for monitoring (single source of truth)
            # We need to find which option_chain was used for this trade
            # This is passed from the calling context, so we'll store it when execute_trade is called

            logger.info("="*80)
            logger.info("TRADE EXECUTED")
            logger.info("="*80)
            
            # CRITICAL DEBUG: Confirm trade execution success before return
            logger.debug(f"[DEBUG] Trade execution SUCCESS for {symbol}, returning True")
            
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

            # CRITICAL FIX: Simple trade registration (MANDATORY)
            trade_data = {
                "instrument_token": instrument_token,
                "symbol": symbol,
                "strike": strike,
                "type": direction,
                "entry_price": option_price,
                "current_price": option_price,
                "target": self.target_price,
                "stop_loss": self.stoploss_price,
                "status": "OPEN",
                "pnl": 0,
                "tradingsymbol": tradingsymbol,
                "expiry": expiry,
                "entry_source": "LIVE"  # Will be updated if entry was STALE
            }
            
            # Check if opportunity had entry_source flag (for STALE entries)
            if hasattr(self, 'current_opportunity') and self.current_opportunity:
                opportunity_entry_source = self.current_opportunity.get('entry_source', 'LIVE')
                if opportunity_entry_source == 'STALE':
                    trade_data['entry_source'] = 'STALE'
                    logger.info(f"[TRADE ENTRY] Trade entry source: STALE (WebSocket ticks may not be available yet)")
            
            self.state_manager.add_trade(trade_data)
            logger.info(f"[TRADE REGISTERED] Token: {instrument_token}")
            
            # VALIDATION (must add)
            active_trades = self.state_manager.get_active_trades()
            found = False
            for trade in active_trades:
                if trade.get('instrument_token') == instrument_token:
                    found = True
                    break
            
            if not found:
                logger.error(f"[CRITICAL] Trade NOT stored in state_manager: {instrument_token}")
                logger.error(f"[CRITICAL] Available tokens: {[t.get('instrument_token') for t in active_trades]}")
            else:
                logger.info(f"[CRITICAL] ✓ Trade successfully stored: {instrument_token}")
                logger.info(f"[CRITICAL] Active trades count: {len(active_trades)}")

            # CRITICAL FIX: Start monitor IMMEDIATELY after trade state update
            # This eliminates race condition - monitor is guaranteed to start if execution succeeds
            monitor_thread = threading.Thread(
                target=self.monitor_trade,
                args=(option_chain, tradingsymbol),  # CRITICAL FIX: Pass tradingsymbol for reliable price lookup
                daemon=True
            )
            monitor_thread.start()

            return True

        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False

    def monitor_trade(self, option_chain=None, tradingsymbol=None):
        """Monitor current trade until SL/TP hit (PRO MODE - no logs, only monitor)

        Args:
            option_chain: Option chain data (passed from execute_trade)
            tradingsymbol: Trading symbol (PRIMARY key for price lookup)
        """
        # Store option chain for this monitoring session
        if option_chain:
            self.current_option_chain = option_chain
            logger.debug(f"[MONITOR DEBUG] Option chain provided: {len(option_chain)} contracts")
        else:
            logger.warning(f"[MONITOR DEBUG] No option chain provided - will use self.current_option_chain if available")
            if hasattr(self, 'current_option_chain') and self.current_option_chain:
                logger.debug(f"[MONITOR DEBUG] Using self.current_option_chain: {len(self.current_option_chain)} contracts")
            else:
                logger.debug(f"[MONITOR DEBUG] self.current_option_chain is also None - monitor may not get prices")

        # CRITICAL FIX: Store tradingsymbol for reliable price lookup
        if tradingsymbol:
            self.current_tradingsymbol = tradingsymbol
            logger.debug(f"[MONITOR DEBUG] Tradingsymbol provided: {tradingsymbol}")
        else:
            logger.debug(f"[MONITOR DEBUG] No tradingsymbol provided - will use self.current_tradingsymbol if available")
            if hasattr(self, 'current_tradingsymbol') and self.current_tradingsymbol:
                logger.debug(f"[MONITOR DEBUG] Using self.current_tradingsymbol: {self.current_tradingsymbol}")
            else:
                logger.debug(f"[MONITOR DEBUG] self.current_tradingsymbol is also None - price lookup will fail")

        try:
            # CRITICAL FIX: Disable log suppression to see monitor logs
            # Logs now go to file only, console is clean
            logger.info("[MONITOR DEBUG] Starting trade monitoring loop")
            logger.info(f"[MONITOR DEBUG] Active trades count: {len(self.active_trades)}")
            logger.info(f"[MONITOR DEBUG] Current symbol: {getattr(self, 'current_symbol', 'N/A')}")
            logger.info(f"[MONITOR DEBUG] Current strike: {getattr(self, 'current_strike', 'N/A')}")
            logger.info(f"[MONITOR DEBUG] Current direction: {getattr(self, 'current_direction', 'N/A')}")
            logger.info(f"[MONITOR DEBUG] Current expiry: {getattr(self, 'current_expiry', 'N/A')}")
            logger.info(f"[MONITOR DEBUG] Entry price: {getattr(self, 'entry_price', 'N/A')}")

            # CRITICAL FIX: Ensure token is subscribed BEFORE monitoring starts
            instrument_token = None
            if self.current_option_chain and self.current_tradingsymbol:
                # Find instrument_token from option chain using tradingsymbol
                for opt in self.current_option_chain:
                    if opt.get('tradingsymbol') == self.current_tradingsymbol:
                        instrument_token = opt.get('instrument_token') or opt.get('instrument_key')
                        break
                
                if instrument_token:
                    logger.info(f"[WS DEBUG] Found instrument token for {self.current_tradingsymbol}: {instrument_token}")
                    
                    # Check if token is already subscribed
                    if instrument_token not in self.state_manager.subscribed_tokens:
                        logger.info(f"[WS DEBUG] Token {instrument_token} NOT subscribed - subscribing now")
                        self.state_manager.subscribe_token(instrument_token)
                        
                        # CRITICAL FIX: Actually subscribe to the token in the WebSocket
                        if hasattr(self, 'ws_client') and self.ws_client:
                            # Set active trade token for targeted debugging
                            self.ws_client.set_active_trade_token(instrument_token)
                            
                            subscribe_success = self.ws_client.subscribe_tokens([instrument_token])
                            if subscribe_success:
                                logger.info(f"[WS DEBUG] Successfully sent subscription request to Kite for token {instrument_token}")
                            else:
                                logger.error(f"[WS DEBUG] Failed to send subscription request to Kite for token {instrument_token}")
                        else:
                            logger.warning(f"[WS DEBUG] No WebSocket client available, cannot send subscription to Kite")
                    else:
                        logger.info(f"[WS DEBUG] Token {instrument_token} already subscribed")
                else:
                    logger.warning(f"[WS DEBUG] Could not find instrument token for {self.current_tradingsymbol}")
            else:
                logger.warning(f"[WS DEBUG] Cannot subscribe - missing option_chain or tradingsymbol")

            # CRITICAL FIX: Monitor depends on active_trades, NOT trade_active flag
            # This eliminates flag dependency and makes monitor independent
            loop_count = 0
            price_fetch_retry_count = 0
            max_price_fetch_retries = 5
            last_option_chain_refresh = time.time()
            option_chain_refresh_interval = 10  # Refresh every 10 seconds

            # CRITICAL FIX: Stale price protection
            consecutive_stale_confirmations = 0
            required_stale_confirmations = 2  # Require 2 consecutive confirmations for TP/SL on stale prices
            last_ws_tick_time = time.time()  # Track last WebSocket tick time
            ws_health_check_interval = 10  # Check WebSocket health every 10 seconds
            last_resubscribe_time = 0  # Track last resubscription attempt time
            resubscribe_cooldown = 30  # Cooldown period between resubscription attempts (seconds)
            last_stale_price = None  # Track last stale price to detect movement
            
            # SECONDARY FIX: Data readiness - Check first tick from shared state_manager
            logger.info(f"[DATA READINESS] Checking first tick for {self.current_symbol} (Token: {instrument_token})")
            logger.info(f"[MONITOR CHECK] First tick received for {instrument_token}: {instrument_token in self.state_manager.first_tick_received}")
            
            # Validation log
            if instrument_token in self.state_manager.first_tick_received:
                logger.info(f"[DATA READINESS] ✓ First tick already received (monitor can start immediately)")
            else:
                logger.info(f"[DATA READINESS] First tick not received yet - will monitor for arrival")
            
            # Do NOT block - just log and continue
            # Monitor will update trade state when ticks arrive

            while len(self.active_trades) > 0:
                loop_count += 1
                logger.debug(f"[MONITOR DEBUG] Monitor loop iteration #{loop_count}")
                logger.debug(f"[MONITOR DEBUG] Active trades: {len(self.active_trades)}")
                logger.debug(f"[MONITOR DEBUG] self.current_option_chain: {'Available' if hasattr(self, 'current_option_chain') and self.current_option_chain else 'None'}")

                # CRITICAL FIX: Periodic option_chain refresh (every 10 seconds)
                current_time = time.time()
                if current_time - last_option_chain_refresh > option_chain_refresh_interval:
                    logger.debug(f"[MONITOR REFRESH] Refreshing option chain (last refresh: {current_time - last_option_chain_refresh:.1f}s ago)")
                    try:
                        fresh_option_chain = self.get_option_chain_for_optionstar(self.current_symbol)
                        if fresh_option_chain:
                            self.current_option_chain = fresh_option_chain
                            last_option_chain_refresh = current_time
                            logger.debug(f"[MONITOR REFRESH] Option chain refreshed: {len(self.current_option_chain)} contracts")
                        else:
                            logger.warning(f"[MONITOR REFRESH] Failed to refresh option chain for {self.current_symbol}")
                    except Exception as e:
                        logger.error(f"[MONITOR REFRESH] Error refreshing option chain: {e}")

                # CRITICAL FIX: Refetch option chain if missing (fallback mechanism)
                if not self.current_option_chain:
                    logger.warning(f"[MONITOR CRITICAL] No option chain available, refetching for {self.current_symbol}")
                    try:
                        self.current_option_chain = self.get_option_chain_for_optionstar(self.current_symbol)
                        if self.current_option_chain:
                            logger.info(f"[MONITOR CRITICAL] Refetched option chain: {len(self.current_option_chain)} contracts")
                        else:
                            logger.error(f"[MONITOR CRITICAL] Failed to refetch option chain for {self.current_symbol}")
                    except Exception as e:
                        logger.error(f"[MONITOR CRITICAL] Error refetching option chain: {e}")
                        self.current_option_chain = None

                # Check daily loss limit using Risk Management Service
                daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)

                if daily_check.get("limit_reached"):
                    logger.error(f"Daily loss limit reached during monitoring ({daily_check['daily_loss_percent']:.1%}). Closing trade immediately.")
                    # CRITICAL FIX: Use stored option chain for single source of truth
                    # CRITICAL FIX: Use tradingsymbol for reliable price lookup
                    current_price, _, is_stale = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction, self.current_expiry, self.current_option_chain, self.current_tradingsymbol)
                    if current_price:
                        pnl = current_price - self.entry_price if self.current_direction == "CALL" else self.entry_price - current_price
                        self.close_trade("DAILY LOSS LIMIT", current_price, pnl)
                    return False

                # Get current option price using tradingsymbol (PRIMARY KEY - most reliable)
                # CRITICAL FIX: Use tradingsymbol instead of strike+direction matching
                logger.info(f"[MONITOR DEBUG] Attempting to get option price using tradingsymbol: {getattr(self, 'current_tradingsymbol', 'N/A')}")
                logger.info(f"[MONITOR DEBUG] Option chain passed to get_option_price: {'Yes' if self.current_option_chain else 'No'}")

                # CRITICAL FIX: Use tradingsymbol for reliable price lookup
                current_price, _, is_stale = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction, self.current_expiry, self.current_option_chain, self.current_tradingsymbol)

                logger.info(f"[MONITOR DEBUG] Current price retrieved: {current_price}")
                logger.info(f"[MONITOR DEBUG] Price is stale: {is_stale}")

                # CRITICAL FIX: Update WebSocket tick time if price is fresh (from WebSocket)
                if not is_stale:
                    last_ws_tick_time = time.time()
                    consecutive_stale_confirmations = 0  # Reset stale counter on fresh price
                    last_stale_price = None  # Reset last stale price on fresh price
                else:
                    logger.warning(f"[MONITOR WARNING] Using stale price - consecutive confirmations: {consecutive_stale_confirmations + 1}/{required_stale_confirmations}")
                    # CRITICAL FIX: Check if stale price has actually moved (reject flat repeated values)
                    # Use dynamic threshold: max(0.01, 0.1% of price) to handle high-premium options
                    price_movement_threshold = max(0.01, current_price * 0.001)  # 0.1% or 0.01 minimum
                    if last_stale_price is not None and abs(current_price - last_stale_price) < price_movement_threshold:
                        logger.warning(f"[MONITOR WARNING] Stale price is flat (no movement): Rs.{current_price} (threshold: {price_movement_threshold:.4f}) - rejecting confirmation")
                        # Don't increment counter for flat prices
                        consecutive_stale_confirmations = 0
                    else:
                        logger.info(f"[MONITOR] Stale price movement detected: Rs.{last_stale_price} -> Rs.{current_price} (threshold: {price_movement_threshold:.4f})")
                    last_stale_price = current_price  # Update last stale price

                # CRITICAL FIX: WebSocket health check with cooldown
                current_time = time.time()
                if current_time - last_ws_tick_time > ws_health_check_interval:
                    logger.warning(f"[WS HEALTH] No WebSocket tick for {current_time - last_ws_tick_time:.1f}s (threshold: {ws_health_check_interval}s)")
                    
                    # CRITICAL FIX: Check if first tick has arrived (from shared state_manager)
                    if instrument_token and instrument_token in self.state_manager.first_tick_received:
                        logger.info(f"[WS HEALTH] First tick received for {instrument_token} - trade should be LIVE now")
                        # Update last_ws_tick_time to prevent repeated warnings
                        last_ws_tick_time = current_time

                    # Check cooldown before resubscribing
                    time_since_last_resubscribe = current_time - last_resubscribe_time
                    if time_since_last_resubscribe > resubscribe_cooldown:
                        logger.warning(f"[WS HEALTH] WebSocket may be unhealthy - attempting resubscription (cooldown OK: {time_since_last_resubscribe:.1f}s > {resubscribe_cooldown}s)")

                        # Attempt resubscription
                        if instrument_token and instrument_token in self.state_manager.subscribed_tokens:
                            logger.info(f"[WS HEALTH] Resubscribing to token {instrument_token}")
                            self.state_manager.subscribe_token(instrument_token)
                            logger.info(f"[WS HEALTH] Token resubscribed successfully")
                            last_resubscribe_time = current_time  # Update last resubscribe time
                            last_ws_tick_time = current_time  # Reset timer after resubscription attempt
                    else:
                        logger.info(f"[WS HEALTH] Skipping resubscription - in cooldown period ({time_since_last_resubscribe:.1f}s < {resubscribe_cooldown}s)")

                # CRITICAL FIX: Do not allow monitor to run without price source
                # With 4-tier fallback (WS -> REST -> option_chain -> entry_price), this should rarely happen
                if not current_price:
                    price_fetch_retry_count += 1
                    logger.error(f"[MONITOR CRITICAL] No price source available - attempt {price_fetch_retry_count}/{max_price_fetch_retries}")
                    logger.error(f"[MONITOR CRITICAL] All 4 fallback strategies failed (WS, REST, option_chain, entry_price)")

                    # CRITICAL FIX: Force exit trade IMMEDIATELY without waiting
                    # Monitor should NEVER block waiting for WebSocket tick
                    if price_fetch_retry_count >= max_price_fetch_retries:
                        logger.error(f"[MONITOR CRITICAL] Max price fetch retries ({max_price_fetch_retries}) exceeded")
                        logger.error(f"[MONITOR CRITICAL] FORCING TRADE EXIT - cannot monitor without price data")
                        # Force exit trade at entry price (last known price)
                        force_exit_price = self.entry_price  # Fallback to entry price
                        try:
                            self.close_trade("PRICE DATA FAILURE - FORCE EXIT", force_exit_price, 0)
                        except Exception as e:
                            logger.error(f"[MONITOR CRITICAL] Error forcing trade exit: {e}")
                        return False

                    # CRITICAL FIX: NO BLOCKING - Continue immediately without waiting
                    # Monitor should never wait for WebSocket tick
                    logger.warning(f"[MONITOR CRITICAL] Retrying price fetch immediately (no blocking)")
                    continue  # Continue monitoring loop to retry price fetch

                # CRITICAL FIX: Reset retry counter on successful price fetch
                price_fetch_retry_count = 0
                
                # CRITICAL FIX: Update trade in StateManager with current price and stale flag
                if self.state_manager and instrument_token:
                    self.state_manager.update_trade(instrument_token, current_price, is_stale)
                    
                    # CRITICAL FIX: Log WebSocket tick status for the trade's token
                    tick_status = self.state_manager.get_token_tick_status(instrument_token)
                    logger.info(f"[WS TICK STATUS] Token {instrument_token}: {tick_status['status']}, Ticks: {tick_status['tick_count']}, Last tick: {tick_status['last_tick']}")
                    
                    if tick_status['status'] == 'NO_TICK':
                        logger.error(f"[WS TICK ERROR] Token {instrument_token} has NOT received ANY ticks since subscription!")
                        logger.error(f"[WS TICK ERROR] This indicates WebSocket subscription is not working for this token")
                    elif tick_status['status'] == 'STALE':
                        logger.warning(f"[WS TICK WARNING] Token {instrument_token} last tick was {tick_status['time_since_last_tick']:.1f}s ago - WebSocket may be lagging")

                # Calculate P&L
                # CRITICAL FIX: For BUYING options (both CALL and PUT), P&L is always (current - entry)
                # Whether CALL or PUT, if we're buying the option, we profit when premium increases
                pnl = current_price - self.entry_price
                pnl_percentage = (pnl / self.entry_price * 100) if self.entry_price > 0 else 0
                logger.info(f"[MONITOR DEBUG] Current price: {current_price}, Entry: {self.entry_price}, P&L: {pnl} ({pnl_percentage:.2f}%)")

                # PRO MODE: Clear screen and show only monitor
                clear_screen()
                self.print_trade_monitor(active_trades_only=True)

                # INTELLIGENT EXIT: Time + Weak Market = Exit (Pro-Level Logic)
                # Time alone should NOT close trade
                # Time + Weak Market = Exit
                # NSE ONLY - single_strike_trader.py is NSE-only bot
                if self.entry_time:
                    # CRITICAL FIX: Use time.time() for consistent type (entry_time is float from time.time())
                    trade_duration = (time.time() - self.entry_time) / 60  # in minutes

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
                            # Trade IS working - let it run (no log in PRO MODE)
                            pass

                # Update Trade Manager with live price
                self.trade_manager_service.update_price(self.current_symbol, current_price)

                # External dashboard only (no console rendering to preserve logs)
                # Dashboard data is written to dashboard_data.json automatically
                # Run dashboard_viewer.py in separate terminal to see the dashboard

                # Use LLM for sentiment-based exit decision (every 5 cycles to avoid too many LLM calls)
                should_use_llm = random.randint(1, 5) == 1  # 20% chance

                # CRITICAL FIX: Check if llm_analyzer_service exists before using it
                if hasattr(self, 'llm_analyzer_service') and self.llm_analyzer_service and should_use_llm:
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

                # Check TP/SL with stale price protection
                # CRITICAL FIX: Require 2 consecutive confirmations for TP/SL on stale prices
                tp_hit = False
                sl_hit = False

                if self.current_direction == "CALL":
                    if current_price >= self.target_price:
                        tp_hit = True
                    elif current_price <= self.stoploss_price:
                        sl_hit = True
                else:  # PUT
                    # CRITICAL FIX: For BUYING PUT options, we want premium to go UP (same as CALL)
                    # Target hit when premium goes UP, SL hit when premium goes DOWN
                    if current_price >= self.target_price:
                        tp_hit = True
                    elif current_price <= self.stoploss_price:
                        sl_hit = True

                # Execute TP/SL based on price freshness
                if tp_hit or sl_hit:
                    if is_stale:
                        # CRITICAL FIX: Check if price has moved before counting confirmation
                        # Use dynamic threshold: max(0.01, 0.1% of price) to handle high-premium options
                        price_movement_threshold = max(0.01, current_price * 0.001)  # 0.1% or 0.01 minimum
                        price_has_moved = (last_stale_price is None or abs(current_price - last_stale_price) >= price_movement_threshold)

                        if price_has_moved:
                            # Stale price with movement - require consecutive confirmations
                            consecutive_stale_confirmations += 1
                            logger.warning(f"[MONITOR WARNING] TP/SL condition met on STALE price with movement - confirmation {consecutive_stale_confirmations}/{required_stale_confirmations} (threshold: {price_movement_threshold:.4f})")

                            if consecutive_stale_confirmations >= required_stale_confirmations:
                                # Confirmed after required consecutive confirmations
                                if tp_hit:
                                    logger.warning(f"[TARGET HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Profit: {pnl:+.2f} (STALE PRICE CONFIRMED)")
                                    self.close_trade("TARGET_HIT", current_price, pnl)
                                else:
                                    logger.warning(f"[STOP LOSS HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Loss: {pnl:+.2f} (STALE PRICE CONFIRMED)")
                                    self.close_trade("SL_HIT", current_price, pnl)
                                return False
                            else:
                                # Not yet confirmed - wait for next confirmation
                                logger.info(f"[MONITOR] Waiting for additional confirmation before executing TP/SL on stale price")
                        else:
                            # Flat stale price - reject TP/SL
                            logger.warning(f"[MONITOR WARNING] TP/SL condition met on STALE price but price is flat (no movement) - REJECTING")
                            logger.warning(f"[MONITOR WARNING] Flat price: Rs.{current_price} (threshold: {price_movement_threshold:.4f}) - not executing TP/SL to prevent false exit")
                    else:
                        # Fresh price - execute immediately
                        if tp_hit:
                            logger.info(f"[TARGET HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Profit: {pnl:+.2f}")
                            self.close_trade("TARGET_HIT", current_price, pnl)
                        else:
                            logger.info(f"[STOP LOSS HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Loss: {pnl:+.2f}")
                            self.close_trade("SL_HIT", current_price, pnl)
                        return False

                # Sleep before next check (1 second for real-time monitoring)
                time.sleep(1)

            # Loop exited (trade_active became False)
            logger.info("monitor_trade() loop exited - trade is no longer active")
            return False

        except Exception as e:
            logger.error(f"Error monitoring trade: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return True  # Continue monitoring despite error

    def close_trade(self, exit_reason, exit_price, pnl):
        """Close current trade and update capital with proper money management"""
        # CRITICAL DEBUG: Log trade closure
        logger.debug(f"[DEBUG] close_trade() called for {self.current_symbol}, reason: {exit_reason}, pnl: {pnl}")
        
        # ANSI color codes for summary
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        CYAN = '\033[96m'
        WHITE = '\033[97m'
        RESET = '\033[0m'
        
        # CRITICAL DEBUG: Log trade closure
        logger.debug(f"[DEBUG] close_trade() called for {self.current_symbol}, reason: {exit_reason}, pnl: {pnl}")
        
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
                # CRITICAL FIX: DO NOT clear active_trades - this would stop the monitor
                # Instead, let the trade continue to monitor until it actually closes (TP/SL hit)
                # Risk management will prevent new trades by checking capital in main loop
                logger.error("Capital protection: Stopping NEW trades, but letting current trade monitor until close")
                # DO NOT clear active_trades - monitor must continue

        # Check daily loss limit using Risk Management Service
        daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)

        if daily_check.get("limit_reached"):
            logger.error(f"Daily loss limit reached: {daily_check['daily_loss_percent']:.1%}")
            # CRITICAL FIX: DO NOT clear active_trades - this would stop the monitor
            # Instead, let the trade continue to monitor until it actually closes (TP/SL hit)
            # Risk management will prevent new trades by checking daily loss in main loop
            logger.error("Daily loss limit: Stopping NEW trades, but letting current trade monitor until close")
            # DO NOT clear active_trades - monitor must continue

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
            'type': self.current_direction,  # For monitor compatibility
            'direction': self.current_direction,  # Keep for backward compatibility
            'expiry': self.current_expiry,
            'entry_price': self.entry_price,
            'exit_price': exit_price,
            'current_price': exit_price,  # For monitor compatibility (closed trades use exit_price)
            'target': self.target_price,
            'stop_loss': self.stoploss_price,
            'exit_reason': exit_reason,
            'pnl': pnl,  # Per lot P&L
            'pnl_per_lot': pnl,
            'pnl_pct': pnl_pct,
            'total_pnl': total_pnl,
            'lot_size': self.actual_lots,  # Actual position size
            'quantity': self.actual_lots,  # For monitor compatibility
            'trade_duration_minutes': trade_duration_minutes,  # NEW: Time-based analysis
            'timestamp': datetime.now().isoformat(),
            'entry_time': self.entry_time,  # For monitor compatibility
            'exit_time': datetime.now(),  # For monitor compatibility
            'capital_before': self.current_capital - total_pnl,
            'capital_after': self.current_capital,
            'status': 'CLOSED',  # For monitor compatibility
            'is_stale': False,  # Closed trades are not stale
            # Enhanced metrics for analysis
            'entry_metrics': self.current_trade_metrics
        }
        self.trade_history.append(trade_record)
        
        # Clear cooldown for the symbol (trade closed via TP/SL, can be selected again)
        if self.current_symbol and self.current_symbol in self.tick_rejected_symbols:
            del self.tick_rejected_symbols[self.current_symbol]
            logger.info(f"[TICK COOLDOWN] Cleared cooldown for {self.current_symbol} - trade closed")

        # PRO MODE: Print MCX-style color-coded trade summary
        pnl_color = GREEN if total_pnl > 0 else RED if total_pnl < 0 else WHITE
        print(f"\n{WHITE}{'='*80}{RESET}")
        print(f"{CYAN}TRADE CLOSED{RESET}")
        print(f"{WHITE}{'='*80}{RESET}")
        print(f"{WHITE}Symbol: {self.current_symbol}{RESET}")
        print(f"{WHITE}Exit Reason: {exit_reason}{RESET}")
        print(f"{WHITE}Exit Price: {exit_price:.2f}{RESET}")
        print(f"{WHITE}Trade P&L (per lot): {pnl:+.2f}{RESET}")
        print(f"{WHITE}Total P&L ({self.actual_lots} lot(s)): {pnl_color}{total_pnl:+.2f}{RESET}")
        print(f"{WHITE}Capital Before: {self.current_capital - total_pnl:+.2f}{RESET}")
        print(f"{WHITE}Capital After: {self.current_capital:+.2f}{RESET}")
        print(f"{WHITE}Capital Change: {pnl_color}{total_pnl:+.2f} ({(total_pnl/self.start_capital*100):+.2f}%){RESET}")
        print(f"{WHITE}{'='*80}{RESET}\n")

        # CRITICAL FIX: Close trade in Trade Manager
        if self.trade_manager_service and self.current_symbol:
            closed_trade = self.trade_manager_service.get_closed_trade(self.current_symbol)
            if closed_trade:
                logger.info(f"[TRADE MANAGER] Trade closed via manager: {closed_trade.get('reason', 'UNKNOWN')}")

        # CRITICAL FIX: Remove trade from StateManager for Pro Monitor UI
        if self.state_manager and self.current_instrument_token:
            self.state_manager.remove_trade(self.current_instrument_token)
            logger.info(f"[UI UPDATE] Trade removed from StateManager: {self.current_symbol} (token: {self.current_instrument_token})")

        # CRITICAL FIX: Remove trade from active_trades (single source of truth)
        # This is the ONLY place where trades are removed from active_trades
        if self.current_symbol in self.active_trades:
            del self.active_trades[self.current_symbol]
            logger.info(f"[ACTIVE TRADES] Trade removed from active_trades: {self.current_symbol}")

        # POST-TRADE EXECUTION: Execute best trade from queue after close
        if len(self.active_trades) == 0 and self.trade_queue:
            logger.info(f"[POST-TRADE EXECUTION] Trade closed, checking queue for next trade")

            # CRITICAL FIX: Re-filter queue before execution (remove stale trades)
            self.filter_trade_queue()

            # PRODUCTION-GRADE SAFEGUARD: Remove stale queue items (> 60s)
            import time
            now = time.time()
            stale_trade_ids = []
            for trade_id, trade in self.trade_queue.items():
                if 'timestamp' in trade:
                    age = now - trade['timestamp']
                    if age > 60:  # 60 seconds max age
                        logger.warning(f"[QUEUE REVALIDATION] Discarding stale queue item: {trade['symbol']} (age: {age:.1f}s)")
                        stale_trade_ids.append(trade_id)
            for trade_id in stale_trade_ids:
                self.trade_queue.pop(trade_id, None)

            sorted_trades = sorted(
                self.trade_queue.values(),
                key=lambda x: (x.get('score', 0), x.get('timestamp', 0)),
                reverse=True
            )

            for trade in sorted_trades:
                # Create trade_id for tracking
                trade_id = f"{trade['symbol']}_{trade['strike']}_{trade['direction']}"

                # CRITICAL FIX: Skip if already executed
                if trade_id in self.executed_trades:
                    logger.warning(f"[POST-TRADE EXECUTION] Skipping {trade['symbol']} - already executed")
                    continue

                # NOTE: instrument_token validation removed - will be fetched if missing

                # PRODUCTION-GRADE SAFEGUARD: Revalidate queued opportunity before execution
                logger.info(f"[QUEUE REVALIDATION] Revalidating queued opportunity: {trade['symbol']}")
                if not self.is_opportunity_still_valid(trade):
                    logger.warning(f"[QUEUE REVALIDATION] Queued opportunity no longer valid for {trade['symbol']}, discarding")
                    # Remove invalid trade from queue
                    self.trade_queue.pop(trade_id, None)
                    continue

                # CRITICAL FIX: Refresh option chain and fetch missing data before executing queued trade
                symbol = trade['symbol']
                latest_chain = self.get_option_chain_for_optionstar(symbol)
                if not latest_chain:
                    logger.warning(f"[POST-TRADE VALIDATION] Skipping {trade['symbol']} - no option chain available")
                    continue

                # CRITICAL FIX: If queue item has minimal data, fetch full data before execution
                if not trade.get("instrument_token") or not trade.get("tradingsymbol"):
                    logger.info(f"[POST-TRADE EXECUTION] Queue item has minimal data, fetching full analysis for {symbol}")

                    # Run full analysis for queued symbol
                    try:
                        # Get spot price
                        spot_price = self.get_spot_price(symbol)
                        if not spot_price:
                            logger.warning(f"[POST-TRADE EXECUTION] No spot price for {symbol}")
                            continue

                        # Smart strike selection
                        elite_strike, selected_expiry, selected_contract, direction, elite_lot = self.smart_strike_service.select_strike_complete(
                            instruments=[],
                            symbol=symbol,
                            option_chain=latest_chain,
                            spot=spot_price,
                            signal=trade.get('direction'),
                            optionstar_data=None,
                            confidence_score=trade.get('score', 75)
                        )

                        if not elite_strike:
                            logger.warning(f"[POST-TRADE EXECUTION] No strike selected for {symbol}")
                            continue

                        # CRITICAL FIX: Parse numeric strike from elite_strike (e.g., "1300 PE" -> 1300)
                        strike_price = int(elite_strike.split()[0]) if isinstance(elite_strike, str) else elite_strike

                        # Get instrument token and tradingsymbol first (needed for reliable price lookup)
                        instrument_token = selected_contract.get('instrument_token')
                        tradingsymbol = selected_contract.get('tradingsymbol')

                        if not instrument_token or not tradingsymbol:
                            logger.warning(f"[POST-TRADE EXECUTION] Missing instrument_token or tradingsymbol for {symbol}")
                            continue

                        # Get option price using tradingsymbol (PRIMARY KEY - most reliable)
                        option_price, _, is_stale = self.get_option_price(symbol, strike_price, direction, selected_expiry, latest_chain, tradingsymbol)
                        
                        # CRITICAL FIX: Log entry data source to identify stale trade selection
                        entry_source = "STALE" if is_stale else "LIVE"
                        logger.info(f"[ENTRY DATA SOURCE] {symbol} {strike_price} {direction} | Token: {instrument_token} | Source: {entry_source} | Price: Rs.{option_price}")
                        if is_stale:
                            logger.warning(f"[ENTRY DATA SOURCE WARNING] Trade entry using STALE price - WebSocket not receiving ticks for this token!")
                            logger.warning(f"[ENTRY DATA SOURCE WARNING] This trade will likely show STALE in monitor")
                        
                        if not option_price:
                            logger.warning(f"[POST-TRADE EXECUTION] No option price for {symbol}")
                            continue

                        # Update trade with full data
                        trade['strike'] = strike_price  # CRITICAL FIX: Use numeric strike (not "1300 PE")
                        trade['option_price'] = option_price
                        trade['expiry'] = selected_expiry
                        trade['selected_contract'] = selected_contract
                        trade['instrument_token'] = instrument_token
                        trade['tradingsymbol'] = tradingsymbol
                        trade['direction'] = direction

                        logger.info(f"[POST-TRADE EXECUTION] Fetched full data for {symbol}: Strike={strike_price}, Token={instrument_token}")

                    except Exception as e:
                        logger.error(f"[POST-TRADE EXECUTION] Failed to fetch full data for {symbol}: {e}")
                        continue

                logger.info(f"[POST-TRADE EXECUTION] Executing queued trade: {trade['symbol']} (Score: {trade.get('score', 0)}/100)")
                # Execute the trade (reuse existing execution logic)
                try:
                    direction = trade['direction']
                    option_price = trade['option_price']
                    expiry = trade.get('expiry', 'N/A')
                    strike = trade['strike']
                    trade_signal = trade.get('trade_signal', {})
                    selected_contract = trade.get('selected_contract')
                    instrument_token = trade.get('instrument_token')
                    tradingsymbol = trade.get('tradingsymbol')

                    if latest_chain and instrument_token:
                        # Micro-confirmation using WebSocket ticks before execution
                        # Extract signal_type from trade_signal (from Execution Brain)
                        signal_type = trade_signal.get('signal_type', 'MOMENTUM')
                        
                        # Check cooldown before tick confirmation
                        current_price = self.get_spot_price(symbol, bypass_cache=True)
                        if self.is_symbol_in_cooldown(symbol, current_price):
                            logger.warning(f"[TICK COOLDOWN] Skipping {symbol} - in rejection cooldown")
                            self.trade_queue.pop(trade_id, None)
                            continue
                        
                        if not self.confirm_entry_with_ticks(symbol, direction, signal_type):
                            logger.warning(f"[TICK CONFIRM] Entry rejected for {symbol} {direction} - ticks did not confirm direction")
                            # Update rejection tracking
                            self.update_tick_rejection(symbol, current_price)
                            self.trade_queue.pop(trade_id, None)
                            continue
                        
                        execution_success = self.execute_trade(symbol, strike, direction, option_price, trade_signal, latest_chain, selected_contract, instrument_token, tradingsymbol)
                        # Track execution failure (separate from tick confirmation failure)
                        if not execution_success:
                            logger.warning(f"[EXECUTION FAILURE] Trade execution failed for {symbol} - adding to cooldown")
                            current_price = self.get_spot_price(symbol, bypass_cache=True)
                            self.update_tick_rejection(symbol, current_price)
                        # CRITICAL FIX: Track executed trade
                        self.executed_trades.add(trade_id)
                        # CRITICAL FIX: Remove only executed trade from queue (not entire queue)
                        self.trade_queue.pop(trade_id, None)
                        logger.info(f"[POST-TRADE EXECUTION] Removed {trade_id} from queue")
                        break
                except Exception as e:
                    logger.error(f"[POST-TRADE EXECUTION] Failed to execute queued trade: {e}")
                    # Remove failed trade from queue
                    self.trade_queue.pop(trade_id, None)
                    continue
            else:
                logger.info(f"[POST-TRADE EXECUTION] No valid trades in queue")

        # Clear cooldown for the symbol (trade completed, can be selected again)
        completed_symbol = self.current_symbol
        self.current_strike = None
        self.current_symbol = None
        self.current_direction = None
        self.entry_price = None
        self.target_price = None
        self.stoploss_price = None
        self.current_expiry = None
        self.entry_time = None
        self.current_option_chain = None  # CRITICAL FIX: Clear stored option chain
        self.current_instrument_token = None  # CRITICAL FIX: Clear instrument token
        self.actual_lots = 1
        
        if completed_symbol and completed_symbol in self.tick_rejected_symbols:
            del self.tick_rejected_symbols[completed_symbol]
            logger.info(f"[TICK COOLDOWN] Cleared cooldown for {completed_symbol} - trade completed")
        
        # Note: trade_active is now a derived property from active_trades
        # No need to set it - clearing active_trades automatically sets trade_active to False
    
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
            
            logger.info(f"[OBSERVATION TRADE] Entry: Rs.{entry_price:.2f}")
            logger.info(f"[OBSERVATION TRADE] TP: Rs.{tp_price:.2f} (Target: +{((tp_price - entry_price) / entry_price * 100):.1f}%)")
            logger.info(f"[OBSERVATION TRADE] SL: Rs.{sl_price:.2f} (Risk: -{((entry_price - sl_price) / entry_price * 100):.1f}%)")
            logger.info(f"[OBSERVATION TRADE] Lot Size: {lot_size}")
            logger.info(f"[OBSERVATION TRADE] Risk: Rs.{risk_amount:.2f} | Reward: Rs.{reward_amount:.2f} | R:R: 1:{risk_reward_ratio:.1f}")
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

            # CRITICAL FIX: Start parallel queue collection thread after successful observation trade
            if self.parallel_thread is None or not self.parallel_thread.is_alive():
                self.parallel_queue_active = True
                self.parallel_queue_results = []

                # Get instruments list for parallel processing
                instruments_list = list(self.symbols) if self.symbols else list(self.config.get('instruments', {}).keys())

                logger.info(f"[PARALLEL QUEUE] Starting continuous background collection for {len(instruments_list)} symbols (observation mode)")
                self.parallel_thread = threading.Thread(
                    target=self.parallel_queue_collection_with_result,
                    args=(instruments_list, symbol),
                    daemon=True
                )
                self.parallel_thread.start()
                logger.info(f"[PARALLEL QUEUE] Background thread started for {symbol} (observation mode)")

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
                current_price = self.state_manager.get_latest_price(instrument_token)
                
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
                            logger.info(f"[OBSERVATION TRADE] Entry: Rs.{trade['entry_price']:.2f} → Exit: Rs.{current_price:.2f}")
                            logger.info(f"[OBSERVATION TRADE] P&L: Rs.{pnl:.2f} ({pnl_percentage:.1f}%)")
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
                            logger.info(f"[OBSERVATION TRADE] Entry: Rs.{trade['entry_price']:.2f} → Exit: Rs.{current_price:.2f}")
                            logger.info(f"[OBSERVATION TRADE] P&L: Rs.{pnl:.2f} ({pnl_percentage:.1f}%)")
                            logger.info(f"[OBSERVATION TRADE] Duration: {elapsed:.0f}s")
                            logger.info("=" * 80)
                            break
                        
                        # Log status every 30 seconds
                        if elapsed % 30 == 0 and elapsed > 0:
                            logger.info(f"[OBSERVATION TRADE] {elapsed}s elapsed | Price: Rs.{current_price:.2f} | P&L: Rs.{pnl:.2f} ({pnl_percentage:.1f}%) | TP: {trade['tp_price']:.2f} | SL: {trade['sl_price']:.2f}")
                
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
                logger.info(f"[OBSERVATION TRADE] Final Price: Rs.{trade['current_price']:.2f} | P&L: Rs.{trade['pnl']:.2f}")
            
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
        
        # CRITICAL FIX: Wait for WebSocket first tick before starting monitoring
        if not self.config.get("data_source") == "upstox":
            logger.info("[STARTUP DELAY] Waiting for WebSocket first tick data before starting monitoring...")
            first_tick_received = False
            max_wait_seconds = 30  # Wait up to 30 seconds for first tick
            wait_start = time.time()
            
            while not first_tick_received and (time.time() - wait_start) < max_wait_seconds:
                # Check if any symbol has price data
                for symbol in self.symbols:
                    price = self.state_manager.get_latest_price(symbol)
                    if price is not None and price > 0:
                        logger.info(f"[STARTUP DELAY] First tick received for {symbol}: {price}")
                        first_tick_received = True
                        break
                
                if not first_tick_received:
                    logger.warning(f"[STARTUP DELAY] Waiting for first tick... ({int(time.time() - wait_start)}s/{max_wait_seconds}s)")
                    time.sleep(2)  # Check every 2 seconds
            
            if first_tick_received:
                logger.info("[STARTUP DELAY] First tick data received - starting monitoring")
            else:
                logger.warning(f"[STARTUP DELAY] Timeout - no first tick received after {max_wait_seconds} seconds")
                logger.warning("[STARTUP DELAY] Proceeding with REST API fallback")
        else:
            logger.info("[STARTUP DELAY] Upstox mode - skipping WebSocket tick wait")
        
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
            logger.debug(f"[DEBUG MAIN LOOP] Cycle {cycle_count} started, trade_active: {self.trade_active}")
            
            # Clean up old tick rejection entries (prevent memory bloat)
            self.cleanup_tick_rejections()

            
            # PRODUCTION FIX: WebSocket soft guard - allow REST API fallback
            # EXCEPTION: Allow execution when using Upstox as data source
            # TEMPORARY FIX: Allow trading even without WebSocket for testing
            if not self.config.get("data_source") == "upstox" and not self.state_manager.is_websocket_connected():
                logger.warning("[WS GUARD] WebSocket not connected - using REST API fallback")
                logger.warning("[WS GUARD] Trading will continue with REST API data (slower)")
                # DO NOT SKIP - allow REST API fallback
                # time.sleep(10)  # Wait longer for WebSocket to connect
                # continue
            
            # CRITICAL FIX: Global data readiness check before evaluation
            # Wait until StateManager has price data for ALL symbols or timeout
            if cycle_count == 1:  # Only check on first cycle
                logger.info("[DATA READINESS] Checking if StateManager has price data for all symbols...")
                data_ready = False
                max_wait_cycles = 12  # Wait up to 60 seconds (12 cycles * 5 seconds)
                wait_cycle = 0
                
                while not data_ready and wait_cycle < max_wait_cycles:
                    missing_symbols = []
                    for symbol in self.symbols:
                        price = self.state_manager.get_latest_price(symbol)
                        if price is None or price == 0:
                            missing_symbols.append(symbol)
                    
                    if not missing_symbols:
                        logger.info(f"[DATA READINESS] All symbols have price data - ready for evaluation")
                        data_ready = True
                        break
                    else:
                        logger.warning(f"[DATA READINESS] Missing price data for {len(missing_symbols)} symbols: {missing_symbols}")
                        logger.warning(f"[DATA READINESS] Waiting for data... (cycle {wait_cycle + 1}/{max_wait_cycles})")
                        time.sleep(5)  # Wait 5 seconds before retry
                        wait_cycle += 1
                
                if not data_ready:
                    logger.error(f"[DATA READINESS] Timeout - some symbols still missing price data after {max_wait_cycles * 5} seconds")
                    logger.error(f"[DATA READINESS] Proceeding anyway with REST API fallback for missing symbols")
                else:
                    logger.info("[DATA READINESS] Data readiness check passed - starting evaluation")
                
                # CRITICAL FIX: Start OptionStar monitoring AFTER data readiness confirmed
                if self.optionstar_service and cycle_count == 1:
                    logger.info("[DATA READINESS] Starting OptionStar monitoring now that data is ready")
                    symbols_to_monitor = self.symbols if self.symbols else list(self.config.get('instruments', {}).keys())
                    # Filter out MCX symbols for OptionStar (NSE only)
                    mcx_symbols = ['CRUDEOIL', 'NATGAS', 'GOLDM', 'SILVERM', 'NATURALGAS', 'COPPER', 'ZINC', 'LEAD', 'ALUMINIUM']
                    symbols_to_monitor = [sym for sym in symbols_to_monitor if sym not in mcx_symbols]
                    try:
                        self.optionstar_service.start_continuous_monitoring(
                            symbols=symbols_to_monitor,
                            option_chain_provider=self.get_option_chain_for_optionstar_dict_format
                        )
                        logger.info(f"[DATA READINESS] OptionStar continuous monitoring started for {len(symbols_to_monitor)} NSE symbols")
                    except Exception as e:
                        logger.error(f"[DATA READINESS] Failed to start OptionStar monitoring: {e}")
                        logger.warning("[DATA READINESS] Continuing without OptionStar monitoring")
            
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
            
            # CRITICAL FIX: Print dashboard EVERY cycle (every 5 seconds) to show active trades immediately
            # This ensures ACTIVE TRADES MONITOR appears right after trade execution
            if cycle_count % 1 == 0:
                self.print_clean_dashboard()

            # CRITICAL FIX: HARD LOCK - Monitor-Only mode during active trade
            # When trade is active, skip ALL processing and API calls
            # Only monitor thread runs, ensuring clean execution flow
            if self.trade_active:
                logger.debug("[MODE] MONITOR ONLY - Trade active, skipping main loop processing")

                # CRITICAL FIX: Integrate parallel queue results if available
                if hasattr(self, 'parallel_queue_results') and self.parallel_queue_results:
                    with self.parallel_queue_lock:
                        if len(self.parallel_queue_results) > 0:
                            logger.info(f"[PARALLEL INTEGRATION] Integrating {len(self.parallel_queue_results)} collected opportunities into queue")
                            for opp in self.parallel_queue_results:
                                self.add_to_queue(opp)
                            self.parallel_queue_results.clear()
                            logger.info(f"[PARALLEL INTEGRATION] Integration complete, queue size: {len(self.trade_queue)}")

                logger.info("[MODE] Parallel queue collection may still be running in background")
                time.sleep(1)
                continue  # Skip entire cycle, only monitor runs

            # Check if new trades can be opened using Risk Management Service
            trade_permission = self.risk_service.can_open_new_trade()
            
            if not trade_permission.get("can_trade"):
                logger.error(f"Trading blocked: {trade_permission['reason']}")
                time.sleep(60)  # Wait before checking again
                continue
            
            # HYBRID EXECUTION MODE: Different logic based on active trade status
            if not self.trade_active:
                # ========================================
                # INITIAL TRADE: QUALITY SELECTION MODE (No active trade)
                # ========================================
                option_chain_cycle += 1

                # CRITICAL FIX: Reset cycle counter to prevent infinite growth
                max_cycle = 100  # Reset after 100 cycles to prevent overflow
                if option_chain_cycle >= max_cycle:
                    option_chain_cycle = 0
                    logger.info("[CYCLE FIX] Reset option chain cycle counter")

                # BATCH MODE: Collect all opportunities, select best (quality selection), execute
                try:
                    logger.info(f"[BATCH MODE] No active trade - running batch selection with quality logic (cycle {option_chain_cycle})")
                    opportunity = self.select_best_strike()
                    logger.info(f"[BATCH MODE] select_best_strike() returned. opportunity: {opportunity['symbol'] if opportunity else 'None'}")
                except Exception as e:
                    logger.error(f"[FAIL-SAFE] Symbol processing failed: {e}")
                    logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                    time.sleep(15)  # Wait before retry
                    continue
            else:
                # ========================================
                # QUEUE COLLECTION MODE (Active trade exists)
                # ========================================
                # CRITICAL FIX: Skip main thread queue collection if parallel thread is already doing it
                if self.parallel_queue_active:
                    logger.info(f"[QUEUE MODE] Active trade exists - skipping queue collection (parallel thread already running)")
                    opportunity = None  # No execution during active trade
                    continue

                logger.info(f"[QUEUE MODE] Active trade exists - parallel thread should be running, skipping main thread collection")
                opportunity = None  # No execution during active trade
                continue

            # EXECUTION PHASE: Process the opportunity from batch mode
            if opportunity:
                # STRICT VALIDATION: Skip trades without instrument_token
                if not opportunity.get('instrument_token'):
                    logger.warning(f"[VALIDATION] Skipping {opportunity['symbol']} - missing instrument_token")
                    continue

                # Create trade_id for tracking
                trade_id = f"{opportunity['symbol']}_{opportunity['strike']}_{opportunity['direction']}"

                # CRITICAL FIX: Check if trade already executed to prevent duplicates
                if trade_id in self.executed_trades:
                    logger.warning(f"[DUPLICATE CHECK] Skipping {opportunity['symbol']} - already executed")
                    continue

                # EXECUTE the best opportunity (batch mode already selected the best)
                logger.info(f"[BATCH EXECUTION] Executing best opportunity: {opportunity['symbol']} (Score: {opportunity['score']}/100)")
                # Proceed to execution phase below

                # CRITICAL FIX: Separate observation mode and normal mode execution paths
                if self.observation_mode:
                    # ========================================
                    # OBSERVATION MODE: MINIMAL EXECUTION PATH
                    # ========================================
                    try:
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

                        # Get institutional data (with timeout protection)
                        institutional_data = self.safe_calculate_institutional_walls(
                            {"calls": [], "puts": []}, spot, symbol, timeout=2
                        )  # Simplified for observation mode

                        # Use Smart Strike Service
                        if self.smart_strike_service:
                            # DEBUG: Log option chain being passed to Smart Strike
                            logger.debug(f"[DEBUG] Passing option chain to SmartStrike: {len(option_chain)} contracts")

                            strike_selection = self.smart_strike_service.select_strike_complete(
                                instruments=[],
                                symbol=symbol,
                                option_chain=option_chain,
                                spot=spot,
                                signal=direction,
                                optionstar_data=institutional_data,
                                confidence_score=75  # Fixed medium confidence for observation
                            )

                            # CRITICAL FIX: Handle Smart Strike errors and fallbacks
                            if not strike_selection or "error" in strike_selection:
                                error_msg = strike_selection.get("error", "Unknown error") if strike_selection else "No selection"
                                fallback_type = strike_selection.get("fallback", "None") if strike_selection else "None"
                                logger.warning(f"[OBSERVATION MODE] Smart Strike failed: {error_msg}, Fallback: {fallback_type}")

                                # CRITICAL FIX: ATM fallback when Smart Strike fails
                                if fallback_type == "ATM" or not strike_selection:
                                    logger.info(f"[OBSERVATION MODE] Using ATM fallback for {symbol}")
                                    # Calculate ATM strike from spot price
                                    atm_strike = self.calculate_atm_strike(symbol, spot)
                                    logger.info(f"[OBSERVATION MODE] ATM strike: {atm_strike}")

                                    # Get option chain to find ATM contract
                                    if option_chain:
                                        # Find ATM contract from option chain
                                        direction_type = "CE" if direction == "CALL" else "PE"
                                        atm_contract = None
                                        for opt in option_chain:
                                            if (opt.get('strike') == atm_strike and
                                                opt.get('type') == direction_type):
                                                atm_contract = opt
                                                break

                                        if atm_contract:
                                            logger.info(f"[OBSERVATION MODE] Found ATM contract: {atm_contract.get('tradingsymbol')}")
                                            strike_selection = {
                                                'strike': atm_strike,
                                                'selected_contract': atm_contract,
                                                'fallback': True
                                            }
                                            # CRITICAL FIX: Log execution proceeding after fallback
                                            logger.info(f"[EXECUTION] Proceeding with strike: {atm_strike} {direction_type} after Smart Strike fallback")
                                        else:
                                            logger.error(f"[OBSERVATION MODE] ATM contract not found for {atm_strike} {direction_type}")
                                            continue
                                    else:
                                        logger.error(f"[OBSERVATION MODE] No option chain for ATM fallback")
                                        continue
                                else:
                                    logger.error(f"[OBSERVATION MODE] Smart Strike failed with no fallback: {error_msg}")
                                    continue

                            if strike_selection and "error" not in strike_selection:
                                elite_strike = strike_selection['strike']
                                # FIX: Don't expect lot_size from smart strike - get from config
                                elite_lot = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                                selected_contract = strike_selection.get('selected_contract', None)

                                logger.info(f"[OBSERVATION MODE] Selected: {elite_strike}, Lot: {elite_lot}")

                                # CRITICAL FIX: Log execution proceeding after Smart Strike selection
                                if strike_selection.get('fallback'):
                                    logger.info(f"[EXECUTION] [OBSERVATION MODE] Proceeding with strike: {elite_strike} after Smart Strike fallback")
                                else:
                                    logger.info(f"[EXECUTION] [OBSERVATION MODE] Proceeding with strike: {elite_strike} after Smart Strike selection")

                                # Get option price using WebSocket with REST fallback
                                if selected_contract:
                                    instrument_token = selected_contract.get('instrument_token') or selected_contract.get('instrument_key')  # FIX: Fallback to instrument_key

                                    # CRITICAL FIX: Multi-strategy price fetch
                                    final_option_price = None

                                    # Strategy 1: WebSocket/StateManager
                                    logger.info(f"[OBSERVATION PRICE] Trying WebSocket for {instrument_token}")
                                    final_option_price = self.state_manager.get_latest_price(instrument_token)

                                    if final_option_price and final_option_price > 0:
                                        logger.info(f"[OBSERVATION PRICE] Got price from WebSocket: Rs.{final_option_price}")
                                    else:
                                        logger.warning(f"[OBSERVATION PRICE] WebSocket price not available")

                                        # Strategy 2: Option chain fallback
                                        logger.info(f"[OBSERVATION PRICE] Trying option chain fallback")
                                        if option_chain:
                                            for opt in option_chain:
                                                if opt.get('instrument_token') == instrument_token or opt.get('instrument_key') == str(instrument_token):
                                                    chain_price = opt.get('last_price', 0)
                                                    if chain_price and chain_price > 0:
                                                        final_option_price = chain_price
                                                        logger.info(f"[OBSERVATION PRICE] Got price from option chain: Rs.{final_option_price}")
                                                        break

                                        # Strategy 3: REST API fallback (rate-limited)
                                        if not final_option_price:
                                            logger.warning(f"[OBSERVATION PRICE] Trying REST API fallback")
                                            try:
                                                tradingsymbol = selected_contract.get('tradingsymbol', '')
                                                if tradingsymbol:
                                                    self._rate_limit_guard()
                                                    quote = self.kite_client.quote([f"NFO:{tradingsymbol}"])
                                                    if quote and f"NFO:{tradingsymbol}" in quote:
                                                        final_option_price = quote[f"NFO:{tradingsymbol}"].get("last_price")
                                                        if final_option_price and final_option_price > 0:
                                                            logger.info(f"[REST FALLBACK] Got option price from REST API: {final_option_price}")
                                                        else:
                                                            logger.warning(f"[REST FALLBACK] REST API returned invalid price: {final_option_price}")
                                            except Exception as e:
                                                logger.error(f"[REST FALLBACK] Failed to get option price from REST API: {e}")

                                    # Check if we got a valid price after REST attempt
                                    if not final_option_price or final_option_price == 0:
                                        logger.warning(f"[OBSERVATION PRICE] REST fallback failed - skipping trade")
                                        continue
                                else:
                                    logger.warning(f"[OBSERVATION MODE] No selected contract")
                                    continue

                            # Final validation
                            if not final_option_price or final_option_price == 0:
                                logger.error(f"[OBSERVATION PRICE] CRITICAL: Could not get price for {instrument_token}")
                                logger.error(f"[OBSERVATION PRICE] All strategies failed - skipping observation trade")
                                continue

                            logger.info(f"[OBSERVATION PRICE] Final price: Rs.{final_option_price}")

                            # ========================================
                            # FORCE EXECUTION - SKIP ALL FILTERS
                            # ========================================
                            logger.info("[OBSERVATION MODE] SKIPPING ALL FILTERS - FORCING EXECUTION")

                            # Calculate simple TP/SL (FIXED - more realistic levels)
                            tp_price = final_option_price * 1.10  # 10% target (more realistic)
                            sl_price = final_option_price * 0.95  # 5% stop loss (more realistic)

                            logger.info(f"[OBSERVATION MODE] Trade: {elite_strike}")
                            logger.info(f"[OBSERVATION MODE] Entry: Rs.{final_option_price:.2f}")
                            logger.info(f"[OBSERVATION MODE] TP: Rs.{tp_price:.2f} (+10%)")
                            logger.info(f"[OBSERVATION MODE] SL: Rs.{sl_price:.2f} (-5%)")
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

                    except Exception as e:
                        logger.error(f"[FAIL-SAFE] Observation mode failed: {e}")
                        logger.error(f"[FAIL-SAFE] Continuing to next cycle (bot will not crash)")
                        import traceback
                        logger.error(f"[FAIL-SAFE] Traceback: {traceback.format_exc()}")
                        time.sleep(15)
                        continue
                else:
                    # ========================================
                    # NORMAL MODE: Full Intelligence Pipeline
                    # ========================================
                    logger.info(f"[NORMAL MODE] Starting normal mode execution pipeline")

                    # DEBUG: Log opportunity data immediately
                    logger.info(f"[DEBUG] Opportunity keys: {opportunity.keys()}")
                    logger.info(f"[DEBUG] instrument_token: {opportunity.get('instrument_token')}")
                    logger.info(f"[DEBUG] tradingsymbol: {opportunity.get('tradingsymbol')}")
                    logger.info(f"[DEBUG] selected_contract: {opportunity.get('selected_contract')}")

                    # CRITICAL FIX: Skip update_market_snapshot if opportunity is complete (from immediate execution)
                    # update_market_snapshot() calls get_option_chain_for_optionstar() internally, which is slow
                    if (opportunity.get('instrument_token') and 
                        opportunity.get('tradingsymbol') and 
                        opportunity.get('selected_contract')):
                        logger.info(f"[DEBUG] Skipping update_market_snapshot (opportunity is complete from immediate execution)")
                    else:
                        logger.info(f"[DEBUG] Running update_market_snapshot (opportunity incomplete)")
                        self.update_market_snapshot()

                    try:

                        # Use direction, option_price, expiry, and trade_signal from Engine1
                        direction = opportunity['direction']
                        option_price = opportunity['option_price']
                        expiry = opportunity.get('expiry', 'N/A')
                        trade_signal = opportunity['trade_signal']
                        symbol = opportunity['symbol']

                        # CRITICAL FIX: Skip option chain re-fetch if opportunity is complete (from immediate execution)
                        # When select_best_strike() returns immediately (score >= 80), opportunity already has all data
                        has_instrument_token = opportunity.get('instrument_token')
                        has_tradingsymbol = opportunity.get('tradingsymbol')
                        has_selected_contract = opportunity.get('selected_contract')

                        logger.info(f"[DEBUG] Opportunity completeness check:")
                        logger.info(f"[DEBUG]   instrument_token: {has_instrument_token}")
                        logger.info(f"[DEBUG]   tradingsymbol: {has_tradingsymbol}")
                        logger.info(f"[DEBUG]   selected_contract: {has_selected_contract}")

                        if has_instrument_token and has_tradingsymbol and has_selected_contract:
                            logger.info(f"[EXECUTION PHASE] Opportunity is complete (from immediate execution), skipping option chain re-fetch for validation")
                            logger.info(f"[EXECUTION PHASE] Using existing data: Token={opportunity.get('instrument_token')}, Symbol={opportunity.get('tradingsymbol')}")
                            # Use existing selected_contract
                            selected_contract = opportunity.get('selected_contract')
                            # CRITICAL FIX: Use option_chain from opportunity (if available)
                            option_chain = opportunity.get('option_chain')
                            if option_chain:
                                logger.info(f"[EXECUTION PHASE] Using option_chain from opportunity: {len(option_chain)} contracts")
                            else:
                                logger.warning(f"[EXECUTION PHASE] No option_chain in opportunity, will refetch for monitoring")
                                option_chain = None
                        else:
                            # CRITICAL FIX: Fetch option chain for execution in normal mode
                            logger.info(f"[EXECUTION PHASE] Opportunity incomplete, fetching option chain for {symbol}")
                            option_chain = self.get_option_chain_for_optionstar(symbol)
                            if not option_chain:
                                logger.warning(f"[EXECUTION PHASE] No option chain for {symbol}, skipping trade")
                                time.sleep(15)
                                continue

                            logger.info(f"[EXECUTION PHASE] Option chain fetched: {len(option_chain)} contracts")
                        logger.info("=" * 80)
                        logger.info("EXECUTION PHASE STARTED")
                        logger.info("=" * 80)

                        # NSE-only decision logic
                        trade_taken = True  # Default to execute if we have a signal
                        skip_reason = None

                        # REMOVED: Strength score adjustment (was causing regression)
                        # Execution Brain already validated the score before adding to execute_opportunities
                        # No need for second-guessing with strength adjustment

                        # REMOVED: MCX filter blocking (was causing hidden execution block)
                        # Execution Brain already validated the score and decided to EXECUTE
                        # No need for second-guessing with MCX filter
                        # MCX filter can be informational only, not blocking

                        # REMOVED: trade_taken check (was causing hidden execution block)
                        # Execution Brain already decided EXECUTE - no need to re-check
                        # trade_taken = True is default and should stay True

                        # Print clean dashboard
                        self.print_clean_dashboard()

                        logger.info(f"Selected: {opportunity['symbol']} {opportunity['strike']} {direction} @ Rs.{option_price} (Expiry: {expiry}, PCR: {opportunity['pcr']:.2f}, Buildup: {opportunity['buildup_pattern']}, Strength: {opportunity['strength']})")

                        # CRITICAL FIX: Store option chain before execution for monitoring
                        self.current_option_chain = option_chain

                        # DEBUG: Log before calling execute_trade
                        logger.debug(f"[DEBUG F] ABOUT TO CALL execute_trade() for {opportunity['symbol']}")

                        # CRITICAL FIX: Pass selected_contract, instrument_token, and tradingsymbol to execute_trade
                        selected_contract = opportunity.get('selected_contract')
                        opportunity_instrument_token = opportunity.get('instrument_token')
                        opportunity_tradingsymbol = opportunity.get('tradingsymbol')

                        # CRITICAL DEBUG: Log instrument mapping before execution
                        logger.debug(f"[DEBUG INSTRUMENT] Symbol: {opportunity['symbol']}, Strike: {opportunity['strike']}")
                        logger.debug(f"[DEBUG INSTRUMENT] instrument_token from opportunity: {opportunity_instrument_token}")
                        logger.debug(f"[DEBUG INSTRUMENT] tradingsymbol from opportunity: {opportunity_tradingsymbol}")
                        logger.debug(f"[DEBUG INSTRUMENT] selected_contract: {selected_contract}")

                        if not opportunity_instrument_token:
                            raise Exception(f"CRITICAL: instrument_token missing - upstream bug. Opportunity keys: {opportunity.keys()}")

                        # CRITICAL LOG: Verify execute_trade() is being called
                        logger.info(">>> CALLING EXECUTE_TRADE <<<")
                        logger.info(f"[EXECUTE TRADE] Symbol: {opportunity['symbol']}, Strike: {opportunity['strike']}, Direction: {direction}")

                        # PRODUCTION-GRADE SAFEGUARD: Revalidate opportunity before execution
                        # CRITICAL FIX: Skip pre-execution validation for immediate execution (score >= 80)
                        # Since we just validated it in select_best_strike(), no need to revalidate
                        if opportunity.get('score', 0) >= 80:  # HIGH_CONF_THRESHOLD = 80
                            logger.info(f"[PRE-EXECUTION VALIDATION] Skipping revalidation for {opportunity['symbol']} (Score: {opportunity['score']}/100 >= 80, just validated in select_best_strike)")
                        else:
                            logger.info(f"[PRE-EXECUTION VALIDATION] Revalidating opportunity for {opportunity['symbol']}")
                            if not self.is_opportunity_still_valid(opportunity):
                                logger.warning(f"[PRE-EXECUTION VALIDATION] Opportunity no longer valid for {opportunity['symbol']}, skipping execution")
                                continue

                        # Micro-confirmation using WebSocket ticks before execution
                        # Extract signal_type from trade_signal (from Execution Brain)
                        signal_type = trade_signal.get('signal_type', 'MOMENTUM')
                        
                        # Check cooldown before tick confirmation
                        current_price = self.get_spot_price(opportunity['symbol'], bypass_cache=True)
                        if self.is_symbol_in_cooldown(opportunity['symbol'], current_price):
                            logger.warning(f"[TICK COOLDOWN] Skipping {opportunity['symbol']} - in rejection cooldown")
                            continue
                        
                        if not self.confirm_entry_with_ticks(opportunity['symbol'], direction, signal_type):
                            logger.warning(f"[TICK CONFIRM] Entry rejected for {opportunity['symbol']} {direction} - ticks did not confirm direction")
                            # Update rejection tracking
                            self.update_tick_rejection(opportunity['symbol'], current_price)
                            continue

                        # Store opportunity for entry_source tracking
                        self.current_opportunity = opportunity
                        
                        if self.execute_trade(opportunity['symbol'], opportunity['strike'], direction, option_price, trade_signal, option_chain, selected_contract, opportunity_instrument_token, opportunity_tradingsymbol):
                            trade_count += 1
                            logger.info(f"[EXECUTE TRADE SUCCESS] Trade executed successfully for {opportunity['symbol']}")
                            logger.info(f"[EXECUTE TRADE SUCCESS] trade_active: {self.trade_active}")
                            logger.info(f"[EXECUTE TRADE SUCCESS] active_trades: {len(self.active_trades)}")

                            # CRITICAL FIX: Track executed trade to prevent duplicates
                            self.executed_trades.add(trade_id)
                            logger.info(f"[EXECUTED TRADES] Added {trade_id} to executed_trades set")
                        else:
                            # Track execution failure
                            logger.warning(f"[EXECUTION FAILURE] Trade execution failed for {opportunity['symbol']} - adding to cooldown")
                            current_price = self.get_spot_price(opportunity['symbol'], bypass_cache=True)
                            self.update_tick_rejection(opportunity['symbol'], current_price)
                            continue

                        # FAIL-SAFE: Verify trade was added to active_trades
                        if len(self.active_trades) == 0:
                            logger.error("CRITICAL: execute_trade returned True but active_trades is empty!")
                            logger.error("CRITICAL: This indicates a bug in execute_trade() - trade not added to active_trades")
                        else:
                            logger.info("FAIL-SAFE: Trade correctly added to active_trades")

                        # CRITICAL FIX: Start parallel queue collection thread after successful execution
                        if self.parallel_thread is None or not self.parallel_thread.is_alive():
                            self.parallel_queue_active = True
                            self.parallel_queue_results = []

                            # Get instruments list for parallel processing
                            instruments_list = list(self.symbols) if self.symbols else list(self.config.get('instruments', {}).keys())

                            logger.info(f"[PARALLEL QUEUE] Starting continuous background collection for {len(instruments_list)} symbols")
                            self.parallel_thread = threading.Thread(
                                target=self.parallel_queue_collection_with_result,
                                args=(instruments_list, opportunity['symbol']),
                                daemon=True
                            )
                            self.parallel_thread.start()
                            logger.info(f"[PARALLEL QUEUE] Background thread started for {opportunity['symbol']}")

                            logger.debug(f"[DEBUG H] execute_trade() returned SUCCESS for {opportunity['symbol']}")
                        else:
                            logger.warning(f"[EXECUTE TRADE FAILURE] execute_trade() returned FAILURE for {opportunity['symbol']}")
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

            # ============================================================
            # REMOVED: External monitor trigger
            # ============================================================
            # Monitor is now started inside execute_trade() as background thread
            # This removes the race condition completely
            # No external trigger needed - monitor is guaranteed to start if execution succeeds
            pass

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
                logger.info(f"Average Win: Rs.{metrics['avg_win']:.2f}")
                logger.info(f"Average Loss: Rs.{metrics['avg_loss']:.2f}")
                logger.info(f"Expectancy: Rs.{metrics['expectancy']:.2f}")
                logger.info(f"Total P&L: Rs.{metrics['total_pnl']:.2f}")
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
            logger.info(f"Average Win: Rs.{metrics['avg_win']:.2f}")
            logger.info(f"Average Loss: Rs.{metrics['avg_loss']:.2f}")
            logger.info(f"Expectancy: Rs.{metrics['expectancy']:.2f} per trade")
            logger.info(f"Total P&L: Rs.{metrics['total_pnl']:.2f}")

            if metrics.get('confidence_performance'):
                logger.info("\nBy Confidence Level:")
                for conf, data in metrics['confidence_performance'].items():
                    logger.info(f"  {conf}: {data['trades']} trades, {data['win_rate']:.1f}% win rate, Rs.{data['total_pnl']:.2f} P&L")

            if metrics.get('exit_reason_performance'):
                logger.info("\nBy Exit Reason:")
                for reason, data in metrics['exit_reason_performance'].items():
                    logger.info(f"  {reason}: {data['trades']} trades, Rs.{data['total_pnl']:.2f} P&L, {data['avg_duration_minutes']:.1f} min avg")

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
    
    # Console startup message (logs go to file, console is clean)
    print("="*80)
    print("SINGLE STRIKE TRADER - STARTING")
    print("="*80)
    print(f"Investment: Rs.{args.investment}")
    print(f"Mode: {'PAPER TRADING' if args.paper_trading else 'LIVE TRADING'}")
    print(f"Console: INFO+ logs (important events)")
    print(f"File: trading.log (DEBUG+ logs - everything)")
    print("="*80)
    print()
    
    if args.paper_trading:
        paper_trading = True
    elif args.live:
        paper_trading = False

    # Parse symbols (only if provided)
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]
    
    # Initialize trader with investment amount and optional symbols
    print("Initializing trader...")
    trader = SingleStrikeTrader(investment_amount=args.investment, paper_trading=paper_trading, symbols=symbols)
    print("Trader initialized successfully")
    print()
    
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
    
    print("Starting trading day...")
    print("Monitor UI will appear when a trade is executed")
    print()
    trader.run_trading_day()
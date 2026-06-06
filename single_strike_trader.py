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
from kite_client import KiteClient
from engine1_market_analyzer import Engine1MarketAnalyzer
from llm_market_analyzer import LLMMarketAnalyzer
from optionstar import calculate_institutional_walls
from risk_management import get_risk_management_service
from risk_wrapper import (
    get_position_size,
    update_trade_result,
    can_execute_trade,
    reset_daily_limits,
    get_risk_status
)
from mcx_wrapper import get_mcx_signal
from combined_wrapper import get_combined_signal
from services.market_analyzer_service import MarketAnalyzerService
from services.breakout_entry_service import BreakoutEntryService
from services.consensus_service import ConsensusService
from services.llm_analyzer_service import LLMAnalyzerService
from services.optionstar_service import OptionStarService
from services.execution_brain_service import ExecutionBrainService
from services.trade_manager_service import TradeManagerService
from services.strike_selector_service import StrikeSelectorService
from services.elite_strike_service import EliteStrikeService
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

        # Initialize KiteClient
        # Paper trading uses real data but doesn't place real orders
        self.kite_client = KiteClient(
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            paper_trading=self.paper_trading  # Paper trading flag
        )
        
        # Initialize Risk Management Service (initialize early - needed by run_trading_day)
        self.risk_service = get_risk_management_service(investment_amount)
        logger.info("Risk Management Service initialized")
        
        # Trading parameters (initialize early - needed by run_trading_day)
        self.start_capital = investment_amount
        self.current_capital = investment_amount
        logger.info(f"Capital initialized: ₹{self.start_capital}")
        
        # Market hours (initialize early - needed by WebSocket initialization)
        # Check if we have MCX symbols - if yes, use MCX hours (09:00-23:30)
        # Otherwise use NSE hours (09:15-15:30)
        has_mcx = any(
            self.config.get('instruments', {}).get(s, {}).get('exchange') == 'MCX'
            for s in (self.symbols if self.symbols else self.config.get('instruments', {}).keys())
        )
        
        if has_mcx:
            self.market_open = dt_time(9, 0)
            self.market_close = dt_time(23, 30)
            logger.info(f"Market hours (MCX): {self.market_open} - {self.market_close}")
        else:
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
        
        # Trade history
        self.trade_history = []
        
        # Initialize Engine1 for historical data and VWAP calculation (data layer only)
        self.engine1 = Engine1MarketAnalyzer(self.kite_client, debug_instrument=None)
        logger.info("Engine 1 (Data Layer) initialized for historical data and VWAP")
        
        # Initialize State Manager for WebSocket data
        self.state_manager = StateManager(max_history=100)
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
        self.kite_client.load_instruments_optimized("NFO")
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
            self.optionstar_service = None
        
        try:
            self.market_analyzer_service = MarketAnalyzerService(optionstar_service=self.optionstar_service)
            logger.info("Market Analyzer Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Market Analyzer Service: {e}")
            self.market_analyzer_service = None
        
        try:
            self.breakout_entry_service = BreakoutEntryService()
            logger.info("Breakout Entry Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Breakout Entry Service: {e}")
            self.breakout_entry_service = None
        
        try:
            self.llm_analyzer_service = LLMAnalyzerService()
            logger.info("LLM Analyzer Service initialized (Advisory)")
        except Exception as e:
            logger.error(f"Failed to initialize LLM Analyzer Service: {e}")
            self.llm_analyzer_service = None
        
        try:
            self.execution_brain_service = ExecutionBrainService()
            logger.info("Execution Brain Service initialized (Final Authority)")
        except Exception as e:
            logger.error(f"Failed to initialize Execution Brain Service: {e}")
            self.execution_brain_service = None
        
        try:
            self.trade_manager_service = TradeManagerService(max_daily_loss=3000, config=self.config)
            logger.info("Trade Manager Service initialized (Live Dashboard)")
        except Exception as e:
            logger.error(f"Failed to initialize Trade Manager Service: {e}")
            self.trade_manager_service = None
        
        try:
            self.strike_selector_service = StrikeSelectorService()
            logger.info("Strike Selector Service initialized (Smart Strike Selection)")
        except Exception as e:
            logger.error(f"Failed to initialize Strike Selector Service: {e}")
            self.strike_selector_service = None
        
        try:
            self.elite_strike_service = EliteStrikeService()
            logger.info("Elite Strike Service initialized (Strike Optimization)")
        except Exception as e:
            logger.error(f"Failed to initialize Elite Strike Service: {e}")
            self.elite_strike_service = None
        
        # Start Strike Selector Service
        if self.strike_selector_service:
            self.strike_selector_service.start()
            logger.info("Strike Selector Service started (independent microservice)")
        
        # Start Elite Strike Service
        if self.elite_strike_service:
            self.elite_strike_service.start()
            logger.info("Elite Strike Service started (independent microservice)")
        
        logger.info("Prop Desk Architecture ready (8 independent services)")
        
        # Start OptionStar continuous monitoring
        if self.optionstar_service:
            symbols_to_monitor = list(self.config.get('instruments', {}).keys())
            self.optionstar_service.start_continuous_monitoring(
                symbols=symbols_to_monitor,
                option_chain_provider=self.get_option_chain_for_optionstar
            )
            logger.info(f"OptionStar continuous monitoring started for {len(symbols_to_monitor)} symbols")
        
        # Initialize historical data for all configured instruments (best effort)
        logger.info("Initializing historical data for Engine 1...")
        all_instruments = self.config.get('instruments', {}).keys()
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
            # Use all instruments from config (includes NFO + MCX)
            monitor_symbols = list(self.config.get('instruments', {}).keys())
        
        # ========================================
        # SPOT WEBSOCKET (NSE) - For spot prices
        # ========================================
        logger.info(f"Loading Spot WebSocket tokens for {len(monitor_symbols)} symbols...")
        spot_tokens = self.ws_client.load_tokens(monitor_symbols)
        
        if spot_tokens:
            logger.info(f"Connecting to Spot WebSocket with {len(spot_tokens)} tokens...")
            self.ws_client.connect(spot_tokens)
            logger.info("Spot WebSocket connected successfully - Real-time spot prices streaming")
            
            # Wait a moment for WebSocket to connect
            time.sleep(2)
        else:
            logger.warning("No Spot WebSocket tokens loaded - falling back to REST API")
        
        # ========================================
        # OPTIONS WEBSOCKET (NFO) - For OI/Volume
        # ========================================
        logger.info("Loading Options WebSocket tokens for OI/Volume data...")
        
        # Get current spot prices for ATM calculation
        all_option_tokens = []
        for symbol in monitor_symbols:
            try:
                spot_price = self.get_spot_price(symbol, bypass_cache=False)
                if spot_price == 0:
                    logger.warning(f"Could not get spot price for {symbol}, skipping options WebSocket")
                    continue
                
                # Get option tokens for ATM strikes
                option_tokens = self.options_ws_client.get_option_tokens(symbol, spot_price)
                all_option_tokens.extend(option_tokens)
                
            except Exception as e:
                logger.error(f"Error getting option tokens for {symbol}: {e}")
                continue
        
        if all_option_tokens:
            logger.info(f"Connecting to Options WebSocket with {len(all_option_tokens)} tokens...")
            self.options_ws_client.connect(all_option_tokens)
            logger.info("Options WebSocket connected successfully - Real-time OI/Volume streaming")
            
            # Wait a moment for WebSocket to connect (non-blocking)
            # Don't block if it takes too long
            for i in range(10):  # Wait up to 10 seconds
                if self.state_manager.is_websocket_connected():
                    break
                time.sleep(1)
        else:
            logger.warning("No Options WebSocket tokens loaded - OI/Volume will use REST API fallback")
        
        # ========================================
        # MCX WEBSOCKET - For commodities (NEW)
        # ========================================
        logger.info("Loading MCX WebSocket tokens for commodities...")
        mcx_symbols = [s for s in monitor_symbols if self.config.get('instruments', {}).get(s, {}).get('exchange') == 'MCX']
        
        if mcx_symbols:
            mcx_tokens = []
            for symbol in mcx_symbols:
                try:
                    # Map CRUDEOIL to CRUDEOILM for MCX instruments
                    mcx_symbol = "CRUDEOILM" if symbol == "CRUDEOIL" else symbol
                    # Get nearest MCX contract
                    contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                    if contract:
                        token = contract['instrument_token']
                        mcx_tokens.append(token)
                        logger.info(f"MCX Token for {symbol} ({mcx_symbol}): {token}")
                except Exception as e:
                    logger.error(f"Error getting MCX contract for {symbol}: {e}")
            
            if mcx_tokens:
                logger.info(f"Connecting to MCX WebSocket with {len(mcx_tokens)} tokens...")
                # Subscribe to MCX tokens (reuse existing WebSocket client)
                self.ws_client.connect(mcx_tokens)
                logger.info("MCX WebSocket connected successfully - Real-time commodity data streaming")
            else:
                logger.warning("No MCX tokens loaded - commodities will use REST API fallback")
        else:
            logger.info("No MCX symbols configured - skipping MCX WebSocket")
        
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
        self.oi_cache = {}  # symbol -> previous total OI for delta calculation
        self.price_cache_timestamp = {}  # symbol -> timestamp of last price update
        
        # Market snapshot data for clean dashboard
        self.market_snapshot = {}  # symbol -> market data
        
        # Enhanced state tracking for better data resolution
        self.price_history = {}  # symbol -> list of last 5 prices
        self.oi_history = {}  # symbol -> list of last 5 OI values
        self.max_history_length = 5  # Keep last 5 data points
        
        # MCX-specific trading logic
        self.mcx_opening_range = {}  # symbol -> {"high": x, "low": y, "timestamp": z}
        self.mcx_first_5min_data = {}  # symbol -> list of prices in first 5 minutes
    
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

    def print_mcx_dashboard(self, symbol, data):
        """Print MCX-specific dashboard with trading signals"""
        print(f"""
================================================================================
 MCX LIVE - {symbol}
================================================================================
 Price    : {data.get('price', 0):<10.2f}    OI       : {data.get('oi', 0):<15.0f}
 Volume   : {data.get('volume', 0):<10.0f}    Trend    : {"BULLISH" if data.get('oi_change', 0) > 0 else "BEARISH":<15}
================================================================================
 Opening Range (First 5 Min)
 High     : {self.mcx_opening_range.get(symbol, {}).get('high', 0):<10.2f}    Low      : {self.mcx_opening_range.get(symbol, {}).get('low', 0):<10.2f}
================================================================================
 Trading Signals
 BUY  Signal  : {"YES - Price > Opening High + OI Increasing" if data.get('price', 0) > self.mcx_opening_range.get(symbol, {}).get('high', 0) and data.get('oi_change', 0) > 0 else "NO":<20}
 SELL Signal  : {"YES - Price < Opening Low + OI Increasing" if data.get('price', 0) < self.mcx_opening_range.get(symbol, {}).get('low', 0) and data.get('oi_change', 0) > 0 else "NO":<20}
================================================================================
 Risk Management
 Stop Loss  : 15 points     Target   : 30-50 points
================================================================================
""")

    def update_market_snapshot(self):
        """Update market snapshot with current data for all symbols"""
        instruments = self.symbols if self.symbols else self.config.get('instruments', {}).keys()
        
        for symbol in instruments:
            try:
                # Check if it's an MCX symbol
                is_mcx = self.config.get('instruments', {}).get(symbol, {}).get('exchange') == 'MCX'
                
                if is_mcx:
                    # MCX-specific data fetching
                    # Map CRUDEOIL to CRUDEOILM for MCX instruments
                    mcx_symbol = "CRUDEOILM" if symbol == "CRUDEOIL" else symbol
                    contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                    if not contract:
                        continue
                    
                    token = contract['instrument_token']
                    quote = self.kite.kite.quote([token])  # Use token directly without MCX prefix
                    
                    if not quote or str(token) not in quote:
                        continue
                    
                    data = quote[str(token)]
                    price = data.get('last_price', 0)
                    oi = data.get('oi', 0)
                    volume = data.get('volume', 0)
                    
                    # Track opening range (first 5 minutes)
                    current_time = datetime.now()
                    if symbol not in self.mcx_opening_range:
                        self.mcx_opening_range[symbol] = {"high": price, "low": price, "timestamp": current_time}
                        self.mcx_first_5min_data[symbol] = [price]
                    else:
                        # Update opening range in first 5 minutes
                        time_diff = (current_time - self.mcx_opening_range[symbol]["timestamp"]).total_seconds()
                        if time_diff < 300:  # First 5 minutes
                            self.mcx_opening_range[symbol]["high"] = max(self.mcx_opening_range[symbol]["high"], price)
                            self.mcx_opening_range[symbol]["low"] = min(self.mcx_opening_range[symbol]["low"], price)
                            self.mcx_first_5min_data[symbol].append(price)
                    
                    # Calculate OI change
                    prev_oi = self.oi_history.get(symbol, [oi])[-1] if symbol in self.oi_history else oi
                    oi_change = oi - prev_oi
                    
                    # Update market snapshot for MCX
                    self.market_snapshot[symbol] = {
                        "spot": price,
                        "atm": price,
                        "pcr": 0,  # Not applicable for futures
                        "bias": "BULLISH" if oi_change > 0 else "BEARISH",
                        "support": self.mcx_opening_range.get(symbol, {}).get('low', 0),
                        "resistance": self.mcx_opening_range.get(symbol, {}).get('high', 0),
                        "signal": "NONE",
                        "price": price,
                        "oi": oi,
                        "volume": volume,
                        "oi_change": oi_change
                    }
                    
                    # Print MCX dashboard immediately when data is available
                    self.print_mcx_dashboard(symbol, self.market_snapshot[symbol])
                    
                else:
                    # NFO/NSE - existing logic
                    spot_price = self.get_spot_price(symbol, bypass_cache=True)
                    if spot_price == 0:
                        continue
                    
                    # Get option chain for PCR calculation
                    option_chain = self.get_option_chain_for_optionstar(symbol)
                    if not option_chain:
                        continue
                    
                    # Calculate PCR
                    total_ce_oi = sum(item.get('call_oi', 0) for item in option_chain)
                    total_pe_oi = sum(item.get('put_oi', 0) for item in option_chain)
                    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
                    
                    # Calculate institutional walls
                    calls = []
                    puts = []
                    for item in option_chain:
                        if item.get('type') == 'CE':
                            calls.append({
                                'strikePrice': item.get('strike'),
                                'openInterest': item.get('call_oi', 0)
                            })
                        elif item.get('type') == 'PE':
                            puts.append({
                                'strikePrice': item.get('strike'),
                                'openInterest': item.get('put_oi', 0)
                            })
                    
                    option_chain_data = {"calls": calls, "puts": puts}
                    institutional_data = calculate_institutional_walls(option_chain_data, spot_price)
                    
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

    def get_spot_price(self, symbol, bypass_cache=False):
        """Get current spot price for symbol (WebSocket - Real-time, no rate limits)"""
        try:
            # Use WebSocket data from State Manager
            price = self.state_manager.get_latest_price(symbol)
            
            if price is None:
                # Fallback to REST API if WebSocket not connected yet
                logger.warning(f"WebSocket data not available for {symbol}, using REST API fallback")
                return self._get_spot_price_rest(symbol, bypass_cache)
            
            return price
            
        except Exception as e:
            logger.error(f"Error getting spot price from WebSocket: {e}")
            # Fallback to REST API
            return self._get_spot_price_rest(symbol, bypass_cache)
    
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
            
            # Convert to OptionStar format
            calls = []
            puts = []
            for item in option_chain:
                if item.get('type') == 'CE':
                    calls.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('call_oi', 0)
                    })
                elif item.get('type') == 'PE':
                    puts.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('put_oi', 0)
                    })
            
            return {"calls": calls, "puts": puts}
            
        except Exception as e:
            logger.error(f"Error getting option chain for OptionStar: {e}")
            return None

    def get_real_option_chain(self, symbol, spot_price):
        """Fetch real option chain using optimized Prop-Desk architecture (NO MOCK DATA)"""
        try:
            logger.info(f"Fetching optimized option chain from Zerodha API for {symbol}")

            # Use optimized option chain (Prop-Desk Level)
            chain, pcr, delta_data, atm = self.kite_client.get_option_chain_optimized(symbol, spot_price)

            if not chain:
                logger.warning(f"{symbol}: No option chain data from optimized API")
                return None

            # Convert optimized chain to Engine1 format
            # Engine1 expects: [{'strike': x, 'call_oi': y, 'put_oi': z, 'last_price': w, 'type': 'CE/PE'}]
            option_chain = []

            for strike, data in chain.items():
                ce_data = data.get("CE", {})
                pe_data = data.get("PE", {})
                expiry = ce_data.get("expiry", pe_data.get("expiry", ""))  # Add expiry field

                if ce_data and ce_data.get("ltp", 0) > 0:
                    option_chain.append({
                        'strike': strike,
                        'expiry': expiry,  # Add expiry field
                        'call_oi': ce_data.get("oi", 0),
                        'put_oi': 0,
                        'last_price': ce_data.get("ltp", 0),
                        'type': 'CE'
                    })

                if pe_data and pe_data.get("ltp", 0) > 0:
                    option_chain.append({
                        'strike': strike,
                        'expiry': expiry,  # Add expiry field
                        'call_oi': 0,
                        'put_oi': pe_data.get("oi", 0),
                        'last_price': pe_data.get("ltp", 0),
                        'type': 'PE'
                    })

            logger.info(f"Built option chain with {len(option_chain)} strikes from optimized API for {symbol}")
            logger.info(f"Optimized metrics - PCR: {pcr:.2f}, ATM: {atm}, ΔOI available: {len(delta_data)} strikes")
            logger.info(f"Option chain includes REAL OI data from Zerodha API with ΔOI tracking")

            # Store PCR and delta_data for Engine1 to use
            self.current_pcr = pcr
            self.current_delta_data = delta_data
            self.current_atm = atm

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
                    logger.warning(f"{symbol}: No real option chain data from Zerodha API, skipping")
                    continue

                # Calculate Institutional Walls (OptionStar)
                calls = []
                puts = []
                for item in option_chain:
                    if item.get('type') == 'CE':
                        calls.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('call_oi', 0)
                        })
                    elif item.get('type') == 'PE':
                        puts.append({
                            'strikePrice': item.get('strike'),
                            'openInterest': item.get('put_oi', 0)
                        })
                
                option_chain_data = {"calls": calls, "puts": puts}
                institutional_data = calculate_institutional_walls(option_chain_data, spot_price)
                
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
                total_ce_oi = sum(item.get('call_oi', 0) for item in option_chain)
                total_pe_oi = sum(item.get('put_oi', 0) for item in option_chain)
                pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
                
                # Update market snapshot with actual PCR
                if symbol in self.market_snapshot:
                    self.market_snapshot[symbol]["pcr"] = pcr
                    self.market_snapshot[symbol]["atm"] = spot_price  # Update ATM with current spot
                
                total_oi = sum(item.get('call_oi', 0) + item.get('put_oi', 0) for item in option_chain)
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
                        {"strike": item.get('strike'), "oi": item.get('call_oi', 0) + item.get('put_oi', 0)}
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
                
                if market_analysis['market_analysis']['market_strength'] >= 3:
                    strength = "STRONG"
                elif market_analysis['market_analysis']['market_strength'] >= 2:
                    strength = "MODERATE"
                else:
                    strength = "WEAK"
                
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
                
                # Determine direction from breakout
                direction = "CALL" if breakout == "BULLISH" else "PUT" if breakout == "BEARISH" else None
                
                if not direction:
                    logger.info(f"{symbol}: No clear breakout direction, skipping")
                    continue
                
                # Update market snapshot with signal
                if symbol in self.market_snapshot:
                    self.market_snapshot[symbol]["signal"] = direction
                
                # ========================================
                # STRIKE SELECTOR SERVICE - Professional Selection
                # ========================================
                # logger.info(f"[STRIKE SELECTOR] Using professional selection for {symbol}")  # Reducing log noise
                
                if not self.strike_selector_service:
                    logger.warning(f"{symbol}: Strike Selector Service not available, using basic selection")
                    # Fallback to basic selection
                    strike_selection = {
                        "strike": int(spot_price),
                        "expiry": "N/A",
                        "signal": direction
                    }
                else:
                    strike_selection = self.strike_selector_service.select_strike_complete(
                        instruments=[],  # Not needed for expiry selection (API already filtered)
                        symbol=symbol,
                        option_chain=option_chain,
                        spot=spot_price,
                        signal=direction,
                        optionstar_data=institutional_data
                    )
                
                if not strike_selection:
                    logger.warning(f"{symbol}: Strike selector could not select strike, skipping")
                    continue
                
                # Get option price for selected strike
                strike_str = strike_selection['strike']
                strike_price = int(strike_str.split()[0])
                option_price, expiry = self.get_option_price(symbol, strike_price, direction)
                
                if option_price == 0:
                    logger.warning(f"{symbol}: Could not get option price for {strike_str}, skipping")
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
                    'trade_mode': 'EXECUTE',
                    'execution_score': 85,  # High score for professional selection
                    'lot_size': self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50)
                }
                
                # Execution Brain approval
                if not self.execution_brain_service:
                    logger.warning(f"{symbol}: Execution Brain Service not available, auto-approving")
                    execution_decision = {"action": "EXECUTE", "score": 85}
                else:
                    execution_decision = self.execution_brain_service.should_execute(
                        symbol=symbol,
                        trade_signal=trade_signal,
                        market_analysis=market_analysis,
                        institutional_walls=institutional_data
                    )
                
                if execution_decision['action'] != 'EXECUTE':
                    logger.info(f"[PROP DESK] {symbol} rejected by Execution Brain: {execution_decision['action']}")
                    continue
                
                # ========================================
                # ELITE STRIKE SERVICE - Strike Optimization
                # ========================================
                # logger.info(f"[ELITE STRIKE] Optimizing strike for {symbol}")  # Reducing log noise
                
                if not self.elite_strike_service:
                    logger.warning(f"{symbol}: Elite Strike Service not available, using original strike")
                    elite_optimization = {
                        "strike": strike_str,
                        "lot": trade_signal['lot_size']
                    }
                else:
                    # Prepare ranked strikes for elite service
                    ranked_strikes = []
                    for item in option_chain:
                        ranked_strikes.append({
                            "strikePrice": item.get('strike'),
                            "call_oi": item.get('call_oi', 0),
                            "put_oi": item.get('put_oi', 0),
                            "volume": item.get('volume', 0)
                        })
                    
                    # Optimize using Elite Strike Service
                    elite_optimization = self.elite_strike_service.optimize(
                        symbol=symbol,
                        signal=direction,
                        strike=strike_str,
                        spot=spot_price,
                        ranked_strikes=ranked_strikes,
                        score=execution_decision.get('score', 85)
                    )
                
                # Apply elite optimizations
                original_strike = strike_str
                elite_strike = elite_optimization['strike']
                elite_lot = elite_optimization['lot']
                
                # Re-parse elite strike for option price lookup
                elite_strike_price = int(elite_strike.split()[0])
                
                # Get option price for elite-optimized strike
                elite_option_price, elite_expiry = self.get_option_price(symbol, elite_strike_price, direction)
                
                if elite_option_price == 0:
                    logger.warning(f"{symbol}: Could not get option price for elite strike {elite_strike}, using original")
                    elite_option_price = option_price
                    elite_expiry = expiry
                    elite_strike = strike_str
                    elite_lot = trade_signal['lot_size']
                else:
                    logger.info(f"[ELITE STRIKE] {symbol} - Original: {original_strike} @ ₹{option_price}, Elite: {elite_strike} @ ₹{elite_option_price}, Lot: {elite_lot}")
                
                # Update trade signal with elite optimizations
                trade_signal['strike'] = elite_strike_price
                trade_signal['expiry'] = elite_expiry
                trade_signal['lot_size'] = elite_lot
                trade_signal['elite_optimized'] = True
                trade_signal['original_strike'] = original_strike
                
                # Update option price for affordability check
                option_price = elite_option_price
                
                # Check affordability
                lot_size = trade_signal['lot_size']
                cost_per_lot = option_price * lot_size
                can_afford = cost_per_lot <= self.current_capital
                
                if not can_afford:
                    logger.warning(f"[PROP DESK] {symbol} cannot afford trade - skipping")
                    continue
                
                # Score calculation
                score = execution_decision['score']
                
                if score > best_score:
                    best_score = score
                    best_opportunity = {
                        'symbol': symbol,
                        'strike': strike_price,
                        'expiry': expiry,
                        'direction': direction,
                        'spot': spot_price,
                        'option_price': option_price,
                        'cost_per_lot': cost_per_lot,
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
                    
                    logger.info(f"[PROP DESK] New best opportunity: {symbol} {strike_price} {direction} @ ₹{option_price} (Score: {score}/100)")
                    
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

    def get_option_price(self, symbol, strike, direction):
        """Get current option price using option_token_map (all expiries) for correct strike selection"""
        try:
            # Use full map for correct strike selection
            with open('option_token_map.json', 'r') as f:
                option_token_map = json.load(f)
            logger.info(f"Using full option token map (all expiries) for correct ATM selection")

            # Create option key (convert CALL/PUT to CE/PE)
            direction_formatted = "CE" if direction == "CALL" else "PE"
            option_key = f"{symbol}{int(strike)}{direction_formatted}"

            # Look up instrument token
            if option_key not in option_token_map:
                logger.warning(f"Option {option_key} not found in token map")
                return None, None

            instrument_token = option_token_map[option_key]['instrument_token']
            expiry = option_token_map[option_key]['expiry']

            logger.info(f"Using option: {option_key} (Expiry: {expiry})")

            # Get LTP from Kite using rate-limited fetch
            ltp_response = self.kite_client.safe_ltp_fetch([instrument_token])
            if ltp_response and instrument_token in ltp_response:
                price = ltp_response[instrument_token]
                # Handle both dict and float returns
                if isinstance(price, dict):
                    return price.get('last_price', 0), expiry
                return price, expiry
            else:
                logger.warning(f"Could not get LTP for {option_key}")
                return None, None

        except Exception as e:
            logger.error(f"Error getting option price: {e}")
            return None, None

    def execute_trade(self, symbol, strike, direction, option_price=None, trade_signal=None):
        """Execute a trade on the selected strike using engine signal for target/stop-loss"""
        try:
            # UNIVERSAL RISK MANAGER CHECK (NEW - for all markets)
            if not can_execute_trade():
                logger.warning("UNIVERSAL RISK MANAGER BLOCKED TRADE - Trading stopped")
                return False
            
            # MCX SIGNAL ENGINE (NEW - only for MCX symbols)
            is_mcx = self.config.get('instruments', {}).get(symbol, {}).get('exchange') == 'MCX'
            if is_mcx:
                logger.info("[MCX] Getting MCX-specific signal...")
                # Get current price for MCX signal
                try:
                    if hasattr(self, 'current_spot_price') and self.current_spot_price:
                        mcx_signal = get_mcx_signal(symbol, self.current_spot_price, 0, 0)
                        logger.info(f"[MCX] Signal: {mcx_signal.get('signal')} | Confidence: {mcx_signal.get('confidence', 0):.2f}")
                except:
                    logger.info("[MCX] Could not get MCX signal (continuing with normal flow)")
            
            # Get option price and expiry if not provided
            if not option_price:
                option_price, expiry = self.get_option_price(symbol, strike, direction)
                if not option_price:
                    logger.error(f"Could not get option price for {symbol} {strike} {direction}")
                    return False
            else:
                # If option_price is provided, still get expiry
                _, expiry = self.get_option_price(symbol, strike, direction)

            # Use engine signal for target/stop-loss if available
            lot_size = self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 1)

            # Use Risk Management Service for position sizing
            position_calc = self.risk_service.calculate_position_size(option_price, lot_size, self.current_capital)
            
            if not position_calc.get("success"):
                logger.error(f"Position sizing failed: {position_calc.get('error')}")
                return False
            
            actual_lots = position_calc["actual_lots"]
            cost_per_lot = position_calc["cost_per_lot"]
            total_cost = position_calc["total_cost"]
            
            logger.info(f"Position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")

            # Use Risk Management Service for risk parameters
            risk_params = self.risk_service.calculate_risk_parameters(option_price, actual_lots, direction, self.current_capital)
            
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
                current_price, _ = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction)
                if current_price:
                    pnl = current_price - self.entry_price if self.current_direction == "CALL" else self.entry_price - current_price
                    self.close_trade("DAILY LOSS LIMIT", current_price, pnl)
                return False

            # Get current option price
            current_price, _ = self.get_option_price(self.current_symbol, self.current_strike, self.current_direction)
            if not current_price:
                logger.warning("Could not get current price, skipping this check")
                return True  # Continue monitoring

            # Calculate P&L
            if self.current_direction == "CALL":
                pnl = current_price - self.entry_price
            else:
                pnl = self.entry_price - current_price
            pnl_percentage = (pnl / self.entry_price * 100) if self.entry_price > 0 else 0

            logger.info(f"[MONITOR] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Entry: {self.entry_price}, Current: {current_price}, P&L: {pnl:+.2f} ({pnl_percentage:+.2f}%)")
            
            # Update Trade Manager with live price
            self.trade_manager_service.update_price(self.current_symbol, current_price)
            
            # Render dashboard periodically
            if random.randint(1, 10) == 1:  # 10% chance to render dashboard
                self.trade_manager_service.render_dashboard()

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
                if current_price <= self.target_price:
                    logger.info(f"[TARGET HIT] {self.current_symbol} {self.current_strike} {self.current_direction} (Expiry: {self.current_expiry}) - Profit: {pnl:+.2f}")
                    self.close_trade("TARGET_HIT", current_price, pnl)
                    return False
                elif current_price >= self.stoploss_price:
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
        self.current_capital = self.risk_service.update_capital(total_pnl)
        
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

        # Save to trade history
        trade_record = {
            'symbol': self.current_symbol,
            'strike': self.current_strike,
            'direction': self.current_direction,
            'entry_price': self.entry_price,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl_per_lot': pnl,
            'total_pnl': total_pnl,
            'lot_size': self.actual_lots,  # Actual position size
            'timestamp': datetime.now().isoformat(),
            'capital_before': self.current_capital - total_pnl,
            'capital_after': self.current_capital
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
        self.current_strike = None
        self.current_symbol = None
        self.current_direction = None
        self.entry_price = None
        self.target_price = None
        self.stoploss_price = None
        self.actual_lots = 1

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
        if self.state_manager.is_websocket_connected():
            logger.info("WebSocket: CONNECTED - Real-time data streaming active")
        else:
            logger.info("WebSocket: DISCONNECTED - Using REST API fallback")
        
        logger.info("="*80)
        
        # Update market snapshot immediately for MCX symbols
        mcx_symbols = [s for s in (self.symbols if self.symbols else self.config.get('instruments', {}).keys()) 
                      if self.config.get('instruments', {}).get(s, {}).get('exchange') == 'MCX']
        if mcx_symbols:
            logger.info("Updating MCX market snapshot immediately...")
            self.update_market_snapshot()

        trade_count = 0
        cycle_count = 0
        option_chain_cycle = 0  # Separate counter for option chain refresh

        while self.is_market_open():
            cycle_count += 1
            
            # Update market snapshot every cycle (every 5 seconds)
            if cycle_count % 12 == 0:  # Every 60 seconds
                self.update_market_snapshot()
            
            # Log status every 60 cycles (approx every 5 minutes)
            if cycle_count % 60 == 0:
                current_time = datetime.now().time()
                ws_status = "CONNECTED" if self.state_manager.is_websocket_connected() else "DISCONNECTED (REST fallback)"
                logger.info(f"[MARKET STATUS] Current Time: {current_time} | Market Open: {self.is_market_open()} | Trade Active: {self.trade_active}")
                logger.info(f"[SERVICE STATUS] OptionStar: Monitoring | Market Analyzer: Active | Breakout Service: Active | Execution Brain: Active | LLM: Advisory | Trade Manager: Active")
                logger.info(f"[DATA STATUS] WebSocket: {ws_status} | Option Chain Refresh: Every 60 sec")
                
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
                
                # Only fetch option chains every 60 seconds (12 cycles) to avoid rate limits
                if option_chain_cycle % 12 == 0:
                    # logger.info("No active trade - selecting new strike...")  # Reducing log noise
                    opportunity = self.select_best_strike()
                else:
                    # logger.info(f"Waiting for option chain refresh (cycle {option_chain_cycle}/12)")  # Reducing log noise
                    time.sleep(5)
                    continue

                if opportunity:
                    # Update market snapshot before trade selection
                    self.update_market_snapshot()
                    
                    # Use direction, option_price, expiry, and trade_signal from Engine1
                    direction = opportunity['direction']
                    option_price = opportunity['option_price']
                    expiry = opportunity.get('expiry', 'N/A')
                    trade_signal = opportunity['trade_signal']
                    
                    # COMBINED INTELLIGENCE (NEW - multi-market confirmation)
                    is_mcx = self.config.get('instruments', {}).get(opportunity['symbol'], {}).get('exchange') == 'MCX'
                    
                    nse_signal = None
                    mcx_signal = None
                    
                    # Prepare NSE signal from existing trade_signal
                    if trade_signal:
                        nse_signal = {
                            "action": direction,  # BUY or SELL
                            "confidence": trade_signal.get('strength', 0.5) / 5.0,  # Normalize strength to 0-1
                            "source": "Engine1"
                        }
                    
                    # Get MCX signal if MCX symbol
                    if is_mcx and hasattr(self, 'current_spot_price') and self.current_spot_price:
                        try:
                            mcx_result = get_mcx_signal(opportunity['symbol'], self.current_spot_price, 0, 0)
                            # Map MCX signals to standard actions
                            mcx_signal_raw = mcx_result.get('signal')
                            action_mapping = {
                                "LONG": "BUY",
                                "SHORT": "SELL",
                                "NEUTRAL": None
                            }
                            mcx_action = action_mapping.get(mcx_signal_raw)
                            
                            if mcx_action:  # Only include if not NEUTRAL
                                mcx_signal = {
                                    "action": mcx_action,
                                    "confidence": mcx_result.get('confidence', 0),
                                    "source": "MCX_Engine"
                                }
                            else:
                                mcx_signal = None  # NEUTRAL signals don't contribute
                        except:
                            mcx_signal = None
                    
                    # Combine signals using Combined Intelligence
                    combined = get_combined_signal(nse_signal, mcx_signal)
                    
                    # DECISION LOGGING (CRITICAL FOR OPTIMIZATION)
                    trade_taken = False
                    skip_reason = None
                    
                    # SAFETY CHECKS
                    if not combined["action"]:
                        skip_reason = f"No agreement between signals (action=None)"
                    elif combined["confidence"] < 0.75:
                        skip_reason = f"Weak confidence {combined['confidence']:.2f} (requires 0.75+)"
                    else:
                        trade_taken = True
                    
                    # DECISION LOG (VERY IMPORTANT)
                    expected_outcome = "UNKNOWN"  # Manual tag after observation
                    
                    print(f"""
================================================================================
                    DECISION LOG
================================================================================
Symbol: {opportunity['symbol']}
Strike: {opportunity['strike']}
Direction: {direction}

NSE Signal: {nse_signal}
MCX Signal: {mcx_signal}

Combined: {combined}

Decision: {"EXECUTED" if trade_taken else "SKIPPED"}

Reason:
- Confidence: {combined['confidence']}
- Action: {combined['action']}
- Skip Reason: {skip_reason if skip_reason else 'None'}
- MCX Available: {'Yes' if mcx_signal else 'No'}
- Market Type: {'MCX' if is_mcx else 'NSE'}
- Expected Outcome (manual): {expected_outcome}
================================================================================
""")
                    
                    if not trade_taken:
                        logger.warning(f"SKIPPING TRADE - {skip_reason}")
                        time.sleep(5)
                        continue
                    
                    # Print clean dashboard
                    self.print_clean_dashboard()
                    
                    logger.info(f"Selected: {opportunity['symbol']} {opportunity['strike']} {direction} @ ₹{option_price} (Expiry: {expiry}, PCR: {opportunity['pcr']:.2f}, Buildup: {opportunity['buildup_pattern']}, Strength: {opportunity['strength']})")
                    logger.info(f"[COMBINED] Action: {combined['action']} | Confidence: {combined['confidence']:.2f} | Reason: {combined['reason']}")

                    if self.execute_trade(opportunity['symbol'], opportunity['strike'], direction, option_price, trade_signal):
                        trade_count += 1
                    else:
                        logger.error("Failed to execute trade, will retry in 5 seconds")
                        time.sleep(5)
                        continue
                else:
                    logger.warning("No suitable opportunity found, waiting 5 seconds")
                    time.sleep(5)
                    continue

            # Monitor active trade
            if self.trade_active:
                should_continue = self.monitor_trade()
                if not should_continue:
                    # Trade closed, wait before selecting new strike
                    logger.info("Trade closed, waiting 5 seconds before selecting new strike...")
                    time.sleep(5)
                else:
                    # Continue monitoring, check every 5 seconds
                    time.sleep(5)

        # Market closed - save trade history
        self.save_trade_history()

        # Market closed
        logger.info("="*80)
        logger.info("MARKET CLOSED - TRADING DAY ENDED")
        logger.info("="*80)
        logger.info(f"Total Trades: {trade_count}")
        logger.info(f"Starting Capital: {self.start_capital}")
        logger.info(f"Ending Capital: {self.current_capital}")
        logger.info(f"Day P&L: {self.current_capital - self.start_capital:+.2f}")
        logger.info("="*80)

    def save_trade_history(self):
        """Save trade history to file for EOD analysis"""
        try:
            with open('single_strike_trade_history.json', 'w') as f:
                json.dump({
                    'trading_session': {
                        'start_capital': self.start_capital,
                        'end_capital': self.current_capital,
                        'total_pnl': self.current_capital - self.start_capital,
                        'total_trades': len(self.trade_history),
                        'date': datetime.now().strftime('%Y-%m-%d')
                    },
                    'trades': self.trade_history
                }, f, indent=2)
            logger.info("Trade history saved to single_strike_trade_history.json")
        except Exception as e:
            logger.error(f"Error saving trade history: {e}")

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
    trader.run_trading_day()
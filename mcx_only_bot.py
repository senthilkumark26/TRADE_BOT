"""
MCX-Only Trading Bot
Dedicated to commodity trading (CRUDEOIL, NATGAS)
No internal signal generation for NSE
"""

import json
import csv
import time
import logging
import asyncio
import threading
import signal
from datetime import datetime, time as dt_time
import sys
import os

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Add services directory to path
services_dir = 'services'
if services_dir not in sys.path:
    sys.path.append(services_dir)

from kite.kite_client import KiteClient
from services.trade_manager_service.service import TradeManagerService
from services.execution_brain_service.service import ExecutionBrainService
from services.smart_strike_service.service import SmartStrikeService
from services.breakout_entry_service import BreakoutEntryService
from wrappers.risk_wrapper import can_execute_trade, update_trade_result, reset_daily_limits, get_risk_status
from risk.risk_management import get_risk_management_service
from mcx.mcx_wrapper import get_mcx_signal, get_mcx_support_resistance
from config.market_config import (
    get_symbol_config,
    calculate_volatility_adjusted_tp_sl,
    GLOBAL_CONFIG
)
from mcx.mcx_options_safety import (
    mcx_options_filter,
    select_mcx_option_strike,
    select_mcx_like_nifty,
    mcx_direction_module,
    get_mcx_option_chain,
    validate_mcx_option_trade,
    create_mcx_option_token_map,
    save_mcx_token_map
)
from services.watchdog_service.service import get_watchdog_service

# MCX Lot Size Configuration (PRODUCTION VALUES)
# Based on MCX official specifications
MCX_LOT_SIZES = {
    "CRUDEOIL": 100,      # Crude Oil - 100 barrels per lot
    "NATURALGAS": 1250,  # Natural Gas - 1250 mmBtu per lot
    "GOLDM": 10,         # Gold Mini - 10 grams per lot
    "SILVERM": 30,       # Silver Mini - 30 kg per lot
    "COPPER": 1000,      # Copper - 1000 kg per lot
    "ZINC": 5000,        # Zinc - 5000 kg per lot
    "LEAD": 5000,        # Lead - 5000 kg per lot
    "ALUMINIUM": 5000    # Aluminium - 5000 kg per lot
}


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class MCXOnlyBot:
    def __init__(self, investment_amount=None, mode="futures"):
        # Load config from current directory
        config_path = os.path.join(current_dir, 'config.json')
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        # MCX FIX: Read investment_amount from config.json (not hardcoded)
        if investment_amount is None:
            investment_amount = self.config.get('investment_amount', 30000)
        
        self.investment_amount = investment_amount
        self.mode = mode  # "futures" or "options"
        self.paper_trading = self.config.get("paper_trading", True)
        
        # Initialize Risk Management Service (same as single_strike_trader)
        try:
            self.risk_service = get_risk_management_service(investment_amount)
            logger.info("Risk Management Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Risk Management Service: {e}")
            logger.warning("Continuing without risk management - trading will NOT have risk protection!")
            self.risk_service = None
        
        # Trading parameters (same as single_strike_trader)
        self.start_capital = investment_amount
        self.current_capital = investment_amount
        logger.info(f"Capital initialized: ₹{self.start_capital}")
        
        # Set file paths
        self.csv_file = os.path.join(current_dir, 'mcx_calls.csv')
        self.history_file = os.path.join(current_dir, 'mcx_trade_history.json')
        
        logger.info("=" * 80)
        logger.info("MCX-ONLY TRADING BOT")
        logger.info("=" * 80)
        logger.info(f"Investment: ₹{investment_amount}")
        logger.info(f"Mode: {'PAPER TRADING' if self.paper_trading else 'LIVE TRADING'}")
        logger.info(f"Trading Mode: {self.mode.upper()}")
        logger.info("Signal Source: MCX Engine Only (Commodities)")
        if self.mode == "futures":
            logger.info("Instruments: CRUDEOIL, NATGAS, GOLDM, SILVERM (FUTURES)")
        else:
            logger.info("Instruments: CRUDEOIL, NATURALGAS, GOLDM, SILVERM (OPTIONS - CRUDEOIL BIG CONTRACT)")
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
        
        # Initialize Risk Management
        logger.info("Risk Management initialized (using risk_wrapper)")
        
        # Initialize Trade Manager
        try:
            self.trade_manager = TradeManagerService(
                max_daily_loss=3000,
                config=self.config
            )
            logger.info("Trade Manager Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Trade Manager Service: {e}")
            logger.warning("Continuing without Trade Manager - trade monitoring will be limited!")
            self.trade_manager = None
        
        # Initialize Execution Brain Service (entry timing, momentum filters)
        try:
            self.execution_brain = ExecutionBrainService()  # FIXED: Removed is_paper parameter
            logger.info("Execution Brain Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Execution Brain Service: {e}")
            logger.warning("Continuing without Execution Brain - entry timing filters disabled!")
            self.execution_brain = None
        
        # Initialize Smart Strike Service (advanced strike selection)
        try:
            self.smart_strike = SmartStrikeService()
            logger.info("Smart Strike Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Smart Strike Service: {e}")
            logger.warning("Continuing without Smart Strike - using basic strike selection!")
            self.smart_strike = None
        
        # Initialize Breakout Entry Service (breakout detection)
        try:
            self.breakout_entry = BreakoutEntryService()
            logger.info("Breakout Entry Service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Breakout Entry Service: {e}")
            logger.warning("Continuing without Breakout Entry - breakout detection disabled!")
            self.breakout_entry = None
        
        # Market hours (MCX: 09:00-23:30)
        self.market_open = dt_time(9, 0)
        self.market_close = dt_time(23, 30)
        
        # Trade tracking
        self.active_trades = {}
        self.trade_history = []
        
        # Live price tracking for MCX futures (for options direction)
        self.mcx_live_prices = {}  # symbol -> current price
        self.mcx_price_history = {}  # symbol -> list of recent prices (for momentum)
        self.mcx_contracts_cache = {}  # symbol -> contract info (to avoid repeated API calls)
        self.mcx_contracts_cache_time = None
        self.mcx_contracts_cache_duration = 300  # Cache contracts for 5 minutes
        
        # Warm-up period configuration (production trading system requirement)
        self.min_candles_for_signals = 20  # Minimum candles before generating signals
        self.warmup_complete = False  # Track warm-up status
        
        # Historical data pre-loading (instant startup during market hours)
        self.use_historical_data = True  # Enable historical data pre-loading
        
        # DEBUG MODE for system validation (force trades to test TP/SL)
        self.debug_mode = GLOBAL_CONFIG.get("debug_mode", True)  # Use global config
        
        # MCX early breakout tracking (for execution logic priority)
        self.early_breakout_detected = {}  # symbol -> bool
        
        # CSV file for MCX call tracking (already set in __init__)
        self._init_csv_file()
        
        # MCX option token map for rendering
        self.mcx_token_map = {}
        self.mcx_token_map_file = os.path.join(current_dir, 'mcx_option_token_map.json')
        
        # Initialize Watchdog Service (health monitoring - enabled by default)
        try:
            self.watchdog_service = get_watchdog_service(check_interval=120)  # 2 minute intervals
            self.watchdog_service.start_monitoring()  # Start by default (logs only, no CLI output)
            logger.info("Watchdog Service initialized and started (health monitoring every 2 minutes - logs only, no CLI output)")
        except Exception as e:
            logger.error(f"Failed to initialize Watchdog Service: {e}")
            self.watchdog_service = None
        
        logger.info(f"Market hours: {self.market_open} - {self.market_close}")
    
    def update_mcx_live_prices(self):
        """Update live prices for MCX futures using REST polling with caching"""
        mcx_symbols_config = [
            ("CRUDEOIL", "CRUDEOIL"),
            ("NATGAS", "NATURALGAS"),
            ("GOLDM", "GOLDM"),
            ("SILVERM", "SILVERM")
        ]
        
        # Check if we need to refresh contract cache
        current_time = time.time()
        if (self.mcx_contracts_cache_time is None or 
            (current_time - self.mcx_contracts_cache_time) > self.mcx_contracts_cache_duration):
            logger.info("Refreshing MCX contracts cache...")
            for symbol, mcx_symbol in mcx_symbols_config:
                try:
                    contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                    if contract:
                        self.mcx_contracts_cache[symbol] = contract  # Cache by symbol name (CRUDEOIL, NATGAS, etc.)
                except Exception as e:
                    logger.debug(f"Error caching contract for {symbol}: {e}")
            self.mcx_contracts_cache_time = current_time
            logger.info(f"MCX contracts cache refreshed for {len(self.mcx_contracts_cache)} symbols")
        
        # Update prices using cached contracts
        for symbol, mcx_symbol in mcx_symbols_config:
            try:
                # Use cached contract if available (cache key = symbol name)
                if symbol in self.mcx_contracts_cache:
                    contract = self.mcx_contracts_cache[symbol]
                else:
                    # Fallback to fresh fetch if not cached
                    contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                    if contract:
                        self.mcx_contracts_cache[symbol] = contract  # Cache by symbol name
                
                if not contract:
                    logger.debug(f"No contract found for {symbol}")
                    continue
                
                token = contract['instrument_token']
                quote = self.kite_client.get_quote(token)
                if quote and quote.get('last_price'):
                    current_price = quote.get('last_price')
                    
                    # Update live price
                    self.mcx_live_prices[symbol] = current_price
                    
                    # Update price history (keep last 20 prices for momentum)
                    if symbol not in self.mcx_price_history:
                        self.mcx_price_history[symbol] = []
                    
                    self.mcx_price_history[symbol].append(current_price)
                    if len(self.mcx_price_history[symbol]) > 20:
                        self.mcx_price_history[symbol].pop(0)
                    
                    # Debug logging for price collection
                    logger.info(f"[PRICE UPDATE] {symbol}: Price={current_price:.2f}, History count={len(self.mcx_price_history[symbol])}")
                else:
                    logger.warning(f"[PRICE UPDATE] {symbol}: No valid quote data")
                    
            except Exception as e:
                logger.error(f"[PRICE UPDATE] Error updating live price for {symbol}: {e}")
        
        # Check if warm-up is complete (all symbols have sufficient data)
        self._check_warmup_status()
    
    def _check_warmup_status(self):
        """Check if warm-up period is complete (production trading system requirement)"""
        if self.warmup_complete:
            return  # Already complete
        
        mcx_symbols = ["CRUDEOIL", "NATGAS", "GOLDM", "SILVERM"]
        all_symbols_ready = True
        
        # Log detailed progress for each symbol
        progress_details = []
        for symbol in mcx_symbols:
            if symbol in self.mcx_price_history:
                count = len(self.mcx_price_history[symbol])
                status = f"{count}/{self.min_candles_for_signals}"
                if count < self.min_candles_for_signals:
                    all_symbols_ready = False
                progress_details.append(f"{symbol}={status}")
            else:
                all_symbols_ready = False
                progress_details.append(f"{symbol}=0/{self.min_candles_for_signals}")
        
        if all_symbols_ready:
            self.warmup_complete = True
            logger.info("=" * 80)
            logger.info("WARM-UP COMPLETE - Ready for signal generation")
            logger.info("=" * 80)
        else:
            # Log detailed progress
            logger.info(f"Warm-up progress: {', '.join(progress_details)}")
    
    def preload_historical_data(self):
        """Pre-load historical data for instant startup (production trading system)"""
        if not self.use_historical_data:
            logger.info("Historical data pre-loading disabled - using real-time warm-up")
            return False
        
        # Check if market has been open long enough to have sufficient data
        now = datetime.now()
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        minutes_since_open = (now - market_open).total_seconds() / 60
        
        if minutes_since_open < self.min_candles_for_signals:
            logger.info(f"Market open only {minutes_since_open:.0f} minutes ago - insufficient historical data, using real-time warm-up")
            return False
        
        logger.info("=" * 80)
        logger.info("PRODUCTION TRADING SYSTEM: Historical Data Pre-loading")
        logger.info(f"Market open {minutes_since_open:.0f} minutes ago - attempting to load historical data")
        logger.info("=" * 80)
        
        mcx_symbols_config = [
            ("CRUDEOIL", "CRUDEOIL"),
            ("NATGAS", "NATURALGAS"),
            ("GOLDM", "GOLDM"),
            ("SILVERM", "SILVERM")
        ]
        
        success_count = 0
        
        for symbol, mcx_symbol in mcx_symbols_config:
            try:
                # Get contract
                contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                if not contract:
                    logger.warning(f"No contract found for {symbol}")
                    continue
                
                token = contract['instrument_token']
                
                # Fetch historical data for today (minute candles)
                today = now.date()
                from_date = today
                to_date = today
                
                logger.info(f"Fetching historical data for {symbol}...")
                historical_data = self.kite_client.get_historical_data(
                    token, "minute", from_date, to_date
                )
                
                if not historical_data or len(historical_data) < self.min_candles_for_signals:
                    logger.warning(f"Insufficient historical data for {symbol}: {len(historical_data) if historical_data else 0} candles")
                    continue
                
                # Extract last N close prices
                recent_candles = historical_data[-self.min_candles_for_signals:]
                close_prices = [candle['close'] for candle in recent_candles]
                
                # Populate price history
                self.mcx_price_history[symbol] = close_prices
                self.mcx_live_prices[symbol] = close_prices[-1]  # Latest price
                
                success_count += 1
                logger.info(f"✓ {symbol}: Loaded {len(close_prices)} historical candles (Latest: {close_prices[-1]:.2f})")
                
            except Exception as e:
                logger.error(f"Error loading historical data for {symbol}: {e}")
        
        if success_count == len(mcx_symbols_config):
            logger.info("=" * 80)
            logger.info("HISTORICAL DATA PRE-LOAD COMPLETE - All symbols loaded")
            logger.info("Warm-up bypassed - Ready for signal generation")
            logger.info("=" * 80)
            self.warmup_complete = True
            return True
        else:
            logger.warning(f"Partial historical data load: {success_count}/{len(mcx_symbols_config)} symbols")
            logger.info("Falling back to real-time warm-up for remaining symbols")
            return False
    
    def _init_csv_file(self):
        """Initialize CSV file with headers if it doesn't exist"""
        try:
            import os
            if not os.path.exists(self.csv_file):
                with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'timestamp',
                        'symbol',
                        'signal',
                        'confidence',
                        'entry',
                        'sl',
                        'target',
                        'status',
                        'executed_at',
                        'pnl',
                        'exit_price',
                        'exit_reason',
                        'expected_outcome',
                        'source'
                    ])
                logger.info(f"CSV file created: {self.csv_file}")
            else:
                logger.info(f"CSV file exists: {self.csv_file}")
        except Exception as e:
            logger.error(f"Error initializing CSV file: {e}")
    
    def _log_call_to_csv(self, signal, status='RECEIVED', executed_at=None, pnl=0, exit_price=None, exit_reason=None, expected_outcome='', source='MCX'):
        """Log MCX call to CSV file"""
        try:
            with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    signal.get('symbol', ''),
                    signal.get('signal', ''),
                    signal.get('confidence', 0),
                    signal.get('entry', ''),
                    signal.get('sl', ''),
                    signal.get('target', ''),
                    status,
                    executed_at if executed_at else '',
                    pnl,
                    exit_price if exit_price else '',
                    exit_reason if exit_reason else '',
                    expected_outcome,
                    source
                ])
            logger.info(f"Call logged to CSV: {signal['symbol']} {signal['signal']} - {status}")
        except Exception as e:
            logger.error(f"Error logging to CSV: {e}")
    
    def _update_call_status(self, signal, status, pnl=0, exit_price=None, exit_reason=None, expected_outcome=''):
        """Update call status in CSV (find and update the last matching call)"""
        try:
            # Read all rows
            rows = []
            with open(self.csv_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader)
                rows = list(reader)
            
            # Find and update the last matching call
            for i in range(len(rows) - 1, -1, -1):
                row = rows[i]
                if (row[1] == signal.get('symbol', '') and 
                    row[2] == signal.get('signal', '') and
                    row[7] == 'RECEIVED'):  # Only update RECEIVED calls
                    # Update status
                    row[7] = status
                    row[8] = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'EXECUTED' else ''
                    row[9] = pnl
                    row[10] = exit_price if exit_price else ''
                    row[11] = exit_reason if exit_reason else ''
                    row[12] = expected_outcome  # Add expected_outcome
                    break
            
            # Write back
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            
            logger.info(f"Call status updated in CSV: {signal['symbol']} {signal['signal']} - {status}")
        except Exception as e:
            logger.error(f"Error updating CSV status: {e}")
    
    def _update_trade_exit_in_csv(self, symbol, entry_price, exit_price, sl, target, pnl, exit_reason):
        """Update trade exit details in CSV (find EXECUTED trade and add exit details)"""
        try:
            # Read all rows
            rows = []
            with open(self.csv_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader)
                rows = list(reader)
            
            # Find and update the last matching EXECUTED call
            for i in range(len(rows) - 1, -1, -1):
                row = rows[i]
                if (row[1] == symbol and
                    row[7] == 'EXECUTED' and
                    row[9] == '0'):  # Only update EXECUTED calls with P&L = 0 (not yet closed)
                    # Update exit details
                    row[5] = sl  # Update SL
                    row[6] = target  # Update Target
                    row[9] = pnl  # Update P&L
                    row[10] = exit_price  # Update exit price
                    row[11] = exit_reason  # Update exit reason
                    logger.info(f"Trade exit updated in CSV: {symbol} | P&L: {pnl} | Exit: {exit_price} | Reason: {exit_reason}")
                    break
            
            # Write back
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            
        except Exception as e:
            logger.error(f"Error updating trade exit in CSV: {e}")
    
    def is_market_open(self):
        """Check if MCX market is currently open"""
        current_time = datetime.now().time()
        return self.market_open <= current_time <= self.market_close
    
    def execute_trade(self, signal):
        """Execute trade based on MCX signal"""
        logger.info(">>> EXECUTE TRADE START <<<")
        try:
            symbol = signal['symbol']
            mcx_signal = signal['signal']
            confidence = signal.get('confidence', 0)
            
            logger.info(f"Executing trade: {symbol} {mcx_signal} (Confidence: {confidence:.2f})")
            
            # PRODUCTION FIX: Execution guard - validate entry price before proceeding
            entry_price = signal.get('entry', 0)
            if entry_price <= 0:
                logger.warning(f"Invalid entry price ({entry_price}) - skipping trade execution")
                self._update_call_status(signal, status='BLOCKED', exit_reason='Invalid entry price')
                return False
            
            # MCX FIX: Only allow one trade at a time (capital concentration)
            if self.active_trades:
                active_symbols = list(self.active_trades.keys())
                logger.warning(f"[TRADE LIMIT] Already have {len(self.active_trades)} active trade(s): {active_symbols}")
                logger.warning(f"[TRADE LIMIT] Skipping new trade for {symbol} - waiting for existing trades to close")
                self._update_call_status(signal, status='BLOCKED', exit_reason='Trade limit: Already have active trades')
                return False
            
            # CRITICAL FIX: Log option premium vs futures price
            option_price = signal.get('entry', 0)
            futures_price = signal.get('futures_price', 0)
            if futures_price > 0:
                logger.info(f"[TRADE EXECUTION] Option Premium: {option_price:.2f} | Futures Price: {futures_price:.2f}")
            
            # Log call to CSV as RECEIVED
            self._log_call_to_csv(signal, status='RECEIVED')
            
            # Check risk limits
            try:
                can_trade = can_execute_trade()
                if not can_trade:
                    logger.error("Trade blocked by risk management")
                    self._update_call_status(signal, status='BLOCKED', exit_reason='Risk Management')
                    return False
            except Exception as e:
                logger.error(f"Error checking risk limits: {e}")
                logger.warning("Proceeding without risk check - trading may exceed limits!")
                # Continue anyway but log the risk
            
            # Execution Brain Service - Entry timing and momentum validation
            if self.execution_brain:
                try:
                    logger.info(">>> EXECUTION BRAIN CHECK <<<")
                    # MCX FIX: Ensure symbol is in signal package for timing filter
                    signal_package = signal.copy()
                    if 'symbol' not in signal_package:
                        signal_package['symbol'] = symbol
                    
                    # MCX FIX: Add MCX-specific fields for scoring
                    signal_package['early_breakout'] = self.early_breakout_detected.get(symbol, False)
                    signal_package['breakdown'] = signal.get('breakdown', False)
                    signal_package['market_type'] = signal.get('market_type', 'TRENDING')
                    signal_package['momentum'] = signal.get('momentum', 'WEAK')
                    
                    # Calculate price move for MCX scoring
                    if symbol in self.mcx_price_history and len(self.mcx_price_history[symbol]) >= 2:
                        price_history = self.mcx_price_history[symbol]
                        price_move = (price_history[-1] - price_history[-2]) / price_history[-2]
                        signal_package['price_move'] = price_move
                    else:
                        signal_package['price_move'] = 0
                    
                    # Add breakout flag
                    signal_package['breakout'] = signal.get('breakout', False)
                    
                    # Calculate range expansion (if price data available)
                    if 'high' in signal and 'low' in signal and 'entry' in signal:
                        current_price = signal['entry']
                        high = signal['high']
                        low = signal['low']
                        if high > low:
                            range_size = high - low
                            range_expansion = (current_price - low) / current_price if current_price > 0 else 0
                            signal_package['range_expansion'] = range_expansion
                        else:
                            signal_package['range_expansion'] = 0
                    else:
                        signal_package['range_expansion'] = 0
                    
                    execution_result = self.execution_brain.evaluate_execution(signal_package)
                    
                    if execution_result['decision'] != 'EXECUTE':
                        reason = execution_result.get('reason', 'Execution brain rejected trade')
                        logger.warning(f"[EXECUTION BRAIN] Trade rejected: {reason}")
                        self._update_call_status(signal, status='BLOCKED', exit_reason=f'Execution Brain: {reason}')
                        return False
                    
                    logger.info(f"[EXECUTION BRAIN] Trade approved: {execution_result.get('reason', 'No specific reason')}")
                except Exception as e:
                    logger.error(f"Error in Execution Brain evaluation: {e}")
                    logger.warning("Proceeding without Execution Brain check!")
            
            # MCX-SPECIFIC MOMENTUM FILTER (Stronger than NSE)
            # MCX needs stronger momentum confirmation (0.25% vs 0.1% for NSE)
            if self.mode == "futures" and symbol in self.mcx_price_history:
                try:
                    logger.info(">>> MCX MOMENTUM FILTER <<<")
                    price_history = self.mcx_price_history[symbol]
                    if len(price_history) >= 5:
                        recent_prices = price_history[-5:]
                        price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                        
                        # MCX-specific threshold: 0.12% (relaxed for earlier entries)
                        momentum_threshold = 0.0012  # 0.12% (relaxed for MCX)
                        
                        # Check if momentum aligns with signal direction
                        if mcx_signal == "LONG" and price_change < momentum_threshold:
                            logger.warning(f"[MCX MOMENTUM] Weak bullish momentum: {price_change*100:.2f}% < {momentum_threshold*100:.2f}%")
                            self._update_call_status(signal, status='BLOCKED', exit_reason=f'Weak momentum: {price_change*100:.2f}%')
                            return False
                        elif mcx_signal == "SHORT" and price_change > -momentum_threshold:
                            logger.warning(f"[MCX MOMENTUM] Weak bearish momentum: {price_change*100:.2f}% > {-momentum_threshold*100:.2f}%")
                            self._update_call_status(signal, status='BLOCKED', exit_reason=f'Weak momentum: {price_change*100:.2f}%')
                            return False
                        else:
                            logger.info(f"[MCX MOMENTUM] Strong momentum confirmed: {price_change*100:.2f}%")
                    else:
                        logger.warning("[MCX MOMENTUM] Insufficient price history for momentum check")
                except Exception as e:
                    logger.error(f"Error in MCX momentum filter: {e}")
                    logger.warning("Proceeding without MCX momentum check!")
            
            # Breakout Entry Service - Breakout confirmation
            if self.breakout_entry and self.mode == "futures":
                try:
                    logger.info(">>> BREAKOUT ENTRY CHECK <<<")
                    # Get current price from signal or live prices
                    current_price = signal.get('entry', 0)
                    if symbol in self.mcx_live_prices:
                        current_price = self.mcx_live_prices[symbol]
                    
                    breakout_result = self.breakout_entry.check_breakout(
                        symbol=symbol,
                        current_price=current_price,
                        signal=mcx_signal,
                        price_history=self.mcx_price_history.get(symbol, [])
                    )
                    
                    if not breakout_result['is_breakout']:
                        reason = breakout_result.get('reason', 'No breakout detected')
                        logger.warning(f"[BREAKOUT ENTRY] Trade rejected: {reason}")
                        self._update_call_status(signal, status='BLOCKED', exit_reason=f'Breakout Entry: {reason}')
                        return False
                    
                    logger.info(f"[BREAKOUT ENTRY] Breakout confirmed: {breakout_result.get('reason', 'Breakout detected')}")
                except Exception as e:
                    logger.error(f"Error in Breakout Entry check: {e}")
                    logger.warning("Proceeding without Breakout Entry check!")
            
            # Smart Strike Service - DISABLED for MCX futures (not needed for commodity futures)
            # Only enabled for MCX options mode (rare)
            if self.smart_strike and self.mode == "options":
                try:
                    logger.info(">>> SMART STRIKE SELECTION (OPTIONS MODE ONLY) <<<")
                    # Get current option chain
                    option_chain = get_mcx_option_chain(self.kite_client, symbol)
                    
                    if option_chain:
                        # Use smart strike to select best option
                        selected_option = self.smart_strike.select_strike_smart(
                            option_chain=option_chain,
                            spot_price=signal.get('futures_price', signal.get('entry', 0)),
                            option_type="CE" if mcx_signal == "LONG" else "PE"
                        )

                        if selected_option:
                            logger.info(f"[SMART STRIKE] Selected better strike: {selected_option.get('tradingsymbol', 'N/A')}")
                            # Update signal with smart strike selection
                            signal['selected_option'] = selected_option
                            signal['entry'] = selected_option.get('last_price', signal.get('entry', 0))
                        else:
                            logger.warning("[SMART STRIKE] No better strike found, using original strike")
                    else:
                        logger.warning("[SMART STRIKE] No option chain available, using original strike")
                except Exception as e:
                    logger.error(f"Error in Smart Strike selection: {e}")
                    logger.warning("Proceeding without Smart Strike selection!")
            else:
                # MCX FUTURES: Skip option chain entirely (heavy + unnecessary)
                logger.info("[MCX FUTURES] Skipping option chain (futures trading - faster execution)")
                # Ensure signal has basic structure for futures
                if 'selected_option' not in signal:
                    signal['selected_option'] = {
                        'tradingsymbol': f"{symbol}_FUT",
                        'lot_size': MCX_LOT_SIZES.get(symbol, 1),  # MCX FIX: Use official lot sizes
                        'instrument_token': signal.get('instrument_token', '')
                    }
            
            # MCX FIX: Ensure selected_option has proper lot size for options trading
            if 'selected_option' in signal and signal['selected_option'].get('lot_size', 1) == 1:
                # Update lot size from MCX configuration
                symbol_for_lot = signal.get('symbol', symbol)
                signal['selected_option']['lot_size'] = MCX_LOT_SIZES.get(symbol_for_lot, 1)
            
            # Send to Trade Manager with enhanced signal
            try:
                logger.info(">>> STEP 1: CALCULATE TP/SL <<<")
                # CRITICAL: Calculate TP/SL using market configuration system
                entry_price = signal.get('entry', 0)
                
                # Get symbol-specific configuration
                try:
                    symbol_config = get_symbol_config("MCX", symbol)
                    logger.info(f"Using market config for {symbol}: {symbol_config['description']}")
                except Exception as e:
                    logger.warning(f"Could not get config for {symbol}, using defaults: {e}")
                    symbol_config = None
                
                # Calculate volatility-adjusted TP/SL
                if symbol_config:
                    tp, sl = calculate_volatility_adjusted_tp_sl(entry_price, symbol_config)
                    
                    # MCX-SPECIFIC RISK LOGIC (Commodities move faster, need tighter stops)
                    # MCX = Speed game, not precision game like NSE options
                    if self.mode == "futures":
                        # Tighter stops for MCX futures (fast-moving commodities)
                        risk_pct = 0.03   # 3% SL (tight for MCX speed)
                        reward_pct = 0.06  # 6% TP (1:2 risk-reward for trending commodities)
                        logger.info("[MCX FUTURES] Using tight risk logic: 3% SL, 6% TP (1:2 RR)")
                    else:
                        # Standard logic for MCX options
                        risk_pct = 0.12   # 12% SL (production realistic)
                        reward_pct = 0.30 # 30% TP (1:2.5 risk-reward ratio)
                        logger.info("[MCX OPTIONS] Using standard risk logic: 12% SL, 30% TP")
                    
                    tp = entry_price * (1 + reward_pct)
                    sl = entry_price * (1 - risk_pct)
                    
                    # CRITICAL FIX: For BUYING options, we always want premium to INCREASE for profit
                    # Whether CALL or PUT, we're buying the option, so:
                    # - Target should be HIGHER than entry (want option premium to go up)
                    # - Stop Loss should be LOWER than entry (don't want option premium to go down too much)
                    # The difference is in the directional signal (CALL = underlying up, PUT = underlying down)
                    # But for the option premium itself, we always want it to increase!
                    
                    # No adjustment needed - both CALL and PUT options should have:
                    # Target > Entry (want premium to increase)
                    # SL < Entry (limit premium decrease)
                else:
                    # Fallback to MCX-specific values (same logic as above)
                    if self.mode == "futures":
                        # MCX futures tight stops
                        risk_pct = 0.03   # 3% SL
                        reward_pct = 0.06  # 6% TP (1:2 RR)
                        logger.info("[MCX FUTURES FALLBACK] Using tight risk logic: 3% SL, 6% TP")
                    else:
                        # MCX options standard logic
                        risk_pct = 0.12   # 12% SL
                        reward_pct = 0.30 # 30% TP (1:2.5 RR)
                        logger.info("[MCX OPTIONS FALLBACK] Using standard risk logic: 12% SL, 30% TP")
                    
                    tp = entry_price * (1 + reward_pct)
                    sl = entry_price * (1 - risk_pct)
                
                logger.info(">>> STEP 2: TP/SL CALCULATION DONE <<<")
                
                logger.info(">>> STEP 3: CALCULATE POSITION SIZE (Using Risk Service) <<<")
                # Use Risk Management Service for position sizing (same as single_strike_trader)
                lot_size = signal.get('selected_option', {}).get('lot_size', 1)
                
                if self.risk_service is None:
                    logger.warning("Risk Service not available - using fallback position sizing")
                    # Fallback: simple calculation
                    actual_lots = 1
                    cost_per_lot = entry_price * lot_size
                    total_cost = cost_per_lot * actual_lots
                    logger.info(f"Fallback position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")
                else:
                    position_calc = self.risk_service.calculate_position_size(entry_price, lot_size, self.current_capital)
                    
                    if not position_calc.get("success"):
                        logger.error(f"Position sizing failed: {position_calc.get('error')}")
                        logger.warning("Using fallback position sizing")
                        actual_lots = 1
                        cost_per_lot = entry_price * lot_size
                        total_cost = cost_per_lot * actual_lots
                    else:
                        actual_lots = position_calc["actual_lots"]
                        cost_per_lot = position_calc["cost_per_lot"]
                        total_cost = position_calc["total_cost"]
                        
                        # MCX FIX: Log risk warning if minimum lot was enforced
                        if position_calc.get("warning"):
                            logger.warning(f"[RISK WARNING] {position_calc['warning']}")
                
                logger.info(f"Position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")
                
                logger.info(">>> STEP 4: CALCULATE RISK PARAMETERS (Using Risk Service) <<<")
                # Use Risk Management Service for risk parameters (same as single_strike_trader)
                if self.risk_service is None:
                    logger.warning("Risk Service not available - using fallback risk parameters")
                    # PRODUCTION FIX: Use production-standard fallback values (12% SL, 30% TP)
                    risk_pct = 0.12
                    reward_pct = 0.30
                    stoploss_price = entry_price * (1 - risk_pct)
                    target_price = entry_price * (1 + reward_pct)
                    risk_amount = (entry_price - stoploss_price) * actual_lots * lot_size
                    logger.info(f"Fallback risk parameters (production standard): SL {risk_pct*100:.0f}%, TP {reward_pct*100:.0f}%, Risk ₹{risk_amount:.2f}")
                else:
                    risk_params = self.risk_service.calculate_risk_parameters(entry_price, actual_lots, mcx_signal, self.current_capital, symbol)
                    
                    if not risk_params.get("success"):
                        logger.error(f"Risk parameter calculation failed: {risk_params.get('error')}")
                        logger.warning("Using production-standard fallback risk parameters")
                        risk_pct = 0.12
                        reward_pct = 0.30
                        stoploss_price = entry_price * (1 - risk_pct)
                        target_price = entry_price * (1 + reward_pct)
                        risk_amount = (entry_price - stoploss_price) * actual_lots * lot_size
                    else:
                        stoploss_price = risk_params["stoploss_price"]
                        target_price = risk_params["target_price"]
                        risk_amount = risk_params["risk_amount"]
                
                logger.info(f"Risk parameters: SL ₹{stoploss_price}, Target ₹{target_price}, Risk ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.3f}%)")
                
                logger.info(">>> STEP 5: ADD TO TRADE MANAGER <<<")
                
                logger.info(f"""
[RISK CALCULATION (Risk Service)]
Symbol: {symbol}
Option: {signal.get('selected_option', {}).get('tradingsymbol', '')}
Entry: {entry_price:.2f}
Target: {target_price:.2f} ({'+' if target_price > entry_price else ''}{((target_price - entry_price) / entry_price * 100):.1f}%)
Stop Loss: {stoploss_price:.2f} ({'+' if stoploss_price > entry_price else ''}{((stoploss_price - entry_price) / entry_price * 100):.1f}%)
Position Size: {actual_lots} lots
Cost Per Lot: ₹{cost_per_lot:.2f}
Total Cost: ₹{total_cost:.2f}
Risk Amount: ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.3f}%)
Capital Available: ₹{self.current_capital:.2f}
""")
                
                logger.info(">>> STEP 6: ADD TO TRADE MANAGER <<<")
                # Add trade to manager (using Trade Manager's TP/SL infrastructure)
                trade = {
                    "symbol": symbol,
                    "signal": "CALL" if mcx_signal == "LONG" else "PUT",  # Trade Manager expects CALL/PUT
                    "entry": entry_price,  # Now using option premium (fixed)
                    "futures_price": signal.get('futures_price', 0),  # Futures price for reference
                    "option_symbol": signal.get('selected_option', {}).get('tradingsymbol', ''),  # Option contract
                    "option_token": signal.get('selected_option', {}).get('instrument_token', ''),  # For price updates
                    "target": target_price,  # Use risk service calculated target
                    "sl": stoploss_price,  # Use risk service calculated SL
                    "expiry": "N/A",
                    "lot_size": actual_lots,  # Use risk service calculated lots
                    "entry_time": datetime.now(),  # MCX: Track entry time for fast exits
                    "initial_sl": stoploss_price,  # MCX: Track initial SL for trailing stops
                    "highest_profit": 0.0,  # MCX: Track highest profit for trailing stops
                    "status": "OPEN",  # FIXED: Explicitly set status to prevent auto-close
                }
                
                # Add to Trade Manager if available
                if self.trade_manager is None:
                    logger.warning("Trade Manager not available - trade will be tracked locally only")
                    self.active_trades[signal.get('symbol', '')] = trade
                else:
                    try:
                        self.trade_manager.add_trade(symbol, trade)  # FIXED: Pass symbol as first argument
                        logger.info("Trade added to Trade Manager successfully")
                    except Exception as e:
                        logger.error(f"Failed to add trade to Trade Manager: {e}")
                        logger.warning("Tracking trade locally instead")
                        self.active_trades[signal.get('symbol', '')] = trade
                
                logger.info(">>> STEP 7: UPDATE ACTIVE TRADES <<<")
                self.active_trades[symbol] = trade
                logger.info(f"Trade added to manager: {symbol} {mcx_signal}")
                
                logger.info(">>> STEP 8: UPDATE CSV STATUS <<<")
                # Update CSV status to EXECUTED
                self._update_call_status(signal, status='EXECUTED')
                logger.info(">>> STEP 9: CSV STATUS UPDATED <<<")
                return True
            except Exception as e:
                logger.error(f"Trade execution failed: {e}")
                self._update_call_status(signal, status='ERROR', exit_reason=str(e))
                logger.info(">>> EXECUTE TRADE END (FAILED) <<<")
                return False
                
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            self._update_call_status(signal, status='ERROR', exit_reason=str(e))
            logger.info(">>> EXECUTE TRADE END (ERROR) <<<")
            return False
        
        logger.info(">>> EXECUTE TRADE END (SUCCESS) <<<")
    
    def monitor_trades(self):
        """Monitor active trades and update prices (single pass, called by main loop)"""
        # QUIET MODE: Skip entering log (reduce noise)
        
        if not self.active_trades:
            return
        
        # QUIET MODE: Skip "Monitoring X trades" log (reduce noise)
        
        # Update prices for active trades (using Trade Manager's infrastructure)
        # FIXED: Iterate over list of keys to avoid "dictionary changed size during iteration" error
        for symbol in list(self.active_trades.keys()):
            trade = self.active_trades[symbol]
            try:
                # QUIET MODE: Skip "CHECKING TRADE" log (reduce noise)
                
                # For options trading, use option token instead of futures contract
                option_token = trade.get('option_token', '')
                option_symbol = trade.get('option_symbol', '')
                entry_price = trade.get('entry', 0)
                target = trade.get('target', 0)
                sl = trade.get('sl', 0)
                
                if option_token:
                    # Fetch option premium (correct approach for options trading)
                    option_quote = self.kite_client.get_quote(option_token)
                    if option_quote:
                        current_price = option_quote.get('last_price', 0)
                        
                        # Calculate P&L percentage (always current - entry for buying options)
                        if entry_price > 0:
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        else:
                            pnl_pct = 0

                        # Determine if SL is trailing (modified from initial)
                        initial_sl = trade.get('initial_sl', sl)
                        sl_label = "Trailing SL" if abs(sl - initial_sl) > 0.01 else "SL"

                        # CLI DISPLAY: Single line with key info
                        logger.info(f"[LIVE TRADE] {symbol} {option_symbol} | Entry: ₹{entry_price:.2f} | Current: ₹{current_price:.2f} | P&L: {pnl_pct:+.1f}% | Target: ₹{target:.2f} | {sl_label}: ₹{sl:.2f}")
                        
                        # MCX FAST EXIT LOGIC (Critical for commodity speed game)
                        entry_time = trade.get('entry_time')
                        if entry_time:
                            trade_duration = (datetime.now() - entry_time).total_seconds() / 60  # in minutes
                            
                            # MCX TIME EXIT: DISABLED - Trades only close on SL/TP hit
                            # # MCX TIME EXIT: Exit if trade duration > 15 minutes (MCX trades are short-lived)
                            # if trade_duration > 15:
                            #     logger.warning(f"[MCX FAST EXIT] {symbol} - Time exit triggered (duration: {trade_duration:.1f} min > 15 min)")
                            #     self.trade_manager.close_trade(symbol, current_price, reason="Time exit (15 min max)")
                            #     # Update CSV with exit details
                            #     pnl_amount = (current_price - entry_price)  # Absolute P&L
                            #     self._update_trade_exit_in_csv(symbol, entry_price, current_price, sl, target, pnl_amount, "Time exit (15 min max)")
                            #     del self.active_trades[symbol]
                            #     continue
                            
                            # INTELLIGENT EXIT: Time + Weak Market = Exit (Pro-Level Logic)
                            # Time alone should NOT close trade
                            # Time + Weak Market = Exit
                            if trade_duration > 45:  # 45-minute threshold
                                # Calculate momentum strength
                                momentum_strength = abs(pnl_pct) / 100  # Convert percentage to decimal
                                
                                # Check if trade is NOT working
                                exit_reason = None
                                
                                # Condition 1: No momentum (price stuck near entry)
                                if momentum_strength < 0.003:  # Less than 0.3% move in 45 min
                                    exit_reason = "Time + No Momentum (sideways)"
                                
                                # Condition 2: Negative momentum (trade going against)
                                elif pnl_pct < -1.0:  # Losing more than 1%
                                    exit_reason = "Time + Negative Momentum"
                                
                                # Condition 3: Weak positive momentum (not enough progress)
                                elif pnl_pct > 0 and pnl_pct < 0.5:  # Positive but weak (<0.5% in 45 min)
                                    exit_reason = "Time + Weak Momentum"
                                
                                # Exit if trade is NOT working
                                if exit_reason:
                                    logger.warning(f"[INTELLIGENT EXIT] {symbol} - {exit_reason} (duration: {trade_duration:.1f} min, P&L: {pnl_pct:+.2f}%)")
                                    self.trade_manager.close_trade(symbol, current_price, reason=exit_reason)
                                    # Update CSV with exit details
                                    pnl_amount = (current_price - entry_price)
                                    self._update_trade_exit_in_csv(symbol, entry_price, current_price, sl, target, pnl_amount, exit_reason)
                                    del self.active_trades[symbol]
                                    continue
                                else:
                                    # Trade IS working - let it run
                                    logger.info(f"[INTELLIGENT EXIT] {symbol} - Trade working (momentum: {pnl_pct:+.2f}%, duration: {trade_duration:.1f} min) - HOLDING")
                            
                            # MCX TRAILING STOP LOGIC: Move SL to breakeven when profit > 3%
                            if pnl_pct > 3 and trade.get('sl') < entry_price:
                                new_sl = entry_price  # Move SL to breakeven
                                trade['sl'] = new_sl
                                logger.info(f"[MCX TRAILING SL] {symbol} - Profit {pnl_pct:.1f}% > 3%, moving SL to breakeven: {new_sl:.2f}")
                                # Update trade manager with new SL
                                if self.trade_manager:
                                    self.trade_manager.update_sl(symbol, new_sl)

                            # MCX AGGRESSIVE TRAILING: Trail aggressively when profit > 5%
                            if pnl_pct > 5:
                                # Trail SL at 2% below current price (lock in profits)
                                new_sl = current_price * 0.98
                                if new_sl > trade.get('sl', entry_price):
                                    trade['sl'] = new_sl
                                    logger.info(f"[MCX AGGRESSIVE TRAIL] {symbol} - Profit {pnl_pct:.1f}% > 5%, trailing SL: {new_sl:.2f}")
                                    # Update trade manager with new SL
                                    if self.trade_manager:
                                        self.trade_manager.update_sl(symbol, new_sl)

                            # MCX MOMENTUM EXIT: DISABLED - Let Trade Manager handle SL/TP
                            # Previous aggressive exit was closing trades too early (within seconds)
                            # Now rely on SL/TP from Trade Manager for proper exit logic
                            current_profit = pnl_pct
                            highest_profit = trade.get('highest_profit', 0)
                            if current_profit > highest_profit:
                                trade['highest_profit'] = current_profit

                            logger.info(f"[MCX METRICS] Duration: {trade_duration:.1f} min | Peak Profit: {highest_profit:.1f}%")
                        
                        # Use Trade Manager's update_price (handles P&L, TP/SL, trailing SL)
                        self.trade_manager.update_price(symbol, current_price)
                        
                        # Check if trade was closed by trade manager (target/SL hit)
                        if symbol not in self.trade_manager.active_trades:
                            logger.info(f"[MONITOR] {symbol} - Trade closed by Trade Manager, removing from active trades")
                            
                            # Update capital with P&L (for realistic paper trading)
                            closed_trade = self.trade_manager.get_closed_trade(symbol)
                            if closed_trade:
                                trade_pnl = closed_trade.get("pnl", 0)
                                exit_price = closed_trade.get("exit_price", current_price)
                                exit_reason = closed_trade.get("exit_reason", "Trade Manager")
                                
                                # Update CSV with exit details
                                self._update_trade_exit_in_csv(symbol, entry_price, exit_price, sl, target, trade_pnl, exit_reason)
                                
                                # Update capital using Risk Management Service (same as single_strike_trader)
                                self.current_capital = self.risk_service.update_capital(trade_pnl, self.current_capital)
                                logger.info(f"[CAPITAL UPDATE] {symbol} P&L: {trade_pnl:+.2f} | New Capital: ₹{self.current_capital:.2f}")
                                
                                # Update daily P&L using Risk Management Service
                                pnl_update = self.risk_service.update_daily_pnl(trade_pnl)
                                logger.info(f"[DAILY P&L UPDATE] {symbol} | Daily P&L: ₹{pnl_update.get('daily_pnl', 0):.2f}")
                                
                                # Check capital protection using Risk Management Service
                                capital_check = self.risk_service.check_capital_protection(self.current_capital, self.paper_trading)
                                if capital_check.get("protection_triggered"):
                                    logger.error(f"Capital protection triggered: {capital_check['reason']}")
                                    if capital_check.get("action") == "stop_trading":
                                        logger.warning("Trading stopped due to capital protection")
                                
                                # Check daily loss limit using Risk Management Service
                                daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)
                                if daily_check.get("limit_reached"):
                                    logger.error(f"Daily loss limit reached: {daily_check['daily_loss_percent']:.1%}")
                                    logger.warning("Trading stopped due to daily loss limit")
                            
                            del self.active_trades[symbol]
                            continue
                    else:
                        logger.warning(f"[MONITOR] {symbol} - Failed to fetch quote for {option_symbol}")
                else:
                    # Fallback to futures price if no option token (should not happen)
                    logger.warning(f"[MONITOR] {symbol} - No option token, using futures price")
                    if symbol in self.mcx_contracts_cache:
                        contract = self.mcx_contracts_cache[symbol]
                    else:
                        contract = self.kite_client.get_nearest_mcx_contract(symbol)
                        if contract:
                            self.mcx_contracts_cache[symbol] = contract
                    
                    if contract:
                        token = contract['instrument_token']
                        quote = self.kite_client.get_quote(token)
                        if quote:
                            current_price = quote.get('last_price', 0)
                            
                            # Calculate P&L for futures
                            if entry_price > 0:
                                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                            else:
                                pnl_pct = 0
                            
                            logger.info(f"[MONITOR] {symbol} | Futures Price: {current_price:.2f} | P&L: {pnl_pct:+.1f}%")
                            
                            # MCX FAST EXIT LOGIC for futures (same as options)
                            entry_time = trade.get('entry_time')
                            if entry_time:
                                trade_duration = (datetime.now() - entry_time).total_seconds() / 60  # in minutes
                                
                                # MCX TIME EXIT: DISABLED - Trades only close on SL/TP hit
                                # # MCX TIME EXIT: Exit if trade duration > 15 minutes
                                # if trade_duration > 15:
                                #     logger.warning(f"[MCX FAST EXIT] {symbol} - Time exit triggered (duration: {trade_duration:.1f} min > 15 min)")
                                #     self.trade_manager.close_trade(symbol, current_price, reason="Time exit (15 min max)")
                                #     # Update CSV with exit details
                                #     pnl_amount = (current_price - entry_price)  # Absolute P&L
                                #     self._update_trade_exit_in_csv(symbol, entry_price, current_price, sl, target, pnl_amount, "Time exit (15 min max)")
                                #     del self.active_trades[symbol]
                                #     continue
                                
                                # INTELLIGENT EXIT: Time + Weak Market = Exit (Pro-Level Logic)
                                # Time alone should NOT close trade
                                # Time + Weak Market = Exit
                                if trade_duration > 45:  # 45-minute threshold
                                    # Calculate momentum strength
                                    momentum_strength = abs(pnl_pct) / 100  # Convert percentage to decimal
                                    
                                    # Check if trade is NOT working
                                    exit_reason = None
                                    
                                    # Condition 1: No momentum (price stuck near entry)
                                    if momentum_strength < 0.003:  # Less than 0.3% move in 45 min
                                        exit_reason = "Time + No Momentum (sideways)"
                                    
                                    # Condition 2: Negative momentum (trade going against)
                                    elif pnl_pct < -1.0:  # Losing more than 1%
                                        exit_reason = "Time + Negative Momentum"
                                    
                                    # Condition 3: Weak positive momentum (not enough progress)
                                    elif pnl_pct > 0 and pnl_pct < 0.5:  # Positive but weak (<0.5% in 45 min)
                                        exit_reason = "Time + Weak Momentum"
                                    
                                    # Exit if trade is NOT working
                                    if exit_reason:
                                        logger.warning(f"[INTELLIGENT EXIT] {symbol} - {exit_reason} (duration: {trade_duration:.1f} min, P&L: {pnl_pct:+.2f}%)")
                                        self.trade_manager.close_trade(symbol, current_price, reason=exit_reason)
                                        # Update CSV with exit details
                                        pnl_amount = (current_price - entry_price)
                                        self._update_trade_exit_in_csv(symbol, entry_price, current_price, sl, target, pnl_amount, exit_reason)
                                        del self.active_trades[symbol]
                                        continue
                                    else:
                                        # Trade IS working - let it run
                                        logger.info(f"[INTELLIGENT EXIT] {symbol} - Trade working (momentum: {pnl_pct:+.2f}%, duration: {trade_duration:.1f} min) - HOLDING")

                                # MCX TRAILING STOP LOGIC: Move SL to breakeven when profit > 3%
                                if pnl_pct > 3 and trade.get('sl') < entry_price:
                                    new_sl = entry_price  # Move SL to breakeven
                                    trade['sl'] = new_sl
                                    logger.info(f"[MCX TRAILING SL] {symbol} - Profit {pnl_pct:.1f}% > 3%, moving SL to breakeven: {new_sl:.2f}")
                                    # Update trade manager with new SL
                                    if self.trade_manager:
                                        self.trade_manager.update_sl(symbol, new_sl)

                                # MCX AGGRESSIVE TRAILING: Trail aggressively when profit > 5%
                                if pnl_pct > 5:
                                    # Trail SL at 2% below current price (lock in profits)
                                    new_sl = current_price * 0.98
                                    if new_sl > trade.get('sl', entry_price):
                                        trade['sl'] = new_sl
                                        logger.info(f"[MCX AGGRESSIVE TRAIL] {symbol} - Profit {pnl_pct:.1f}% > 5%, trailing SL: {new_sl:.2f}")
                                        # Update trade manager with new SL
                                        if self.trade_manager:
                                            self.trade_manager.update_sl(symbol, new_sl)

                                # MCX MOMENTUM EXIT: DISABLED - Let Trade Manager handle SL/TP
                                # Previous aggressive exit was closing trades too early (within seconds)
                                # Now rely on SL/TP from Trade Manager for proper exit logic
                                current_profit = pnl_pct
                                highest_profit = trade.get('highest_profit', 0)
                                if current_profit > highest_profit:
                                    trade['highest_profit'] = current_profit

                                logger.info(f"[MCX METRICS] Duration: {trade_duration:.1f} min | Peak Profit: {highest_profit:.1f}%")
                            
                            self.trade_manager.update_price(symbol, current_price)
                            
                            # Check if trade was closed by trade manager (target/SL hit)
                            if symbol not in self.trade_manager.active_trades:
                                logger.info(f"[MONITOR] {symbol} - Trade closed by Trade Manager, removing from active trades")
                                
                                # Update capital with P&L (for realistic paper trading)
                                closed_trade = self.trade_manager.get_closed_trade(symbol)
                                if closed_trade:
                                    trade_pnl = closed_trade.get("pnl", 0)
                                    exit_price = closed_trade.get("exit_price", current_price)
                                    exit_reason = closed_trade.get("exit_reason", "Trade Manager")
                                    
                                    # Update CSV with exit details
                                    self._update_trade_exit_in_csv(symbol, entry_price, exit_price, sl, target, trade_pnl, exit_reason)
                                    
                                    # Update capital using Risk Management Service (same as single_strike_trader)
                                    self.current_capital = self.risk_service.update_capital(trade_pnl, self.current_capital)
                                    logger.info(f"[CAPITAL UPDATE] {symbol} P&L: {trade_pnl:+.2f} | New Capital: ₹{self.current_capital:.2f}")
                                    
                                    # Update daily P&L using Risk Management Service
                                    pnl_update = self.risk_service.update_daily_pnl(trade_pnl)
                                    logger.info(f"[DAILY P&L UPDATE] {symbol} | Daily P&L: ₹{pnl_update.get('daily_pnl', 0):.2f}")
                                    
                                    # Check capital protection using Risk Management Service
                                    capital_check = self.risk_service.check_capital_protection(self.current_capital, self.paper_trading)
                                    if capital_check.get("protection_triggered"):
                                        logger.error(f"Capital protection triggered: {capital_check['reason']}")
                                        if capital_check.get("action") == "stop_trading":
                                            logger.warning("Trading stopped due to capital protection")
                                    
                                    # Check daily loss limit using Risk Management Service
                                    daily_check = self.risk_service.check_daily_loss_limit(self.current_capital)
                                    if daily_check.get("limit_reached"):
                                        logger.error(f"Daily loss limit reached: {daily_check['daily_loss_percent']:.1%}")
                                        logger.warning("Trading stopped due to daily loss limit")
                                
                                del self.active_trades[symbol]
                                continue
            except Exception as e:
                logger.error(f"Error monitoring trade {symbol}: {e}")
        
        # QUIET MODE: Skip monitor loop complete log (reduce noise)
    
    def generate_mcx_signals(self):
        """Generate MCX signals for configured instruments"""
        if self.mode == "futures":
            return self.generate_futures_signals()
        else:
            return self.generate_options_signals()
    
    def generate_futures_signals(self):
        """Generate MCX futures signals (original logic)"""
        mcx_symbols = ['CRUDEOIL', 'NATGAS', 'GOLDM', 'SILVERM']
        signals = []
        
        for symbol in mcx_symbols:
            try:
                # Get current price
                symbol_mapping = {
                    "CRUDEOIL": "CRUDEOILM",
                    "NATGAS": "NATURALGAS", 
                    "GOLDM": "GOLDM",
                    "SILVERM": "SILVERM"
                }
                mcx_symbol = symbol_mapping.get(symbol, symbol)
                contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                if not contract:
                    logger.warning(f"No MCX contract found for {symbol} (tried {mcx_symbol})")
                    continue
                
                token = contract['instrument_token']
                quote = self.kite_client.get_quote(token)
                if not quote or not quote.get('last_price'):
                    logger.warning(f"No valid quote data for {symbol}")
                    continue
                
                current_price = quote.get('last_price', 0)
                oi = quote.get('oi', 0)
                volume = quote.get('volume', 0)
                
                # Get MCX support/resistance (HYBRID approach)
                mcx_sr = get_mcx_support_resistance(symbol, current_price)
                
                # Generate MCX signal
                mcx_result = get_mcx_signal(symbol, current_price, oi, volume)
                
                if mcx_result is None:
                    logger.error("MCX service disabled or unavailable. MCX-only bot cannot run without MCX service.")
                    logger.error("Please enable mcx_enabled=true in config.json to use MCX-only bot")
                    return
                
                if mcx_result.get('signal') in ['LONG', 'SHORT']:
                    # Enhance signal with S/R information
                    sr_strength = mcx_sr.get('strength', 'NORMAL') if mcx_sr else 'NORMAL'
                    sr_confidence = mcx_sr.get('confidence', 0.5) if mcx_sr else 0.5
                    
                    # Adjust confidence based on S/R alignment
                    adjusted_confidence = mcx_result.get('confidence', 0)
                    if sr_strength == 'VERY STRONG':
                        adjusted_confidence = min(0.95, adjusted_confidence + 0.2)
                    elif sr_strength == 'STRONG':
                        adjusted_confidence = min(0.85, adjusted_confidence + 0.1)
                    
                    signal = {
                        'symbol': symbol,
                        'signal': mcx_result.get('signal'),
                        'confidence': adjusted_confidence,
                        'entry': current_price,
                        'sl': current_price * 0.02,  # 2% SL
                        'target': current_price * 0.04,  # 4% target
                        'source': 'MCX',
                        'mode': 'futures',
                        'sr_info': mcx_sr if mcx_sr else None,
                        'sr_strength': sr_strength
                    }
                    signals.append(signal)
                    logger.info(f"MCX Signal Generated: {symbol} {signal['signal']} (Confidence: {signal['confidence']:.2f}, S/R Strength: {sr_strength})")
            
            except Exception as e:
                logger.error(f"Error generating MCX signal for {symbol}: {e}")
        
        return signals
    
    def generate_options_signals(self):
        """Generate MCX options signals (NEW - with safety filters and warm-up logic)"""
        signals = []
        
        # PRODUCTION TRADING SYSTEM: Check warm-up status before generating signals
        if not self.warmup_complete:
            logger.info("WARM-UP IN PROGRESS - Skipping signal generation (waiting for sufficient price data)")
            return signals
        
        # Options trading instruments (CRUDEOIL big contract + others)
        mcx_symbols_config = [
            ("CRUDEOIL", "CRUDEOIL"),  # Big contract (100 lot size)
            ("NATGAS", "NATURALGAS"),
            ("GOLDM", "GOLDM"),
            ("SILVERM", "SILVERM")
        ]
        
        for symbol, mcx_symbol in mcx_symbols_config:
            try:
                logger.info(f"Processing {symbol} options...")

                # Determine if this is CRUDEOIL (big contract) for strict filtering
                use_big_contract = (symbol == "CRUDEOIL")
                strict_mode = use_big_contract

                # Get current price (use cached contract to avoid rate limiting)
                if symbol in self.mcx_contracts_cache:
                    contract = self.mcx_contracts_cache[symbol]
                else:
                    contract = self.kite_client.get_nearest_mcx_contract(mcx_symbol)
                    if contract:
                        self.mcx_contracts_cache[symbol] = contract
                if not contract:
                    logger.warning(f"No MCX contract found for {mcx_symbol}")
                    continue

                token = contract['instrument_token']
                quote = self.kite_client.get_quote(token)
                if not quote or not quote.get('last_price'):
                    logger.warning(f"No valid quote data for {symbol}")
                    continue

                current_price = quote.get('last_price', 0)
                oi = quote.get('oi', 0)
                volume = quote.get('volume', 0)

                # Get MCX option chain (use big contract for CRUDEOIL, nearest expiry only)
                logger.info(f"Fetching MCX option chain for {mcx_symbol}...")
                option_chain = get_mcx_option_chain(
                    self.kite_client, 
                    mcx_symbol, 
                    use_big_contract=use_big_contract,
                    prefer_nearest_expiry=True  # Professional: nearest expiry only
                )

                if not option_chain:
                    logger.warning(f"No MCX options available for {mcx_symbol}")
                    continue
                
                # Update MCX token map for rendering (NSE-style format)
                symbol_token_map = create_mcx_option_token_map(option_chain)
                self.mcx_token_map.update(symbol_token_map)
                
                # Save updated token map periodically
                save_mcx_token_map(self.mcx_token_map, self.mcx_token_map_file)

                # PRODUCTION TRADING SYSTEM: Use real price data with confidence scoring
                using_real_data = False
                skip_sideways_check = False
                
                if symbol in self.mcx_price_history and len(self.mcx_price_history[symbol]) >= 2:
                    price_history = self.mcx_price_history[symbol]
                    recent_high = max(price_history[-10:]) if len(price_history) >= 10 else max(price_history)
                    recent_low = min(price_history[-10:]) if len(price_history) >= 10 else min(price_history)
                    last_price = price_history[-2] if len(price_history) >= 2 else current_price
                    
                    price_data = {
                        "current": current_price,
                        "high": recent_high,
                        "low": recent_low,
                        "last": last_price
                    }
                    using_real_data = True
                    
                    # Debug logging for price data
                    range_size = recent_high - recent_low
                    range_pct = (range_size / current_price) * 100
                    logger.info(f"[DEBUG] {symbol} Price Data: Current={current_price:.2f}, High={recent_high:.2f}, Low={recent_low:.2f}, Range={range_pct:.3f}%")
                else:
                    # Fallback if not enough history (should not happen after warm-up)
                    logger.warning(f"[MCX OPTIONS] {symbol}: Using fallback data (insufficient history)")
                    price_data = {
                        "current": current_price,
                        "high": current_price * 1.01,
                        "low": current_price * 0.99,
                        "last": current_price
                    }
                    skip_sideways_check = True  # Skip sideways check for fallback data

                # Get direction signal with smart fallback logic
                option_type, direction_reason, early_breakout, breakdown, market_type, momentum = mcx_direction_module(
                    price_data,
                    skip_sideways_check=skip_sideways_check,
                    debug_mode=self.debug_mode,
                    early_breakout=False  # Will be determined internally
                )
                
                # Track early breakout status for this symbol
                self.early_breakout_detected[symbol] = early_breakout

                if not option_type:
                    logger.info(f"[MCX OPTIONS] {symbol}: {direction_reason}")
                    continue

                logger.info(f"[MCX OPTIONS] {symbol} Direction: {option_type} | {direction_reason}")

                # Select best strike using NIFTY-like selector
                selected_option = select_mcx_like_nifty(option_chain, current_price, option_type)

                if not selected_option:
                    logger.warning(f"No suitable MCX option found for {symbol} {option_type}")
                    continue

                # Validate the selected option (using market configuration)
                market_data = {"price": current_price}
                
                # Get symbol configuration for filter parameters
                try:
                    symbol_config = get_symbol_config("MCX", symbol)
                except Exception as e:
                    logger.warning(f"Could not get config for {symbol}, using defaults: {e}")
                    symbol_config = None
                
                is_valid, filter_reason = mcx_options_filter(
                    selected_option, 
                    market_data, 
                    strict_mode=strict_mode,
                    debug_mode=self.debug_mode,
                    symbol_config=symbol_config,
                    early_breakout=self.early_breakout_detected.get(symbol, False)
                )

                if not is_valid:
                    logger.warning(f"[MCX OPTIONS] {symbol}: {filter_reason}")
                    continue

                logger.info(f"[MCX OPTIONS] {symbol} Selected: {selected_option['tradingsymbol']}")
                
                # MCX DEBUG PRINT: Trade decision visibility
                logger.info(f"""
[TRADE DECISION DEBUG]
Symbol: {symbol}
Early Breakout: {self.early_breakout_detected.get(symbol, False)}
Direction: {option_type}
Volume: {market_data.get('volume', 0)}
Filter Reason: {filter_reason}
Decision: PROCEED TO EXECUTION
""")

                # CRITICAL FIX: Fetch option premium (not futures price)
                option_symbol = selected_option['tradingsymbol']
                option_token = selected_option.get('instrument_token')
                
                if option_token:
                    try:
                        option_quote = self.kite_client.get_quote(option_token)
                        option_price = option_quote.get('last_price', 0) if option_quote else 0
                        logger.info(f"[DEBUG] Option Premium: {option_symbol} = {option_price:.2f}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch option premium for {option_symbol}: {e}")
                        option_price = current_price  # Fallback to futures price
                else:
                    logger.warning(f"No instrument token for {option_symbol}, using futures price")
                    option_price = current_price  # Fallback to futures price

                # CRITICAL DEBUG LOGGING
                logger.info(f"""
[TRADE DEBUG]
Symbol: {symbol}
Option: {option_symbol}
Futures Price: {current_price:.2f}
Option Premium: {option_price:.2f}
Direction: {option_type}
""")

                # PRODUCTION TRADING SYSTEM: Confidence scoring
                confidence = 0
                if using_real_data:
                    confidence += 70  # High confidence for real data
                else:
                    confidence += 30  # Low confidence for fallback data
                
                # Add trend confirmation bonus
                if "Breakout" in direction_reason or "Breakdown" in direction_reason:
                    confidence += 30
                
                # DEBUG MODE: Add bonus for testing
                if self.debug_mode:
                    confidence += 50  # Bonus for debug mode
                
                # PRODUCTION FIX: Soft confidence filter (40% threshold instead of 60%)
                MIN_CONFIDENCE = 40  # Production safe lower bound - allows developing setups but blocks garbage
                
                # Only trade if confidence >= MIN_CONFIDENCE
                # DEBUG MODE: Override confidence check for testing
                if confidence < MIN_CONFIDENCE and not self.debug_mode:
                    logger.warning(f"[MCX OPTIONS] {symbol}: SKIP - Low confidence ({confidence}/100, minimum: {MIN_CONFIDENCE})")
                    continue
                elif confidence < MIN_CONFIDENCE and self.debug_mode:
                    logger.warning(f"[DEBUG MODE] Forcing trade despite low confidence ({confidence}/100, minimum: {MIN_CONFIDENCE})")

                # Create signal with trade reason tagging (for debugging)
                trade_reasons = []
                if self.debug_mode:
                    trade_reasons.append("DEBUG_MODE_OVERRIDE")
                if "DEBUG" in direction_reason:
                    trade_reasons.append("FORCED_DIRECTION")
                if "DEBUG" in filter_reason:
                    trade_reasons.append("FORCED_FILTERS")
                if not using_real_data:
                    trade_reasons.append("FALLBACK_DATA")
                
                signals.append({
                    "symbol": symbol,
                    "signal": "LONG" if option_type == "CE" else "SHORT",
                    "option_type": option_type,
                    "selected_option": selected_option,
                    "entry": option_price,  # CRITICAL FIX: Use option premium, not futures price
                    "futures_price": current_price,  # Keep futures price for reference
                    "confidence": confidence / 100,  # Normalize to 0-1 range
                    "reasoning": [direction_reason, filter_reason, f"Confidence: {confidence}/100"],
                    "trade_reasons": trade_reasons,  # Debugging: why this trade was taken
                    "mode": "options",
                    "strict_mode": strict_mode,
                    "using_real_data": using_real_data,
                    "debug_mode": self.debug_mode,
                    # NEW: MCX balanced scoring fields
                    "breakdown": breakdown,
                    "market_type": market_type,
                    "momentum": momentum
                })
                
                # Add small delay between commodities to avoid rate limiting
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error generating MCX options signal for {symbol}: {e}")
        
        return signals
    
    def run(self):
        """Main run loop for MCX-only bot"""
        logger.info("Starting MCX-only bot...")
        
        # Wait for market to open
        while not self.is_market_open():
            logger.info("Waiting for MCX market to open...")
            time.sleep(60)
        
        logger.info("MCX market is open - starting warm-up period...")
        logger.info("=" * 80)
        logger.info("PRODUCTION TRADING SYSTEM: Warm-up Period")
        logger.info("Collecting price data for accurate signal generation")
        logger.info(f"Required: {self.min_candles_for_signals} candles per symbol")
        logger.info("=" * 80)
        
        # PRODUCTION TRADING SYSTEM: Try historical data pre-loading first
        if self.preload_historical_data():
            logger.info("Historical data pre-load successful - skipping real-time warm-up")
        else:
            logger.info("Historical data pre-load failed or unavailable - using real-time warm-up")
            # Initial price update before main loop
            self.update_mcx_live_prices()
            logger.info("Live MCX futures prices updated")
        
        # Main monitoring loop
        try:
            while self.is_market_open():
                # QUIET MODE: Skip main loop log when trade is active (reduce noise)
                if len(self.active_trades) == 0:
                    logger.info("=== MAIN LOOP CYCLE START ===")
                
                # Update live prices every cycle (for momentum detection)
                # QUIET MODE: Skip price updates when trade is active (reduce noise)
                if len(self.active_trades) == 0:
                    self.update_mcx_live_prices()
                
                # Check risk limits
                can_trade = can_execute_trade()
                if not can_trade:
                    logger.warning("Trading blocked by risk management")
                    time.sleep(60)
                    continue
                
                # DEBUG MODE: Limit to 1 trade for testing
                if self.debug_mode and len(self.active_trades) >= 1:
                    logger.info("[DEBUG MODE] Max 1 trade limit reached - skipping signal generation")
                # MCX FIX: Skip signal generation when there's an active trade (one-trade-at-a-time)
                elif len(self.active_trades) >= 1:
                    active_symbols = list(self.active_trades.keys())
                    # QUIET MODE: Skip price updates during active trade (reduce noise)
                    # Only show trade monitoring, not all instrument prices
                    logger.info(f"[TRADE ACTIVE] Monitoring: {active_symbols} - waiting for exit")
                else:
                    # Generate MCX signals (will skip during warm-up)
                    signals = self.generate_mcx_signals()
                    
                    if signals:
                        # PRODUCTION FIX: Smart signal selection with validation
                        # MCX FIX: Only filter invalid entry, allow lot_size issues (will handle in execution)
                        valid_signals = [
                            s for s in signals
                            if s.get('entry', 0) > 0  # Only reject invalid entry prices
                        ]
                        
                        if not valid_signals:
                            logger.warning("No valid signals after filtering (invalid entry)")
                        else:
                            # Pick highest confidence among VALID signals
                            best_signal = max(valid_signals, key=lambda s: s.get('confidence', 0))
                            logger.info(f"Best signal: {best_signal['symbol']} (Confidence: {best_signal.get('confidence', 0):.2f})")
                            
                            logger.info(">>> BEFORE EXECUTE TRADE <<<")
                            self.execute_trade(best_signal)
                            logger.info(">>> AFTER EXECUTE TRADE <<<")
                    else:
                        logger.info("No valid signals generated for any instrument")
                
                # Monitor active trades (every cycle, not blocking)
                self.monitor_trades()
                
                # Render dashboard (disabled to show detailed analyzer logs)
                # self.trade_manager.render_dashboard()
                
                # Small delay between cycles
                # QUIET MODE: Skip main loop complete log when trade is active (reduce noise)
                if len(self.active_trades) == 0:
                    logger.info("=== MAIN LOOP CYCLE COMPLETE ===")
                time.sleep(5)  # Check every 5 seconds
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        
        # Stop watchdog monitoring
        if self.watchdog_service:
            try:
                self.watchdog_service.stop_monitoring()
                logger.info("Watchdog monitoring stopped")
            except Exception as e:
                logger.error(f"Error stopping watchdog: {e}")
        
        # Save trade history
        self.save_trade_history()
        
        logger.info("MCX-only bot stopped")
    
    def save_trade_history(self):
        """Save trade history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump({
                    'trading_session': {
                        'start_capital': self.investment_amount,
                        'end_capital': self.investment_amount,
                        'total_pnl': 0,
                        'total_trades': len(self.trade_history),
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'signal_source': 'MCX_ONLY'
                    },
                    'trades': self.trade_history
                }, f, indent=2)
            logger.info("MCX trade history saved to mcx_trade_history.json")
        except Exception as e:
            logger.error(f"Error saving trade history: {e}")

def generate_trade_summary(bot):
    """Generate complete trade summary from CSV and print to console"""
    try:
        import csv
        from collections import defaultdict
        
        # Read all trades from CSV
        trades = []
        with open(bot.csv_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
            
        # Calculate summary
        total_trades = len(trades)
        executed_trades = [t for t in trades if t['status'] == 'EXECUTED']
        closed_trades = [t for t in executed_trades if t['pnl'] != '0']
        
        total_pnl = sum(float(t['pnl']) for t in closed_trades)
        winning_trades = [t for t in closed_trades if float(t['pnl']) > 0]
        losing_trades = [t for t in closed_trades if float(t['pnl']) < 0]
        
        win_rate = (len(winning_trades) / len(closed_trades)) * 100 if closed_trades else 0
        
        # Print summary
        logger.info("=" * 80)
        logger.info("TRADE SUMMARY REPORT")
        logger.info("=" * 80)
        logger.info(f"Total Signals: {total_trades}")
        logger.info(f"Executed Trades: {len(executed_trades)}")
        logger.info(f"Closed Trades: {len(closed_trades)}")
        logger.info(f"Total P&L: ₹{total_pnl:.2f}")
        logger.info(f"Win Rate: {win_rate:.1f}%")
        logger.info(f"Winning Trades: {len(winning_trades)}")
        logger.info(f"Losing Trades: {len(losing_trades)}")
        logger.info(f"Current Capital: ₹{bot.current_capital:.2f}")
        logger.info(f"Starting Capital: ₹{bot.start_capital:.2f}")
        logger.info(f"Overall Return: {((bot.current_capital - bot.start_capital) / bot.start_capital * 100):.2f}%")
        logger.info("=" * 80)
        
        # Print individual trade details
        logger.info("INDIVIDUAL TRADE DETAILS:")
        logger.info("-" * 80)
        for trade in closed_trades:
            logger.info(f"{trade['symbol']} {trade['signal']} | Entry: ₹{trade['entry']} | Exit: ₹{trade['exit_price']} | P&L: ₹{trade['pnl']} | Reason: {trade['exit_reason']}")
        
        # Save summary to file
        summary_file = os.path.join(os.path.dirname(bot.csv_file), 'trade_summary.txt')
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("TRADE SUMMARY REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"Total Signals: {total_trades}\n")
            f.write(f"Executed Trades: {len(executed_trades)}\n")
            f.write(f"Closed Trades: {len(closed_trades)}\n")
            f.write(f"Total P&L: ₹{total_pnl:.2f}\n")
            f.write(f"Win Rate: {win_rate:.1f}%\n")
            f.write(f"Winning Trades: {len(winning_trades)}\n")
            f.write(f"Losing Trades: {len(losing_trades)}\n")
            f.write(f"Current Capital: ₹{bot.current_capital:.2f}\n")
            f.write(f"Starting Capital: ₹{bot.start_capital:.2f}\n")
            f.write(f"Overall Return: {((bot.current_capital - bot.start_capital) / bot.start_capital * 100):.2f}%\n")
            f.write("=" * 80 + "\n")
            f.write("INDIVIDUAL TRADE DETAILS:\n")
            f.write("-" * 80 + "\n")
            for trade in closed_trades:
                f.write(f"{trade['symbol']} {trade['signal']} | Entry: ₹{trade['entry']} | Exit: ₹{trade['exit_price']} | P&L: ₹{trade['pnl']} | Reason: {trade['exit_reason']}\n")
        
        logger.info(f"Trade summary saved to: {summary_file}")
        
    except Exception as e:
        logger.error(f"Error generating trade summary: {e}")

def handle_shutdown(signum=None, frame=None):
    """Handle graceful shutdown with trade summary"""
    logger.info("=" * 80)
    logger.info("SHUTDOWN SIGNAL RECEIVED")
    logger.info("=" * 80)
    logger.info("Generating trade summary before shutdown...")
    # This will be called from main with bot instance
    logger.info("Shutdown complete. Goodbye!")
    sys.exit(0)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='MCX-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=None,
                       help='Investment amount (default: read from config.json)')
    parser.add_argument('--mode', type=str, default='futures',
                       choices=['futures', 'options'],
                       help='Trading mode: futures (default) or options')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    parser.add_argument('--disable-watchdog', action='store_true',
                       help='Disable watchdog monitoring (enabled by default, logs only)')
    
    args = parser.parse_args()
    
    # Create bot with mode
    bot = MCXOnlyBot(investment_amount=args.investment, mode=args.mode)
    
    # Handle watchdog disable (enabled by default)
    if args.disable_watchdog and bot.watchdog_service:
        bot.watchdog_service.stop_monitoring()
        logger.info("Watchdog monitoring disabled via command line")
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, lambda s, f: (generate_trade_summary(bot), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (generate_trade_summary(bot), sys.exit(0)))
    
    # Override paper trading if --live flag is set
    if args.live:
        bot.paper_trading = False
        logger.warning("LIVE MODE ENABLED - REAL MONEY AT RISK!")
    
    # Run bot
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        generate_trade_summary(bot)
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")
        generate_trade_summary(bot)
        raise

if __name__ == "__main__":
    main()

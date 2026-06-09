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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class MCXOnlyBot:
    def __init__(self, investment_amount=30000, mode="futures"):
        # Load config from current directory
        config_path = os.path.join(current_dir, 'config.json')
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.investment_amount = investment_amount
        self.mode = mode  # "futures" or "options"
        self.paper_trading = self.config.get("paper_trading", True)
        
        # Initialize Risk Management Service (same as single_strike_trader)
        self.risk_service = get_risk_management_service(investment_amount)
        logger.info("Risk Management Service initialized")
        
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
        self.trade_manager = TradeManagerService(
            max_daily_loss=3000,
            config=self.config
        )
        logger.info("Trade Manager Service initialized")
        
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
        
        # CSV file for MCX call tracking (already set in __init__)
        self._init_csv_file()
        
        # MCX option token map for rendering
        self.mcx_token_map = {}
        self.mcx_token_map_file = os.path.join(current_dir, 'mcx_option_token_map.json')
        
        # Initialize Watchdog Service (health monitoring - enabled by default)
        try:
            self.watchdog_service = get_watchdog_service(check_interval=120)  # 2 minute intervals
            self.watchdog_service.start_monitoring()  # Start by default
            logger.info("Watchdog Service initialized and started (health monitoring every 2 minutes)")
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
                with open(self.csv_file, 'w', newline='') as f:
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
            with open(self.csv_file, 'a', newline='') as f:
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
            with open(self.csv_file, 'r', newline='') as f:
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
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            
            logger.info(f"Call status updated in CSV: {signal['symbol']} {signal['signal']} - {status}")
        except Exception as e:
            logger.error(f"Error updating CSV status: {e}")
    
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
            
            # CRITICAL FIX: Log option premium vs futures price
            option_price = signal.get('entry', 0)
            futures_price = signal.get('futures_price', 0)
            if futures_price > 0:
                logger.info(f"[TRADE EXECUTION] Option Premium: {option_price:.2f} | Futures Price: {futures_price:.2f}")
            
            # Log call to CSV as RECEIVED
            self._log_call_to_csv(signal, status='RECEIVED')
            
            # Check risk limits
            can_trade = can_execute_trade()
            if not can_trade:
                logger.error("Trade blocked by risk management")
                self._update_call_status(signal, status='BLOCKED', exit_reason='Risk Management')
                return False
            
            # Send to Trade Manager directly (MCX doesn't need Execution Brain)
            # MCX signals are already validated by the MCX signal engine
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
                    # Fallback to hardcoded values (same for both CALL and PUT when buying)
                    tp = entry_price * 1.20  # Want 20% gain in option premium
                    sl = entry_price * 0.85  # Accept 15% loss in option premium
                
                logger.info(">>> STEP 2: TP/SL CALCULATION DONE <<<")
                
                logger.info(">>> STEP 3: CALCULATE POSITION SIZE (Using Risk Service) <<<")
                # Use Risk Management Service for position sizing (same as single_strike_trader)
                lot_size = signal.get('selected_option', {}).get('lot_size', 1)
                
                position_calc = self.risk_service.calculate_position_size(entry_price, lot_size, self.current_capital)
                
                if not position_calc.get("success"):
                    logger.error(f"Position sizing failed: {position_calc.get('error')}")
                    return False
                
                actual_lots = position_calc["actual_lots"]
                cost_per_lot = position_calc["cost_per_lot"]
                total_cost = position_calc["total_cost"]
                
                logger.info(f"Position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")
                
                logger.info(">>> STEP 4: CALCULATE RISK PARAMETERS (Using Risk Service) <<<")
                # Use Risk Management Service for risk parameters (same as single_strike_trader)
                risk_params = self.risk_service.calculate_risk_parameters(entry_price, actual_lots, mcx_signal, self.current_capital)
                
                if not risk_params.get("success"):
                    logger.error(f"Risk parameter calculation failed: {risk_params.get('error')}")
                    return False
                
                stoploss_price = risk_params["stoploss_price"]
                target_price = risk_params["target_price"]
                risk_amount = risk_params["risk_amount"]
                
                logger.info(f"Risk parameters: SL ₹{stoploss_price}, Target ₹{target_price}, Risk ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.1f}%)")
                
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
Risk Amount: ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.1f}%)
Capital Used: ₹{self.current_capital}
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
                }
                
                logger.info(">>> STEP 7: CALL TRADE MANAGER ADD_TRADE <<<")
                success = self.trade_manager.add_trade(symbol, trade)
                logger.info(">>> STEP 8: TRADE MANAGER ADD_TRADE DONE <<<")
                
                if success:
                    logger.info(">>> STEP 9: UPDATE ACTIVE TRADES <<<")
                    self.active_trades[symbol] = trade
                    logger.info(f"Trade added to manager: {symbol} {mcx_signal}")
                    
                    logger.info(">>> STEP 10: UPDATE CSV STATUS <<<")
                    # Update CSV status to EXECUTED
                    self._update_call_status(signal, status='EXECUTED')
                    logger.info(">>> STEP 11: CSV STATUS UPDATED <<<")
                    return True
                else:
                    logger.error(f"Failed to add trade to manager")
                    self._update_call_status(signal, status='FAILED', exit_reason='Trade Manager Error')
                    return False
                    
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
        logger.info(">>> ENTERING MONITOR LOOP <<<")
        
        if not self.active_trades:
            logger.debug("No active trades to monitor")
            return
        
        logger.info(f"Monitoring {len(self.active_trades)} active trades")
        
        # Update prices for active trades (using Trade Manager's infrastructure)
        for symbol, trade in self.active_trades.items():
            try:
                logger.info(f">>> CHECKING TRADE: {symbol}")
                
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
                        
                        logger.info(f"[MONITOR] {symbol} | {option_symbol} | Entry: {entry_price:.2f} | Current: {current_price:.2f} | P&L: {pnl_pct:+.1f}% | Target: {target:.2f} | SL: {sl:.2f}")
                        
                        # Use Trade Manager's update_price (handles P&L, TP/SL, trailing SL)
                        self.trade_manager.update_price(symbol, current_price)
                        
                        # Check if trade was closed by trade manager (target/SL hit)
                        if symbol not in self.trade_manager.active_trades:
                            logger.info(f"[MONITOR] {symbol} - Trade closed by Trade Manager, removing from active trades")
                            
                            # Update capital with P&L (for realistic paper trading)
                            closed_trade = self.trade_manager.get_closed_trade(symbol)
                            if closed_trade:
                                trade_pnl = closed_trade.get("pnl", 0)
                                
                                # Update capital using Risk Management Service (same as single_strike_trader)
                                self.current_capital = self.risk_service.update_capital(trade_pnl)
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
                            self.trade_manager.update_price(symbol, current_price)
                            logger.info(f"[MONITOR] {symbol} | Futures Price: {current_price:.2f}")
                            
                            # Check if trade was closed by trade manager (target/SL hit)
                            if symbol not in self.trade_manager.active_trades:
                                logger.info(f"[MONITOR] {symbol} - Trade closed by Trade Manager, removing from active trades")
                                
                                # Update capital with P&L (for realistic paper trading)
                                closed_trade = self.trade_manager.get_closed_trade(symbol)
                                if closed_trade:
                                    trade_pnl = closed_trade.get("pnl", 0)
                                    
                                    # Update capital using Risk Management Service (same as single_strike_trader)
                                    self.current_capital = self.risk_service.update_capital(trade_pnl)
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
        
        logger.info(">>> MONITOR LOOP CYCLE COMPLETE <<<")
    
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
                option_type, direction_reason = mcx_direction_module(
                    price_data, 
                    skip_sideways_check=skip_sideways_check,
                    debug_mode=self.debug_mode
                )

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
                    symbol_config=symbol_config
                )

                if not is_valid:
                    logger.warning(f"[MCX OPTIONS] {symbol}: {filter_reason}")
                    continue

                logger.info(f"[MCX OPTIONS] {symbol} Selected: {selected_option['tradingsymbol']}")

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
                
                # Only trade if confidence > 60 (production safety threshold)
                # DEBUG MODE: Override confidence check for testing
                if confidence < 60 and not self.debug_mode:
                    logger.warning(f"[MCX OPTIONS] {symbol}: SKIP - Low confidence ({confidence}/100)")
                    continue
                elif confidence < 60 and self.debug_mode:
                    logger.warning(f"[DEBUG MODE] Forcing trade despite low confidence ({confidence}/100)")

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
                    "debug_mode": self.debug_mode
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
                logger.info("=== MAIN LOOP CYCLE START ===")
                
                # Update live prices every cycle (for momentum detection)
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
                else:
                    # Generate MCX signals (will skip during warm-up)
                    signals = self.generate_mcx_signals()
                    
                    # Execute signals (limit to 1 in debug mode)
                    if self.debug_mode and signals:
                        # Only execute first signal in debug mode
                        logger.info(f"[DEBUG MODE] Executing 1 of {len(signals)} signals")
                        logger.info(">>> BEFORE EXECUTE TRADE <<<")
                        self.execute_trade(signals[0])
                        logger.info(">>> AFTER EXECUTE TRADE <<<")
                    else:
                        # Execute all signals in normal mode
                        for signal in signals:
                            logger.info(">>> BEFORE EXECUTE TRADE <<<")
                            self.execute_trade(signal)
                            logger.info(">>> AFTER EXECUTE TRADE <<<")
                
                # Monitor active trades (every cycle, not blocking)
                self.monitor_trades()
                
                # Render dashboard (disabled to show detailed analyzer logs)
                # self.trade_manager.render_dashboard()
                
                # Small delay between cycles
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

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='MCX-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    parser.add_argument('--mode', type=str, default='futures',
                       choices=['futures', 'options'],
                       help='Trading mode: futures (default) or options')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    parser.add_argument('--disable-watchdog', action='store_true',
                       help='Disable watchdog monitoring (enabled by default)')
    
    args = parser.parse_args()
    
    # Create bot with mode
    bot = MCXOnlyBot(investment_amount=args.investment, mode=args.mode)
    
    # Handle watchdog disable (enabled by default)
    if args.disable_watchdog and bot.watchdog_service:
        bot.watchdog_service.stop_monitoring()
        logger.info("Watchdog monitoring disabled via command line")
    
    # Override paper trading if --live flag is set
    if args.live:
        bot.paper_trading = False
        logger.warning("LIVE MODE ENABLED - REAL MONEY AT RISK!")
    
    # Run bot
    bot.run()

if __name__ == "__main__":
    main()

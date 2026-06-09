"""
Telegram-Only Trading Bot
Dedicated to executing Telegram signals only
No internal signal generation
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

# Add parent directory to path for imports
# This works whether run from parent directory or telegram directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Also add current directory to path for telegram services
if current_dir not in sys.path:
    sys.path.append(current_dir)

from kite.kite_client import KiteClient
from services.telegram_service.telegram_service import TelegramService
from services.trade_manager_service.service import TradeManagerService
from risk.risk_management import get_risk_management_service
from wrappers.risk_wrapper import can_execute_trade, update_trade_result, reset_daily_limits, get_risk_status
from services.watchdog_service.service import get_watchdog_service

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class BasicSignalValidator:
    """
    Basic Signal Validation Module - Execution protection layer
    Validates signals without market analysis (trusts provider, protects execution)
    """
    
    def __init__(self):
        # Configurable thresholds
        self.max_entry_deviation = 0.20   # 20% deviation allowed
        self.max_signal_age_sec = 120     # 2 minutes freshness
    
    def validate(self, signal: dict, market_data: dict) -> tuple:
        """
        Validate signal with basic sanity checks.
        
        Args:
            signal: dict from Telegram
            market_data: dict with current price, support, resistance
            
        Returns:
            (is_valid, reason) tuple
        """
        current_price = market_data.get("price")
        support = market_data.get("support")
        resistance = market_data.get("resistance")
        
        # -------------------------------
        # RULE 1: ENTRY DISTANCE CHECK
        # -------------------------------
        entry = signal.get("entry")
        
        if entry and current_price:
            deviation = abs(current_price - entry) / entry
            
            if deviation > self.max_entry_deviation:
                return False, f"SKIP: Chasing entry (deviation {deviation:.2f})"
        
        # -------------------------------
        # RULE 2: DIRECTION CHECK
        # -------------------------------
        option_type = signal.get("option_type")
        
        if option_type == "CE" and support:
            if current_price < support:
                return False, "SKIP: Weak bullish setup (below support)"
        
        if option_type == "PE" and resistance:
            if current_price > resistance:
                return False, "SKIP: Weak bearish setup (above resistance)"
        
        # -------------------------------
        # RULE 3: SIGNAL FRESHNESS
        # -------------------------------
        timestamp = signal.get("timestamp")
        
        if timestamp:
            now = datetime.now().timestamp()
            age = now - timestamp
            
            if age > self.max_signal_age_sec:
                return False, f"SKIP: Stale signal ({int(age)} sec old)"
        
        # -------------------------------
        # PASSED ALL CHECKS
        # -------------------------------
        return True, "VALID SIGNAL"


class EntryTimingFilter:
    """
    Entry Timing Filter - Time-based risk control for Telegram bot
    Blocks late-day trades, expiry-risk trades, and early market noise
    Configurable via config.json
    """
    
    def __init__(self, config: dict):
        """
        Initialize timing filter with config
        
        Args:
            config: Telegram config with entry_timing_filter settings
        """
        timing_config = config.get("entry_timing_filter", {})
        
        self.enabled = timing_config.get("enabled", True)
        self.market_end_buffer_min = timing_config.get("market_end_buffer_min", 30)
        self.expiry_buffer_days = timing_config.get("expiry_buffer_days", 1)
        
        # Parse start buffer time
        start_buffer_str = timing_config.get("market_start_buffer", "09:20")
        self.market_start_buffer = dt_time(*map(int, start_buffer_str.split(":")))
        
        logger.info(f"Entry Timing Filter: {'ENABLED' if self.enabled else 'DISABLED'}")
        if self.enabled:
            logger.info(f"  - Market end buffer: {self.market_end_buffer_min} mins")
            logger.info(f"  - Expiry buffer: {self.expiry_buffer_days} days")
            logger.info(f"  - Market start buffer: {self.market_start_buffer}")
    
    def is_valid_entry_time(self, signal: dict) -> tuple:
        """
        Check if entry timing is valid.
        
        Args:
            signal: Signal dictionary with expiry info
            
        Returns:
            (is_valid, reason) tuple
        """
        if not self.enabled:
            return True, "VALID (filter disabled)"
        
        now = datetime.now().time()
        
        # -------------------------------
        # RULE 1: AVOID LATE DAY ENTRY
        # -------------------------------
        market_end = dt_time(15, 30)
        
        minutes_left = (
            (market_end.hour * 60 + market_end.minute) -
            (now.hour * 60 + now.minute)
        )
        
        if minutes_left <= self.market_end_buffer_min:
            return False, f"BLOCKED: Late market entry ({minutes_left} mins left)"
        
        # -------------------------------
        # RULE 2: AVOID EXPIRY DAY
        # -------------------------------
        if "expiry" in signal and signal["expiry"]:
            try:
                expiry_date = datetime.strptime(signal["expiry"], "%Y-%m-%d").date()
                today = datetime.now().date()
                
                days_left = (expiry_date - today).days
                
                if days_left <= self.expiry_buffer_days:
                    return False, f"BLOCKED: Near expiry risk ({days_left} days left)"
            except Exception as e:
                logger.warning(f"Could not parse expiry date: {e}")
        
        # -------------------------------
        # RULE 3: OPTIONAL - EARLY NOISE FILTER
        # -------------------------------
        if now < self.market_start_buffer:
            return False, "BLOCKED: Early market noise"
        
        return True, "VALID"

class TelegramOnlyBot:
    def __init__(self, investment_amount=30000):
        # Load config from parent directory
        config_path = os.path.join(parent_dir, 'config.json')
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.investment_amount = investment_amount
        self.paper_trading = self.config.get("paper_trading", True)
        
        # Initialize Risk Management Service (same as MCX bot and single_strike_trader)
        self.risk_service = get_risk_management_service(investment_amount)
        logger.info("Risk Management Service initialized")
        
        # Trading parameters (same as single_strike_trader)
        self.start_capital = investment_amount
        self.current_capital = investment_amount
        logger.info(f"Capital initialized: ₹{self.start_capital}")
        
        # Set file paths
        self.csv_file = os.path.join(current_dir, 'telegram_calls.csv')
        self.history_file = os.path.join(current_dir, 'telegram_trade_history.json')
        
        # Set session file path (use sessions folder)
        sessions_dir = os.path.join(parent_dir, 'sessions')
        self.session_file = os.path.join(sessions_dir, 'tg_session.session')
        
        logger.info("=" * 80)
        logger.info("TELEGRAM-ONLY TRADING BOT")
        logger.info("=" * 80)
        logger.info(f"Investment: ₹{investment_amount}")
        logger.info(f"Mode: {'PAPER TRADING' if self.paper_trading else 'LIVE TRADING'}")
        logger.info("Signal Source: Telegram Only (No internal signals)")
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
        
        # Initialize Entry Timing Filter
        telegram_config = self.config.get("telegram", {})
        self.timing_filter = EntryTimingFilter(telegram_config)
        
        # Initialize Basic Signal Validator
        self.signal_validator = BasicSignalValidator()
        logger.info("Basic Signal Validator initialized (entry distance, direction, freshness)")
        
        # Initialize Risk Management
        # Note: risk_wrapper uses a global RiskManager instance
        # We'll use the wrapper functions directly
        logger.info("Risk Management initialized (using risk_wrapper)")
        
        # Initialize Trade Manager
        self.trade_manager = TradeManagerService(
            max_daily_loss=3000,
            config=self.config
        )
        logger.info("Trade Manager Service initialized")
        
        # DISABLE WebSocket for Telegram bot (use REST API to avoid conflicts)
        # WebSocket conflicts with KiteTicker error handling
        self.websocket_client = None
        self.subscribed_tokens = set()
        logger.info("WebSocket disabled for Telegram bot - using REST API for price updates")
        
        # Initialize Telegram Service with callback
        telegram_config = self.config.get("telegram", {})
        if telegram_config.get("enabled", False):
            try:
                self.telegram_service = TelegramService(
                    api_id=telegram_config.get("api_id"),
                    api_hash=telegram_config.get("api_hash"),
                    group_id=telegram_config.get("group_id"),
                    signal_callback=self.execute_trade,  # Direct callback for execution
                    signal_received_callback=self._signal_received_callback,  # Callback for CSV logging
                    kite_client=self.kite_client,  # Pass kite_client for symbol lookup
                    session_file=self.session_file  # Pass session file path
                )
                logger.info("Telegram Service initialized with direct callback, CSV logging, and dynamic symbol lookup")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram Service: {e}")
                self.telegram_service = None
        else:
            logger.error("Telegram not enabled in config - cannot run without Telegram")
            raise Exception("Telegram service required for Telegram-only bot")
        
        # Initialize Watchdog Service (health monitoring - enabled by default)
        try:
            self.watchdog_service = get_watchdog_service(check_interval=120)  # 2 minute intervals
            self.watchdog_service.start_monitoring()  # Start by default
            logger.info("Watchdog Service initialized and started (health monitoring every 2 minutes)")
        except Exception as e:
            logger.error(f"Failed to initialize Watchdog Service: {e}")
            self.watchdog_service = None
        
        # Market hours
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        
        # Trade tracking
        self.active_trades = {}
        self.trade_history = []
        
        # CSV file for Telegram call tracking
        self.csv_file = 'telegram_calls.csv'
        self._init_csv_file()
        
        logger.info(f"Market hours: {self.market_open} - {self.market_close}")
    
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
                        'strike',
                        'option_type',
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
    
    def _log_call_to_csv(self, signal, status='RECEIVED', executed_at=None, pnl=0, exit_price=None, exit_reason=None, expected_outcome='', source='TELEGRAM'):
        """Log Telegram call to CSV file"""
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    signal.get('symbol', ''),
                    signal.get('strike', ''),
                    signal.get('option_type', ''),
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
            logger.info(f"Call logged to CSV: {signal['symbol']} {signal['strike']} {signal['option_type']} - {status}")
        except Exception as e:
            logger.error(f"Error logging to CSV: {e}")
    
    def _signal_received_callback(self, signal):
        """Callback when signal is received from Telegram (for CSV logging)"""
        self._log_call_to_csv(signal, status='RECEIVED')
    
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
                    row[2] == str(signal.get('strike', '')) and 
                    row[3] == signal.get('option_type', '') and
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
            
            logger.info(f"Call status updated in CSV: {signal['symbol']} {signal['strike']} {signal['option_type']} - {status}")
        except Exception as e:
            logger.error(f"Error updating CSV status: {e}")
    
    def save_trade_history(self):
        """Save trade history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump({
                    'trading_session': {
                        'start_capital': self.start_capital,
                        'end_capital': self.current_capital,  # Use current capital (updated with P&L)
                        'total_pnl': self.current_capital - self.start_capital,
                        'total_trades': len(self.trade_history),
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'signal_source': 'TELEGRAM_ONLY'
                    },
                    'trades': self.trade_history
                }, f, indent=2)
            logger.info("Telegram trade history saved to telegram_trade_history.json")
        except Exception as e:
            logger.error(f"Error saving trade history: {e}")
    
    def update_trade_exit(self, signal, pnl, exit_price, exit_reason, expected_outcome=''):
        """Update CSV when trade exits (SL/TP hit)"""
        try:
            self._update_call_status(
                signal, 
                status='EXITED', 
                pnl=pnl, 
                exit_price=exit_price, 
                exit_reason=exit_reason,
                expected_outcome=expected_outcome
            )
            logger.info(f"Trade exit updated in CSV: {signal['symbol']} {signal['strike']} {signal['option_type']} - P&L: {pnl}")
        except Exception as e:
            logger.error(f"Error updating trade exit: {e}")
    
    def is_market_open(self):
        """Check if market is currently open"""
        current_time = datetime.now().time()
        return self.market_open <= current_time <= self.market_close
    
    def execute_trade(self, signal):
        """Execute trade based on Telegram signal"""
        try:
            symbol = signal['symbol']
            strike = signal['strike']
            option_type = signal['option_type']
            entry = signal['entry']
            sl = signal['sl']
            target = signal['target']
            
            logger.info(f"Executing trade: {symbol} {strike} {option_type} @ {entry}")
            
            # Note: CSV logging is done automatically by signal_received_callback
            
            # STEP 1: Entry Timing Filter (FIRST CHECK)
            is_valid_timing, timing_reason = self.timing_filter.is_valid_entry_time(signal)
            if not is_valid_timing:
                logger.warning(f"[TIMING FILTER] {timing_reason}")
                self._update_call_status(signal, status='BLOCKED', exit_reason=timing_reason)
                return False
            
            # STEP 2: Basic Signal Validation (EXECUTION PROTECTION)
            # Get current price for validation
            try:
                # Use the tradingsymbol from signal to get current price
                tradingsymbol = signal.get('tradingsymbol')
                instrument_token = signal.get('instrument_token')
                
                current_price = None
                if instrument_token:
                    ltp_data = self.kite_client.get_ltp([instrument_token])
                    if ltp_data and instrument_token in ltp_data:
                        current_price = ltp_data[instrument_token].get('last_price', 0)
                elif tradingsymbol:
                    ltp_data = self.kite_client.get_ltp([f"NFO:{tradingsymbol}"])
                    if ltp_data and f"NFO:{tradingsymbol}" in ltp_data:
                        current_price = ltp_data[f"NFO:{tradingsymbol}"].get('last_price', 0)
                
                # Prepare market data for validation
                market_data = {
                    "price": current_price if current_price else entry,  # Fallback to entry if no price
                    "support": None,  # Telegram signals don't have OptionStar data
                    "resistance": None  # Telegram signals don't have OptionStar data
                }
                
                # Add timestamp to signal for freshness check
                signal["timestamp"] = datetime.now().timestamp()
                
                # Validate signal
                is_valid, validation_reason = self.signal_validator.validate(signal, market_data)
                if not is_valid:
                    logger.warning(f"[VALIDATION BLOCKED] {validation_reason}")
                    self._update_call_status(signal, status='BLOCKED', exit_reason=validation_reason)
                    return False
                
                logger.info(f"[VALIDATION PASSED] {validation_reason}")
                
            except Exception as e:
                logger.warning(f"Could not get current price for validation: {e}")
                # Continue anyway if price fetch fails (don't block on validation failure)
            
            # STEP 3: Check risk limits
            can_trade = can_execute_trade()
            if not can_trade:
                logger.error("Trade blocked by risk management")
                self._update_call_status(signal, status='BLOCKED', exit_reason='Risk Management')
                return False
            
            # STEP 4: Calculate position size using Risk Management Service
            lot_size = signal.get('lot_size', 1)  # Get lot size from signal or default to 1
            
            position_calc = self.risk_service.calculate_position_size(entry, lot_size, self.current_capital)
            
            if not position_calc.get("success"):
                logger.error(f"Position sizing failed: {position_calc.get('error')}")
                return False
            
            actual_lots = position_calc["actual_lots"]
            cost_per_lot = position_calc["cost_per_lot"]
            total_cost = position_calc["total_cost"]
            
            logger.info(f"Position sizing: {actual_lots} lot(s) @ ₹{cost_per_lot}/lot = ₹{total_cost} total")
            
            # STEP 5: Calculate risk parameters using Risk Management Service
            risk_params = self.risk_service.calculate_risk_parameters(entry, actual_lots, "CALL" if option_type == "CE" else "PUT", self.current_capital)
            
            if not risk_params.get("success"):
                logger.error(f"Risk parameter calculation failed: {risk_params.get('error')}")
                return False
            
            stoploss_price = risk_params["stoploss_price"]
            target_price = risk_params["target_price"]
            risk_amount = risk_params["risk_amount"]
            
            logger.info(f"Risk parameters: SL ₹{stoploss_price}, Target ₹{target_price}, Risk ₹{risk_amount:.2f} ({(risk_amount/self.current_capital*100):.1f}%)")
            
            # For Telegram-only bot, we bypass Execution Brain and go directly to Trade Manager
            # Telegram signals are already validated and complete
            trade = {
                "symbol": symbol,
                "tradingsymbol": signal.get("tradingsymbol"),  # Full option symbol for LTP
                "instrument_token": signal.get("instrument_token"),  # Token for API calls
                "signal": "CALL" if option_type == "CE" else "PUT",
                "strike": strike,
                "entry": entry,
                "sl": stoploss_price,  # Use risk service calculated SL
                "target": target_price,  # Use risk service calculated target
                "expiry": signal.get("expiry", "N/A"),  # Dynamic expiry from contract
                "lot_size": actual_lots  # Use risk service calculated lots
            }
            
            success = self.trade_manager.add_trade(symbol, trade)
            
            if success:
                self.active_trades[symbol] = trade
                logger.info(f"Trade added to manager: {symbol} {strike} {option_type}")
                
                # NO WebSocket subscription (using REST API only)
                logger.info(f"Using REST API for price updates (WebSocket disabled)")
                
                # Update CSV status to EXECUTED
                self._update_call_status(signal, status='EXECUTED')
                return True
            else:
                logger.error(f"Failed to add trade to manager")
                self._update_call_status(signal, status='FAILED', exit_reason='Trade Manager Error')
                return False
                
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            self._update_call_status(signal, status='ERROR', exit_reason=str(e))
            return False
    
    def monitor_trades(self):
        """Monitor active trades and update prices (single pass, called by main loop)"""
        if not self.active_trades:
            return
        
        logger.info(f"Monitoring {len(self.active_trades)} active trades")
        
        # Update prices for active trades
        for symbol, trade in self.active_trades.items():
            try:
                tradingsymbol = trade.get('tradingsymbol')
                instrument_token = trade.get('instrument_token')
                
                if not tradingsymbol:
                    logger.warning(f"No tradingsymbol in trade data for {symbol}")
                    continue
                
                # Use instrument token (cleanest approach) OR add NFO prefix
                # Zerodha expects: "NFO:TRADINGSYMBOL" or [token]
                if instrument_token:
                    # Use token directly (cleanest, no symbol issues)
                    logger.debug(f"Fetching LTP for token: {instrument_token}")
                    ltp_data = self.kite_client.get_ltp([instrument_token])
                    
                    if ltp_data and instrument_token in ltp_data:
                        current_price = ltp_data[instrument_token].get('last_price', 0)
                    else:
                        logger.warning(f"Could not get LTP for token {instrument_token}")
                else:
                    # Fallback: Use NFO prefix with tradingsymbol
                    logger.debug(f"Fetching LTP for NFO:{tradingsymbol}")
                    ltp_data = self.kite_client.get_ltp([f"NFO:{tradingsymbol}"])
                    
                    if ltp_data and f"NFO:{tradingsymbol}" in ltp_data:
                        current_price = ltp_data[f"NFO:{tradingsymbol}"].get('last_price', 0)
                    else:
                        logger.warning(f"Could not get LTP for NFO:{tradingsymbol}")
                
                if current_price and current_price > 0:
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
                    logger.warning(f"Invalid LTP for {tradingsymbol}: {current_price}")
            except Exception as e:
                logger.error(f"Error updating price for {symbol}: {e}")
        
        logger.info(">>> MONITOR LOOP CYCLE COMPLETE <<<")
    
    def run(self):
        """Main run loop for Telegram-only bot"""
        logger.info("Starting Telegram-only bot...")
        
        # Start Telegram service in background
        if self.telegram_service:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                def run_telegram():
                    loop.run_until_complete(self.telegram_service.start())
                
                telegram_thread = threading.Thread(target=run_telegram, daemon=True)
                telegram_thread.start()
                logger.info("Telegram Service started in background")
            except Exception as e:
                logger.error(f"Failed to start Telegram Service: {e}")
                return
        
        # Wait for market to open
        while not self.is_market_open():
            logger.info("Waiting for market to open...")
            time.sleep(60)
        
        logger.info("Market is open - ready to receive Telegram signals")
        
        # Main monitoring loop
        try:
            while self.is_market_open():
                # Check risk limits
                can_trade = can_execute_trade()
                if not can_trade:
                    logger.warning("Trading blocked by risk management")
                    time.sleep(60)
                    continue
                
                # External dashboard only (no console rendering to preserve logs)
                # Dashboard data is written to dashboard_data.json automatically
                # Run dashboard_viewer.py in separate terminal to see the dashboard
                
                # Check if there are active trades to monitor
                if self.active_trades:
                    # Monitor trades (single pass)
                    self.monitor_trades()
                    time.sleep(5)  # Small delay between monitoring cycles
                else:
                    # No active trades - waiting for Telegram signals
                    logger.info("Waiting for Telegram signals...")
                    time.sleep(10)
                
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
        
        logger.info("Telegram-only bot stopped")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Telegram-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    parser.add_argument('--paper-trading', action='store_true',
                       help='Paper trading with REAL market data but NO real orders (recommended for testing)')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    parser.add_argument('--disable-watchdog', action='store_true',
                       help='Disable watchdog monitoring (enabled by default)')
    
    args = parser.parse_args()
    
    # Create bot
    bot = TelegramOnlyBot(investment_amount=args.investment)
    
    # Handle watchdog disable (enabled by default)
    if args.disable_watchdog and bot.watchdog_service:
        bot.watchdog_service.stop_monitoring()
        logger.info("Watchdog monitoring disabled via command line")
    
    # Override paper trading if --paper-trading or --live flag is set
    if args.paper_trading:
        bot.paper_trading = True
        logger.info("PAPER TRADING MODE - Real Market Data, No Real Orders")
    elif args.live:
        bot.paper_trading = False
        logger.warning("LIVE MODE ENABLED - REAL MONEY AT RISK!")
    
    # Run bot
    bot.run()

if __name__ == "__main__":
    main()

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
from kite_client import KiteClient
from services.telegram_service.telegram_service import TelegramService
from services.trade_manager_service.service import TradeManagerService
from risk_wrapper import can_execute_trade, update_trade_result, reset_daily_limits, get_risk_status

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class TelegramOnlyBot:
    def __init__(self, investment_amount=30000):
        # Load config
        with open('config.json', 'r') as f:
            self.config = json.load(f)
        
        self.investment_amount = investment_amount
        self.paper_trading = self.config.get("paper_trading", True)
        
        logger.info("=" * 80)
        logger.info("TELEGRAM-ONLY TRADING BOT")
        logger.info("=" * 80)
        logger.info(f"Investment: ₹{investment_amount}")
        logger.info(f"Mode: {'PAPER TRADING' if self.paper_trading else 'LIVE TRADING'}")
        logger.info("Signal Source: Telegram Only (No internal signals)")
        logger.info("=" * 80)
        
        # Initialize Kite Client
        self.kite_client = KiteClient(
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            paper_trading=self.paper_trading
        )
        
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
        
        # Initialize Telegram Service with callback
        telegram_config = self.config.get("telegram", {})
        if telegram_config.get("enabled", False):
            try:
                self.telegram_service = TelegramService(
                    api_id=telegram_config.get("api_id"),
                    api_hash=telegram_config.get("api_hash"),
                    group_id=telegram_config.get("group_id"),
                    signal_callback=self.execute_trade,  # Direct callback for execution
                    signal_received_callback=self._signal_received_callback  # Callback for CSV logging
                )
                logger.info("Telegram Service initialized with direct callback and CSV logging")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram Service: {e}")
                self.telegram_service = None
        else:
            logger.error("Telegram not enabled in config - cannot run without Telegram")
            raise Exception("Telegram service required for Telegram-only bot")
        
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
            with open('telegram_trade_history.json', 'w') as f:
                json.dump({
                    'trading_session': {
                        'start_capital': self.investment_amount,
                        'end_capital': self.investment_amount,  # Will be updated with real P&L
                        'total_pnl': 0,
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
            
            # Check risk limits
            can_trade = can_execute_trade()
            if not can_trade:
                logger.error("Trade blocked by risk management")
                self._update_call_status(signal, status='BLOCKED', exit_reason='Risk Management')
                return False
            
            # For Telegram-only bot, we bypass Execution Brain and go directly to Trade Manager
            # Telegram signals are already validated and complete
            trade = {
                "symbol": symbol,
                "signal": "CALL" if option_type == "CE" else "PUT",
                "strike": strike,
                "entry": entry,
                "sl": sl,
                "target": target,
                "expiry": "N/A"
            }
            
            success = self.trade_manager.add_trade(symbol, trade)
            
            if success:
                self.active_trades[symbol] = trade
                logger.info(f"Trade added to manager: {symbol} {strike} {option_type}")
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
        """Monitor active trades and update prices"""
        while True:
            try:
                if not self.is_market_open():
                    logger.info("Market closed - stopping trade monitoring")
                    break
                
                # Update prices for active trades
                for symbol, trade in self.active_trades.items():
                    try:
                        # Get current price (simplified - in production use WebSocket)
                        quote = self.kite_client.get_quote(symbol)
                        if quote:
                            current_price = quote.get('last_price', 0)
                            self.trade_manager.update_price(symbol, current_price)
                    except Exception as e:
                        logger.error(f"Error updating price for {symbol}: {e}")
                
                # Render dashboard
                self.trade_manager.render_dashboard()
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in trade monitoring: {e}")
                time.sleep(5)
    
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
                
                # Render dashboard
                self.trade_manager.render_dashboard()
                
                # Check if there are active trades to monitor
                if self.active_trades:
                    # Monitor trades
                    self.monitor_trades()
                else:
                    # No active trades - waiting for Telegram signals
                    logger.info("Waiting for Telegram signals...")
                    time.sleep(10)
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        
        # Save trade history
        self.save_trade_history()
        
        logger.info("Telegram-only bot stopped")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Telegram-Only Trading Bot')
    parser.add_argument('--investment', type=float, default=30000,
                       help='Investment amount (default: 30000)')
    parser.add_argument('--live', action='store_true',
                       help='Force live mode with real orders (REAL MONEY AT RISK)')
    
    args = parser.parse_args()
    
    # Create bot
    bot = TelegramOnlyBot(investment_amount=args.investment)
    
    # Override paper trading if --live flag is set
    if args.live:
        bot.paper_trading = False
        logger.warning("LIVE MODE ENABLED - REAL MONEY AT RISK!")
    
    # Run bot
    bot.run()

if __name__ == "__main__":
    main()

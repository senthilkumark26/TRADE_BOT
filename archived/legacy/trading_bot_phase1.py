"""
Phase 1 Trading Bot - 2-Engine Architecture
--------------------------------------------
Strict Phase 1 Implementation:
- Engine 1: Fast Market Analyzer (Main Thread) - Non-blocking
- Engine 2: Async LLM Worker (Background Thread) - Queue-based
- Execution & Risk Manager: Single-leg, fixed trailing SL, ₹5,000 daily target

This is a clean, stable architecture designed for reliability and non-blocking operation.
"""

import logging
import time
import json
import threading
import argparse
from typing import Dict, Any, Optional, List
from datetime import datetime, time as dt_time

from kite_client import KiteClient
from engine1_market_analyzer import Engine1MarketAnalyzer
from engine2_llm_worker import Engine2LLMWorker
from execution_risk_manager import ExecutionRiskManager
from llm_market_analyzer import LLMMarketAnalyzer
from gemini_integration import GeminiIntegration

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("trading_bot_phase1.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Kite Connect Symbol Mapping
SYMBOL_MAP = {
    "NIFTY": "256265",
    "BANKNIFTY": "260105",
    "INFY": "408065",
    "TCS": "438821",
    "HDFCBANK": "341249",
    "ICICIBANK": "887457",
    "SBIN": "779521",
    "AXISBANK": "590981",
    "KOTAKBANK": "895329",
}


class TradingBotPhase1:
    """
    Phase 1 Trading Bot with 2-Engine Architecture.
    
    Engine 1 (Main Thread): Fast Market Analyzer - NEVER BLOCKS
    Engine 2 (Background Thread): Async LLM Worker - Queue-based
    
    This architecture ensures the main thread never blocks on LLM calls.
    """
    
    def __init__(self):
        """Initialize Phase 1 Trading Bot."""
        self.config_path = "config.json"
        self.load_config()
        
        # Bot state
        self.bot_running = False
        self.market_data = {}
        
        # Initialize Kite Client
        api_key = self.config.get("api_key", "")
        access_token = self.config.get("access_token", "")
        use_demo_data = self.config.get("use_demo_data", False)
        
        if use_demo_data:
            logger.info("=" * 80)
            logger.info("DEMO MODE DISABLED - Demo simulator removed from codebase")
            logger.info("=" * 80)
            self.kite_client = KiteClient(api_key, access_token)
        else:
            self.kite_client = KiteClient(api_key, access_token)
        
        # Initialize Engine 1 (Fast Market Analyzer)
        self.engine1 = Engine1MarketAnalyzer(self.kite_client)
        logger.info("✅ Engine 1 (Fast Market Analyzer) initialized")
        
        # Initialize LLM Analyzer
        self.llm_analyzer = self._init_llm_analyzer()
        
        # Initialize Engine 2 (Async LLM Worker)
        self.engine2 = Engine2LLMWorker(self.llm_analyzer, config=self.config)
        self.engine2.start()
        logger.info("✅ Engine 2 (Async LLM Worker) started with production-grade features")
        
        # Initialize Execution & Risk Manager
        daily_target = 5000  # ₹5,000 daily target
        self.risk_manager = ExecutionRiskManager(self.kite_client, daily_target=daily_target)
        logger.info(f"✅ Execution & Risk Manager initialized (Daily Target: ₹{daily_target})")

        # Initialize trading bot for real-time price updates
        from trading_bot import CleanTradingBot
        self.trading_bot = CleanTradingBot()
        logger.info("✅ Trading Bot initialized for real-time price updates")
        
        # Trading universe
        self.watchlist = self._load_watchlist()
        
        # Pending validations (request_id -> signal_data)
        self.pending_validations = {}
        
        # Statistics
        self.stats = {
            'cycles': 0,
            'signals_generated': 0,
            'llm_submitted': 0,
            'llm_approved': 0,
            'llm_rejected': 0,
            'executed_trades': 0
        }
        
        logger.info("=" * 80)
        logger.info("PHASE 1 TRADING BOT - 2-ENGINE ARCHITECTURE")
        logger.info("=" * 80)
        logger.info(f"Trading Universe: {self.watchlist}")
        logger.info(f"Engine 1: Fast Market Analyzer (Non-blocking)")
        logger.info(f"Engine 2: Async LLM Worker (Queue-based)")
        logger.info(f"Risk Manager: Single-leg, ₹5,000 daily target")
        logger.info("=" * 80)
    
    def load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self.config = {}
    
    def _init_llm_analyzer(self):
        """Initialize LLM analyzer based on config."""
        try:
            llm_provider = self.config.get("llm_provider", "ollama")
            logger.info(f"LLM Provider: {llm_provider}")
            
            if llm_provider == "openai":
                openai_config = self.config.get("openai", {})
                if openai_config.get("enabled", False):
                    from openai_integration import OpenAIIntegration
                    api_key = openai_config.get("api_key", "")
                    model = openai_config.get("default_model", "gpt-4o-mini")
                    return OpenAIIntegration(api_key=api_key, model_name=model)
            
            elif llm_provider == "gemini":
                gemini_config = self.config.get("gemini", {})
                if gemini_config.get("enabled", False):
                    api_key = gemini_config.get("api_key", "")
                    model = gemini_config.get("default_model", "gemini-1.5-flash")
                    return GeminiIntegration(api_key=api_key, model_name=model)
            
            elif llm_provider == "ollama":
                ollama_config = self.config.get("ollama", {})
                if ollama_config.get("enabled", False):
                    ollama_url = ollama_config.get("base_url", "http://localhost:11434")
                    model = ollama_config.get("default_model", "phi3:mini")
                    mode = ollama_config.get("trading_mode", "moderate")
                    return LLMMarketAnalyzer(ollama_url=ollama_url, model=model, mode=mode)
            
            logger.warning("LLM not enabled in config, using fallback logic")
            return None
            
        except Exception as e:
            logger.error(f"Error initializing LLM analyzer: {e}")
            return None
    
    def _load_watchlist(self) -> List[str]:
        """Load watchlist from config."""
        try:
            instruments = self.config.get("instruments", {})
            watchlist = list(instruments.keys())
            logger.info(f"Loaded watchlist: {watchlist}")
            return watchlist
        except Exception as e:
            logger.error(f"Error loading watchlist: {e}")
            return ["NIFTY", "BANKNIFTY"]
    
    def get_live_quotes(self, instrument_keys: List[str]) -> Dict[str, Dict]:
        """
        Get live market data for instruments.
        
        Args:
            instrument_keys: List of instrument tokens/symbols
            
        Returns:
            Dictionary with LTP data
        """
        try:
            # Demo mode: return mock data
            if self.config.get("use_demo_data", False):
                mock_data = {}
                for key in instrument_keys:
                    if '256265' in key or 'NIFTY' in str(key).upper():
                        base_price = 23600
                    elif '260105' in key or 'BANKNIFTY' in str(key).upper():
                        base_price = 48000
                    else:
                        base_price = 2500
                    
                    import random
                    variation = random.randint(-50, 50)
                    mock_data[key] = {'ltp': base_price + variation}
                
                return mock_data
            
            # Live mode: use Kite client
            ltp_data = self.kite_client.get_ltp(instrument_keys)
            return ltp_data if ltp_data else {}
            
        except Exception as e:
            logger.error(f"Error fetching live quotes: {e}")
            return {}
    
    def get_option_chain(self, symbol: str, spot_price: float) -> List[Dict]:
        """
        Get option chain data for PCR/OI calculation.
        
        Args:
            symbol: Instrument symbol
            spot_price: Current spot price
            
        Returns:
            List of option chain data
        """
        try:
            # For Phase 1, use empty option chain (legacy file - not used by active system)
            # In production, this would fetch real option chain from Kite
            option_chain = []
            
            # Update Engine 1's option chain cache
            self.engine1.update_option_chain(symbol, option_chain)
            
            return option_chain
            
        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return []
    
    def is_market_hours(self) -> bool:
        """Check if market is open."""
        if self.config.get("paper_trading", False):
            return True  # Always open in paper trading mode
        
        now = datetime.now().time()
        market_open = dt_time(9, 15)
        market_close = dt_time(15, 30)
        return market_open <= now <= market_close
    
    def run_main_loop(self):
        """
        Main trading loop - NON-BLOCKING.
        
        This is the heart of the 2-engine architecture:
        1. Engine 1 processes tick data and generates signals (NEVER BLOCKS)
        2. Engine 2 validates signals asynchronously in background
        3. Execution happens when validation completes
        """
        logger.info("=" * 80)
        logger.info("MAIN TRADING LOOP STARTED")
        logger.info("=" * 80)
        
        cycle_count = 0
        
        while self.bot_running:
            try:
                cycle_count += 1
                self.stats['cycles'] = cycle_count
                
                logger.info(f"\n{'=' * 80}")
                logger.info(f"CYCLE {cycle_count}")
                logger.info(f"{'=' * 80}")
                
                # STEP 1: Monitor existing positions (NON-BLOCKING)
                self._monitor_positions()
                
                # STEP 2: Check daily target halt
                pnl_summary = self.risk_manager.get_daily_pnl()
                if pnl_summary['halt_triggered']:
                    logger.warning("Daily target halt triggered - trading stopped")
                    break
                
                # STEP 3: Monitor existing positions if any, then scan for new signals
                active_positions = self.risk_manager.get_active_positions()
                if len(active_positions) > 0:
                    logger.info(f"Active positions: {len(active_positions)} - monitoring and updating P&L")
                    self._monitor_positions()  # Actually monitor the positions
                    time.sleep(5)
                    continue  # Skip new scanning while monitoring existing positions
                
                # STEP 4: Scan market for signals (Engine 1 - NON-BLOCKING)
                self._scan_market()
                
                # STEP 5: Check for completed LLM validations (NON-BLOCKING)
                self._check_validation_results()
                
                # STEP 6: Print summary
                if cycle_count % 5 == 0:
                    self._print_summary()
                
                # Controlled frequency (non-blocking)
                time.sleep(10)  # 10-second cycle time
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)
        
        logger.info("Main trading loop stopped")
    
    def _monitor_positions(self):
        """Monitor existing positions and update prices using real market data."""
        active_positions = self.risk_manager.get_active_positions()

        for position in active_positions:
            position_id = position['position_id']
            symbol = position['symbol']
            strike = position.get('strike', 0)
            direction = position.get('direction', 'CALL')

            try:
                # Get real current option price from market
                current_price = self.trading_bot.get_real_option_price(symbol, strike, direction)

                if current_price:
                    self.risk_manager.update_position_price(position_id, current_price)
                    logger.info(f"Updated {symbol} {strike} {direction}: ₹{current_price:.2f}")
                else:
                    logger.warning(f"Failed to get price for {symbol} {strike} {direction}")
            except Exception as e:
                logger.error(f"Error monitoring position {position_id}: {e}")
    
    def _scan_market(self):
        """Scan market for trading signals using Engine 1."""
        for symbol in self.watchlist:
            if not self.bot_running:
                break
            
            # Check market hours
            if not self.is_market_hours():
                logger.info(f"Market closed for {symbol}")
                continue
            
            try:
                # Get instrument token
                instrument_key = SYMBOL_MAP.get(symbol, symbol)
                
                # Get live quote
                quotes = self.get_live_quotes([instrument_key])
                if not quotes or instrument_key not in quotes:
                    logger.warning(f"No quote for {symbol}")
                    continue
                
                # Extract price
                quote_data = quotes[instrument_key]
                current_price = quote_data.get('ltp', 0)
                
                if current_price == 0:
                    logger.warning(f"Invalid price for {symbol}")
                    continue
                
                # Update Engine 1 price history
                vwap = self.engine1.update_price(symbol, current_price)
                
                # Calculate price change
                price_history = self.engine1.price_history.get(symbol, [])
                if len(price_history) >= 2:
                    prev_price = price_history[-2][0]
                    price_change = ((current_price - prev_price) / prev_price) * 100
                else:
                    price_change = 0.0
                
                # Get option chain for PCR/OI
                self.get_option_chain(symbol, current_price)
                
                # Generate signal using Engine 1 (NON-BLOCKING)
                signal = self.engine1.generate_signal(symbol, current_price, price_change)
                
                if signal:
                    self.stats['signals_generated'] += 1
                    logger.info(f"🚀 Signal generated: {signal['direction']} {symbol}")
                    
                    # Submit to Engine 2 for validation (NON-BLOCKING)
                    request_id = self.engine2.submit_validation_request(signal)
                    
                    if request_id:
                        self.stats['llm_submitted'] += 1
                        self.pending_validations[request_id] = signal
                        logger.info(f"📤 Submitted to Engine 2: {request_id}")
                
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
    
    def _check_validation_results(self):
        """Check for completed LLM validations from Engine 2."""
        # Get list of pending request IDs
        pending_ids = list(self.pending_validations.keys())
        
        for request_id in pending_ids:
            # Check if result is available (non-blocking with timeout)
            result = self.engine2.get_validation_result(request_id, timeout=0.1)
            
            if result:
                # Get the original signal
                signal = self.pending_validations[request_id]
                
                # Remove from pending
                del self.pending_validations[request_id]
                
                # Process result
                approved = result.get('result', {}).get('approved', False)
                reason = result.get('result', {}).get('reason', '')
                
                if approved:
                    self.stats['llm_approved'] += 1
                    logger.info(f"✅ LLM Approved: {request_id} - {reason}")
                    
                    # Execute trade
                    self._execute_signal(signal)
                else:
                    self.stats['llm_rejected'] += 1
                    logger.info(f"❌ LLM Rejected: {request_id} - {reason}")
    
    def _execute_signal(self, signal: Dict[str, Any]):
        """
        Execute a validated signal.
        
        Args:
            signal: Validated signal data
        """
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            strike = signal['strike']
            
            # Get option entry price
            entry_price = self._get_option_entry_price(symbol, strike, direction)
            
            if not entry_price or entry_price <= 0:
                logger.warning(f"Could not get entry price for {symbol} {strike} {direction}")
                return
            
            # Execute single-leg trade
            position_id = self.risk_manager.execute_single_leg(
                signal_data=signal,
                entry_price=entry_price,
                quantity=1  # Phase 1: Always 1 lot
            )
            
            if position_id:
                self.stats['executed_trades'] += 1
                logger.info(f"✅ Trade executed: {position_id}")
            else:
                logger.warning("Trade execution failed")
                
        except Exception as e:
            logger.error(f"Error executing signal: {e}")
    
    def _get_option_entry_price(self, symbol: str, strike: int, direction: str) -> Optional[float]:
        """
        Get option entry price from market.
        
        Args:
            symbol: Instrument symbol
            strike: Strike price
            direction: CALL or PUT
            
        Returns:
            Entry price or None if unavailable
        """
        try:
            # Generate option symbol
            option_symbol = self._get_option_symbol(symbol, strike, direction)
            
            if not option_symbol:
                return None
            
            # Get LTP
            ltp_data = self.get_live_quotes([option_symbol])
            if ltp_data and option_symbol in ltp_data:
                return ltp_data[option_symbol].get('ltp', 0)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting option entry price: {e}")
            return None
    
    def _get_option_symbol(self, symbol: str, strike: int, direction: str) -> Optional[str]:
        """
        Generate option symbol format.
        
        Args:
            symbol: Instrument symbol
            strike: Strike price
            direction: CALL or PUT
            
        Returns:
            Option symbol string
        """
        try:
            # Hardcode expiry for Phase 1 simplicity
            expiry = "26JUN"
            opt_type = "CE" if direction == "CALL" else "PE"
            
            # Format: NFO:SYMBOLYYMONDDSTRIKECE/PE
            full_symbol = f"NFO:{symbol}{expiry}{strike}{opt_type}"
            
            return full_symbol
            
        except Exception as e:
            logger.error(f"Error generating option symbol: {e}")
            return None
    
    def _print_summary(self):
        """Print trading summary."""
        logger.info("=" * 80)
        logger.info("TRADING SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Cycles: {self.stats['cycles']}")
        logger.info(f"Signals Generated: {self.stats['signals_generated']}")
        logger.info(f"LLM Submitted: {self.stats['llm_submitted']}")
        logger.info(f"LLM Approved: {self.stats['llm_approved']}")
        logger.info(f"LLM Rejected: {self.stats['llm_rejected']}")
        logger.info(f"Executed Trades: {self.stats['executed_trades']}")
        
        # Print risk manager summary
        self.risk_manager.print_position_summary()
        
        # Print Engine 2 stats
        engine2_stats = self.engine2.get_stats()
        logger.info(f"Engine 2 Stats: {engine2_stats}")
        
        logger.info("=" * 80)
    
    def start(self):
        """Start the trading bot."""
        self.bot_running = True
        logger.info("Bot started")
        
        try:
            self.run_main_loop()
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the trading bot."""
        self.bot_running = False
        
        # Stop Engine 2
        self.engine2.stop()
        
        # Close all positions
        self.risk_manager._close_all_positions(reason="Bot stopped")
        
        logger.info("Bot stopped and cleaned up")


def main():
    """Main entry point with command-line argument support."""
    parser = argparse.ArgumentParser(
        description='Phase 1 Trading Bot - 2-Engine Architecture',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python trading_bot_phase1.py --enable-paper-trade-bot
  python trading_bot_phase1.py --enable-paper-trade-bot --verbose
        '''
    )
    
    parser.add_argument(
        '--enable-paper-trade-bot',
        action='store_true',
        help='Enable the Phase 1 paper trading bot'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.enable_paper_trade_bot:
        print("=" * 80)
        print("PHASE 1 PAPER TRADING BOT - 2-ENGINE ARCHITECTURE")
        print("=" * 80)
        print("Starting bot with production-grade features...")
        print()
    else:
        print("=" * 80)
        print("PHASE 1 TRADING BOT - 2-ENGINE ARCHITECTURE")
        print("=" * 80)
        print("Starting bot...")
        print()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    bot = TradingBotPhase1()
    bot.start()


if __name__ == "__main__":
    main()

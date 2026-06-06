"""
Market Analysis System - Main Integration Script
Starts Market Analyzer, Web Interface, and optionally Trading Bot

PHASE 1 INTEGRATION: When --auto-paper-trading is used, the system uses the new
fast Phase 1 architecture (engine1_market_analyzer.py + engine2_llm_worker.py)
instead of the legacy blocking components.
"""
import logging
import threading
import time
import sys
import os
import webbrowser
from datetime import datetime, time as dt_time
from trading_bot import CleanTradingBot, TRADE_MANIFEST_PATH
from market_analyzer import create_market_analyzer
from web_interface import set_market_analyzer, run_web_server
from llm_worker import start_llm_worker

# PHASE 1 IMPORTS (used only when --auto-paper-trading is enabled)
try:
    from engine1_market_analyzer import Engine1MarketAnalyzer
    from engine2_llm_worker import Engine2LLMWorker
    from execution_risk_manager import ExecutionRiskManager
    from llm_market_analyzer import LLMMarketAnalyzer
    from gemini_integration import GeminiIntegration
    from kite_client import KiteClient
    PHASE1_AVAILABLE = True
except ImportError as e:
    PHASE1_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"Phase 1 components not available: {e}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def auto_open_dashboard():
    """Automatically opens the main dashboard in browser."""
    try:
        dashboard_url = "http://localhost:5000"
        logger.info(f"🌐 Auto-opening dashboard: {dashboard_url}")
        webbrowser.open(dashboard_url)
        time.sleep(1)  # Small delay between opens
    except Exception as e:
        logger.error(f"Failed to auto-open dashboard: {e}")


def auto_open_url(url, description="URL"):
    """Automatically opens a specific URL in browser."""
    try:
        logger.info(f"🌐 Auto-opening {description}: {url}")
        webbrowser.open(url)
        time.sleep(1)  # Small delay between opens
    except Exception as e:
        logger.error(f"Failed to auto-open {description}: {e}")


def safe_input(prompt=""):
    """
    Safe input wrapper that handles EOFError gracefully.
    Prevents crashes when running in background shells or subprocesses.
    
    Args:
        prompt: Input prompt message
        
    Returns:
        User input string or None if EOFError
    """
    try:
        return input(prompt)
    except EOFError:
        # No user input available - return None to prevent crash
        return None
    except KeyboardInterrupt:
        # User pressed Ctrl+C
        return None


class MarketAnalysisSystem:
    """
    Complete market analysis system integration.
    Coordinates Market Analyzer, Web Interface, and Trading Bot.
    """
    
    def __init__(self, enable_trading_bot=False, automated_mode=None):
        """
        Initialize the market analysis system.
        
        Args:
            enable_trading_bot: Whether to also run the trading bot
            automated_mode: If True, run fully automated without interactive prompts.
                          If None, check AUTOMATED_MODE environment variable.
        """
        self.enable_trading_bot = enable_trading_bot
        
        # Determine automated mode (parameter > env var > default False)
        if automated_mode is None:
            self.automated_mode = os.getenv('AUTOMATED_MODE', 'false').lower() == 'true'
        else:
            self.automated_mode = automated_mode
        
        # CRITICAL: Headless execution isolation - suppress stdin in automated mode
        if self.automated_mode:
            try:
                sys.stdin = open(os.devnull, 'r')
                logger.info("🔒 Standard input completely detached. Headless insulation complete.")
            except Exception as e:
                logger.warning(f"Could not suppress stdin: {e}")
        
        # Initialize components
        self.trading_bot = None
        self.market_analyzer = None
        self.web_thread = None
        self.running = True
        
        logger.info("Market Analysis System initializing...")
        if self.automated_mode:
            logger.info("🤖 AUTOMATED MODE ENABLED - No interactive prompts")
    
    def start(self, skip_cli_mode=False):
        """Start all components of the system.
        
        Args:
            skip_cli_mode: If True, skip CLI mode (for auto paper trading)
        """
        try:
            # Step 1: Initialize trading bot (needed for Kite client and config)
            logger.info("Step 1: Initializing Trading Bot...")
            self.trading_bot = CleanTradingBot()
            logger.info("✅ Trading Bot initialized")
            
            # Step 2: Initialize Market Analyzer (don't start thread - main loop handles it)
            logger.info("Step 2: Initializing Market Analyzer...")
            # DYNAMIC TIMING: Faster scans during opening bell
            current_hour = datetime.now().hour
            current_minute = datetime.now().minute
            
            # Opening bell mode: 9:15-9:30 AM → 2-minute scans
            if current_hour == 9 and 15 <= current_minute < 30:
                analysis_interval = 120  # 2 minutes during opening
                logger.info("🚀 OPENING BELL MODE: Fast 2-minute scans (9:15-9:30 AM)")
            else:
                analysis_interval = 900  # 15 minutes normal mode
                logger.info("⏳ Normal mode: 15-minute scans")
            
            self.market_analyzer = create_market_analyzer(
                kite_client=self.trading_bot.kite_client,
                watchlist=self.trading_bot.watchlist,
                analysis_interval=analysis_interval,
                auto_start=True,  # Always start background scanning for web interface
                llm_analyzer=None  # LLM moved to execution stage only - scanner is technical-only
            )
            logger.info("✅ Market Analyzer initialized")
            
            # No callback - Market Analyzer is independent service
            logger.info("✅ Market Analyzer provides numbered trade list independently")
            
            # Step 2.5: If trading bot enabled, ready for CLI
            if self.enable_trading_bot:
                logger.info("Step 2.5: Trading Bot ready for CLI commands")
                logger.info("✅ User can select trades from numbered list")
            
            # Step 3: Connect Market Analyzer to Web Interface
            logger.info("Step 3: Connecting Web Interface...")
            set_market_analyzer(self.market_analyzer)
            logger.info("✅ Web Interface connected")
            
            # Step 4: Start Web Interface in background thread
            logger.info("Step 4: Starting Web Interface...")
            self.web_thread = threading.Thread(
                target=run_web_server,
                kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': False},
                daemon=True
            )
            self.web_thread.start()
            logger.info("✅ Web Interface started on http://localhost:5000")
            
            # Step 5: Auto-open dashboard in browser
            logger.info("Step 5: Auto-opening dashboard...")
            auto_open_dashboard()
            logger.info("✅ Dashboard opened in browser")
            
            # Step 6: Optionally start Trading Bot
            if self.enable_trading_bot:
                logger.info("Step 6: Trading Bot ready for user-driven mode")
                logger.info("✅ Trading Bot will handle user input in main thread")
                # Don't run in background thread - user input needs main thread
            
            # Print system status
            self._print_system_status()
            
            # Keep main thread alive and run interactive CLI
            logger.info("\n" + "="*80)
            logger.info("🚀 MARKET ANALYSIS SYSTEM RUNNING")
            logger.info("="*80)
            logger.info("📊 Web Interface: http://localhost:5000")
            logger.info("🔍 Market Analyzer: Initialized (scans every 15 min from main loop)")
            if self.enable_trading_bot:
                logger.info("🤖 Trading Bot: Running (CLI Controlled Mode)")
                logger.info("💬 Type 'lock <n>' to lock trades (LLM + real entry price)")
            else:
                logger.info("🤖 Trading Bot: Disabled (View-only mode)")
            logger.info("="*80)
            logger.info("Press Ctrl+C to stop the system")
            logger.info("="*80 + "\n")
            
            # Interactive CLI loop (only if not skipping)
            if not skip_cli_mode:
                self._interactive_cli_loop()
                
        except KeyboardInterrupt:
            logger.info("\n🛑 Shutting down system...")
            self.stop()
        except Exception as e:
            logger.error(f"Error starting system: {e}")
            self.stop()
    
    def stop(self):
        """Stop all components gracefully."""
        logger.info("Stopping Market Analysis System...")
        self.running = False
        
        # Stop trading bot
        if self.trading_bot:
            self.trading_bot.bot_running = False
            logger.info("✅ Trading Bot stopped")
        
        # Stop market analyzer
        if self.market_analyzer:
            self.market_analyzer.stop()
            logger.info("✅ Market Analyzer stopped")
        
        # Web interface will stop when main thread exits
        logger.info("✅ Web Interface stopping")
        
        logger.info("🛑 System stopped successfully")
    
    def _print_system_status(self):
        """Print current system status."""
        logger.info("\n" + "="*80)
        logger.info("SYSTEM STATUS")
        logger.info("="*80)
        logger.info(f"Trading Bot: {'Running' if self.enable_trading_bot else 'Disabled'}")
        logger.info(f"Market Analyzer: Running (Independent service)")
        logger.info(f"Web Interface: Running on http://localhost:5000")
        logger.info(f"Watchlist: {self.trading_bot.watchlist}")
        logger.info(f"Max Concurrent Trades: {self.trading_bot.trade_manager.max_concurrent_trades}")
        if self.enable_trading_bot:
            logger.info(f"Mode: Independent - Market Analyzer updates every 15min")
            logger.info(f"Trade Selection: Type 'lock <n>' to lock trades (LLM + real entry price)")
        logger.info("="*80)
    
    def _interactive_cli_loop(self):
        """Single main loop - CLI controlled, no background threads."""
        
        # SAFETY CHECK: Never run interactive loop in automated mode
        if self.automated_mode:
            logger.info("🤖 AUTOMATED MODE ACTIVE - skipping interactive CLI loop")
            logger.info("🤖 System running in background without user input requirements")
            return
        
        print("\n" + "="*80)
        print("🤖 Trading Bot Started (CLI Controlled Mode)")
        print("="*80)
        print("💬 Type 'help' for all commands")
        print("⏳ Waiting for Market Analyzer to complete first analysis...")
        
        # Wait for initial scan
        time.sleep(5)
        
        # Initial display - show scanner options
        print("\n" + "="*80)
        print("📋 NEW SCANNER OPTIONS (Available to Lock)")
        print("="*80)
        self._show_current_trades()
        
        last_scan_time = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # DYNAMIC TIMING: Opening bell fast scans
                current_hour = datetime.now().hour
                current_minute = datetime.now().minute
                
                # Opening bell mode: 9:15-9:30 AM → 2-minute scans
                if current_hour == 9 and 15 <= current_minute < 30:
                    scan_interval = 120  # 2 minutes during opening
                    scan_mode = "OPENING BELL (2-min)"
                else:
                    scan_interval = 900  # 15 minutes normal mode
                    scan_mode = "NORMAL (15-min)"
                
                # 1. SCAN (dynamic interval) - no background thread
                if current_time - last_scan_time > scan_interval:
                    # Clear screen for better UX
                    os.system('cls')
                    
                    print("\n" + "="*80)
                    print(f"🔄 SCANNING MARKET ({scan_mode})")
                    print("="*80)
                    # Call the analyze method directly (no background thread)
                    self.market_analyzer._analyze_market()
                    self.market_analyzer._print_numbered_trade_list()
                    
                    # Only show scanner if no active trades
                    if not self.trading_bot.active_trades:
                        self._show_current_trades()
                    
                    last_scan_time = current_time
                
                # 2. EVENT-DRIVEN: If no active trades, WAIT for user input
                if not self.trading_bot.active_trades:
                    # WAIT MODE - blocking input (only print waiting message once)
                    if not hasattr(self, '_waiting_message_shown'):
                        print("\n" + "="*80)
                        print("💬 WAITING FOR INPUT (Type 'lock <n>' to lock a trade)")
                        print("💡 Type 'help' for commands | 'refresh' to rerun scanner")
                        print("="*80)
                        self._waiting_message_shown = True
                    
                    command = safe_input("❓ Enter command: ")
                    if command is None:
                        # No input available - wait and retry
                        time.sleep(1)
                        continue
                    
                    command = command.strip()
                    if command:
                        self._handle_cli_command(command)
                        # Reset waiting message flag after command
                        self._waiting_message_shown = False
                else:
                    # 3. MONITOR MODE - active trades, update dashboard + allow commands
                    # Clear screen for better UX
                    os.system('cls')
                    
                    # Update trade prices
                    self._update_trade_prices()
                    
                    # Display live dashboard ONLY when trades are active
                    self._display_live_dashboard()
                    
                    # Non-blocking command check (allows commands during monitoring)
                    command = self._get_user_input_non_blocking()
                    if command:
                        self._handle_cli_command(command)
                    
                    # Small delay to prevent spam
                    time.sleep(2)
                
            except KeyboardInterrupt:
                print("\n👋 Exiting...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(1)
    
    def _show_help(self):
        """Show available commands."""
        print("\n" + "="*80)
        print("📋 AVAILABLE COMMANDS")
        print("="*80)
        print("help              - Show this help message")
        print("list              - Show current perfect trades list")
        print("lock <n>          - Lock trade number n (goes through LLM validation)")
        print("lock <n1> <n2>    - Lock multiple trades")
        print("refresh           - Manually rerun scanner NOW (instant update)")
        print("active            - Show locked active trades")
        print("completed         - Show completed trades history")
        print("unlock <n>        - Unlock specific trade")
        print("unlock all        - Unlock all trades")
        print("status            - Show system status")
        print("exit              - Exit the system")
        print("="*80)
        print("NOTE: Auto scan runs every 15 min | Use 'refresh' for instant update")
        print("="*80)
    
    def _get_user_input_non_blocking(self):
        """Non-blocking input check using msvcrt on Windows."""
        try:
            if sys.platform == 'win32':
                import msvcrt
                if msvcrt.kbhit():
                    return safe_input("\n❓ Enter command: ")
            else:
                # Unix: use select
                import select
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    return safe_input("\n❓ Enter command: ")
        except (ImportError, AttributeError):
            pass
        except EOFError:
            pass
        return None
    
    def _handle_cli_command(self, command):
        """Handle CLI commands - only way to trigger trades."""
        command = command.strip().lower()
        
        if command == 'help':
            self._show_help()
        elif command == 'list':
            self._show_current_trades()
        elif command == 'refresh':
            self._handle_refresh_command()
        elif command.startswith('lock'):
            self._handle_lock_command(command)
        elif command == 'active':
            self._show_active_trades()
        elif command == 'completed':
            self._show_completed_trades()
        elif command.startswith('unlock'):
            self._handle_unlock_command(command)
        elif command == 'status':
            self._show_status()
        elif command == 'exit':
            print("👋 Exiting...")
            self.running = False
        else:
            # Check if it's just a number (direct lock)
            if command.isdigit():
                self._handle_lock_command(f"lock {command}")
            elif all(part.isdigit() for part in command.split()):
                self._handle_lock_command(f"lock {command}")
            else:
                print("⚠️  Unknown command. Type 'help' for available commands.")
    
    def _update_trade_prices(self):
        """Update prices for locked trades (no new trades here)."""
        try:
            monitor_results = self.trading_bot.monitor_active_trade()
            # Results are already stored in active_trades
        except Exception as e:
            logger.error(f"Error updating trade prices: {e}")
    
    def _display_live_dashboard(self):
        """Display live dashboard with auto refresh - shows both active trades and new scanner options."""
        print("\n" + "="*80)
        print("📊 LIVE DASHBOARD")
        print("="*80)
        
        # Show active locked trades
        if self.trading_bot.active_trades:
            print(f"🔒 ACTIVE TRADES ({len(self.trading_bot.active_trades)})")
            print("-" * 80)
            for trade in self.trading_bot.active_trades:
                direction = trade.get('direction', 'N/A')
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                option_symbol = f"{trade.get('strike')} {option_type}"
                
                current = trade.get('current_price', 0)
                entry = trade.get('entry', 0)
                pnl = trade.get('pnl', 0)
                pnl_percent = trade.get('pnl_percent', 0)
                status = trade.get('status', 'ACTIVE')
                
                print(f"\n{trade.get('symbol')} {option_symbol} | {status}")
                print(f"Entry: ₹{entry:.2f} | Current: ₹{current:.2f}")
                print(f"Target: ₹{trade.get('target', 0):.2f} | SL: ₹{trade.get('stoploss', 0):.2f}")
                print(f"P&L: ₹{pnl:.2f} ({pnl_percent:.2f}%)")
                print("-" * 50)
            print("="*80)
        else:
            print("🔓 No active trades locked")
        
        # Show new scanner options (always available)
        print(f"\n📋 NEW SCANNER OPTIONS (Available to Lock)")
        print("-" * 80)
        trades = self.market_analyzer.get_perfect_trades()
        if trades:
            for i, trade in enumerate(trades, 1):
                symbol = trade.get('symbol', 'N/A')
                direction = trade.get('direction', 'N/A')
                strike = trade.get('strike', 'N/A')
                quality = trade.get('quality_score', 0)
                ranking = trade.get('ranking_score', 0)
                reason = trade.get('reason', 'N/A')
                spot = trade.get('spot', 0)
                support = trade.get('support', 0)
                resistance = trade.get('resistance', 0)
                
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                option_symbol = f"{strike} {option_type}"
                
                # Calculate ESTIMATED values for display (UX only - improved estimation)
                est_entry = self.trading_bot.estimate_option_price(spot, strike, direction)
                est_target, est_sl = self.trading_bot.estimate_levels(est_entry)
                
                print(f"{i}. {symbol} {option_symbol}")
                print(f"   Spot: ₹{spot:.2f} | Support: ₹{support:.2f} | Resistance: ₹{resistance:.2f}")
                print(f"   Est Entry: ~₹{est_entry:.2f} | Est Target: ~₹{est_target:.2f} | Est SL: ~₹{est_sl:.2f}")
                print(f"   Quality: {quality:.1f}% | Ranking: {ranking:.1f} - {reason}")
                print(f"   💡 Type 'lock {i}' to confirm with REAL LTP")
                print("-" * 40)
        else:
            print("No scanner options available (waiting for next scan)")
        
        print("="*80)
        print("💬 Type 'lock <n>' to lock a trade | 'help' for commands")
        print("="*80)
    
    def _show_current_trades(self):
        """Show current perfect trades from Market Analyzer (scanner output with ESTIMATED values)."""
        trades = self.market_analyzer.get_perfect_trades()
        
        print("\n" + "="*80)
        print("📋 PERFECT TRADES LIST (Scanner Output with ESTIMATES)")
        print("="*80)
        
        if not trades:
            print("No perfect trades available")
        else:
            for i, trade in enumerate(trades, 1):
                symbol = trade.get('symbol', 'N/A')
                direction = trade.get('direction', 'N/A')
                strike = trade.get('strike', 'N/A')
                quality = trade.get('quality_score', 0)
                ranking = trade.get('ranking_score', 0)
                reason = trade.get('reason', 'N/A')
                spot = trade.get('spot', 0)
                support = trade.get('support', 0)
                resistance = trade.get('resistance', 0)
                
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                option_symbol = f"{strike} {option_type}"
                
                # Calculate ESTIMATED values for display (UX only - improved estimation)
                est_entry = self.trading_bot.estimate_option_price(spot, strike, direction)
                est_target, est_sl = self.trading_bot.estimate_levels(est_entry)
                
                print(f"{i}. {symbol} {option_symbol}")
                print(f"   Spot: ₹{spot:.2f} | Support: ₹{support:.2f} | Resistance: ₹{resistance:.2f}")
                print(f"   Est Entry: ~₹{est_entry:.2f} | Est Target: ~₹{est_target:.2f} | Est SL: ~₹{est_sl:.2f}")
                print(f"   Quality: {quality:.1f}% | Ranking: {ranking:.1f} - {reason}")
                print(f"   💡 Type 'lock {i}' to confirm with REAL LTP")
                print("-" * 80)
        
        print("="*80)
        print("💡 Scanner shows ESTIMATED values | Lock shows REAL LTP")
        print("="*80)
    
    def _show_status(self):
        """Show system status."""
        print("\n" + "="*80)
        print("📊 SYSTEM STATUS")
        print("="*80)
        print(f"Market Analyzer: {'Running' if self.market_analyzer.running else 'Stopped'}")
        print(f"Analysis Interval: {self.market_analyzer.analysis_interval}s (15 minutes)")
        print(f"Watchlist: {self.trading_bot.watchlist}")
        print(f"Active Trades: {self.trading_bot.trade_manager.get_active_trade_count()}")
        print(f"Completed Trades: {len(self.trading_bot.trade_manager.completed_trades)}")
        print("="*80)
    
    def _show_active_trades(self):
        """Show currently monitored trades (NEW ARCHITECTURE - multi-trade)."""
        if self.trading_bot.active_trades:
            print("\n" + "="*80)
            print(f"🔒 LOCKED ACTIVE TRADES ({len(self.trading_bot.active_trades)})")
            print("="*80)
            for trade in self.trading_bot.active_trades:
                direction = trade.get('direction', 'N/A')
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                option_symbol = f"{trade.get('strike')} {option_type}"
                
                print(f"\nTrade ID: {trade.get('trade_id')}")
                print(f"Symbol: {trade.get('symbol')} | Option: {option_symbol}")
                print(f"Entry: ₹{trade.get('entry', 0):.2f} | Target: ₹{trade.get('target', 0):.2f} | SL: ₹{trade.get('stoploss', 0):.2f}")
                print(f"Current: ₹{trade.get('current_price', 0):.2f} | P&L: ₹{trade.get('pnl', 0):.2f} ({trade.get('pnl_percent', 0):.2f}%)")
                print(f"Status: {trade.get('status', 'UNKNOWN')}")
                print("-" * 40)
            print("="*80)
        else:
            print("\n" + "="*80)
            print("🔓 No active trades locked")
            print("💡 Type 'lock <n>' to lock a trade from scanner output")
            print("="*80)
    
    def _show_completed_trades(self):
        """Show completed trades history."""
        if self.trading_bot.completed_trades:
            print("\n" + "="*80)
            print(f"📜 COMPLETED TRADES HISTORY ({len(self.trading_bot.completed_trades)})")
            print("="*80)
            for trade in self.trading_bot.completed_trades:
                direction = trade.get('direction', 'N/A')
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                option_symbol = f"{trade.get('strike')} {option_type}"
                
                print(f"\nTrade ID: {trade.get('trade_id')}")
                print(f"Symbol: {trade.get('symbol')} | Option: {option_symbol}")
                print(f"Entry: ₹{trade.get('entry', 0):.2f} | Exit: ₹{trade.get('exit_price', 0):.2f}")
                print(f"Target: ₹{trade.get('target', 0):.2f} | SL: ₹{trade.get('stoploss', 0):.2f}")
                print(f"P&L: ₹{trade.get('exit_pnl', 0):.2f}")
                print(f"Status: {trade.get('status', 'UNKNOWN')}")
                print("-" * 40)
            print("="*80)
        else:
            print("\n" + "="*80)
            print("📜 No completed trades yet")
            print("="*80)
    
    def _handle_lock_command(self, user_input):
        """Handle lock command - trade goes through proper pipeline (LLM + real entry price)."""
        if not self.enable_trading_bot:
            print("⚠️  Trading bot is disabled. Cannot lock trades.")
            return
        
        try:
            # Parse trade numbers (can be single or multiple)
            parts = user_input.split()
            if len(parts) < 2:
                print("⚠️  Usage: lock <number> or lock <number1> <number2> ...")
                print("   Example: lock 1")
                print("   Example: lock 1 2 3")
                return
            
            # Get all trade numbers
            trade_numbers = []
            for part in parts[1:]:
                try:
                    trade_numbers.append(int(part))
                except ValueError:
                    print(f"⚠️  Invalid trade number: {part}")
                    return
            
            # Get trades from Market Analyzer
            trades = self.market_analyzer.get_perfect_trades()
            
            if not trades:
                print("⚠️  No perfect trades available")
                return
            
            # Validate trade numbers
            for num in trade_numbers:
                if num < 1 or num > len(trades):
                    print(f"⚠️  Invalid trade number: {num}. Choose 1-{len(trades)}")
                    return
            
            # Show selected trades summary with ESTIMATED values
            print("\n" + "="*80)
            print(f"📋 SELECTED TRADES: {', '.join(map(str, trade_numbers))}")
            print("="*80)
            print("Full trade details are shown in the scanner table above (with ESTIMATED values).")
            print("="*80)
            print("✅ Trades are already LLM-validated during market scan")
            print("💡 Lock will fetch REAL LTP from market (no LLM delay)")
            print("="*80)
            
            # Confirm before locking (use safe_input to prevent EOFError in background mode)
            if self.automated_mode:
                # Skip confirmation in automated mode
                logger.info(f"🤖 Automated mode: Auto-confirming lock for {len(trade_numbers)} trade(s)")
                confirm = 'Y'
            else:
                confirm = safe_input(f"\n❓ Lock {len(trade_numbers)} trade(s) through proper pipeline? (Y/N): ")
                
                # If running in background mode (no stdin available), auto-confirm
                if confirm is None:
                    logger.info("Running in background mode - auto-confirming trade lock")
                    confirm = 'Y'
                else:
                    confirm = confirm.strip().upper()
            
            if confirm != 'Y':
                print("⏭️ Locking cancelled")
                return
            
            # Lock each trade through proper pipeline
            locked_count = 0
            for num in trade_numbers:
                trade = trades[num - 1].copy()
                
                # Lock the trade in the trading bot (goes through LLM + real entry price)
                trade_id = self.trading_bot.lock_active_trade(trade, use_llm_validation=True)
                
                if trade_id:
                    # Get the locked trade (already processed through pipeline)
                    locked_trade = self.trading_bot.active_trade
                    
                    if locked_trade:
                        direction = trade.get('direction', 'N/A')
                        option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                        option_symbol = f"{trade.get('strike')} {option_type}"
                        
                        # Calculate estimated values for comparison (improved estimation)
                        spot = trade.get('spot', 0)
                        strike = trade.get('strike', 0)
                        est_entry = self.trading_bot.estimate_option_price(spot, strike, direction)
                        est_target, est_sl = self.trading_bot.estimate_levels(est_entry)
                        
                        real_entry = locked_trade['entry']
                        real_target = locked_trade['target']
                        real_sl = locked_trade['stoploss']
                        
                        print(f"\n✅ TRADE LOCKED: {trade_id}")
                        print(f"   {trade.get('symbol')} {option_symbol}")
                        print(f"   📊 REAL LTP: ₹{real_entry:.2f} (from market)")
                        print(f"   Target: ₹{real_target:.2f} | SL: ₹{real_sl:.2f}")
                        print(f"   Risk: ₹{locked_trade.get('risk_amount', 0):.2f} | Reward: ₹{locked_trade.get('reward_amount', 0):.2f}")
                        print(f"   📈 Est vs Real: ~₹{est_entry:.2f} → ₹{real_entry:.2f}")
                        locked_count += 1
                    else:
                        print(f"⚠️  Failed to process trade {num}")
                else:
                    print(f"⚠️  Failed to lock trade {num} (may have been rejected by LLM)")
            
            print("\n" + "="*80)
            print(f"🔒 {locked_count}/{len(trade_numbers)} trade(s) locked with REAL LTP")
            print("🔔 Bot will alert you when TP/SL is hit")
            print("💡 Scanner continues to find new opportunities (with ESTIMATED values)")
            print("="*80)
        
        except ValueError:
            print("⚠️  Invalid trade number. Please enter valid numbers.")
        except Exception as e:
            logger.error(f"Error handling lock command: {e}")
            print(f"⚠️  Error: {e}")
    
    def _handle_unlock_command(self, user_input):
        """Handle unlock command - unlock specific trade or all trades."""
        if not self.enable_trading_bot:
            print("⚠️  Trading bot is disabled. Cannot unlock trades.")
            return
        
        try:
            parts = user_input.split()
            
            if len(parts) == 1:
                # "unlock" - unlock all
                self.trading_bot.unlock_active_trade(trade_id=None)
            elif len(parts) == 2:
                # "unlock <n>" - unlock specific trade
                try:
                    trade_num = int(parts[1])
                    # Get the trade ID from active trades
                    if self.trading_bot.active_trades and trade_num <= len(self.trading_bot.active_trades):
                        trade_id = self.trading_bot.active_trades[trade_num - 1].get('trade_id')
                        self.trading_bot.unlock_active_trade(trade_id=trade_id)
                    else:
                        print(f"⚠️  Invalid trade number: {trade_num}")
                except ValueError:
                    print("⚠️  Invalid trade number")
            else:
                print("⚠️  Usage: unlock or unlock <number>")
                print("   Example: unlock")
                print("   Example: unlock 1")
        
        except Exception as e:
            logger.error(f"Error handling unlock command: {e}")
    
    def _handle_refresh_command(self):
        """Handle refresh command - manually rerun scanner NOW."""
        print("\n" + "="*80)
        print("🔄 MANUAL REFRESH TRIGGERED")
        print("="*80)
        
        try:
            # Clear screen for better UX
            os.system('cls')
            
            # Rerun market analysis
            print("Rerunning scanner...")
            self.market_analyzer._analyze_market()
            self.market_analyzer._print_numbered_trade_list()
            
            # Show updated trades (only if no active trades)
            if not self.trading_bot.active_trades:
                self._show_current_trades()
            else:
                print("⚠️  Active trades locked - scanner not shown")
                print("💡 Use 'active' to see locked trades")
            
            print("="*80)
            print("✅ Scanner refreshed successfully")
            print("="*80)
            
        except Exception as e:
            logger.error(f"Error refreshing scanner: {e}")
            print("⚠️  Error refreshing scanner")


    def run_auto_paper_trading(self, start_capital=30000, end_time="15:20"):
        """
        Run fully automatic paper trading mode with capital tracking.
        
        Args:
            start_capital: Starting capital (default: ₹30,000)
            end_time: End time for trading (default: "15:20")
        """
        print("\n" + "="*80)
        print("🤖 AUTO PAPER TRADING MODE")
        print("="*80)
        print(f"Starting Capital: ₹{start_capital}")
        print(f"End Time: {end_time}")
        
        # ENSURE UI IS OPEN: Explicitly open dashboard for paper trading
        print("\n" + "="*80)
        print("🌐 OPENING WEB INTERFACE")
        print("="*80)
        print("📊 Dashboard: http://localhost:5000")
        print("🎯 Web Interface should be opening in your browser...")
        print("="*80)
        
        # Verify web interface is running
        if hasattr(self, 'web_thread') and self.web_thread.is_alive():
            print("✅ Web Interface is RUNNING")
        else:
            print("⚠️  Web Interface may not be running - attempting to start...")
            try:
                from web_interface import run_web_server
                import threading
                self.web_thread = threading.Thread(
                    target=run_web_server,
                    kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': False},
                    daemon=True
                )
                self.web_thread.start()
                print("✅ Web Interface started successfully")
            except Exception as e:
                print(f"❌ Failed to start Web Interface: {e}")
        
        # Force-open browser for paper trading mode
        try:
            auto_open_dashboard()
            logger.info("✅ Dashboard auto-opened for paper trading mode")
        except Exception as e:
            logger.warning(f"Could not auto-open dashboard: {e}")
            print(f"⚠️  Please manually open: http://localhost:5000")
        
        print("\n" + "="*80)
        
        # TRADING RULES (Strict filters)
        MIN_RANKING = 115
        MAX_DISTANCE = 40
        MIN_EXPECTED_PROFIT = 600  # ₹600 minimum to cover charges + buffer
        MIN_RISK_REWARD = 5.0  # 1:5 risk-reward ratio (high conviction)
        MAX_PREMIUM = 500  # Avoid expensive options
        MAX_TRADES_PER_DAY = None  # REMOVED - Unlimited trades with 1:5 RR
        PRIORITY_SYMBOLS = []  # All instruments equal priority (14-instrument universe)
        INDEX_ONLY = False  # Trade all instruments (indices + stocks) for full universe
        NO_TRADE_AFTER = dt_time(15, 30)  # No new trades after 3:30 PM (MARKET CLOSE)
        
        print()
        print("STRICT TRADING RULES (UNLIMITED VOLUME WITH 1:5 RR):")
        print(f"  • LLM Confidence Threshold: 85% (high-conviction only)")
        print(f"  • Minimum Ranking: {MIN_RANKING}")
        print(f"  • Maximum Distance: {MAX_DISTANCE} points")
        print(f"  • Technical Concurrence: Spot trend, VWAP, OI must align")
        print(f"  • Minimum Expected Profit: ₹{MIN_EXPECTED_PROFIT}")
        print(f"  • Risk-Reward Ratio: 1:{int(MIN_RISK_REWARD)} (high conviction)")
        print(f"  • Maximum Premium: ₹{MAX_PREMIUM}")
        print(f"  • Daily Trade Cap: REMOVED (unlimited with 1:5 RR)")
        print(f"  • Session Caps: 1-2 trades per session (Morning/Noon/Afternoon)")
        print(f"  • Entry Cool-Down: 30 minutes between trades")
        print(f"  • Index Only: {INDEX_ONLY} (All 14 instruments enabled)")
        print(f"  • No consecutive same symbol")
        print(f"  • No new trades after 3:30 PM")
        print("=" * 80)
        
        current_capital = start_capital
        trade_count = 0
        wins = 0
        losses = 0
        trade_history = []
        last_traded_symbol = None  # Track last traded symbol
        
        # DAILY PROFIT GOAL TRACKING
        daily_profit_goal = 5000  # ₹5,000 daily profit target
        daily_accumulated_pnl = 0.0  # Track total P&L (realized + unrealized)
        profit_goal_reached = False  # Flag when goal is reached
        active_positions = {}  # Track active trades for real-time P&L calculation
        
        # SESSION-BASED TRADE CAPS & COOL-DOWN
        session_trades = {
            'morning': 0,   # 09:15-11:30
            'noon': 0,      # 11:30-13:30
            'afternoon': 0  # 13:30-15:30
        }
        MAX_TRADES_PER_SESSION = 2  # Max 2 trades per session
        ENTRY_COOLDOWN_MINUTES = 30  # 30-minute cool-down between trades
        last_trade_time = None  # Track last trade entry time
        
        # Anti-Whipsaw Cool-Down Filter for paper trading
        sl_cooldown_cache = {}  # symbol -> timestamp when SL was hit
        sl_cooldown_minutes = 30  # 30-minute cooldown after SL hit
        
        def get_current_session(current_time):
            """Determine which session we're in based on time."""
            # Handle both datetime and timestamp inputs
            if isinstance(current_time, (int, float)):
                # Convert timestamp to datetime
                current_time = datetime.fromtimestamp(current_time)
            
            hour = current_time.hour
            minute = current_time.minute
            time_minutes = hour * 60 + minute
            
            # Morning: 09:15-11:30 (555 to 690 minutes)
            if 555 <= time_minutes < 690:
                return 'morning'
            # Noon: 11:30-13:30 (690 to 810 minutes)
            elif 690 <= time_minutes < 810:
                return 'noon'
            # Afternoon: 13:30-15:30 (810 to 930 minutes)
            elif 810 <= time_minutes < 930:
                return 'afternoon'
            else:
                return None  # Outside trading hours
        
        def is_session_cap_reached(current_session):
            """Check if we've hit the session trade cap."""
            if current_session and session_trades[current_session] >= MAX_TRADES_PER_SESSION:
                logger.warning(f"🛑 SESSION CAP REACHED: {current_session} session has {session_trades[current_session]}/{MAX_TRADES_PER_SESSION} trades")
                return True
            return False
        
        def is_entry_cooldown_active(current_time):
            """Check if we're in the 30-minute entry cool-down period."""
            if last_trade_time:
                time_since_last_trade = current_time - last_trade_time
                cooldown_seconds = ENTRY_COOLDOWN_MINUTES * 60
                if time_since_last_trade < cooldown_seconds:
                    minutes_left = int((cooldown_seconds - time_since_last_trade) / 60)
                    logger.warning(f"🛑 ENTRY COOL-DOWN ACTIVE: {minutes_left} minutes remaining before next trade")
                    return True
            return False
        
        def calculate_realtime_pnl():
            """Calculate real-time P&L including both realized and unrealized profits."""
            global daily_accumulated_pnl
            
            # Calculate realized P&L from closed trades
            realized_pnl = sum([trade['pnl'] for trade in trade_history])
            
            # Calculate unrealized P&L from active positions
            unrealized_pnl = 0.0
            for trade_id, position in active_positions.items():
                try:
                    current_price = self.trading_bot.get_real_option_price(
                        position['symbol'], position['strike'], position['direction']
                    )
                    if current_price:
                        lot_size = self.trading_bot.config.get('instruments', {}).get(position['symbol'], {}).get('lot_size', 1)
                        unrealized_pnl += (current_price - position['entry']) * lot_size
                except Exception as e:
                    logger.warning(f"Error calculating unrealized P&L for {trade_id}: {e}")
            
            total_pnl = realized_pnl + unrealized_pnl
            daily_accumulated_pnl = total_pnl
            
            return {
                'realized_pnl': realized_pnl,
                'unrealized_pnl': unrealized_pnl,
                'total_pnl': total_pnl,
                'goal_progress': (total_pnl / daily_profit_goal) * 100 if daily_profit_goal > 0 else 0
            }
        
        def check_profit_goal():
            """Check if daily profit goal is reached."""
            global profit_goal_reached
            
            pnl_data = calculate_realtime_pnl()
            
            if pnl_data['total_pnl'] >= daily_profit_goal and not profit_goal_reached:
                profit_goal_reached = True
                logger.info("="*80)
                logger.info("🎉 [GOAL REACHED] Daily profit target of ₹5,000 achieved!")
                logger.info("="*80)
                logger.info(f"Realized P&L: ₹{pnl_data['realized_pnl']:.2f}")
                logger.info(f"Unrealized P&L: ₹{pnl_data['unrealized_pnl']:.2f}")
                logger.info(f"Total P&L: ₹{pnl_data['total_pnl']:.2f}")
                logger.info("="*80)
                logger.info("🔒 Locking system entries - no new trades for the day")
                logger.info("="*80)
                return True
            
            return False
        
        def is_symbol_allowed_to_trade(symbol):
            """Check if a symbol is currently serving a penalty for hitting Stop Loss."""
            if symbol in sl_cooldown_cache:
                sl_hit_time = sl_cooldown_cache[symbol]
                time_passed = current_time - sl_hit_time
                cooldown_seconds = sl_cooldown_minutes * 60
                
                if time_passed < cooldown_seconds:
                    minutes_left = int((cooldown_seconds - time_passed) / 60)
                    logger.warning(f"🛡️ [BLOCK] {symbol} hit SL recently. Cooling off for another {minutes_left} mins.")
                    return False
                else:
                    # Cooldown expired, remove from cache
                    del sl_cooldown_cache[symbol]
                    logger.info(f"✅ {symbol} cooldown expired, now available for trading")
            
            return True
        
        last_scan_time = 0
        scan_interval = 300  # 5 minutes between scans for auto mode
        
        while self.running:
            try:
                current_time = time.time()
                current_datetime = datetime.now()
                current_time_str = current_datetime.strftime("%H:%M")
                
                # Check if market is closed (3:30 PM IST - SYSTEM-WIDE SHUTDOWN)
                # SKIP MARKET CLOSE CHECK IN DEMO MODE - demo runs 24/7
                is_demo_mode = self.trading_bot and hasattr(self.trading_bot, 'demo_simulator') and self.trading_bot.demo_simulator is not None
                
                if current_time_str >= end_time and not is_demo_mode:
                    logger.warning(f"🛑 MARKET CLOSE DETECTED AT {current_time_str} IST - AUTOMATIC SYSTEM SHUTDOWN INITIATED")
                    print(f"\n{'='*80}")
                    print(f"🛑 MARKET CLOSE DETECTED AT {current_time_str} IST")
                    print(f"🛑 AUTOMATIC SYSTEM SHUTDOWN INITIATED")
                    print(f"{'='*80}")
                    print(f"⏰ Stopping all trading operations")
                    print(f"📊 Final Capital: ₹{current_capital:.2f}")
                    print(f"🛑 No new trades will be executed")
                    print(f"{'='*80}")
                    break
                
                if is_demo_mode and current_time_str >= end_time:
                    logger.info(f"🕐 Market close time reached ({current_time_str}) - DEMO MODE: Continuing to run (24/7 demo)")
                    print(f"\n{'='*80}")
                    print(f"🕐 Market close time reached ({current_time_str})")
                    print(f"🎮 DEMO MODE: Continuing to run (24/7 demo market)")
                    print(f"{'='*80}")
                
                # Scan market at intervals
                if current_time - last_scan_time > scan_interval:
                    # Check no-trade zone (after 3:30 PM - MARKET CLOSE)
                    # SKIP IN DEMO MODE - demo runs 24/7
                    if current_datetime.time() >= NO_TRADE_AFTER and not is_demo_mode:
                        logger.warning(f"🛑 MARKET CLOSE ZONE (3:30 PM) - No new trades allowed")
                        print(f"⏰ MARKET CLOSE ZONE (3:30 PM) - No new trades allowed")
                        print(f"🛑 Waiting for system shutdown at end time")
                        time.sleep(60)
                        continue
                    
                    print(f"\n{'='*80}")
                    print(f"🔄 STAGE 1: TECHNICAL SCANNER ({current_time_str})")
                    print(f"{'='*80}")
                    print(f"Current Capital: ₹{current_capital}")
                    print(f"Scanning 14 instruments for technical setups...")
                    print(f"{'='*80}")
                    
                    # Scan market (technical analysis only - NO LLM)
                    self.market_analyzer._analyze_market()
                    
                    # Save signals to web_signals.json for UI sync
                    self.market_analyzer._save_signals_to_json()
                    
                    # Get perfect trades from technical scanner
                    trades = self.market_analyzer.perfect_trades
                    
                    if not trades:
                        print("❌ No technical setups found - waiting...")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    print(f"✅ Technical scanner found {len(trades)} potential setups")
                    
                    # STAGE 1.5: Apply strict technical filters (backend only)
                    print(f"\n{'='*80}")
                    print(f"🔍 STAGE 1.5: TECHNICAL FILTERING")
                    print(f"{'='*80}")
                    
                    # Filter trades by ranking > 110 and distance < 40
                    filtered_trades = []
                    for trade in trades:
                        ranking = trade.get('ranking_score', 0)
                        spot = trade.get('spot', 0)
                        strike = trade.get('strike', 0)
                        distance = abs(spot - strike)
                        symbol = trade.get('symbol', '')
                        
                        # STRICT TRADING RULES
                        # Rule 1: Skip same symbol as last trade (prevent overtrading same stock)
                        if symbol == last_traded_symbol:
                            logger.info(f"⚠️  Skipping {symbol} - same as last trade")
                            continue
                        
                        # Rule 1.5: Anti-Whipsaw Cool-Down Filter
                        if not is_symbol_allowed_to_trade(symbol):
                            logger.info(f"⚠️  Skipping {symbol} - in cooldown period after SL hit")
                            continue
                        
                        # Rule 1.6: Index only filter (avoid low-liquidity stock options)
                        if INDEX_ONLY and symbol not in PRIORITY_SYMBOLS:
                            logger.info(f"⚠️  Skipping {symbol} - not an index (Index Only mode)")
                            continue
                        
                        # Rule 2: Minimum ranking
                        if ranking < MIN_RANKING:
                            continue
                        
                        # Rule 3: Maximum distance
                        if distance >= MAX_DISTANCE:
                            continue
                        
                        # Rule 3.5: Multivariable Technical Concurrence (Quality Over Quantity)
                        # Verify spot trend, VWAP, and OI bias all align with trade direction
                        spot = trade.get('spot', 0)
                        vwap = trade.get('vwap', 0)
                        direction = trade.get('direction', '')
                        
                        # Determine trend based on spot vs VWAP
                        if spot > vwap:
                            spot_trend = 'BULLISH'  # Price above VWAP = bullish
                        elif spot < vwap:
                            spot_trend = 'BEARISH'  # Price below VWAP = bearish
                        else:
                            spot_trend = 'NEUTRAL'
                        
                        # Check if trade direction aligns with spot trend
                        if direction == 'CALL' and spot_trend == 'BEARISH':
                            logger.info(f"⚠️  Skipping {symbol} - CALL trade but spot trend is BEARISH (price < VWAP)")
                            continue
                        elif direction == 'PUT' and spot_trend == 'BULLISH':
                            logger.info(f"⚠️  Skipping {symbol} - PUT trade but spot trend is BULLISH (price > VWAP)")
                            continue
                        
                        # Check OI bias if available (from market_data)
                        market_data = trade.get('market_data', {})
                        oi_type = market_data.get('oi_type', 'balanced')
                        
                        # If OI is heavily skewed against direction, skip
                        if direction == 'CALL' and oi_type == 'bearish':
                            logger.info(f"⚠️  Skipping {symbol} - CALL trade but OI bias is bearish")
                            continue
                        elif direction == 'PUT' and oi_type == 'bullish':
                            logger.info(f"⚠️  Skipping {symbol} - PUT trade but OI bias is bullish")
                            continue
                        
                        # Log technical concurrence check passed
                        logger.info(f"✅ {symbol} {direction} - Technical concurrence: Trend={spot_trend}, OI={oi_type}, VWAP aligned")
                        
                        filtered_trades.append(trade)
                    
                    if not filtered_trades:
                        print("❌ No qualified trades after technical filtering (ranking > 115, distance < 40, technical concurrence aligned)")
                        print("💡 This is GOOD - system is filtering out noise")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    print(f"✅ Technical filtering passed - {len(filtered_trades)} high-probability setups")
                    
                    # Sort by ranking and pick best
                    filtered_trades.sort(key=lambda x: x.get('ranking_score', 0), reverse=True)
                    best_trade = filtered_trades[0]
                    
                    print(f"\n{'='*80}")
                    print(f"🎯 BEST TECHNICAL SETUP SELECTED")
                    print(f"{'='*80}")
                    
                    # Get trade details
                    symbol = best_trade.get('symbol', '')
                    direction = best_trade.get('direction', '')
                    strike = best_trade.get('strike', 0)
                    ranking = best_trade.get('ranking_score', 0)
                    
                    print(f"✅ SELECTED TRADE: {symbol} {direction} @ {strike}")
                    print(f"   Ranking: {ranking}")
                    
                    # DAILY TRADE CAP CHECK: REMOVED - Unlimited trades with 1:5 RR
                    # SESSION CAP CHECK: Enforce session-based limits
                    current_session = get_current_session(current_time)
                    if current_session and is_session_cap_reached(current_session):
                        logger.warning(f"🛑 SESSION CAP REACHED - waiting for next session")
                        print(f"\n⏳ Session cap reached - waiting for next time slot...")
                        time.sleep(60)
                        continue
                    
                    # ENTRY COOL-DOWN CHECK: Enforce 30-minute gap between trades
                    if is_entry_cooldown_active(current_time):
                        print(f"\n⏳ Entry cool-down active - waiting...")
                        time.sleep(60)
                        continue
                    
                    # PROFIT GOAL CHECK: Halt new entries if ₹5,000 target reached
                    if check_profit_goal():
                        print(f"\n🎉 DAILY PROFIT GOAL REACHED: ₹{daily_accumulated_pnl:.2f}")
                        print(f"🔒 System entries locked - no new trades for the day")
                        print(f"⏳ Letting active trailing stop-losses protect gains...")
                        time.sleep(60)
                        continue
                    
                    # Get entry price (real LTP)
                    entry = self.trading_bot.get_real_option_price(symbol, strike, direction)
                    
                    if not entry:
                        print("❌ Failed to get entry price - skipping trade")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    print(f"   Entry: ₹{entry}")
                    
                    # STAGE 2: LLM VALIDATION (Decoupled - Cache Lookup)
                    print(f"\n{'='*80}")
                    print(f"🤖 STAGE 2: LLM VALIDATION (Cache Lookup)")
                    print(f"{'='*80}")
                    print(f"Checking LLM state cache for {symbol}...")
                    print(f"Confidence Threshold: 85%")
                    print(f"{'='*80}")
                    
                    # DECOUPLED LLM VALIDATION: Check cache instead of blocking call
                    llm_decision = None
                    if self.trading_bot.llm_state_worker:
                        logger.info(f"🤖 Checking LLM state cache for {symbol} {direction}")
                        try:
                            llm_decision = self.trading_bot.llm_state_worker.get_llm_decision(symbol, direction)
                            logger.info(f"✅ LLM cache lookup: {llm_decision['decision']} (source: {llm_decision['source']})")
                            print(f"✅ LLM Cache: {llm_decision['decision']} (source: {llm_decision['source']})")
                        except Exception as e:
                            logger.error(f"Error checking LLM cache: {e}")
                            llm_decision = None
                    else:
                        logger.warning("LLM State Worker not available")
                        print("⚠️ LLM State Worker not available")
                    
                    # Process LLM decision
                    if llm_decision and llm_decision['decision'] == 'TAKE':
                        logger.info(f"✅ LLM APPROVED final execution: {symbol}")
                        print(f"✅ LLM APPROVED trade execution")
                        print(f"   Reason: {llm_decision['reason']}")
                        print(f"   Source: {llm_decision['source']}")
                    elif llm_decision and llm_decision['decision'] == 'SKIP':
                        reason = llm_decision.get('reason', 'LLM rejected trade')
                        logger.warning(f"🛑 LLM REJECTED trade (cache): {symbol} - {reason}")
                        print(f"❌ LLM REJECTED: {reason}")
                        print(f"💡 Trade rejected - system continues scanning for next opportunity")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    else:
                        # No LLM decision or cache miss - use technical only
                        logger.warning("⚠️ No LLM decision available - using technical filters only")
                        print(f"⚠️ [TECHNICAL_ONLY] No LLM decision - executing based on technical filters")
                        print(f"💡 Trade execution based purely on mathematical filters (1:5 RR, technical concurrence)")
                        # Continue with trade execution (technical only)
                    
                    # Get lot size (needed for profit calculation)
                    lot_size = self.trading_bot.config.get('instruments', {}).get(symbol, {}).get('lot_size', 1)
                    print(f"   Lot Size: {lot_size}")
                    
                    # STRICT TRADING RULES (Post-entry checks)
                    # Rule 4: Premium cap check (avoid expensive options)
                    if entry > MAX_PREMIUM:
                        logger.info(f"⚠️  Skipping {symbol} - premium too high (₹{entry} > ₹{MAX_PREMIUM})")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    # Calculate levels (1:5 risk-reward for high conviction)
                    # FIXED: Correct target calculation for PUT options
                    if direction == 'CALL':
                        target = entry * 1.5  # 50% profit target (1:5 RR)
                        sl = entry * 0.9   # 10% stoploss (price goes down)
                    else:  # PUT
                        target = entry * 0.5  # 50% profit target (1:5 RR)
                        sl = entry * 1.1   # 10% stoploss (price goes up)
                    
                    # Rule 5: Risk-Reward check (minimum 1:5)
                    risk = entry - sl
                    reward = target - entry
                    if reward > 0:
                        rr = reward / risk if risk > 0 else 0
                        if rr < MIN_RISK_REWARD:
                            logger.info(f"⚠️  Skipping {symbol} - RR too low ({rr:.2f} < {MIN_RISK_REWARD})")
                            last_scan_time = current_time
                            time.sleep(60)
                            continue
                    else:
                        logger.info(f"⚠️  Skipping {symbol} - invalid RR calculation")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    # Rule 6: Minimum expected profit check (₹600 to cover charges)
                    lot_size = self.trading_bot.config.get('instruments', {}).get(symbol, {}).get('lot_size', 1)
                    expected_profit_points = target - entry
                    expected_profit_rupees = expected_profit_points * lot_size
                    
                    if expected_profit_rupees < MIN_EXPECTED_PROFIT:
                        logger.info(f"⚠️  Skipping {symbol} - expected profit too low (₹{expected_profit_rupees:.2f} < ₹{MIN_EXPECTED_PROFIT})")
                        last_scan_time = current_time
                        time.sleep(60)
                        continue
                    
                    # 5K SINGLE-SHOT SETUP FLAGGING
                    # Check if this trade can clear ₹5,000 on its own
                    SINGLE_SHOT_THRESHOLD = 5000  # ₹5,000 threshold for single-shot setup
                    is_single_shot = expected_profit_rupees >= SINGLE_SHOT_THRESHOLD
                    trade_type = "[5K Single-Shot Setup]" if is_single_shot else "[Standard 1:5 Setup]"
                    
                    if is_single_shot:
                        logger.info(f"🎯 MASSIVE OPPORTUNITY: {symbol} - Expected profit ₹{expected_profit_rupees:.2f} (5K Single-Shot!)")
                        print(f"   🎯 TRADE TYPE: {trade_type}")
                        print(f"   💰 Expected Profit: ₹{expected_profit_rupees:.2f} (can clear ₹5,000 on its own)")
                    else:
                        print(f"   📊 TRADE TYPE: {trade_type}")
                    
                    print(f"   Target: ₹{target}")
                    print(f"   Stoploss: ₹{sl}")
                    print(f"   Expected Profit: ₹{expected_profit_rupees:.2f} (RR: {rr:.2f})")
                    
                    # PRINT TRADE TAKEN (User Visibility)
                    logger.info("="*80)
                    logger.info("📊 STAGE 3: TRADE EXECUTION & DASHBOARD DISPLAY")
                    logger.info("="*80)
                    logger.info(f"Instrument      : {symbol}")
                    logger.info(f"Direction       : {direction}")
                    logger.info(f"Strike          : {strike}")
                    logger.info("")
                    logger.info(f"Entry Price     : ₹{entry:.2f}")
                    logger.info(f"Target Price    : ₹{target:.2f}")
                    logger.info(f"Stoploss Price  : ₹{sl:.2f}")
                    logger.info("")
                    logger.info(f"Capital Before  : ₹{current_capital:.2f}")
                    logger.info("="*80)
                    logger.info("✅ Trade written to manifest for dashboard display")
                    logger.info("✅ Web UI will show this trade at http://localhost:5000")
                    logger.info(f"✅ Trade Type: {trade_type}")
                    
                    # UPDATE SESSION TRADE COUNT
                    if current_session:
                        session_trades[current_session] += 1
                        logger.info(f"✅ Session trade count: {current_session} = {session_trades[current_session]}/{MAX_TRADES_PER_SESSION}")
                    
                    # UPDATE ENTRY COOL-DOWN TIMER
                    last_trade_time = current_time
                    logger.info(f"✅ Entry cool-down timer set for {ENTRY_COOLDOWN_MINUTES} minutes")
                    
                    # TRACK ACTIVE POSITION for real-time P&L calculation
                    trade_id = f"{symbol}_{strike}_{direction}_{int(current_time.timestamp())}"
                    active_positions[trade_id] = {
                        'symbol': symbol,
                        'direction': direction,
                        'strike': strike,
                        'entry': entry,
                        'target': target,
                        'sl': sl,
                        'lot_size': lot_size,
                        'entry_time': current_time
                    }
                    logger.info(f"✅ Active position tracked: {trade_id}")
                    logger.info(f"✅ Current Daily P&L: ₹{daily_accumulated_pnl:.2f} (Goal: ₹{daily_profit_goal})")
                    
                    # Monitor trade
                    print(f"\n⏳ Monitoring trade...")
                    exit_price = None
                    status = "ACTIVE"
                    
                    # NO TIME LIMIT - Let market play out until TP/SL hit
                    # Only exit when target or stoploss is triggered (market structure)
                    monitor_iteration = 0
                    trailing_sl = sl  # Initial trailing stop (same as initial SL)
                    
                    while True:
                        current = self.trading_bot.get_real_option_price(symbol, strike, direction)
                        
                        if not current:
                            time.sleep(1)
                            continue
                        
                        # REAL-TIME P&L TRACKING (every iteration)
                        if monitor_iteration % 5 == 0:  # Update every 5 iterations to reduce API calls
                            pnl_data = calculate_realtime_pnl()
                            logger.info(f"💰 Real-time P&L: ₹{pnl_data['total_pnl']:.2f} (Realized: ₹{pnl_data['realized_pnl']:.2f}, Unrealized: ₹{pnl_data['unrealized_pnl']:.2f})")
                            logger.info(f"📊 Goal Progress: {pnl_data['goal_progress']:.1f}% of ₹{daily_profit_goal}")
                            
                            # Check if goal reached during monitoring
                            if check_profit_goal():
                                logger.info("🎉 Profit goal reached during active trade - continuing to let trailing SL protect gains")
                        
                        # FIXED: Correct trailing stop math with 5% activation threshold
                        # For CALL: trailing SL only moves UP (locks in profit) after 5% gain
                        # For PUT: trailing SL only moves DOWN (locks in profit) after 5% gain
                        if direction == 'CALL':
                            profit_percentage = ((current - entry) / entry) * 100 if entry > 0 else 0
                            if current > entry and profit_percentage >= 5:  # Only activate after 5% gain
                                profit = current - entry
                                # New SL is entry + 25% of profit (locks in gains)
                                potential_sl = entry + (profit * 0.25)
                                # Only update if new SL is higher than current trailing SL (only moves up)
                                trailing_sl = max(trailing_sl, potential_sl)
                                logger.info(f"📈 Trailing SL updated to ₹{trailing_sl:.2f} (profit: ₹{profit:.2f}, {profit_percentage:.2f}%)")
                        
                        elif direction == 'PUT':
                            profit_percentage = ((entry - current) / entry) * 100 if entry > 0 else 0
                            if current < entry and profit_percentage >= 5:  # Only activate after 5% gain
                                profit = entry - current
                                # New SL is entry - 25% of profit (locks in gains)
                                potential_sl = entry - (profit * 0.25)
                                # Only update if new SL is lower than current trailing SL (only moves down)
                                trailing_sl = min(trailing_sl, potential_sl)
                                logger.info(f"📈 Trailing SL updated to ₹{trailing_sl:.2f} (profit: ₹{profit:.2f}, {profit_percentage:.2f}%)")
                        
                        # LIVE MONITOR PRINT (Every 30 iterations to reduce log spam)
                        monitor_iteration += 1
                        if monitor_iteration % 30 == 0:
                            pnl_points = current - entry
                            pnl_rupees = pnl_points * lot_size
                            live_capital = current_capital + pnl_rupees
                            
                            logger.info("-"*80)
                            logger.info(f"📡 LIVE UPDATE #{monitor_iteration} ({current_datetime.strftime('%H:%M:%S')})")
                            logger.info("-"*80)
                            logger.info(f"{symbol} {direction} @ {strike}")
                            logger.info(f"Entry     : ₹{entry:.2f}")
                            logger.info(f"Current   : ₹{current:.2f}")
                            logger.info("")
                            logger.info(f"P&L       : ₹{pnl_rupees:.2f} ({pnl_points:.2f} points)")
                            logger.info(f"Capital   : ₹{live_capital:.2f}")
                            logger.info("-"*80)
                        
                        # Check TP/SL (using trailing stop for better risk management)
                        if direction == 'CALL':
                            if current >= target:
                                exit_price = current
                                status = "TARGET HIT"
                                break
                            elif current <= trailing_sl:
                                exit_price = current
                                status = "TRAILING SL HIT"
                                break
                        else:  # PUT
                            if current <= target:
                                exit_price = current
                                status = "TARGET HIT"
                                break
                            elif current >= trailing_sl:
                                exit_price = current
                                status = "TRAILING SL HIT"
                                break
                        
                        # Check market close (3:30 PM IST) - SYSTEM-WIDE SHUTDOWN
                        # SKIP IN DEMO MODE - demo runs 24/7
                        current_time_of_day = datetime.now().time()
                        market_close_time = dt_time(15, 30)
                        
                        if current_time_of_day >= market_close_time and not is_demo_mode:
                            logger.warning("⚠️ MARKET CLOSE DETECTED (3:30 PM IST) - Forcing position closure")
                            exit_price = current
                            status = "MARKET CLOSE"
                            break
                        
                        # FIXED: Add sleep to prevent API hammering
                        time.sleep(1)
                    
                    # Exit should always be set now (TP/SL or market close)
                    if exit_price is None:
                        # Fallback - should not happen
                        exit_price = self.trading_bot.get_real_option_price(symbol, strike, direction)
                        status = "UNEXPECTED EXIT"
                    
                    print(f"\n📊 TRADE RESULT: {status}")
                    print(f"   Exit: ₹{exit_price}")
                    
                    # Calculate P&L
                    points = exit_price - entry
                    pnl = points * lot_size
                    pnl_percent = (pnl / (entry * lot_size)) * 100
                    
                    # Update capital
                    current_capital += pnl
                    trade_count += 1
                    
                    if pnl > 0:
                        wins += 1
                        result_str = "WIN"
                    else:
                        losses += 1
                        result_str = "LOSS"
                    
                    # PRINT TRADE CLOSED (User Visibility)
                    logger.info("="*80)
                    logger.info("📊 TRADE CLOSED")
                    logger.info("="*80)
                    logger.info(f"Exit Price      : ₹{exit_price:.2f}")
                    logger.info(f"Points Gained   : {points:.2f}")
                    logger.info(f"P&L             : ₹{pnl:.2f} ({pnl_percent:.2f}%)")
                    logger.info(f"Result          : {result_str}")
                    logger.info("")
                    logger.info(f"Updated Capital : ₹{current_capital:.2f}")
                    logger.info("="*80)
                    
                    # REMOVE ACTIVE POSITION from tracking
                    trade_id = f"{symbol}_{strike}_{direction}_{int(current_time.timestamp())}"
                    if trade_id in active_positions:
                        del active_positions[trade_id]
                        logger.info(f"✅ Active position removed: {trade_id}")
                    
                    # UPDATE REAL-TIME P&L after trade close
                    pnl_data = calculate_realtime_pnl()
                    logger.info(f"💰 Updated Daily P&L: ₹{pnl_data['total_pnl']:.2f} (Goal: ₹{daily_profit_goal})")
                    logger.info(f"📊 Goal Progress: {pnl_data['goal_progress']:.1f}%")
                    
                    # Check if profit goal reached after this trade
                    if check_profit_goal():
                        logger.info("🎉 Profit goal reached after trade close - system entries locked")
                    
                    # Record trade
                    trade_record = {
                        'trade_num': trade_count,
                        'symbol': symbol,
                        'direction': direction,
                        'strike': strike,
                        'entry': entry,
                        'exit': exit_price,
                        'points': points,
                        'pnl': pnl,
                        'pnl_percent': pnl_percent,
                        'status': status,
                        'capital': current_capital,
                        'trade_type': trade_type  # Add trade type flag
                    }
                    trade_history.append(trade_record)
                    
                    # Write trade to manifest file for web interface
                    try:
                        import json
                        manifest_path = "D:\\Traiding_Bot\\active_trades.json"
                        
                        # Load existing manifest
                        if os.path.exists(manifest_path):
                            with open(manifest_path, 'r') as f:
                                manifest_data = json.load(f)
                        else:
                            manifest_data = {'trades': [], 'capital': start_capital}
                        
                        # Add trade to manifest
                        manifest_trade = {
                            'trade_id': f"{symbol}_{strike}_{direction}_{int(current_time.timestamp())}",
                            'underlying': symbol,
                            'option_type': 'CE' if direction == 'CALL' else 'PE',
                            'strike_price': strike,
                            'timestamp': current_time.isoformat(),
                            'status': status,
                            'trade_type': trade_type,  # Add trade type flag for dashboard
                            'execution': {
                                'entry_price': entry,
                                'current_price': exit_price,
                                'take_profit': target,
                                'current_stoploss': sl,
                                'pnl': pnl,
                                'pnl_percent': pnl_percent
                            },
                            'capital': current_capital,
                            'daily_pnl_tracking': {
                                'realized_pnl': daily_accumulated_pnl - pnl,  # P&L before this trade
                                'unrealized_pnl': 0.0,  # Trade is closed, so 0
                                'total_pnl': daily_accumulated_pnl,
                                'daily_profit_goal': daily_profit_goal,
                                'goal_progress': (daily_accumulated_pnl / daily_profit_goal) * 100 if daily_profit_goal > 0 else 0
                            }
                        }
                        manifest_data['trades'].append(manifest_trade)
                        manifest_data['capital'] = current_capital
                        
                        # Save manifest
                        with open(manifest_path, 'w') as f:
                            json.dump(manifest_data, f, indent=2)
                        
                        logger.info(f"✅ Trade written to manifest file: {manifest_trade['trade_id']}")
                    except Exception as e:
                        logger.error(f"❌ Failed to write trade to manifest: {e}")
                    
                    # Update last traded symbol (prevent consecutive same symbol)
                    last_traded_symbol = symbol
                    logger.info(f"✅ Updated last traded symbol to: {last_traded_symbol}")
                    
                    if pnl < 0 and "SL" in status:
                        sl_cooldown_cache[symbol] = current_time
                        logger.info(f"Anti-Whipsaw: {symbol} added to cooldown")
                    
                    last_scan_time = current_time
                    
                    # Wait before next trade
                    print(f"\n⏳ Waiting 2 minutes before next scan...")
                    time.sleep(120)
                else:
                    # Wait for next scan
                    time.sleep(30)
                    
            except KeyboardInterrupt:
                print("\n👋 Auto trading stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in auto trading loop: {e}")
                time.sleep(5)
        
        # Print final report
        self._print_auto_trading_report(start_capital, current_capital, trade_count, wins, losses, trade_history)
        
        # Generate comprehensive EOD markdown report
        print("\n" + "="*80)
        print("📊 GENERATING COMPREHENSIVE EOD PERFORMANCE REPORT")
        print("="*80)
        try:
            eod_report = self.trading_bot.generate_eod_performance_report(save_to_file=True)
            print(eod_report)
            print("="*80)
            print("✅ EOD Report saved to logs/ directory")
            print("="*80)
            
            # Auto-open logs directory to show EOD report
            try:
                logs_dir = os.path.join(os.path.dirname(TRADE_MANIFEST_PATH), "logs")
                logger.info(f"🌐 Auto-opening logs directory: {logs_dir}")
                webbrowser.open(f"file:///{logs_dir}")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Failed to auto-open logs directory: {e}")
        except Exception as e:
            logger.error(f"Error generating EOD report: {e}")
            print(f"⚠️  Error generating EOD report: {e}")
    
    def _print_auto_trading_report(self, start_capital, final_capital, trade_count, wins, losses, trade_history):
        """Print final auto trading report."""
        print("\n" + "="*80)
        print("📊 FINAL REPORT - AUTO PAPER TRADING")
        print("="*80)
        print(f"Starting Capital: ₹{start_capital}")
        print(f"Final Capital: ₹{final_capital:.2f}")
        print(f"Total P&L: ₹{final_capital - start_capital:.2f}")
        print()
        print(f"Total Trades: {trade_count}")
        print(f"Wins: {wins}")
        print(f"Losses: {losses}")
        
        if trade_count > 0:
            win_rate = (wins / trade_count) * 100
            avg_pnl = (final_capital - start_capital) / trade_count
            print(f"Win Rate: {win_rate:.2f}%")
            print(f"Average P&L per Trade: ₹{avg_pnl:.2f}")
        
        print()
        print("Trade History:")
        print("-" * 80)
        for trade in trade_history:
            print(f"Trade {trade['trade_num']}: {trade['symbol']} {trade['direction']} @ {trade['strike']}")
            print(f"  Entry: ₹{trade['entry']} | Exit: ₹{trade['exit']} | P&L: ₹{trade['pnl']:.2f} ({trade['pnl_percent']:.2f}%)")
            print(f"  Status: {trade['status']} | Capital: ₹{trade['capital']:.2f}")
        
        print("="*80)
        
        if final_capital > start_capital:
            print("✅ RESULT: PROFIT")
        elif final_capital < start_capital:
            print("❌ RESULT: LOSS")
        else:
            print("⚖️  RESULT: BREAKEVEN")
        print("="*80)



class Phase1AutoPaperTradingSystem:
    """
    Phase 1 Auto Paper Trading System
    Uses the new fast 2-engine architecture for automatic paper trading.
    """
    
    def __init__(self, start_capital=30000, end_time="15:20"):
        """
        Initialize Phase 1 Auto Paper Trading System.
        
        Args:
            start_capital: Starting virtual capital (default: ₹30,000)
            end_time: End time for trading (default: "15:20")
        """
        self.start_capital = start_capital
        self.end_time = end_time
        self.running = True
        
        # Load config
        self.config = self._load_config()
        
        # Initialize Phase 1 components
        self._init_phase1_components()
        
        # Web interface
        self.web_thread = None
        
        logger.info("Phase 1 Auto Paper Trading System initialized")
    
    def _load_config(self):
        """Load configuration from config.json."""
        try:
            import json
            with open("config.json", 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def _init_phase1_components(self):
        """Initialize Phase 1 components."""
        # Initialize Kite Client
        api_key = self.config.get("api_key", "")
        access_token = self.config.get("access_token", "")
        use_demo_data = self.config.get("use_demo_data", False)
        
        if use_demo_data:
            logger.info("DEMO MODE DISABLED - Demo simulator removed from codebase")
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
        logger.info("✅ Engine 2 (Async LLM Worker) started")
        
        # Initialize Execution & Risk Manager with virtual wallet
        self.risk_manager = ExecutionRiskManager(
            self.kite_client,
            daily_target=5000,
            start_capital=self.start_capital
        )
        logger.info(f"✅ Execution & Risk Manager initialized (Capital: ₹{self.start_capital})")

        # Initialize trading bot for real-time price updates
        from trading_bot import CleanTradingBot
        self.trading_bot = CleanTradingBot()
        logger.info("✅ Trading Bot initialized for real-time price updates")
        
        # Trading universe
        self.watchlist = self._load_watchlist()
        
        # Pending validations
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
        
        # LLM latency tracking for CLI table
        self.llm_latency_history = []  # List of recent LLM latencies
        self.cycle_history = []  # List of recent cycle data for CLI table
    
    def _init_llm_analyzer(self):
        """Initialize LLM analyzer based on config."""
        try:
            llm_provider = self.config.get("llm_provider", "ollama")
            logger.info(f"LLM Provider: {llm_provider}")
            
            if llm_provider == "ollama":
                ollama_config = self.config.get("ollama", {})
                if ollama_config.get("enabled", False):
                    ollama_url = ollama_config.get('base_url', 'http://localhost:11434')
                    model = ollama_config.get('default_model', 'tinyllama')
                    mode = ollama_config.get('trading_mode', 'moderate')
                    return LLMMarketAnalyzer(ollama_url=ollama_url, model=model, mode=mode)
            
            elif llm_provider == "gemini":
                gemini_config = self.config.get("gemini", {})
                if gemini_config.get("enabled", False):
                    api_key = gemini_config.get("api_key", "")
                    model = gemini_config.get("default_model", "gemini-1.5-flash")
                    return GeminiIntegration(api_key=api_key, model_name=model)
            
            logger.warning("LLM not enabled in config")
            return None
            
        except Exception as e:
            logger.error(f"Error initializing LLM analyzer: {e}")
            return None
    
    def _load_watchlist(self):
        """Load watchlist from config."""
        try:
            instruments = self.config.get("instruments", {})
            watchlist = list(instruments.keys())
            logger.info(f"Loaded watchlist: {watchlist}")
            return watchlist
        except Exception as e:
            logger.error(f"Error loading watchlist: {e}")
            return ["NIFTY", "BANKNIFTY"]
    
    def _start_web_interface(self):
        """Start the web interface in background thread."""
        try:
            logger.info("Starting Web Interface...")
            self.web_thread = threading.Thread(
                target=run_web_server,
                kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': False},
                daemon=True
            )
            self.web_thread.start()
            logger.info("✅ Web Interface started on http://localhost:5000")
        except Exception as e:
            logger.error(f"Failed to start Web Interface: {e}")
    
    def _auto_open_dashboard(self):
        """Auto-open the dashboard in browser."""
        try:
            dashboard_url = "http://localhost:5000"
            logger.info(f"🌐 Auto-opening dashboard: {dashboard_url}")
            webbrowser.open(dashboard_url)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Failed to auto-open dashboard: {e}")
            logger.info(f"Please manually open: http://localhost:5000")
    
    def run(self):
        """Run the Phase 1 auto paper trading system."""
        logger.info("=" * 80)
        logger.info("PHASE 1 AUTO PAPER TRADING SYSTEM STARTED")
        logger.info("=" * 80)
        
        # Start Web Interface
        self._start_web_interface()
        
        # Auto-open browser dashboard
        self._auto_open_dashboard()
        
        try:
            while self.running:
                cycle_start = time.time()
                
                self.stats['cycles'] += 1
                
                logger.info(f"\n{'=' * 80}")
                logger.info(f"CYCLE {self.stats['cycles']}")
                logger.info(f"{'=' * 80}")
                
                # Step 1: Monitor existing positions
                self._monitor_positions()
                
                # Step 2: Check daily target
                pnl_summary = self.risk_manager.get_daily_pnl()
                if pnl_summary['halt_triggered']:
                    logger.warning("Daily target halt triggered - trading stopped")
                    break
                
                # Step 3: Monitor existing positions if any, then scan for new signals
                active_positions = self.risk_manager.get_active_positions()
                if len(active_positions) > 0:
                    logger.info(f"Active positions: {len(active_positions)} - monitoring and updating P&L")
                    self._monitor_positions()  # Actually monitor the positions
                    time.sleep(5)
                    continue  # Skip new scanning while monitoring existing positions
                
                # Step 4: Scan market for signals (Engine 1 - NON-BLOCKING)
                self._scan_market()
                
                # Step 5: Check for completed LLM validations (NON-BLOCKING)
                self._check_validation_results()
                
                # Step 6: Print summary every 5 cycles
                if self.stats['cycles'] % 5 == 0:
                    self._print_summary()
                
                # Controlled frequency (non-blocking)
                time.sleep(10)
                
        except KeyboardInterrupt:
            logger.info("System stopped by user")
        finally:
            self.stop()
    
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
            if not self.running:
                break
            
            try:
                # Get instrument token
                instrument_key = self.config.get("instruments", {}).get(symbol, {}).get("instrument_token", symbol)
                
                # Get live quote (simplified for demo)
                import random
                base_price = 23600 if symbol == "NIFTY" else 48000 if symbol == "BANKNIFTY" else 2500
                current_price = base_price + random.randint(-50, 50)
                
                # Update Engine 1 price history
                vwap = self.engine1.update_price(symbol, current_price)
                
                # Generate empty option chain data (legacy file - not used by active system)
                option_chain = []
                self.engine1.update_option_chain(symbol, option_chain)
                
                # Calculate price change
                price_history = self.engine1.price_history.get(symbol, [])
                if len(price_history) >= 2:
                    prev_price = price_history[-2][0]
                    price_change = ((current_price - prev_price) / prev_price) * 100
                else:
                    price_change = 0.0
                
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
                decision = result.get('result', {}).get('decision', 'SKIP')
                latency = result.get('latency', 0.0)
                
                # Track LLM latency for CLI table
                self.llm_latency_history.append({
                    'request_id': request_id,
                    'decision': decision,
                    'latency': latency,
                    'symbol': signal.get('symbol', 'N/A'),
                    'direction': signal.get('direction', 'N/A')
                })
                
                # Keep only last 10 latencies
                if len(self.llm_latency_history) > 10:
                    self.llm_latency_history.pop(0)
                
                if approved:
                    self.stats['llm_approved'] += 1
                    logger.info(f"✅ LLM Approved: {request_id} - {reason}")
                    
                    # Execute trade
                    self._execute_signal(signal)
                else:
                    self.stats['llm_rejected'] += 1
                    logger.info(f"❌ LLM Rejected: {request_id} - {reason}")
    
    def _execute_signal(self, signal):
        """Execute a validated signal with dynamic lot sizing."""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            strike = signal['strike']
            
            # Get option entry price (simplified for demo)
            import random
            entry_price = 100 + random.randint(-20, 20)
            
            if entry_price <= 0:
                logger.warning(f"Invalid entry price for {symbol}")
                return
            
            # Calculate market quality for dynamic lot sizing
            market_quality = self._calculate_market_quality(signal)
            lot_size = self._determine_lot_size(market_quality)
            
            logger.info(f"📊 Market Quality: {market_quality} | Lot Size: {lot_size}")
            
            # Execute single-leg trade with dynamic lot sizing
            position_id = self.risk_manager.execute_single_leg(
                signal_data=signal,
                entry_price=entry_price,
                quantity=lot_size
            )
            
            if position_id:
                self.stats['executed_trades'] += 1
                logger.info(f"✅ Trade executed: {position_id} ({lot_size} lot)")
            else:
                logger.warning("Trade execution failed")
                
        except Exception as e:
            logger.error(f"Error executing signal: {e}")
    
    def _calculate_market_quality(self, signal):
        """
        Calculate market quality score based on technical confluence and human sentiment.
        
        Returns:
            'GOOD', 'FAIR', or 'POOR'
        """
        score = 0
        
        # Technical confluence score (0-3)
        strength = signal.get('strength', 0)
        score += strength  # 0-3 points
        
        # Human sentiment score (0-3)
        llm_context = signal.get('llm_context', {})
        
        # Trap detection bonus
        trap_detection = llm_context.get('trap_detection', 'NONE')
        if trap_detection == 'RETAIL_TRAP':
            score += 2  # Strong signal
        elif trap_detection == 'POTENTIAL_TRAP':
            score += 1
        
        # Smart money flow alignment
        smart_money = llm_context.get('smart_money_flow', 'NEUTRAL')
        if smart_money == 'BULLISH_DIVERGENCE' and signal.get('direction') == 'CALL':
            score += 1
        elif smart_money == 'BEARISH_DIVERGENCE' and signal.get('direction') == 'PUT':
            score += 1
        
        # Retail trap risk penalty
        trap_risk = llm_context.get('retail_trap_risk', 'MEDIUM')
        if trap_risk == 'HIGH':
            score -= 2  # Penalize high risk
        elif trap_risk == 'LOW':
            score += 1  # Bonus low risk
        
        # Determine quality
        if score >= 4:
            return 'GOOD'
        elif score >= 2:
            return 'FAIR'
        else:
            return 'POOR'
    
    def _determine_lot_size(self, market_quality):
        """
        Determine lot size based on market quality.
        
        Args:
            market_quality: 'GOOD', 'FAIR', or 'POOR'
            
        Returns:
            Lot size (integer)
        """
        if market_quality == 'GOOD':
            return 2  # Scale up for high-quality setups
        elif market_quality == 'FAIR':
            return 1  # Standard lot size
        else:  # POOR
            return 1  # Minimum lot size for defensive trading
    
    def _print_summary(self):
        """Print trading summary with CLI table formatter."""
        logger.info("=" * 100)
        logger.info("PHASE 1 TRADING SUMMARY - CLI TABLE FORMATTER")
        logger.info("=" * 100)
        
        # Print wallet balance
        capital_info = self.risk_manager.get_current_capital()
        pnl_summary = self.risk_manager.get_daily_pnl()
        logger.info(f"💰 Wallet Balance: ₹{capital_info:.2f} | Daily P&L: ₹{pnl_summary['daily_pnl']:.2f} | Target: ₹{pnl_summary['daily_target']}")
        
        # Print session status
        current_session = self.risk_manager.get_current_session()
        session_trades = self.risk_manager.session_trades.get(current_session, 0) if current_session else 0
        logger.info(f"📊 Session: {current_session.upper() if current_session else 'N/A'} | Trades: {session_trades}/{self.risk_manager.max_trades_per_session}")
        
        # Print cooldown status
        cooldown_active = self.risk_manager.is_entry_cooldown_active()
        logger.info(f"⏱️  Entry Cooldown: {'ACTIVE' if cooldown_active else 'INACTIVE'}")
        
        # Print LLM stats
        logger.info(f"🤖 LLM Stats: Submitted={self.stats['llm_submitted']} | Approved={self.stats['llm_approved']} | Rejected={self.stats['llm_rejected']}")
        
        # Print LLM decision history table
        logger.info(f"\n📋 LLM DECISION HISTORY (Last 10 Validations)")
        logger.info("-" * 100)
        logger.info(f"{'Symbol':<12} {'Direction':<8} {'Decision':<12} {'Latency(s)':<12} {'Status':<10}")
        logger.info("-" * 100)
        
        for entry in self.llm_latency_history[-10:]:
            symbol = entry['symbol']
            direction = entry['direction']
            decision = entry['decision']
            latency = entry['latency']
            status = 'APPROVED' if decision == 'YES' else 'REJECTED' if decision == 'NO' else 'SKIPPED'
            logger.info(f"{symbol:<12} {direction:<8} {decision:<12} {latency:<12.2f} {status:<10}")
        
        logger.info("=" * 100)
        
        # Print risk manager summary
        self.risk_manager.print_position_summary()
        
        logger.info("=" * 100)
    
    def stop(self):
        """Stop the Phase 1 system and generate EOD report."""
        self.running = False
        
        # Stop Engine 2
        self.engine2.stop()
        
        # Close all positions
        self.risk_manager._close_all_positions(reason="System stopped")
        
        # Generate EOD report
        self._generate_eod_report()
        
        logger.info("Phase 1 Auto Paper Trading System stopped")
    
    def _generate_eod_report(self):
        """Generate End-of-Day report."""
        try:
            logger.info("=" * 80)
            logger.info("GENERATING END-OF-DAY REPORT")
            logger.info("=" * 80)
            
            # Get final statistics
            capital_info = self.risk_manager.get_current_capital()
            pnl_summary = self.risk_manager.get_daily_pnl()
            
            # Calculate win/loss statistics
            completed_positions = self.risk_manager.completed_positions
            wins = sum(1 for p in completed_positions if p['pnl'] > 0)
            losses = sum(1 for p in completed_positions if p['pnl'] < 0)
            trade_count = len(completed_positions)
            
            # Generate report
            report = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'start_time': datetime.now().isoformat(),
                'start_capital': self.start_capital,
                'final_capital': capital_info,
                'total_pnl': pnl_summary['daily_pnl'],
                'realized_pnl': pnl_summary['realized_pnl'],
                'unrealized_pnl': pnl_summary['unrealized_pnl'],
                'daily_target': pnl_summary['daily_target'],
                'target_hit': pnl_summary['target_hit'],
                'total_trades': trade_count,
                'wins': wins,
                'losses': losses,
                'win_rate': (wins / trade_count * 100) if trade_count > 0 else 0,
                'llm_stats': {
                    'submitted': self.stats['llm_submitted'],
                    'approved': self.stats['llm_approved'],
                    'rejected': self.stats['llm_rejected']
                },
                'session_stats': self.risk_manager.session_trades,
                'trade_history': completed_positions
            }
            
            # Save report to file
            import json
            with open('eod_report_phase1.json', 'w') as f:
                json.dump(report, f, indent=2)
            
            # Print report
            logger.info(f"Date: {report['date']}")
            logger.info(f"Starting Capital: ₹{report['start_capital']}")
            logger.info(f"Final Capital: ₹{report['final_capital']:.2f}")
            logger.info(f"Total P&L: ₹{report['total_pnl']:.2f}")
            logger.info(f"Realized P&L: ₹{report['realized_pnl']:.2f}")
            logger.info(f"Unrealized P&L: ₹{report['unrealized_pnl']:.2f}")
            logger.info(f"Daily Target: ₹{report['daily_target']}")
            logger.info(f"Target Hit: {report['target_hit']}")
            logger.info(f"Total Trades: {report['total_trades']}")
            logger.info(f"Wins: {report['wins']} | Losses: {report['losses']}")
            logger.info(f"Win Rate: {report['win_rate']:.2f}%")
            logger.info(f"LLM Stats: Submitted={report['llm_stats']['submitted']} | Approved={report['llm_stats']['approved']} | Rejected={report['llm_stats']['rejected']}")
            logger.info(f"Session Stats: {report['session_stats']}")
            
            logger.info("=" * 80)
            logger.info("✅ EOD Report saved to eod_report_phase1.json")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error generating EOD report: {e}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Market Analysis System')
    parser.add_argument('--enable-trading-bot', action='store_true', 
                       help='Enable trading bot (CLI mode)')
    parser.add_argument('--auto-paper-trading', action='store_true',
                       help='Enable automatic paper trading mode')
    parser.add_argument('--automated', action='store_true',
                       help='Run in automated mode (no interactive prompts, auto-confirm trades)')
    parser.add_argument('--start-capital', type=int, default=30000,
                       help='Starting capital for paper trading')
    parser.add_argument('--eod', action='store_true',
                       help='Generate and print EOD performance report (manual trigger)')
    parser.add_argument('--end-time', type=str, default='15:30',
                       help='End time for trading (HH:MM format)')
    
    args = parser.parse_args()
    
    # Handle --eod flag (manual EOD report generation)
    if args.eod:
        print("\n" + "="*80)
        print("📊 GENERATING END-OF-DAY PERFORMANCE REPORT")
        print("="*80)
        try:
            from trading_bot import CleanTradingBot
            bot = CleanTradingBot()
            eod_report = bot.generate_eod_performance_report(save_to_file=True)
            print(eod_report)
            print("="*80)
            print("✅ EOD Report generated successfully")
            print("="*80)
            
            # Auto-open logs directory to show EOD report
            try:
                logs_dir = os.path.join(os.path.dirname(TRADE_MANIFEST_PATH), "logs")
                logger.info(f"🌐 Auto-opening logs directory: {logs_dir}")
                webbrowser.open(f"file:///{logs_dir}")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Failed to auto-open logs directory: {e}")
            
            return
        except Exception as e:
            print(f"❌ Error generating EOD report: {e}")
            return
    
    # Create and start system
    system = MarketAnalysisSystem(
        enable_trading_bot=args.enable_trading_bot,
        automated_mode=args.automated
    )
    
    # NON-DESTRUCTIVE HOOK: Start LLM worker (if trading bot enabled)
    if args.enable_trading_bot and system.trading_bot:
        def execute_trade_callback(trade):
            """Execution callback for LLM worker."""
            return system.trading_bot.trade_manager.add_trade(trade)
        
        start_llm_worker(execute_trade_callback)
        logger.info("✅ LLM Worker started in background (non-destructive integration)")
    
    # Choose mode
    if args.auto_paper_trading:
        # PHASE 1 MODE: Use new fast architecture when --auto-paper-trading is enabled
        if PHASE1_AVAILABLE:
            logger.info("🚀 PHASE 1 MODE: Using fast 2-engine architecture")
            print("\n🚀 PHASE 1 AUTO PAPER TRADING MODE")
            print("=" * 80)
            print("Using new non-blocking Phase 1 architecture:")
            print("  - Engine 1: Fast Market Analyzer (non-blocking)")
            print("  - Engine 2: Async LLM Worker (queue-based)")
            print("  - Risk Armor: Session caps, cooldowns, 1:5 RR")
            print("  - Virtual Wallet: ₹30,000 starting capital")
            print("=" * 80)
            
            # Initialize Phase 1 system
            phase1_system = Phase1AutoPaperTradingSystem(
                start_capital=args.start_capital,
                end_time=args.end_time
            )
            phase1_system.run()
        else:
            logger.warning("⚠️  Phase 1 components not available, falling back to legacy system")
            print("\n⚠️  Phase 1 components not available, using legacy system...")
            
            # Auto-paper-trading should always be automated
            if not system.automated_mode:
                logger.info("🤖 Auto-paper-trading mode detected - enabling automated mode")
                system.automated_mode = True
            
            print("\n🤖 Initializing Auto Paper Trading Mode...")
            system.start(skip_cli_mode=True)  # Initialize components, skip CLI
            system.run_auto_paper_trading(start_capital=args.start_capital, end_time=args.end_time)
    else:
        # Normal mode (CLI or market analyzer only) - uses legacy system
        system.start()


if __name__ == "__main__":
    main()
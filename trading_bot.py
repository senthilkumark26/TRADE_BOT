"""
Clean Event-Driven Trading Bot with LLM Integration
---------------------------------------------------
Architecture:
1. WebSocket Manager (data)
2. Market Scanner (find trade)
3. Trade Filter (OI + VIX + Delta + Trap)
4. LLM Evaluator (score)
5. Execution Controller (print/execute)

Event-driven: Bot finds trade → pauses → calls LLM → resumes

⚠️ MEMORY-SAFE SETTINGS (FROZEN - DO NOT MODIFY) ⚠️
These settings are PERMANENT and locked to prevent memory crashes.
Any attempt to modify these settings will be rejected.

MANUAL SIGNAL MODE:
Bot generates AI-validated manual signals for human execution instead of automated trading.
- Trade strength filtering: ENABLED (minimum strength 2/5)
- LLM cooldown: 30 seconds (FROZEN)
- Loop delay: 30 seconds (FROZEN) 
- Memory threshold: 80% (FROZEN)
- Memory cleanup: every 10 instruments (FROZEN)
- Model unload: every 3 calls (FROZEN)
"""

import os
import json
import logging
import time
import urllib.request
import urllib.parse
import math
import sys
import threading
import concurrent.futures
from datetime import datetime, time as dt_time
from typing import Dict, Any, Optional, List
from llm_market_analyzer import LLMMarketAnalyzer
from kite_client import KiteClient
from gemini_integration import GeminiIntegration
from optionstar import generate_trade
from llm_state_worker import LLMStateWorker
from trade_queue_system import TradeQueueSystem
from trade_memory import add_trade_result
from expiry_manager import ExpiryManager


# Thread-safe file locking for cross-component data integrity
file_lock = threading.Lock()

# Centralized file paths for consistency across modules
TRADE_MANIFEST_PATH = "D:\\Traiding_Bot\\active_trades.json"


# Trade Manifest Persistence Functions
def archive_daily_manifest(filename=None):
    """
    Archive the current day's trade manifest to logs directory for calibration.
    Creates a timestamped backup before starting a new trading day.
    
    Args:
        filename: Path to the trade manifest JSON file (uses default if None)
        
    Returns:
        True if successful, False otherwise
    """
    if filename is None:
        filename = TRADE_MANIFEST_PATH
        
    try:
        if not os.path.exists(filename):
            logger.info("No existing manifest to archive")
            return True
            
        # Create archive filename with date
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.path.dirname(filename), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Archive filename
        archive_filename = os.path.join(logs_dir, f"active_trades_{timestamp}.json")
        
        with file_lock:  # Ensure thread-safe archiving
            # Copy current manifest to archive
            with open(filename, 'r') as src:
                data = json.load(src)
            
            # Add archive metadata
            data['archive_metadata'] = {
                'archived_at': datetime.now().isoformat(),
                'archive_reason': 'daily_rotation',
                'original_file': filename
            }
            
            # Write to archive
            with open(archive_filename, 'w') as dst:
                json.dump(data, dst, indent=4)
            
            logger.info(f"📦 Daily manifest archived: {archive_filename}")
            
            # Clear current manifest for new trading day
            with open(filename, 'w') as f:
                json.dump({
                    "system_metadata": {
                        "engine_id": "12edf3",
                        "automated_mode": True,
                        "timeframe": "15m",
                        "ema_filter": "9_21_crossover"
                    },
                    "trades": []
                }, f, indent=4)
            
            logger.info(f"🧹 Manifest cleared for new trading day")
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to archive daily manifest: {e}")
        return False

def save_trade_manifest(trade_data, filename=None):
    """
    Persists trade data with complete structural constraints, calculations, and pre-market logic.
    Uses thread-safe atomic file operations to prevent corruption during concurrent read/write.
    
    Args:
        trade_data: Dictionary containing complete trade information
        filename: Path to the trade manifest JSON file (uses default if None)
        
    Returns:
        True if successful, False otherwise
    """
    if filename is None:
        filename = TRADE_MANIFEST_PATH
        
    with file_lock:  # Ensures web server cannot read mid-write
        try:
            # Prevent completely overwriting historical files if they exist
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    existing_data = json.load(f)
                # Check if trade already exists, update it instead of appending
                trade_id = trade_data.get('trade_id', '')
                if trade_id:
                    # Update existing trade or append new one
                    found = False
                    for i, trade in enumerate(existing_data.get("trades", [])):
                        if trade.get('trade_id') == trade_id:
                            existing_data["trades"][i] = trade_data
                            found = True
                            break
                    if not found:
                        existing_data["trades"].append(trade_data)
                else:
                    existing_data["trades"].append(trade_data)
            else:
                # Create new file with system metadata
                existing_data = {
                    "system_metadata": {
                        "engine_id": "12edf3",
                        "automated_mode": True,
                        "timeframe": "15m",
                        "ema_filter": "9_21_crossover"
                    },
                    "trades": [trade_data]
                }
            
            # Write to temporary file first, then atomically replace the target file
            temp_filename = filename + ".tmp"
            with open(temp_filename, 'w') as f:
                json.dump(existing_data, f, indent=4)
            
            # Atomic operation - works on both Windows and Linux
            os.replace(temp_filename, filename)
            
            logger.info(f"✅ Trade manifest saved atomically: {trade_data.get('trade_id', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"❌ Critical write failure in save_trade_manifest: {e}")
            return False


def should_rotate_manifest(filename=None):
    """
    Check if manifest rotation is needed (new trading day).
    
    Args:
        filename: Path to the trade manifest JSON file (uses default if None)
        
    Returns:
        True if rotation is needed, False otherwise
    """
    if filename is None:
        filename = TRADE_MANIFEST_PATH
        
    try:
        if not os.path.exists(filename):
            return False  # No existing file, no rotation needed
            
        with file_lock:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            # Check archive metadata if exists
            if 'archive_metadata' in data:
                archived_at = data['archive_metadata']['archived_at']
                archived_date = datetime.fromisoformat(archived_at).date()
                today = datetime.now().date()
                
                # If archived on a different day, rotation needed
                return archived_date != today
            
            # Check if trades exist and last trade was from a different day
            trades = data.get('trades', [])
            if trades:
                # Get timestamp from most recent trade
                last_trade_time = trades[-1].get('timestamp', '')
                if last_trade_time and isinstance(last_trade_time, str):
                    try:
                        last_trade_date = datetime.fromisoformat(last_trade_time).date()
                        today = datetime.now().date()
                        return last_trade_date != today
                    except ValueError:
                        logger.warning(f"Could not parse trade timestamp: {last_trade_time}")
                        return False
            
            return False
            
    except Exception as e:
        logger.error(f"Error checking manifest rotation: {e}")
        return False  # On error, don't rotate to be safe

def load_trade_manifest(filename=None):
    """
    Loads the complete trade manifest from disk with thread-safe reading.
    
    Args:
        filename: Path to the trade manifest JSON file (uses default if None)
        
    Returns:
        Dictionary containing system metadata and trades, or None if file doesn't exist
    """
    if filename is None:
        filename = TRADE_MANIFEST_PATH
        
    with file_lock:  # Ensures no concurrent write during read
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return json.load(f)
            return None
        except Exception as e:
            logger.error(f"❌ Failed to read trade manifest: {e}")
            return None


def convert_to_manifest_format(trade_data, filter_data=None):
    """
    Converts internal trade format to production-ready manifest format.
    
    Args:
        trade_data: Internal trade data dictionary
        filter_data: Optional filter data (EMA, OI, trend direction)
        
    Returns:
        Dictionary in manifest format
    """
    from datetime import datetime, timezone
    
    manifest_trade = {
        "trade_id": trade_data.get('trade_id', ''),
        "timestamp": datetime.fromtimestamp(trade_data.get('entry_time', time.time()), tz=timezone.utc).isoformat(),
        "underlying": trade_data.get('symbol', ''),
        "strike_price": trade_data.get('strike', 0),
        "option_type": trade_data.get('option_type', ''),
        "status": trade_data.get('status', 'ACTIVE'),
        "execution": {
            "entry_price": trade_data.get('entry', 0.0),
            "current_price": trade_data.get('current_price', 0.0),
            "highest_price_reached": trade_data.get('highest_price', 0.0),
            "initial_stoploss": trade_data.get('original_stoploss', 0.0),
            "current_stoploss": trade_data.get('stoploss', 0.0),
            "take_profit": trade_data.get('target', 0.0),
            "risk_reward_ratio": trade_data.get('risk_reward_ratio', 0.0),
            "lot_size": self.config.get('instruments', {}).get(trade_data.get('symbol', ''), {}).get('lot_size', 1),  # Dynamic lot size from Zerodha
            "total_risk_capital": trade_data.get('risk_amount', 0.0)
        },
        "trailing_sl_logic": {
            "lock_in_percentage": 0.25,
            "peak_profit": trade_data.get('pnl_percentage', 0.0) if trade_data.get('pnl_percentage', 0.0) > 0 else 0.0,
            "mathematical_floor_applied": len(trade_data.get('sl_adjustments', [])) > 0
        }
    }
    
    # Add straddle volatility metrics if available (Filter 5 data)
    if 'straddle_metrics' in trade_data and trade_data['straddle_metrics']:
        straddle_metrics = trade_data['straddle_metrics']
        manifest_trade["straddle_volatility"] = {
            "straddle_price": straddle_metrics.get('straddle_price', 0.0),
            "blended_vwap": straddle_metrics.get('blended_vwap', 0.0),
            "deviation_percentage": straddle_metrics.get('deviation_percentage', 0.0),
            "ce_price": straddle_metrics.get('ce_price', 0.0),
            "pe_price": straddle_metrics.get('pe_price', 0.0),
            "total_volume": straddle_metrics.get('total_volume', 0),
            "expansion_status": "CONFIRMED" if straddle_metrics.get('deviation_percentage', 0) >= 2.5 else "NEUTRAL"
        }
    
    # Add filter data if provided
    if filter_data:
        manifest_trade["filters_passed"] = filter_data
    
    return manifest_trade

# ⚠️ FROZEN MEMORY-SAFE CONSTANTS (DO NOT MODIFY) ⚠️
# These settings are locked permanently to prevent memory crashes
FROZEN_LLM_COOLDOWN_SECONDS = 30  # FROZEN: Minimum 30 seconds between LLM calls
FROZEN_LOOP_DELAY_SECONDS = 30     # FROZEN: 30 seconds between scan cycles
FROZEN_MEMORY_THRESHOLD_PERCENT = 80  # FROZEN: Skip LLM if memory > 80%
FROZEN_MEMORY_CLEANUP_FREQUENCY = 10  # FROZEN: Cleanup every 10 instruments
FROZEN_MODEL_UNLOAD_FREQUENCY = 3     # FROZEN: Unload model every 3 calls
FROZEN_TRADE_STRENGTH_THRESHOLD = 2   # FROZEN: Minimum trade strength 2/5 for LLM
FROZEN_MEMORY_GUARD_THRESHOLD = 70   # FROZEN: Sleep if memory > 70%

# Kite Connect Symbol Mapping (using instrument tokens)
# Instrument tokens are required for Kite Connect LTP API
SYMBOL_MAP = {
    "NIFTY": "256265",          # NIFTY 50 Index
    "BANKNIFTY": "260105",      # NIFTY BANK Index
    "INFY": "408065",           # INFOSYS
    "TCS": "438821",            # TCS
    "HDFCBANK": "341249",       # HDFC BANK
    "ICICIBANK": "887457",      # ICICI BANK
    "SBIN": "779521",           # STATE BANK OF INDIA
    "AXISBANK": "590981",       # AXIS BANK
    "KOTAKBANK": "895329",      # KOTAK MAHINDRA BANK
    "WIPRO": "741569",          # WIPRO
    "HCLTECH": "738561",        # HCL TECHNOLOGIES
    "ITC": "466881",            # ITC
    "HINDUNILVR": "633601",     # HINDUSTAN UNILEVER
    "ONGC": "881313"            # ONGC
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TradeManager:
    """
    Manages active trades with continuous monitoring, exit analysis, and SL management.
    Sticks with trades until completion (TP/SL hit) before finding new ones.
    """
    
    def __init__(self, kite_client, llm_analyzer, max_concurrent_trades=2):
        """
        Initialize Trade Manager.
        
        Args:
            kite_client: KiteConnect client for price updates
            llm_analyzer: LLM analyzer for exit/sentiment analysis
            max_concurrent_trades: Maximum number of concurrent trades (default: 2)
        """
        self.kite_client = kite_client
        self.llm_analyzer = llm_analyzer
        self.max_concurrent_trades = max_concurrent_trades
        
        # Active trades tracking
        self.active_trades = {}  # trade_id -> trade_data
        self.completed_trades = []  # History of completed trades
        
        # Trade monitoring
        self.monitoring_active = False
        self.last_monitor_time = 0
        self.monitor_interval = 5  # Check every 5 seconds
        
        logger.info(f"Trade Manager initialized (max concurrent trades: {max_concurrent_trades})")
    
    def add_trade(self, trade_setup):
        """
        Add a new trade to active monitoring.
        
        Args:
            trade_setup: Complete trade setup with entry, target, stoploss, etc.
        
        Returns:
            trade_id if added successfully, None if at max capacity
        """
        if len(self.active_trades) >= self.max_concurrent_trades:
            logger.warning(f"Cannot add trade - at max capacity ({self.max_concurrent_trades})")
            return None
        
        # Generate unique trade ID
        trade_id = f"{trade_setup['symbol']}_{trade_setup['strike']}_{int(time.time())}"
        
        # Initialize trade tracking data
        trade_data = {
            "trade_id": trade_id,
            "symbol": trade_setup['symbol'],
            "direction": trade_setup['direction'],
            "strike": trade_setup['strike'],
            "option_type": 'CE' if trade_setup['direction'] == 'CALL' else 'PE',
            "entry": trade_setup['entry'],
            "target": trade_setup['target'],
            "stoploss": trade_setup['stoploss'],
            "original_stoploss": trade_setup['stoploss'],
            "risk_amount": trade_setup.get('risk_amount', 0),
            "reward_amount": trade_setup.get('reward_amount', 0),
            "risk_reward_ratio": trade_setup.get('risk_reward_ratio', 0),
            "spot": trade_setup.get('spot', 0),
            "entry_time": time.time(),
            "status": "ACTIVE",  # ACTIVE, TP_HIT, SL_HIT, EXIT_MANUAL
            "current_price": trade_setup['entry'],
            "pnl": 0.0,
            "pnl_percentage": 0.0,
            "highest_price": trade_setup['entry'],  # For trailing SL
            "lowest_price": trade_setup['entry'],   # For trailing SL
            "sl_adjustments": [],  # History of SL adjustments
            "exit_reason": "",
            "llm_analysis_history": [],  # History of LLM exit analyses
            "instrument_token": trade_setup.get('instrument_token', '')
        }
        
        self.active_trades[trade_id] = trade_data
        
        # Enhanced logging for first trade verification
        logger.info("=" * 80)
        logger.info(f"✅ NEW TRADE ADDED: {trade_id}")
        logger.info(f"Symbol: {trade_setup['symbol']} | Strike: {trade_setup['strike']} {trade_data['option_type']}")
        logger.info(f"Direction: {trade_setup['direction']}")
        logger.info(f"Entry: ₹{trade_setup['entry']:.2f} | Target: ₹{trade_setup['target']:.2f} | SL: ₹{trade_setup['stoploss']:.2f}")
        logger.info(f"Risk: ₹{trade_data['risk_amount']:.2f} | Reward: ₹{trade_data['reward_amount']:.2f} | R:R: {trade_data['risk_reward_ratio']:.2f}")
        logger.info(f"Initial Highest Price: ₹{trade_data['highest_price']:.2f} (for trailing SL)")
        logger.info("=" * 80)
        
        self.print_trade_table(trade_id)
        
        # Save to trade manifest
        try:
            manifest_trade = convert_to_manifest_format(trade_data)
            save_trade_manifest(manifest_trade)
        except Exception as e:
            logger.warning(f"Failed to save trade manifest: {e}")
        
        return trade_id
    
    def update_trade_price(self, trade_id, current_price):
        """
        Update current price for a trade and check TP/SL conditions.
        
        Args:
            trade_id: Trade identifier
            current_price: Current option premium price
        """
        if trade_id not in self.active_trades:
            return
        
        trade = self.active_trades[trade_id]
        trade['current_price'] = current_price
        
        # Calculate P&L
        trade['pnl'] = current_price - trade['entry']
        trade['pnl_percentage'] = (trade['pnl'] / trade['entry']) * 100
        
        # Update highest/lowest for trailing SL with logging
        if current_price > trade['highest_price']:
            old_highest = trade['highest_price']
            trade['highest_price'] = current_price
            logger.info(f"📈 New Highest Price: {trade_id} | ₹{old_highest:.2f} → ₹{current_price:.2f} | Profit: ₹{trade['pnl']:.2f} ({trade['pnl_percentage']:.2f}%)")
        if current_price < trade['lowest_price']:
            trade['lowest_price'] = current_price
        
        # Check TP hit
        if current_price >= trade['target']:
            self._handle_tp_hit(trade_id)
            return
        
        # Check SL hit
        # Check SL hit with entry skip rule (30-second buffer to allow bid-ask spread to settle)
        time_in_trade = time.time() - trade['entry_time']
        if time_in_trade >= 30 and current_price <= trade['stoploss']:
            self._handle_sl_hit(trade_id)
            return
        
        # Save manifest for price update (throttle to avoid excessive writes)
        # Only save if price changed significantly or every N updates
        if int(time.time()) % 10 == 0:  # Save every 10 seconds approximately
            try:
                manifest_trade = convert_to_manifest_format(trade)
                save_trade_manifest(manifest_trade)
            except Exception as e:
                logger.warning(f"Failed to save trade manifest on price update: {e}")
    
    def _handle_tp_hit(self, trade_id):
        """Handle when target price is hit."""
        trade = self.active_trades[trade_id]
        trade['status'] = 'TP_HIT'
        trade['exit_reason'] = 'Target achieved'
        trade['exit_time'] = time.time()
        
        # Record outcome in memory for adaptive learning
        add_trade_result("WIN", trade['symbol'], trade['direction'])
        
        # Move to completed trades
        self.completed_trades.append(trade)
        del self.active_trades[trade_id]
        
        logger.info(f"🎯 TP HIT: {trade_id} | P&L: ₹{trade['pnl']:.2f} ({trade['pnl_percentage']:.2f}%)")
        self.print_trade_summary(trade)
        
        # Save manifest for completed trade
        try:
            manifest_trade = convert_to_manifest_format(trade)
            save_trade_manifest(manifest_trade)
        except Exception as e:
            logger.warning(f"Failed to save trade manifest on TP hit: {e}")
        
        # Call completion callback if registered
        if self.trade_completion_callback:
            try:
                self.trade_completion_callback(trade_id, trade)
                logger.info(f"🔔 Trade completion callback triggered for {trade_id}")
            except Exception as e:
                logger.error(f"Error calling trade completion callback: {e}")
    
    def _handle_sl_hit(self, trade_id):
        """Handle when stoploss is hit - trigger LLM analysis for SL decision."""
        trade = self.active_trades[trade_id]
        
        logger.warning(f"⚠️ SL HIT: {trade_id} | Current: ₹{trade['current_price']:.2f}, SL: ₹{trade['stoploss']:.2f}")
        
        # Anti-Whipsaw: Log SL hit timestamp for cooldown
        symbol = trade['symbol']
        self.sl_cooldown_cache[symbol] = time.time()
        logger.info(f"🛡️ Anti-Whipsaw: {symbol} added to 30-minute cooldown cache")
        
        # Use LLM to decide whether to move SL or exit
        if self.llm_analyzer:
            decision = self._analyze_sl_decision(trade)
            if decision == 'MOVE_SL':
                self._adjust_stoploss(trade_id)
            else:
                self._close_trade(trade_id, 'SL hit - LLM recommended exit')
        else:
            # No LLM available, close the trade
            self._close_trade(trade_id, 'SL hit - no LLM available')
    
    def _analyze_sl_decision(self, trade):
        """
        Use LLM to analyze whether to move SL or exit when SL is hit.
        
        Args:
            trade: Trade data dictionary
        
        Returns:
            'MOVE_SL' or 'EXIT'
        """
        try:
            # Prepare trade context for LLM
            trade_context = {
                "symbol": trade['symbol'],
                "direction": trade['direction'],
                "entry": trade['entry'],
                "current_price": trade['current_price'],
                "stoploss": trade['stoploss'],
                "target": trade['target'],
                "pnl": trade['pnl'],
                "pnl_percentage": trade['pnl_percentage'],
                "highest_price": trade['highest_price'],
                "time_in_trade": time.time() - trade['entry_time'],
                "analysis_type": "sl_decision"
            }
            
            logger.info(f"🤖 LLM analyzing SL decision for {trade['trade_id']}...")
            
            # Call LLM for exit analysis
            if hasattr(self.llm_analyzer, 'analyze_exit_signal'):
                analysis = self.llm_analyzer.analyze_exit_signal(trade_context, trade)
            elif hasattr(self.llm_analyzer, 'analyze_trading_data'):
                analysis = self.llm_analyzer.analyze_trading_data(trade_context, "exit")
            else:
                logger.warning("LLM analyzer has no exit analysis method")
                return 'EXIT'
            
            if analysis:
                action = analysis.get('action', 'EXIT')
                confidence = analysis.get('confidence', 0)
                reason = analysis.get('reason', 'No reason provided')
                
                # Store LLM analysis history
                trade['llm_analysis_history'].append({
                    'timestamp': time.time(),
                    'action': action,
                    'confidence': confidence,
                    'reason': reason
                })
                
                logger.info(f"🤖 LLM SL Decision: {action} (confidence: {confidence}%)")
                logger.info(f"🤖 LLM Reason: {reason}")
                
                if action in ['EXIT_NOW', 'EXIT']:
                    return 'EXIT'
                elif action in ['HOLD', 'MOVE_SL', 'ADJUST_SL']:
                    return 'MOVE_SL'
            
            return 'EXIT'
            
        except Exception as e:
            logger.error(f"Error in LLM SL analysis: {e}")
            return 'EXIT'
    
    def _adjust_stoploss(self, trade_id):
        """
        Adjust stoploss based on LLM recommendation or trailing logic.
        
        CRITICAL: Trailing stop MUST only move UP, never down.
        It should be based on HIGHEST price reached, not current price.
        
        Args:
            trade_id: Trade identifier
        """
        trade = self.active_trades[trade_id]
        
        # Calculate new SL based on HIGHEST price (trailing SL logic)
        # This ensures SL only moves UP, never down
        highest_price = trade['highest_price']
        peak_profit = highest_price - trade['entry']
        
        # Calculate new SL: lock 25% of peak profit
        # Example: Entry 100, Highest 120 (20% profit) → SL = 100 + (20 * 0.25) = 105
        new_sl = trade['entry'] + (peak_profit * 0.25)
        
        # Ensure SL is at least at breakeven if in profit
        if trade['pnl_percentage'] > 0:
            new_sl = max(new_sl, trade['entry'])
        
        # CRITICAL: Only move SL UP (never down)
        # This is the defining characteristic of a trailing stop
        # Using max() ensures SL never decreases even if there's a logic bug
        if new_sl > trade['stoploss']:
            old_sl = trade['stoploss']
            trade['stoploss'] = max(trade['stoploss'], new_sl)  # Double protection
            
            trade['sl_adjustments'].append({
                'timestamp': time.time(),
                'old_sl': old_sl,
                'new_sl': new_sl,
                'reason': f'Trailing SL (Highest: ₹{highest_price:.2f}, Peak Profit: ₹{peak_profit:.2f})'
            })
            
            logger.info(f"📈 SL Adjusted: {trade_id} | Old SL: ₹{old_sl:.2f} → New SL: ₹{new_sl:.2f} | Highest: ₹{highest_price:.2f}")
            
            # Save manifest for SL adjustment
            try:
                manifest_trade = convert_to_manifest_format(trade)
                save_trade_manifest(manifest_trade)
            except Exception as e:
                logger.warning(f"Failed to save trade manifest on SL adjustment: {e}")
            self.print_trade_table(trade_id)
        else:
            logger.info(f"SL not adjusted - new SL ({new_sl:.2f}) not higher than current ({trade['stoploss']:.2f})")
            self._close_trade(trade_id, 'SL hit - SL adjustment not beneficial')
    
    def analyze_exit_signal(self, trade_id):
        """
        Use LLM to analyze if current trade should be exited (profit booking or loss cutting).
        
        Args:
            trade_id: Trade identifier
        
        Returns:
            Dictionary with exit recommendation and sentiment
        """
        if trade_id not in self.active_trades:
            return None
        
        trade = self.active_trades[trade_id]
        
        try:
            # Prepare trade context for LLM
            trade_context = {
                "symbol": trade['symbol'],
                "direction": trade['direction'],
                "strike": trade['strike'],
                "entry": trade['entry'],
                "current_price": trade['current_price'],
                "target": trade['target'],
                "stoploss": trade['stoploss'],
                "pnl": trade['pnl'],
                "pnl_percentage": trade['pnl_percentage'],
                "highest_price": trade['highest_price'],
                "lowest_price": trade['lowest_price'],
                "time_in_trade": time.time() - trade['entry_time'],
                "risk_reward_ratio": trade['risk_reward_ratio'],
                "analysis_type": "exit_analysis"
            }
            
            logger.info(f"🤖 LLM analyzing exit signal for {trade_id}...")
            
            # Call LLM for exit analysis
            if hasattr(self.llm_analyzer, 'analyze_exit_signal'):
                analysis = self.llm_analyzer.analyze_exit_signal(trade_context, trade)
            elif hasattr(self.llm_analyzer, 'analyze_trading_data'):
                analysis = self.llm_analyzer.analyze_trading_data(trade_context, "exit")
            else:
                logger.warning("LLM analyzer has no exit analysis method")
                return None
            
            if analysis:
                # Store LLM analysis history
                trade['llm_analysis_history'].append({
                    'timestamp': time.time(),
                    'analysis': analysis
                })
                
                logger.info(f"🤖 LLM Exit Analysis: {analysis.get('action', 'N/A')} (confidence: {analysis.get('confidence', 0)}%)")
                logger.info(f"🤖 LLM Sentiment: {analysis.get('reason', 'N/A')}")
                
                return analysis
            
            return None
            
        except Exception as e:
            logger.error(f"Error in LLM exit analysis: {e}")
            return None
    
    def _close_trade(self, trade_id, reason):
        """Close a trade and move it to completed trades."""
        trade = self.active_trades[trade_id]
        trade['status'] = 'CLOSED'
        trade['exit_reason'] = reason
        trade['exit_time'] = time.time()
        
        # Record outcome in memory for adaptive learning
        outcome = "WIN" if trade['pnl'] > 0 else "LOSS"
        add_trade_result(outcome, trade['symbol'], trade['direction'])
        
        # Move to completed trades
        self.completed_trades.append(trade)
        del self.active_trades[trade_id]
        
        logger.info(f"❌ Trade Closed: {trade_id} | Reason: {reason} | P&L: ₹{trade['pnl']:.2f} ({trade['pnl_percentage']:.2f}%)")
        self.print_trade_summary(trade)
        
        # Save manifest for closed trade
        try:
            manifest_trade = convert_to_manifest_format(trade)
            save_trade_manifest(manifest_trade)
        except Exception as e:
            logger.warning(f"Failed to save trade manifest on trade close: {e}")
        
        # Call completion callback if registered
        if self.trade_completion_callback:
            try:
                self.trade_completion_callback(trade_id, trade)
                logger.info(f"🔔 Trade completion callback triggered for {trade_id}")
            except Exception as e:
                logger.error(f"Error calling trade completion callback: {e}")
    
    def close_trade_manually(self, trade_id, reason="Manual exit"):
        """Manually close a trade."""
        if trade_id in self.active_trades:
            self._close_trade(trade_id, reason)
            return True
        return False
    
    def monitor_active_trades(self):
        """
        Monitor all active trades - update prices, check TP/SL, perform exit analysis.
        Should be called periodically in the main loop.
        """
        if not self.active_trades:
            return
        
        current_time = time.time()
        if current_time - self.last_monitor_time < self.monitor_interval:
            return
        
        self.last_monitor_time = current_time
        
        logger.info(f"🔍 Monitoring {len(self.active_trades)} active trade(s)...")
        
        # Update prices for all active trades
        for trade_id in list(self.active_trades.keys()):  # Use list() to avoid dict modification during iteration
            trade = self.active_trades[trade_id]
            
            try:
                # Get current price for the option
                # In real implementation, this would fetch actual option price
                # For now, we'll simulate price movement or use last known price
                # In production, you'd fetch the actual option premium from Kite
                
                # Simulate price movement for demo (remove in production)
                import random
                price_change_percent = random.uniform(-0.5, 0.5)  # -0.5% to +0.5%
                simulated_price = trade['current_price'] * (1 + price_change_percent / 100)
                
                # Update trade price
                self.update_trade_price(trade_id, simulated_price)
                
                # Perform periodic exit analysis (every 30 seconds)
                if current_time - trade['entry_time'] > 30 and len(trade['llm_analysis_history']) == 0:
                    exit_analysis = self.analyze_exit_signal(trade_id)
                    if exit_analysis:
                        action = exit_analysis.get('action', 'HOLD')
                        if action == 'EXIT_NOW':
                            self._close_trade(trade_id, 'LLM recommended immediate exit')
                        elif action == 'EXIT_SOON':
                            logger.info(f"⏰ LLM suggests exiting soon for {trade_id}")
                
            except Exception as e:
                logger.error(f"Error monitoring trade {trade_id}: {e}")
    
    def can_add_new_trade(self):
        """Check if we can add a new trade (under max capacity)."""
        return len(self.active_trades) < self.max_concurrent_trades
    
    def get_active_trade_count(self):
        """Get number of currently active trades."""
        return len(self.active_trades)
    
    def print_trade_table(self, trade_id=None):
        """Print formatted table of trade(s). If trade_id provided, print only that trade."""
        print("\n" + "=" * 120)
        print("📊 ACTIVE TRADES MONITORING")
        print("=" * 120)
        
        trades_to_print = []
        if trade_id:
            if trade_id in self.active_trades:
                trades_to_print = [self.active_trades[trade_id]]
        else:
            trades_to_print = list(self.active_trades.values())
        
        if not trades_to_print:
            print("No active trades")
            print("=" * 120)
            return
        
        # Print table header
        print(f"{'ID':<20} {'Symbol':<10} {'Option':<12} {'Entry':<10} {'Current':<10} {'Target':<10} {'SL':<10} {'P&L (₹)':<10} {'P&L %':<8} {'Status':<12}")
        print("-" * 120)
        
        for trade in trades_to_print:
            option_str = f"{trade['strike']} {trade['option_type']}"
            pnl_str = f"{trade['pnl']:.2f}"
            pnl_pct_str = f"{trade['pnl_percentage']:.2f}%"
            
            print(f"{trade['trade_id']:<20} {trade['symbol']:<10} {option_str:<12} {trade['entry']:<10.2f} {trade['current_price']:<10.2f} {trade['target']:<10.2f} {trade['stoploss']:<10.2f} {pnl_str:<10} {pnl_pct_str:<8} {trade['status']:<12}")
        
        print("=" * 120)
    
    def print_trade_summary(self, trade):
        """Print summary of a completed trade."""
        print("\n" + "=" * 120)
        print(f"📋 TRADE COMPLETED: {trade['trade_id']}")
        print("=" * 120)
        print(f"Symbol: {trade['symbol']} | Option: {trade['strike']} {trade['option_type']}")
        print(f"Entry: ₹{trade['entry']:.2f} | Exit: ₹{trade['current_price']:.2f}")
        print(f"Target: ₹{trade['target']:.2f} | Stoploss: ₹{trade['stoploss']:.2f}")
        print(f"Final P&L: ₹{trade['pnl']:.2f} ({trade['pnl_percentage']:.2f}%)")
        print(f"Status: {trade['status']} | Reason: {trade['exit_reason']}")
        print(f"Duration: {int(time.time() - trade['entry_time'])} seconds")
        print("=" * 120)


class CleanTradingBot:
    """
    Clean event-driven trading bot with proper LLM integration.
    Multi-instrument market scanner with smart universe selection.
    Now with trade management - sticks with trades until completion.
    """
    
    def __init__(self):
        self.config_path = "config.json"
        
        # Bot state flags (NOT blocking loops) - Initialize BEFORE load_config
        self.bot_running = False
        self.bot_mode = "normal"  # normal or observation
        self.paper_trading_enabled = False  # Runtime control - manual toggle
        self.market_data = {}
        self.price_history = {}
        
        # Best trades ranking (for initial trade selection)
        self.best_trades = []
        self.max_best_trades = 3  # Keep top 3 trades
        
        # 9:15 Market Open Analysis
        self.market_open_analysis_done = False  # Track if 9:15 analysis completed
        self.selected_strikes = {}  # Store selected strikes per instrument
        
        self.load_config()
        self.base_url = "https://api.upstox.com/v2"
        
        # CRITICAL: Daily manifest rotation for calibration baseline preservation
        if should_rotate_manifest():
            logger.info("🔄 Daily manifest rotation detected - archiving previous day's data")
            archive_daily_manifest()
        
        # Trading universe (smart selection - dynamically loaded from config)
        self.watchlist = self._load_watchlist_from_config()

        # Initialize Kite Connect client
        api_key = self.config.get("api_key", "")
        access_token = self.config.get("access_token", "")
        
        # Check for demo mode
        use_demo_data = self.config.get("use_demo_data", False)
        self.demo_simulator = None
        
        if use_demo_data:
            logger.info("="*80)
            logger.info("DEMO MODE DISABLED - Demo simulator removed from codebase")
            logger.info("="*80)
            # Demo simulator has been removed - use real data only
            self.kite_client = KiteClient(api_key, access_token)
        else:
            # Initialize kite_client in live mode
            self.kite_client = KiteClient(api_key, access_token)
        
        # Trade throttling
        self.last_trade_time = 0
        self.trade_cooldown_seconds = 10  # Minimum 10 seconds between trades
        
        # LLM throttling (to prevent memory spikes) - FROZEN MEMORY-SAFE SETTINGS
        self.last_llm_call = 0
        self._llm_cooldown_seconds = FROZEN_LLM_COOLDOWN_SECONDS  # ⚠️ FROZEN: Do not modify
        self.llm_call_count = 0  # Track LLM calls for periodic cleanup
        
        # Memory watchdog (proactive crash prevention) - FROZEN MEMORY-SAFE SETTINGS  
        self._memory_threshold_percent = FROZEN_MEMORY_THRESHOLD_PERCENT  # ⚠️ FROZEN: Do not modify
        try:
            import psutil
            self.psutil_available = True
            logger.info("Memory watchdog enabled (psutil available)")
        except ImportError:
            self.psutil_available = False
            logger.warning("psutil not available, memory watchdog disabled (install with: pip install psutil)")
        
        # Initialize LLM analyzer
        self.llm_analyzer = None
        self.fast_llm_analyzer = None  # Fast-mode LLM for market scanning
        self.llm_state_worker = None  # Decoupled LLM state worker
        self.init_llm_analyzer()
        
        # Start LLM State Worker if initialized
        if self.llm_state_worker:
            self.llm_state_worker.start()
            logger.info("LLM State Worker started in background")
        
        # Initialize Trade Queue System (Event-Driven Architecture)
        self.trade_queue_system = None
        if self.llm_analyzer:
            try:
                # Define execution callback for approved trades
                def execution_callback(trade):
                    """Execute approved trade from queue."""
                    return self._execute_queued_trade(trade)
                
                self.trade_queue_system = TradeQueueSystem(self.llm_analyzer, execution_callback)
                logger.info("Trade Queue System initialized (Event-Driven Architecture)")
            except Exception as e:
                logger.error(f"Error initializing Trade Queue System: {e}")
                self.trade_queue_system = None

        # Load instruments and dynamically pick nearest expiry
        self.instruments = self._load_instruments()
        
        # Initialize Trade Manager (NEW - for trade management)
        max_concurrent = self.config.get("max_concurrent_trades", 2)
        self.trade_manager = TradeManager(self.kite_client, self.llm_analyzer, max_concurrent)
        
        # Initialize Expiry Manager (automatic expiry switching)
        self.expiry_manager = ExpiryManager(cutoff_hour=15, cutoff_minute=20)
        logger.info("Expiry Manager initialized for automatic expiry switching")
        
        # Callback for trade completion (to notify Market Analyzer)
        self.trade_completion_callback = None  # Function to call when trade completes
        
        # Duplicate trade detection cache
        self.recently_found_trades = {}  # trade_signature -> timestamp
        self.duplicate_trade_timeout = 300  # 5 minutes - consider same trade after 5 minutes
        
        # Anti-Whipsaw Cool-Down Filter (SL hit tracking)
        self.sl_cooldown_cache = {}  # symbol -> timestamp when SL was hit
        self.sl_cooldown_minutes = 30  # 30-minute cooldown after SL hit
        
        # Trade statistics for debugging
        self.trade_stats = {
            'total_found': 0,
            'duplicates_skipped': 0,
            'hard_filter_rejected': 0,
            'capacity_rejected': 0,
            'cooldown_rejected': 0,
            'llm_rejected': 0,
            'llm_approved': 0,
            'added_to_manager': 0
        }
        
        # ACTIVE TRADE STATE (NEW - for proper trade binding)
        self.active_trades = []  # List of locked trades (multi-trade capability)
        self.active_trade = None  # Legacy - for backward compatibility
        self.active_trade_id = None  # Legacy - for backward compatibility
        self.trade_lock_time = 0  # When the trade was locked
        self.last_scan_time = 0  # When the last scan was performed
        self.completed_trades = []  # History of completed trades

        logger.info("Clean Trading Bot initialized")
        logger.info(f"Trading Universe: {self.watchlist}")
        logger.info(f"Trade Manager: Max concurrent trades = {max_concurrent}")
        logger.info(f"Duplicate detection: Enabled (timeout: {self.duplicate_trade_timeout}s)")
        
        # ⚠️ Validate frozen memory-safe settings on initialization
        self._validate_frozen_settings()
    
    def get_option_symbol(self, symbol, strike, direction):
        """
        Generate proper Zerodha option symbol format with robust validation.
        
        Args:
            symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            strike: Strike price
            direction: CALL or PUT
            
        Returns:
            Zerodha option symbol (e.g., NFO:NIFTY26JUN23300CE) or None if invalid
        """
        try:
            # Validate and clean inputs
            if not symbol or not isinstance(symbol, str):
                logger.error(f"Invalid symbol: {symbol}")
                return None
                
            if not strike or not isinstance(strike, (int, float)):
                logger.error(f"Invalid strike: {strike}")
                return None
                
            if not direction or direction not in ["CALL", "PUT"]:
                logger.error(f"Invalid direction: {direction}")
                return None
            
            # Clean strike properly
            strike = int(float(strike))
            
            # Validate strike range (prevent obviously invalid strikes)
            if strike <= 0 or strike > 100000:
                logger.error(f"Strike price out of valid range: {strike}")
                return None
            
            # CRITICAL FIX: Hardcode expiry for now to avoid corruption
            expiry = "26JUN"  # TODO: Auto-detect later
            
            # Fix option type
            opt_type = "CE" if direction == "CALL" else "PE"
            
            # Construct symbol with validation
            full_symbol = f"NFO:{symbol}{expiry}{strike}{opt_type}"
            
            # Validate the final format matches expected pattern
            # Expected format: NFO:SYMBOLYYMONDDSTRIKECE/PE
            import re
            pattern = r'^NFO:[A-Z]{3,}\d{2}[A-Z]{3}\d+(CE|PE)$'
            if not re.match(pattern, full_symbol):
                logger.error(f"Generated symbol format validation failed: {full_symbol}")
                return None
            
            # DEBUG PRINTS
            logger.info(f"DEBUG INPUT: symbol={symbol}, strike={strike}, direction={direction}")
            logger.info(f"DEBUG EXPIRY: {expiry}")
            logger.info(f"DEBUG TYPE: {opt_type}")
            logger.info(f"FINAL SYMBOL: {full_symbol}")
            
            return full_symbol
            
        except Exception as e:
            logger.error(f"Critical error in get_option_symbol: {e}")
            return None
    
    def generate_manual_signal(self, trade):
        """
        Generate a manual trading signal using Mistral-7B for human execution.
        This replaces automated execution with AI-validated manual signals.
        
        Args:
            trade: Trade setup dictionary with all calculated levels and filter data
            
        Returns:
            Dictionary with signal status and formatted manual instructions
        """
        try:
            if not self.llm_analyzer:
                logger.warning("LLM analyzer not available for manual signal generation")
                return {"status": "NO_LLM", "signal": None}
            
            # Load capital manager for account risk metrics
            capital_manager = self.get_capital_manager()
            starting_capital = capital_manager.get('starting_virtual_capital', 30000)
            current_active = capital_manager.get('current_active_balance', 30000)
            consecutive_wins = capital_manager.get('consecutive_wins', 0)
            consecutive_losses = capital_manager.get('consecutive_losses', 0)
            
            # Calculate account drawdown percentage
            if starting_capital > 0:
                drawdown_percent = ((current_active - starting_capital) / starting_capital) * 100
            else:
                drawdown_percent = 0
            
            # Determine account stress level
            if drawdown_percent < -5:
                stress_level = "HIGH STRESS - Recent losses detected"
            elif drawdown_percent < -2:
                stress_level = "MODERATE STRESS - Slight drawdown"
            elif consecutive_losses > 0:
                stress_level = "RECOVERY MODE - Loss streak active"
            else:
                stress_level = "NORMAL - Account in healthy state"
            
            # Prepare context for manual signal generation with account risk metrics
            signal_context = {
                "account_metrics": {
                    "starting_virtual_capital": starting_capital,
                    "current_active_balance": current_active,
                    "investment_vault_balance": capital_manager.get('investment_vault_balance', 0),
                    "drawdown_percentage": round(drawdown_percent, 2),
                    "consecutive_wins": consecutive_wins,
                    "consecutive_losses": consecutive_losses,
                    "current_session_lots": capital_manager.get('current_session_lots', 1),
                    "stress_level": stress_level
                },
                "trade_setup": {
                    "direction": trade.get("direction", ""),
                    "strike": trade.get("strike", 0),
                    "entry": trade.get("entry", 0),
                    "target": trade.get("target", 0),
                    "stoploss": trade.get("stoploss", 0),
                    "symbol": trade.get("symbol", ""),
                    "spot": trade.get("spot", 0)
                },
                "filter_analysis": {
                    "ema_trend": trade.get("ema_trend", "UNKNOWN"),
                    "straddle_deviation": trade.get("straddle_deviation", 0),
                    "straddle_status": trade.get("straddle_status", "UNKNOWN"),
                    "blended_vwap": trade.get("blended_vwap", 0),
                    "straddle_price": trade.get("straddle_price", 0)
                }
            }
            
            logger.info(f"🤖 Generating manual signal for {trade.get('symbol', '')} {trade.get('direction', '')}")
            logger.info(f"📊 Account Metrics: {stress_level} | Drawdown: {drawdown_percent:.2f}% | Win Streak: {consecutive_wins}")
            
            # Use the new manual signal prompt
            def get_manual_signal():
                if hasattr(self.llm_analyzer, 'analyze_entry_signal'):
                    # Use existing method but with new prompt context
                    return self.llm_analyzer.analyze_entry_signal(signal_context)
                else:
                    logger.error("LLM analyzer has no compatible method for manual signals")
                    return None
            
            # Call LLM with timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(get_manual_signal)
                try:
                    manual_signal = future.result(timeout=15)
                except concurrent.futures.TimeoutError:
                    logger.error("Manual signal generation timed out after 15 seconds")
                    return {"status": "TIMEOUT", "signal": None}
            
            if manual_signal:
                # Parse the plaintext signal
                signal_text = str(manual_signal).strip()
                
                # Determine signal status
                if "APPROVED" in signal_text:
                    status = "APPROVED"
                    logger.info(f"✅ MANUAL SIGNAL APPROVED: {trade.get('symbol', '')}")
                elif "REJECTED" in signal_text:
                    status = "REJECTED"
                    logger.info(f"❌ MANUAL SIGNAL REJECTED: {trade.get('symbol', '')}")
                else:
                    status = "UNCLEAR"
                    logger.warning(f"⚠️ UNCLEAR MANUAL SIGNAL FORMAT")
                
                return {
                    "status": status,
                    "signal": signal_text,
                    "trade_id": trade.get("trade_id", ""),
                    "timestamp": time.time(),
                    "account_metrics": signal_context["account_metrics"]
                }
            else:
                return {"status": "NO_SIGNAL", "signal": None}
                
        except Exception as e:
            logger.error(f"Error generating manual signal: {e}")
            return {"status": "ERROR", "signal": None}
    
    def estimate_option_price(self, spot, strike, direction):
        """
        Advanced option premium estimation using intrinsic + dynamic time value.
        Handles ITM/OTM behavior realistically.
        
        Args:
            spot: Current spot price
            strike: Strike price
            direction: CALL or PUT
            
        Returns:
            Estimated option premium (closer to real market)
        """
        spot = float(spot)
        strike = float(strike)
        
        # Intrinsic value (real value if option exercised now)
        if direction == "CALL":
            intrinsic = max(0, spot - strike)
        else:  # PUT
            intrinsic = max(0, strike - spot)
        
        # Distance from ATM (determines time value)
        distance = abs(spot - strike)
        
        # Dynamic time value based on distance from ATM
        # ATM options have highest time value, OTM have lower
        if distance < 50:
            # ATM - highest time value
            time_value = spot * 0.003
        elif distance < 100:
            # Near ATM - moderate time value
            time_value = spot * 0.002
        elif distance < 200:
            # Slightly OTM - lower time value
            time_value = spot * 0.0015
        else:
            # Deep OTM - minimal time value
            time_value = spot * 0.001
        
        # ITM boost (deep ITM options have higher premiums due to volatility)
        if intrinsic > 0:
            # Add volatility premium for ITM options
            time_value *= 2.0  # ITM options have higher time value
        
        # Total premium = intrinsic + time value
        premium = intrinsic + time_value
        
        return round(premium, 2)
    
    def estimate_levels(self, entry):
        """
        Quick estimation of target and stoploss based on entry.
        
        Args:
            entry: Entry price
            
        Returns:
            Tuple of (target, stoploss)
        """
        # Simple but effective: 1:1.5 risk-reward ratio
        target = round(entry * 1.5, 2)   # 50% profit target
        stoploss = round(entry * 0.9, 2) # 10% stoploss
        
        return target, stoploss
    
    def get_real_option_price(self, symbol, strike, direction):
        """
        Get real option LTP from Kite Connect (not formula-based).
        
        Args:
            symbol: Underlying symbol
            strike: Strike price
            direction: CALL or PUT
            
        Returns:
            Current option price from market, or None if not available
        """
        # DEMO MODE: Use fake data from simulator
        if self.demo_simulator:
            logger.info(f"DEMO MODE: Getting fake option price for {symbol} {strike} {direction}")
            price = self.demo_simulator.get_option_price(symbol, strike, direction)
            logger.info(f"DEMO MODE: Option price = {price}")
            return price
        
        # LIVE MODE: Use real Kite API with instrument tokens
        try:
            # Load option token mapping
            try:
                with open('option_token_map.json', 'r') as f:
                    option_token_map = json.load(f)
            except FileNotFoundError:
                logger.error("option_token_map.json not found. Run fetch_nfo_instruments.py first.")
                return None

            # Create option key for lookup (convert CALL/PUT to CE/PE)
            direction_formatted = "CE" if direction == "CALL" else "PE"
            option_key = f"{symbol}{int(strike)}{direction_formatted}"

            # Look up instrument token
            if option_key not in option_token_map:
                logger.warning(f"Option {option_key} not found in token map")
                return None

            instrument_token = option_token_map[option_key]['instrument_token']
            trading_symbol = option_token_map[option_key]['trading_symbol']

            logger.info(f"Fetching LTP for: {trading_symbol} (Token: {instrument_token})")

            # Try to get LTP from Kite using instrument token
            ltp_response = self.kite_client.get_ltp([instrument_token])

            logger.info(f"LTP response: {ltp_response}")

            if ltp_response and instrument_token in ltp_response:
                price_data = ltp_response[instrument_token]

                # Handle both dict and int response formats
                if isinstance(price_data, dict):
                    price = price_data.get('last_price', 0)
                else:
                    price = price_data  # Direct integer response

                logger.info(f"Got real LTP: {price} for {trading_symbol}")
                return price
            else:
                logger.warning(f"Could not get LTP for {trading_symbol}, falling back to formula")
                return None
        except Exception as e:
            logger.error(f"Error getting real option price: {e}")
            return None
    
    def set_trade_completion_callback(self, callback):
        """
        Set callback function to be called when a trade completes.
        
        Args:
            callback: Function to call when trade completes
        """
        self.trade_completion_callback = callback
        self.trade_manager.trade_completion_callback = callback
        logger.info("Trade completion callback registered")
    
    def on_trade_completed(self, trade_id, trade):
        """
        Callback when a trade completes.
        
        Args:
            trade_id: Trade identifier
            trade: Trade data dictionary
        """
        logger.info(f"🎯 Trade {trade_id} completed")
    
    def _generate_trade_signature(self, trade):
        """
        Generate a unique signature for a trade to detect duplicates.
        
        Args:
            trade: Trade dictionary
        
        Returns:
            String signature for the trade
        """
        # Create signature based on key trade parameters
        symbol = trade.get('symbol', '').upper()
        direction = trade.get('direction', '').upper()
        strike = trade.get('strike', 0)
        spot = trade.get('spot', 0)
        
        # Round spot to nearest 50 points to group similar trades
        spot_rounded = round(spot / 50) * 50
        
        signature = f"{symbol}_{direction}_{strike}_{spot_rounded}"
        return signature
    
    def _is_duplicate_trade(self, trade):
        """
        Check if a trade is a duplicate of recently found trades.
        
        Args:
            trade: Trade dictionary
        
        Returns:
            True if duplicate, False otherwise
        """
        signature = self._generate_trade_signature(trade)
        current_time = time.time()
        
        # Check if this trade was recently found
        if signature in self.recently_found_trades:
            last_found_time = self.recently_found_trades[signature]
            time_since = current_time - last_found_time
            
            if time_since < self.duplicate_trade_timeout:
                logger.info(f"🔄 Duplicate trade detected: {signature} (found {time_since:.0f}s ago, skipping)")
                return True
        
        # Add to recently found trades
        self.recently_found_trades[signature] = current_time
        
        # Clean up old entries (older than timeout)
        self._cleanup_duplicate_cache()
        
        return False
    
    def _cleanup_duplicate_cache(self):
        """Clean up old entries from the duplicate detection cache."""
        current_time = time.time()
        signatures_to_remove = []
        
        for signature, timestamp in self.recently_found_trades.items():
            if current_time - timestamp > self.duplicate_trade_timeout:
                signatures_to_remove.append(signature)
        
        for signature in signatures_to_remove:
            del self.recently_found_trades[signature]
        
        if signatures_to_remove:
            logger.debug(f"Cleaned up {len(signatures_to_remove)} old trade signatures from cache")
    
    def _validate_frozen_settings(self):
        """
        Validate that frozen memory-safe settings are correct.
        This method enforces the permanent memory-safe configuration.
        """
        # Check that all frozen settings are set to their correct values
        errors = []
        
        if self._llm_cooldown_seconds != FROZEN_LLM_COOLDOWN_SECONDS:
            errors.append(f"LLM cooldown must be {FROZEN_LLM_COOLDOWN_SECONDS}s (current: {self._llm_cooldown_seconds}s)")
        
        if self._memory_threshold_percent != FROZEN_MEMORY_THRESHOLD_PERCENT:
            errors.append(f"Memory threshold must be {FROZEN_MEMORY_THRESHOLD_PERCENT}% (current: {self._memory_threshold_percent}%)")
        
        if errors:
            error_msg = "⚠️ FROZEN SETTINGS VIOLATION:\n" + "\n".join(errors)
            logger.error(error_msg)
            raise ValueError(error_msg + "\nThese settings are PERMANENTLY locked to prevent memory crashes.")
        
        logger.info("✓ All frozen memory-safe settings validated and locked")
    
    @property
    def llm_cooldown_seconds(self):
        """Getter for frozen LLM cooldown setting."""
        return self._llm_cooldown_seconds
    
    @llm_cooldown_seconds.setter
    def llm_cooldown_seconds(self, value):
        """Prevent modification of frozen LLM cooldown setting."""
        raise ValueError(
            f"⚠️ SETTING LOCKED: llm_cooldown_seconds is FROZEN at {FROZEN_LLM_COOLDOWN_SECONDS}s. "
            f"Cannot change to {value}s. "
            f"This setting is permanently locked to prevent memory crashes."
        )
    
    @property
    def memory_threshold_percent(self):
        """Getter for frozen memory threshold setting."""
        return self._memory_threshold_percent
    
    @memory_threshold_percent.setter
    def memory_threshold_percent(self, value):
        """Prevent modification of frozen memory threshold setting."""
        raise ValueError(
            f"⚠️ SETTING LOCKED: memory_threshold_percent is FROZEN at {FROZEN_MEMORY_THRESHOLD_PERCENT}%. "
            f"Cannot change to {value}%. "
            f"This setting is permanently locked to prevent memory crashes."
        )

    def _lock_frozen_setting(self, setting_name, current_value, frozen_value):
        """
        Prevent modification of frozen settings.
        Raises an error if someone tries to modify a frozen setting.
        """
        if current_value != frozen_value:
            raise ValueError(
                f"⚠️ SETTING LOCKED: {setting_name} is FROZEN at {frozen_value}. "
                f"Cannot change to {current_value}. "
                f"This setting is permanently locked to prevent memory crashes."
            )

    def is_symbol_allowed_to_trade(self, symbol):
        """
        Check if a symbol is currently serving a penalty for hitting Stop Loss.
        
        Args:
            symbol: The symbol to check
            
        Returns:
            True if symbol is allowed to trade, False if in cooldown
        """
        if symbol in self.sl_cooldown_cache:
            sl_hit_time = self.sl_cooldown_cache[symbol]
            time_passed = time.time() - sl_hit_time
            cooldown_seconds = self.sl_cooldown_minutes * 60
            
            if time_passed < cooldown_seconds:
                minutes_left = int((cooldown_seconds - time_passed) / 60)
                logger.warning(f"🛡️ [BLOCK] {symbol} hit SL recently. Cooling off for another {minutes_left} mins.")
                self.trade_stats['cooldown_rejected'] += 1
                return False
            else:
                # Cooldown expired, remove from cache
                del self.sl_cooldown_cache[symbol]
                logger.info(f"✅ {symbol} cooldown expired, now available for trading")
        
        return True

    def _load_instruments(self):
        """
        Load instruments from config.json and use Kite Connect instrument tokens.
        Returns instruments dict with instrument tokens for LTP API.
        """
        instruments = {}

        # Load instruments from config
        config_instruments = self.config.get("instruments", {})

        # Build instruments dict using instrument tokens from SYMBOL_MAP
        for symbol, data in config_instruments.items():
            symbol = symbol.upper()
            symbol_name = data.get("symbol", symbol)

            # Use instrument token from SYMBOL_MAP (required for Kite LTP API)
            instrument_token = SYMBOL_MAP.get(symbol, symbol)

            instruments[symbol] = {
                "name": symbol_name,
                "key": instrument_token,  # Instrument token for LTP API
                "lot_size": data.get("lot_size", 1),
                "tick_size": data.get("tick_size", 0.05)
            }

        logger.info(f"Loaded {len(instruments)} instruments from config with instrument tokens")
        return instruments

    def _load_watchlist_from_config(self):
        """
        Load watchlist dynamically from config instruments.
        Returns list of instrument symbols for trading.
        """
        watchlist = []
        try:
            # Load instruments from config
            instruments_config = self.config.get("instruments", {})
            
            # Extract symbol names from config
            for symbol in instruments_config.keys():
                watchlist.append(symbol.upper())
            
            logger.info(f"Loaded {len(watchlist)} instruments from config: {watchlist}")
            return watchlist
            
        except Exception as e:
            logger.error(f"Error loading watchlist from config: {e}")
            # Fallback to default watchlist
            logger.warning("Using fallback watchlist")
            return ["NIFTY", "BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"]

    def load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            self.access_token = self.config.get('access_token', '')
            self.api_key = self.config.get('api_key', '')
            
            # Config value (default setting from config file)
            self.paper_trading_default = self.config.get("paper_trading", False)
            # Runtime control (uses manual toggle, not config)
            self.paper_trading = self.paper_trading_enabled
            
            # Set up headers
            self.headers = {
                'accept': 'application/json',
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            logger.info("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return False
    
    def init_llm_analyzer(self):
        """Initialize LLM analyzer from config - supports Ollama and Gemini"""
        try:
            llm_provider = self.config.get("llm_provider", "ollama")
            logger.info(f"LLM Provider: {llm_provider}")

            if llm_provider == "gemini":
                gemini_config = self.config.get("gemini", {})
                gemini_enabled = gemini_config.get("enabled", False)

                if gemini_enabled:
                    api_key = gemini_config.get("api_key", "")
                    default_model = gemini_config.get("default_model", "gemini-1.5-flash")
                    trading_mode = gemini_config.get("trading_mode", "moderate")

                    if not api_key:
                        logger.warning("Gemini enabled but no API key provided")
                        self.llm_analyzer = None
                        self.fast_llm_analyzer = None
                        return

                    self.llm_analyzer = GeminiIntegration(
                        api_key=api_key,
                        model_name=default_model
                    )
                    logger.info(f"LLM analyzer initialized: Gemini model={default_model}, mode={trading_mode}")
                else:
                    logger.info("Gemini disabled in config, using fallback logic")
                    self.llm_analyzer = None
                    self.fast_llm_analyzer = None
                    self.llm_state_worker = None

            elif llm_provider == "ollama":
                ollama_config = self.config.get("ollama", {})
                ollama_enabled = ollama_config.get("enabled", False)

                if ollama_enabled:
                    ollama_url = ollama_config.get("base_url", "http://localhost:11434")
                    default_model = ollama_config.get("default_model", "qwen2:7b")
                    trading_mode = ollama_config.get("trading_mode", "moderate")

                    self.llm_analyzer = LLMMarketAnalyzer(
                        provider="ollama",
                        ollama_url=ollama_url,
                        model=default_model,
                        mode=trading_mode
                    )
                    logger.info(f"LLM analyzer initialized: Ollama model={default_model}, mode={trading_mode}")
                    
                    # Create fast-mode LLM analyzer for market scanning (optimized for speed)
                    self.fast_llm_analyzer = LLMMarketAnalyzer(
                        provider="ollama",
                        ollama_url=ollama_url,
                        model=default_model,
                        mode=trading_mode,
                        fast_mode=True  # Enable fast mode for quick validation
                    )
                    logger.info(f"Fast LLM analyzer initialized for market scanning")

            elif llm_provider == "airllm":
                airllm_config = self.config.get("airllm", {})
                airllm_enabled = airllm_config.get("enabled", False)

                if airllm_enabled:
                    model_path = airllm_config.get("model_path", "garage-bAInd/Platypus2-70B-instruct")
                    trading_mode = airllm_config.get("trading_mode", "moderate")
                    fast_mode = airllm_config.get("fast_mode", True)

                    self.llm_analyzer = LLMMarketAnalyzer(
                        provider="airllm",
                        model=model_path,
                        mode=trading_mode,
                        fast_mode=fast_mode,
                        airllm_config=airllm_config
                    )
                    logger.info(f"LLM analyzer initialized: AirLLM model={model_path}, mode={trading_mode}")
                    
                    # Create fast-mode LLM analyzer for market scanning (optimized for speed)
                    self.fast_llm_analyzer = LLMMarketAnalyzer(
                        provider="airllm",
                        model=model_path,
                        mode=trading_mode,
                        fast_mode=True,
                        airllm_config=airllm_config
                    )
                    logger.info(f"Fast LLM analyzer initialized for market scanning")
                    
                    # Initialize LLM State Worker (Decoupled Execution Pipeline)
                    if self.llm_analyzer:
                        try:
                            self.llm_state_worker = LLMStateWorker(self.llm_analyzer, update_interval=300)
                            logger.info("LLM State Worker initialized (Decoupled Execution Pipeline)")
                        except Exception as e:
                            logger.error(f"Error initializing LLM State Worker: {e}")
                            self.llm_state_worker = None
                    else:
                        self.llm_state_worker = None
                else:
                    logger.info("Ollama disabled in config, using fallback logic")
                    self.llm_analyzer = None
                    self.fast_llm_analyzer = None
                    self.llm_state_worker = None

            else:
                logger.warning(f"Unknown LLM provider: {llm_provider}, using fallback logic")
                self.llm_analyzer = None
                self.llm_state_worker = None

        except Exception as e:
            logger.error(f"Error initializing LLM analyzer: {e}")
            logger.info("Will use fallback trading logic")
            self.llm_analyzer = None
    
    def get_live_quotes(self, instrument_keys):
        """Get live market data for instruments using Kite Connect SDK"""
        if self.paper_trading:
            # Return mock data for paper trading with realistic prices and variation
            import random
            mock_data = {}
            for key in instrument_keys:
                if '256265' in key or 'NIFTY' in str(key).upper():
                    base_price = 23600
                    variation = random.randint(-50, 50)
                    mock_data[key] = {'ltp': base_price + variation}
                elif '260105' in key or 'BANKNIFTY' in str(key).upper():
                    base_price = 48000
                    variation = random.randint(-100, 100)
                    mock_data[key] = {'ltp': base_price + variation}
                else:
                    base_price = 2500
                    variation = random.randint(-100, 100)
                    mock_data[key] = {'ltp': base_price + variation}
                logger.info(f"MOCK DATA for {key}: {mock_data[key]}")
            return mock_data

        # Use Kite Connect SDK for live data
        try:
            # Instrument keys are now instrument tokens (strings or integers)
            logger.info(f"Fetching LTP for instrument tokens: {instrument_keys}")

            # Get quotes using Kite Connect SDK
            ltp_data = self.kite_client.get_ltp(instrument_keys)

            logger.info(f"LTP DATA from Kite: {ltp_data}")

            if ltp_data:
                # Convert Kite response format to expected format
                result = {}
                for key in instrument_keys:
                    # Convert key to string for consistent lookup
                    key_str = str(key)
                    if key_str in ltp_data:
                        result[key] = {
                            'ltp': ltp_data[key_str],
                            'last_price': ltp_data[key_str]
                        }
                    else:
                        logger.warning(f"No data found for instrument token {key_str} in LTP data")
                logger.info(f"KITE QUOTES (converted): {result}")
                return result
            else:
                logger.error("No LTP data received from Kite")
                return {}
        except Exception as e:
            logger.error(f"Error fetching live quotes: {e}")
            return {}
    
    def get_option_chain(self, symbol, spot_price):
        """
        Fetch real option chain data for a given symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "BANKNIFTY")
            spot_price: Current spot price for strike range calculation
            
        Returns:
            List of option data with strike, call_oi, put_oi
        """
        try:
            logger.info(f"Fetching option chain for {symbol} at spot {spot_price}")
            
            # Try to fetch real option chain with OI from Kite
            if hasattr(self.kite_client, 'get_option_chain_oi'):
                option_chain = self.kite_client.get_option_chain_oi(symbol, spot_price)
                
                if option_chain and len(option_chain) > 0:
                    logger.info(f"Successfully fetched real option chain with {len(option_chain)} strikes")
                    return option_chain
                else:
                    logger.warning(f"Real option chain fetch failed or empty, using empty chain")
            
            # Fallback to empty chain if real fetch fails
            logger.info(f"Using empty option chain for {symbol} (legacy file - not used by active system)")
            option_chain = []
            return option_chain
            
        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            # Fallback to empty chain
            logger.info(f"Using empty option chain as fallback (legacy file - not used by active system)")
            return []
    
    def scan_market(self, instrument_key, instrument_name):
        """
        Scan market for trading opportunity using OptionStar rule-based engine.
        Returns trade data if opportunity found, None otherwise.
        """
        try:
            # Get current price
            quotes = self.get_live_quotes([instrument_key])
            if not quotes or instrument_key not in quotes:
                return None

            # Handle different response formats
            if 'last_price' in quotes[instrument_key]:
                current_price = quotes[instrument_key].get('last_price', 0)
                logger.info(f"LTP from last_price: {current_price}")
            else:
                current_price = quotes[instrument_key].get('ltp', 0)
                logger.info(f"LTP from ltp: {current_price}")

            logger.info(f"EXTRACTED CURRENT PRICE: {current_price}")

            if current_price == 0:
                return None

            # Store price history for VWAP calculation
            if instrument_key not in self.price_history:
                self.price_history[instrument_key] = []

            self.price_history[instrument_key].append(current_price)

            # Keep only last 20 prices for VWAP calculation
            if len(self.price_history[instrument_key]) > 20:
                self.price_history[instrument_key] = self.price_history[instrument_key][-20:]

            # Need minimum history for VWAP
            if len(self.price_history[instrument_key]) < 5:
                return None

            # Calculate VWAP (simplified - using price average as proxy)
            price_history = self.price_history[instrument_key]
            vwap = sum(price_history) / len(price_history)

            # Generate option chain data (using real data when available)
            option_chain = self.get_option_chain(instrument_name, current_price)

            # Use OptionStar for trade idea generation
            # If we have a pre-selected strike from 9:15 analysis, use it
            if instrument_name in self.selected_strikes:
                pre_selected = self.selected_strikes[instrument_name]
                logger.info(f"Using pre-selected strike from 9:15 analysis: {pre_selected['strike']} {pre_selected['direction']}")
                
                # Create trade setup from pre-selected data
                optionstar_trade = {
                    "direction": pre_selected['direction'],
                    "strike": pre_selected['strike'],
                    "spot": current_price,
                    "vwap": vwap,
                    "support": pre_selected['support'],
                    "resistance": pre_selected['resistance'],
                    "reason": f"Pre-selected at 9:15: {pre_selected['reason']}"
                }
            else:
                # Generate new trade setup using OptionStar
                optionstar_trade = generate_trade(current_price, vwap, option_chain, symbol)

            if not optionstar_trade:
                logger.info("No OptionStar setup generated")
                return None

            logger.info(f"OptionStar Trade Setup: {optionstar_trade}")

            # Build enhanced trade data combining OptionStar setup with market context
            trade = {
                # OptionStar fields
                "direction": optionstar_trade['direction'],
                "strike": optionstar_trade['strike'],
                "vwap": optionstar_trade['vwap'],
                "support": optionstar_trade['support'],
                "resistance": optionstar_trade['resistance'],
                "optionstar_reason": optionstar_trade['reason'],
                
                # Market context fields
                "spot": current_price,
                "symbol": instrument_name,
                "price_change": f"{((current_price - price_history[0]) / price_history[0] * 100):.2f}%" if len(price_history) > 0 else "0%",
                "timestamp": datetime.now().isoformat(),
                
                # Additional context for LLM
                "price_history_count": len(price_history),
                "current_vs_vwap": current_price - vwap
            }

            logger.info(f"FINAL TRADE DATA: {trade}")

            return trade

        except Exception as e:
            logger.error(f"Error scanning market: {e}")
            return None
    
    def calculate_next_lot_size(self, capital_metadata):
        """
        Handles systematic compounding based on wins, and protects
        the margin strictly during consecutive losses.
        
        Args:
            capital_metadata: Dictionary with consecutive_wins, consecutive_losses
            
        Returns:
            Integer lot size (1, 2, or 3)
        """
        consecutive_losses = capital_metadata.get('consecutive_losses', 0)
        consecutive_wins = capital_metadata.get('consecutive_wins', 0)
        base_lots = 1
        
        # LOSS RECOVERY SHIELD
        if consecutive_losses > 0:
            # If we made a loss, drop to the absolute minimum baseline (1 Lot) 
            # to protect the main margin pool until a win breaks the streak.
            logger.warning(" [DRAWDOWN PROTECTOR] Forcing minimum 1-Lot baseline to preserve margin.")
            return base_lots

        # COMPOUNDING WIN STREAK
        if consecutive_wins == 1:
            logger.info(" [WIN STREAK ACTIVATED] Scaling position size to 2 Lots.")
            return 2
        elif consecutive_wins >= 2:
            logger.info(" [MAX MOMENTUM ACTIVATED] Scaling position size to 3 Lots.")
            return 3  # Hard ceiling cap to prevent catastrophic over-leverage
            
        return base_lots
    
    def process_profit_split(self, profit_amount, capital_metadata):
        """
        Implements the 50/50 Profit Split on Take Profit hits.
        
        Args:
            profit_amount: Profit from winning trade
            capital_metadata: Current capital manager state
            
        Returns:
            Updated capital_metadata dictionary
        """
        if profit_amount <= 0:
            return capital_metadata
            
        # 50% to active balance (for compounding)
        active_share = profit_amount * 0.5
        # 50% to investment vault (locked savings)
        vault_share = profit_amount * 0.5
        
        # Update balances
        capital_metadata['current_active_balance'] += active_share
        capital_metadata['investment_vault_balance'] += vault_share
        
        logger.info(f" [PROFIT SPLIT] INR {profit_amount:.2f} → Active: +INR {active_share:.2f} | Vault: +INR {vault_share:.2f}")
        logger.info(f" [UPDATED BALANCES] Active: INR {capital_metadata['current_active_balance']:.2f} | Vault: INR {capital_metadata['investment_vault_balance']:.2f}")
        
        # CRITICAL: Save to disk immediately for next-day persistence
        self.save_capital_manager(capital_metadata)
        logger.info(" [PERSISTENCE] Capital state saved to active_trades.json")
        
        return capital_metadata
    
    def process_loss(self, loss_amount, capital_metadata):
        """
        Processes loss impact on capital and resets lot sizing.
        
        Args:
            loss_amount: Loss from losing trade
            capital_metadata: Current capital manager state
            
        Returns:
            Updated capital_metadata dictionary
        """
        if loss_amount <= 0:
            return capital_metadata
            
        # Subtract full loss from active balance
        capital_metadata['current_active_balance'] -= loss_amount
        # Increment consecutive losses
        capital_metadata['consecutive_losses'] += 1
        # Reset consecutive wins
        capital_metadata['consecutive_wins'] = 0
        # Reset lot size to baseline
        capital_metadata['current_session_lots'] = 1
        
        logger.warning(f" [LOSS PROCESSED] INR {loss_amount:.2f} deducted from active balance")
        logger.warning(f" [DRAWDOWN PROTECTOR] Consecutive losses: {capital_metadata['consecutive_losses']} | Lot size reset to 1")
        
        # CRITICAL: Save to disk immediately for next-day persistence
        self.save_capital_manager(capital_metadata)
        logger.info(" [PERSISTENCE] Capital state saved to active_trades.json")
        
        return capital_metadata
    
    def process_win(self, capital_metadata):
        """
        Updates win streak tracking after a winning trade.
        
        Args:
            capital_metadata: Current capital manager state
            
        Returns:
            Updated capital_metadata dictionary
        """
        # Increment consecutive wins
        capital_metadata['consecutive_wins'] += 1
        # Reset consecutive losses
        capital_metadata['consecutive_losses'] = 0
        # Update lot size based on new win streak
        capital_metadata['current_session_lots'] = self.calculate_next_lot_size(capital_metadata)
        
        logger.info(f" [WIN STREAK UPDATE] Consecutive wins: {capital_metadata['consecutive_wins']} | New lot size: {capital_metadata['current_session_lots']}")
        
        # CRITICAL: Save to disk immediately for next-day persistence
        self.save_capital_manager(capital_metadata)
        logger.info(" [PERSISTENCE] Capital state saved to active_trades.json")
        
        return capital_metadata
    
    def get_capital_manager(self):
        """
        Load capital manager state from active_trades.json.
        
        Returns:
            Dictionary with capital_manager data
        """
        try:
            manifest = load_trade_manifest()
            return manifest.get('capital_manager', {})
        except Exception as e:
            logger.error(f"Error loading capital manager: {e}")
            return {}
    
    def get_lot_size_for_instrument(self, instrument):
        """
        Get dynamic lot size for a specific instrument from capital_manager.
        
        Args:
            instrument: Instrument symbol (e.g., 'NIFTY', 'SBIN')
            
        Returns:
            Integer lot size for the instrument
        """
        try:
            capital_manager = self.get_capital_manager()
            lot_sizes = capital_manager.get('lot_sizes', {})
            
            # Get lot size from dynamic mapping
            lot_size = lot_sizes.get(instrument)
            
            if lot_size:
                logger.info(f" [DYNAMIC LOT SIZE] {instrument}: {lot_size} units")
                return lot_size
            else:
                # Fallback to config.json if not in capital_manager
                config_lot_size = self.config.get('instruments', {}).get(instrument, {}).get('lot_size', 1)
                logger.warning(f" [LOT SIZE FALLBACK] {instrument}: {config_lot_size} units (from config)")
                return config_lot_size
                
        except Exception as e:
            logger.error(f"Error getting lot size for {instrument}: {e}")
            return 1  # Safe fallback
    
    def save_capital_manager(self, capital_metadata):
        """
        Save updated capital manager state to active_trades.json.
        Uses direct atomic file write to avoid trade manifest logic.
        
        Args:
            capital_metadata: Updated capital manager dictionary
        """
        try:
            # Load current manifest
            manifest = load_trade_manifest()
            
            # Update capital_manager section
            manifest['capital_manager'] = capital_metadata
            
            # Direct atomic write to file (bypass trade manifest logic)
            with file_lock:
                temp_file = TRADE_MANIFEST_PATH + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                os.replace(temp_file, TRADE_MANIFEST_PATH)
            
            logger.info(" [CAPITAL MANAGER] State saved successfully")
        except Exception as e:
            logger.error(f"Error saving capital manager: {e}")
    
    def generate_eod_performance_report(self, save_to_file=True):
        """
        Generates comprehensive EOD performance report in markdown format.
        Triggers automatically at 3:30 PM IST or via manual --eod flag.
        
        Args:
            save_to_file: If True, saves report to logs directory
            
        Returns:
            String containing the complete markdown report
        """
        try:
            # Load current data
            manifest = load_trade_manifest()
            capital_manager = manifest.get('capital_manager', {})
            trades = manifest.get('trades', [])
            
            # Calculate performance metrics
            starting_capital = capital_manager.get('starting_virtual_capital', 30000)
            current_active = capital_manager.get('current_active_balance', 30000)
            vault_balance = capital_manager.get('investment_vault_balance', 0)
            consecutive_wins = capital_manager.get('consecutive_wins', 0)
            consecutive_losses = capital_manager.get('consecutive_losses', 0)
            current_lots = capital_manager.get('current_session_lots', 1)
            
            # Trade statistics
            total_trades = len(trades)
            wins = len([t for t in trades if t.get('status') == 'COMPLETED' and t.get('pnl', 0) > 0])
            losses = len([t for t in trades if t.get('status') == 'COMPLETED' and t.get('pnl', 0) < 0])
            active_trades = len([t for t in trades if t.get('status') == 'ACTIVE'])
            
            # Calculate total P&L
            total_pnl = sum([t.get('pnl', 0) for t in trades if t.get('status') == 'COMPLETED'])
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            
            # Generate markdown report
            report = []
            report.append("# 📊 END-OF-DAY PERFORMANCE REPORT")
            report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
            report.append("")
            
            # Capital Summary
            report.append("## 💰 CAPITAL SUMMARY")
            report.append(f"- **Starting Virtual Capital:** INR {starting_capital:.2f}")
            report.append(f"- **Current Active Balance:** INR {current_active:.2f}")
            report.append(f"- **Investment Vault Balance:** INR {vault_balance:.2f} (Locked Savings)")
            report.append(f"- **Total P&L:** INR {total_pnl:.2f} ({((total_pnl/starting_capital)*100):.2f}%)")
            report.append("")
            
            # Performance Metrics
            report.append("## 📈 PERFORMANCE METRICS")
            report.append(f"- **Total Trades:** {total_trades}")
            report.append(f"- **Wins:** {wins}")
            report.append(f"- **Losses:** {losses}")
            report.append(f"- **Active Trades:** {active_trades}")
            report.append(f"- **Win Rate:** {win_rate:.2f}%")
            report.append(f"- **Average P&L per Trade:** INR {(total_pnl/total_trades):.2f}" if total_trades > 0 else "- **Average P&L per Trade:** N/A")
            report.append("")
            
            # Risk Management
            report.append("## 🛡️ RISK MANAGEMENT")
            report.append(f"- **Consecutive Wins:** {consecutive_wins}")
            report.append(f"- **Consecutive Losses:** {consecutive_losses}")
            report.append(f"- **Current Session Lots:** {current_lots}")
            report.append(f"- **Lot Size (Nifty):** {capital_manager.get('nse_lot_size_nifty', 65)} units")
            report.append(f"- **Lot Size (Bank Nifty):** {capital_manager.get('nse_lot_size_banknifty', 30)} units")
            report.append("")
            
            # Trade History with AI Reasoning
            report.append("## 📋 TRADE HISTORY")
            report.append("")
            
            if trades:
                for i, trade in enumerate(trades, 1):
                    status = trade.get('status', 'UNKNOWN')
                    symbol = trade.get('underlying', 'N/A')
                    strike = trade.get('strike_price', 0)
                    option_type = trade.get('option_type', 'N/A')
                    pnl = trade.get('execution', {}).get('current_price', 0) - trade.get('execution', {}).get('entry_price', 0)
                    pnl_percent = trade.get('pnl_percentage', 0)
                    
                    report.append(f"### Trade {i}: {symbol} {strike} {option_type}")
                    report.append(f"- **Status:** {status}")
                    report.append(f"- **P&L:** INR {pnl:.2f} ({pnl_percent:.2f}%)")
                    
                    # Add AI reasoning if available
                    if 'ai_validation_note' in trade:
                        report.append(f"- **AI Validation:** {trade['ai_validation_note']}")
                    
                    report.append("")
            else:
                report.append("*No trades executed in this session*")
                report.append("")
            
            # System Status
            report.append("## ⚙️ SYSTEM STATUS")
            report.append("- **Straddle Volatility Filter:** Active")
            report.append("- **EMA Trend Filter:** Active (9/21 Crossover)")
            report.append("- **Mistral-7B Validation:** Active")
            report.append("- **Capital Management:** Active (50/50 Split)")
            report.append("")
            
            report.append("---")
            report.append("*Report generated by AI Paper Trading System*")
            
            # Join into single string
            report_text = "\n".join(report)
            
            # Save to file if requested
            if save_to_file:
                try:
                    logs_dir = os.path.join(os.path.dirname(TRADE_MANIFEST_PATH), "logs")
                    os.makedirs(logs_dir, exist_ok=True)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    report_filename = os.path.join(logs_dir, f"eod_report_{timestamp}.md")
                    
                    with open(report_filename, 'w', encoding='utf-8') as f:
                        f.write(report_text)
                    
                    logger.info(f" [EOD REPORT] Saved to {report_filename}")
                except Exception as e:
                    logger.error(f" [EOD REPORT] Failed to save file: {e}")
            
            return report_text
            
        except Exception as e:
            logger.error(f"Error generating EOD report: {e}")
            return f"Error generating EOD report: {str(e)}"
    
    def calculate_straddle_metrics(self, ce_ticks, pe_ticks):
        """
        Combines CE and PE live feeds to detect premium expansion or squeeze.
        Takes tick dictionaries from Kite WebSocket or LTP responses.
        
        Args:
            ce_ticks: Dictionary with CE option data (last_price, volume)
            pe_ticks: Dictionary with PE option data (last_price, volume)
            
        Returns:
            Dictionary with straddle_price, blended_vwap, deviation_percentage
        """
        try:
            # Validate input data structure
            if not ce_ticks or not pe_ticks:
                logger.error("Missing CE or PE tick data for straddle calculation")
                return None
                
            if 'last_price' not in ce_ticks or 'last_price' not in pe_ticks:
                logger.error("Missing last_price in tick data")
                return None
            
            # Extract prices with validation
            ce_price = float(ce_ticks['last_price'])
            pe_price = float(pe_ticks['last_price'])
            
            if ce_price <= 0 or pe_price <= 0:
                logger.error(f"Invalid option prices: CE={ce_price}, PE={pe_price}")
                return None
            
            # Combined Premium (The Straddle Price)
            straddle_price = ce_price + pe_price
            
            # Extract volumes with fallback to 0 if not available
            ce_volume = int(ce_ticks.get('volume', 0)) if 'volume' in ce_ticks else 0
            pe_volume = int(pe_ticks.get('volume', 0)) if 'volume' in pe_ticks else 0
            
            # Combined Traded Volume
            total_volume = ce_volume + pe_volume
            
            # Combined Value for blended VWAP tracking
            combined_value = (ce_price * ce_volume) + (pe_price * pe_volume)
            
            # Calculate blended VWAP (fallback to simple average if no volume data)
            if total_volume > 0:
                blended_vwap = combined_value / total_volume
            else:
                blended_vwap = straddle_price / 2  # Simple average fallback
            
            # Calculate deviation percentage
            if blended_vwap > 0:
                deviation_percentage = ((straddle_price - blended_vwap) / blended_vwap) * 100
            else:
                deviation_percentage = 0
            
            metrics = {
                "straddle_price": straddle_price,
                "blended_vwap": blended_vwap,
                "deviation_percentage": deviation_percentage,
                "ce_price": ce_price,
                "pe_price": pe_price,
                "total_volume": total_volume,
                "ce_volume": ce_volume,
                "pe_volume": pe_volume
            }
            
            logger.info(f"📊 Straddle Metrics: Price={straddle_price:.2f}, VWAP={blended_vwap:.2f}, Deviation={deviation_percentage:.2f}%")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Straddle math compilation error: {e}")
            return None
    
    def get_atm_strike(self, spot_price, symbol):
        """
        Calculate the At-The-Money (ATM) strike based on current spot price using option chain.
        Fetches real option chain from Zerodha and selects the closest available strike.
        Works automatically for all instruments in the watchlist.

        Args:
            spot_price: Current spot price of the underlying
            symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY, ICICIBANK)

        Returns:
            Integer ATM strike price from actual option chain, or None if option chain unavailable
        """
        try:
            spot = float(spot_price)

            # Load option token mapping to get available strikes
            try:
                with open('option_token_map.json', 'r') as f:
                    option_token_map = json.load(f)
            except FileNotFoundError:
                logger.error("❌ CRITICAL: option_token_map.json not found!")
                logger.error("❌ Run fetch_nfo_instruments.py to generate option chain mapping")
                logger.error("❌ Trade execution aborted - option chain required")
                return None

            # Filter strikes for the specific symbol
            symbol_strikes = []
            for key, value in option_token_map.items():
                if value['name'] == symbol:
                    symbol_strikes.append(value['strike'])

            if not symbol_strikes:
                logger.error(f"❌ CRITICAL: No strikes found for {symbol} in option chain!")
                logger.error(f"❌ Symbol {symbol} may not be available in current option chain")
                logger.error("❌ Trade execution aborted - no valid strikes available")
                logger.error("❌ This instrument will be skipped during trading")
                return None

            # Find the strike closest to spot price
            closest_strike = min(symbol_strikes, key=lambda x: abs(x - spot))

            logger.info(f"🎯 ATM Strike from Option Chain: {symbol} Spot={spot:.2f} → ATM={closest_strike}")
            logger.info(f"📊 Available strikes range: {min(symbol_strikes)} - {max(symbol_strikes)}")
            logger.info(f"📊 Total contracts available: {len(symbol_strikes)}")

            return int(closest_strike)

        except Exception as e:
            logger.error(f"❌ CRITICAL: Error getting ATM strike from option chain: {e}")
            logger.error("❌ Trade execution aborted - option chain error")
            return None
    
    def get_straddle_symbols(self, symbol, spot_price=None):
        """
        Generate CE and PE option symbols for the ATM straddle.
        
        Args:
            symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            spot_price: Current spot price (if None, will fetch from market)
            
        Returns:
            Dictionary with 'ce_symbol' and 'pe_symbol' for the ATM straddle
        """
        try:
            # Fetch spot price if not provided
            if spot_price is None:
                instrument_token = SYMBOL_MAP.get(symbol)
                if instrument_token:
                    ltp_data = self.kite_client.get_ltp([instrument_token])
                    if ltp_data and instrument_token in ltp_data:
                        spot_price = ltp_data[instrument_token]
                    else:
                        logger.error(f"Could not fetch spot price for {symbol}")
                        return None
                else:
                    logger.error(f"No instrument token for {symbol}")
                    return None
            
            # Calculate ATM strike
            atm_strike = self.get_atm_strike(spot_price, symbol)

            # Check if ATM strike calculation failed
            if atm_strike is None:
                logger.error("❌ CRITICAL: ATM strike calculation failed - trade execution aborted")
                return None

            # Generate CE and PE symbols
            ce_symbol = self.get_option_symbol(symbol, atm_strike, "CALL")
            pe_symbol = self.get_option_symbol(symbol, atm_strike, "PUT")

            if not ce_symbol or not pe_symbol:
                logger.error("Failed to generate straddle symbols")
                return None
            
            return {
                'symbol': symbol,
                'atm_strike': atm_strike,
                'spot_price': spot_price,
                'ce_symbol': ce_symbol,
                'pe_symbol': pe_symbol
            }
            
        except Exception as e:
            logger.error(f"Error generating straddle symbols: {e}")
            return None
    
    def verify_volatility_expansion(self, straddle_metrics, threshold=2.5):
        """
        Acts as Filter 5: Ensures we only buy when premiums are expanding out of a squeeze.
        
        Args:
            straddle_metrics: Dictionary from calculate_straddle_metrics()
            threshold: Percentage deviation above VWAP required to confirm expansion (default 2.5%)
            
        Returns:
            "CONFIRMED" if expansion detected, "NEUTRAL" if squeeze or insufficient data
        """
        if not straddle_metrics:
            logger.warning("No straddle metrics available for expansion verification")
            return "NEUTRAL"
        
        try:
            current_price = straddle_metrics["straddle_price"]
            vwap = straddle_metrics["blended_vwap"]
            deviation = straddle_metrics["deviation_percentage"]
            
            # SQUEEZE ZONE: Premium is flat or collapsing under average volume weight
            if current_price <= vwap:
                logger.info(f"🔒 [SQUEEZE] Straddle under VWAP by {abs(deviation):.2f}%. Rejecting execution to avoid IV decay.")
                return "NEUTRAL"
            
            # EXPANSION ZONE: Momentum spike confirmed
            if deviation >= threshold:
                logger.info(f"🚀 [EXPANSION] Volatility breakout confirmed! Deviation: {deviation:.2f}% above VWAP threshold {threshold}%")
                return "CONFIRMED"
            
            # NEUTRAL ZONE: Between squeeze and expansion
            logger.info(f"⏸️ [NEUTRAL] Straddle deviation {deviation:.2f}% below expansion threshold {threshold}%")
            return "NEUTRAL"
            
        except Exception as e:
            logger.error(f"Error in volatility expansion verification: {e}")
            return "NEUTRAL"
    
    def calculate_ema(self, prices, period):
        """
        Calculate Exponential Moving Average (EMA).
        
        Args:
            prices: List of closing prices
            period: EMA period (e.g., 9, 21)
        
        Returns:
            EMA value
        """
        if len(prices) < period:
            logger.warning(f"Not enough data points for EMA {period}: need {period}, have {len(prices)}")
            return None
        
        # Calculate initial SMA for first EMA value
        sma = sum(prices[:period]) / period
        
        # Calculate multiplier
        multiplier = 2 / (period + 1)
        
        # Calculate EMA
        ema = sma
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def get_ema_trend(self, symbol):
        """
        Get EMA trend for a symbol using 15-minute timeframe with robust error handling.
        Uses 9-period and 21-period EMAs with graceful degradation on data failures.
        
        Includes caching and fallback to previous day if insufficient data today.
        
        Args:
            symbol: Symbol name (e.g., "NIFTY", "BANKNIFTY")
        
        Returns:
            "BULLISH" if 9 EMA > 21 EMA
            "BEARISH" if 9 EMA < 21 EMA
            "NEUTRAL" if data unavailable or EMAs are equal
        """
        try:
            # Check cache first (5 minute cache to avoid API rate limits)
            cache_key = f"{symbol}_ema_trend"
            current_time = time.time()
            if hasattr(self, '_ema_cache') and cache_key in self._ema_cache:
                cached_data = self._ema_cache[cache_key]
                if current_time - cached_data['timestamp'] < 300:  # 5 minute cache
                    logger.info(f"[EMA CACHE] Using cached trend for {symbol}: {cached_data['trend']}")
                    return cached_data['trend']
            
            # Get instrument token for the symbol
            instrument_token = SYMBOL_MAP.get(symbol)
            if not instrument_token:
                logger.warning(f"No instrument token found for {symbol}")
                return "NEUTRAL"
            
            # Get today's date
            from datetime import datetime, timedelta
            today = datetime.now().date()
            from_date = today.strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")
            
            # Fetch 15-minute historical data for today
            # Need enough data for 21-period EMA (at least 21 candles)
            historical_data = self.kite_client.get_historical_data(
                instrument_token,
                "15minute",
                from_date,
                to_date
            )
            
            # Fallback: If today has insufficient data, fetch previous day too
            if not historical_data or len(historical_data) < 21:
                logger.warning(f"Insufficient data for {symbol} today, fetching previous day...")
                yesterday = today - timedelta(days=1)
                from_date = yesterday.strftime("%Y-%m-%d")
                
                # Fetch previous day's data
                prev_data = self.kite_client.get_historical_data(
                    instrument_token,
                    "15minute",
                    from_date,
                    from_date
                )
                
                if prev_data:
                    # Combine previous day's data with today's
                    historical_data = prev_data + (historical_data or [])
                    logger.info(f"Combined data: {len(historical_data)} candles")
            
            # CRITICAL: Graceful degradation with comprehensive checks
            if not historical_data or len(historical_data) < 21:
                logger.warning(f"Insufficient historical data for {symbol}: need 21 candles, got {len(historical_data) if historical_data else 0}")
                return "NEUTRAL"
            
            # Validate data structure before processing
            if not isinstance(historical_data, list):
                logger.error(f"Invalid historical data format for {symbol}: expected list, got {type(historical_data)}")
                return "NEUTRAL"
            
            # Extract closing prices with validation
            closing_prices = []
            for candle in historical_data[-50:]:  # Use last 50 candles to ensure fresh data
                if not isinstance(candle, dict) or 'close' not in candle:
                    logger.warning(f"Invalid candle format in historical data for {symbol}")
                    continue
                try:
                    close_price = float(candle['close'])
                    if close_price > 0:  # Validate price is positive
                        closing_prices.append(close_price)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid close price in candle for {symbol}: {e}")
                    continue
            
            # CRITICAL: Check if we have enough valid data points after validation
            if len(closing_prices) < 21:
                logger.warning(f"Insufficient valid closing prices for {symbol}: need 21, got {len(closing_prices)} after validation")
                return "NEUTRAL"
            
            # Calculate 9-period and 21-period EMAs
            ema_9 = self.calculate_ema(closing_prices, 9)
            ema_21 = self.calculate_ema(closing_prices, 21)
            
            if ema_9 is None or ema_21 is None:
                logger.warning(f"Could not calculate EMAs for {symbol}")
                return "NEUTRAL"
            
            # Determine trend
            if ema_9 > ema_21:
                trend = "BULLISH"
                logger.info(f"[EMA TREND] {symbol}: BULLISH (EMA9: {ema_9:.2f} > EMA21: {ema_21:.2f})")
            elif ema_9 < ema_21:
                trend = "BEARISH"
                logger.info(f"[EMA TREND] {symbol}: BEARISH (EMA9: {ema_9:.2f} < EMA21: {ema_21:.2f})")
            else:
                trend = "NEUTRAL"
                logger.info(f"[EMA TREND] {symbol}: NEUTRAL (EMA9: {ema_9:.2f} = EMA21: {ema_21:.2f})")
            
            # Cache the result
            if not hasattr(self, '_ema_cache'):
                self._ema_cache = {}
            self._ema_cache[cache_key] = {
                'trend': trend,
                'timestamp': current_time
            }
            
            return trend
            
        except Exception as e:
            logger.error(f"Error getting EMA trend for {symbol}: {e}")
            return "NEUTRAL"
    
    def apply_hard_filters(self, trade):
        """
        Apply hard filters before LLM evaluation.
        With OptionStar, most filtering is already done, so we keep minimal checks.
        Returns True if trade passes filters, False otherwise.
        """
        # OptionStar already does the main filtering, so we keep minimal checks
        # Filter 1: Ensure required OptionStar fields exist
        required_fields = ["direction", "strike", "spot", "vwap", "support", "resistance"]
        for field in required_fields:
            if field not in trade:
                logger.info(f"[FILTER] Trade rejected: Missing required field '{field}'")
                return False
        
        # Filter 2: Basic sanity check on strike vs spot
        strike = trade.get("strike", 0)
        spot = trade.get("spot", 0)
        if strike == 0 or spot == 0:
            logger.info(f"[FILTER] Trade rejected: Invalid strike or spot price")
            return False
        
        # Filter 3: Ensure strike is reasonable (within 500 points of spot)
        if abs(strike - spot) > 500:
            logger.info(f"[FILTER] Trade rejected: Strike too far from spot ({abs(strike - spot)} points)")
            return False
        
        # Filter 4: EMA Trend Filter (NEW - Critical for win rate improvement)
        # Only take CALL trades in BULLISH trend, PUT trades in BEARISH trend
        symbol = trade.get("symbol", "")
        direction = trade.get("direction", "")
        
        if symbol and direction:
            trend = self.get_ema_trend(symbol)
            
            if trend == "BULLISH" and direction == "PUT":
                logger.info(f"[FILTER] Trade rejected: {symbol} is BULLISH but trade is PUT (wrong direction)")
                return False
            elif trend == "BEARISH" and direction == "CALL":
                logger.info(f"[FILTER] Trade rejected: {symbol} is BEARISH but trade is CALL (wrong direction)")
                return False
            elif trend == "NEUTRAL":
                logger.info(f"[FILTER] Trade rejected: {symbol} trend is NEUTRAL (insufficient data)")
                return False
            else:
                # Trend matches direction - allow trade
                logger.info(f"[FILTER] EMA Trend check passed: {symbol} {trend} matches {direction} trade")
        
        # Filter 5: Straddle Volatility Expansion Filter (NEW - Institutional-grade timing)
        # Ensures we only enter when premiums are expanding out of a squeeze, avoiding IV decay
        if symbol:
            try:
                # Get ATM straddle symbols
                straddle_info = self.get_straddle_symbols(symbol)
                
                if straddle_info:
                    # Fetch LTP for both CE and PE
                    ce_symbol = straddle_info['ce_symbol']
                    pe_symbol = straddle_info['pe_symbol']
                    
                    ltp_response = self.kite_client.get_ltp([ce_symbol, pe_symbol])
                    
                    if ltp_response:
                        ce_ticks = {'last_price': ltp_response.get(ce_symbol, 0), 'volume': 0}  # Volume not available in LTP
                        pe_ticks = {'last_price': ltp_response.get(pe_symbol, 0), 'volume': 0}
                        
                        # Calculate straddle metrics
                        straddle_metrics = self.calculate_straddle_metrics(ce_ticks, pe_ticks)
                        
                        if straddle_metrics:
                            # Verify volatility expansion
                            expansion_status = self.verify_volatility_expansion(straddle_metrics, threshold=2.5)
                            
                            if expansion_status != "CONFIRMED":
                                logger.info(f"[FILTER] Trade rejected: {symbol} straddle not in expansion mode ({expansion_status})")
                                return False
                            else:
                                logger.info(f"[FILTER] Straddle expansion confirmed: {symbol} volatility breakout detected")
                                # Store straddle metrics in trade for later use
                                trade['straddle_metrics'] = straddle_metrics
                        else:
                            # If straddle calculation fails, log warning but allow trade (graceful degradation)
                            logger.warning(f"[FILTER] Straddle metrics calculation failed for {symbol}, allowing trade with warning")
                    else:
                        # If LTP fetch fails, log warning but allow trade (graceful degradation)
                        logger.warning(f"[FILTER] Could not fetch straddle LTP for {symbol}, allowing trade with warning")
                else:
                    # If straddle symbol generation fails, log warning but allow trade (graceful degradation)
                    logger.warning(f"[FILTER] Could not generate straddle symbols for {symbol}, allowing trade with warning")
                    
            except Exception as e:
                # If any error in straddle filtering, log warning but allow trade (graceful degradation)
                logger.error(f"[FILTER] Error in straddle expansion filter for {symbol}: {e}, allowing trade with warning")
        
        logger.info(f"[FILTER] Trade passed all hard filters for {trade['symbol']}")
        return True
    
    def calculate_trade_levels(self, trade):
        """
        Calculate entry, target, and stoploss levels based on option pricing logic.
        This is BOT responsibility - NOT LLM responsibility.
        
        Uses 1:5 risk-reward ratio as requested.
        
        Args:
            trade: OptionStar trade setup with direction, strike, spot, etc.
        
        Returns:
            Updated trade with entry, target, stoploss, action
        """
        try:
            spot = trade.get("spot", 0)
            strike = trade.get("strike", 0)
            direction = trade.get("direction", "CALL")
            
            # CRITICAL FIX: If entry is already set from real LTP, use it
            # Do NOT overwrite with formula-based entry
            if 'entry' in trade and trade.get('entry', 0) > 0:
                entry = trade['entry']
                logger.info(f"Using REAL LTP entry: ₹{entry:.2f}")
            else:
                # Fallback to formula-based entry only if real LTP not available
                # Calculate option premium estimate based on moneyness
                distance_from_spot = abs(spot - strike)
                
                # Base premium calculation (simplified)
                if direction == "CALL":
                    if spot > strike:  # ITM
                        base_premium = (spot - strike) * 0.5 + 50
                    else:  # OTM
                        base_premium = max(20, 100 - distance_from_spot * 0.3)
                else:  # PUT
                    if spot < strike:  # ITM
                        base_premium = (strike - spot) * 0.5 + 50
                    else:  # OTM
                        base_premium = max(20, 100 - distance_from_spot * 0.3)
                
                entry = round(base_premium, 2)
                logger.warning(f"Using FORMULA entry (fallback): ₹{entry:.2f}")
            
            # Risk management calculations with 1:5 risk-reward ratio
            # For 1:5 ratio: If risk is X, reward should be 5X
            # Using 10% stoploss and 50% target gives exactly 1:5 ratio
            risk_percentage = 0.12  # 12% stoploss (increased to prevent instant micro-exits)
            reward_percentage = 0.60  # 60% target (5x the risk)
            
            stoploss = round(entry * (1 - risk_percentage), 2)
            target = round(entry * (1 + reward_percentage), 2)
            
            # Determine action based on direction
            action = "BUY" if direction in ["CALL", "PUT"] else "HOLD"
            
            # Calculate actual risk and reward amounts
            risk_amount = entry - stoploss
            reward_amount = target - entry
            actual_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            # Update trade with calculated levels
            trade.update({
                "action": action,
                "entry": entry,
                "target": target,
                "stoploss": stoploss,
                "risk_amount": round(risk_amount, 2),
                "reward_amount": round(reward_amount, 2),
                "risk_reward_ratio": round(actual_ratio, 2)
            })
            
            logger.info(f"[TRADE LEVELS] Entry: ₹{entry}, Target: ₹{target}, Stoploss: ₹{stoploss}")
            logger.info(f"[RISK/REWARD] Risk: ₹{risk_amount:.2f}, Reward: ₹{reward_amount:.2f}, Ratio: 1:{actual_ratio:.2f}")
            
            return trade
            
        except Exception as e:
            logger.error(f"Error calculating trade levels: {e}")
            # Add fallback values
            trade.update({
                "action": "HOLD",
                "entry": 0,
                "target": 0,
                "stoploss": 0,
                "risk_amount": 0,
                "reward_amount": 0,
                "risk_reward_ratio": 0
            })
            return trade
    
    def lock_active_trade(self, trade, use_llm_validation=True):
        """
        Lock a trade as an active trade to be processed and monitored.
        This is the CORE FIX for trade binding with real data.
        
        Args:
            trade: Trade dictionary from scanner
            use_llm_validation: Whether to validate with LLM before locking (default: True)
        
        Returns:
            trade_id if locked successfully, None otherwise
        """
        # STEP 1: LLM Validation is now done during scan, not during lock
        # This prevents blocking and improves UX
        logger.info("="*80)
        logger.info("🔒 LOCKING TRADE (Pre-validated by Scanner)")
        logger.info("="*80)
        logger.info("Trade was already validated by LLM during market scan")
        logger.info("Fetching real entry price from market...")
        
        # STEP 2: Get Real Option Price for Entry (not formula-based)
        symbol = trade.get('symbol', '')
        strike = trade.get('strike', 0)
        direction = trade.get('direction', 'CALL')
        
        real_entry_price = self.get_real_option_price(symbol, strike, direction)
        
        if real_entry_price:
            trade['entry'] = real_entry_price
            logger.info(f"📊 REAL ENTRY PRICE: ₹{real_entry_price:.2f} (from market LTP)")
        else:
            logger.warning("⚠️  Could not get real entry price, using formula-based entry")
        
        # STEP 3: Calculate trade levels
        trade = self.calculate_trade_levels(trade)
        
        # STEP 4: Generate trade ID and lock
        trade_id = f"{trade['symbol']}_{trade['strike']}_{int(time.time())}"
        trade['trade_id'] = trade_id
        trade['locked_at'] = time.time()
        trade['status'] = 'ACTIVE'
        
        # STEP 5: Add to active trades list (multi-trade capability)
        self.active_trades.append(trade)
        
        # Legacy: Set single active trade for backward compatibility
        self.active_trade = trade
        self.active_trade_id = trade_id
        self.trade_lock_time = time.time()
        
        logger.info("="*80)
        logger.info("🔒 NEW ACTIVE TRADE LOCKED")
        logger.info("="*80)
        logger.info(f"Symbol: {trade['symbol']}")
        logger.info(f"Strike: {trade['strike']}")
        logger.info(f"Direction: {trade['direction']}")
        logger.info(f"Trade ID: {trade_id}")
        logger.info(f"Entry: ₹{trade['entry']:.2f}")
        logger.info(f"Target: ₹{trade['target']:.2f}")
        logger.info(f"Stoploss: ₹{trade['stoploss']:.2f}")
        logger.info(f"Active Trades: {len(self.active_trades)}")
        logger.info("="*80)
        
        return trade_id
    
    def process_active_trade(self):
        """
        Process the locked active trade - calculate entry/SL/TP ONLY for this trade.
        This prevents mismatch between scanner and engine.
        
        Returns:
            Updated active trade with levels, or None if no active trade
        """
        if not self.active_trade:
            return None
        
        trade = self.active_trade
        
        # Calculate trade levels (only once per trade)
        if 'entry' not in trade or trade.get('entry', 0) == 0:
            trade = self.calculate_trade_levels(trade)
            self.active_trade = trade  # Update the locked trade
        
        return self.active_trade
    
    def monitor_active_trade(self):
        """
        Monitor all locked active trades - track price movement for SAME trades only.
        Supports multi-trade capability.
        
        Returns:
            List of monitoring results for all active trades
        """
        if not self.active_trades:
            return []
        
        results = []
        
        for i, trade in enumerate(self.active_trades):
            if trade.get('status') != 'ACTIVE':
                continue
            
            try:
                symbol = trade.get('symbol', '')
                strike = trade.get('strike', 0)
                direction = trade.get('direction', 'CALL')
                
                # Get current option price using real option symbol
                current_price = self.get_real_option_price(symbol, strike, direction)
                
                if current_price:
                    # Calculate P&L
                    entry = trade.get('entry', 0)
                    pnl = current_price - entry
                    pnl_percent = (pnl / entry * 100) if entry > 0 else 0
                    
                    # Check TP/SL
                    target = trade.get('target', 0)
                    stoploss = trade.get('stoploss', 0)
                    
                    status = 'ACTIVE'
                    if current_price >= target:
                        status = 'TARGET HIT'
                        logger.info("="*80)
                        logger.info("🎯 TARGET HIT!")
                        logger.info(f"Trade ID: {trade.get('trade_id')}")
                        logger.info(f"{symbol} {strike} {direction}")
                        logger.info(f"Entry: {entry} | Current: {current_price} | Target: {target}")
                        logger.info(f"P&L: ₹{pnl:.2f} ({pnl_percent:.2f}%)")
                        logger.info("="*80)
                        trade['status'] = 'TARGET HIT'
                        trade['exit_price'] = current_price
                        trade['exit_pnl'] = pnl
                        trade['exit_time'] = time.time()
                        # Add to completed trades for history
                        self.completed_trades.append(trade.copy())
                        logger.info("✅ Trade added to completed trades history")
                        logger.info("💡 New trades can be locked from scanner output")
                    elif current_price <= stoploss:
                        status = 'STOPLOSS HIT'
                        logger.info("="*80)
                        logger.info("🛑 STOPLOSS HIT!")
                        logger.info(f"Trade ID: {trade.get('trade_id')}")
                        logger.info(f"{symbol} {strike} {direction}")
                        logger.info(f"Entry: {entry} | Current: {current_price} | SL: {stoploss}")
                        logger.info(f"P&L: ₹{pnl:.2f} ({pnl_percent:.2f}%)")
                        logger.info("="*80)
                        trade['status'] = 'STOPLOSS HIT'
                        trade['exit_price'] = current_price
                        trade['exit_pnl'] = pnl
                        trade['exit_time'] = time.time()
                        # Add to completed trades for history
                        self.completed_trades.append(trade.copy())
                        logger.info("✅ Trade added to completed trades history")
                        logger.info("💡 New trades can be locked from scanner output")
                    
                    # Update trade with current price
                    trade['current_price'] = current_price
                    trade['pnl'] = pnl
                    trade['pnl_percent'] = pnl_percent
                    
                    # Only add to results if still ACTIVE (completed trades already logged above)
                    if status == 'ACTIVE':
                        results.append({
                            'trade_id': trade.get('trade_id'),
                            'current_price': current_price,
                            'pnl': pnl,
                            'pnl_percent': pnl_percent,
                            'status': status
                        })
            except Exception as e:
                logger.error(f"Error monitoring trade {trade.get('trade_id')}: {e}")
        
        # Clean up completed trades from active list (CRITICAL)
        before_cleanup = len(self.active_trades)
        self.active_trades = [t for t in self.active_trades if t.get('status') == 'ACTIVE']
        after_cleanup = len(self.active_trades)
        
        if before_cleanup > after_cleanup:
            logger.info(f"🧹 Cleaned up {before_cleanup - after_cleanup} completed trade(s) from active list")
            logger.info(f"📊 Active trades remaining: {after_cleanup}")
            logger.info("💡 Scanner continues to find new opportunities")
        
        # Update legacy single active trade
        if self.active_trades:
            self.active_trade = self.active_trades[-1]
            self.active_trade_id = self.active_trades[-1].get('trade_id')
        else:
            self.active_trade = None
            self.active_trade_id = None
            logger.info("🔓 No active trades - waiting for new trade selection")
        
        return results
    
    def unlock_active_trade(self, trade_id=None):
        """
        Unlock active trade(s).
        
        Args:
            trade_id: Specific trade ID to unlock, or None to unlock all
        """
        if trade_id:
            # Unlock specific trade
            self.active_trades = [t for t in self.active_trades if t.get('trade_id') != trade_id]
            logger.info("="*80)
            logger.info(f"🔓 TRADE UNLOCKED: {trade_id}")
            logger.info("="*80)
        else:
            # Unlock all trades
            if self.active_trades:
                logger.info("="*80)
                logger.info("🔓 ALL TRADES UNLOCKED")
                logger.info(f"Unlocked {len(self.active_trades)} trade(s)")
                logger.info("="*80)
            self.active_trades = []
        
        # Update legacy single active trade
        if self.active_trades:
            self.active_trade = self.active_trades[-1]
            self.active_trade_id = self.active_trades[-1].get('trade_id')
        else:
            self.active_trade = None
            self.active_trade_id = None
    
    def _calculate_trade_strength(self, trade):
        """
        Calculate trade strength to filter weak trades before LLM call.
        Returns score 1-5 (higher = stronger trade).
        
        MEMORY SAFE: This is the BIGGEST FIX to reduce LLM calls
        """
        strength = 0
        
        # Factor 1: Price momentum (strong movement = stronger trade)
        try:
            price_change = float(trade.get('price_change', '0%').replace('%', ''))
            if abs(price_change) > 0.5:  # More than 0.5% movement
                strength += 2
            elif abs(price_change) > 0.2:  # More than 0.2% movement
                strength += 1
        except:
            pass
        
        # Factor 2: OptionStar reason quality (check for positive indicators)
        optionstar_reason = trade.get('optionstar_reason', '').lower()
        positive_indicators = ['strong', 'breakout', 'momentum', 'trend', 'support', 'resistance']
        if any(indicator in optionstar_reason for indicator in positive_indicators):
            strength += 1
        
        # Factor 3: VWAP alignment (price near VWAP = stronger trade)
        try:
            current_vs_vwap = trade.get('current_vs_vwap', 0)
            if abs(current_vs_vwap) < 50:  # Within 50 points of VWAP
                strength += 1
        except:
            pass
        
        # Factor 4: Price history consistency (more history = more reliable)
        try:
            history_count = trade.get('price_history_count', 0)
            if history_count >= 10:
                strength += 1
        except:
            pass
        
        # Cap at 5
        return min(5, max(1, strength))
    
    def evaluate_with_llm(self, trade):
        """
        Evaluate trade using LLM.
        Returns (score, decision, llm_confirmation) tuple.
        
        MEMORY SAFE: Trade strength filtering to reduce LLM calls (BIGGEST FIX)
        """
        if not self.llm_analyzer:
            logger.warning("LLM not available, using fallback logic")
            return 50, "HOLD", "LLM not available - using fallback logic"
        
        # MEMORY SAFE: Trade strength filtering - Skip LLM for weak trades (BIGGEST FIX)
        trade_strength = self._calculate_trade_strength(trade)
        if trade_strength < FROZEN_TRADE_STRENGTH_THRESHOLD:  # ⚠️ FROZEN: Do not modify threshold
            logger.info(f"⏸️  Trade strength too low ({trade_strength}/5 < {FROZEN_TRADE_STRENGTH_THRESHOLD}), skipping LLM call (memory safe)")
            return 30, "SKIP", f"Trade strength too low ({trade_strength}/5), skipped LLM evaluation"
        
        # Check LLM cooldown to prevent memory spikes
        time_since_last_llm = time.time() - self.last_llm_call
        if time_since_last_llm < self.llm_cooldown_seconds:
            logger.info(f"⏸️  LLM cooldown active ({time_since_last_llm:.1f}s < {self.llm_cooldown_seconds}s), using fallback")
            return 50, "HOLD", "LLM cooldown active, using fallback logic"
        
        # Memory watchdog - skip LLM if memory usage is too high
        if self.psutil_available:
            try:
                import psutil
                mem_percent = psutil.virtual_memory().percent
                
                # MEMORY SAFE: Additional memory guard - sleep if memory is high
                if mem_percent > FROZEN_MEMORY_GUARD_THRESHOLD:  # ⚠️ FROZEN: Do not modify threshold
                    logger.warning(f"⚠️  Memory usage elevated: {mem_percent:.1f}% > {FROZEN_MEMORY_GUARD_THRESHOLD}%, sleeping for 20s (memory safe)")
                    time.sleep(20)
                
                if mem_percent > self.memory_threshold_percent:
                    logger.warning(f"⚠️  Critical memory usage: {mem_percent:.1f}% > {self.memory_threshold_percent}%, skipping LLM call")
                    return 50, "HOLD", f"Critical memory usage ({mem_percent:.1f}%), skipped LLM evaluation"
            except Exception as e:
                logger.warning(f"Memory check failed: {e}")
        
        try:
            # Check connection status before attempting LLM call
            if hasattr(self.llm_analyzer, 'connection_ok') and not self.llm_analyzer.connection_ok:
                logger.warning("LLM connection not available, using fallback logic")
                return 50, "HOLD", "LLM connection not available, using fallback logic"
            
            logger.info(f"🤖 Sending trade to LLM for evaluation: {trade['symbol']}")

            # Get LLM analysis with timeout protection using threading
            import concurrent.futures

            def get_analysis():
                # Handle different LLM interfaces
                if hasattr(self.llm_analyzer, 'analyze_entry_signal'):
                    # Ollama wrapper (LLMMarketAnalyzer)
                    return self.llm_analyzer.analyze_entry_signal(trade)
                elif hasattr(self.llm_analyzer, 'analyze_trading_data'):
                    # Direct integration (Gemini or Ollama)
                    return self.llm_analyzer.analyze_trading_data(trade, "entry")
                else:
                    logger.error("LLM analyzer has no compatible analysis method")
                    return None

            # Use ThreadPoolExecutor with 10-second timeout (reduced from 30)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(get_analysis)
                try:
                    analysis = future.result(timeout=10)
                except concurrent.futures.TimeoutError:
                    logger.error("LLM call timed out after 10 seconds, using fallback")
                    return 50, "HOLD", "LLM call timed out after 10 seconds, using fallback logic"
            
            if analysis:
                signal = analysis.get('signal', 'HOLD')
                confidence = analysis.get('confidence', 0)
                reason = analysis.get('reason', 'No reason provided')
                
                logger.info(f"🤖 LLM Decision: {signal} (confidence: {confidence}%)")
                logger.info(f"🤖 LLM Reason: {reason}")
                
                # Update last LLM call time on successful call
                self.last_llm_call = time.time()
                self.llm_call_count += 1
                
                # Periodically unload model to free memory (⚠️ FROZEN: every 3rd call)
                if hasattr(self.llm_analyzer, 'ollama') and self.llm_call_count % FROZEN_MODEL_UNLOAD_FREQUENCY == 0:
                    try:
                        self.llm_analyzer.ollama.unload_model()
                        logger.info("✓ Periodic model unload for memory management")
                    except Exception as e:
                        logger.warning(f"Model unload failed: {e}")
                
                # Create LLM confirmation message with trade levels
                llm_confirmation = f"✅ LLM CONFIRMED: {signal} signal with {confidence}% confidence. "
                llm_confirmation += f"Entry: ₹{trade.get('entry', 'N/A')}, Target: ₹{trade.get('target', 'N/A')}, "
                llm_confirmation += f"Stoploss: ₹{trade.get('stoploss', 'N/A')}, Risk-Reward: 1:{trade.get('risk_reward_ratio', 'N/A')}. "
                llm_confirmation += f"Reason: {reason}"
                
                # Convert signal to score
                if signal == "BUY":
                    score = confidence
                    decision = "EXECUTE"
                elif signal == "SELL":
                    score = confidence
                    decision = "EXECUTE"
                else:
                    score = confidence
                    decision = "SKIP"
                
                return score, decision, llm_confirmation
            else:
                logger.warning("LLM analysis failed, using fallback")
                return 50, "HOLD", "LLM analysis failed, using fallback logic"
                
        except Exception as e:
            logger.error(f"Error in LLM evaluation: {e}")
            return 50, "HOLD", f"Error in LLM evaluation: {str(e)}"
    
    def _execute_queued_trade(self, trade: Dict[str, Any]) -> bool:
        """
        Execute trade approved by LLM from queue.
        
        Args:
            trade: Trade dictionary with all trade details
            
        Returns:
            True if trade executed successfully, False otherwise
        """
        try:
            symbol = trade.get('symbol', '')
            direction = trade.get('direction', '')
            strike = trade.get('strike', 0)
            entry = trade.get('entry', 0)
            
            logger.info(f"🚀 Executing queued trade: {symbol} {direction} @ {strike} (entry: {entry})")
            
            # Add trade to trade manager
            trade_id = self.trade_manager.add_trade(trade)
            
            if trade_id:
                logger.info(f"✅ Trade executed successfully: {trade_id}")
                return True
            else:
                logger.warning(f"⚠️ Trade execution failed: {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing queued trade: {e}")
            return False
    
    def execute_trade(self, trade, decision, llm_confirmation=""):
        """
        Generate manual trading signal instead of automated execution.
        
        Args:
            trade: Trade dictionary with all trade details
            decision: Trading decision (EXECUTE, SKIP, HOLD)
            llm_confirmation: LLM confirmation message with trade levels
        """
        # Generate manual signal using Mistral-7B
        logger.info(f"🤖 Generating manual signal for {trade.get('symbol', '')} {trade.get('direction', '')}")
        
        # Prepare trade data for manual signal generation
        signal_trade = {
            "trade_id": trade.get('trade_id', ''),
            "symbol": trade.get('symbol', ''),
            "direction": trade.get('direction', ''),
            "strike": trade.get('strike', 0),
            "entry": trade.get('entry', 0),
            "target": trade.get('target', 0),
            "stoploss": trade.get('stoploss', 0),
            "spot": trade.get('spot', 0),
            # Add filter data for AI validation
            "ema_trend": trade.get('ema_trend', 'UNKNOWN'),
            "straddle_deviation": trade.get('straddle_deviation', 0),
            "straddle_status": trade.get('straddle_status', 'UNKNOWN'),
            "blended_vwap": trade.get('blended_vwap', 0),
            "straddle_price": trade.get('straddle_price', 0)
        }
        
        # Generate manual signal
        manual_signal_result = self.generate_manual_signal(signal_trade)
        
        if manual_signal_result['status'] == 'APPROVED':
            # Add approved signal to web interface
            try:
                from web_interface import add_manual_signal
                add_manual_signal(manual_signal_result)
                logger.info(f"✅ Manual signal added to dashboard: {trade.get('symbol', '')}")
            except ImportError:
                logger.warning("Could not import web_interface for signal display")
            
            # Print the approved signal to console
            print("\n" + "=" * 80)
            print("🚀 NEW MANUAL TRADING SIGNAL APPROVED BY AI")
            print("=" * 80)
            print(manual_signal_result['signal'])
            print("=" * 80)
            print("📢 Signal added to Port 5000 Dashboard - Execute manually at your discretion")
            print("=" * 80)
            
        elif manual_signal_result['status'] == 'REJECTED':
            # Log rejection
            logger.info(f"❌ Manual signal rejected: {trade.get('symbol', '')}")
            print(f"\n❌ SIGNAL REJECTED: {trade.get('symbol', '')}")
            print(f"Reason: Check dashboard for details")
            
        else:
            logger.warning(f"⚠️ Manual signal generation failed: {manual_signal_result['status']}")
            print(f"\n⚠️ SIGNAL GENERATION FAILED: {manual_signal_result['status']}")
    
    def rank_and_store_trade(self, trade, confidence, symbol, llm_confirmation=""):
        """
        Rank and store the best trades from multiple instruments.
        
        Args:
            trade: Complete trade setup with entry, target, stoploss
            confidence: LLM confidence score
            symbol: Instrument symbol
            llm_confirmation: LLM confirmation message with trade levels
        """
        trade_entry = {
            "symbol": symbol,
            "confidence": confidence,
            "trade": trade,
            "llm_confirmation": llm_confirmation,
            "timestamp": datetime.now().isoformat()
        }
        
        self.best_trades.append(trade_entry)
        
        # Sort by confidence (highest first)
        self.best_trades = sorted(self.best_trades, key=lambda x: x["confidence"], reverse=True)
        
        # Keep only top N trades
        if len(self.best_trades) > self.max_best_trades:
            self.best_trades = self.best_trades[:self.max_best_trades]
        
        logger.info(f"[RANKING] Added {symbol} trade (confidence: {confidence}%), Top trades: {len(self.best_trades)}")
    
    def print_best_trades(self):
        """Print the current best trades in a readable table format."""
        if not self.best_trades:
            return
        
        print("\n" + "=" * 100)
        print("🏆 BEST TRADES RANKING (Post-LLM Analysis)")
        print("=" * 100)
        
        # Print table header
        print(f"{'#':<4} {'Symbol':<10} {'Option':<12} {'Entry (₹)':<10} {'Target (₹)':<10} {'SL (₹)':<10} {'Risk (₹)':<10} {'Reward (₹)':<12} {'R:R':<6} {'Conf%':<8}")
        print("-" * 100)
        
        for i, trade_entry in enumerate(self.best_trades, 1):
            trade = trade_entry["trade"]
            
            # Determine option type (CE/PE) based on direction
            direction = trade.get('direction', 'N/A')
            option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
            strike = trade.get('strike', 'N/A')
            
            # Format the option symbol
            option_symbol = f"{strike} {option_type}"
            
            # Print trade data row
            print(f"{i:<4} {trade_entry['symbol']:<10} {option_symbol:<12} {trade.get('entry', 0):<10.2f} {trade.get('target', 0):<10.2f} {trade.get('stoploss', 0):<10.2f} {trade.get('risk_amount', 0):<10.2f} {trade.get('reward_amount', 0):<12.2f} 1:{trade.get('risk_reward_ratio', 0):<4.1f} {trade_entry['confidence']:<8.0f}")
            
            # Print LLM confirmation if available (abbreviated)
            if trade_entry.get('llm_confirmation'):
                confirmation = trade_entry['llm_confirmation']
                # Show first part of confirmation
                if len(confirmation) > 80:
                    confirmation = confirmation[:80] + "..."
                print(f"     └─ {confirmation}")
        
        print("=" * 100)
        print(f"🥇 TOP TRADE: {self.best_trades[0]['symbol']} | Confidence: {self.best_trades[0]['confidence']}%")
        print("=" * 100)

    def enable_paper_trading(self):
        """Enable paper trading execution"""
        self.paper_trading_enabled = True
        self.paper_trading = True
        logger.info("✅ PAPER TRADING ENABLED - Bot will now execute paper trades")
        logger.info("✅ Type 'disable paper trade' to stop execution")
        logger.info("=" * 80)

    def disable_paper_trading(self):
        """Disable paper trading execution"""
        self.paper_trading_enabled = False
        self.paper_trading = False
        logger.info("⛔ PAPER TRADING DISABLED - Bot will scan but not execute")
        logger.info("✅ Type 'enable paper trade' to allow execution")
        logger.info("=" * 80)

    def get_status(self):
        """Get current bot status"""
        status = {
            "paper_trading": self.paper_trading_enabled,
            "paper_trading_default": getattr(self, 'paper_trading_default', False),
            "bot_running": self.bot_running,
            "bot_mode": self.bot_mode,
            "llm_enabled": hasattr(self, 'llm_analyzer'),
            "monitoring": list(self.market_data.keys()) if self.market_data else []
        }
        return status

    def handle_command(self, command):
        """
        Handle user commands for bot control.
        Returns True if command was handled, False otherwise.
        """
        command = command.lower().strip()

        if command == "enable paper trade":
            self.enable_paper_trading()
            return True

        elif command == "disable paper trade":
            self.disable_paper_trading()
            return True

        elif command == "status":
            status = self.get_status()
            logger.info("=" * 80)
            logger.info("📊 BOT STATUS")
            logger.info("=" * 80)
            logger.info(f"Paper Trading (runtime): {'ENABLED' if status['paper_trading'] else 'DISABLED'}")
            logger.info(f"Paper Trading (config default): {'ENABLED' if status['paper_trading_default'] else 'DISABLED'}")
            logger.info(f"Bot Running: {status['bot_running']}")
            logger.info(f"Bot Mode: {status['bot_mode']}")
            logger.info(f"LLM Enabled: {status['llm_enabled']}")
            logger.info(f"Monitoring: {status['monitoring']}")
            logger.info("=" * 80)
            return True

        elif command == "help":
            logger.info("=" * 80)
            logger.info("📋 AVAILABLE COMMANDS")
            logger.info("=" * 80)
            logger.info("enable paper trade  - Enable paper trading execution")
            logger.info("disable paper trade - Disable paper trading execution")
            logger.info("status              - Show current bot status")
            logger.info("help                - Show this help message")
            logger.info("stop                - Stop the bot")
            logger.info("=" * 80)
            return True

        elif command == "stop":
            self.bot_running = False
            logger.info("🛑 STOPPING BOT...")
            return True

        return False
    
    def handle_trade(self, trade, symbol):
        """
        Handle trade: Duplicate check → Apply filters → Calculate levels → Check capacity → LLM evaluation → Add to Trade Manager
        Updated to use Trade Manager instead of ranking - sticks with trades until completion.
        """
        self.trade_stats['total_found'] += 1
        logger.info(f"\n📊 Trade found: {symbol} at {trade['spot']}")

        # Step 0: Check for duplicate trades
        if self._is_duplicate_trade(trade):
            self.trade_stats['duplicates_skipped'] += 1
            return

        # Observation mode: Print details and skip execution
        if self.bot_mode == "observation":
            logger.info("\n" + "="*80)
            logger.info(" OBSERVATION MODE")
            logger.info("="*80)
            logger.info(f"TRADE DATA: Symbol={symbol}, Spot={trade.get('spot')}, Direction={trade.get('direction')}, Strike={trade.get('strike')}")
            logger.info("="*80)
            # In observation mode, we still process the trade for analysis
            # but skip actual execution
            pass

        # Step 1: Apply hard filters
        if not self.apply_hard_filters(trade):
            self.trade_stats['hard_filter_rejected'] += 1
            logger.info(f"⏭️  Trade failed hard filters")
            return
        
        # Step 1.5: Check Anti-Whipsaw cooldown (prevent re-entry after SL hit)
        if not self.is_symbol_allowed_to_trade(symbol):
            logger.info(f"⏭️  Skipping {symbol} - currently in cooldown period after SL hit")
            return
        
        # Step 2: Calculate trade levels (entry, target, stoploss) - BOT RESPONSIBILITY
        trade = self.calculate_trade_levels(trade)
        
        # Step 3: Check if Trade Manager has capacity
        if not self.trade_manager.can_add_new_trade():
            self.trade_stats['capacity_rejected'] += 1
            active_count = self.trade_manager.get_active_trade_count()
            logger.info(f"⏸️  Trade Manager at capacity ({active_count}/{self.trade_manager.max_concurrent_trades}) - monitoring existing trades")
            logger.info(f"⏭️  Skipping new trade search until current trades complete")
            return
        
        # Display trade setup table before LLM evaluation
        print("\n" + "=" * 100)
        print(f"📊 TRADE SETUP: {symbol} (Pre-LLM Analysis)")
        print("=" * 100)
        
        # Determine option type (CE/PE) based on direction
        direction = trade.get('direction', 'N/A')
        option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
        strike = trade.get('strike', 'N/A')
        
        # Format the option symbol
        option_symbol = f"{strike} {option_type}"
        
        # Create table header
        print(f"{'Symbol':<12} {'Option':<15} {'Entry (₹)':<12} {'Target (₹)':<12} {'Stoploss (₹)':<12} {'Risk (₹)':<10} {'Reward (₹)':<12} {'R:R Ratio':<10}")
        print("-" * 100)
        
        # Print trade data row
        print(f"{trade['symbol']:<12} {option_symbol:<15} {trade['entry']:<12.2f} {trade['target']:<12.2f} {trade['stoploss']:<12.2f} {trade.get('risk_amount', 0):<10.2f} {trade.get('reward_amount', 0):<12.2f} 1:{trade.get('risk_reward_ratio', 0):<8.2f}")
        print("=" * 100)
        print(f"🤖 Sending to LLM for evaluation...")
        print("=" * 100)
        
        # Step 4: Check trade cooldown
        time_since_last_trade = time.time() - self.last_trade_time
        if time_since_last_trade < self.trade_cooldown_seconds:
            self.trade_stats['cooldown_rejected'] += 1
            logger.info(f"⏸️  Trade cooldown active ({time_since_last_trade:.1f}s < {self.trade_cooldown_seconds}s)")
            return
        
        # Step 5: LLM evaluation (PAUSES here for LLM response) - LLM VALIDATES TRADE
        logger.info(f"🤖 Starting LLM evaluation for {symbol} trade...")
        score, decision, llm_confirmation = self.evaluate_with_llm(trade)
        
        logger.info(f"🤖 LLM Result: Decision={decision}, Score={score}, Threshold=70")
        
        # Step 6: Add to Trade Manager if LLM approves
        if decision == "EXECUTE" and score >= 70:  # 70% confidence threshold
            self.trade_stats['llm_approved'] += 1
            
            # Add instrument token to trade setup
            instrument_key = self.instruments.get(symbol, {}).get('key', '')
            trade['instrument_token'] = instrument_key
            
            # Add to Trade Manager for active monitoring
            trade_id = self.trade_manager.add_trade(trade)
            
            if trade_id:
                self.trade_stats['added_to_manager'] += 1
                logger.info(f"✅ Trade added to active monitoring: {trade_id}")
                print(f"\n🎯 TRADE ACTIVATED: {trade_id}")
                print(f"📊 LLM Confirmation: {llm_confirmation}")
                print("=" * 100)
                
                # Update last trade time
                self.last_trade_time = time.time()
            else:
                logger.warning("⚠️  Failed to add trade to Trade Manager (capacity issue)")
        else:
            self.trade_stats['llm_rejected'] += 1
            logger.info(f"⏭️  Skipping {symbol} trade - LLM decision: {decision}, score: {score}/70")
            logger.info(f"   Reason: Score below threshold or decision not EXECUTE")
    
    def is_market_hours(self, instrument=None):
        """Check if market is open for specific instrument - DYNAMIC from config"""
        # In paper trading mode, always return True for testing
        if self.paper_trading:
            return True

        now = datetime.now().time()

        # Default to first instrument in watchlist if none specified
        if instrument is None:
            instrument = self.watchlist[0] if self.watchlist else "NIFTY"

        # Get instrument data from config
        instrument_data = None
        instruments_config = self.config.get("instruments", {})
        
        if instrument in instruments_config:
            instrument_data = instruments_config[instrument]
        else:
            # Check if it's a commodity (GOLDM, etc.) from instruments dict
            if instrument in self.instruments:
                # Commodities have special handling
                if instrument in ["GOLDM", "SILVERM", "CRUDEOIL"]:
                    market_open = dt_time(9, 0)
                    market_close = dt_time(23, 30)
                    return market_open <= now <= market_close
                # Default to NSE equity timings
                market_open = dt_time(9, 15)
                market_close = dt_time(15, 30)
                return market_open <= now <= market_close
            else:
                logger.warning(f"Instrument {instrument} not found in config, using default NSE timings")
                market_open = dt_time(9, 15)
                market_close = dt_time(15, 30)
                return market_open <= now <= market_close

        # Determine market hours based on exchange and instrument type from config
        exchange = instrument_data.get("exchange", "NSE")
        symbol = instrument_data.get("symbol", "")
        
        # NSE Index timings (for indices like NIFTY, BANKNIFTY)
        if exchange == "NSE" and any(idx in symbol.upper() for idx in ["NIFTY", "BANK", "FINNIFTY"]):
            market_open = dt_time(9, 15)
            market_close = dt_time(15, 30)
            return market_open <= now <= market_close
        
        # NSE Equity timings (for stocks)
        elif exchange == "NSE":
            market_open = dt_time(9, 15)
            market_close = dt_time(15, 30)
            return market_open <= now <= market_close
        
        # MCX Commodity timings
        elif exchange == "MCX":
            market_open = dt_time(9, 0)
            market_close = dt_time(23, 30)
            return market_open <= now <= market_close
        
        # BSE or other exchanges - use NSE timings as default
        else:
            market_open = dt_time(9, 15)
            market_close = dt_time(15, 30)
            return market_open <= now <= market_close
    
    def is_market_open_time(self):
        """Check if current time is 9:15 AM (market open)"""
        now = datetime.now()
        market_open_time = dt_time(9, 15)
        current_time = now.time()
        
        # Check if it's within 2 minutes of market open (9:15-9:17)
        time_diff = abs((current_time.hour - market_open_time.hour) * 60 + (current_time.minute - market_open_time.minute))
        return time_diff <= 2 and not self.market_open_analysis_done
    
    def is_before_market_open(self):
        """Check if current time is before 9:15 AM (pre-market)"""
        now = datetime.now()
        market_open_time = dt_time(9, 15)
        current_time = now.time()
        
        # Check if current time is before 9:15 AM
        return current_time < market_open_time
    
    def perform_premarket_analysis(self):
        """
        Perform pre-market analysis using OptionStar (before 9:15 AM).
        This runs OptionStar analysis for all instruments to generate trade ideas.
        """
        logger.info("=" * 80)
        logger.info("PRE-MARKET OPTIONSTAR ANALYSIS (Before 9:15 AM)")
        logger.info("=" * 80)
        
        try:
            # Analyze each instrument in watchlist
            for symbol in self.watchlist:
                logger.info(f"\nAnalyzing {symbol} in pre-market...")
                
                # Get instrument key
                instrument_key = self._get_instrument_key(symbol)
                if not instrument_key:
                    logger.warning(f"Instrument key not found for {symbol}, skipping...")
                    continue
                
                # Get current price (use paper trading mode if enabled to get mock data)
                quotes = self.get_live_quotes([instrument_key])
                if not quotes or instrument_key not in quotes:
                    logger.warning(f"No quotes available for {symbol}, skipping...")
                    continue
                
                # Extract current price
                if 'last_price' in quotes[instrument_key]:
                    current_price = quotes[instrument_key].get('last_price', 0)
                else:
                    current_price = quotes[instrument_key].get('ltp', 0)
                
                if current_price == 0:
                    logger.warning(f"Invalid price for {symbol}, skipping...")
                    continue
                
                # Initialize price history for VWAP
                self.price_history[instrument_key] = [current_price]
                
                # Use current price as VWAP proxy at pre-market (no history yet)
                vwap = current_price
                
                # Fetch real option chain data
                option_chain = self.get_option_chain(symbol, current_price)
                
                # Use OptionStar for trade idea generation
                optionstar_trade = generate_trade(current_price, vwap, option_chain, symbol)
                
                if optionstar_trade:
                    # Store the selected strike for this instrument
                    self.selected_strikes[symbol] = {
                        'strike': optionstar_trade['strike'],
                        'direction': optionstar_trade['direction'],
                        'spot': current_price,
                        'vwap': vwap,
                        'support': optionstar_trade['support'],
                        'resistance': optionstar_trade['resistance'],
                        'reason': optionstar_trade['reason'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    logger.info(f"✓ {symbol} - OptionStar Setup: {optionstar_trade['strike']} {optionstar_trade['direction']}")
                    logger.info(f"  Reason: {optionstar_trade['reason']}")
                    logger.info(f"  Support: {optionstar_trade['support']}, Resistance: {optionstar_trade['resistance']}")
                    
                    # Print trade data in the requested format
                    print("\n" + "=" * 80)
                    print("OPTIONSTAR PRE-MARKET ANALYSIS")
                    print("=" * 80)
                    print(f"Symbol: {symbol}")
                    print(f"{{")
                    print(f"  \"strike\": {optionstar_trade['strike']},")
                    print(f"  \"direction\": \"{optionstar_trade['direction']}\",")
                    print(f"  \"spot\": {current_price},")
                    print(f"  \"support\": {optionstar_trade['support']},")
                    print(f"  \"resistance\": {optionstar_trade['resistance']},")
                    print(f"  \"reason\": \"{optionstar_trade['reason']}\"")
                    print(f"}}")
                    print("=" * 80)
                else:
                    logger.info(f"No OptionStar setup generated for {symbol} in pre-market")
            
            # Print summary
            logger.info("\n" + "=" * 80)
            logger.info("PRE-MARKET OPTIONSTAR ANALYSIS SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Instruments analyzed: {len(self.watchlist)}")
            logger.info(f"Setups generated: {len(self.selected_strikes)}")
            
            if self.selected_strikes:
                logger.info("\nOptionStar Setups:")
                for symbol, data in self.selected_strikes.items():
                    logger.info(f"  {symbol}: {data['strike']} ({data['direction']}) - {data['reason']}")
            
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error in pre-market analysis: {e}")
    
    def perform_market_open_analysis(self):
        """
        Perform 9:15 market open analysis using OptionStar.
        Analyzes all instruments and selects best strikes based on option chain data.
        """
        logger.info("=" * 80)
        logger.info("9:15 MARKET OPEN ANALYSIS STARTED")
        logger.info("=" * 80)
        
        try:
            # Analyze each instrument in watchlist
            for symbol in self.watchlist:
                logger.info(f"\nAnalyzing {symbol} at market open...")
                
                # Get instrument key
                instrument_key = self._get_instrument_key(symbol)
                if not instrument_key:
                    logger.warning(f"Instrument key not found for {symbol}, skipping...")
                    continue
                
                # Get current price
                quotes = self.get_live_quotes([instrument_key])
                if not quotes or instrument_key not in quotes:
                    logger.warning(f"No quotes available for {symbol}, skipping...")
                    continue
                
                # Extract current price
                if 'last_price' in quotes[instrument_key]:
                    current_price = quotes[instrument_key].get('last_price', 0)
                else:
                    current_price = quotes[instrument_key].get('ltp', 0)
                
                if current_price == 0:
                    logger.warning(f"Invalid price for {symbol}, skipping...")
                    continue
                
                # Initialize price history for VWAP
                self.price_history[instrument_key] = [current_price]
                
                # Use current price as VWAP proxy at market open (no history yet)
                vwap = current_price
                
                # Fetch real option chain data
                option_chain = self.get_option_chain(symbol, current_price)
                
                # Use OptionStar for trade idea generation
                optionstar_trade = generate_trade(current_price, vwap, option_chain, symbol)
                
                if optionstar_trade:
                    # Store the selected strike for this instrument
                    self.selected_strikes[symbol] = {
                        'strike': optionstar_trade['strike'],
                        'direction': optionstar_trade['direction'],
                        'spot': current_price,
                        'vwap': vwap,
                        'support': optionstar_trade['support'],
                        'resistance': optionstar_trade['resistance'],
                        'reason': optionstar_trade['reason'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    logger.info(f"✓ {symbol} - Selected Strike: {optionstar_trade['strike']} {optionstar_trade['direction']}")
                    logger.info(f"  Reason: {optionstar_trade['reason']}")
                    logger.info(f"  Support: {optionstar_trade['support']}, Resistance: {optionstar_trade['resistance']}")
                else:
                    logger.info(f"No trade setup generated for {symbol} at market open")
            
            # Mark analysis as complete
            self.market_open_analysis_done = True
            
            # Print summary
            logger.info("\n" + "=" * 80)
            logger.info("9:15 MARKET OPEN ANALYSIS SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Instruments analyzed: {len(self.watchlist)}")
            logger.info(f"Strikes selected: {len(self.selected_strikes)}")
            
            if self.selected_strikes:
                logger.info("\nSelected Strikes:")
                for symbol, data in self.selected_strikes.items():
                    logger.info(f"  {symbol}: {data['strike']} ({data['direction']}) - {data['reason']}")
            
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error in market open analysis: {e}")
            # Don't mark as done if there was an error
            self.market_open_analysis_done = False
    
    def _get_instrument_key(self, symbol):
        """
        Get instrument key for a given symbol from the instruments dict.
        Maps symbol names to their instrument keys.
        """
        symbol = symbol.upper()
        
        # Check direct mapping in instruments
        if symbol in self.instruments:
            return self.instruments[symbol]["key"]
        
        # Check for partial matches
        for instrument_name, instrument_data in self.instruments.items():
            if symbol in instrument_name.upper():
                return instrument_data["key"]
        
        logger.warning(f"No instrument key found for symbol: {symbol}")
        return None
    
    def run_event_loop(self, target_instrument=None):
        """
        Main event loop - Trade Management System.
        Monitors active trades, only scans for new ones when capacity available.
        Sticks with trades until completion (TP/SL hit) before finding new ones.
        """
        # Determine which instruments to monitor
        if target_instrument:
            # Single instrument mode (for testing)
            monitoring_list = [target_instrument.upper()]
            logger.info(f"Single instrument mode: {monitoring_list}")
        else:
            # Multi-instrument mode - use watchlist
            monitoring_list = self.watchlist
            logger.info(f"Multi-instrument scanner mode: {monitoring_list}")
        
        logger.info("=" * 80)
        logger.info("TRADE MANAGEMENT SYSTEM STARTED")
        logger.info("=" * 80)
        logger.info(f"Trading Universe: {monitoring_list}")
        logger.info(f"Max Concurrent Trades: {self.trade_manager.max_concurrent_trades}")
        logger.info(f"Paper trading (runtime): {self.paper_trading_enabled}")
        logger.info(f"Paper trading (config default): {getattr(self, 'paper_trading_default', False)}")
        logger.info(f"LLM enabled: {self.llm_analyzer is not None}")
        logger.info(f"Trade cooldown: {self.trade_cooldown_seconds}s")
        logger.info(f"Scan frequency: {FROZEN_LOOP_DELAY_SECONDS}s per instrument (⚠️ FROZEN)")
        logger.info(f"LLM cooldown: {FROZEN_LLM_COOLDOWN_SECONDS}s (⚠️ FROZEN)")
        logger.info(f"Memory threshold: {FROZEN_MEMORY_THRESHOLD_PERCENT}% (⚠️ FROZEN)")
        logger.info("⚠️ Memory-safe settings are PERMANENTLY LOCKED to prevent crashes")
        
        # Show current mode based on time
        if self.is_before_market_open():
            logger.info("🌅 MODE: PRE-MARKET OPTIONSTAR ANALYSIS (Before 9:15 AM)")
        else:
            logger.info("📈 MODE: TRADE MANAGEMENT & MONITORING (After 9:15 AM)")
        
        logger.info("=" * 80)
        
        scan_count = 0
        instruments_checked = 0
        
        # Main event loop (NON-BLOCKING)
        while self.bot_running:
            try:
                # PRIORITY 1: Monitor existing active trades
                self.trade_manager.monitor_active_trades()
                
                # Print active trades table periodically
                if instruments_checked % 5 == 0:  # Every 5 cycles
                    self.trade_manager.print_trade_table()
                
                # PRIORITY 2: Only scan for new trades if capacity available
                if self.trade_manager.can_add_new_trade():
                    logger.info(f"🔍 Trade Manager has capacity - scanning for new trade opportunities...")
                    
                    # Check if it's 9:15 market open time and perform analysis
                    if self.is_market_open_time():
                        logger.info("🔔 Market open time detected (9:15) - performing OptionStar analysis...")
                        self.perform_market_open_analysis()
                    
                    # Process each instrument in watchlist to find new trades
                    for symbol in monitoring_list:
                        if not self.bot_running:
                            break
                        
                        # Stop scanning if we found and added a trade
                        if not self.trade_manager.can_add_new_trade():
                            logger.info(f"⏸️  Trade Manager now at capacity - stopping scan")
                            break
                        
                        instruments_checked += 1
                        logger.info(f"\n{'='*80}")
                        logger.info(f"SCANNING: {symbol} (#{instruments_checked})")
                        logger.info(f"{'='*80}")
                        
                        # Check market hours for this instrument
                        market_open = self.is_market_hours(symbol)
                        logger.info(f"Market check: {symbol} - Open: {market_open}")

                        if not market_open:
                            # Check if it's before 9:15 AM (pre-market)
                            if self.is_before_market_open():
                                logger.info(f"Pre-market mode (before 9:15 AM) - running OptionStar analysis...")
                                # Run pre-market OptionStar analysis once per cycle
                                if instruments_checked == 1:  # Run only once per cycle
                                    self.perform_premarket_analysis()
                                continue
                            else:
                                logger.info(f"Market closed for {symbol}, skipping...")
                                continue
                        
                        # Scan for trade using OptionStar
                        instrument_key = self._get_instrument_key(symbol)
                        if not instrument_key:
                            logger.warning(f"Instrument key not found for {symbol}, skipping...")
                            continue
                        
                        trade = self.scan_market(instrument_key, symbol)
                        
                        if trade:
                            # Handle trade (includes OptionStar → Bot calc → LLM validation → Trade Manager)
                            self.handle_trade(trade, symbol)
                            scan_count += 1
                            
                            # If trade was added to manager, stop scanning for this cycle
                            if self.trade_manager.get_active_trade_count() >= self.trade_manager.max_concurrent_trades:
                                logger.info(f"✅ Trade added - Trade Manager now at capacity")
                                break
                else:
                    # Trade Manager at capacity - only monitor existing trades
                    active_count = self.trade_manager.get_active_trade_count()
                    logger.info(f"⏸️  Trade Manager at capacity ({active_count}/{self.trade_manager.max_concurrent_trades}) - monitoring existing trades only")
                    logger.info(f"⏭️  Skipping new trade search until current trades complete")
                
                # Print periodic summary
                if instruments_checked % (len(monitoring_list) * 2) == 0:  # Every 2 full cycles
                    logger.info(f"\n{'='*80}")
                    logger.info("TRADE MANAGEMENT SUMMARY")
                    logger.info(f"{'='*80}")
                    logger.info(f"Instruments checked: {instruments_checked}")
                    logger.info(f"Trades found: {scan_count}")
                    logger.info(f"Active trades: {self.trade_manager.get_active_trade_count()}")
                    logger.info(f"Completed trades: {len(self.trade_manager.completed_trades)}")
                    
                    # Detailed trade statistics
                    logger.info(f"Trade Statistics:")
                    logger.info(f"  Total found: {self.trade_stats['total_found']}")
                    logger.info(f"  Duplicates skipped: {self.trade_stats['duplicates_skipped']}")
                    logger.info(f"  Hard filter rejected: {self.trade_stats['hard_filter_rejected']}")
                    logger.info(f"  Capacity rejected: {self.trade_stats['capacity_rejected']}")
                    logger.info(f"  Cooldown rejected: {self.trade_stats['cooldown_rejected']}")
                    logger.info(f"  LLM rejected: {self.trade_stats['llm_rejected']}")
                    logger.info(f"  LLM approved: {self.trade_stats['llm_approved']}")
                    logger.info(f"  Added to manager: {self.trade_stats['added_to_manager']}")
                    
                    if self.trade_manager.active_trades:
                        for trade_id, trade in self.trade_manager.active_trades.items():
                            logger.info(f"  {trade_id}: P&L ₹{trade['pnl']:.2f} ({trade['pnl_percentage']:.2f}%)")
                    logger.info(f"{'='*80}")
                
                # Prevent CPU overload - controlled frequency (⚠️ FROZEN: 30 seconds)
                time.sleep(FROZEN_LOOP_DELAY_SECONDS)  # ⚠️ FROZEN: Do not modify
                
                # Periodic cleanup to prevent memory leaks (⚠️ FROZEN: every 10 instruments)
                if self.psutil_available and instruments_checked % FROZEN_MEMORY_CLEANUP_FREQUENCY == 0:
                    try:
                        import psutil
                        import gc
                        
                        mem_percent = psutil.virtual_memory().percent
                        if mem_percent > 75:  # Lowered threshold from 85% to 75%
                            logger.warning(f"⚠️  High memory usage: {mem_percent:.1f}%, performing aggressive cleanup")
                            
                            # Clean up price history for inactive instruments
                            active_symbols = monitoring_list
                            for symbol in list(self.price_history.keys()):
                                if symbol not in active_symbols:
                                    del self.price_history[symbol]
                            
                            # Clear old best trades (older than 30 minutes - reduced from 1 hour)
                            current_time = time.time()
                            self.best_trades = [
                                t for t in self.best_trades 
                                if current_time - datetime.fromisoformat(t['timestamp']).timestamp() < 1800
                            ]
                            
                            # Force Python garbage collection
                            gc.collect()
                            
                            # Unload LLM model if available
                            if hasattr(self.llm_analyzer, 'ollama'):
                                try:
                                    self.llm_analyzer.ollama.unload_model()
                                    logger.info("✓ LLM model unloaded for memory management")
                                except:
                                    pass
                            
                            logger.info(f"✓ Aggressive cleanup complete, memory: {psutil.virtual_memory().percent:.1f}%, trades: {len(self.best_trades)}")
                    except Exception as e:
                        logger.warning(f"Memory cleanup failed: {e}")
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in event loop: {e}")
                time.sleep(5)
        
        logger.info("Multi-instrument scanner stopped")
    
    def start(self, target_instrument=None):
        """Start the trading bot"""
        if not self.load_config():
            logger.error("Failed to load configuration")
            return False
        
        if not self.access_token:
            logger.error("No access token found in config")
            return False
        
        self.bot_running = True
        logger.info("Bot started")
        
        try:
            self.run_event_loop(target_instrument)
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.bot_running = False
            logger.info("Bot stopped")
    
    def stop(self):
        """Stop the trading bot"""
        self.bot_running = False
        logger.info("Stopping bot...")
        
        # Clean up LLM resources
        if self.llm_analyzer and hasattr(self.llm_analyzer, 'ollama'):
            try:
                self.llm_analyzer.ollama.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up LLM: {e}")
        
        # Clean up price history
        self.price_history.clear()
        logger.info("Bot stopped and cleaned up")
    
    def switch_trading_mode(self, mode: str) -> bool:
        """Switch trading mode (conservative/moderate/aggressive)"""
        if self.llm_analyzer:
            success = self.llm_analyzer.switch_mode(mode)
            if success:
                logger.info(f"Switched to {mode} trading mode")
            return success
        else:
            logger.warning("LLM analyzer not available")
            return False
    
    def switch_model(self, model_name: str) -> bool:
        """Switch Ollama model"""
        if self.llm_analyzer:
            success = self.llm_analyzer.switch_model(model_name)
            if success:
                logger.info(f"Switched to model: {model_name}")
            return success
        else:
            logger.warning("LLM analyzer not available")
            return False
    
    def trigger_market_open_analysis(self):
        """Manually trigger the 9:15 market open analysis (for testing)"""
        logger.info("Manually triggering market open analysis...")
        self.market_open_analysis_done = False  # Reset flag
        self.perform_market_open_analysis()
    
    def show_selected_strikes(self):
        """Display the selected strikes from 9:15 analysis"""
        logger.info("=" * 80)
        logger.info("SELECTED STRIKES FROM 9:15 ANALYSIS")
        logger.info("=" * 80)
        
        if not self.selected_strikes:
            logger.info("No strikes selected yet. Analysis not performed or no valid setups found.")
        else:
            for symbol, data in self.selected_strikes.items():
                logger.info(f"\n{symbol}:")
                logger.info(f"  Strike: {data['strike']}")
                logger.info(f"  Direction: {data['direction']}")
                logger.info(f"  Spot: {data['spot']}")
                logger.info(f"  Support: {data['support']}")
                logger.info(f"  Resistance: {data['resistance']}")
                logger.info(f"  Reason: {data['reason']}")
                logger.info(f"  Time: {data['timestamp']}")
        
        logger.info("=" * 80)


def main():
    """
    Main entry point with command interface.
    Event-driven: User commands control bot state.

    Command-line options:
    --observation <instrument>  Start in observation mode (no execution)
    --instrument <instrument>   Start in normal mode with specific instrument
    --interactive               Run in interactive mode (default)
    """
    bot = CleanTradingBot()

    # Parse command-line arguments
    observation_mode = False
    target_instrument = None
    interactive_mode = True

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--observation" and i + 1 < len(sys.argv):
            observation_mode = True
            target_instrument = sys.argv[i + 1].upper()
            interactive_mode = False
        elif arg == "--instrument" and i + 1 < len(sys.argv):
            target_instrument = sys.argv[i + 1].upper()
            interactive_mode = False
        elif arg == "--interactive":
            interactive_mode = True

    # Direct mode (command-line)
    if not interactive_mode:
        if observation_mode:
            bot.bot_mode = "observation"
            print(f"Starting OBSERVATION MODE for {target_instrument}")
            print("No trades will be executed - observation only")
            logger.info(f"Bot mode set to: OBSERVATION for {target_instrument}")
        else:
            print(f"Starting NORMAL MODE for {target_instrument}")
            logger.info(f"Bot mode set to: NORMAL for {target_instrument}")

        try:
            bot.start(target_instrument=target_instrument)
        except KeyboardInterrupt:
            print("\nBot stopped by user")
        return

    # Interactive mode (existing flow)
    print("=" * 80)
    print("CLEAN EVENT-DRIVEN TRADING BOT")
    print("=" * 80)
    print("Commands:")
    print("  start bot [instrument]  - Start bot (optional: NIFTY, BANKNIFTY, GOLDM, etc.)")
    print("  start observation [instrument] - Start in observation mode (no execution)")
    print("  enable paper trade     - Enable paper trading execution")
    print("  disable paper trade    - Disable paper trading execution")
    print("  status                  - Show bot status")
    print("  stop bot                - Stop bot")
    print("  mode <mode>             - Switch trading mode (conservative/moderate/aggressive)")
    print("  model <model>           - Switch Ollama model")
    print("  analyze 9:15           - Manually trigger 9:15 market open analysis")
    print("  show strikes           - Show selected strikes from 9:15 analysis")
    print("  help                    - Show available commands")
    print("  exit                    - Exit program")
    print("=" * 80)

    while True:
        try:
            user_input = input("\nCommand: ").strip().lower()
            
            if user_input == "exit":
                if bot.bot_running:
                    bot.stop()
                print("Exiting...")
                break
            
            elif user_input.startswith("start bot"):
                if bot.bot_running:
                    print("Bot is already running")
                    continue

                # Parse instrument if provided
                parts = user_input.split()
                instrument = parts[2] if len(parts) > 2 else None

                # Start bot in background
                import threading
                bot_thread = threading.Thread(target=bot.start, args=(instrument,))
                bot_thread.daemon = True
                bot_thread.start()
                print("✓ Bot started")

            elif user_input.startswith("start observation"):
                if bot.bot_running:
                    print("Bot is already running")
                    continue

                # Parse instrument if provided
                parts = user_input.split()
                instrument = parts[2] if len(parts) > 2 else None

                # Set observation mode
                bot.bot_mode = "observation"

                # Start bot in background
                import threading
                bot_thread = threading.Thread(target=bot.start, args=(instrument,))
                bot_thread.daemon = True
                bot_thread.start()
                print("✓ Bot started in OBSERVATION MODE (no execution)")
            
            elif user_input == "enable paper trade":
                bot.enable_paper_trading()
                print("✓ Paper trading enabled")

            elif user_input == "disable paper trade":
                bot.disable_paper_trading()
                print("✓ Paper trading disabled")

            elif user_input == "stop bot":
                if not bot.bot_running:
                    print("Bot is not running")
                    continue
                bot.stop()
                bot.bot_mode = "normal"  # Reset mode
                print("✓ Bot stopped")
            
            elif user_input == "status":
                bot.handle_command("status")

            elif user_input == "help":
                bot.handle_command("help")
            
            elif user_input == "analyze 9:15":
                bot.trigger_market_open_analysis()
                print("✓ 9:15 market open analysis triggered")
            
            elif user_input == "show strikes":
                bot.show_selected_strikes()

            elif user_input.startswith("mode "):
                mode = user_input.split()[1]
                success = bot.switch_trading_mode(mode)
                if success:
                    print(f"✓ Switched to {mode} mode")
                else:
                    print(f"✗ Failed to switch mode")
            
            elif user_input.startswith("model "):
                model = user_input.split()[1]
                success = bot.switch_model(model)
                if success:
                    print(f"✓ Switched to model: {model}")
                else:
                    print(f"✗ Failed to switch model")
            
            else:
                print("Unknown command. Type 'exit' to quit.")
        
        except KeyboardInterrupt:
            if bot.bot_running:
                bot.stop()
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()

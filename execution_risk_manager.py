"""
Execution & Risk Manager
-------------------------
Handles:
- Single-leg option execution only
- Fixed trailing stop-loss logic
- ₹5,000 daily target halt
- Position monitoring and exit management
- Session-based trade caps
- Entry cooldowns
- Anti-whipsaw SL cooldown
- ₹30,000 virtual wallet
- 1:5 Risk-Reward ratio

Phase 1: Simple, focused, non-blocking execution.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime, time as dt_time
import json
import os

logger = logging.getLogger(__name__)


class ExecutionRiskManager:
    """
    Execution & Risk Manager
    Manages trade execution, trailing SL, and daily profit targets.
    """
    
    def __init__(self, kite_client, daily_target=5000, start_capital=30000):
        """
        Initialize Execution & Risk Manager.
        
        Args:
            kite_client: KiteConnect client for execution
            daily_target: Daily profit target in INR (default: ₹5,000)
            start_capital: Starting virtual capital (default: ₹30,000)
        """
        self.kite_client = kite_client
        self.daily_target = daily_target
        self.start_capital = start_capital
        self.current_capital = start_capital
        
        # Active positions (single-leg only)
        self.active_positions = {}  # position_id -> position_data
        
        # Daily P&L tracking
        self.daily_pnl = 0.0
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
        self.daily_target_hit = False
        self.daily_halt_triggered = False
        
        # Position counters
        self.position_counter = 0
        self.completed_positions = []
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Trade manifest path
        self.trade_manifest_path = "active_trades.json"
        
        # RISK ARMOR: Session-based trade caps
        self.session_trades = {
            'morning': 0,   # 09:15-11:30
            'noon': 0,      # 11:30-13:30
            'afternoon': 0  # 13:30-15:30
        }
        self.max_trades_per_session = 2
        
        # RISK ARMOR: Entry cooldown (30 minutes between trades)
        self.last_trade_time = None
        self.entry_cooldown_minutes = 30
        
        # RISK ARMOR: Anti-whipsaw SL cooldown (30 minutes after SL hit)
        self.sl_cooldown_cache = {}  # symbol -> timestamp when SL was hit
        self.sl_cooldown_minutes = 30
        
        # RISK ARMOR: 1:5 Risk-Reward ratio
        self.min_risk_reward_ratio = 5.0
        
        logger.info(f"Execution & Risk Manager initialized (Daily Target: ₹{daily_target}, Capital: ₹{start_capital})")
    
    def execute_single_leg(self, signal_data: Dict[str, Any], 
                          entry_price: float, quantity: int = 1) -> Optional[str]:
        """
        Execute a single-leg option trade.
        
        Phase 1: Simple ATM/NTM directional options only.
        RISK ARMOR: Checks session caps, cooldowns, and SL penalties before execution.
        
        Args:
            signal_data: Signal data from Engine 1
            entry_price: Option premium entry price
            quantity: Number of lots (default: 1)
            
        Returns:
            Position ID if executed successfully, None otherwise
        """
        with self.lock:
            # Check if daily target already hit
            if self.daily_halt_triggered:
                logger.warning("Daily target halt triggered - cannot execute new trades")
                return None
            
            # RISK ARMOR: Check session cap
            if self.is_session_cap_reached():
                logger.warning("Session cap reached - cannot execute new trades")
                return None
            
            # RISK ARMOR: Check entry cooldown
            if self.is_entry_cooldown_active():
                logger.warning("Entry cooldown active - cannot execute new trades")
                return None
            
            # RISK ARMOR: Check SL cooldown for symbol
            symbol = signal_data.get('symbol', '')
            if self.is_symbol_in_sl_cooldown(symbol):
                logger.warning(f"Symbol {symbol} in SL cooldown - cannot execute new trades")
                return None
            
            # Generate position ID
            self.position_counter += 1
            position_id = f"POS_{self.position_counter}_{int(time.time())}"
            
            # Calculate risk management levels (1:5 Risk-Reward ratio)
            risk_amount = entry_price * 0.10  # 10% risk (tighter for 1:5 RR)
            stoploss = entry_price - risk_amount
            target = entry_price * 1.50  # 50% profit target (1:5 risk-reward)
            
            # Create position data
            position = {
                'position_id': position_id,
                'symbol': signal_data.get('symbol', ''),
                'direction': signal_data.get('direction', ''),
                'strike': signal_data.get('strike', 0),
                'option_type': 'CE' if signal_data.get('direction') == 'CALL' else 'PE',
                'entry_price': entry_price,
                'current_price': entry_price,
                'stoploss': stoploss,
                'target': target,
                'original_stoploss': stoploss,
                'highest_price': entry_price,  # For trailing SL
                'quantity': quantity,
                'entry_time': time.time(),
                'status': 'ACTIVE',
                'pnl': 0.0,
                'pnl_percentage': 0.0,
                'sl_adjustments': [],
                'signal_data': signal_data,
                'risk_reward_ratio': round((target - entry_price) / risk_amount, 2)
            }
            
            # Add to active positions
            self.active_positions[position_id] = position
            
            # RISK ARMOR: Update session trade counter
            current_session = self.get_current_session()
            if current_session:
                self.session_trades[current_session] += 1
                logger.info(f"📊 Session Trade Count: {current_session} = {self.session_trades[current_session]}/{self.max_trades_per_session}")
            
            # RISK ARMOR: Update last trade time for entry cooldown
            self.last_trade_time = datetime.now()
            
            logger.info("=" * 80)
            logger.info(f"✅ SINGLE-LEG EXECUTION: {position_id}")
            logger.info(f"Symbol: {position['symbol']} | Strike: {position['strike']} {position['option_type']}")
            logger.info(f"Direction: {position['direction']}")
            logger.info(f"Entry: ₹{entry_price:.2f} | Target: ₹{target:.2f} | SL: ₹{stoploss:.2f}")
            logger.info(f"Risk-Reward: 1:{position['risk_reward_ratio']}")
            logger.info(f"Current Capital: ₹{self.current_capital:.2f}")
            logger.info("=" * 80)
            
            # Save to trade manifest
            self._save_position_to_manifest(position)
            
            return position_id
    
    def update_position_price(self, position_id: str, current_price: float):
        """
        Update current price for a position and check exit conditions.
        
        Args:
            position_id: Position identifier
            current_price: Current option premium price
        """
        with self.lock:
            if position_id not in self.active_positions:
                return
            
            position = self.active_positions[position_id]
            position['current_price'] = current_price
            
            # Calculate P&L
            position['pnl'] = (current_price - position['entry_price']) * position['quantity']
            position['pnl_percentage'] = ((current_price - position['entry_price']) / position['entry_price']) * 100
            
            # Update highest price for trailing SL
            if current_price > position['highest_price']:
                old_highest = position['highest_price']
                position['highest_price'] = current_price
                logger.info(f"📈 New Highest Price: {position_id} | ₹{old_highest:.2f} → ₹{current_price:.2f}")
            
            # Check target hit
            if current_price >= position['target']:
                self._handle_target_hit(position_id)
                return
            
            # Check stoploss hit (with 30-second entry buffer)
            time_in_position = time.time() - position['entry_time']
            if time_in_position >= 30 and current_price <= position['stoploss']:
                self._handle_stoploss_hit(position_id)
                return
            
            # Update trailing SL if in profit
            if position['pnl_percentage'] > 10:  # Only trail if 10%+ profit
                self._update_trailing_sl(position_id)
            
            # Update daily unrealized P&L
            self._update_daily_pnl()
    
    def _update_trailing_sl(self, position_id: str):
        """
        Update trailing stop-loss to lock in profits.
        
        CRITICAL: Trailing SL only moves UP, never down.
        Based on HIGHEST price reached, not current price.
        
        Args:
            position_id: Position identifier
        """
        position = self.active_positions[position_id]
        
        # Calculate new SL: lock 25% of peak profit
        highest_price = position['highest_price']
        peak_profit_pct = ((highest_price - position['entry_price']) / position['entry_price']) * 100
        
        # Only trail if we have meaningful profit
        if peak_profit_pct < 15:
            return
        
        # Lock 25% of peak profit
        lock_in_pct = peak_profit_pct * 0.25
        new_sl = position['entry_price'] * (1 + lock_in_pct / 100)
        
        # Ensure SL is at least at breakeven
        new_sl = max(new_sl, position['entry_price'])
        
        # CRITICAL: Only move SL UP (never down)
        if new_sl > position['stoploss']:
            old_sl = position['stoploss']
            position['stoploss'] = new_sl
            
            position['sl_adjustments'].append({
                'timestamp': time.time(),
                'old_sl': old_sl,
                'new_sl': new_sl,
                'highest_price': highest_price,
                'peak_profit_pct': peak_profit_pct,
                'reason': f'Trailing SL (Peak Profit: {peak_profit_pct:.2f}%)'
            })
            
            logger.info(f"📈 SL Adjusted: {position_id} | Old SL: ₹{old_sl:.2f} → New SL: ₹{new_sl:.2f} | Peak: ₹{highest_price:.2f}")
            
            # Save to manifest
            self._save_position_to_manifest(position)
    
    def _handle_target_hit(self, position_id: str):
        """
        Handle when target price is hit.
        
        Args:
            position_id: Position identifier
        """
        position = self.active_positions[position_id]
        position['status'] = 'TARGET_HIT'
        position['exit_time'] = time.time()
        position['exit_price'] = position['current_price']
        
        # Add to completed positions
        self.completed_positions.append(position.copy())
        
        # Remove from active positions
        del self.active_positions[position_id]
        
        # Update daily P&L
        self._update_daily_pnl()
        
        logger.info("=" * 80)
        logger.info(f"🎯 TARGET HIT: {position_id}")
        logger.info(f"Symbol: {position['symbol']} | Strike: {position['strike']} {position['option_type']}")
        logger.info(f"Entry: ₹{position['entry_price']:.2f} | Exit: ₹{position['exit_price']:.2f}")
        logger.info(f"P&L: ₹{position['pnl']:.2f} ({position['pnl_percentage']:.2f}%)")
        logger.info("=" * 80)
        
        # Save to manifest
        self._save_position_to_manifest(position)
        
        # Check daily target
        self._check_daily_target()
    
    def _handle_stoploss_hit(self, position_id: str):
        """
        Handle when stoploss is hit.
        
        Args:
            position_id: Position identifier
        """
        position = self.active_positions[position_id]
        position['status'] = 'STOPLOSS_HIT'
        position['exit_time'] = time.time()
        position['exit_price'] = position['current_price']
        
        # Add symbol to SL cooldown cache (Anti-whipsaw protection)
        symbol = position['symbol']
        self.sl_cooldown_cache[symbol] = datetime.now()
        logger.info(f"🛑 SYMBOL ADDED TO SL COOLDOWN: {symbol} - 30 minutes penalty")
        
        # Add to completed positions
        self.completed_positions.append(position.copy())
        
        # Remove from active positions
        del self.active_positions[position_id]
        
        # Update daily P&L
        self._update_daily_pnl()
        
        logger.info("=" * 80)
        logger.info(f"🛑 STOPLOSS HIT: {position_id}")
        logger.info(f"Symbol: {position['symbol']} | Strike: {position['strike']} {position['option_type']}")
        logger.info(f"Entry: ₹{position['entry_price']:.2f} | Exit: ₹{position['exit_price']:.2f}")
        logger.info(f"P&L: ₹{position['pnl']:.2f} ({position['pnl_percentage']:.2f}%)")
        logger.info("=" * 80)
        
        # Save to manifest
        self._save_position_to_manifest(position)
    
    def _update_daily_pnl(self):
        """Update daily P&L calculations."""
        # Calculate realized P&L from completed positions
        realized_pnl = sum(p['pnl'] for p in self.completed_positions)
        
        # Calculate unrealized P&L from active positions
        unrealized_pnl = sum(p['pnl'] for p in self.active_positions.values())
        
        self.daily_realized_pnl = realized_pnl
        self.daily_unrealized_pnl = unrealized_pnl
        self.daily_pnl = realized_pnl + unrealized_pnl
    
    def _check_daily_target(self):
        """Check if daily target has been hit and trigger halt if needed."""
        if self.daily_pnl >= self.daily_target and not self.daily_halt_triggered:
            self.daily_target_hit = True
            self.daily_halt_triggered = True
            
            logger.info("=" * 80)
            logger.info(f"🎉 DAILY TARGET HIT: ₹{self.daily_pnl:.2f}")
            logger.info(f"Target: ₹{self.daily_target}")
            logger.info(f"Closing all positions and halting trading for the day")
            logger.info("=" * 80)
            
            # Close all active positions
            self._close_all_positions(reason="Daily target hit")
    
    def _close_all_positions(self, reason: str = "Manual close"):
        """
        Close all active positions and print performance report.
        
        Args:
            reason: Reason for closing positions
        """
        with self.lock:
            position_ids = list(self.active_positions.keys())
            
            for position_id in position_ids:
                position = self.active_positions[position_id]
                position['status'] = 'CLOSED'
                position['exit_time'] = time.time()
                position['exit_price'] = position['current_price']
                position['exit_reason'] = reason
                
                # Add to completed positions
                self.completed_positions.append(position.copy())
            
            # Clear active positions
            self.active_positions.clear()
            
            # Update daily P&L
            self._update_daily_pnl()
            
            logger.info(f"Closed all positions: {reason}")
            
            # Print performance report for shutdown
            self._print_performance_report()
    
    def get_daily_pnl(self) -> Dict[str, float]:
        """
        Get daily P&L summary with capital tracking.
        
        Returns:
            Dictionary with daily P&L breakdown and capital info
        """
        with self.lock:
            self._update_daily_pnl()
            
            # Update current capital
            self.current_capital = self.start_capital + self.daily_pnl
            
            return {
                'daily_pnl': self.daily_pnl,
                'realized_pnl': self.daily_realized_pnl,
                'unrealized_pnl': self.daily_unrealized_pnl,
                'daily_target': self.daily_target,
                'target_hit': self.daily_target_hit,
                'halt_triggered': self.daily_halt_triggered,
                'start_capital': self.start_capital,
                'current_capital': self.current_capital,
                'total_pnl': self.daily_pnl  # Alias for compatibility
            }
    
    def get_current_capital(self) -> float:
        """
        Get current virtual capital.
        
        Returns:
            Current capital amount
        """
        with self.lock:
            self._update_daily_pnl()
            self.current_capital = self.start_capital + self.daily_pnl
            return self.current_capital
    
    def get_active_positions(self) -> List[Dict[str, Any]]:
        """
        Get list of active positions.
        
        Returns:
            List of active position dictionaries
        """
        with self.lock:
            return list(self.active_positions.values())
    
    def get_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Get specific position by ID.
        
        Args:
            position_id: Position identifier
            
        Returns:
            Position dictionary or None if not found
        """
        with self.lock:
            return self.active_positions.get(position_id)
    
    def close_position(self, position_id: str, reason: str = "Manual close"):
        """
        Close a specific position and print performance report.
        
        Args:
            position_id: Position identifier
            reason: Reason for closing
        """
        with self.lock:
            if position_id not in self.active_positions:
                logger.warning(f"Position {position_id} not found")
                return
            
            position = self.active_positions[position_id]
            position['status'] = 'CLOSED'
            position['exit_time'] = time.time()
            position['exit_price'] = position['current_price']
            position['exit_reason'] = reason
            
            # Add to completed positions
            self.completed_positions.append(position.copy())
            
            # Remove from active positions
            del self.active_positions[position_id]
            
            # Update daily P&L
            self._update_daily_pnl()
            
            # Save to manifest
            self._save_position_to_manifest(position)
            
            logger.info(f"Position {position_id} closed: {reason}")
            
            # Print performance report for manual exit
            if "manual" in reason.lower():
                self._print_performance_report()
    
    def get_current_session(self, current_time=None):
        """
        Determine which session we're in based on time.
        
        Args:
            current_time: datetime object or None (uses current time)
            
        Returns:
            Session name ('morning', 'noon', 'afternoon', or None)
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Handle both datetime and timestamp inputs
        if isinstance(current_time, (int, float)):
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
    
    def is_session_cap_reached(self, current_time=None):
        """
        Check if we've hit the session trade cap.
        
        Args:
            current_time: datetime object or None (uses current time)
            
        Returns:
            True if session cap reached, False otherwise
        """
        current_session = self.get_current_session(current_time)
        if current_session and self.session_trades[current_session] >= self.max_trades_per_session:
            logger.warning(f"🛑 SESSION CAP REACHED: {current_session} session has {self.session_trades[current_session]}/{self.max_trades_per_session} trades")
            return True
        return False
    
    def is_entry_cooldown_active(self, current_time=None):
        """
        Check if we're in the 30-minute entry cooldown period.
        
        Args:
            current_time: datetime object or None (uses current time)
            
        Returns:
            True if cooldown active, False otherwise
        """
        if current_time is None:
            current_time = datetime.now()
        
        if self.last_trade_time:
            time_since_last_trade = current_time - self.last_trade_time
            cooldown_seconds = self.entry_cooldown_minutes * 60
            if time_since_last_trade.total_seconds() < cooldown_seconds:
                minutes_left = int((cooldown_seconds - time_since_last_trade.total_seconds()) / 60)
                logger.warning(f"🛑 ENTRY COOL-DOWN ACTIVE: {minutes_left} minutes remaining before next trade")
                return True
        return False
    
    def is_symbol_in_sl_cooldown(self, symbol, current_time=None):
        """
        Check if a symbol is currently serving a penalty for hitting Stop Loss.
        
        Args:
            symbol: Instrument symbol
            current_time: datetime object or None (uses current time)
            
        Returns:
            True if symbol is in SL cooldown, False otherwise
        """
        if current_time is None:
            current_time = datetime.now()
        
        if symbol in self.sl_cooldown_cache:
            sl_hit_time = self.sl_cooldown_cache[symbol]
            time_since_sl = current_time - sl_hit_time
            cooldown_seconds = self.sl_cooldown_minutes * 60
            
            if time_since_sl.total_seconds() < cooldown_seconds:
                minutes_left = int((cooldown_seconds - time_since_sl.total_seconds()) / 60)
                logger.warning(f"🛑 SYMBOL IN SL COOLDOWN: {symbol} - {minutes_left} minutes remaining")
                return True
            else:
                # Cooldown expired, remove from cache
                del self.sl_cooldown_cache[symbol]
                logger.info(f"✅ SL COOLDOWN EXPIRED: {symbol} - eligible for trading again")
        
        return False
    
    def _save_position_to_manifest(self, position: Dict[str, Any]):
        """
        Save position data to trade manifest.
        
        Args:
            position: Position dictionary
        """
        try:
            # Load existing manifest
            if os.path.exists(self.trade_manifest_path):
                with open(self.trade_manifest_path, 'r') as f:
                    manifest = json.load(f)
            else:
                manifest = {
                    "system_metadata": {
                        "engine_id": "phase1_2engine",
                        "automated_mode": True,
                        "architecture": "2-engine"
                    },
                    "trades": [],
                    "capital_manager": {
                        "starting_virtual_capital": 30000,
                        "current_active_balance": 30000,
                        "investment_vault_balance": 0,
                        "consecutive_wins": 0,
                        "consecutive_losses": 0,
                        "current_session_lots": 1
                    }
                }
            
            # Convert position to manifest format
            trade_entry = {
                "trade_id": position['position_id'],
                "timestamp": datetime.fromtimestamp(position['entry_time']).isoformat(),
                "underlying": position['symbol'],
                "strike_price": position['strike'],
                "option_type": position['option_type'],
                "status": position['status'],
                "execution": {
                    "entry_price": position['entry_price'],
                    "current_price": position['current_price'],
                    "highest_price_reached": position['highest_price'],
                    "initial_stoploss": position['original_stoploss'],
                    "current_stoploss": position['stoploss'],
                    "take_profit": position['target'],
                    "risk_reward_ratio": position['risk_reward_ratio']
                },
                "pnl": position['pnl'],
                "pnl_percentage": position['pnl_percentage']
            }
            
            # Add or update trade
            trade_found = False
            for i, trade in enumerate(manifest['trades']):
                if trade['trade_id'] == position['position_id']:
                    manifest['trades'][i] = trade_entry
                    trade_found = True
                    break
            
            if not trade_found:
                manifest['trades'].append(trade_entry)
            
            # Save manifest
            with open(self.trade_manifest_path, 'w') as f:
                json.dump(manifest, f, indent=4)
            
        except Exception as e:
            logger.error(f"Error saving position to manifest: {e}")
    
    def print_position_summary(self):
        """Print summary of all positions."""
        with self.lock:
            print("\n" + "=" * 100)
            print("📊 POSITION SUMMARY")
            print("=" * 100)
            
            # Daily P&L
            pnl_summary = self.get_daily_pnl()
            print(f"\nDaily P&L: ₹{pnl_summary['daily_pnl']:.2f} (Target: ₹{pnl_summary['daily_target']})")
            print(f"Realized: ₹{pnl_summary['realized_pnl']:.2f} | Unrealized: ₹{pnl_summary['unrealized_pnl']:.2f}")
            print(f"Target Hit: {pnl_summary['target_hit']} | Halt Triggered: {pnl_summary['halt_triggered']}")
            
            # Active positions
            if self.active_positions:
                print(f"\n📈 Active Positions: {len(self.active_positions)}")
                print(f"{'ID':<20} {'Symbol':<10} {'Option':<12} {'Entry':<10} {'Current':<10} {'Target':<10} {'SL':<10} {'P&L (₹)':<10} {'P&L %':<8}")
                print("-" * 100)
                
                for pos_id, pos in self.active_positions.items():
                    option_str = f"{pos['strike']} {pos['option_type']}"
                    pnl_str = f"₹{pos['pnl']:.2f}"
                    pnl_pct_str = f"{pos['pnl_percentage']:.2f}%"
                    
                    print(f"{pos_id:<20} {pos['symbol']:<10} {option_str:<12} {pos['entry_price']:<10.2f} {pos['current_price']:<10.2f} {pos['target']:<10.2f} {pos['stoploss']:<10.2f} {pnl_str:<10} {pnl_pct_str:<8}")
            else:
                print("\nNo active positions")
            
            # Completed positions
            if self.completed_positions:
                print(f"\n✅ Completed Positions: {len(self.completed_positions)}")
    
    def _print_performance_report(self):
        """Print detailed performance report for manual exit or shutdown."""
        with self.lock:
            self._update_daily_pnl()
            
            logger.info("=" * 100)
            logger.info("📊 PERFORMANCE REPORT")
            logger.info("=" * 100)
            
            # Trade statistics
            total_trades = len(self.completed_positions)
            winning_trades = sum(1 for p in self.completed_positions if p['pnl'] > 0)
            losing_trades = sum(1 for p in self.completed_positions if p['pnl'] < 0)
            breakeven_trades = sum(1 for p in self.completed_positions if p['pnl'] == 0)
            
            logger.info(f"\n📈 TRADE STATISTICS:")
            logger.info(f"  Total Trades:        {total_trades}")
            logger.info(f"  Winning Trades:      {winning_trades}")
            logger.info(f"  Losing Trades:       {losing_trades}")
            logger.info(f"  Breakeven Trades:    {breakeven_trades}")
            
            if total_trades > 0:
                win_rate = (winning_trades / total_trades) * 100
                logger.info(f"  Win Rate:           {win_rate:.2f}%")
            
            # P&L from 30K wallet
            pnl_summary = self.get_daily_pnl()
            logger.info(f"\n💰 WALLET PERFORMANCE (₹30,000 Starting Capital):")
            logger.info(f"  Starting Capital:   ₹{self.start_capital:.2f}")
            logger.info(f"  Current Capital:    ₹{pnl_summary['current_capital']:.2f}")
            logger.info(f"  Total P&L:          ₹{pnl_summary['daily_pnl']:.2f}")
            logger.info(f"  Realized P&L:       ₹{pnl_summary['realized_pnl']:.2f}")
            logger.info(f"  Unrealized P&L:     ₹{pnl_summary['unrealized_pnl']:.2f}")
            logger.info(f"  Daily Target:       ₹{pnl_summary['daily_target']:.2f}")
            logger.info(f"  Target Hit:         {pnl_summary['target_hit']}")
            
            # Contract breakdown
            if self.completed_positions:
                logger.info(f"\n📋 CONTRACT BREAKDOWN:")
                logger.info(f"{'Symbol':<12} {'Type':<8} {'Strike':<10} {'Entry':<10} {'Exit':<10} {'P&L (₹)':<12} {'Status':<15}")
                logger.info("-" * 100)
                
                for pos in self.completed_positions:
                    symbol = pos['symbol']
                    option_type = pos['option_type']
                    strike = pos['strike']
                    entry = pos['entry_price']
                    exit_price = pos.get('exit_price', pos['current_price'])
                    pnl = pos['pnl']
                    status = pos['status']
                    quantity = pos.get('quantity', 1)
                    
                    logger.info(f"{symbol:<12} {option_type:<8} {strike:<10} {entry:<10.2f} {exit_price:<10.2f} {pnl:<12.2f} {status:<15} ({quantity} lot)")
            
            logger.info("=" * 100)

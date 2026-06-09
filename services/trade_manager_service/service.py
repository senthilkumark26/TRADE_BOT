"""
Trade Manager Service - Live trade execution and management
Manages: Active trades, P&L tracking, trailing SL, kill switch, live dashboard
NOW WITH: External dashboard support via JSON file
"""

import logging
import json
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class TradeManagerService:
    """
    Trade Manager Service - Live trade execution and management.
    
    Manages:
    - Active trades tracking
    - P&L calculation
    - Trailing stop-loss
    - Kill switch (daily loss control)
    - Live dashboard rendering
    """
    
    def __init__(self, max_daily_loss=3000, config=None):
        """
        Initialize the Trade Manager Service.
        
        Args:
            max_daily_loss: Maximum daily loss limit
            config: Config dict for lot sizes
        """
        self.service_name = "trade_manager_service"
        self.version = "1.1.0"  # Upgraded for external dashboard support
        self.dependencies = []
        self.dependents = ["trading_bot"]
        self.protection_level = "CRITICAL"
        
        self.active_trades = {}
        self.closed_trades = []
        self.total_pnl = 0
        self.max_daily_loss = -abs(max_daily_loss)
        self.trading_enabled = True
        self.config = config or {}
        
        # External dashboard support
        self.dashboard_data_file = "dashboard_data.json"
        
        logger.info(f"Trade Manager Service initialized (v{self.version})")
        logger.info(f"Max Daily Loss: {self.max_daily_loss}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"External Dashboard: {self.dashboard_data_file}")
    
    def add_trade(self, symbol: str, trade: Dict):
        """
        Add new trade to active trades.
        
        Args:
            symbol: Trading symbol
            trade: Trade dictionary with entry, signal, strike, etc.
        """
        if not self.trading_enabled:
            logger.warning(f"[TRADE MANAGER] Trading disabled - cannot add trade for {symbol}")
            return False
        
        # Use lot_size from trade dict, fallback to config, then default to 50
        lot_size = trade.get('lot_size', self.config.get('instruments', {}).get(symbol, {}).get('lot_size', 50))
        
        self.active_trades[symbol] = {
            **trade,
            "ltp": trade["entry"],
            "pnl": 0,
            "status": "RUNNING",
            "lot_size": lot_size,
            "entry_time": datetime.now().isoformat(),
            "expiry": trade.get('expiry', 'N/A')  # Store expiry date
        }
        
        logger.info(f"[TRADE MANAGER] Trade added: {symbol} {trade['signal']} @ {trade['entry']} (Expiry: {trade.get('expiry', 'N/A')}, Lot Size: {lot_size})")
        
        # Update external dashboard
        self._write_dashboard_data()
        
        return True
    
    def update_price(self, symbol: str, ltp: float):
        """
        Update live price and calculate P&L.
        
        Args:
            symbol: Trading symbol
            ltp: Current LTP
        """
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        entry = trade["entry"]
        lot_size = trade.get("lot_size", 50)
        
        # CRITICAL FIX: When BUYING options (both CALL and PUT), P&L is always (current - entry)
        # Whether CALL or PUT, if we're buying the option, we profit when premium increases
        # The difference is what makes the premium increase (underlying up for CALL, down for PUT)
        # But for P&L calculation, it's always: (current premium - entry premium) * lot_size
        pnl = (ltp - entry) * lot_size
        
        trade["ltp"] = ltp
        trade["pnl"] = pnl
        
        # Update external dashboard
        self._write_dashboard_data()
        
        # Trailing SL
        self._update_trailing_sl(symbol)
        
        # Check exit conditions
        self._check_exit(symbol)
    
    def _update_trailing_sl(self, symbol: str):
        """
        Update trailing stop-loss logic.
        
        Args:
            symbol: Trading symbol
        """
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        entry = trade["entry"]
        ltp = trade["ltp"]
        sl = trade.get("sl", 0)
        
        if sl == 0:
            return
        
        # CRITICAL FIX: When BUYING options (both CALL and PUT), we always want premium to go UP
        # So trailing SL should always trail UPWARD, regardless of CALL/PUT
        # Move SL to cost when 20% profit
        if ltp >= entry * 1.2:
            trade["tsl"] = entry
            logger.info(f"[TRADE MANAGER] {symbol} Trailing SL moved to cost: {entry}")
        
        # Lock profit when 40% profit
        if ltp >= entry * 1.4:
            trade["tsl"] = entry * 1.2
            logger.info(f"[TRADE MANAGER] {symbol} Trailing SL locked at profit: {entry * 1.2}")
    
    def _check_exit(self, symbol: str):
        """
        Check exit conditions (SL, target).
        
        Args:
            symbol: Trading symbol
        """
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        ltp = trade["ltp"]
        sl = trade.get("tsl", trade.get("sl", 0))
        target = trade.get("target", 0)
        signal = trade.get("signal", "CALL")
        
        if sl == 0 and target == 0:
            return
        
        # CRITICAL FIX: When BUYING options (both CALL and PUT), we always want premium to INCREASE
        # Whether it's a CALL or PUT, if we're buying the option, we want the premium to go up
        # The difference is in what makes the premium go up (underlying up for CALL, down for PUT)
        # But for exit conditions, we always want:
        # - Target hit when premium goes UP (ltp >= target)
        # - Stop loss hit when premium goes DOWN (ltp <= sl)
        
        # Check SL (premium went down too much)
        if sl > 0 and ltp <= sl:
            logger.info(f"[TRADE MANAGER] {symbol} Stop Loss hit: {ltp} <= {sl}")
            self._close_trade(symbol, "STOP LOSS")
            return
        
        # Check Target (premium went up as desired)
        if target > 0 and ltp >= target:
            logger.info(f"[TRADE MANAGER] {symbol} Target hit: {ltp} >= {target}")
            self._close_trade(symbol, "TARGET")
            return
    
    def _close_trade(self, symbol: str, reason: str = "MANUAL"):
        """
        Internal method to close trade.
        
        Args:
            symbol: Trading symbol
            reason: Reason for closing
        """
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades.pop(symbol)
        trade["status"] = "CLOSED"
        trade["close_reason"] = reason
        trade["close_time"] = datetime.now().isoformat()
        
        self.closed_trades.append(trade)
        self.total_pnl += trade["pnl"]
        
        logger.info(f"[TRADE MANAGER] Trade closed: {symbol} P&L: {trade['pnl']:.2f} Reason: {reason}")
        
        # Update universal risk manager with P&L (same as single_strike_trader)
        try:
            from wrappers.risk_wrapper import update_trade_result
            update_trade_result(trade["pnl"])
            logger.info(f"[TRADE MANAGER] Universal risk manager updated with P&L: {trade['pnl']:.2f}")
        except Exception as e:
            logger.warning(f"[TRADE MANAGER] Failed to update universal risk manager: {e}")
        
        # Update external dashboard
        self._write_dashboard_data()
        
        # Kill switch
        if self.total_pnl <= self.max_daily_loss:
            self.trading_enabled = False
            logger.error(f"[TRADE MANAGER] KILL SWITCH ACTIVATED - Total P&L: {self.total_pnl} <= Max Loss: {self.max_daily_loss}")
    
    def get_dashboard_data(self) -> Dict:
        """
        Get dashboard data for rendering.
        
        Returns:
            Dictionary with active trades and totals
        """
        return {
            "active": self.active_trades,
            "closed": self.closed_trades,
            "total_pnl": self.total_pnl,
            "max_daily_loss": self.max_daily_loss,
            "status": "STOPPED" if not self.trading_enabled else "ACTIVE",
            "last_update": datetime.now().isoformat()
        }
    
    def get_closed_trade(self, symbol: str) -> Optional[Dict]:
        """
        Get the most recently closed trade for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Trade dictionary or None if not found
        """
        # Search closed trades in reverse order (most recent first)
        for trade in reversed(self.closed_trades):
            if trade.get("symbol") == symbol:
                return trade
        return None
    
    def _write_dashboard_data(self):
        """Write dashboard data to JSON file for external viewer"""
        try:
            data = self.get_dashboard_data()
            with open(self.dashboard_data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing dashboard data: {e}")
    
    def render_dashboard(self):
        """Render live trade dashboard"""
        import os
        import sys
        
        # Clear screen for better visibility
        os.system('cls' if os.name == 'nt' else 'clear')
        
        data = self.get_dashboard_data()
        trades = data["active"]
        
        print("\n" + "=" * 84)
        print(" LIVE TRADE DASHBOARD (WITH TRADE MANAGER)")
        print("=" * 84)
        
        if not trades:
            print("NO ACTIVE TRADES - SYSTEM SCANNING FOR OPPORTUNITIES...")
        else:
            print(f"{'SYM':<8}{'SIG':<6}{'STRIKE':<12}{'EXPIRY':<12}{'ENTRY':<8}{'LTP':<8}{'P&L':<10}{'SL':<8}{'TSL':<8}{'TGT':<8}{'STATUS':<10}")
            print("-" * 84)
            
            for symbol, t in trades.items():
                tsl = t.get('tsl', t.get('sl', 0))
                print(f"{symbol:<8}{t['signal']:<6}{t['strike']:<12}{t.get('expiry', 'N/A'):<12}{t['entry']:<8.2f}{t['ltp']:<8.2f}{t['pnl']:<10.2f}{t.get('sl', 0):<8.2f}{tsl:<8.2f}{t.get('target', 0):<8.2f}{t['status']:<10}")
        
        print("-" * 84)
        print(f"TOTAL P&L: {data['total_pnl']:.2f}")
        print(f"MAX LOSS LIMIT: {data['max_daily_loss']:.2f}")
        print(f"STATUS: {data['status']}")
        print("=" * 84)
        
        # Force flush to ensure dashboard appears immediately
        sys.stdout.flush()
    
    def get_service_info(self) -> Dict:
        """Get service information for service discovery"""
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "trade_management",
                "pnl_tracking",
                "trailing_sl",
                "kill_switch",
                "dashboard_rendering"
            ]
        }

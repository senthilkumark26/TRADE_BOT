"""
State Manager - Centralized state management for trading system
Stores and provides real-time market data from WebSocket
"""

import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


class StateManager:
    """
    State Manager for centralized data storage.
    
    Manages:
    - Real-time price history
    - Open Interest (OI) data
    - Volume data
    - Trade state
    - System status
    """
    
    def __init__(self, max_history=100):
        """
        Initialize State Manager.
        
        Args:
            max_history: Maximum number of data points to keep per symbol
        """
        self.max_history = max_history
        
        # Price history: symbol -> deque of prices
        self.price_history = {}
        
        # OI history: symbol -> deque of OI values
        self.oi_history = {}
        
        # Volume history: symbol -> deque of volume values
        self.volume_history = {}
        
        # Latest data cache
        self.latest_prices = {}
        self.latest_oi = {}
        self.latest_volume = {}
        
        # Trade state
        self.current_trade = None
        self.trade_active = False
        
        # System status
        self.websocket_connected = False
        self.last_update = None
        
        logger.info(f"State Manager initialized (max_history: {max_history})")
    
    # -------------------------
    # UPDATE PRICE
    # -------------------------
    def update_price(self, symbol, price):
        """
        Update price for symbol.
        
        Args:
            symbol: Trading symbol
            price: Current price
        """
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history)
        
        self.price_history[symbol].append(price)
        self.latest_prices[symbol] = price
        self.last_update = datetime.now()
    
    # -------------------------
    # UPDATE OI
    # -------------------------
    def update_oi(self, symbol, oi):
        """
        Update Open Interest for symbol.
        
        Args:
            symbol: Trading symbol
            oi: Open Interest value
        """
        if symbol not in self.oi_history:
            self.oi_history[symbol] = deque(maxlen=self.max_history)
        
        self.oi_history[symbol].append(oi)
        self.latest_oi[symbol] = oi
    
    # -------------------------
    # UPDATE VOLUME
    # -------------------------
    def update_volume(self, symbol, volume):
        """
        Update volume for symbol.
        
        Args:
            symbol: Trading symbol
            volume: Volume value
        """
        if symbol not in self.volume_history:
            self.volume_history[symbol] = deque(maxlen=self.max_history)
        
        self.volume_history[symbol].append(volume)
        self.latest_volume[symbol] = volume
    
    # -------------------------
    # GET LATEST PRICE
    # -------------------------
    def get_latest_price(self, symbol):
        """
        Get latest price for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Latest price or None if not available
        """
        return self.latest_prices.get(symbol)
    
    # -------------------------
    # GET PRICE HISTORY
    # -------------------------
    def get_price_history(self, symbol, count=None):
        """
        Get price history for symbol.
        
        Args:
            symbol: Trading symbol
            count: Number of recent prices to return (None for all)
            
        Returns:
            List of prices
        """
        if symbol not in self.price_history:
            return []
        
        history = list(self.price_history[symbol])
        if count:
            return history[-count:]
        return history
    
    # -------------------------
    # GET LATEST OI
    # -------------------------
    def get_latest_oi(self, symbol):
        """
        Get latest OI for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Latest OI or None if not available
        """
        return self.latest_oi.get(symbol)
    
    # -------------------------
    # GET LATEST VOLUME
    # -------------------------
    def get_latest_volume(self, symbol):
        """
        Get latest volume for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Latest volume or None if not available
        """
        return self.latest_volume.get(symbol)
    
    # -------------------------
    # SET TRADE STATE
    # -------------------------
    def set_trade_state(self, trade_data):
        """
        Set current trade state.
        
        Args:
            trade_data: Dictionary with trade information
        """
        self.current_trade = trade_data
        self.trade_active = True
        logger.info(f"Trade state updated: {trade_data}")
    
    # -------------------------
    # CLEAR TRADE STATE
    # -------------------------
    def clear_trade_state(self):
        """Clear current trade state"""
        self.current_trade = None
        self.trade_active = False
        logger.info("Trade state cleared")
    
    # -------------------------
    # GET TRADE STATE
    # -------------------------
    def get_trade_state(self):
        """Get current trade state"""
        return self.current_trade
    
    # -------------------------
    # IS TRADE ACTIVE
    # -------------------------
    def is_trade_active(self):
        """Check if trade is active"""
        return self.trade_active
    
    # -------------------------
    # SET WEBSOCKET STATUS
    # -------------------------
    def set_websocket_connected(self, connected):
        """
        Set WebSocket connection status.
        
        Args:
            connected: Boolean connection status
        """
        self.websocket_connected = connected
        logger.info(f"WebSocket status: {'Connected' if connected else 'Disconnected'}")
    
    # -------------------------
    # IS WEBSOCKET CONNECTED
    # -------------------------
    def is_websocket_connected(self):
        """Check if WebSocket is connected"""
        return self.websocket_connected
    
    # -------------------------
    # GET LAST UPDATE TIME
    # -------------------------
    def get_last_update(self):
        """Get last data update time"""
        return self.last_update
    
    # -------------------------
    # GET ALL SYMBOLS
    # -------------------------
    def get_all_symbols(self):
        """Get all symbols with data"""
        return list(self.price_history.keys())
    
    # -------------------------
    # CLEAR SYMBOL DATA
    # -------------------------
    def clear_symbol_data(self, symbol):
        """
        Clear all data for a symbol.
        
        Args:
            symbol: Trading symbol
        """
        if symbol in self.price_history:
            del self.price_history[symbol]
        if symbol in self.oi_history:
            del self.oi_history[symbol]
        if symbol in self.volume_history:
            del self.volume_history[symbol]
        if symbol in self.latest_prices:
            del self.latest_prices[symbol]
        if symbol in self.latest_oi:
            del self.latest_oi[symbol]
        if symbol in self.latest_volume:
            del self.latest_volume[symbol]
        
        logger.info(f"Cleared data for symbol: {symbol}")
    
    # -------------------------
    # GET SYSTEM STATUS
    # -------------------------
    def get_system_status(self):
        """
        Get overall system status.
        
        Returns:
            Dictionary with system status information
        """
        return {
            "websocket_connected": self.websocket_connected,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "symbols_tracked": len(self.price_history),
            "trade_active": self.trade_active,
            "current_trade": self.current_trade
        }

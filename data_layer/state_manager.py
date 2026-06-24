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
        
        # Subscription tracking for diagnostics
        self.subscribed_tokens = set()
        self.first_tick_timestamps = {}  # token -> first tick timestamp
        self.first_tick_received = set()  # tokens that have received first tick (for monitor visibility)
        self.last_tick_timestamps = {}   # token -> last tick timestamp
        self.subscription_timestamps = {}  # token -> subscription timestamp
        self.tick_counts = {}  # token -> list of tick timestamps
        
        # Trade state
        self.current_trade = None
        self.trade_active = False
        
        # Active trades for Pro Monitor UI (multiple trades support)
        self.active_trades = []  # List of active trade records
        
        # System status
        self.websocket_connected = False
        self.last_update = None
        
        logger.info(f"State Manager initialized (max_history: {max_history})")
    
    # -------------------------
    # SUBSCRIPTION TRACKING
    # -------------------------
    def track_subscription(self, token):
        """
        Track when a token is subscribed to WebSocket.
        
        Args:
            token: Instrument token ID
        """
        self.subscribed_tokens.add(token)
        self.subscription_timestamps[token] = datetime.now()
        logger.debug(f"[SUBSCRIPTION] Token {token} subscribed at {datetime.now().strftime('%H:%M:%S.%f')}")
    
    def track_tick(self, token):
        """
        Track when a tick is received for a token.
        
        Args:
            token: Instrument token ID
        """
        current_time = datetime.now()
        self.last_tick_timestamps[token] = current_time
        
        if token not in self.first_tick_timestamps:
            self.first_tick_timestamps[token] = current_time
            self.first_tick_received.add(token)  # CRITICAL: Add to set for monitor visibility
            delay = (current_time - self.subscription_timestamps.get(token, current_time)).total_seconds() * 1000
            logger.debug(f"[WS TICK] Token {token} received FIRST tick after {delay:.0f}ms")
        else:
            # Log every 10th tick to avoid spam
            tick_count = len(self.tick_counts.get(token, []))
            if tick_count % 10 == 0:
                logger.debug(f"[WS TICK] Token {token} received tick #{tick_count}")
        
        # Track tick count
        if token not in self.tick_counts:
            self.tick_counts[token] = []
        self.tick_counts[token].append(current_time)
    
    def is_token_receiving_ticks(self, token):
        """
        Check if a token is receiving ticks.
        
        Args:
            token: Instrument token ID
            
        Returns:
            bool: True if token has received at least one tick
        """
        return token in self.first_tick_timestamps
    
    def get_token_tick_status(self, token):
        """
        Get tick status for a token.
        
        Args:
            token: Instrument token ID
            
        Returns:
            dict: Tick status information
        """
        if token not in self.first_tick_timestamps:
            return {
                "status": "NO_TICK",
                "tick_count": 0,
                "last_tick": None,
                "first_tick": None,
                "time_since_last_tick": None
            }
        
        now = datetime.now()
        last_tick = self.last_tick_timestamps.get(token)
        first_tick = self.first_tick_timestamps.get(token)
        time_since_last_tick = (now - last_tick).total_seconds() if last_tick else None
        
        return {
            "status": "RECEIVING" if time_since_last_tick < 5 else "STALE",
            "tick_count": len(self.tick_counts.get(token, [])),
            "last_tick": last_tick.strftime('%H:%M:%S') if last_tick else None,
            "first_tick": first_tick.strftime('%H:%M:%S') if first_tick else None,
            "time_since_last_tick": time_since_last_tick
        }
    
    # -------------------------
    # UPDATE PRICE
    # -------------------------
    def update_price(self, symbol, price, token=None):
        """
        Update price for symbol.
        
        Args:
            symbol: Trading symbol
            price: Current price
            token: Optional instrument token (for tick tracking)
        """
        # Track tick timing by token if provided
        if token:
            self.track_tick(token)
        else:
            self.track_tick(symbol)
        
        # FIX: Add debug log to track cache updates
        old_price = self.latest_prices.get(symbol, None)
        if old_price != price:
            logger.debug(f"[CACHE UPDATE] Price updated: {symbol} {old_price} -> {price} at {datetime.now().strftime('%H:%M:%S')}")
        else:
            logger.debug(f"[CACHE UPDATE] Price unchanged: {symbol} {price} at {datetime.now().strftime('%H:%M:%S')}")
        
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
        # Track tick timing
        self.track_tick(symbol)
        
        # FIX: Add debug log to track cache updates
        old_oi = self.latest_oi.get(symbol, None)
        if old_oi != oi:
            logger.debug(f"[CACHE UPDATE] OI updated: {symbol} {old_oi} -> {oi} at {datetime.now().strftime('%H:%M:%S')}")
        else:
            logger.debug(f"[CACHE UPDATE] OI unchanged: {symbol} {oi} at {datetime.now().strftime('%H:%M:%S')}")
        
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
    def get_latest_price(self, symbol, context=None):
        """
        Get latest price for symbol with diagnostic logging.
        
        Args:
            symbol: Trading symbol (instrument token)
            context: Optional dict with additional info (symbol_name, strike, option_type, etc.)
            
        Returns:
            Latest price or None if not available
        """
        # FIX: Add enhanced diagnostic logging
        price = self.latest_prices.get(symbol)
        
        if price is not None:
            logger.debug(f"[CACHE ACCESS] Price accessed: {symbol} = {price} at {datetime.now().strftime('%H:%M:%S')}")
        else:
            # Enhanced diagnostic logging for missing price
            classification = self._classify_missing_token(symbol)
            
            # RUNTIME FIX: Reduce warning spam - only warn for subscribed tokens with no data
            if classification == "SUBSCRIBED_BUT_NO_TICK_YET":
                log_level = logger.info
                log_msg = f"[DATA WAIT] Price not ready yet: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            elif classification == "NO_DATA_YET":
                log_level = logger.info
                log_msg = f"[DATA WAIT] Price waiting for data: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            elif classification == "NOT_SUBSCRIBED":
                # RUNTIME FIX: Use debug level for non-subscribed tokens (normal, not an error)
                log_level = logger.debug
                log_msg = f"[WS CACHE] Token not subscribed: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            else:
                # Only warn if subscribed but still no data (actual problem)
                log_level = logger.warning
                log_msg = f"[CACHE ACCESS] Price NOT FOUND: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            
            if context:
                context_str = f" | Symbol: {context.get('symbol_name', 'N/A')} | Strike: {context.get('strike', 'N/A')} | Type: {context.get('option_type', 'N/A')}"
                log_msg += context_str
            
            log_msg += f" | Classification: {classification}"
            
            # Add timing info if subscribed
            if symbol in self.subscribed_tokens:
                sub_time = self.subscription_timestamps.get(symbol)
                first_tick = self.first_tick_timestamps.get(symbol)
                last_tick = self.last_tick_timestamps.get(symbol)
                
                if sub_time:
                    log_msg += f" | Subscribed: {sub_time.strftime('%H:%M:%S.%f')}"
                if first_tick:
                    delay = (first_tick - sub_time).total_seconds() * 1000 if sub_time else 0
                    log_msg += f" | First tick delay: {delay:.0f}ms"
                if last_tick:
                    log_msg += f" | Last tick: {last_tick.strftime('%H:%M:%S.%f')}"
            
            log_level(log_msg)
        
        return price
    
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
    def get_latest_oi(self, symbol, context=None):
        """
        Get latest OI for symbol with diagnostic logging.
        
        Args:
            symbol: Trading symbol (instrument token)
            context: Optional dict with additional info (symbol_name, strike, option_type, etc.)
            
        Returns:
            Latest OI or None if not available
        """
        # FIX: Add enhanced diagnostic logging
        oi = self.latest_oi.get(symbol)
        
        if oi is not None:
            logger.debug(f"[CACHE ACCESS] OI accessed: {symbol} = {oi} at {datetime.now().strftime('%H:%M:%S')}")
        else:
            # Enhanced diagnostic logging for missing OI
            classification = self._classify_missing_token(symbol)
            
            # RUNTIME FIX: Reduce warning spam - only warn for subscribed tokens with no data
            if classification == "SUBSCRIBED_BUT_NO_TICK_YET":
                log_level = logger.info
                log_msg = f"[DATA WAIT] OI not ready yet: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            elif classification == "NO_DATA_YET":
                log_level = logger.info
                log_msg = f"[DATA WAIT] OI waiting for data: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            elif classification == "NOT_SUBSCRIBED":
                # RUNTIME FIX: Use debug level for non-subscribed tokens (normal, not an error)
                log_level = logger.debug
                log_msg = f"[WS CACHE] Token not subscribed: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            else:
                # Only warn if subscribed but still no data (actual problem)
                log_level = logger.warning
                log_msg = f"[CACHE ACCESS] OI NOT FOUND: {symbol} at {datetime.now().strftime('%H:%M:%S')}"
            
            if context:
                context_str = f" | Symbol: {context.get('symbol_name', 'N/A')} | Strike: {context.get('strike', 'N/A')} | Type: {context.get('option_type', 'N/A')}"
                log_msg += context_str
            
            log_msg += f" | Classification: {classification}"
            
            # Add timing info if subscribed
            if symbol in self.subscribed_tokens:
                sub_time = self.subscription_timestamps.get(symbol)
                first_tick = self.first_tick_timestamps.get(symbol)
                last_tick = self.last_tick_timestamps.get(symbol)
                
                if sub_time:
                    log_msg += f" | Subscribed: {sub_time.strftime('%H:%M:%S.%f')}"
                if first_tick:
                    delay = (first_tick - sub_time).total_seconds() * 1000 if sub_time else 0
                    log_msg += f" | First tick delay: {delay:.0f}ms"
                if last_tick:
                    log_msg += f" | Last tick: {last_tick.strftime('%H:%M:%S.%f')}"
            
            log_level(log_msg)
        
        return oi
    
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
    # ADD TRADE (Pro Monitor UI)
    # -------------------------
    def add_trade(self, trade_record):
        """
        Add trade to active trades list for Pro Monitor UI.
        
        Args:
            trade_record: Dictionary with trade information
        """
        # Simple append - no validation, no logging, just store
        self.active_trades.append(trade_record)
    
    # -------------------------
    # UPDATE TRADE
    # -------------------------
    def update_trade(self, instrument_token, current_price, is_stale=False):
        """
        Update trade with current price and calculate P&L.
        
        Args:
            instrument_token: Instrument token ID
            current_price: Current market price
            is_stale: Whether price is from WebSocket (False) or fallback (True)
        """
        for trade in self.active_trades:
            if trade.get('instrument_token') == instrument_token:
                old_price = trade.get('current_price', trade.get('entry_price'))
                trade['current_price'] = current_price
                trade['is_stale'] = is_stale
                
                # CRITICAL: Update entry_source to LIVE when WebSocket ticks arrive
                # This handles STALE entries that later become LIVE
                if not is_stale and trade.get('entry_source') == 'STALE':
                    trade['entry_source'] = 'LIVE'
                    logger.debug(f"[ENTRY SOURCE UPDATE] {trade.get('symbol')} updated from STALE to LIVE")
                
                # Calculate P&L
                # For long option positions (buying CE/PE), PnL is same for both types:
                # Profit when premium increases, loss when premium decreases
                entry_price = trade.get('entry_price', 0)
                quantity = trade.get('quantity', 1)
                
                pnl = (current_price - entry_price) * quantity
                
                trade['pnl'] = pnl
                logger.debug(f"[UI UPDATE] {trade.get('symbol')} LTP: Rs.{current_price}, PnL: Rs.{pnl:.2f} (Previous: Rs.{old_price}), Source: {trade.get('entry_source')}")
                return True
        
        return False
    
    # -------------------------
    # GET ACTIVE TRADES
    # -------------------------
    def get_active_trades(self):
        """Get list of active trades"""
        return self.active_trades
    
    # -------------------------
    # REMOVE TRADE
    # -------------------------
    def remove_trade(self, instrument_token):
        """
        Remove trade from active trades list.
        
        Args:
            instrument_token: Instrument token ID
        """
        self.active_trades = [t for t in self.active_trades if t.get('instrument_token') != instrument_token]
        logger.info(f"[STATE MANAGER] Trade removed from active_trades: token {instrument_token}")
    
    # -------------------------
    # SUBSCRIBE TOKEN
    # -------------------------
    def subscribe_token(self, token):
        """
        Subscribe to token for live price updates.
        
        Args:
            token: Instrument token ID
        """
        self.track_subscription(token)
        logger.info(f"[STATE MANAGER] Subscribed to token {token} for live price updates")
    
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
    # CHECK CACHE FRESHNESS
    # -------------------------
    def check_cache_freshness(self, max_age_seconds=60):
        """
        Check if cache data is fresh or stale.
        
        Args:
            max_age_seconds: Maximum age in seconds before considering data stale
            
        Returns:
            Dictionary with freshness status for each symbol
        """
        if not hasattr(self, 'last_update'):
            return {"status": "ERROR", "message": "No update timestamp available"}
        
        age_seconds = (datetime.now() - self.last_update).total_seconds()
        
        freshness_report = {
            "status": "FRESH" if age_seconds < max_age_seconds else "STALE",
            "age_seconds": age_seconds,
            "last_update": self.last_update.strftime('%H:%M:%S') if self.last_update else "N/A",
            "symbols_count": len(self.latest_prices),
            "oi_count": len(self.latest_oi)
        }
        
        if age_seconds >= max_age_seconds:
            logger.warning(f"[STALE DATA DETECTED] Cache age: {age_seconds:.0f}s (max: {max_age_seconds}s)")
            logger.warning(f"[STALE DATA] Last update: {freshness_report['last_update']}")
            logger.warning(f"[STALE DATA] Symbols cached: {freshness_report['symbols_count']}, OI cached: {freshness_report['oi_count']}")
        else:
            logger.info(f"[CACHE FRESH] Cache age: {age_seconds:.0f}s (max: {max_age_seconds}s) - Data is fresh")
        
        return freshness_report
    
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
    
    # -------------------------
    # HELPER: CLASSIFY MISSING TOKEN
    # -------------------------
    def _classify_missing_token(self, token):
        """
        Classify why a token is missing from cache.
        
        Args:
            token: Instrument token ID
            
        Returns:
            Classification string: NOT_SUBSCRIBED, SUBSCRIBED_BUT_NO_TICK_YET, NO_DATA_YET, CACHE_BUG
        """
        if token not in self.subscribed_tokens:
            return "NOT_SUBSCRIBED"
        
        if token not in self.first_tick_timestamps:
            return "SUBSCRIBED_BUT_NO_TICK_YET"
        
        # Token is subscribed and has received ticks, check if data exists
        has_price = token in self.latest_prices
        has_oi = token in self.latest_oi
        
        # CRITICAL FIX: If subscribed but no data yet, classify as NO_DATA_YET (not CACHE_BUG)
        if not has_price and not has_oi:
            return "NO_DATA_YET"
        
        # Token is subscribed, has received ticks, but data is missing - potential cache bug
        if not has_price or not has_oi:
            return "CACHE_BUG"
        
        return "UNKNOWN"
    
    # -------------------------
    # DATA HEALTH SUMMARY
    # -------------------------
    def get_data_health_summary(self):
        """
        Generate data health summary for diagnostics.
        
        Returns:
            Dictionary with subscription and data health statistics
        """
        subscribed_count = len(self.subscribed_tokens)
        tokens_with_price = len(self.latest_prices)
        tokens_with_oi = len(self.latest_oi)
        tokens_with_first_tick = len(self.first_tick_timestamps)
        
        # Classify missing tokens (only among subscribed tokens)
        not_subscribed = 0
        subscribed_no_tick = 0
        no_data_yet = 0
        cache_bug = 0
        
        # Check all subscribed tokens
        for token in self.subscribed_tokens:
            classification = self._classify_missing_token(token)
            if classification == "NOT_SUBSCRIBED":
                not_subscribed += 1
            elif classification == "SUBSCRIBED_BUT_NO_TICK_YET":
                subscribed_no_tick += 1
            elif classification == "NO_DATA_YET":
                no_data_yet += 1
            elif classification == "CACHE_BUG":
                cache_bug += 1
        
        # Calculate missing data among subscribed tokens only
        subscribed_with_price = sum(1 for token in self.subscribed_tokens if token in self.latest_prices)
        subscribed_with_oi = sum(1 for token in self.subscribed_tokens if token in self.latest_oi)
        subscribed_missing_data = subscribed_count - subscribed_with_price
        
        summary = {
            "subscribed_tokens": subscribed_count,
            "tokens_with_price": tokens_with_price,
            "tokens_with_oi": tokens_with_oi,
            "tokens_with_first_tick": tokens_with_first_tick,
            "subscribed_with_price": subscribed_with_price,
            "subscribed_with_oi": subscribed_with_oi,
            "subscribed_missing_data": subscribed_missing_data,
            "classification": {
                "not_subscribed": not_subscribed,
                "subscribed_no_tick": subscribed_no_tick,
                "cache_bug": cache_bug
            }
        }
        
        logger.info(f"[DATA HEALTH] Subscribed tokens: {subscribed_count}")
        logger.info(f"[DATA HEALTH] Subscribed tokens with data (price): {subscribed_with_price}")
        logger.info(f"[DATA HEALTH] Subscribed tokens with data (OI): {subscribed_with_oi}")
        logger.info(f"[DATA HEALTH] Subscribed tokens missing data: {subscribed_missing_data}")
        logger.info(f"[DATA HEALTH] Total tokens with data (price): {tokens_with_price}")
        logger.info(f"[DATA HEALTH] Total tokens with data (OI): {tokens_with_oi}")
        logger.info(f"[DATA HEALTH] Classification: NOT_SUBSCRIBED={not_subscribed}, SUBSCRIBED_BUT_NO_TICK_YET={subscribed_no_tick}, NO_DATA_YET={no_data_yet}, CACHE_BUG={cache_bug}")
        
        return summary
    
    # -------------------------
    # DATA READINESS VALIDATION
    # -------------------------
    def check_symbol_data_readiness(self, tokens, min_ready_percentage=70.0):
        """
        Check if a symbol's tokens have sufficient data readiness.
        
        Args:
            tokens: List of instrument tokens to check
            min_ready_percentage: Minimum percentage of tokens that must have data (default: 70%)
            
        Returns:
            Dictionary with readiness status and statistics
        """
        if not tokens:
            return {
                "ready": False,
                "ready_percentage": 0,
                "total_tokens": 0,
                "tokens_with_data": 0,
                "tokens_missing_data": 0,
                "reason": "No tokens to check"
            }
        
        tokens_with_data = 0
        tokens_missing_data = 0
        
        for token in tokens:
            has_price = token in self.latest_prices
            has_oi = token in self.latest_oi
            
            if has_price and has_oi:
                tokens_with_data += 1
            else:
                tokens_missing_data += 1
        
        total_tokens = len(tokens)
        ready_percentage = (tokens_with_data / total_tokens * 100) if total_tokens > 0 else 0
        is_ready = ready_percentage >= min_ready_percentage
        
        result = {
            "ready": is_ready,
            "ready_percentage": ready_percentage,
            "total_tokens": total_tokens,
            "tokens_with_data": tokens_with_data,
            "tokens_missing_data": tokens_missing_data,
            "min_required": min_ready_percentage
        }
        
        return result

"""
WebSocket Client - Real-time market data streaming
Eliminates REST API rate limits by using Kite WebSocket for live price data
NOW WITH: Token Manager integration (dynamic instruments)
"""

import logging
import time
from kiteconnect import KiteTicker
from kiteconnect import KiteConnect
from services.token_manager_service import get_token_manager

logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    WebSocket Client for real-time market data streaming.
    
    Provides:
    - Live price (LTP) without rate limits
    - Open Interest (OI) updates
    - Volume updates
    - Direct feed into State Manager
    - Zero REST API calls for price data
    - Dynamic instrument loading (NEW)
    - Smart token selection (NEW)
    - Reconnection logic (NEW)
    """
    
    def __init__(self, api_key, access_token, state_manager, token_manager=None, on_reconnect_callback=None):
        """
        Initialize WebSocket Client.
        
        Args:
            api_key: Kite API key
            access_token: Kite access token
            state_manager: StateManager instance for data storage
            token_manager: Optional shared TokenManager instance (prevents re-auth)
            on_reconnect_callback: Optional callback function called on WebSocket reconnect
        """
        self.api_key = api_key
        self.access_token = access_token
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        
        # CRITICAL: Create SEPARATE KiteTicker instance for Spot WebSocket
        # Each WebSocket (Spot and Options) must have its own KiteTicker instance
        # This does NOT cause 429 errors - rate limiting is per API key, not per instance
        self.kws = KiteTicker(api_key, access_token)
        self.state = state_manager
        
        # CRITICAL FIX: Use shared token manager if provided, otherwise create new
        if token_manager:
            self.token_manager = token_manager
            logger.info("WebSocket Client initialized with shared Token Manager (no re-auth)")
        else:
            # Fallback: create new token manager (may cause re-auth issues)
            self.token_manager = get_token_manager(api_key, access_token)
            logger.warning("WebSocket Client initialized with new Token Manager (may cause re-auth issues)")
        
        self.token_map = {}   # symbol -> token
        self.symbol_map = {}  # token -> symbol
        
        self.tick_count = 0  # Track total ticks received
        
        # Active trade token for targeted debugging
        self.active_trade_token = None
        self.received_first_tick = set()  # Track first tick for each token
        self.all_tokens_seen = set()  # Track ALL tokens seen in WebSocket stream (for comparison)
        
        # PRODUCTION FIX: Conservative reconnection to avoid Zerodha rate limits
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3  # Reduced from 5 to avoid rate limiting
        self.reconnect_delay = 30  # Increased from 3 to 30 seconds
        self.exponential_backoff = True  # Enable exponential backoff
        
        # CRITICAL FIX: Track WebSocket connection status
        self.ws_connected = False
        self.ws_subscribed = False
        
        # Reconnect safety callback
        self.on_reconnect_callback = on_reconnect_callback
        
        logger.info("WebSocket Client initialized")
    
    # -------------------------
    # LOAD INSTRUMENT TOKENS (DYNAMIC + SMART)
    # -------------------------
    def load_tokens(self, symbols):
        """
        Load instrument tokens dynamically using Token Manager with smart resolution.
        
        Args:
            symbols: List of trading symbols (e.g., ["NIFTY", "BANKNIFTY"])
            
        Returns:
            List of instrument tokens for WebSocket subscription
        """
        try:
            logger.info(f"Loading instrument tokens for {len(symbols)} symbols using Token Manager (smart resolution)...")
            
            # Refresh instruments if needed
            self.token_manager.refresh_if_needed()
            
            # Load tokens for each symbol using smart resolution (FUT > SPOT > OPTION)
            for symbol in symbols:
                instrument = self.token_manager.resolve_symbol_token(symbol)
                if instrument:
                    token = instrument["instrument_token"]
                    tradingsymbol = instrument["tradingsymbol"]
                    
                    self.token_map[symbol] = token
                    self.symbol_map[token] = symbol
                    
                    logger.info(f"Loaded token: {symbol} -> {token} (Trading Symbol: {tradingsymbol})")
                else:
                    logger.warning(f"Could not load token for {symbol}")
            
            tokens = list(self.token_map.values())
            logger.info(f"Loaded {len(tokens)} tokens for WebSocket subscription")
            
            if len(tokens) == 0:
                logger.warning(f"No tokens found for symbols: {symbols}")
            
            return tokens
            
        except Exception as e:
            logger.error(f"Error loading instrument tokens: {e}")
            return []
    
    # -------------------------
    # ON TICKS
    # -------------------------
    def on_ticks(self, ws, ticks):
        """
        Handle incoming WebSocket ticks.

        Args:
            ws: WebSocket instance
            ticks: List of tick data
        """
        self.tick_count += 1

        # Log first few ticks to confirm connection
        if self.tick_count <= 5:
            logger.info(f"[TICK #{self.tick_count}] Received {len(ticks)} tick(s)")

        for tick in ticks:
            token = tick["instrument_token"]
            
            # Track ALL tokens seen in WebSocket stream (for comparison only)
            self.all_tokens_seen.add(token)
            
            # FILTERED Tick Logging (CRITICAL - No Noise)
            # Only log ticks for the active trade token
            if self.active_trade_token and token == self.active_trade_token:
                # First Tick Confirmation
                if token not in self.received_first_tick:
                    logger.debug(f"[WS FIRST TICK] Token {token} received first tick")
                    self.received_first_tick.add(token)
            
            symbol = self.symbol_map.get(token)

            if not symbol:
                continue

            price = tick.get("last_price", 0)
            oi = tick.get("oi", 0)
            volume = tick.get("volume", 0)

            # Feed into state manager BY SYMBOL (for spot prices)
            self.state.update_price(symbol, price)
            self.state.update_oi(symbol, oi)
            self.state.update_volume(symbol, volume)

            # CRITICAL FIX: ALSO store by TOKEN (for options) and pass token for tick tracking
            # This enables production architecture to retrieve by token
            self.state.update_price(token, price, token=token)
            self.state.update_oi(token, oi)
            self.state.update_volume(token, volume)
            
            # CRITICAL FIX: Track tick in state_manager for monitor visibility
            self.state.track_tick(token)
            
            # CRITICAL FIX: Update active trades with live price for Pro Monitor UI
            # This is needed for spot WebSocket to update trades (options_ws_client already does this)
            self.state.update_trade(token, price)

            # Log tick updates for first few ticks
            if self.tick_count <= 5:
                logger.info(f"[TICK #{self.tick_count}] {symbol} (Token: {token}) -> Price: {price}, OI: {oi}, Volume: {volume}")

        # CRITICAL FIX: Log cache size periodically
        if self.tick_count % 10 == 0:
            cache_size = len(self.state.latest_prices)
            logger.debug(f"[WS CACHE SIZE] {cache_size} instruments cached")
    
    # -------------------------
    # ON CONNECT (PRODUCTION-READY)
    # -------------------------
    def on_connect(self, ws, response):
        """
        Handle WebSocket connection with proper subscription sequence.
        
        Args:
            ws: WebSocket instance
            response: Connection response
        """
        logger.info("=" * 80)
        logger.info("SPOT WEBSOCKET CONNECTED")
        logger.info("=" * 80)
        
        # CRITICAL FIX: Track connection status
        self.ws_connected = True
        
        # Check if this is a reconnection (reconnect_attempts > 0)
        is_reconnect = self.reconnect_attempts > 0
        
        # Reset reconnection counter
        self.reconnect_attempts = 0
        
        # Get tokens to subscribe
        tokens = list(self.token_map.values())
        
        logger.info(f"[WS CONNECTED] Subscribing to {len(tokens)} tokens")
        
        if not tokens:
            logger.warning("No tokens to subscribe - WebSocket will idle")
            self.ws_subscribed = False
            return
        
        # Track subscriptions in state manager for diagnostics
        if self.state:
            for token in tokens:
                self.state.track_subscription(token)
        
        # Subscribe FIRST
        ws.subscribe(tokens)
        logger.info(f"✓ Subscribed to {len(tokens)} spot tokens")
        
        # DATA READINESS: Warm-up wait for WebSocket data to populate
        # Spot tokens receive data immediately, but we wait for consistency
        warm_up_time = 0.3  # 300ms warm-up for spot
        logger.info(f"[DATA READINESS] Warm-up wait: {warm_up_time*1000:.0f}ms for WebSocket data to populate")
        time.sleep(warm_up_time)
        logger.info(f"[DATA READINESS] Warm-up complete, proceeding with data processing")
        
        # Set mode SECOND (FULL mode for OI + Volume + Depth)
        ws.set_mode(ws.MODE_FULL, tokens)
        logger.info(f"✓ Mode set to FULL (OI + Volume + Depth enabled)")
        
        # CRITICAL FIX: Track subscription status
        self.ws_subscribed = True
        
        # Log subscription details
        for symbol, token in self.token_map.items():
            logger.info(f"  - {symbol}: Token {token}")
        
        # WEBSOCKET RECONNECT SAFETY: Call callback if this is a reconnection
        if is_reconnect and self.on_reconnect_callback:
            logger.info("[WEBSOCKET RECONNECT SAFETY] Calling reconnect safety callback")
            try:
                self.on_reconnect_callback()
            except Exception as e:
                logger.error(f"[WEBSOCKET RECONNECT SAFETY] Callback failed: {e}")
        
        logger.info("=" * 80)
        logger.info("SPOT WEBSOCKET READY FOR DATA STREAMING")
        logger.info("=" * 80)
    
    # -------------------------
    # ON CLOSE (PRODUCTION-READY)
    # -------------------------
    def on_close(self, ws, code, reason):
        """
        Handle WebSocket connection close with reconnection logic.
        
        Args:
            ws: WebSocket instance
            code: Close code
            reason: Close reason
        """
        logger.warning(f"[SPOT WS CLOSED] Code: {code}, Reason: {reason}")
        
        # CRITICAL FIX: Reset connection status
        self.ws_connected = False
        self.ws_subscribed = False
        
        # PRODUCTION FIX: Exponential backoff to avoid rate limiting
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            
            # Calculate delay with exponential backoff
            if self.exponential_backoff:
                delay = self.reconnect_delay * (2 ** (self.reconnect_attempts - 1))
            else:
                delay = self.reconnect_delay
            
            logger.info(f"[SPOT WS] Attempting reconnection {self.reconnect_attempts}/{self.max_reconnect_attempts} in {delay}s...")
            time.sleep(delay)
            self.reconnect()
        else:
            logger.error("[SPOT WS] Max reconnection attempts reached. WebSocket not reconnected.")
    
    # -------------------------
    # ON ERROR (PRODUCTION-READY)
    # -------------------------
    def on_error(self, ws, code, reason):
        """
        Handle WebSocket errors with proper error classification.
        
        Args:
            ws: WebSocket instance
            code: Error code
            reason: Error reason
        """
        logger.error(f"[SPOT WS ERROR] Code: {code}, Reason: {reason}")
        
        if code == 403:
            logger.error("[CRITICAL] 403 Forbidden - Check IP restrictions in Kite account")
        elif code == 1006:
            logger.error("[CRITICAL] Connection closed uncleanly - Network or auth issue")
        else:
            logger.error(f"[SPOT WS] Non-critical error - will attempt reconnection")
    
    # -------------------------
    # ON RECONNECT
    # -------------------------
    def on_reconnect(self, ws, attempt_count):
        """Handle WebSocket reconnection"""
        logger.info(f"WebSocket reconnecting... Attempt {attempt_count}")
    
    # -------------------------
    # RECONNECT
    # -------------------------
    def reconnect(self):
        """Reconnect WebSocket"""
        try:
            logger.info("Reconnecting WebSocket...")
            tokens = list(self.token_map.values())
            self.connect(tokens)
        except Exception as e:
            logger.error(f"Error reconnecting WebSocket: {e}")
    
    # -------------------------
    # CONNECT (PRODUCTION-READY)
    # -------------------------
    def connect(self, tokens):
        """
        Connect to WebSocket with proper setup and start streaming.
        
        Args:
            tokens: List of instrument tokens to subscribe
        """
        try:
            logger.info("=" * 80)
            logger.info("INITIALIZING SPOT WEBSOCKET CONNECTION")
            logger.info("=" * 80)
            logger.info(f"Tokens to subscribe: {len(tokens)}")
            
            # Store tokens for subscription
            for token in tokens:
                # Find symbol for this token
                symbol = self.symbol_map.get(token)
                if symbol:
                    self.token_map[symbol] = token
                    logger.info(f"  - {symbol}: Token {token}")
                else:
                    logger.warning(f"Token {token} has no symbol mapping")
            
            # Set callbacks BEFORE connecting
            self.kws.on_ticks = self.on_ticks
            self.kws.on_connect = self.on_connect
            self.kws.on_error = self.on_error
            self.kws.on_close = self.on_close
            self.kws.on_reconnect = self.on_reconnect
            
            # Connect in threaded mode (non-blocking)
            logger.info("Connecting to WebSocket...")
            self.kws.connect(threaded=True)
            
            logger.info("✓ Spot WebSocket connection initiated (threaded mode)")
            logger.info("✓ Waiting for connection callback...")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"[CRITICAL] Error connecting to Spot WebSocket: {e}")
            raise
    
    # -------------------------
    # DISCONNECT
    # -------------------------
    def disconnect(self):
        """Disconnect WebSocket"""
        try:
            logger.info("Disconnecting WebSocket...")
            self.kws.close()
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")
    
    def subscribe_tokens(self, tokens):
        """
        Subscribe to additional tokens after connection is established.
        
        Args:
            tokens: List of instrument tokens to subscribe
        """
        # WebSocket Connection Status (before subscription)
        logger.info(f"[WS STATUS] Connected: {self.ws_connected}")
        logger.info(f"[WS KWS AVAILABLE] {self.kws is not None}")
        logger.info(f"[WS KWS CONNECTED] {self.kws.is_connected if self.kws else False}")
        
        if not self.ws_connected:
            logger.warning(f"[WS SUBSCRIBE] WebSocket not connected, cannot subscribe to tokens: {tokens}")
            return False
        
        if not self.kws:
            logger.warning(f"[WS SUBSCRIBE] Kite WebSocket not initialized, cannot subscribe to tokens: {tokens}")
            return False
        
        try:
            # Subscription Call (CRITICAL)
            for token in tokens:
                logger.info(f"[WS SUBSCRIBE CALL] Sending token to Kite: {token}")
            
            self.kws.subscribe(tokens)
            logger.info(f"[WS SUBSCRIBE] Subscribed to {len(tokens)} additional tokens")
            
            # Set mode to FULL for new tokens
            self.kws.set_mode(self.kws.MODE_FULL, tokens)
            logger.info(f"[WS SUBSCRIBE] Mode set to FULL for new tokens")
            
            # Track subscriptions in state manager
            if self.state:
                for token in tokens:
                    self.state.track_subscription(token)
            
            return True
        except Exception as e:
            logger.error(f"[WS SUBSCRIBE] Error subscribing to tokens: {e}")
            return False
    
    # -------------------------
    # GET TOKEN FOR SYMBOL
    # -------------------------
    def get_token(self, symbol):
        """Get instrument token for symbol"""
        return self.token_map.get(symbol)
    
    def set_active_trade_token(self, token):
        """
        Set the active trade token for targeted tick debugging.
        
        Args:
            token: Instrument token of the active trade
        """
        self.active_trade_token = token
        self.received_first_tick = set()  # Reset first tick tracking for new trade
        logger.info(f"[WS DEBUG] Active trade token set to: {token}")
        logger.info(f"[WS DEBUG] Reset first tick tracking for new trade")
    
    def check_token_presence(self, token):
        """
        Check if a token is present in the WebSocket stream and classify the issue.
        
        Args:
            token: Instrument token to check
        """
        if token not in self.received_first_tick:
            logger.warning(f"[WS MISSING] No ticks for active trade token: {token}")
        
        if token in self.all_tokens_seen:
            if token in self.received_first_tick:
                return "TOKEN_CORRECT_TICKS_RECEIVED"
            else:
                return "TOKEN_IN_STREAM_NO_FIRST_TICK"
        else:
            return "TOKEN_NOT_IN_STREAM"
    
    # -------------------------
    # GET SYMBOL FOR TOKEN
    # -------------------------
    def get_symbol(self, token):
        """Get symbol for instrument token"""
        return self.symbol_map.get(token)
    
    # -------------------------
    # IS CONNECTED
    # -------------------------
    def is_connected(self):
        """Check if WebSocket is connected and subscribed"""
        return self.ws_connected and self.ws_subscribed
    
    # -------------------------
    # GET CONNECTION STATUS
    # -------------------------
    def get_connection_status(self):
        """Get WebSocket connection status"""
        return {
            "connected": self.ws_connected,
            "subscribed": self.ws_subscribed,
            "tokens_loaded": len(self.token_map),
            "ticks_received": self.tick_count,
            "reconnect_attempts": self.reconnect_attempts
        }

"""
Options WebSocket - Real-time options data streaming
Subscribes to NFO (options) for real OI, Volume, and LTP
"""

import logging
import time
from kiteconnect import KiteTicker, KiteConnect

logger = logging.getLogger(__name__)


class OptionsWebSocket:
    """
    Options WebSocket - Real-time options data streaming.
    
    Features:
    - Subscribes to NFO (options) not NSE (spot)
    - Gets real OI, Volume, and LTP for CE/PE contracts
    - Auto-picks ATM strikes
    - Feeds data into State Manager
    """
    
    def __init__(self, kite_client, api_key, access_token, state, token_manager=None):
        """
        Initialize Options WebSocket.
        
        CRITICAL: This WebSocket uses a SEPARATE KiteTicker instance for the connection.
        The shared KiteConnect instance (kite_client) is only for REST API calls (loading instruments).
        The WebSocket connection (self.kws) is a separate KiteTicker instance.
        
        This does NOT cause 429 errors because:
        - Rate limiting is per API key, not per KiteTicker instance
        - Multiple WebSocket connections are allowed and supported by Kite
        
        Args:
            kite_client: Shared KiteConnect instance (for REST API calls only, not WebSocket)
            api_key: Kite API key (for token manager)
            access_token: Kite access token (for token manager)
            state: State Manager instance
            token_manager: Optional shared TokenManager instance (prevents re-auth)
        """
        # CRITICAL FIX: Reuse shared KiteClient instance for REST API calls only (prevents re-login)
        # This is NOT used for WebSocket connection - WebSocket uses separate KiteTicker
        self.kite = kite_client
        self.api_key = api_key  # Store for token manager
        self.access_token = access_token  # Store for token manager
        self.token_manager = token_manager  # CRITICAL FIX: Store token manager for instrument access
        
        # Safety validation
        if not self.api_key or not self.access_token:
            raise ValueError("OptionsWebSocket missing credentials")
        
        # CRITICAL FIX: Create SEPARATE KiteTicker instance for Options WebSocket
        # KiteTicker limitation: Single instance can only handle one stream context
        # Reusing the same instance causes second subscription to fail silently
        
        # IMPORTANT: This does NOT cause 429 errors because:
        # - Rate limiting is per API key, not per KiteTicker instance
        # - Multiple WebSocket connections are allowed and supported by Kite
        # - Rate limiting applies to REST API calls, not WebSocket subscriptions
        # - We're using the same API credentials (api_key, access_token)
        
        from kiteconnect import KiteTicker
        
        # Create separate KiteTicker instance for Options WebSocket
        # DO NOT share with Spot WebSocket
        self.kws = KiteTicker(self.api_key, self.access_token)
        
        # Note: We still use shared TokenManager for credentials (auth only), not for WS instance
        if self.token_manager:
            logger.info("Options WebSocket using shared TokenManager for credentials (auth only, not WS instance)")
        else:
            logger.info("Options WebSocket using direct auth (no TokenManager)")
        
        logger.info("✓ Created SEPARATE KiteTicker instance for Options WebSocket (will NOT cause 429 errors)")
        
        self.state = state
        
        self.token_symbol_map = {}  # token -> trading symbol
        self.tick_count = 0
        self.tokens_received_first_tick = set()  # Track tokens that have received first tick
        self.tokens_with_oi = set()  # Track tokens that have received OI data
        
        # Active trade token for targeted debugging
        self.active_trade_token = None
        self.received_first_tick = set()  # Track first tick for each token (for debugging)
        self.all_tokens_seen = set()  # Track ALL tokens seen in WebSocket stream (for comparison)
        
        logger.info("Options WebSocket initialized with shared KiteClient (no re-login)")
        if self.token_manager:
            logger.info("Options WebSocket using shared TokenManager (no re-auth)")
        else:
            logger.info("Options WebSocket without shared TokenManager (may have instrument access issues)")
    
    # -------------------------
    # LOAD OPTION TOKENS (WRAPPER - PRODUCTION-FIXED)
    # -------------------------
    def load_option_tokens(self, symbol: str, token_manager=None, spot_price=None) -> list:
        """
        Load option tokens for a symbol (wrapper that avoids quote calls).
        
        Args:
            symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY", "SBIN")
            token_manager: Shared TokenManager instance (prevents re-auth)
            spot_price: Optional spot price (if known, avoids quote call)
            
        Returns:
            List of instrument tokens for ATM strikes
        """
        try:
            logger.info(f"[DEBUG] load_option_tokens called for {symbol} with token_manager: {token_manager is not None}")
            # CRITICAL FIX: Use shared token manager (prevents re-login)
            if not token_manager:
                logger.info("[DEBUG] No shared token manager provided - skipping option tokens")
                return []
            
            # Get instrument for this symbol (handles both indices and stocks)
            logger.info(f"[DEBUG] Resolving instrument token for {symbol}...")
            instrument = token_manager.resolve_symbol_token(symbol)
            
            if not instrument:
                logger.info(f"[DEBUG] Could not resolve instrument token for {symbol}")
                return []
            
            instrument_token = instrument["instrument_token"]
            logger.info(f"[DEBUG] Resolved instrument token for {symbol}: {instrument_token}")
            
            # CRITICAL FIX: Use provided spot price or get from state (avoid quote call)
            if spot_price is None:
                # Try to get from state manager
                if hasattr(self.state, 'get_latest_price'):
                    spot_price = self.state.get_latest_price(symbol)
                
                # If still no spot price, then use quote as last resort
                if not spot_price:
                    logger.info(f"Using quote call for spot price (should be avoided)")
                    quote_data = self.kite.quote([instrument_token])
                    if not quote_data or str(instrument_token) not in quote_data:
                        logger.info(f"Could not get quote data for {symbol}")
                        return []
                    spot_price = quote_data[str(instrument_token)].get('last_price', 0)
            
            if not spot_price:
                logger.info(f"Could not get spot price for {symbol}")
                return []
            
            logger.info(f"Got spot price for {symbol}: {spot_price}")
            
            # Call get_option_tokens with the spot price
            logger.info(f"[DEBUG] Calling get_option_tokens for {symbol} at spot {spot_price}")
            result = self.get_option_tokens(symbol, spot_price)
            logger.info(f"[DEBUG] get_option_tokens returned {len(result)} tokens for {symbol}")
            return result
            
        except Exception as e:
            # CRITICAL FIX: Catch 429 errors specifically
            if "429" in str(e) or "rate limit" in str(e).lower():
                logger.info("[429 ERROR] Rate limit hit in load_option_tokens - cooling down")
                import time
                time.sleep(5)  # Cool down before retry
                return []
            
            logger.info(f"Error loading option tokens for {symbol}: {e}")
            import traceback
            logger.info(f"Full traceback: {traceback.format_exc()}")
            return []
    
    # -------------------------
    # GET OPTION TOKENS (ATM ONLY)
    # -------------------------
    def get_option_tokens(self, symbol: str, spot: float) -> list:
        """
        Get option tokens for ATM strikes (CE/PE).
        
        Args:
            symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY")
            spot: Current spot price
            
        Returns:
            List of instrument tokens for ATM strikes
        """
        try:
            logger.info(f"[DEBUG] get_option_tokens called for {symbol} at spot {spot}")
            logger.info(f"[DEBUG] Token manager available: {self.token_manager is not None}")
            logger.info(f"[DEBUG] Token manager has instrument_map: {hasattr(self.token_manager, 'instrument_map') if self.token_manager else False}")
            
            logger.info(f"Fetching option tokens for {symbol} at spot {spot}")
            
            # CRITICAL FIX: Use token manager instead of kite.instruments()
            if self.token_manager and hasattr(self.token_manager, 'instrument_map'):
                instruments = list(self.token_manager.instrument_map.values())
                logger.info(f"Using token manager instrument map: {len(instruments)} instruments")
            else:
                # Fallback: Try to use kite.instruments() if available
                if hasattr(self.kite, 'instruments'):
                    instruments = self.kite.instruments("NFO")
                    logger.info(f"Using kite.instruments() fallback: {len(instruments)} instruments")
                else:
                    logger.info("No instrument data source available (no token manager and no kite.instruments)")
                    return []
            
            # Step 1: Get nearest expiry
            expiries = sorted({
                inst["expiry"]
                for inst in instruments
                if inst.get("name") == symbol and inst.get("expiry")
            })
            
            if not expiries:
                logger.info(f"No expiries found for {symbol}")
                return []
            
            nearest_expiry = expiries[0]
            logger.info(f"Nearest expiry: {nearest_expiry}")
            
            # Step 2: Find ATM strike
            strikes = sorted({
                inst["strike"]
                for inst in instruments
                if inst.get("name") == symbol and inst.get("expiry") == nearest_expiry
            })
            
            if not strikes:
                logger.info(f"No strikes found for {symbol}")
                return []
            
            atm = min(strikes, key=lambda x: abs(x - spot))
            logger.info(f"ATM strike: {atm}")
            
            # Step 3: Get tokens for ATM ± 200 strikes (expanded range for better OI/PCR data)
            tokens = []
            strike_range = [atm - 200, atm - 150, atm - 100, atm - 50, atm, atm + 50, atm + 100, atm + 150, atm + 200]
            
            # STEP 4: FIX SUBSCRIPTION LOGIC
            # Ensure BOTH CE and PE tokens are subscribed for every strike
            # Current logic already does this (line 235: instrument_type in ["CE", "PE"])
            # The issue is likely in WebSocket subscription success, not selection logic
            ce_tokens = 0
            pe_tokens = 0
            
            for inst in instruments:
                if (
                    inst["name"] == symbol and
                    inst["expiry"] == nearest_expiry and
                    inst["strike"] in strike_range and
                    inst["instrument_type"] in ["CE", "PE"]
                ):
                    token = inst["instrument_token"]
                    trading_symbol = inst["tradingsymbol"]
                    
                    # Track CE/PE counts
                    if inst["instrument_type"] == "CE":
                        ce_tokens += 1
                    else:
                        pe_tokens += 1
                    
                    self.token_symbol_map[token] = trading_symbol
                    tokens.append(token)
                    
                    logger.info(f"Option token: {trading_symbol} -> {token}")
            
            logger.info(f"Loaded {len(tokens)} option tokens for {symbol} (CE: {ce_tokens}, PE: {pe_tokens})")
            logger.info(f"[DEBUG] Returning {len(tokens)} tokens from get_option_tokens")
            return tokens
            
        except Exception as e:
            logger.info(f"Error getting option tokens: {e}")
            return []
    
    # -------------------------
    # ON TICKS (PRODUCTION-READY)
    # -------------------------
    def on_ticks(self, ws, ticks):
        """
        Handle incoming option ticks with proper data flow.
        
        Args:
            ws: WebSocket instance
            ticks: List of tick data
        """
        # CRITICAL: Wrap entire tick processing in try-except to prevent WebSocket crash
        try:
            self.tick_count += 1
            
            # Log tick reception (less verbose after first few)
            if self.tick_count <= 3:
                logger.info(f"[OPTIONS TICK #{self.tick_count}] Received {len(ticks)} tick(s)")
            
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
                
                symbol = self.token_symbol_map.get(token)
                
                if not symbol:
                    continue
                
                # Track first tick reception
                if token not in self.tokens_received_first_tick:
                    self.tokens_received_first_tick.add(token)
                    logger.debug(f"[FIRST TICK] Token {symbol} received first tick")
                
                # Extract all available data (FULL mode provides these)
                ltp = tick.get("last_price", 0)
                oi = tick.get("oi", 0)
                volume = tick.get("volume", 0)
                
                # CRITICAL FIX: Track tokens with OI data (must extract OI first)
                if oi is not None and oi > 0:
                    if token not in self.tokens_with_oi:
                        self.tokens_with_oi.add(token)
                        logger.debug(f"[OI DATA] Token {symbol} received OI data: {oi}")

                # Feed into state manager BY TOKEN (for production architecture compatibility)
                self.state.update_price(token, ltp, token=token)
                self.state.update_oi(token, oi)
                self.state.update_volume(token, volume)
                
                # CRITICAL FIX: Track tick in state_manager for monitor visibility
                self.state.track_tick(token)

                # CRITICAL FIX: Update active trades with live price for Pro Monitor UI
                self.state.update_trade(token, ltp)

                # Also feed by SYMBOL for compatibility with existing code
                if symbol:
                    self.state.update_price(symbol, ltp, token=token)
                    self.state.update_oi(symbol, oi)
                    self.state.update_volume(symbol, volume)
                    
        except Exception as e:
            # CRITICAL: Log error but DO NOT crash the WebSocket
            logger.info(f"[OPTIONS TICK ERROR] Error processing ticks: {e}")
            logger.info(f"[OPTIONS TICK ERROR] Tick count: {self.tick_count}")
            logger.info(f"[OPTIONS TICK ERROR] This error was caught - WebSocket will continue")
            # Do not re-raise - let WebSocket continue processing

        # CRITICAL FIX: Log cache size periodically
        if self.tick_count % 10 == 0:
            cache_size = len(self.state.latest_prices)
            logger.debug(f"[OPTIONS WS CACHE SIZE] {cache_size} instruments cached")
    
    # -------------------------
    # ON CONNECT (PRODUCTION-READY)
    # -------------------------
    def on_connect(self, ws, response):
        """
        Handle Options WebSocket connection with proper subscription.
        
        Args:
            ws: WebSocket instance
            response: Connection response
        """
        logger.info("=" * 80)
        logger.info("OPTIONS WEBSOCKET CONNECTED")
        logger.info("=" * 80)
        
        # CRITICAL DEBUG: Log connection summary
        logger.info(f"[DEBUG] Connection successful - proceeding with subscription")
        
        # Get tokens to subscribe
        tokens = list(self.token_symbol_map.keys())
        
        logger.info(f"[WS CONNECTED] Subscribing to {len(tokens)} tokens")
        logger.info(f"[WS CONNECTED] Sample tokens: {list(tokens)[:5]}")  # Log sample tokens
        
        if not tokens:
            logger.error("[CRITICAL] No option tokens to subscribe - WebSocket will idle")
            logger.error("[CRITICAL] FIX: Check token_manager initialization and instrument segment")
            return
        
        # CRITICAL DEBUG: Verify token_symbol_map is populated
        logger.info(f"[DEBUG] Token symbol map size: {len(self.token_symbol_map)}")
        if len(self.token_symbol_map) == 0:
            logger.error(f"[CRITICAL] Token symbol map is EMPTY - NO TOKENS TO SUBSCRIBE")
            logger.error(f"[CRITICAL] FIX: Ensure load_option_tokens() is called before connect()")
            return
        else:
            logger.info(f"[DEBUG] Token symbol map populated with {len(self.token_symbol_map)} tokens")
        
        # Reset first tick tracking
        self.tokens_received_first_tick.clear()
        self.tokens_with_oi.clear()
        
        # Track subscriptions in state manager for diagnostics
        if self.state:
            for token in tokens:
                self.state.track_subscription(token)
        
        # Subscribe FIRST
        ws.subscribe(tokens)
        logger.info(f"✓ Subscribed to {len(tokens)} option tokens")
        
        # CRITICAL DEBUG: Verify subscription was successful
        logger.info(f"[DEBUG] Subscription command sent - waiting for ticks...")
        logger.info(f"[DEBUG] Expected: Ticks should arrive within 200-800ms after subscription")
        logger.info(f"[DEBUG] If no ticks arrive within 2 seconds, there may be a subscription issue")
        
        # Set mode SECOND (FULL mode for OI + Volume + Depth)
        ws.set_mode(ws.MODE_FULL, tokens)
        logger.info(f"✓ Mode set to FULL (OI + Volume + Depth enabled) - CRITICAL for OI data")
        
        # CRITICAL DEBUG: Verify mode setting
        logger.info(f"[DEBUG] Mode set to FULL for {len(tokens)} tokens - OI data should flow")
        
        # Log subscription summary (not individual tokens to reduce verbosity)
        logger.info(f"[DEBUG] Subscription complete: {len(tokens)} tokens subscribed in FULL mode")
        
        # CRITICAL: Wait until 70% of tokens receive first tick
        self._wait_for_first_ticks(tokens, min_percentage=70.0)
        
        logger.info("=" * 80)
        logger.info("OPTIONS WEBSOCKET READY FOR OI/VOLUME STREAMING")
        logger.info("=" * 80)
    
    # -------------------------
    # WAIT FOR FIRST TICKS
    # -------------------------
    def _wait_for_first_ticks(self, tokens, min_percentage=70.0, max_wait_seconds=10):
        """
        Wait until minimum percentage of tokens receive their first tick.
        
        Args:
            tokens: List of tokens to wait for
            min_percentage: Minimum percentage required (default 70%)
            max_wait_seconds: Maximum time to wait (default 10 seconds)
        """
        import time
        logger.info(f"[DATA READINESS] Waiting for {min_percentage}% of tokens to receive first tick (max {max_wait_seconds}s)")
        
        min_required = int(len(tokens) * min_percentage / 100)
        start_time = time.time()
        
        # CRITICAL DEBUG: Log wait start
        logger.info(f"[DEBUG] Wait started: {min_required} tokens required out of {len(tokens)} total")
        
        while len(self.tokens_received_first_tick) < min_required:
            if time.time() - start_time > max_wait_seconds:
                logger.info(f"[DATA READINESS] Timeout after {max_wait_seconds}s - only {len(self.tokens_received_first_tick)}/{len(tokens)} tokens received first tick")
                logger.info(f"[DATA READINESS] Required: {min_required}, Received: {len(self.tokens_received_first_tick)}")
                logger.info(f"[CRITICAL] NO TICKS RECEIVED - CHECK: 1) Mode set to FULL? 2) Token validity? 3) Segment NFO?")
                break
            
            time.sleep(0.1)  # Check every 100ms
        
        final_percentage = len(self.tokens_received_first_tick) / len(tokens) * 100
        logger.info(f"[DATA READINESS] First tick coverage: {final_percentage:.1f}% ({len(self.tokens_received_first_tick)}/{len(tokens)} tokens)")
        
        if final_percentage < min_percentage:
            logger.info(f"[DATA READINESS] Coverage below {min_percentage}% threshold - may have incomplete data")
        else:
            logger.info(f"[DATA READINESS] Coverage meets {min_percentage}% threshold - proceeding")
    
    # -------------------------
    # ON ERROR (PRODUCTION-READY)
    # -------------------------
    def on_error(self, ws, code, reason):
        """
        Handle Options WebSocket errors with proper logging.
        
        Args:
            ws: WebSocket instance
            code: Error code
            reason: Error reason
        """
        logger.info(f"[OPTIONS WS ERROR] Code: {code}, Reason: {reason}")
        
        if code == 403:
            logger.info("[CRITICAL] 403 Forbidden - Check IP restrictions in Kite account")
        elif code == 1006:
            logger.info("[CRITICAL] Connection closed uncleanly - Network or auth issue")
    
    # -------------------------
    # ON CLOSE (PRODUCTION-READY)
    # -------------------------
    def on_close(self, ws, code, reason):
        """
        Handle Options WebSocket close with proper logging.
        
        Args:
            ws: WebSocket instance
            code: Close code
            reason: Close reason
        """
        logger.info(f"[OPTIONS WS CLOSED] Code: {code}, Reason: {reason}")
        logger.info("[OPTIONS WS] Will auto-reconnect if applicable")
    
    # -------------------------
    # CONNECT (PRODUCTION-READY)
    # -------------------------
    def connect(self, tokens):
        """
        Connect to WebSocket and subscribe to option tokens with proper setup.
        
        Args:
            tokens: List of instrument tokens to subscribe
        """
        try:
            logger.info("=" * 80)
            logger.info("INITIALIZING OPTIONS WEBSOCKET CONNECTION")
            logger.info("=" * 80)
            logger.info(f"Tokens to subscribe: {len(tokens)}")
            
            # Store token mapping
            for token in tokens:
                if token not in self.token_symbol_map:
                    logger.info(f"Token {token} has no symbol mapping - will skip data")
            
            # Set callbacks BEFORE connecting
            self.kws.on_ticks = self.on_ticks
            self.kws.on_connect = self.on_connect
            self.kws.on_error = self.on_error
            self.kws.on_close = self.on_close
            
            # Connect in threaded mode (non-blocking)
            logger.info("Connecting to WebSocket...")
            self.kws.connect(threaded=True)
            
            logger.info("✓ Options WebSocket connection initiated (threaded mode)")
            logger.info("✓ Waiting for connection callback...")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.info(f"[CRITICAL] Error connecting to Options WebSocket: {e}")
            raise
    
    def set_active_trade_token(self, token):
        """
        Set the active trade token for targeted tick debugging.
        
        Args:
            token: Instrument token of the active trade
        """
        self.active_trade_token = token
        self.received_first_tick = set()  # Reset first tick tracking for new trade
        logger.info(f"[WS DEBUG] Active trade token set to: {token} (Options WebSocket)")
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
    # DISCONNECT
    # -------------------------
    def disconnect(self):
        """Disconnect WebSocket"""
        try:
            logger.info("Disconnecting Options WebSocket...")
            if hasattr(self, 'kws'):
                self.kws.close()
                # Wait for close to complete
                import time
                time.sleep(0.3)
            logger.info("Options WebSocket disconnected")
        except Exception as e:
            logger.info(f"Error disconnecting Options WebSocket: {e}")
    
    # -------------------------
    # STOP (Alternative shutdown)
    # -------------------------
    def stop(self):
        """Stop WebSocket (alias for disconnect)"""
        self.disconnect()
    
    # -------------------------
    # GET STATISTICS
    # -------------------------
    def get_statistics(self):
        """Get WebSocket statistics"""
        return {
            "tick_count": self.tick_count,
            "subscribed_tokens": len(self.token_symbol_map),
            "tokens_with_first_tick": len(self.tokens_received_first_tick),
            "tokens_with_oi": len(self.tokens_with_oi)
        }
    
    # -------------------------
    # CHECK OPTION DATA READINESS
    # -------------------------
    def is_option_data_ready(self, min_required_tokens=20, min_percentage=40.0):
        """
        Check if enough option tokens have received OI data.
        
        Args:
            min_required_tokens: Minimum number of tokens required (default 20)
            min_percentage: Minimum percentage of subscribed tokens (default 40%)
        
        Returns:
            Tuple (is_ready, populated_count, total_subscribed)
        """
        total_subscribed = len(self.token_symbol_map)
        populated_count = len(self.tokens_with_oi)
        
        if total_subscribed == 0:
            return False, populated_count, total_subscribed
        
        # Check absolute minimum
        if populated_count < min_required_tokens:
            return False, populated_count, total_subscribed
        
        # Check percentage minimum
        percentage = (populated_count / total_subscribed) * 100
        if percentage < min_percentage:
            return False, populated_count, total_subscribed
        
        return True, populated_count, total_subscribed

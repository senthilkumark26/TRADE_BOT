"""
WebSocket Client - Real-time market data streaming
Eliminates REST API rate limits by using Kite WebSocket for live price data
"""

import logging
from kiteconnect import KiteTicker
from kiteconnect import KiteConnect

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
    """
    
    def __init__(self, api_key, access_token, state_manager):
        """
        Initialize WebSocket Client.
        
        Args:
            api_key: Kite API key
            access_token: Kite access token
            state_manager: StateManager instance for data storage
        """
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        
        self.kws = KiteTicker(api_key, access_token)
        self.state = state_manager
        
        self.token_map = {}   # symbol -> token
        self.symbol_map = {}  # token -> symbol
        
        self.tick_count = 0  # Track total ticks received
        
        logger.info("WebSocket Client initialized")
    
    # -------------------------
    # LOAD INSTRUMENT TOKENS
    # -------------------------
    def load_tokens(self, symbols):
        """
        Load instrument tokens for given symbols.
        
        Args:
            symbols: List of trading symbols (e.g., ["NIFTY", "BANKNIFTY"])
            
        Returns:
            List of instrument tokens for WebSocket subscription
        """
        try:
            logger.info(f"Loading instrument tokens for {len(symbols)} symbols...")
            
            # Map indices to their NSE trading symbols
            symbol_mapping = {
                "NIFTY": "NIFTY 50",
                "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FIN SERVICE"
            }
            
            # Load instruments from NSE exchange
            instruments = self.kite.instruments("NSE")
            
            for inst in instruments:
                tradingsymbol = inst["tradingsymbol"]
                
                # Check if this instrument matches any of our symbols
                for symbol in symbols:
                    # Use mapping for indices
                    target_symbol = symbol_mapping.get(symbol, symbol)
                    
                    if tradingsymbol == target_symbol:
                        token = inst["instrument_token"]
                        
                        self.token_map[symbol] = token  # Store with original symbol name
                        self.symbol_map[token] = symbol
                        
                        logger.info(f"Loaded token: {symbol} -> {token} (Trading Symbol: {tradingsymbol})")
                        break
            
            tokens = list(self.token_map.values())
            logger.info(f"Loaded {len(tokens)} tokens for WebSocket subscription")
            
            if len(tokens) == 0:
                logger.warning(f"No tokens found for symbols: {symbols}")
                logger.info("Available symbols in NSE (first 10):")
                for inst in instruments[:10]:
                    logger.info(f"  - {inst['tradingsymbol']}")
            
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
            symbol = self.symbol_map.get(token)
            
            if not symbol:
                continue
            
            price = tick.get("last_price", 0)
            oi = tick.get("oi", 0)
            volume = tick.get("volume", 0)
            
            # Feed into state manager
            self.state.update_price(symbol, price)
            self.state.update_oi(symbol, oi)
            self.state.update_volume(symbol, volume)
            
            # Log tick updates for first few ticks
            if self.tick_count <= 5:
                logger.info(f"[TICK #{self.tick_count}] {symbol} -> Price: {price}, OI: {oi}, Volume: {volume}")
    
    # -------------------------
    # ON CONNECT
    # -------------------------
    def on_connect(self, ws, response):
        """
        Handle WebSocket connection.
        
        Args:
            ws: WebSocket instance
            response: Connection response
        """
        logger.info("WebSocket connected successfully")
        
        # Subscribe to tokens
        tokens = list(self.token_map.values())
        ws.subscribe(tokens)
        
        # Set mode to full (get all tick data)
        ws.set_mode(ws.MODE_FULL, tokens)
        
        logger.info(f"Subscribed to {len(tokens)} tokens in FULL mode")
    
    # -------------------------
    # ON ERROR
    # -------------------------
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        logger.error(f"WebSocket error: {error}")
    
    # -------------------------
    # ON CLOSE
    # -------------------------
    def on_close(self, ws, code, reason):
        """Handle WebSocket connection close"""
        logger.warning(f"WebSocket closed: {code} - {reason}")
    
    # -------------------------
    # ON RECONNECT
    # -------------------------
    def on_reconnect(self, ws, attempt_count):
        """Handle WebSocket reconnection"""
        logger.info(f"WebSocket reconnecting... Attempt {attempt_count}")
    
    # -------------------------
    # CONNECT
    # -------------------------
    def connect(self, tokens):
        """
        Connect to WebSocket and start streaming.
        
        Args:
            tokens: List of instrument tokens to subscribe
        """
        try:
            # Set callbacks
            self.kws.on_ticks = self.on_ticks
            self.kws.on_connect = self.on_connect
            self.kws.on_error = self.on_error
            self.kws.on_close = self.on_close
            self.kws.on_reconnect = self.on_reconnect
            
            # Connect in threaded mode (non-blocking)
            logger.info("Connecting to WebSocket...")
            self.kws.connect(threaded=True)
            
            logger.info("WebSocket connection initiated (threaded mode)")
            
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {e}")
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
    
    # -------------------------
    # GET TOKEN FOR SYMBOL
    # -------------------------
    def get_token(self, symbol):
        """Get instrument token for symbol"""
        return self.token_map.get(symbol)
    
    # -------------------------
    # GET SYMBOL FOR TOKEN
    # -------------------------
    def get_symbol(self, token):
        """Get symbol for instrument token"""
        return self.symbol_map.get(token)

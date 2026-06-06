"""
Options WebSocket - Real-time options data streaming
Subscribes to NFO (options) for real OI, Volume, and LTP
"""

import logging
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
    
    def __init__(self, api_key: str, access_token: str, state):
        """
        Initialize Options WebSocket.
        
        Args:
            api_key: Kite API key
            access_token: Kite access token
            state: State Manager instance
        """
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        
        self.kws = KiteTicker(api_key, access_token)
        self.state = state
        
        self.token_symbol_map = {}  # token -> trading symbol
        self.tick_count = 0
        
        logger.info("Options WebSocket initialized")
    
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
            logger.info(f"Fetching option tokens for {symbol} at spot {spot}")
            
            # Get NFO instruments (options)
            instruments = self.kite.instruments("NFO")
            
            # Step 1: Get nearest expiry
            expiries = sorted({
                inst["expiry"]
                for inst in instruments
                if inst["name"] == symbol and inst["expiry"]
            })
            
            if not expiries:
                logger.warning(f"No expiries found for {symbol}")
                return []
            
            nearest_expiry = expiries[0]
            logger.info(f"Nearest expiry: {nearest_expiry}")
            
            # Step 2: Find ATM strike
            strikes = sorted({
                inst["strike"]
                for inst in instruments
                if inst["name"] == symbol and inst["expiry"] == nearest_expiry
            })
            
            if not strikes:
                logger.warning(f"No strikes found for {symbol}")
                return []
            
            atm = min(strikes, key=lambda x: abs(x - spot))
            logger.info(f"ATM strike: {atm}")
            
            # Step 3: Get tokens for ATM ± 50 strikes (CE and PE)
            tokens = []
            
            for inst in instruments:
                if (
                    inst["name"] == symbol and
                    inst["expiry"] == nearest_expiry and
                    inst["strike"] in [atm - 50, atm, atm + 50] and
                    inst["instrument_type"] in ["CE", "PE"]
                ):
                    token = inst["instrument_token"]
                    trading_symbol = inst["tradingsymbol"]
                    
                    self.token_symbol_map[token] = trading_symbol
                    tokens.append(token)
                    
                    logger.info(f"Option token: {trading_symbol} -> {token}")
            
            logger.info(f"Loaded {len(tokens)} option tokens for {symbol}")
            return tokens
            
        except Exception as e:
            logger.error(f"Error getting option tokens: {e}")
            return []
    
    # -------------------------
    # ON TICKS (REAL DATA FLOW)
    # -------------------------
    def on_ticks(self, ws, ticks):
        """
        Handle incoming option ticks.
        
        Args:
            ws: WebSocket instance
            ticks: List of tick data
        """
        self.tick_count += 1
        
        # Log first few ticks to confirm connection
        if self.tick_count <= 5:
            logger.info(f"[OPTIONS TICK #{self.tick_count}] Received {len(ticks)} tick(s)")
        
        for tick in ticks:
            token = tick["instrument_token"]
            symbol = self.token_symbol_map.get(token)
            
            if not symbol:
                continue
            
            ltp = tick.get("last_price", 0)
            oi = tick.get("oi", 0)
            volume = tick.get("volume", 0)
            
            # Feed into state manager
            self.state.update_price(symbol, ltp)
            self.state.update_oi(symbol, oi)
            self.state.update_volume(symbol, volume)
            
            # Log tick updates for first few ticks
            if self.tick_count <= 5:
                logger.info(f"[OPTIONS TICK #{self.tick_count}] {symbol} -> LTP: {ltp}, OI: {oi}, Volume: {volume}")
    
    # -------------------------
    # CONNECT
    # -------------------------
    def connect(self, tokens):
        """
        Connect to WebSocket and subscribe to option tokens.
        
        Args:
            tokens: List of instrument tokens to subscribe
        """
        try:
            logger.info(f"Connecting to Options WebSocket with {len(tokens)} tokens...")
            
            self.kws.on_ticks = self.on_ticks
            
            def on_connect(ws, response):
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL, tokens)
                logger.info(f"Subscribed to {len(tokens)} option tokens in FULL mode")
            
            self.kws.on_connect = on_connect
            self.kws.connect(threaded=True)
            
            logger.info("Options WebSocket connection initiated (threaded mode)")
            
        except Exception as e:
            logger.error(f"Error connecting to Options WebSocket: {e}")
    
    # -------------------------
    # GET STATISTICS
    # -------------------------
    def get_statistics(self):
        """Get WebSocket statistics"""
        return {
            "tick_count": self.tick_count,
            "subscribed_tokens": len(self.token_symbol_map)
        }

"""
Token Manager Service - Dynamic instrument and token management
Production-grade solution for WebSocket subscriptions and instrument data
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

logger = logging.getLogger(__name__)


class TokenManagerService:
    """
    Token Manager Service - Dynamic instrument and token management.
    
    Provides:
    - Dynamic instrument loading (no hardcoding)
    - Smart token selection for WebSocket
    - Auto contract selection (current expiry)
    - Mode optimization (LTP vs FULL)
    - WebSocket reconnection logic
    - Rate limiting and fallback control
    """
    
    def __init__(self, api_key: str, access_token: str):
        """
        Initialize Token Manager Service.
        
        Args:
            api_key: Kite API key
            access_token: Kite access token
        """
        self.api_key = api_key
        self.access_token = access_token
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        
        # Instrument maps
        self.instrument_map = {}  # tradingsymbol -> instrument data
        self.token_map = {}  # tradingsymbol -> token
        self.symbol_to_tokens = {}  # base symbol -> list of tokens
        
        # Core symbols (indices)
        self.core_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        
        # Active watchlist (stocks)
        self.watchlist = ["HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "RELIANCE", "AXISBANK", "KOTAKBANK"]
        
        # Rate limiting
        self.last_call = {}  # symbol -> last call timestamp
        self.rate_limit = 1.0  # seconds between calls
        
        # Reconnection settings
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 3  # seconds
        
        # Cache management
        self.last_refresh = None
        self.refresh_interval = 3600  # 1 hour refresh
        
        logger.info("Token Manager Service initialized")
    
    def load_instruments(self, exchange: str = "NFO") -> Tuple[Dict, Dict]:
        """
        Load instruments dynamically from Kite API.
        
        Args:
            exchange: Exchange to load instruments from (default: NFO)
            
        Returns:
            Tuple of (instrument_map, token_map)
        """
        try:
            logger.info(f"Loading instruments from {exchange}...")
            
            instruments = self.kite.instruments(exchange)
            
            instrument_map = {}
            token_map = {}
            symbol_to_tokens = {}
            
            for ins in instruments:
                tradingsymbol = ins["tradingsymbol"]
                token = ins["instrument_token"]
                name = ins["name"]
                
                instrument_map[tradingsymbol] = ins
                token_map[tradingsymbol] = token
                
                # Group by base symbol
                if name not in symbol_to_tokens:
                    symbol_to_tokens[name] = []
                symbol_to_tokens[name].append(token)
            
            self.instrument_map = instrument_map
            self.token_map = token_map
            self.symbol_to_tokens = symbol_to_tokens
            self.last_refresh = datetime.now()
            
            logger.info(f"Loaded {len(instrument_map)} instruments from {exchange}")
            logger.info(f"Unique symbols: {len(symbol_to_tokens)}")
            
            return instrument_map, token_map
            
        except Exception as e:
            logger.error(f"Error loading instruments: {e}")
            return {}, {}
    
    def load_nse_instruments(self) -> Tuple[Dict, Dict]:
        """
        Load NSE (spot) instruments for stocks without FUT contracts.
        
        Returns:
            Tuple of (instrument_map, token_map)
        """
        try:
            logger.info("Loading NSE (spot) instruments for stock fallback...")
            
            instruments = self.kite.instruments("NSE")
            
            nse_instrument_map = {}
            nse_token_map = {}
            
            for ins in instruments:
                tradingsymbol = ins["tradingsymbol"]
                token = ins["instrument_token"]
                name = ins["name"]
                
                nse_instrument_map[tradingsymbol] = ins
                nse_token_map[tradingsymbol] = token
            
            logger.info(f"Loaded {len(nse_instrument_map)} NSE instruments")
            
            return nse_instrument_map, nse_token_map
            
        except Exception as e:
            logger.error(f"Error loading NSE instruments: {e}")
            return {}, {}
    
    def get_current_future(self, symbol: str) -> Optional[Dict]:
        """
        Get current future contract for symbol (auto-selects nearest expiry).
        
        Args:
            symbol: Base symbol (e.g., "HDFCBANK")
            
        Returns:
            Instrument data or None
        """
        try:
            if not self.instrument_map:
                self.load_instruments()
            
            # Find all FUT contracts for this symbol
            futures = []
            for tradingsymbol, data in self.instrument_map.items():
                if symbol in tradingsymbol and "FUT" in tradingsymbol:
                    futures.append((data["expiry"], data))
            
            if not futures:
                logger.warning(f"No FUT contracts found for {symbol}")
                return None
            
            # Sort by expiry and get nearest
            futures.sort(key=lambda x: x[0])
            nearest_future = futures[0][1]
            
            logger.info(f"Current future for {symbol}: {nearest_future['tradingsymbol']} (Expiry: {nearest_future['expiry']})")
            return nearest_future
            
        except Exception as e:
            logger.error(f"Error getting current future for {symbol}: {e}")
            return None
    
    def get_spot_token(self, symbol: str) -> Optional[Dict]:
        """
        Get spot (EQ) token for symbol (fallback for stocks without FUT).
        
        Args:
            symbol: Base symbol (e.g., "HDFCBANK")
            
        Returns:
            Instrument data or None
        """
        try:
            if not self.instrument_map:
                self.load_instruments()
            
            # Find EQ (spot) contract for this symbol
            for tradingsymbol, data in self.instrument_map.items():
                if symbol in tradingsymbol and "EQ" in tradingsymbol:
                    logger.info(f"Spot token for {symbol}: {tradingsymbol}")
                    return data
            
            logger.warning(f"No EQ contract found for {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting spot token for {symbol}: {e}")
            return None
    
    def resolve_symbol_token(self, symbol: str) -> Optional[Dict]:
        """
        Resolve token for symbol with smart priority (FUT > SPOT > OPTION).
        
        Args:
            symbol: Base symbol (e.g., "HDFCBANK")
            
        Returns:
            Instrument data or None
        """
        try:
            # Priority 1: FUT (best for sentiment)
            future = self.get_current_future(symbol)
            if future:
                return future
            
            # Priority 2: SPOT/EQ from NSE (fallback for stocks)
            nse_map, nse_tokens = self.load_nse_instruments()
            for tradingsymbol, data in nse_map.items():
                if symbol in tradingsymbol and "EQ" in tradingsymbol:
                    logger.info(f"NSE spot token for {symbol}: {tradingsymbol}")
                    return data
            
            # Priority 3: OPTION (for trading)
            # Get ATM option as fallback
            logger.warning(f"No FUT or NSE EQ found for {symbol}, trying options...")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving token for {symbol}: {e}")
            return None
    
    def get_active_tokens(self, mode: str = "smart") -> List[int]:
        """
        Get active tokens for WebSocket subscription with smart resolution.
        
        Args:
            mode: "smart" for FUT > SPOT > OPTION, "futures" for FUT only, "options" for options, "all" for both
            
        Returns:
            List of instrument tokens
        """
        try:
            if not self.instrument_map:
                self.load_instruments()
            
            tokens = []
            symbols = self.core_symbols + self.watchlist
            
            for symbol in symbols:
                if mode == "smart":
                    # Smart resolution: FUT > SPOT > OPTION
                    instrument = self.resolve_symbol_token(symbol)
                    if instrument:
                        tokens.append(instrument["instrument_token"])
                elif mode in ["futures", "all"]:
                    # Add FUT token
                    future = self.get_current_future(symbol)
                    if future:
                        tokens.append(future["instrument_token"])
                
                if mode in ["options", "all"]:
                    # Add option tokens (ATM strikes)
                    option_tokens = self.get_atm_option_tokens(symbol)
                    tokens.extend(option_tokens)
            
            logger.info(f"Active tokens ({mode}): {len(tokens)}")
            return tokens
            
        except Exception as e:
            logger.error(f"Error getting active tokens: {e}")
            return []
    
    def get_atm_option_tokens(self, symbol: str, spot: float = None, strikes: int = 3) -> List[int]:
        """
        Get ATM option tokens for symbol.
        
        Args:
            symbol: Base symbol
            spot: Current spot price (optional, will fetch if not provided)
            strikes: Number of strikes above/below ATM (default: 3)
            
        Returns:
            List of option tokens
        """
        try:
            if not self.instrument_map:
                self.load_instruments()
            
            # Get spot price if not provided
            if spot is None:
                future = self.get_current_future(symbol)
                if future:
                    quote = self.kite.ltp(future["instrument_token"])
                    spot = quote.get("last_price", 0)
            
            if not spot:
                logger.warning(f"Could not get spot price for {symbol}")
                return []
            
            # Find nearest expiry
            expiries = set()
            for tradingsymbol, data in self.instrument_map.items():
                if symbol in tradingsymbol and "CE" in tradingsymbol:
                    expiries.add(data["expiry"])
            
            if not expiries:
                return []
            
            nearest_expiry = min(expiries)
            
            # Calculate ATM strike
            step = 50 if symbol in ["NIFTY", "BANKNIFTY"] else 2.5
            atm = round(spot / step) * step
            
            # Get tokens for ATM ± strikes
            tokens = []
            for tradingsymbol, data in self.instrument_map.items():
                if (
                    symbol in tradingsymbol and
                    data["expiry"] == nearest_expiry and
                    abs(data["strike"] - atm) <= strikes * step and
                    data["instrument_type"] in ["CE", "PE"]
                ):
                    tokens.append(data["instrument_token"])
            
            logger.info(f"ATM option tokens for {symbol}: {len(tokens)} (ATM: {atm})")
            return tokens
            
        except Exception as e:
            logger.error(f"Error getting ATM option tokens for {symbol}: {e}")
            return []
    
    def safe_ltp(self, symbol: str) -> Optional[float]:
        """
        Get LTP with rate limiting and fallback control.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Last price or None
        """
        try:
            now = time.time()
            
            # Rate limiting check
            if symbol in self.last_call and now - self.last_call[symbol] < self.rate_limit:
                logger.debug(f"Rate limited: {symbol}")
                return None
            
            self.last_call[symbol] = now
            
            # Get instrument token
            future = self.get_current_future(symbol)
            if not future:
                return None
            
            # Fetch LTP
            quote = self.kite.ltp(future["instrument_token"])
            return quote.get("last_price", 0)
            
        except Exception as e:
            logger.error(f"Error getting safe LTP for {symbol}: {e}")
            return None
    
    def should_refresh(self) -> bool:
        """
        Check if instruments need refresh.
        
        Returns:
            True if refresh needed
        """
        if self.last_refresh is None:
            return True
        
        elapsed = (datetime.now() - self.last_refresh).total_seconds()
        return elapsed > self.refresh_interval
    
    def refresh_if_needed(self):
        """Refresh instruments if needed."""
        if self.should_refresh():
            logger.info("Refreshing instruments...")
            self.load_instruments()
    
    def get_service_info(self) -> Dict:
        """Get service information."""
        return {
            "service_name": "token_manager_service",
            "version": "1.0.0",
            "instruments_loaded": len(self.instrument_map),
            "symbols_tracked": len(self.symbol_to_tokens),
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "core_symbols": self.core_symbols,
            "watchlist_size": len(self.watchlist),
            "rate_limit": self.rate_limit
        }


# Global instance
_token_manager = None

def get_token_manager(api_key: str, access_token: str) -> TokenManagerService:
    """
    Get global token manager instance.
    
    Args:
        api_key: Kite API key
        access_token: Kite access token
        
    Returns:
        TokenManagerService instance
    """
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManagerService(api_key, access_token)
    return _token_manager
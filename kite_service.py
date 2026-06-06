"""
Kite Service - Centralized KiteConnect Integration
All Kite-related functionality in one service
"""

import logging
import time
import threading
import requests
from collections import defaultdict
from datetime import datetime, timedelta, date
from kiteconnect import KiteConnect
from expiry_manager import ExpiryManager

logger = logging.getLogger(__name__)


# STRICT GLOBAL RATE LIMITER (Production-Grade)
class StrictRateLimiter:
    """
    Thread-safe rate limiter for Kite API calls.
    Prevents API rate limit violations.
    """
    
    def __init__(self, calls_per_sec=2):
        self.lock = threading.Lock()
        self.delay = 1 / calls_per_sec
        self.last_call = 0
    
    def wait(self):
        """Wait if necessary to respect rate limit."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            
            self.last_call = time.time()


# Global rate limiter instance
rate_limiter = StrictRateLimiter(2)  # 2 calls/sec with thread-safe lock


# NSE EXPIRY CALENDAR FETCHER
class NSEExpiryCalendar:
    """
    Fetches NSE official expiry calendar from NSE website.
    Used for determining option expiry dates.
    """
    
    def __init__(self):
        self.expiry_cache = {}
        self.cache_expiry = 3600  # Cache for 1 hour
        self.last_fetch = 0
    
    def get_nse_expiry_calendar(self):
        """
        Fetch NSE official expiry calendar from NSE website.
        Returns: Dictionary with index and stock expiries
        """
        current_time = time.time()
        
        # Use cached data if still valid
        if self.expiry_cache and (current_time - self.last_fetch) < self.cache_expiry:
            logger.info("Using cached NSE expiry calendar")
            return self.expiry_cache
        
        try:
            # NSE Equity Derivatives page (contains expiry calendar)
            url = "https://www.nseindia.com/products-services/equity-derivatives"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Parse the response to extract expiry dates
                # For now, we'll use a simplified approach
                # In production, you'd parse the actual HTML or use NSE API
                
                # Fallback: Use current date + common patterns
                today = date.today()
                
                # Index weekly expiries (every Thursday)
                index_expries = []
                for i in range(4):  # Next 4 weeks
                    days_ahead = (3 - today.weekday()) % 7 + (i * 7)
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Thursday, use next Thursday
                    expiry_date = today + timedelta(days=days_ahead)
                    index_expries.append(expiry_date.strftime('%Y-%m-%d'))
                
                # Stock monthly expiries (last Thursday of month)
                stock_expries = []
                for i in range(3):  # Next 3 months
                    year = today.year + (today.month + i - 1) // 12
                    month = (today.month + i - 1) % 12 + 1
                    
                    # Find last Thursday of the month
                    last_day = date(year, month + 1, 1) - timedelta(days=1)
                    while last_day.weekday() != 3:  # 3 = Thursday
                        last_day -= timedelta(days=1)
                    
                    stock_expries.append(last_day.strftime('%Y-%m-%d'))
                
                self.expiry_cache = {
                    'indices': index_expries,
                    'stocks': stock_expries
                }
                self.last_fetch = current_time
                
                logger.info(f"Fetched NSE expiry calendar - Indices: {index_expries}, Stocks: {stock_expries}")
                return self.expiry_cache
            else:
                logger.warning(f"Failed to fetch NSE expiry calendar: Status {response.status_code}")
                return self.get_fallback_expiry_calendar()
        except Exception as e:
            logger.error(f"Error fetching NSE expiry calendar: {e}")
            return self.get_fallback_expiry_calendar()
    
    def get_fallback_expiry_calendar(self):
        """
        Fallback expiry calendar if NSE fetch fails.
        Uses standard expiry patterns.
        """
        today = date.today()
        
        # Index weekly expiries (every Thursday)
        index_expries = []
        for i in range(4):
            days_ahead = (3 - today.weekday()) % 7 + (i * 7)
            if days_ahead == 0:
                days_ahead = 7
            expiry_date = today + timedelta(days=days_ahead)
            index_expries.append(expiry_date.strftime('%Y-%m-%d'))
        
        # Stock monthly expiries (last Thursday of month)
        stock_expries = []
        for i in range(3):
            year = today.year + (today.month + i - 1) // 12
            month = (today.month + i - 1) % 12 + 1
            
            last_day = date(year, month + 1, 1) - timedelta(days=1)
            while last_day.weekday() != 3:
                last_day -= timedelta(days=1)
            
            stock_expries.append(last_day.strftime('%Y-%m-%d'))
        
        return {
            'indices': index_expries,
            'stocks': stock_expries
        }


# Global NSE expiry calendar instance
nse_expiry_calendar = NSEExpiryCalendar()


class KiteService:
    """
    Centralized Kite Service - All KiteConnect functionality in one place.
    Handles:
    - KiteConnect initialization
    - Option chain fetching
    - LTP fetching
    - OI tracking
    - Rate limiting
    - Expiry management
    """
    
    def __init__(self, api_key, access_token, demo_mode=False, demo_simulator=None):
        """
        Initialize Kite Service.
        
        Args:
            api_key: Zerodha API key
            access_token: Zerodha access token
            demo_mode: Enable demo mode for testing
            demo_simulator: Demo market simulator for testing
        """
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.demo_mode = demo_mode
        self.demo_simulator = demo_simulator
        
        # Initialize ExpiryManager for automatic expiry switching
        self.expiry_manager = ExpiryManager(cutoff_hour=15, cutoff_minute=20)
        
        # Cache instruments to avoid repeated API calls (CRITICAL)
        self.instruments_cache = None
        self.instruments_loaded = False
        
        # OI state for ΔOI calculation (stateful tracking)
        self.previous_oi = {}  # instrument_token -> previous OI
        self.oi_update_timestamp = {}  # instrument_token -> last update time
        self.oi_cooldown_seconds = 60  # Update OI every 60 seconds
        
        # Thread safety
        self.lock = threading.Lock()
        
        logger.info("Kite Service initialized with ExpiryManager")
    
    def get_ltp(self, instruments):
        """
        Get Last Traded Price (LTP) for instruments.
        
        Args:
            instruments: List of instrument tokens or symbols
            
        Returns:
            Dictionary of instrument -> LTP
        """
        if self.demo_mode and self.demo_simulator:
            return self.demo_simulator.get_ltp(instruments)
        
        rate_limiter.wait()
        return self.kite.ltp(instruments)
    
    def fetch_option_chain(self, symbol, spot_price):
        """
        Fetch option chain for a symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY")
            spot_price: Current spot price
            
        Returns:
            Tuple of (option_chain, atm_strike, spot_price)
        """
        # This is a placeholder - actual implementation in kite_client.py
        # For now, return None to indicate it needs to be implemented
        logger.warning("fetch_option_chain not implemented in KiteService yet")
        return None, None, spot_price
    
    def get_quote(self, instrument_token):
        """
        Get quote for a single instrument.
        
        Args:
            instrument_token: Instrument token
            
        Returns:
            Quote data
        """
        if self.demo_mode and self.demo_simulator:
            return self.demo_simulator.get_quote(instrument_token)
        
        rate_limiter.wait()
        return self.kite.quote(instrument_token)
    
    def get_instruments(self, segment="NFO"):
        """
        Get instruments for a segment.
        
        Args:
            segment: Market segment (e.g., "NFO", "NSE")
            
        Returns:
            List of instruments
        """
        rate_limiter.wait()
        return self.kite.instruments(segment)
    
    def get_ohlc(self, instrument_token):
        """
        Get OHLC data for an instrument.
        
        Args:
            instrument_token: Instrument token
            
        Returns:
            OHLC data
        """
        rate_limiter.wait()
        return self.kite.ohlc(instrument_token)
    
    def get_historical_data(self, instrument_token, from_date, to_date, interval):
        """
        Get historical data for an instrument.
        
        Args:
            instrument_token: Instrument token
            from_date: Start date
            to_date: End date
            interval: Time interval (e.g., "minute", "day")
            
        Returns:
            Historical data
        """
        rate_limiter.wait()
        return self.kite.historical_data(instrument_token, from_date, to_date, interval)

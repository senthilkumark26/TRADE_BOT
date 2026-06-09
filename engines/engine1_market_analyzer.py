"""
Engine 1: Fast Market Analyzer
-------------------------------
Non-blocking main thread engine that handles:
- Live tick data processing
- VWAP calculation and filtering
- Strike-wise PCR & OI confluence
- Signal generation (single-leg only)

This engine NEVER blocks or waits for API responses.
"""

import logging
import time
import threading
from collections import deque
from typing import Dict, Any, Optional, List
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from utils.optionstar import calculate_institutional_walls
from services.breakout_entry_service import BreakoutEntryService

logger = logging.getLogger(__name__)


class Engine1MarketAnalyzer:
    """
    Fast Market Analyzer - Engine 1
    Processes live tick data and generates trading signals without blocking.
    """
    

    def __init__(self, kite_client, max_price_history=100, debug_instrument=None):
        """
        Initialize Engine 1.
        
        Args:
            kite_client: KiteConnect client for market data
            max_price_history: Maximum number of price points to keep for VWAP
            debug_instrument: Show debug logs only for this instrument (None = no debug)
        """
        self.kite_client = kite_client
        self.max_price_history = max_price_history
        self.debug_instrument = debug_instrument  # Only show debug for this instrument
        
        # Initialize Breakout Entry Service (microservice)
        self.entry_engine = BreakoutEntryService()
        
        # Institutional walls cache (OptionStar data)
        self.institutional_walls = {}  # symbol -> institutional data
        
        # Instrument-specific breakout thresholds (BASE CONFIG - FALLBACK ONLY)
        # These are fallback values; adaptive thresholds are used in production
        self.BREAKOUT_CONFIG = {
            # DEFAULT FALLBACK (for unknown instruments)
            "DEFAULT": {
                "price_change": 0.3,
                "vwap_diff": 0.5,
                "oi_threshold": 5000
            },
            # INDICES (FAST)
            "NIFTY": {
                "price_change": 5,        # Base fallback value
                "vwap_diff": 7,          # Base fallback value
                "oi_threshold": 20000    # Base fallback value
            },
            "BANKNIFTY": {
                "price_change": 12,      # Base fallback value
                "vwap_diff": 15,        # Base fallback value
                "oi_threshold": 40000    # Base fallback value
            },
            # BANKING STOCKS (Lowered thresholds for polling-based system)
            "HDFCBANK": {
                "price_change": 0.5,  # Lowered from 1.5
                "vwap_diff": 0.8,  # Lowered from 2
                "oi_threshold": 5000  # Lowered from 20000
            },
            "ICICIBANK": {
                "price_change": 0.6,  # Lowered from 2
                "vwap_diff": 1.0,  # Lowered from 2.5
                "oi_threshold": 6000  # Lowered from 25000
            },
            "SBIN": {
                "price_change": 0.4,  # Lowered from 1
                "vwap_diff": 0.5,  # Lowered from 1.2
                "oi_threshold": 5000  # Lowered from 30000
            },
            "AXISBANK": {
                "price_change": 0.5,  # Lowered from 1.5
                "vwap_diff": 0.8,  # Lowered from 2
                "oi_threshold": 5000  # Lowered from 20000
            },
            "KOTAKBANK": {
                "price_change": 0.6,  # Lowered from 2
                "vwap_diff": 1.0,  # Lowered from 2.5
                "oi_threshold": 5000  # Lowered from 15000
            },
            # IT STOCKS (Lowered thresholds for polling-based system)
            "INFY": {
                "price_change": 0.6,  # Lowered from 2
                "vwap_diff": 1.0,  # Lowered from 2.5
                "oi_threshold": 5000  # Lowered from 15000
            },
            "TCS": {
                "price_change": 1.0,  # Lowered from 5
                "vwap_diff": 1.5,  # Lowered from 6
                "oi_threshold": 4000  # Lowered from 10000
            },
            "WIPRO": {
                "price_change": 0.3,  # Lowered from 0.8
                "vwap_diff": 0.5,  # Lowered from 1
                "oi_threshold": 3000  # Lowered from 20000
            },
            "HCLTECH": {
                "price_change": 0.5,  # Lowered from 2
                "vwap_diff": 0.8,  # Lowered from 2.5
                "oi_threshold": 3000  # Lowered from 15000
            },
            # OTHER STOCKS (Lowered thresholds for polling-based system)
            "ITC": {
                "price_change": 0.2,  # Lowered from 0.5
                "vwap_diff": 0.3,  # Lowered from 0.6
                "oi_threshold": 2000  # Lowered from 40000
            },
            "HINDUNILVR": {
                "price_change": 0.8,  # Lowered from 3
                "vwap_diff": 1.0,  # Lowered from 3.5
                "oi_threshold": 3000  # Lowered from 10000
            },
            "ONGC": {
                "price_change": 0.2,  # Lowered for better signal detection
                "vwap_diff": 0.3,  # Lowered for better signal detection
                "oi_threshold": 5000  # Lowered for better signal detection
            }
        }
        
        # Price history for VWAP calculation (per instrument)
        self.price_history = {}  # symbol -> deque of (price, volume, timestamp)
        
        # VWAP cache (per instrument)
        self.vwap_cache = {}  # symbol -> current VWAP
        
        # Option chain cache for PCR/OI calculation
        self.option_chain_cache = {}  # symbol -> option chain data
        self.option_chain_cache_time = {}  # symbol -> last update time
        
        # Baseline data for delta calculations
        self.opening_prices = {}  # symbol -> today's opening price
        self.opening_oi = {}  # symbol -> today's opening OI (per strike)
        self.previous_close = {}  # symbol -> previous day close price
        self.baseline_oi = {}  # symbol -> baseline OI for delta calculation
        self.baseline_timestamp = {}  # symbol -> when baseline was set
        
        # Volatility tracking for adaptive thresholds
        self.volatility_history = {}  # symbol -> list of recent price changes
        self.volatility_window = 10  # Track last 10 price changes
        
        # OI history for validation (mirrors single_strike_trader logic)
        self.oi_history = {}  # symbol -> list of recent OI values
        
        # Thread safety
        self.lock = threading.Lock()
        
        logger.info("Engine 1 (Fast Market Analyzer) initialized with adaptive thresholds and entry timing engine")
    
    def initialize_historical_data(self, symbol: str):
        """
        Initialize historical data for VWAP and baseline calculations.
        
        This should be called when Engine 1 starts up or when a new symbol is added.
        Fetches intraday historical data to seed VWAP and establish baselines.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "BANKNIFTY")
        """
        try:
            logger.info(f"Initializing historical data for {symbol}...")
            
            # 1. Get intraday historical data for VWAP seeding
            self._load_intraday_history_for_vwap(symbol)
            
            # 2. Get opening price and previous close
            self._load_price_baselines(symbol)
            
            # 3. Initialize baseline OI (will be updated with first option chain)
            self.baseline_oi[symbol] = {}
            self.baseline_timestamp[symbol] = datetime.now()
            
            logger.info(f"Historical data initialized for {symbol}")
            
        except Exception as e:
            logger.error(f"Error initializing historical data for {symbol}: {e}")
    
    def _load_intraday_history_for_vwap(self, symbol: str):
        """
        Load intraday historical data to seed VWAP calculation.
        
        Fetches 1-minute candles from 9:15 AM to current time to establish
        a proper VWAP baseline instead of starting from zero.
        """
        try:
            # Map symbol to instrument token
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                logger.warning(f"Could not get instrument token for {symbol}")
                # Fallback: Initialize empty price history (will be seeded with live data)
                self.price_history[symbol] = deque(maxlen=self.max_price_history)
                return
            
            # Get current time
            now = datetime.now()
            
            # Try to fetch intraday historical data
            try:
                # Fetch 1-minute candles for today
                from datetime import date
                today = date.today()
                
                # Use Kite historical data API
                historical_data = self.kite_client.kite.historical_data(
                    instrument_token,
                    today,
                    today,
                    interval="minute"
                )
                
                if historical_data:
                    logger.info(f"Loaded {len(historical_data)} historical candles for {symbol}")
                    
                    # Seed price history with historical data
                    self.price_history[symbol] = deque(maxlen=self.max_price_history)
                    
                    for candle in historical_data:
                        # candle format: {'date': datetime, 'open': float, 'high': float, 
                        #                 'low': float, 'close': float, 'volume': int}
                        price = candle['close']
                        volume = candle['volume']
                        timestamp = candle['date']
                        
                        self.price_history[symbol].append((price, volume, timestamp))
                    
                    # Calculate initial VWAP from historical data
                    if len(self.price_history[symbol]) > 0:
                        self.vwap_cache[symbol] = self._calculate_vwap_from_history(symbol)
                        logger.info(f"Seeded VWAP for {symbol}: {self.vwap_cache[symbol]:.2f}")
                else:
                    logger.warning(f"No historical data available for {symbol}")
                    # Fallback: Initialize empty price history (will be seeded with live data)
                    self.price_history[symbol] = deque(maxlen=self.max_price_history)
                    
            except Exception as e:
                logger.warning(f"Could not fetch historical data for {symbol}: {e}")
                # Fallback: Initialize empty price history (will be seeded with live data)
                self.price_history[symbol] = deque(maxlen=self.max_price_history)
                logger.info(f"Will seed VWAP with live data for {symbol}")
                
        except Exception as e:
            logger.error(f"Error in _load_intraday_history_for_vwap: {e}")
            # Fallback: Initialize empty price history (will be seeded with live data)
            self.price_history[symbol] = deque(maxlen=self.max_price_history)
    
    def _load_price_baselines(self, symbol: str):
        """
        Load opening price and previous close for price change calculation.
        
        Price Change = Current LTP - Today's Opening Price
        (or Previous Day Close if opening not available)
        """
        try:
            # Simplified approach: Use current price as baseline initially
            # The price change will be calculated as the difference from the first price seen
            # This is a pragmatic fallback when historical data is not available
            logger.info(f"Using live price baseline for {symbol} (historical data not available)")
            
        except Exception as e:
            logger.error(f"Error in _load_price_baselines: {e}")
    
    def _get_instrument_token(self, symbol: str) -> str:
        """
        Get instrument token for a symbol.
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            Instrument token as string, or None if not found
        """
        try:
            # Try to get from cached instruments
            if hasattr(self.kite_client, 'instruments_cache') and self.kite_client.instruments_cache:
                for instrument in self.kite_client.instruments_cache:
                    # Handle both dict and list formats
                    if isinstance(instrument, dict):
                        tradingsymbol = instrument.get('tradingsymbol', '')
                        if tradingsymbol == symbol or symbol in tradingsymbol:
                            return str(instrument.get('instrument_token'))
            
            # Fallback mappings for common symbols
            token_map = {
                'NIFTY': '256265',
                'BANKNIFTY': '260105',
                'NIFTY 50': '256265',
                'NIFTY BANK': '260105'
            }
            
            return token_map.get(symbol)
            
        except Exception as e:
            logger.error(f"Error getting instrument token for {symbol}: {e}")
            return None
    
    def _calculate_vwap_from_history(self, symbol: str) -> float:
        """
        Calculate VWAP from historical price history.
        
        VWAP = (Sum of Price * Volume) / Sum of Volume
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            VWAP price
        """
        if symbol not in self.price_history or len(self.price_history[symbol]) == 0:
            return 0.0
        
        total_pv = 0.0  # Price * Volume
        total_volume = 0
        
        for price, volume, timestamp in self.price_history[symbol]:
            total_pv += price * volume
            total_volume += volume
        
        if total_volume == 0:
            # Fallback to simple average if no volume data
            return sum(price for price, _, _ in self.price_history[symbol]) / len(self.price_history[symbol])
        
        vwap = total_pv / total_volume
        
        return vwap
    
    def calculate_adaptive_thresholds(self, symbol: str, spot_price: float, price_change: float, delta_oi: int) -> dict:
        """
        Calculate adaptive thresholds based on real-time volatility and market conditions.
        
        This replaces static hardcoded thresholds with dynamic values that respond to:
        - Current price volatility
        - Time of day (market phase)
        - Instrument characteristics
        - Recent OI activity
        
        Args:
            symbol: Instrument symbol
            spot_price: Current spot price
            price_change: Current price change
            delta_oi: Current delta OI
            
        Returns:
            Dictionary with adaptive thresholds
        """
        try:
            # Update volatility history
            if symbol not in self.volatility_history:
                self.volatility_history[symbol] = []
            
            self.volatility_history[symbol].append(abs(price_change))
            
            # Keep only last 10 volatility readings
            if len(self.volatility_history[symbol]) > self.volatility_window:
                self.volatility_history[symbol].pop(0)
            
            # Update OI history for validation
            if symbol not in self.oi_history:
                self.oi_history[symbol] = []
            
            self.oi_history[symbol].append(delta_oi)
            
            # Keep only last 5 OI readings
            if len(self.oi_history[symbol]) > 5:
                self.oi_history[symbol].pop(0)
            
            # Calculate average volatility
            if len(self.volatility_history[symbol]) > 0:
                avg_volatility = sum(self.volatility_history[symbol]) / len(self.volatility_history[symbol])
            else:
                avg_volatility = abs(price_change) if price_change != 0 else 1.0
            
            # Get time factor (market phase adjustment)
            time_factor = self._get_time_factor()
            
            # Get instrument base characteristics
            base_config = self.BREAKOUT_CONFIG.get(symbol, self.BREAKOUT_CONFIG.get("DEFAULT", {
                "price_change": 0.3,
                "vwap_diff": 0.5,
                "oi_threshold": 5000
            }))
            
            # Calculate adaptive price threshold
            # Formula: base_threshold * volatility_factor * time_factor
            volatility_factor = max(0.5, min(2.0, avg_volatility / max(0.1, base_config.get("price_change", 1))))
            adaptive_price_threshold = base_config.get("price_change", 0.3) * volatility_factor * time_factor
            
            # Calculate adaptive OI threshold
            # Formula: base_threshold * time_factor (OI less volatile)
            adaptive_oi_threshold = base_config.get("oi_threshold", 5000) * time_factor
            
            # Calculate adaptive VWAP threshold
            # Formula: max(minimum, price_threshold * 0.6)
            adaptive_vwap_threshold = max(0.2, adaptive_price_threshold * 0.6)
            
            # Ensure minimum thresholds (safety guardrails)
            adaptive_price_threshold = max(0.1, adaptive_price_threshold)
            adaptive_oi_threshold = max(1000, adaptive_oi_threshold)
            adaptive_vwap_threshold = max(0.1, adaptive_vwap_threshold)
            
            logger.debug(f"""
[ADAPTIVE THRESHOLDS] {symbol}
Avg Volatility: {avg_volatility:.2f}
Time Factor: {time_factor:.2f}
Price Threshold: {adaptive_price_threshold:.2f} (base: {base_config.get('price_change', 'N/A')})
OI Threshold: {adaptive_oi_threshold:.0f} (base: {base_config.get('oi_threshold', 'N/A')})
VWAP Threshold: {adaptive_vwap_threshold:.2f}
""")
            
            return {
                "price_threshold": adaptive_price_threshold,
                "oi_threshold": adaptive_oi_threshold,
                "vwap_threshold": adaptive_vwap_threshold,
                "volatility_factor": volatility_factor,
                "time_factor": time_factor
            }
            
        except Exception as e:
            logger.error(f"Error calculating adaptive thresholds for {symbol}: {e}")
            # Fallback to static config
            fallback = self.BREAKOUT_CONFIG.get(symbol, self.BREAKOUT_CONFIG.get("DEFAULT", {
                "price_change": 0.3,
                "vwap_diff": 0.5,
                "oi_threshold": 5000
            }))
            return {
                "price_threshold": fallback.get("price_change", 0.3),
                "oi_threshold": fallback.get("oi_threshold", 5000),
                "vwap_threshold": fallback.get("vwap_diff", 0.5),
                "volatility_factor": 1.0,
                "time_factor": 1.0
            }
    
    def _get_time_factor(self) -> float:
        """
        Get time-based adjustment factor for thresholds.
        
        Market phases:
        - Opening (9:15-10:00): High volatility, higher thresholds
        - Midday (10:00-14:00): Lower volatility, lower thresholds
        - Closing (14:00-15:30): High volatility, higher thresholds
        
        Returns:
            Time factor (0.5-1.5)
        """
        try:
            from datetime import datetime, time as dt_time
            now = datetime.now()
            current_time = now.time()
            
            # Opening phase (9:15-10:00): Higher thresholds
            if dt_time(9, 15) <= current_time <= dt_time(10, 0):
                return 1.3
            
            # Midday phase (10:00-14:00): Lower thresholds
            elif dt_time(10, 0) < current_time < dt_time(14, 0):
                return 0.7
            
            # Closing phase (14:00-15:30): Higher thresholds
            elif dt_time(14, 0) <= current_time <= dt_time(15, 30):
                return 1.2
            
            # Default
            return 1.0
            
        except Exception as e:
            logger.error(f"Error calculating time factor: {e}")
            return 1.0
    
    def calculate_price_change(self, symbol: str, current_price: float) -> float:
        """
        Calculate price change based on established baselines.
        
        Priority:
        1. Today's Opening Price (most accurate for intraday)
        2. Previous Day Close (fallback)
        3. First price seen (pragmatic fallback)
        4. 0 (if no baseline available)
        
        Args:
            symbol: Instrument symbol
            current_price: Current LTP
            
        Returns:
            Price change (current - baseline)
        """
        # Try today's opening price first
        if symbol in self.opening_prices:
            return current_price - self.opening_prices[symbol]
        
        # Fallback to previous close
        if symbol in self.previous_close:
            return current_price - self.previous_close[symbol]
        
        # Pragmatic fallback: Use first price seen as baseline
        if symbol not in self.opening_prices:
            self.opening_prices[symbol] = current_price
            logger.info(f"Established price baseline for {symbol}: {current_price:.2f}")
            return 0.0  # First time, no change
        
        # Calculate change from established baseline
        return current_price - self.opening_prices[symbol]
    
    def update_baseline_oi(self, symbol: str, option_chain: list):
        """
        Update baseline OI for delta calculations.
        
        This should be called when the first option chain is received,
        or periodically to establish a rolling baseline.
        
        Args:
            symbol: Instrument symbol
            option_chain: Current option chain data
        """
        try:
            if symbol not in self.baseline_oi or not self.baseline_oi[symbol]:
                # First time - establish baseline
                self.baseline_oi[symbol] = {}
                for item in option_chain:
                    strike = item.get('strike')
                    call_oi = item.get('call_oi', 0)
                    put_oi = item.get('put_oi', 0)
                    
                    if strike not in self.baseline_oi[symbol]:
                        self.baseline_oi[symbol][strike] = {}
                    
                    self.baseline_oi[symbol][strike]['call_oi'] = call_oi
                    self.baseline_oi[symbol][strike]['put_oi'] = put_oi
                
                self.baseline_timestamp[symbol] = datetime.now()
                logger.info(f"Baseline OI established for {symbol} with {len(self.baseline_oi[symbol])} strikes")
            
        except Exception as e:
            logger.error(f"Error updating baseline OI for {symbol}: {e}")
    
    def calculate_delta_oi(self, symbol: str, current_oi_data: dict) -> int:
        """
        Calculate delta OI based on established baseline.
        
        Delta OI = Current OI - Baseline OI
        
        Args:
            symbol: Instrument symbol
            current_oi_data: Current OI data per strike
            
        Returns:
            Total delta OI (sum of all strike changes)
        """
        try:
            if symbol not in self.baseline_oi or not self.baseline_oi[symbol]:
                # No baseline established yet
                return 0
            
            total_delta = 0
            
            for strike, current_data in current_oi_data.items():
                if strike in self.baseline_oi[symbol]:
                    baseline_call = self.baseline_oi[symbol][strike].get('call_oi', 0)
                    baseline_put = self.baseline_oi[symbol][strike].get('put_oi', 0)
                    
                    current_call = current_data.get('call_oi', 0)
                    current_put = current_data.get('put_oi', 0)
                    
                    # Calculate delta
                    call_delta = current_call - baseline_call
                    put_delta = current_put - baseline_put
                    
                    # Sum absolute changes (or use signed based on strategy)
                    total_delta += abs(call_delta) + abs(put_delta)
            
            return total_delta
            
        except Exception as e:
            logger.error(f"Error calculating delta OI for {symbol}: {e}")
            return 0
    
    def normalize_value(self, value):
        """
        Normalize value to 0-1 range (capped at 1).
        Used for breakout strength calculation.
        """
        return min(value, 1.0)
    
    def calculate_breakout_strength(self, spot, vwap, price_change, delta_oi, price_threshold, vwap_threshold, oi_threshold):
        """
        Calculate breakout strength (normalized, weighted).
        
        Args:
            spot: Current spot price
            vwap: VWAP price
            price_change: Price change
            delta_oi: Total delta OI
            price_threshold: Adaptive price threshold
            vwap_threshold: Adaptive VWAP threshold
            oi_threshold: Adaptive OI threshold
            
        Returns:
            Strength classification: "STRONG", "MODERATE", or "WEAK"
        """
        vwap_diff = abs(spot - vwap)
        
        # Normalize each component (capped at 1)
        vwap_score = self.normalize_value(vwap_diff / vwap_threshold)
        momentum_score = self.normalize_value(abs(price_change) / price_threshold)
        oi_score = self.normalize_value(delta_oi / oi_threshold)
        
        # Weighted strength (VWAP > Momentum > OI)
        strength = (
            0.5 * vwap_score +
            0.3 * momentum_score +
            0.2 * oi_score
        )
        
        # Classification
        if strength >= 0.75:
            return "STRONG", strength
        elif strength >= 0.5:
            return "MODERATE", strength
        else:
            return "WEAK", strength
    
    def pcr_filter(self, pcr, breakout):
        """
        PCR Filter - PCR acts as FILTER for existing breakouts, NOT trade creator.
        
        For BULLISH BREAKOUT:
        PCR < 0.7 → BLOCK (don't trust bullish move)
        PCR 0.7-1.0 → Weak confidence
        PCR 1.0-1.3 → Good
        PCR > 1.3 → Weak (crowded)
        
        For BEARISH BREAKOUT:
        PCR > 1.3 → BLOCK (trap zone)
        PCR 1.0-1.3 → Weak
        PCR 0.7-1.0 → Good
        PCR < 0.7 → Strong
        
        Args:
            pcr: Put-Call Ratio
            breakout: Breakout direction (BULLISH/BEARISH)
            
        Returns:
            Filter decision: "ALLOW", "BLOCK", "WEAK", "STRONG"
        """
        # Bullish breakout
        if breakout == "BULLISH":
            if pcr < 0.7:
                return "BLOCK"  # Don't trust bullish move
            elif pcr > 1.3:
                return "WEAK"  # Crowded
            else:
                return "ALLOW"  # Good confidence
        
        # Bearish breakout
        if breakout == "BEARISH":
            if pcr > 1.3:
                return "BLOCK"  # Trap zone
            elif pcr < 0.7:
                return "STRONG"  # Strong bearish
            else:
                return "ALLOW"  # Good confidence
        
        return "BLOCK"  # No breakout
    
    def update_price(self, symbol: str, price: float, volume: int = 1) -> float:
        """
        Update price history and calculate VWAP for a symbol.
        
        Args:
            symbol: Instrument symbol
            price: Current price
            volume: Trade volume (default 1 for LTP updates)
            
        Returns:
            Current VWAP for the symbol
        """
        with self.lock:
            # Initialize price history if not exists
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.max_price_history)
            
            # Add new price point
            timestamp = time.time()
            self.price_history[symbol].append((price, volume, timestamp))
            
            # Calculate VWAP (uses seeded historical data if available)
            vwap = self._calculate_vwap(symbol)
            self.vwap_cache[symbol] = vwap
            
            return vwap
    
    def _calculate_vwap(self, symbol: str) -> float:
        """
        Calculate Volume Weighted Average Price (VWAP).
        
        VWAP = (Sum of Price * Volume) / Sum of Volume
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            VWAP value
        """
        if symbol not in self.price_history or len(self.price_history[symbol]) == 0:
            return 0.0
        
        price_points = self.price_history[symbol]
        
        # DEBUG: Print VWAP calculation details
        logger.debug(f"""
[VWAP DEBUG] {symbol}
Price Points Count: {len(price_points)}
First Price: {price_points[0][0] if price_points else 'N/A'}
Last Price: {price_points[-1][0] if price_points else 'N/A'}
""")
        
        total_pv = sum(price * volume for price, volume, _ in price_points)
        total_volume = sum(volume for _, volume, _ in price_points)
        
        if total_volume == 0:
            # Fallback to simple average if no volume data
            return sum(price for price, _, _ in price_points) / len(price_points)
        
        vwap = total_pv / total_volume
        
        # DEBUG: Print VWAP result
        logger.debug(f"Calculated VWAP for {symbol}: {vwap:.2f}")
        
        return vwap
    
    def get_vwap(self, symbol: str) -> float:
        """
        Get current VWAP for a symbol.
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            Current VWAP value
        """
        with self.lock:
            return self.vwap_cache.get(symbol, 0.0)
    
    def check_vwap_filter(self, symbol: str, current_price: float, direction: str) -> bool:
        """
        VWAP Filter: Price must be above VWAP for Call setups, below VWAP for Put setups.
        
        Args:
            symbol: Instrument symbol
            current_price: Current spot price
            direction: 'CALL' or 'PUT'
            
        Returns:
            True if VWAP filter passes, False otherwise
        """
        vwap = self.get_vwap(symbol)
        
        if vwap == 0:
            logger.warning(f"VWAP not available for {symbol}, skipping filter")
            return False
        
        if direction == 'CALL':
            passes = current_price > vwap
            logger.info(f"VWAP Filter (CALL): {symbol} Price={current_price:.2f}, VWAP={vwap:.2f}, Pass={passes}")
        else:  # PUT
            passes = current_price < vwap
            logger.info(f"VWAP Filter (PUT): {symbol} Price={current_price:.2f}, VWAP={vwap:.2f}, Pass={passes}")
        
        return passes
    
    def update_option_chain(self, symbol: str, option_chain: List[Dict]):
        """
        Update option chain cache for PCR/OI calculation.
        
        Args:
            symbol: Instrument symbol
            option_chain: List of option chain data with strike, call_oi, put_oi
        """
        with self.lock:
            self.option_chain_cache[symbol] = option_chain
            self.option_chain_cache_time[symbol] = time.time()
    
    def get_option_chain(self, symbol: str, max_age_seconds: int = 60) -> Optional[List[Dict]]:
        """
        Get option chain from cache if fresh enough.
        
        Args:
            symbol: Instrument symbol
            max_age_seconds: Maximum age of cache in seconds
            
        Returns:
            Option chain data or None if cache is stale
        """
        with self.lock:
            if symbol not in self.option_chain_cache:
                return None
            
            cache_time = self.option_chain_cache_time.get(symbol, 0)
            if time.time() - cache_time > max_age_seconds:
                logger.info(f"Option chain cache stale for {symbol}, refresh needed")
                return None
            
            return self.option_chain_cache[symbol]
    
    def calculate_strike_pcr_oi(self, symbol: str, spot_price: float, 
                                 lookback_strikes: int = 3, price_change: float = 0,
                                 delta_oi_data: Dict = None) -> Dict[str, Any]:
        """
        Calculate Strike-Wise PCR & OI Confluence for ATM/NTM strikes.
        
        Args:
            symbol: Instrument symbol
            spot_price: Current spot price
            lookback_strikes: Number of strikes above/below ATM to consider
            price_change: Price change for build-up detection
            delta_oi_data: ΔOI data from prop-desk architecture
            
        Returns:
            Dictionary with PCR, OI data, and build-up patterns
        """
        option_chain = self.get_option_chain(symbol)
        
        if not option_chain:
            logger.warning(f"No option chain data available for {symbol}")
            return None
        
        # Find ATM and nearby strikes
        atm_strike = self._find_atm_strike(option_chain, spot_price)

        if not atm_strike:
            logger.error(f"❌ CRITICAL: Could not find ATM strike for {symbol}")
            logger.error("❌ Option chain may be incomplete or symbol not available")
            logger.error("❌ Signal generation aborted - no valid ATM strike")
            return None
        
        # Get strikes in range (ATM ± lookback_strikes)
        nearby_strikes = self._get_nearby_strikes(
            option_chain, atm_strike, lookback_strikes
        )
        
        if not nearby_strikes:
            logger.warning(f"No nearby strikes found for {symbol}")
            return None
        
        # Calculate PCR for each strike
        strike_analysis = []
        for strike_data in nearby_strikes:
            strike = strike_data['strike']
            call_oi = strike_data.get('call_oi', 0)
            put_oi = strike_data.get('put_oi', 0)
            
            # Calculate PCR
            pcr = put_oi / call_oi if call_oi > 0 else 0
            
            # Determine build-up pattern using ΔOI + Price (CORRECT LOGIC)
            delta_oi = 0
            if delta_oi_data and strike in delta_oi_data:
                # Use ΔOI from prop-desk architecture
                delta_oi = delta_oi_data[strike].get('CE_ΔOI', 0) if strike_data.get('type') == 'CE' else delta_oi_data[strike].get('PE_ΔOI', 0)
            
            build_up = self._determine_buildup_pattern(strike_data, spot_price, price_change, delta_oi)
            
            strike_analysis.append({
                'strike': strike,
                'pcr': pcr,
                'call_oi': call_oi,
                'put_oi': put_oi,
                'build_up': build_up,
                'delta_oi': delta_oi
            })
        
        # Calculate aggregate PCR for ATM/NTM region
        total_call_oi = sum(s['call_oi'] for s in strike_analysis)
        total_put_oi = sum(s['put_oi'] for s in strike_analysis)
        aggregate_pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        
        return {
            'atm_strike': atm_strike,
            'aggregate_pcr': aggregate_pcr,
            'strike_analysis': strike_analysis,
            'total_call_oi': total_call_oi,
            'total_put_oi': total_put_oi
        }
    
    def _find_atm_strike(self, option_chain: List[Dict], spot_price: float) -> Optional[int]:
        """Find the ATM strike from option chain."""
        if not option_chain:
            return None
        
        # Find strike closest to spot price
        atm_strike = min(option_chain, key=lambda x: abs(x['strike'] - spot_price))
        return atm_strike['strike']
    
    def _get_nearby_strikes(self, option_chain: List[Dict], 
                           atm_strike: int, lookback: int) -> List[Dict]:
        """Get strikes within lookback range of ATM."""
        nearby = []
        for strike_data in option_chain:
            strike = strike_data['strike']
            if abs(strike - atm_strike) <= (lookback * 50):  # Assuming 50-point intervals
                nearby.append(strike_data)
        return nearby
    
    def _determine_buildup_pattern(self, strike_data: Dict, spot_price: float, 
                                  price_change: float = 0, delta_oi: float = 0) -> str:
        """
        Determine build-up pattern using ΔOI + Price (CORRECT LOGIC).
        
        Real Build-up (Correct Logic):
        - Long Build-up: Price Up + OI Up (Strong bullish)
        - Short Build-up: Price Down + OI Up (Strong bearish)
        - Short Covering: Price Up + OI Down (Reversal up)
        - Long Unwinding: Price Down + OI Down (Reversal down)
        
        Args:
            strike_data: Strike data with OI
            spot_price: Current spot price
            price_change: Price change
            delta_oi: Change in OI (ΔOI)
            
        Returns:
            'LONG_BUILDUP', 'SHORT_BUILDUP', 'SHORT_COVERING', 'LONG_UNWINDING', or 'NEUTRAL'
        """
        # Use ΔOI + Price for correct build-up detection
        if delta_oi != 0:
            if price_change > 0 and delta_oi > 0:
                return 'LONG_BUILDUP'  # Strong bullish
            elif price_change < 0 and delta_oi > 0:
                return 'SHORT_BUILDUP'  # Strong bearish
            elif price_change > 0 and delta_oi < 0:
                return 'SHORT_COVERING'  # Reversal up
            elif price_change < 0 and delta_oi < 0:
                return 'LONG_UNWINDING'  # Reversal down
            else:
                return 'NEUTRAL'
        else:
            # Fallback to simplified logic if ΔOI not available
            call_oi = strike_data.get('call_oi', 0)
            put_oi = strike_data.get('put_oi', 0)
            
            if call_oi > put_oi * 1.2:
                return 'LONG_BUILDUP'  # More CALL OI suggests bullish buildup
            elif put_oi > call_oi * 1.2:
                return 'SHORT_BUILDUP'  # More PUT OI suggests bearish buildup
            else:
                return 'NEUTRAL'
    
    def classify_pcr(self, pcr: float) -> str:
        """
        Classify PCR into proper ranges (Prop-Level Logic).
        
        PCR Range    Meaning
        < 0.7         Strong bearish
        0.7 – 1.0     Mild bearish
        1.0 – 1.3     Mild bullish
        > 1.3         Strong bullish (possible reversal)
        
        Args:
            pcr: Put-Call Ratio
            
        Returns:
            PCR classification
        """
        if pcr < 0.7:
            return "STRONG_BEARISH"
        elif pcr < 1.0:
            return "BEARISH"
        elif pcr < 1.3:
            return "BULLISH"
        else:
            return "OVERBULLISH"  # Caution - possible reversal
    
    def generate_signal(self, symbol: str, spot_price: float, 
                       price_change: float, delta_oi_data: Dict = None) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal with INSTRUMENT-SPECIFIC BREAKOUT THRESHOLDS + DYNAMIC STRIKE SELECTION.
        
        Layer 1: Engine1 (Binary Detection)
        - PCR in BULLISH/OVERBULLISH or BEARISH/STRONG_BEARISH range
        - Build-up detected
        - Instrument-specific thresholds met
        
        Layer 2: Breakout Strength (Graded Quality)
        - Normalized VWAP (50%)
        - Normalized Momentum (30%)
        - Normalized OI (20%)
        - STRONG/MODERATE/WEAK
        
        Layer 3: Dynamic Strike Selection
        - STRONG → OTM (aggressive, quick profit)
        - MODERATE → ATM (balanced)
        - WEAK → NO TRADE
        
        Args:
            symbol: Instrument symbol
            spot_price: Current spot price
            price_change: Price change percentage
            delta_oi_data: ΔOI data from prop-desk architecture
            
        Returns:
            Signal dictionary or None if no signal
        """
        # Step 1: Check VWAP filter
        vwap = self.get_vwap(symbol)
        if vwap == 0:
            logger.info(f"❌ BLOCKED: VWAP not available for {symbol}")
            return None
        
        # Step 2: Calculate adaptive thresholds (REPLACES STATIC CONFIG)
        # Get total delta OI from data
        total_delta_oi = 0
        if delta_oi_data:
            total_delta_oi = sum(data.get('delta_oi', 0) for data in delta_oi_data.values())
        
        adaptive_thresholds = self.calculate_adaptive_thresholds(symbol, spot_price, price_change, total_delta_oi)
        
        # Use adaptive thresholds instead of static config
        price_threshold = adaptive_thresholds["price_threshold"]
        oi_threshold = adaptive_thresholds["oi_threshold"]
        vwap_threshold = adaptive_thresholds["vwap_threshold"]
        time_factor = adaptive_thresholds["time_factor"]
        
        # LIVE VALIDATION LOG
        logger.info(f"""
[LIVE VALIDATION] {symbol}

Price History: {list(self.price_history.get(symbol, []))}
OI History: {list(self.oi_history.get(symbol, []))}

Price Change: {price_change:.2f}
Delta OI: {total_delta_oi:,}

Dynamic Thresholds:
Price: {price_threshold:.2f}
OI: {oi_threshold:.0f}
VWAP: {vwap_threshold:.2f}

Time Factor: {time_factor:.2f}
""")
        
        # Step 3: Calculate PCR/OI confluence with ΔOI data
        pcr_oi_data = self.calculate_strike_pcr_oi(symbol, spot_price, price_change=price_change, delta_oi_data=delta_oi_data)
        
        if not pcr_oi_data:
            logger.info(f"❌ BLOCKED: PCR/OI data not available for {symbol}")
            return None
        
        # Step 3.5: Calculate Institutional Walls (OptionStar) - CRITICAL
        option_chain = self.get_option_chain(symbol)
        if option_chain:
            # Convert option chain to OptionStar format
            calls = []
            puts = []
            for item in option_chain:
                if item.get('type') == 'CE':
                    calls.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('call_oi', 0)
                    })
                elif item.get('type') == 'PE':
                    puts.append({
                        'strikePrice': item.get('strike'),
                        'openInterest': item.get('put_oi', 0)
                    })
            
            option_chain_data = {"calls": calls, "puts": puts}
            institutional_data = calculate_institutional_walls(option_chain_data, spot_price, symbol)
            
            if "error" not in institutional_data:
                self.institutional_walls[symbol] = institutional_data
                
                # Log institutional walls
                logger.info(f"""
[OPTIONSTAR] {symbol}
Spot: {institutional_data['spot_price']}
Resistance: {institutional_data['resistance']['strike']} (OI: {institutional_data['resistance']['oi']})
Support: {institutional_data['support']['strike']} (OI: {institutional_data['support']['oi']})
Bias: {institutional_data['trend_bias']}
""")
        
        aggregate_pcr = pcr_oi_data['aggregate_pcr']
        atm_strike = pcr_oi_data['atm_strike']
        
        # Step 4: Classify PCR into proper ranges (Prop-Level Logic)
        pcr_bias = self.classify_pcr(aggregate_pcr)
        
        # Calculate total delta OI for OI threshold check
        total_delta_oi = 0
        if delta_oi_data:
            for strike_data in delta_oi_data.values():
                if isinstance(strike_data, dict):
                    total_delta_oi += abs(strike_data.get('ce_delta_oi', 0) + strike_data.get('pe_delta_oi', 0))
        
        # DEBUG: Show debug logs for ALL instruments
        # DEBUG: Check CALL conditions (with adaptive thresholds)
        logger.info(f"""
================================================================================
DEBUG: {symbol} - CALL Signal Check (ADAPTIVE THRESHOLDS)
================================================================================
PCR: {aggregate_pcr:.2f} ({pcr_bias})
Required: BULLISH or OVERBULLISH
Status: {'✅ PASS' if pcr_bias in ['BULLISH', 'OVERBULLISH'] else '❌ FAIL'}

Price Change: {price_change:.4f}
Adaptive Threshold: {price_threshold:.2f} (volatility: {adaptive_thresholds['volatility_factor']:.2f}x, time: {adaptive_thresholds['time_factor']:.2f}x)
Status: {'✅ PASS' if abs(price_change) >= price_threshold else '❌ FAIL'}

Spot vs VWAP: {spot_price:.2f} vs {vwap:.2f} (diff: {abs(spot_price - vwap):.2f})
Adaptive Threshold: {vwap_threshold:.2f}
Status: {'✅ PASS' if abs(spot_price - vwap) >= vwap_threshold else '❌ FAIL'}

Total ΔOI: {total_delta_oi}
Adaptive Threshold: {oi_threshold:.0f}
Status: {'✅ PASS' if total_delta_oi >= oi_threshold else '❌ FAIL'}

Long Build-up: {sum(1 for s in pcr_oi_data['strike_analysis'] if s['build_up'] == 'LONG_BUILDUP')}
Required: > 0
Status: {'✅ PASS' if sum(1 for s in pcr_oi_data['strike_analysis'] if s['build_up'] == 'LONG_BUILDUP') > 0 else '❌ FAIL'}
================================================================================
""")
        
        # DEBUG: Check PUT conditions (with adaptive thresholds)
        logger.info(f"""
================================================================================
DEBUG: {symbol} - PUT Signal Check (ADAPTIVE THRESHOLDS)
================================================================================
PCR: {aggregate_pcr:.2f} ({pcr_bias})
Required: BEARISH or STRONG_BEARISH
Status: {'✅ PASS' if pcr_bias in ['BEARISH', 'STRONG_BEARISH'] else '❌ FAIL'}

Price Change: {price_change:.4f}
Adaptive Threshold: {price_threshold:.2f} (volatility: {adaptive_thresholds['volatility_factor']:.2f}x, time: {adaptive_thresholds['time_factor']:.2f}x)
Status: {'✅ PASS' if abs(price_change) >= price_threshold else '❌ FAIL'}

Spot vs VWAP: {spot_price:.2f} vs {vwap:.2f} (diff: {abs(spot_price - vwap):.2f})
Adaptive Threshold: {vwap_threshold:.2f}
Status: {'✅ PASS' if abs(spot_price - vwap) >= vwap_threshold else '❌ FAIL'}

Total ΔOI: {total_delta_oi}
Adaptive Threshold: {oi_threshold:.0f}
Status: {'✅ PASS' if total_delta_oi >= oi_threshold else '❌ FAIL'}

Short Build-up: {sum(1 for s in pcr_oi_data['strike_analysis'] if s['build_up'] == 'SHORT_BUILDUP')}
Required: > 0
Status: {'✅ PASS' if sum(1 for s in pcr_oi_data['strike_analysis'] if s['build_up'] == 'SHORT_BUILDUP') > 0 else '❌ FAIL'}
================================================================================
""")
        
        # Step 5: Layer 1 - Engine1 Binary Detection
        signal = None
        breakout_strength = None
        strength_score = 0
        recommended_strike = None
        entry_decision = None
        pcr_filter_result = None
        
        # Detect breakout direction
        breakout_direction = "NONE"
        if spot_price > vwap and price_change > 0:
            breakout_direction = "BULLISH"
        elif spot_price < vwap and price_change < 0:
            breakout_direction = "BEARISH"
        
        # Calculate strength scoring for confluence filter (applies to both CALL and PUT)
        strength = 0
        price_condition = abs(price_change) >= price_threshold
        oi_condition = total_delta_oi >= oi_threshold
        vwap_condition = abs(spot_price - vwap) >= vwap_threshold
        
        if price_condition:
            strength += 1
        if oi_condition:
            strength += 1
        if vwap_condition:
            strength += 1
        
        # OI INTELLIGENCE LAYER - Critical Market Interpretation
        # Interpret the combination of price direction + OI change
        if price_change > 0 and total_delta_oi > 0:
            oi_signal = "LONG_BUILDUP"  # Strong bullish
        elif price_change < 0 and total_delta_oi > 0:
            oi_signal = "SHORT_BUILDUP"  # Strong bearish
        elif price_change > 0 and total_delta_oi < 0:
            oi_signal = "SHORT_COVERING"  # Weak bullish (longs covering/shorts exiting)
        elif price_change < 0 and total_delta_oi < 0:
            oi_signal = "LONG_UNWINDING"  # Weak bearish (longs exiting/shorts entering)
        else:
            oi_signal = "NEUTRAL"
        
        # Block weak signals (SHORT_COVERING, LONG_UNWINDING = exhaustion)
        oi_strength_valid = oi_signal in ["LONG_BUILDUP", "SHORT_BUILDUP"]
        
        # OI ANALYSIS LOG
        logger.info(f"""
[OI ANALYSIS] {symbol}

Price Change: {price_change:.2f}
Delta OI: {total_delta_oi:,}

OI Signal: {oi_signal}
OI Strength Valid: {oi_strength_valid}
""")
        
        # TRADE MODE LOGIC - Dual-Mode Execution (Institutional Approach)
        if strength >= 2:
            if oi_signal in ["LONG_BUILDUP", "SHORT_BUILDUP"]:
                trade_mode = "CONFIRMED"   # Strong trade - full size
                lot_size = 2  # or 3 for high conviction
            elif oi_signal == "NEUTRAL":
                trade_mode = "PROBING"     # Early entry - small size
                lot_size = 1  # small risk for early positioning
            else:
                trade_mode = "REJECT"
                lot_size = 0
        else:
            trade_mode = "REJECT"
            lot_size = 0
        
        # TRADE MODE LOG
        logger.info(f"""
[TRADE MODE] {symbol}

Strength: {strength}/3
OI Signal: {oi_signal}

Mode: {trade_mode}
Lot Size: {lot_size if trade_mode != "REJECT" else 0}
""")
        
        # Call Signal: PCR in BULLISH/OVERBULLISH range AND adaptive thresholds
        # Dual-mode execution: CONFIRMED (full size) or PROBING (small size)
        if (pcr_bias in ["BULLISH", "OVERBULLISH"] and 
            strength >= 2 and 
            trade_mode in ["CONFIRMED", "PROBING"]):
            
            # Check for long buildup in strike analysis
            long_buildup_count = sum(
                1 for s in pcr_oi_data['strike_analysis'] 
                if s['build_up'] == 'LONG_BUILDUP'
            )
            
            if long_buildup_count > 0:
                # Layer 2: Calculate Breakout Strength (with adaptive thresholds)
                breakout_strength, strength_score = self.calculate_breakout_strength(
                    spot_price, vwap, price_change, total_delta_oi, 
                    price_threshold, vwap_threshold, oi_threshold
                )
                
                # Layer 2.5: PCR Filter (PCR acts as FILTER, not trade creator)
                pcr_filter_result = self.pcr_filter(aggregate_pcr, breakout_direction)
                
                if pcr_filter_result == "BLOCK":
                    logger.info(f"❌ BLOCKED (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                    return None
                elif pcr_filter_result == "WEAK":
                    logger.info(f"⚠️ WEAK (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                    # Still allow but with warning
                elif pcr_filter_result == "STRONG":
                    logger.info(f"✅ STRONG (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                
                # Layer 3: Entry Timing Engine
                entry_decision = self.entry_engine.get_entry(
                    symbol, breakout_direction, breakout_strength, spot_price, vwap
                )
                
                # Check if entry decision allows trade
                if entry_decision["signal"] == "NO TRADE":
                    logger.info(f"❌ NO TRADE (Entry Engine): {symbol} | Breakout={breakout_direction} | Strength={breakout_strength} | Entry={entry_decision['signal']}")
                    return None
                elif entry_decision["signal"] == "WAIT":
                    logger.info(f"⏳ WAIT (Entry Engine): {symbol} | Breakout={breakout_direction} | Strength={breakout_strength} | Waiting for confirmation")
                    return None
                
                signal = {
                    'symbol': symbol,
                    'direction': 'CALL',
                    'strike': atm_strike,
                    'spot': spot_price,
                    'vwap': vwap,
                    'pcr': aggregate_pcr,
                    'pcr_bias': pcr_bias,
                    'price_change': price_change,
                    'buildup_pattern': 'LONG_BUILDUP',
                    'strength': min(long_buildup_count, 3),  # 1-3 based on buildup strength
                    'breakout_strength': breakout_strength,
                    'strength_score': strength_score,
                    'recommended_strike': entry_decision['strike'],
                    'entry_type': entry_decision['entry_type'],
                    'breakout_direction': breakout_direction,
                    'pcr_filter': pcr_filter_result,
                    'trade_mode': trade_mode,  # CONFIRMED or PROBING
                    'lot_size': lot_size,  # Position sizing based on mode
                    'timestamp': datetime.now().isoformat(),
                    # LLM CONTEXT: Human Emotion / Retail Trap parameters
                    'llm_context': {
                        'market_sentiment': 'BULLISH',
                        'retail_positioning': 'LONG',
                        'trap_detection': 'NONE',
                        'fear_greed': 'GREED',
                        'retail_trap_risk': 'LOW',
                        'smart_money_flow': 'BULLISH_DIVERGENCE',
                        'technical_traps': ['NONE']
                    }
                }
                logger.info(f"🚀 CALL SIGNAL (PCR FILTER): {symbol} | PCR={aggregate_pcr:.2f} ({pcr_bias}) | Filter={pcr_filter_result} | VWAP={vwap:.2f} | Price={spot_price:.2f} | Breakout={breakout_direction} | Strength={breakout_strength} ({strength_score:.2f}) | Entry={entry_decision['entry_type']} | Strike={entry_decision['strike']} | Confluence={strength}/3 | OI Signal={oi_signal} | Trade Mode={trade_mode} | Lot Size={lot_size}")
        
        # Put Signal: PCR in BEARISH/STRONG_BEARISH range AND adaptive thresholds
        # Dual-mode execution: CONFIRMED (full size) or PROBING (small size)
        elif (pcr_bias in ["BEARISH", "STRONG_BEARISH"] and 
              strength >= 2 and 
              trade_mode in ["CONFIRMED", "PROBING"]):
            
            # Check for short buildup in strike analysis
            short_buildup_count = sum(
                1 for s in pcr_oi_data['strike_analysis'] 
                if s['build_up'] == 'SHORT_BUILDUP'
            )
            
            if short_buildup_count > 0:
                # Layer 2: Calculate Breakout Strength (with adaptive thresholds)
                breakout_strength, strength_score = self.calculate_breakout_strength(
                    spot_price, vwap, price_change, total_delta_oi,
                    price_threshold, vwap_threshold, oi_threshold
                )
                
                # Layer 2.5: PCR Filter (PCR acts as FILTER, not trade creator)
                pcr_filter_result = self.pcr_filter(aggregate_pcr, breakout_direction)
                
                if pcr_filter_result == "BLOCK":
                    logger.info(f"❌ BLOCKED (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                    return None
                elif pcr_filter_result == "WEAK":
                    logger.info(f"⚠️ WEAK (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                    # Still allow but with warning
                elif pcr_filter_result == "STRONG":
                    logger.info(f"✅ STRONG (PCR Filter): {symbol} | Breakout={breakout_direction} | PCR={aggregate_pcr:.2f} | Filter={pcr_filter_result}")
                
                # Layer 3: Entry Timing Engine
                entry_decision = self.entry_engine.get_entry(
                    symbol, breakout_direction, breakout_strength, spot_price, vwap
                )
                
                # Check if entry decision allows trade
                if entry_decision["signal"] == "NO TRADE":
                    logger.info(f"❌ NO TRADE (Entry Engine): {symbol} | Breakout={breakout_direction} | Strength={breakout_strength} | Entry={entry_decision['signal']}")
                    return None
                elif entry_decision["signal"] == "WAIT":
                    logger.info(f"⏳ WAIT (Entry Engine): {symbol} | Breakout={breakout_direction} | Strength={breakout_strength} | Waiting for confirmation")
                    return None
                
                signal = {
                    'symbol': symbol,
                    'direction': 'PUT',
                    'strike': atm_strike,
                    'spot': spot_price,
                    'vwap': vwap,
                    'pcr': aggregate_pcr,
                    'pcr_bias': pcr_bias,
                    'price_change': price_change,
                    'buildup_pattern': 'SHORT_BUILDUP',
                    'strength': min(short_buildup_count, 3),  # 1-3 based on buildup strength
                    'breakout_strength': breakout_strength,
                    'strength_score': strength_score,
                    'recommended_strike': entry_decision['strike'],
                    'entry_type': entry_decision['entry_type'],
                    'breakout_direction': breakout_direction,
                    'pcr_filter': pcr_filter_result,
                    'trade_mode': trade_mode,  # CONFIRMED or PROBING
                    'lot_size': lot_size,  # Position sizing based on mode
                    'timestamp': datetime.now().isoformat(),
                    # LLM CONTEXT: Human Emotion / Retail Trap parameters
                    'llm_context': {
                        'market_sentiment': 'BEARISH',
                        'retail_positioning': 'SHORT',
                        'trap_detection': 'NONE',
                        'fear_greed': 'FEAR',
                        'retail_trap_risk': 'LOW',
                        'smart_money_flow': 'BEARISH_DIVERGENCE',
                        'technical_traps': ['NONE']
                    }
                }
                logger.info(f"🚀 PUT SIGNAL (PCR FILTER): {symbol} | PCR={aggregate_pcr:.2f} ({pcr_bias}) | Filter={pcr_filter_result} | VWAP={vwap:.2f} | Price={spot_price:.2f} | Breakout={breakout_direction} | Strength={breakout_strength} ({strength_score:.2f}) | Entry={entry_decision['entry_type']} | Strike={entry_decision['strike']} | Confluence={strength}/3 | OI Signal={oi_signal} | Trade Mode={trade_mode} | Lot Size={lot_size}")
        
        if not signal:
            logger.info(f"""
==============================
SYMBOL: {symbol}

Spot: {spot_price:.2f}
VWAP: {vwap:.2f}
Price Change: {price_change:.4f}
Delta OI: {total_delta_oi}
PCR: {aggregate_pcr:.2f} ({pcr_bias})

Breakout: {breakout_direction if 'breakout_direction' in locals() else 'NONE'}
Strength: {breakout_strength if 'breakout_strength' in locals() else 'NONE'} ({strength_score if 'strength_score' in locals() else 0:.2f})
PCR Filter: {pcr_filter_result if 'pcr_filter_result' in locals() else 'NONE'}
Confluence: {strength if 'strength' in locals() else 0}/3
OI Signal: {oi_signal if 'oi_signal' in locals() else 'NONE'}
Trade Mode: {trade_mode if 'trade_mode' in locals() else 'NONE'}
Lot Size: {lot_size if 'lot_size' in locals() else 0}

FINAL DECISION: NO SIGNAL
==============================
""")
            return signal
        
        # Final debug log (comprehensive)
        logger.info(f"""
==============================
SYMBOL: {symbol}

Spot: {spot_price:.2f}
VWAP: {vwap:.2f}
Price Change: {price_change:.4f}
Delta OI: {total_delta_oi}
PCR: {aggregate_pcr:.2f} ({pcr_bias})

Breakout: {breakout_direction}
Strength: {breakout_strength} ({strength_score:.2f})
PCR Filter: {pcr_filter_result}
Entry Type: {entry_decision['entry_type']}
Strike: {entry_decision['strike']}

FINAL DECISION: {signal['direction']} {signal['entry_type']} {signal['recommended_strike']}
==============================
""")
        
        return signal
    
    def cleanup_old_data(self, max_age_seconds: int = 3600):
        """
        Clean up old price history data to prevent memory bloat.
        
        Args:
            max_age_seconds: Maximum age of data to keep
        """
        with self.lock:
            current_time = time.time()
            
            for symbol in list(self.price_history.keys()):
                # Filter old price points
                filtered_history = deque(
                    [p for p in self.price_history[symbol] 
                     if current_time - p[2] < max_age_seconds],
                    maxlen=self.max_price_history
                )
                self.price_history[symbol] = filtered_history
            
            logger.info("Engine 1: Cleaned up old price data")

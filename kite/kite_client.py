from kiteconnect import KiteConnect
import logging
import time
import threading
import requests
from collections import defaultdict
from datetime import datetime, timedelta, date
import sys
import os

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from utils.expiry_manager import ExpiryManager
from kite.kite_service import KiteService, rate_limiter, nse_expiry_calendar

logger = logging.getLogger(__name__)

class KiteClient:
    def __init__(self, api_key, access_token, paper_trading=False):
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self.paper_trading = paper_trading  # Paper trading: real data, no real orders
        
        # Initialize ExpiryManager for automatic expiry switching
        self.expiry_manager = ExpiryManager(cutoff_hour=15, cutoff_minute=20)
        
        # Cache instruments to avoid repeated API calls (CRITICAL)
        self.instruments_cache = {}  # Initialize as empty dict
        self.instruments_loaded = False

        # OI state for ΔOI calculation (stateful tracking)
        self.previous_oi = {}
        
        # CENTRALIZED LTP CACHE (REST API-based with rate limiting)
        self.ltp_cache = {}  # instrument_token -> last_price
        
        # Rate limiting for REST API calls
        self.last_api_call = 0
        self.min_api_interval = 1.0  # Minimum 1 second between API calls (Kite limit: 3/sec)
        
        if self.paper_trading:
            logger.info("KiteClient initialized in PAPER TRADING MODE - using real Kite API data, no real orders")
        else:
            logger.info("KiteClient initialized in LIVE MODE - using real Kite API")

    def load_instruments_cache(self, segment=None):
        """
        Load instruments from Zerodha API and cache them (do this once at startup)
        """
        if self.instruments_loaded and self.instruments_cache:
            logger.info("Using cached instruments (already loaded)")
            return self.instruments_cache

        try:
            logger.info(f"Loading instruments from Zerodha API (segment: {segment or 'ALL'})...")
            instruments = self.kite.instruments(segment)
            self.instruments_cache = instruments
            self.instruments_loaded = True
            logger.info(f"Loaded {len(instruments)} instruments and cached them")
            return instruments
        except Exception as e:
            logger.error(f"Error loading instruments: {e}")
            return None

    def get_ltp(self, instruments, bypass_cache=False):
        """
        Get LTP for instruments using instrument tokens (rate-limited).
        instruments: ["256265", "260105"] (instrument tokens as strings or integers)
        bypass_cache: Force fresh API call (for high-frequency Engine 1 checks)
        Returns: dict with instrument_token as key and last_price as value
        """
        
        # Use rate-limited fetch to respect Kite 3/sec limit
        instrument_tokens = [str(inst) for inst in instruments]
        
        if bypass_cache:
            # Force fresh API call (still rate-limited)
            return self.safe_ltp_fetch(instrument_tokens)
        else:
            # Try cache first
            cached_data = {}
            for token in instrument_tokens:
                cached_price = self.get_cached_ltp(token)
                if cached_price:
                    cached_data[token] = cached_price
            
            # If all cached, return cache
            if len(cached_data) == len(instrument_tokens):
                return cached_data
            
            # Otherwise fetch fresh data
            return self.safe_ltp_fetch(instrument_tokens)
    
    def _token_to_symbol(self, token: str) -> str:
        """Convert instrument token to symbol (simplified for demo)."""
        # Token to symbol mapping for demo
        token_map = {
            '256265': 'BANKNIFTY',
            '260105': 'NIFTY',
            # Add more mappings as needed
        }
        return token_map.get(token, 'NIFTY')  # Fallback

    def get_historical_data(self, instrument_token, interval, from_date, to_date):
        """
        Get historical data for an instrument.
        
        Args:
            instrument_token: Instrument token (string or integer)
            interval: Time interval - "minute", "15minute", "hour", "day"
            from_date: From date in YYYY-MM-DD format
            to_date: To date in YYYY-MM-DD format
        
        Returns:
            List of candles with date, open, high, low, close, volume
        """
        try:
            instrument_token = str(instrument_token)
            logger.info(f"Fetching historical data for {instrument_token} | Interval: {interval} | {from_date} to {to_date}")
            
            data = self.kite.historical_data(instrument_token, from_date, to_date, interval)
            
            logger.info(f"Retrieved {len(data)} candles")
            return data
            
        except Exception as e:
            logger.error(f"Kite historical data error: {e}")
            return None
    
    def get_option_chain_oi(self, symbol, spot_price, expiry_date=None):
        """
        Fetch real option chain data with Open Interest (OI) from Kite.

        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "BANKNIFTY", "INFY")
            spot_price: Current spot price for strike range calculation
            expiry_date: Expiry date in YYYY-MM-DD format (optional, uses nearest if not provided)

        Returns:
            List of option data with strike, call_oi, put_oi, last_price
        """
        try:
            logger.info(f"Fetching option chain with OI for {symbol} at spot {spot_price}")

            # Load instruments from cache (do this once at startup, not every time!)
            instruments = self.load_instruments_cache("NFO")
            if not instruments:
                logger.error("Failed to load instruments from cache")
                return []

            # Filter for options of the symbol (using cached instruments)
            symbol_options = []
            for instrument in instruments:
                if instrument.get('name') == symbol and instrument.get('segment') in ['NFO-OPT', 'BFO-OPT']:
                    symbol_options.append(instrument)

            logger.info(f"Found {len(symbol_options)} option instruments for {symbol} (from cache)")

            if not symbol_options:
                logger.warning(f"No option instruments found for {symbol}")
                return []

            # Filter by expiry date if provided
            if expiry_date:
                symbol_options = [opt for opt in symbol_options if opt.get('expiry') == expiry_date]
                logger.info(f"Filtered to {len(symbol_options)} options for expiry {expiry_date}")

            # Get quote data with OI for all options (with batching to avoid 414 errors)
            instrument_tokens = [opt.get('instrument_token') for opt in symbol_options]

            # Batch the quote requests to avoid 414 Request-URI Too Large errors
            batch_size = 30  # Reduced from 50 to avoid rate limits
            batch_delay = 1.0  # Increased from 0.5 to 1.0 for rate limit safety
            all_quotes = {}

            for i in range(0, len(instrument_tokens), batch_size):
                batch_tokens = instrument_tokens[i:i + batch_size]
                try:
                    batch_quotes = self.kite.quote(batch_tokens)
                    all_quotes.update(batch_quotes)
                    logger.info(f"Fetched quotes for batch {i//batch_size + 1}/{(len(instrument_tokens) + batch_size - 1)//batch_size}")

                    # Add delay between batches to avoid rate limits
                    if i + batch_size < len(instrument_tokens):
                        time.sleep(batch_delay)
                except Exception as e:
                    logger.error(f"Error fetching quotes for batch {i//batch_size + 1}: {e}")
                    continue

            quote_data = all_quotes

            # Build option chain with OI data from quotes
            option_chain = []
            oi_debug_count = 0
            oi_debug_values = []

            for opt in symbol_options:
                token = opt.get('instrument_token')
                if token in quote_data:
                    quote = quote_data[token]
                    last_price = quote.get('last_price', 0)
                    oi = quote.get('oi', 0)  # Real OI from Zerodha
                    strike = opt.get('strike')

                    # Debug: Track OI values
                    if oi_debug_count < 5:  # Log first 5 OI values for debugging
                        oi_debug_values.append(f"Token {token}: OI={oi}, LTP={last_price}")
                        oi_debug_count += 1

                    # Relaxed OI condition: Accept if oi is not None (not just > 0)
                    if oi is not None:
                        # Check if it's CE or PE
                        instrument_type = opt.get('instrument_type')
                        expiry = opt.get('expiry', '')  # Add expiry field
                        if instrument_type == 'CE':
                            option_chain.append({
                                'strike': strike,
                                'expiry': expiry,  # Add expiry field
                                'call_oi': oi,  # Real OI from Zerodha
                                'put_oi': 0,
                                'last_price': last_price,
                                'type': 'CE'
                            })
                        elif instrument_type == 'PE':
                            option_chain.append({
                                'strike': strike,
                                'expiry': expiry,  # Add expiry field
                                'call_oi': 0,
                                'put_oi': oi,  # Real OI from Zerodha
                                'last_price': last_price,
                                'type': 'PE'
                            })

            # Debug: Log OI values
            logger.info(f"OI Debug (first 5): {oi_debug_values}")
            logger.info(f"Total options with OI data: {len(option_chain)}")

            logger.info(f"Built option chain with {len(option_chain)} strikes with OI data")
            return option_chain

        except Exception as e:
            logger.error(f"Error fetching option chain with OI: {e}")
            return None

    # ========== PROP-DESK LEVEL OPTIMIZED METHODS ==========
    
    def load_instruments_optimized(self, segment="NFO"):
        """
        Load instruments only ONCE and organize by symbol (Prop-Desk Level)
        Supports both NFO and MCX segments
        Returns: option_map[symbol] = [instruments]
        """
        cache_key = f"instruments_{segment}"
        if cache_key in self.instruments_cache:
            logger.info(f"Using cached instruments ({segment})")
            return self.instruments_cache[cache_key]

        try:
            logger.info(f"Loading instruments (ONE TIME) from {segment}...")
            instruments = self.kite.instruments(segment)

            option_map = defaultdict(list)

            for ins in instruments:
                # For NFO, filter options; for MCX, include all
                if segment == "NFO":
                    if ins["segment"] == "NFO-OPT":
                        option_map[ins["name"]].append(ins)
                else:  # MCX
                    option_map[ins["name"]].append(ins)

            self.instruments_cache[cache_key] = option_map
            logger.info(f"Loaded {len(instruments)} instruments, organized by {len(option_map)} symbols")
            return option_map

        except Exception as e:
            logger.error(f"Error loading instruments from {segment}: {e}")
            return {}
    
    def load_nse_instruments(self):
        """
        Load NSE (spot) instruments for stocks without FUT contracts.
        
        Returns:
            Dictionary of NSE instruments organized by symbol
        """
        try:
            logger.info("Loading NSE (spot) instruments for stock fallback...")
            
            instruments = self.kite.instruments("NSE")
            
            nse_map = defaultdict(list)
            
            for ins in instruments:
                # Load all NSE instruments (EQ segment for stocks)
                if ins["segment"] == "NSE-EQ":
                    nse_map[ins["name"]].append(ins)
            
            logger.info(f"Loaded {len(instruments)} NSE instruments, organized by {len(nse_map)} symbols")
            return nse_map
            
        except Exception as e:
            logger.error(f"Error loading NSE instruments: {e}")
            return {}

    def get_mcx_contracts(self, symbol):
        """
        Get MCX contracts for a specific symbol
        Returns: list of contracts
        """
        try:
            instruments = self.kite.instruments("MCX")
            contracts = [
                inst for inst in instruments
                if inst["name"] == symbol
            ]
            logger.info(f"Found {len(contracts)} MCX contracts for {symbol}")
            return contracts
        except Exception as e:
            logger.error(f"Error getting MCX contracts for {symbol}: {e}")
            return []

    def get_nearest_mcx_contract(self, symbol):
        """
        Get nearest active MCX contract (nearest expiry)
        Prefers futures (FUT) over options (CE/PE)
        Returns: contract dict or None
        """
        try:
            instruments = self.kite.instruments("MCX")
            
            # First try to get futures (FUT)
            futures = [
                inst for inst in instruments
                if inst["name"] == symbol and inst.get("expiry") and "FUT" in inst.get("tradingsymbol", "")
            ]
            
            if futures:
                # Sort by expiry (nearest first)
                futures.sort(key=lambda x: x["expiry"])
                nearest = futures[0]
                logger.info(f"Nearest MCX FUTURES contract for {symbol}: {nearest['tradingsymbol']} (Expiry: {nearest['expiry']})")
                return nearest
            
            # Fallback to any contract if no futures found
            contracts = [
                inst for inst in instruments
                if inst["name"] == symbol and inst.get("expiry")
            ]

            if not contracts:
                logger.warning(f"No MCX contracts found for {symbol}")
                return None

            # Sort by expiry (nearest first)
            contracts.sort(key=lambda x: x["expiry"])
            nearest = contracts[0]
            
            logger.info(f"Nearest MCX contract for {symbol}: {nearest['tradingsymbol']} (Expiry: {nearest['expiry']})")
            return nearest

        except Exception as e:
            logger.error(f"Error getting nearest MCX contract for {symbol}: {e}")
            return None

    def filter_strikes_atm(self, options, spot, strike_range=3, step=None):
        """
        Smart strike filtering - ATM ± range (Production-Grade)
        Target: 20-40 options max (NOT 240)
        
        Args:
            options: List of option instruments
            spot: Current spot price
            strike_range: Number of strikes above/below ATM (default 3)
            step: Strike step size (auto-detect if None)
            
        Returns: filtered options, ATM strike
        """
        # Auto-detect step size if not provided
        if step is None:
            # Find the most common strike difference
            strikes = sorted(set([o["strike"] for o in options]))
            if len(strikes) > 1:
                differences = [strikes[i+1] - strikes[i] for i in range(len(strikes)-1)]
                step = max(set(differences), key=differences.count) if differences else 50
                logger.info(f"Auto-detected step size: {step}")
            else:
                step = 50  # Fallback for indices

        # Calculate ATM strike based on step size
        atm = round(spot / step) * step

        # Filter by strike range ONLY (ATM ± strike_range * step)
        selected = []
        for o in options:
            if abs(o["strike"] - atm) <= strike_range * step:
                selected.append(o)

        logger.info(f"ATM strike: {atm}, filtered to {len(selected)} options (±{strike_range} strikes, step={step})")
        
        # Warn if too many options (indicates expiry filtering needed)
        if len(selected) > 40:
            logger.warning(f"Too many options ({len(selected)}), consider adding expiry filtering")
        
        # Fallback: if no options, try without step filtering
        if len(selected) == 0:
            logger.warning(f"No options with step={step}, trying without step filtering")
            strikes = sorted(set([o["strike"] for o in options]))
            atm = min(strikes, key=lambda x: abs(x - spot)) if strikes else spot
            for o in options:
                if abs(o["strike"] - atm) <= strike_range * 50:  # Use 50 as fallback
                    selected.append(o)
            logger.info(f"Fallback: ATM={atm}, filtered to {len(selected)} options (no step filtering)")
        
        return selected, atm

    def filter_strikes_wide_range(self, options, spot, itm_depth=10, otm_depth=10):
        """
        Wide strike filtering - Deep ITM to OTM (Production-Grade)
        Strategy: Deep ITM (10) to OTM (10) = 20 strikes total (FIXED for proper OI distribution)
        For CALL: ATM - 10 to ATM + 10 (ITM to OTM)
        For PUT: ATM - 10 to ATM + 10 (ITM to OTM)
        
        Args:
            options: List of option instruments
            spot: Current spot price
            itm_depth: Number of strikes ITM (default 10 - increased from 5)
            otm_depth: Number of strikes OTM (default 10 - increased from 3)
            
        Returns: filtered options, ATM strike
        """
        # Auto-detect step size if not provided
        strikes = sorted(set([o["strike"] for o in options]))
        if len(strikes) > 1:
            differences = [strikes[i+1] - strikes[i] for i in range(len(strikes)-1)]
            step = max(set(differences), key=differences.count) if differences else 50
            logger.info(f"Auto-detected step size: {step}")
        else:
            step = 50  # Fallback for indices

        # Calculate ATM strike based on step size
        atm = round(spot / step) * step

        # Filter by wide range (Deep ITM to OTM)
        # Include both CE and PE across the full range
        selected = []
        for o in options:
            # Calculate distance from ATM in steps
            distance_steps = abs(o["strike"] - atm) / step
            
            # Include strikes from Deep ITM to OTM
            # For CALL: ATM - 5 to ATM + 3 (ITM to OTM)
            # For PUT: ATM - 3 to ATM + 5 (ITM to OTM)
            # We include both directions to get full range
            if distance_steps <= max(itm_depth, otm_depth):
                selected.append(o)

        logger.info(f"ATM strike: {atm}, filtered to {len(selected)} options (Deep ITM {itm_depth} to OTM {otm_depth}, step={step})")
        
        # Warn if too many options
        if len(selected) > 100:
            logger.warning(f"Too many options ({len(selected)}), consider reducing range")
        
        # Fallback: if no options, try without step filtering
        if len(selected) == 0:
            logger.warning(f"No options with step={step}, trying without step filtering")
            atm = min(strikes, key=lambda x: abs(x - spot)) if strikes else spot
            for o in options:
                if abs(o["strike"] - atm) <= max(itm_depth, otm_depth) * 50:  # Use 50 as fallback
                    selected.append(o)
            logger.info(f"Fallback: ATM={atm}, filtered to {len(selected)} options (no step filtering)")
        
        return selected, atm

    def get_quote(self, instrument_token):
        """
        Get quote for a single instrument.
        
        Args:
            instrument_token: Instrument token
            
        Returns:
            Quote data dictionary
        """
        try:
            rate_limiter.wait()
            quotes = self.kite.quote([instrument_token])
            return quotes.get(str(instrument_token), {})
        except Exception as e:
            logger.error(f"Error fetching quote for {instrument_token}: {e}")
            return {}

    def fetch_quotes_batched(self, tokens, batch_size=80):
        """
        Batched quote fetching with rate limiting and retry (Production-Grade)
        Returns: quotes dict
        """
        quotes = {}

        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]

            # Retry with backoff
            for retry in range(3):
                try:
                    rate_limiter.wait()  # Thread-safe rate limiter
                    data = self.kite.quote(batch)
                    quotes.update(data)
                    logger.info(f"Fetched batch {i//batch_size + 1}/{(len(tokens) + batch_size - 1)//batch_size}: {len(data)} quotes")
                    break  # Success, exit retry loop
                except Exception as e:
                    if "Too many requests" in str(e) or "414" in str(e):
                        logger.warning(f"Rate limit hit on batch {i//batch_size + 1}, retry {retry + 1}/3")
                        time.sleep(1.5 * (retry + 1))  # Backoff: 1.5s, 3s, 4.5s
                    else:
                        logger.error(f"Error fetching batch {i//batch_size + 1}: {e}")
                        break  # Non-rate-limit error, don't retry

        return quotes

    def build_option_chain_optimized(self, options, quotes):
        """
        Build option chain with proper OI structure (Prop-Desk Level)
        Returns: chain[strike][CE/PE] = {oi, ltp, expiry}
        """
        chain = {}

        for opt in options:
            token = opt["instrument_token"]
            symbol = opt["tradingsymbol"]
            expiry = opt.get("expiry", "")  # Add expiry field

            # Try both formats: with and without NFO: prefix
            q = quotes.get(f"NFO:{symbol}", quotes.get(str(token), {}))

            oi = q.get("oi", 0)  # Correct field
            ltp = q.get("last_price", 0)

            strike = opt["strike"]
            typ = "CE" if "CE" in symbol else "PE"

            if strike not in chain:
                chain[strike] = {"CE": {}, "PE": {}}

            chain[strike][typ] = {
                "oi": oi,
                "ltp": ltp,
                "expiry": expiry  # Add expiry field
            }

        return chain

    def compute_oi_metrics(self, chain):
        """
        Compute OI + ΔOI + PCR (Prop-Desk Level)
        Returns: PCR, delta_data
        """
        total_ce_oi = 0
        total_pe_oi = 0
        delta_data = {}

        for strike, data in chain.items():
            ce_oi = data["CE"].get("oi", 0)
            pe_oi = data["PE"].get("oi", 0)

            total_ce_oi += ce_oi
            total_pe_oi += pe_oi

            # ΔOI (Change in OI)
            prev_ce = self.previous_oi.get((strike, "CE"), 0)
            prev_pe = self.previous_oi.get((strike, "PE"), 0)

            delta_ce = ce_oi - prev_ce
            delta_pe = pe_oi - prev_pe

            delta_data[strike] = {
                "CE_ΔOI": delta_ce,
                "PE_ΔOI": delta_pe
            }

            # Update state
            self.previous_oi[(strike, "CE")] = ce_oi
            self.previous_oi[(strike, "PE")] = pe_oi

        pcr = total_pe_oi / total_ce_oi if total_ce_oi != 0 else 0

        logger.info(f"OI Metrics - Total CE OI: {total_ce_oi}, Total PE OI: {total_pe_oi}, PCR: {pcr:.2f}")
        return pcr, delta_data

    def get_option_chain_optimized(self, symbol, spot_price):
        """
        Prop-Desk Level Option Chain (Integrates with Engine1)
        Returns: option_chain, pcr, delta_data, atm_strike
        """
        try:
            logger.info(f"Fetching optimized option chain for {symbol} at spot {spot_price}")

            # 1. Load instruments (cached)
            option_map = self.load_instruments_optimized("NFO")
            if symbol not in option_map:
                logger.warning(f"No options found for {symbol}")
                return None, 0, {}, spot_price

            options = option_map[symbol]

            # 2. Expiry Auto-Switch (Production-Ready)
            # Use ExpiryManager to automatically select correct expiry
            # Handles weekly expiry, expiry day switch, post-expiry rollover
            options_filtered, selected_expiry = self.expiry_manager.filter_options(options)
            
            if selected_expiry:
                expiry_str = selected_expiry.strftime('%Y-%m-%d') if isinstance(selected_expiry, date) else str(selected_expiry)
                logger.info(f"Auto-selected expiry: {expiry_str} ({len(options_filtered)} options)")
            else:
                logger.warning("Could not auto-select expiry, using all options")
            
            options = options_filtered

            # 3. Filter ATM strikes (wider range - Deep ITM to OTM)
            # Strategy: Deep ITM (10) to OTM (10) = 20 strikes total (FIXED for proper OI distribution)
            # For CALL: ATM - 10 to ATM + 10 (ITM to OTM)
            # For PUT: ATM - 10 to ATM + 10 (ITM to OTM)
            filtered, atm = self.filter_strikes_wide_range(options, spot_price, itm_depth=10, otm_depth=10)

            if not filtered:
                logger.warning(f"No filtered options for {symbol}")
                return None, 0, {}, spot_price

            # 3. Prepare tokens
            tokens = [f"NFO:{o['tradingsymbol']}" for o in filtered]

            # 4. Batched quotes with rate limiting and retry
            quotes = self.fetch_quotes_batched(tokens, batch_size=80)

            # 5. Build optimized chain
            chain = self.build_option_chain_optimized(filtered, quotes)

            # 6. Compute OI metrics (OI + ΔOI + PCR)
            pcr, delta_data = self.compute_oi_metrics(chain)

            logger.info(f"Built optimized option chain: {len(chain)} strikes, ATM: {atm}, PCR: {pcr:.2f}")

            return chain, pcr, delta_data, atm
            
        except Exception as e:
            logger.error(f"Error in optimized option chain: {e}")
            return None, 0, {}, spot_price
    
    def get_cached_ltp(self, instrument_token):
        """
        Get LTP from cache (REST API-based with rate limiting).
        
        Args:
            instrument_token: Instrument token
            
        Returns:
            Last price from cache, or None if not available
        """
        return self.ltp_cache.get(str(instrument_token))
    
    def safe_ltp_fetch(self, instruments):
        """
        Safe LTP fetch with rate limiting (REST API).
        
        Args:
            instruments: List of instrument tokens or symbols
            
        Returns:
            Dictionary of LTP values (normalized to float)
        """
        # Rate limiting
        current_time = time.time()
        if current_time - self.last_api_call < self.min_api_interval:
            logger.warning(f"Rate limit: Skipping API call (last call {current_time - self.last_api_call:.2f}s ago)")
            return {}
        
        self.last_api_call = current_time
        
        # Batch fetch
        try:
            if isinstance(instruments, list):
                ltp_data = self.kite.ltp(instruments)
            else:
                ltp_data = self.kite.ltp([instruments])
            
            # Update cache (normalize to float)
            for token, price in ltp_data.items():
                if isinstance(price, dict):
                    self.ltp_cache[str(token)] = price.get('last_price', 0)
                else:
                    self.ltp_cache[str(token)] = price
            
            return ltp_data
        except Exception as e:
            logger.error(f"Error fetching LTP: {e}")
            return {}

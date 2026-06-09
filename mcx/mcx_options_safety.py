"""
MCX Options Safety Modules
Phase 2: Safety filters and strike selectors for MCX options trading
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)

# Global cache for MCX instruments (to avoid repeated API calls)
_mcx_instruments_cache = None
_mcx_instruments_cache_time = None
_mcx_cache_duration = 300  # Cache for 5 minutes (re-enabled to prevent rate limiting)


def mcx_options_filter(option_contract: Dict, market_data: Dict, strict_mode: bool = False, debug_mode: bool = False, symbol_config: Dict = None) -> Tuple[bool, str]:
    """
    Ensures MCX option is tradable (CRITICAL SAFETY LAYER)

    This is the most important filter - it blocks illiquid options
    that could trap your capital.

    Args:
        option_contract: Option contract data
        market_data: Current market data
        strict_mode: If True, use stricter filters for big contracts (CRUDEOIL)
        debug_mode: If True, override filters for system validation
        symbol_config: Market configuration for the symbol (from market_config.py)

    Returns:
        (is_valid, reason) tuple
    """
    volume = option_contract.get("volume", 0)
    oi = option_contract.get("oi", 0)
    bid = option_contract.get("bid", 0)
    ask = option_contract.get("ask", 0)

    # Use market configuration if available, otherwise use hardcoded values
    if symbol_config:
        min_volume = symbol_config.get("min_volume", 10)
        min_oi = symbol_config.get("min_oi", 100)
    else:
        # Fallback to hardcoded values
        if strict_mode:
            min_volume = 10
            min_oi = 100
        else:
            min_volume = 5
            min_oi = 50

    # -------------------------------
    #  LIQUIDITY CHECK (Using market configuration)
    # -------------------------------
    if volume < min_volume:
        if debug_mode:
            logger.warning(f"[DEBUG MODE] Forcing trade despite low volume ({volume} < {min_volume})")
        else:
            return False, f"SKIP: Low volume ({volume} < {min_volume})"
    
    if oi < min_oi:
        if debug_mode:
            logger.warning(f"[DEBUG MODE] Forcing trade despite low OI ({oi} < {min_oi})")
        else:
            return False, f"SKIP: Low OI ({oi} < {min_oi})"

    # -------------------------------
    #  SPREAD CHECK
    # -------------------------------
    if bid and ask:
        spread = (ask - bid) / ask

        if strict_mode:
            # Stricter spread check for CRUDEOIL
            if spread > 0.10:  # 10% spread
                if debug_mode:
                    logger.warning(f"[DEBUG MODE] Forcing trade despite high spread ({spread:.2%} > 10%)")
                else:
                    return False, f"SKIP: High spread ({spread:.2%} > 10%)"
        else:
            if spread > 0.15:  # 15% spread
                if debug_mode:
                    logger.warning(f"[DEBUG MODE] Forcing trade despite high spread ({spread:.2%})")
                else:
                    return False, f"SKIP: High spread ({spread:.2%})"
    else:
        # Skip spread check if no bid/ask data
        logger.debug(f"No bid/ask data - skipping spread check")

    # -------------------------------
    #  STRIKE POSITION CHECK
    # -------------------------------
    spot = market_data.get("price")
    strike = option_contract.get("strike")

    if spot and strike:
        distance = abs(spot - strike) / spot

        if distance > 0.10:  # >10% away = avoid deep OTM
            if debug_mode:
                logger.warning(f"[DEBUG MODE] Forcing trade despite far strike ({distance:.2%} > 10%)")
            else:
                return False, f"SKIP: Strike too far from ATM ({distance:.2%})"

    # -------------------------------
    #  SAFE TO TRADE
    # -------------------------------
    if debug_mode:
        logger.warning("[DEBUG MODE] All filters overridden - forcing trade for testing")
    
    return True, "MCX OPTION VALID"


def select_mcx_option_strike(option_chain: List[Dict], spot_price: float, 
                            option_type: str) -> Optional[Dict]:
    """
    Smart MCX Option Strike Selector (Safe Version)
    
    Priority:
    1. Near ATM (1 step)
    2. High liquidity
    3. Tight spread
    4. Avoid deep OTM
    
    Args:
        option_chain: List of option contracts
        spot_price: Current spot price
        option_type: "CE" or "PE"
        
    Returns:
        Best option contract or None
    """
    if not option_chain:
        logger.warning("Empty option chain provided")
        return None
    
    # Filter CE / PE
    options = [
        opt for opt in option_chain
        if opt.get("instrument_type") == option_type
    ]
    
    if not options:
        logger.warning(f"No {option_type} options found in chain")
        return None
    
    # -------------------------------
    #  FIND ATM STRIKE
    # -------------------------------
    strikes = sorted(set([opt["strike"] for opt in options]))
    atm = min(strikes, key=lambda x: abs(x - spot_price))
    
    step = abs(strikes[1] - strikes[0]) if len(strikes) > 1 else 0
    
    # Only consider near ATM (very important for MCX)
    valid_strikes = [atm, atm - step, atm + step]
    candidates = [opt for opt in options if opt["strike"] in valid_strikes]
    
    if not candidates:
        logger.warning(f"No valid strikes near ATM: {valid_strikes}")
        return None
    
    # -------------------------------
    #  SCORE EACH OPTION
    # -------------------------------
    best_option = None
    best_score = -1
    
    for opt in candidates:
        volume = opt.get("volume", 0)
        oi = opt.get("oi", 0)
        bid = opt.get("bid", 0)
        ask = opt.get("ask", 0)
        
        # Skip dead contracts (AGGRESSIVE for paper trading data collection)
        if volume < 5 or oi < 50:  # Very aggressive for paper trading
            continue
        
        # Spread check (AGGRESSIVE for paper trading data collection)
        if bid and ask:
            spread = (ask - bid) / ask
            if spread > 0.15:  # >15% spread avoid (very aggressive)
                continue
        # No spread check if no bid/ask data (paper trading experimental)
        
        # -------------------------------
        #  SCORING LOGIC
        # -------------------------------
        score = 0
        
        # Liquidity weight
        score += min(volume / 1000, 1) * 40
        score += min(oi / 10000, 1) * 30
        
        # Tight spread bonus
        score += (1 - spread) * 30
        
        # Prefer ATM slightly
        if opt["strike"] == atm:
            score += 10
        
        if score > best_score:
            best_score = score
            best_option = opt
    
    # -------------------------------
    #  FINAL FALLBACK (VERY IMPORTANT)
    # -------------------------------
    if not best_option:
        logger.warning("No ideal MCX option found, using safest ATM fallback")
        
        for opt in options:
            if opt["strike"] == atm:
                logger.info(f"Using ATM fallback: {opt['tradingsymbol']}")
                return opt
    
    if best_option:
        logger.info(f"Selected MCX Option: {best_option['tradingsymbol']} (Score: {best_score:.1f})")
    
    return best_option


def select_mcx_like_nifty(option_chain: List[Dict], spot_price: float, 
                         option_type: str) -> Optional[Dict]:
    """
    NIFTY-style MCX option selector (safe version)
    
    This mimics your NIFTY logic but with MCX safety checks:
    - Try ATM first (like NIFTY)
    - If ATM not liquid, find nearest liquid strike
    - Fallback to ATM if nothing else works
    
    Args:
        option_chain: List of option contracts
        spot_price: Current spot price
        option_type: "CE" or "PE"
        
    Returns:
        Best option contract or None
    """
    options = [
        opt for opt in option_chain
        if opt.get("instrument_type") == option_type
    ]
    
    if not options:
        logger.warning(f"No {option_type} options found")
        return None
    
    # -------------------------------
    #  FIND ATM
    # -------------------------------
    strikes = sorted(set([opt["strike"] for opt in options]))
    atm = min(strikes, key=lambda x: abs(x - spot_price))
    
    # -------------------------------
    #  TRY PURE ATM FIRST (like NIFTY)
    # -------------------------------
    for opt in options:
        if opt["strike"] == atm:
            volume = opt.get("volume", 0)
            oi = opt.get("oi", 0)
            
            if volume > 5 and oi > 50:  # AGGRESSIVE for paper trading data collection
                logger.info(f"Using ATM (NIFTY style): {atm} {option_type}")
                return opt
    
    # -------------------------------
    #  FALLBACK  NEAREST LIQUID
    # -------------------------------
    logger.info("ATM not liquid, searching nearest liquid strike...")
    
    best_option = None
    best_distance = float("inf")
    
    for opt in options:
        volume = opt.get("volume", 0)
        oi = opt.get("oi", 0)
        
        if volume < 5 or oi < 50:  # AGGRESSIVE for paper trading data collection
            continue
        
        distance = abs(opt["strike"] - spot_price)
        
        if distance < best_distance:
            best_distance = distance
            best_option = opt
    
    if best_option:
        logger.info(f"Using nearest liquid strike: {best_option['strike']} {option_type}")
        return best_option
    
    # -------------------------------
    #  FINAL FALLBACK
    # -------------------------------
    logger.warning("No liquid strikes, fallback ATM")
    for opt in options:
        if opt["strike"] == atm:
            logger.info(f"Using ATM fallback: {atm} {option_type}")
            return opt
    
    return None


def mcx_direction_module(price_data: Dict, skip_sideways_check: bool = False, debug_mode: bool = False) -> Tuple[Optional[str], str]:
    """
    MCX Direction + Sideways Detection (Production Trading System)
    
    Args:
        price_data: Dictionary with current, high, low, last prices
        skip_sideways_check: If True, skip sideways filter (for fallback data during warm-up)
        debug_mode: If True, override filters for system validation
    
    Returns: (action, reason)
    action: "CE", "PE", or None
    reason: Explanation
    """
    current_price = price_data["current"]
    recent_high = price_data["high"]
    recent_low = price_data["low"]
    last_price = price_data["last"]
    
    # -------------------------------
    #  SIDEWAYS FILTER (Skip during warm-up/fallback or debug mode)
    # -------------------------------
    if not skip_sideways_check:
        range_size = recent_high - recent_low
        
        if range_size < (0.002 * current_price):  # ~0.2% range
            if debug_mode:
                logger.warning("[DEBUG MODE] Forcing trade despite sideways market (for testing)")
                # In debug mode, still return a direction for testing
                if current_price > (recent_high + recent_low) / 2:
                    return "CE", "DEBUG: Forced CALL (sideways override)"
                else:
                    return "PE", "DEBUG: Forced PUT (sideways override)"
            return None, "SKIP: Sideways market"
    
    # -------------------------------
    #  BREAKOUT LOGIC
    # -------------------------------
    if current_price > recent_high:
        return "CE", "BUY CALL: Breakout above high"
    
    if current_price < recent_low:
        return "PE", "BUY PUT: Breakdown below low"
    
    # -------------------------------
    #  MOMENTUM CONFIRMATION
    # -------------------------------
    move = abs(current_price - last_price)
    
    if move < (0.0005 * current_price):  # weak move
        if debug_mode:
            logger.warning("[DEBUG MODE] Forcing trade despite weak momentum (for testing)")
            # In debug mode, still return a direction for testing
            if current_price > last_price:
                return "CE", "DEBUG: Forced CALL (weak momentum override)"
            else:
                return "PE", "DEBUG: Forced PUT (weak momentum override)"
        return None, "SKIP: Weak momentum"
    
    # DEBUG MODE: Force trade if no clear direction
    if debug_mode:
        logger.warning("[DEBUG MODE] No clear direction, forcing trade for testing")
        if current_price > (recent_high + recent_low) / 2:
            return "CE", "DEBUG: Forced CALL (no direction override)"
        else:
            return "PE", "DEBUG: Forced PUT (no direction override)"
    
    return None, "SKIP: No clear direction"


# -------------------------------
#  INTEGRATION HELPER
# -------------------------------

def get_mcx_option_chain(kite_client, symbol: str, use_big_contract: bool = False, prefer_nearest_expiry: bool = True) -> List[Dict]:
    """
    Fetch MCX option chain for a symbol (with caching to avoid rate limits)

    Args:
        kite_client: KiteClient instance
        symbol: MCX symbol (e.g., "CRUDEOIL", "CRUDEOILM")
        use_big_contract: If True, use CRUDEOIL instead of CRUDEOILM
        prefer_nearest_expiry: If True, filter to nearest expiry only (professional practice)

    Returns:
        List of option contracts
    """
    global _mcx_instruments_cache, _mcx_instruments_cache_time
    
    try:
        # Check cache first (to avoid repeated API calls)
        current_time = time.time()
        if (_mcx_instruments_cache is not None and 
            _mcx_instruments_cache_time is not None and
            (current_time - _mcx_instruments_cache_time) < _mcx_cache_duration):
            logger.debug("Using cached MCX instruments")
            instruments = _mcx_instruments_cache
        else:
            # Fetch fresh data (only if cache expired)
            logger.info("Fetching MCX instruments (cache expired or empty)...")
            instruments = kite_client.kite.instruments("MCX")
            _mcx_instruments_cache = instruments
            _mcx_instruments_cache_time = current_time
            logger.info(f"Cached {len(instruments)} MCX instruments")

        # Determine which symbol to use
        target_symbol = "CRUDEOIL" if (use_big_contract and symbol == "CRUDEOIL") else symbol

        # Filter for options of the symbol (from cached data)
        mcx_options = [
            i for i in instruments
            if i["segment"] == "MCX-OPT" and i["name"] == target_symbol
        ]

        logger.info(f"Found {len(mcx_options)} {target_symbol} options")
        
        # PROFESSIONAL TRADING: Filter to nearest expiry if enabled
        if prefer_nearest_expiry and mcx_options:
            mcx_options = filter_to_nearest_expiry(mcx_options)
            logger.info(f"Filtered to nearest expiry: {len(mcx_options)} options")
        
        return mcx_options

    except Exception as e:
        logger.error(f"Error fetching MCX option chain for {symbol}: {e}")
        return []


def filter_to_nearest_expiry(options: List[Dict]) -> List[Dict]:
    """
    Filter options to nearest expiry only (professional trading practice)
    
    This mimics NSE weekly expiry preference but for MCX monthly expiries.
    Nearest expiry has highest liquidity and most accurate pricing.
    
    Args:
        options: List of option contracts
        
    Returns:
        Filtered list with only nearest expiry options
    """
    if not options:
        return options
    
    # Get all unique expiries
    from datetime import date
    expiries = set([opt.get('expiry') for opt in options if opt.get('expiry')])
    
    if not expiries:
        return options
    
    # Find nearest expiry (minimum days from today)
    today = date.today()
    nearest_expiry = min(expiries, key=lambda x: abs((x - today).days))
    
    # Filter to nearest expiry only
    filtered_options = [opt for opt in options if opt.get('expiry') == nearest_expiry]
    
    logger.info(f"Selected nearest expiry: {nearest_expiry} ({len(filtered_options)} options)")
    
    return filtered_options


def validate_mcx_option_trade(option_contract: Dict, market_data: Dict) -> bool:
    """
    Complete validation before MCX option trade execution
    
    This combines all safety checks
    """
    is_valid, reason = mcx_options_filter(option_contract, market_data)
    
    if not is_valid:
        logger.warning(f"[MCX OPTION BLOCKED] {reason}")
        return False
    
    logger.info(f"[MCX OPTION OK] {option_contract['tradingsymbol']}")
    return True


def create_mcx_option_token_map(option_chain: List[Dict]) -> Dict:
    """
    Create MCX option token map for rendering (similar to NSE format)
    
    Format: {SYMBOL+STRIKE+TYPE: {instrument_token, trading_symbol, expiry, name, strike, type}}
    
    Args:
        option_chain: List of MCX option contracts
        
    Returns:
        Dictionary mapping option tokens to contract details
    """
    token_map = {}
    
    for option in option_chain:
        try:
            # Extract key components
            symbol = option.get('name', '')
            strike = option.get('strike', 0)
            instrument_type = option.get('instrument_type', '')  # CE or PE
            
            # Create token key (similar to NSE format)
            # Example: "CRUDEOIL8550CE" (symbol + strike + type)
            token_key = f"{symbol}{int(strike)}{instrument_type}"
            
            # Create token entry (matching NSE format)
            token_map[token_key] = {
                "instrument_token": str(option.get('instrument_token', '')),
                "trading_symbol": option.get('tradingsymbol', ''),
                "expiry": str(option.get('expiry', '')),
                "name": symbol,
                "strike": float(strike),
                "type": instrument_type
            }
            
        except Exception as e:
            logger.debug(f"Error creating token map entry: {e}")
            continue
    
    logger.info(f"Created MCX option token map: {len(token_map)} options")
    return token_map


def save_mcx_token_map(token_map: Dict, file_path: str = "mcx_option_token_map.json"):
    """
    Save MCX option token map to JSON file for rendering
    
    Args:
        token_map: MCX option token map
        file_path: Path to save the token map
    """
    import json
    try:
        with open(file_path, 'w') as f:
            json.dump(token_map, f, indent=2)
        logger.info(f"MCX option token map saved to {file_path}")
    except Exception as e:
        logger.error(f"Error saving MCX token map: {e}")
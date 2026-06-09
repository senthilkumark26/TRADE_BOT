import re
import time
import logging
import json
from .symbol_lookup import get_symbol_lookup

logger = logging.getLogger(__name__)

def adapt_signal(message: str, kite_client=None):
    """
    Adapt Telegram signal using exact option contract matching
    
    Args:
        message: Telegram message text
        kite_client: Authenticated Kite client (for symbol lookup)
        
    Returns:
        Structured signal dictionary or None
    """
    message = message.upper()

    try:
        # STEP 1: PARSE SIGNAL COMPONENTS FIRST
        # Extract symbol (company name)
        symbol_match = re.search(r'([A-Z]{3,})', message)
        if not symbol_match:
            logger.warning(f"No symbol found in message: {message}")
            return None
        symbol = symbol_match.group(1)
        
        # Normalize common symbol abbreviations from config
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                symbol_normalization = config.get('symbol_normalization', {})
                symbol = symbol_normalization.get(symbol, symbol)
                logger.info(f"Normalized symbol: {symbol}")
                
                # Check if instrument exists in config
                instruments = config.get('instruments', {})
                if symbol not in instruments:
                    logger.warning(f"⚠️ INSTRUMENT NOT IN CONFIG: {symbol}")
                    logger.warning(f"⚠️ Please add {symbol} to config.json instruments section to enable trading")
                    logger.warning(f"⚠️ Available instruments: {list(instruments.keys())}")
                    return None
                else:
                    logger.info(f"✅ Instrument {symbol} found in config - trading enabled")
        except Exception as e:
            logger.warning(f"Could not load symbol normalization from config: {e}")
            logger.info(f"Using original symbol: {symbol}")
        
        # STRIKE + TYPE
        strike_match = re.search(r'(\d{3,5})\s*(CE|PE)', message)
        if not strike_match:
            logger.warning(f"No strike/option type found in message: {message}")
            return None
        strike = int(strike_match.group(1))
        option_type = strike_match.group(2)
        
        # ENTRY
        entry_match = re.search(r'(ABOVE|ABV|@|AT|BUY)\s*(\d+\.?\d*)', message)
        if not entry_match:
            logger.warning(f"No entry price found in message: {message}")
            return None
        entry = float(entry_match.group(2))
        
        # SL
        sl_match = re.search(r'(SL|STOPLOSS)\s*(\d+\.?\d*)', message)
        if not sl_match:
            logger.warning(f"No SL found in message: {message}")
            return None
        sl = float(sl_match.group(2))
        
        # TARGET
        target_match = re.search(r'(TARGET|TGT)\s*(\d+\.?\d*)', message)
        if not target_match:
            logger.warning(f"No target found in message: {message}")
            return None
        target = float(target_match.group(2))
        
        # EXPIRY HINT (OPTIONAL - DO NOT USE FOR SYMBOL BUILDING)
        # This is just a hint for filtering, not for building tradingsymbol
        expiry_hint = None
        expiry_match = re.search(r'(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', message)
        if expiry_match:
            expiry_hint = expiry_match.group(0)
            logger.info(f"Expiry hint from Telegram: {expiry_hint} (will be used for filtering only)")
        
        logger.info(f"Parsed signal: {symbol} {strike} {option_type} @ {entry} SL {sl} TGT {target}")
        
        # STEP 2: FIND EXACT OPTION CONTRACT FROM INSTRUMENT DATA
        # IMPORTANT: Do NOT use Telegram expiry to build symbol
        # Always use actual instrument data from exchange
        symbol_lookup = get_symbol_lookup()
        if not symbol_lookup.initialized and kite_client:
            symbol_lookup.build_symbol_lookup(kite_client)
        
        # Use exact contract matching (symbol + strike + option type)
        # Let exchange data determine the correct tradingsymbol format
        contract = symbol_lookup.find_option_contract(symbol, strike, option_type, kite_client)
        if not contract:
            logger.error(f"Could not find option contract for {symbol} {strike} {option_type}")
            return None
        
        tradingsymbol = contract["tradingsymbol"]
        instrument_token = contract["instrument_token"]
        
        # BONUS SAFETY CHECK: Validate strike match
        if abs(contract["strike"] - strike) > 100:
            logger.error(f"Strike mismatch: requested {strike}, found {contract['strike']}")
            return None
        
        logger.info(f"Found exact contract from exchange: {tradingsymbol} (Token: {instrument_token})")
        
        # Extract expiry date from actual contract (not from Telegram)
        expiry_date = contract.get("expiry", "N/A")
        if expiry_date != "N/A":
            expiry_date = expiry_date.strftime("%Y-%m-%d") if hasattr(expiry_date, "strftime") else str(expiry_date)
        
        # STRICT VALIDATION
        if not (symbol and strike and option_type and entry and sl and target):
            return None
        
        return {
            "symbol": symbol,
            "tradingsymbol": tradingsymbol,  # From exchange, not built from Telegram
            "instrument_token": instrument_token,
            "strike": strike,
            "option_type": option_type,
            "entry": entry,
            "sl": sl,
            "target": target,
            "expiry": expiry_date,  # From exchange contract data
            "source": "TELEGRAM",
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(f"[ADAPTER ERROR] {e}")
        return None

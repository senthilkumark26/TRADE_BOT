"""
Dynamic Symbol Lookup - Professional-grade symbol detection
Uses live instrument data instead of hardcoded symbol maps
"""

import re
import logging
from typing import Dict, Optional, List
from difflib import get_close_matches

logger = logging.getLogger(__name__)


class SymbolLookup:
    """
    Dynamic symbol lookup using live instrument data
    Matches Telegram text to real trading symbols
    """
    
    def __init__(self):
        self.symbol_lookup = {}  # clean_name -> tradingsymbol
        self.tradingsymbol_to_base = {}  # tradingsymbol -> base symbol
        self.base_to_tradingsymbols = {}  # base symbol -> list of tradingsymbols
        self.initialized = False
    
    def build_symbol_lookup(self, kite_client):
        """
        Build symbol lookup from live instrument data
        
        Args:
            kite_client: Authenticated Kite client
        """
        try:
            logger.info("Building dynamic symbol lookup from live instrument data...")
            
            # Get all NFO instruments
            instruments = kite_client.kite.instruments("NFO")
            
            for ins in instruments:
                name = ins.get("name", "").lower()  # e.g. "apollo hospitals"
                tradingsymbol = ins.get("tradingsymbol", "")  # APOLLOHOSP26JUN8700CE
                
                if not name or not tradingsymbol:
                    continue
                
                # Clean name (remove common suffixes)
                clean_name = name.replace("ltd", "").replace("limited", "").strip()
                
                # Store lookup
                self.symbol_lookup[clean_name] = tradingsymbol
                
                # Extract base symbol from tradingsymbol
                base_symbol = self.extract_base_symbol(tradingsymbol)
                if base_symbol:
                    self.tradingsymbol_to_base[tradingsymbol] = base_symbol
                    
                    # Group tradingsymbols by base symbol
                    if base_symbol not in self.base_to_tradingsymbols:
                        self.base_to_tradingsymbols[base_symbol] = []
                    self.base_to_tradingsymbols[base_symbol].append(tradingsymbol)
            
            self.initialized = True
            logger.info(f"Symbol lookup built: {len(self.symbol_lookup)} company names")
            logger.info(f"Base symbols: {len(self.base_to_tradingsymbols)}")
            
        except Exception as e:
            logger.error(f"Error building symbol lookup: {e}")
            self.initialized = False
    
    def extract_base_symbol(self, tradingsymbol: str) -> Optional[str]:
        """
        Extract base symbol from tradingsymbol
        
        Example: APOLLOHOSP26JUN8700CE -> APOLLOHOSP
        
        Args:
            tradingsymbol: Trading symbol from Zerodha
            
        Returns:
            Base symbol or None
        """
        try:
            # Match the base symbol (letters before numbers)
            match = re.match(r"([A-Z]+)", tradingsymbol)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            logger.error(f"Error extracting base symbol from {tradingsymbol}: {e}")
            return None
    
    def find_best_symbol(self, text: str) -> Optional[str]:
        """
        Find best matching tradingsymbol from text
        
        Args:
            text: Telegram message text
            
        Returns:
            Tradingsymbol or None
        """
        if not self.initialized:
            logger.warning("Symbol lookup not initialized")
            return None
        
        text = text.lower()
        
        # Try exact match first
        for name in self.symbol_lookup:
            if name in text:
                logger.info(f"Exact match found: '{name}' -> {self.symbol_lookup[name]}")
                return self.symbol_lookup[name]
        
        # Try fuzzy match as fallback
        return self.find_best_symbol_fuzzy(text)
    
    def find_best_symbol_fuzzy(self, text: str) -> Optional[str]:
        """
        Find best matching tradingsymbol using fuzzy matching
        
        Args:
            text: Telegram message text
            
        Returns:
            Tradingsymbol or None
        """
        if not self.initialized:
            return None
        
        text = text.lower()
        words = text.split()
        
        # Try matching with combined words
        combined_text = " ".join(words)
        matches = get_close_matches(combined_text, self.symbol_lookup.keys(), n=1, cutoff=0.6)
        
        if matches:
            best_match = matches[0]
            logger.info(f"Fuzzy match found: '{best_match}' -> {self.symbol_lookup[best_match]}")
            return self.symbol_lookup[best_match]
        
        # Try matching individual words
        for word in words:
            if len(word) < 3:  # Skip very short words
                continue
            matches = get_close_matches(word, self.symbol_lookup.keys(), n=1, cutoff=0.7)
            if matches:
                best_match = matches[0]
                logger.info(f"Fuzzy match found (word): '{best_match}' -> {self.symbol_lookup[best_match]}")
                return self.symbol_lookup[best_match]
        
        return None
    
    def get_base_symbol(self, tradingsymbol: str) -> Optional[str]:
        """
        Get base symbol from tradingsymbol
        
        Args:
            tradingsymbol: Trading symbol
            
        Returns:
            Base symbol or None
        """
        return self.tradingsymbol_to_base.get(tradingsymbol)
    
    def get_all_tradingsymbols(self, base_symbol: str) -> List[str]:
        """
        Get all tradingsymbols for a base symbol
        
        Args:
            base_symbol: Base symbol (e.g., "NIFTY")
            
        Returns:
            List of tradingsymbols
        """
        return self.base_to_tradingsymbols.get(base_symbol, [])
    
    def find_option_contract(self, symbol: str, strike: int, option_type: str, kite_client) -> Optional[Dict]:
        """
        Find exact option contract matching symbol, strike, and option type.
        
        Args:
            symbol: Base symbol (e.g., "SRF")
            strike: Strike price (e.g., 2740)
            option_type: Option type ("CE" or "PE")
            kite_client: Authenticated Kite client
            
        Returns:
            Instrument data or None
        """
        try:
            logger.info(f"Finding option contract: {symbol} {strike} {option_type}")
            
            # Try NFO first (indices), then NSE (stocks)
            all_instruments = []
            
            try:
                all_instruments.extend(kite_client.kite.instruments("NFO"))
            except Exception as e:
                logger.warning(f"Could not fetch NFO instruments: {e}")
            
            try:
                all_instruments.extend(kite_client.kite.instruments("NSE"))
            except Exception as e:
                logger.warning(f"Could not fetch NSE instruments: {e}")
            
            candidates = []
            
            for ins in all_instruments:
                # Match exact symbol, strike, and option type
                # Note: instrument_type in Zerodha API is "type" in option chain data
                if (
                    ins.get("name", "").upper() == symbol.upper() and
                    ins.get("strike") == strike and
                    ins.get("instrument_type", ins.get("type", "")) == option_type
                ):
                    candidates.append(ins)
            
            if not candidates:
                logger.warning(f"No option contract found for {symbol} {strike} {option_type}")
                return None
            
            # Sort by expiry and pick nearest
            candidates.sort(key=lambda x: x["expiry"])
            best_contract = candidates[0]
            
            logger.info(f"Found option contract: {best_contract['tradingsymbol']} (Expiry: {best_contract['expiry']})")
            return best_contract
            
        except Exception as e:
            logger.error(f"Error finding option contract: {e}")
            return None


# Global instance
_symbol_lookup = None

def get_symbol_lookup() -> SymbolLookup:
    """Get global symbol lookup instance"""
    global _symbol_lookup
    if _symbol_lookup is None:
        _symbol_lookup = SymbolLookup()
    return _symbol_lookup
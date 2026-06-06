"""
Strike Selector Service - Smart strike selection engine
Selects correct expiry, highest liquidity strikes, aligns with OptionStar support/resistance
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class StrikeSelectorService:
    """
    Strike Selector Service - Professional-grade strike selection.
    
    Features:
    - Automatic expiry selection (weekly/monthly)
    - Liquidity-based strike filtering
    - OI + Volume ranking
    - Support/Resistance alignment
    - ATM preference boost
    - Independent microservice with continuous operation
    """
    
    def __init__(self):
        """Initialize the Strike Selector Service"""
        self.service_name = "strike_selector_service"
        self.version = "1.0.0"
        self.dependencies = []
        self.dependents = ["trading_bot", "execution_brain"]
        self.protection_level = "CRITICAL"
        
        # Configuration
        self.atm_range_percent = 0.03  # 3% range for ATM strikes
        self.min_oi_threshold = 10000  # Minimum OI for liquidity
        self.min_volume_threshold = 500  # Minimum volume for liquidity
        self.atm_boost_range = 100  # Points for ATM boost
        
        # State
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # Cache for selected strikes
        self.selected_strikes = {}  # symbol -> strike info
        
        logger.info(f"Strike Selector Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
    
    # -------------------------
    # SELECT BEST EXPIRY (SIMPLIFIED)
    # -------------------------
    def select_best_expiry(self, option_chain: List[Dict], symbol: str) -> Optional[str]:
        """
        Select best expiry from already-filtered option chain.
        
        Note: The option chain is already filtered to the best expiry by the API,
        so we just extract the expiry from the first item.
        
        Args:
            option_chain: List of option chain data (already filtered)
            symbol: Trading symbol
            
        Returns:
            Expiry date string or None
        """
        try:
            if not option_chain:
                logger.warning(f"No option chain data for {symbol}")
                return None
            
            # Option chain is already filtered to best expiry by API
            # Just extract expiry from first item
            expiry = option_chain[0].get("expiry")
            
            if not expiry:
                logger.warning(f"No expiry found in option chain for {symbol}")
                return None
            
            logger.info(f"[EXPIRY SELECTION] {symbol} - Using API-filtered expiry: {expiry}")
            return expiry
            
        except Exception as e:
            logger.error(f"Error selecting expiry: {e}")
            return None
    
    # -------------------------
    # FILTER LIQUID STRIKES
    # -------------------------
    def filter_liquid_strikes(self, option_chain: List[Dict], spot: float) -> List[Dict]:
        """
        Filter strikes based on liquidity criteria.
        
        Args:
            option_chain: List of option chain data
            spot: Current spot price
            
        Returns:
            List of liquid strikes
        """
        try:
            filtered = []
            
            for strike in option_chain:
                strike_price = strike.get("strikePrice", 0)
                
                # Near ATM only (3% range)
                if abs(strike_price - spot) > spot * self.atm_range_percent:
                    continue
                
                call_oi = strike.get("call_oi", 0)
                put_oi = strike.get("put_oi", 0)
                volume = strike.get("volume", 0)
                
                # Liquidity conditions
                if call_oi + put_oi < self.min_oi_threshold:
                    continue
                
                if volume < self.min_volume_threshold:
                    continue
                
                filtered.append(strike)
            
            logger.info(f"[LIQUIDITY FILTER] {len(filtered)} liquid strikes from {len(option_chain)} total")
            return filtered
            
        except Exception as e:
            logger.error(f"Error filtering liquid strikes: {e}")
            return []
    
    # -------------------------
    # RANK STRIKES
    # -------------------------
    def rank_strikes(self, strikes: List[Dict], spot: float) -> List[Dict]:
        """
        Rank strikes by OI + Volume with ATM boost.
        
        Args:
            strikes: List of strike data
            spot: Current spot price
            
        Returns:
            Sorted list of strikes by score
        """
        try:
            for s in strikes:
                base_score = (
                    s.get("call_oi", 0) +
                    s.get("put_oi", 0) +
                    s.get("volume", 0)
                )
                
                # ATM boost (prefer ATM ± 100 points)
                strike_price = s.get("strikePrice", 0)
                if abs(strike_price - spot) < self.atm_boost_range:
                    base_score *= 1.5  # 50% boost for ATM strikes
                
                s["score"] = base_score
            
            ranked = sorted(strikes, key=lambda x: x["score"], reverse=True)
            
            logger.info(f"[STRIKE RANKING] Top 3: {[s.get('strikePrice') for s in ranked[:3]]}")
            return ranked
            
        except Exception as e:
            logger.error(f"Error ranking strikes: {e}")
            return strikes
    
    # -------------------------
    # SELECT BEST STRIKE
    # -------------------------
    def select_best_strike(self, ranked_strikes: List[Dict], signal: str, 
                          optionstar_data: Dict) -> Optional[str]:
        """
        Select best strike aligned with OptionStar support/resistance.
        
        Args:
            ranked_strikes: List of ranked strike data
            signal: Trading signal ("CALL" or "PUT")
            optionstar_data: OptionStar support/resistance data
            
        Returns:
            Best strike string (e.g., "23350 CE") or None
        """
        try:
            support = optionstar_data.get("support", {}).get("strike", 0)
            resistance = optionstar_data.get("resistance", {}).get("strike", 0)
            
            for s in ranked_strikes:
                strike = s.get("strikePrice", 0)
                
                # CALL logic - strike should be above support
                if signal == "CALL":
                    if strike >= support:
                        best_strike = f"{int(strike)} CE"
                        logger.info(f"[STRIKE SELECTION] CALL: {best_strike} (Support: {support})")
                        return best_strike
                
                # PUT logic - strike should be below resistance
                elif signal == "PUT":
                    if strike <= resistance:
                        best_strike = f"{int(strike)} PE"
                        logger.info(f"[STRIKE SELECTION] PUT: {best_strike} (Resistance: {resistance})")
                        return best_strike
            
            logger.warning(f"No suitable strike found for {signal} signal")
            return None
            
        except Exception as e:
            logger.error(f"Error selecting best strike: {e}")
            return None
    
    # -------------------------
    # COMPLETE SELECTION FLOW
    # -------------------------
    def select_strike_complete(self, instruments: List[Dict], symbol: str, 
                             option_chain: List[Dict], spot: float, 
                             signal: str, optionstar_data: Dict) -> Optional[Dict]:
        """
        Complete strike selection flow.
        
        Args:
            instruments: List of instrument data (for reference, not used for expiry)
            symbol: Trading symbol
            option_chain: Option chain data (already filtered to best expiry)
            spot: Current spot price
            signal: Trading signal
            optionstar_data: OptionStar support/resistance data
            
        Returns:
            Dictionary with selected strike info or None
        """
        try:
            logger.info(f"=" * 80)
            logger.info(f"[STRIKE SELECTION] {symbol}")
            logger.info(f"=" * 80)
            
            # Step 1: Select best expiry (simplified - use API-filtered expiry)
            expiry = self.select_best_expiry(option_chain, symbol)
            if not expiry:
                logger.error("Failed to select expiry")
                return None
            
            # Step 2: Filter option chain by expiry (already filtered, so just use as-is)
            filtered_chain = option_chain
            logger.info(f"Using API-filtered expiry {expiry}: {len(filtered_chain)} strikes")
            
            # Step 3: Filter liquid strikes
            liquid_strikes = self.filter_liquid_strikes(filtered_chain, spot)
            if not liquid_strikes:
                logger.error("No liquid strikes found")
                return None
            
            # Step 4: Rank strikes
            ranked_strikes = self.rank_strikes(liquid_strikes, spot)
            
            # Step 5: Select best strike
            best_strike = self.select_best_strike(ranked_strikes, signal, optionstar_data)
            if not best_strike:
                logger.error("Failed to select best strike")
                return None
            
            result = {
                "strike": best_strike,
                "expiry": expiry,
                "signal": signal,
                "spot": spot,
                "support": optionstar_data.get("support", {}).get("strike", 0),
                "resistance": optionstar_data.get("resistance", {}).get("strike", 0),
                "liquid_strikes_count": len(liquid_strikes)
            }
            
            # Cache the selected strike
            with self.lock:
                self.selected_strikes[symbol] = result
            
            logger.info(f"=" * 80)
            logger.info(f"[STRIKE SELECTION COMPLETE]")
            logger.info(f"Expiry: {expiry}")
            logger.info(f"Liquid Strikes: {len(liquid_strikes)}")
            logger.info(f"Best Strike: {best_strike}")
            logger.info(f"=" * 80)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in complete strike selection: {e}")
            return None
    
    # -------------------------
    # GET CACHED STRIKE
    # -------------------------
    def get_cached_strike(self, symbol: str) -> Optional[Dict]:
        """Get cached selected strike for symbol"""
        with self.lock:
            return self.selected_strikes.get(symbol)
    
    # -------------------------
    # START SERVICE
    # -------------------------
    def start(self):
        """Start the Strike Selector Service"""
        if self.running:
            logger.warning("Strike Selector Service already running")
            return
        
        self.running = True
        logger.info("Strike Selector Service started")
    
    # -------------------------
    # STOP SERVICE
    # -------------------------
    def stop(self):
        """Stop the Strike Selector Service"""
        self.running = False
        logger.info("Strike Selector Service stopped")
    
    # -------------------------
    # GET SERVICE INFO
    # -------------------------
    def get_service_info(self) -> Dict[str, Any]:
        """Get service information"""
        return {
            "service": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "running": self.running,
            "config": {
                "atm_range_percent": self.atm_range_percent,
                "min_oi_threshold": self.min_oi_threshold,
                "min_volume_threshold": self.min_volume_threshold,
                "atm_boost_range": self.atm_boost_range
            },
            "cached_strikes": list(self.selected_strikes.keys())
        }

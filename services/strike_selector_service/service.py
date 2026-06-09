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
        
        # Configuration - RELAXED thresholds for better trade execution
        self.atm_range_percent = 0.05  # 5% range for ATM strikes (increased from 3%)
        self.min_oi_threshold = 500  # Minimum OI for liquidity (lowered from 1000)
        self.min_volume_threshold = 25  # Minimum volume for liquidity (lowered from 50)
        self.atm_boost_range = 150  # Points for ATM boost (increased from 100)
        
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
    # SMART STRIKE SELECTOR (PRODUCTION READY)
    # -------------------------
    def select_strike_smart(self, option_chain: List[Dict], spot_price: float, 
                          option_type: str) -> Optional[Dict]:
        """
        Smart Strike Selector (Production Ready)
        
        Priority:
        1. Liquid ATM
        2. Liquid near ATM
        3. Any ATM
        4. Nearest strike fallback
        
        Args:
            option_chain: List of option chain data
            spot_price: Current spot price
            option_type: "CE" or "PE"
            
        Returns:
            Selected option contract or None
        """
        if not option_chain:
            logger.warning("No option chain data provided")
            return None
        
        # Extract strikes (FIXED: use "strike" not "strikePrice" - Zerodha API field name)
        strikes = sorted(set([opt.get("strike", 0) for opt in option_chain if opt.get("strike", 0) > 0]))
        
        if not strikes:
            logger.warning("No valid strikes found in option chain - fallback to raw options")
            return option_chain[0] if option_chain else None
        
        # Find ATM
        atm = min(strikes, key=lambda x: abs(x - spot_price))
        logger.info(f"[SMART SELECTOR] ATM strike: {atm} (Spot: {spot_price})")
        
        # Split CE / PE
        options = [
            opt for opt in option_chain
            if opt.get("type") == option_type
        ]
        
        if not options:
            logger.warning(f"No {option_type} options found")
            return None
        
        # -------------------------------
        # STEP 1: Try LIQUID ATM
        # -------------------------------
        for opt in options:
            if (
                opt.get("strike", 0) == atm and
                opt.get("volume", 0) > 50 and
                opt.get("call_oi", 0) + opt.get("put_oi", 0) > 10000
            ):
                logger.info(f"[SMART SELECTOR] Step 1: Using liquid ATM strike: {atm}")
                return opt
        
        # -------------------------------
        # STEP 2: Try LIQUID NEAR ATM (1 step)
        # -------------------------------
        step = abs(strikes[1] - strikes[0]) if len(strikes) > 1 else 50
        
        near_strikes = [atm - step, atm + step]
        
        for ns in near_strikes:
            for opt in options:
                if (
                    opt.get("strike", 0) == ns and
                    opt.get("volume", 0) > 20 and
                    opt.get("call_oi", 0) + opt.get("put_oi", 0) > 5000
                ):
                    logger.info(f"[SMART SELECTOR] Step 2: Using NEAR ATM strike: {ns}")
                    return opt
        
        # -------------------------------
        # STEP 3: ANY ATM (ignore liquidity)
        # -------------------------------
        for opt in options:
            if opt.get("strike", 0) == atm:
                logger.info(f"[SMART SELECTOR] Step 3: Using ATM fallback (low liquidity): {atm}")
                return opt
        
        # -------------------------------
        # STEP 4: FINAL FALLBACK (NEAREST STRIKE)
        # -------------------------------
        nearest = min(options, key=lambda x: abs(x.get("strike", 0) - spot_price))
        
        logger.info(f"[SMART SELECTOR] Step 4: Using FINAL fallback strike: {nearest.get('strike', 0)}")
        return nearest
    
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
                strike_price = s.get("strike", 0)
                if abs(strike_price - spot) < self.atm_boost_range:
                    base_score *= 1.5  # 50% boost for ATM strikes
                
                s["score"] = base_score
            
            ranked = sorted(strikes, key=lambda x: x["score"], reverse=True)
            
            logger.info(f"[STRIKE RANKING] Top 3: {[s.get('strike') for s in ranked[:3]]}")
            return ranked
            
        except Exception as e:
            logger.error(f"Error ranking strikes: {e}")
            return strikes
    
    # -------------------------
    # SELECT BEST STRIKE (WITH NEAR ATM FALLBACK)
    # -------------------------
    def select_best_strike(self, ranked_strikes: List[Dict], signal: str, 
                          optionstar_data: Dict, spot: float) -> Optional[str]:
        """
        Select best strike aligned with OptionStar support/resistance.
        Includes fallback to nearest ATM if no suitable strike found.
        
        Args:
            ranked_strikes: List of ranked strike data
            signal: Trading signal ("CALL" or "PUT")
            optionstar_data: OptionStar support/resistance data
            spot: Current spot price
            
        Returns:
            Best strike string (e.g., "23350 CE") or None
        """
        try:
            support = optionstar_data.get("support", {}).get("strike", 0)
            resistance = optionstar_data.get("resistance", {}).get("strike", 0)
            
            # Try to find strike aligned with OptionStar
            for s in ranked_strikes:
                strike = s.get("strike", 0)
                
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
            
            # FALLBACK: Use nearest ATM strike
            logger.warning("[FALLBACK] No OptionStar-aligned strike found, using nearest ATM")
            nearest_atm = min(ranked_strikes, key=lambda x: abs(x.get("strike", 0) - spot))
            atm_strike = nearest_atm.get("strike", 0)
            
            if signal == "CALL":
                best_strike = f"{int(atm_strike)} CE"
            else:
                best_strike = f"{int(atm_strike)} PE"
            
            logger.info(f"[FALLBACK] Using nearest ATM: {best_strike} (Spot: {spot})")
            return best_strike
            
        except Exception as e:
            logger.error(f"Error selecting best strike: {e}")
            return None
    
    # -------------------------
    # COMPLETE SELECTION FLOW (USING SMART SELECTOR)
    # -------------------------
    def select_strike_complete(self, instruments: List[Dict], symbol: str, 
                             option_chain: List[Dict], spot: float, 
                             signal: str, optionstar_data: Dict) -> Optional[Dict]:
        """
        Complete strike selection flow using smart selector.
        
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
            
            logger.info(f"Using API-filtered expiry {expiry}: {len(option_chain)} strikes")
            
            # Step 2: Use smart selector to pick best strike
            option_type = "CE" if signal == "CALL" else "PE"
            selected_contract = self.select_strike_smart(option_chain, spot, option_type)
            
            if not selected_contract:
                logger.error("Smart selector failed to find any strike")
                return None
            
            # Extract strike info
            strike_price = selected_contract.get("strike", 0)
            best_strike = f"{int(strike_price)} {option_type}"
            
            result = {
                "strike": best_strike,
                "expiry": expiry,
                "signal": signal,
                "spot": spot,
                "support": optionstar_data.get("support", {}).get("strike", 0),
                "resistance": optionstar_data.get("resistance", {}).get("strike", 0),
                "selected_contract": selected_contract,
                "liquid_strikes_count": len(option_chain)
            }
            
            # Cache the selected strike
            with self.lock:
                self.selected_strikes[symbol] = result
            
            logger.info(f"=" * 80)
            logger.info(f"[STRIKE SELECTION COMPLETE]")
            logger.info(f"Expiry: {expiry}")
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

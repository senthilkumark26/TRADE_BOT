"""
Elite Strike Service - Strike optimization and enhancement layer
Enhances strike selection with smart shifting, gamma preference, and dynamic lot sizing
"""

import logging
import threading
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class EliteStrikeService:
    """
    Elite Strike Service - Professional strike optimization.
    
    Features:
    - Smart strike shifting (price run adjustment)
    - Gamma-style selection (near ATM focus)
    - Dynamic lot sizing (confidence-based)
    - Non-intrusive enhancement layer
    - Independent microservice
    """
    
    def __init__(self):
        """Initialize the Elite Strike Service"""
        self.service_name = "elite_strike_service"
        self.version = "1.0.0"
        self.dependencies = ["strike_selector_service", "execution_brain"]
        self.dependents = ["trade_manager"]
        self.protection_level = "CRITICAL"
        
        # Configuration
        self.strike_shift_step = 50  # Points to shift strike
        self.atm_preference_count = 3  # Number of ATM strikes to consider
        self.high_confidence_threshold = 80  # Score threshold for 3 lots
        self.medium_confidence_threshold = 65  # Score threshold for 2 lots
        
        # State
        self.running = False
        self.lock = threading.Lock()
        
        # Statistics
        self.optimization_count = 0
        self.shift_count = 0
        self.lot_adjustments = {"1_lot": 0, "2_lot": 0, "3_lot": 0}
        
        logger.info(f"Elite Strike Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
    
    # -------------------------
    # SMART STRIKE SHIFTING
    # -------------------------
    def adjust_strike(self, signal: str, strike: str, spot: float) -> str:
        """
        Adjust strike based on price movement (price run adjustment).
        
        Args:
            signal: Trading signal ("CALL" or "PUT")
            strike: Current strike (e.g., "23500 CE")
            spot: Current spot price
            
        Returns:
            Adjusted strike string
        """
        try:
            strike_val = int(strike.split()[0])
            original_strike = strike_val
            
            # If price already moved, shift strike
            if signal == "CALL" and spot > strike_val:
                strike_val += self.strike_shift_step  # Shift ITM to ATM
                self.shift_count += 1
                logger.info(f"[ELITE SHIFT] CALL: {original_strike} -> {strike_val} (Spot: {spot})")
                
            elif signal == "PUT" and spot < strike_val:
                strike_val -= self.strike_shift_step
                self.shift_count += 1
                logger.info(f"[ELITE SHIFT] PUT: {original_strike} -> {strike_val} (Spot: {spot})")
            
            return f"{strike_val} {'CE' if signal == 'CALL' else 'PE'}"
            
        except Exception as e:
            logger.error(f"Error adjusting strike: {e}")
            return strike
    
    # -------------------------
    # GAMMA-STYLE SELECTION
    # -------------------------
    def gamma_preference(self, strikes: List[Dict], spot: float) -> List[Dict]:
        """
        Prefer ATM strikes (gamma-style selection).
        
        Args:
            strikes: List of strike data
            spot: Current spot price
            
        Returns:
            Top N closest strikes to ATM
        """
        try:
            # Prefer ATM ± 1 strikes
            sorted_strikes = sorted(
                strikes,
                key=lambda x: abs(x["strikePrice"] - spot)
            )
            
            preferred = sorted_strikes[:self.atm_preference_count]
            
            logger.info(f"[ELITE GAMMA] Top {len(preferred)} ATM strikes: {[s['strikePrice'] for s in preferred]}")
            return preferred
            
        except Exception as e:
            logger.error(f"Error in gamma preference: {e}")
            return strikes[:self.atm_preference_count]
    
    # -------------------------
    # DYNAMIC LOT SIZING
    # -------------------------
    def dynamic_lot(self, score: float) -> int:
        """
        Calculate lot size based on confidence score.
        
        Args:
            score: Execution confidence score (0-100)
            
        Returns:
            Recommended lot size
        """
        try:
            if score >= self.high_confidence_threshold:
                lot = 3
                self.lot_adjustments["3_lot"] += 1
                logger.info(f"[ELITE LOT] High confidence ({score}) -> 3 lots")
            elif score >= self.medium_confidence_threshold:
                lot = 2
                self.lot_adjustments["2_lot"] += 1
                logger.info(f"[ELITE LOT] Medium confidence ({score}) -> 2 lots")
            else:
                lot = 1
                self.lot_adjustments["1_lot"] += 1
                logger.info(f"[ELITE LOT] Low confidence ({score}) -> 1 lot")
            
            return lot
            
        except Exception as e:
            logger.error(f"Error calculating dynamic lot: {e}")
            return 1
    
    # -------------------------
    # MAIN OPTIMIZER FUNCTION
    # -------------------------
    def optimize(self, symbol: str, signal: str, strike: str, spot: float, 
                ranked_strikes: List[Dict], score: float) -> Dict[str, Any]:
        """
        Main optimizer function - enhances strike selection.
        
        Args:
            symbol: Trading symbol
            signal: Trading signal
            strike: Current strike
            spot: Current spot price
            ranked_strikes: List of ranked strikes
            score: Execution confidence score
            
        Returns:
            Optimized strike and lot size
        """
        try:
            self.optimization_count += 1
            
            logger.info(f"=" * 80)
            logger.info(f"[ELITE OPTIMIZATION] {symbol}")
            logger.info(f"=" * 80)
            logger.info(f"Original Strike: {strike}")
            logger.info(f"Signal: {signal}")
            logger.info(f"Spot: {spot}")
            logger.info(f"Score: {score}")
            
            # 1. Gamma preference - select best ATM strike
            preferred = self.gamma_preference(ranked_strikes, spot)
            
            if not preferred:
                logger.warning("No preferred strikes available, using original")
                best = int(strike.split()[0])
            else:
                best = preferred[0]["strikePrice"]
                logger.info(f"Gamma-preferred strike: {best}")
            
            # 2. Adjust strike if needed (price run adjustment)
            final_strike = self.adjust_strike(signal, f"{best}", spot)
            
            # 3. Dynamic lot sizing
            lot = self.dynamic_lot(score)
            
            result = {
                "strike": final_strike,
                "lot": lot,
                "original_strike": strike,
                "gamma_preferred": best,
                "adjusted": final_strike != f"{best} {'CE' if signal == 'CALL' else 'PE'}"
            }
            
            logger.info(f"=" * 80)
            logger.info(f"[ELITE OPTIMIZATION COMPLETE]")
            logger.info(f"Original: {strike}")
            logger.info(f"Gamma Preferred: {best}")
            logger.info(f"Final Strike: {final_strike}")
            logger.info(f"Lot Size: {lot}")
            logger.info(f"=" * 80)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in optimization: {e}")
            return {
                "strike": strike,
                "lot": 1,
                "original_strike": strike,
                "gamma_preferred": int(strike.split()[0]),
                "adjusted": False
            }
    
    # -------------------------
    # START SERVICE
    # -------------------------
    def start(self):
        """Start the Elite Strike Service"""
        if self.running:
            logger.warning("Elite Strike Service already running")
            return
        
        self.running = True
        logger.info("Elite Strike Service started")
    
    # -------------------------
    # STOP SERVICE
    # -------------------------
    def stop(self):
        """Stop the Elite Strike Service"""
        self.running = False
        logger.info("Elite Strike Service stopped")
    
    # -------------------------
    # GET STATISTICS
    # -------------------------
    def get_statistics(self) -> Dict[str, Any]:
        """Get service statistics"""
        return {
            "optimization_count": self.optimization_count,
            "shift_count": self.shift_count,
            "lot_adjustments": self.lot_adjustments
        }
    
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
                "strike_shift_step": self.strike_shift_step,
                "atm_preference_count": self.atm_preference_count,
                "high_confidence_threshold": self.high_confidence_threshold,
                "medium_confidence_threshold": self.medium_confidence_threshold
            },
            "statistics": self.get_statistics()
        }

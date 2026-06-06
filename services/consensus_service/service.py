"""
Consensus Service - Coordinates between independent services for trade decisions
Combines: Market analysis + Breakout detection → Consensus → LLM final decision
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ConsensusService:
    """
    Consensus Service - Coordinates independent services for trade decisions.
    
    Architecture:
    1. Market Analyzer Service → Identifies potential strikes based on PCR/OI/VWAP
    2. Breakout Entry Service → Identifies entry timing and strike selection
    3. Consensus Service → Finds common strikes and validates agreement
    4. LLM Analyzer → Makes final YES/NO decision on consensus strikes
    """
    
    def __init__(self, llm_analyzer_service=None):
        """Initialize the Consensus Service"""
        self.service_name = "consensus_service"
        self.version = "1.0.0"
        self.dependencies = ["market_analyzer_service", "breakout_entry_service"]
        self.dependents = ["llm_analyzer_service", "trading_bot"]
        self.protection_level = "CRITICAL"
        
        # Reference to LLM Analyzer Service (independent)
        self.llm_analyzer_service = llm_analyzer_service
        
        logger.info(f"Consensus Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"LLM Service: {'Connected' if llm_analyzer_service else 'Not connected'}")
    
    def find_consensus(self, market_analysis: Dict, breakout_analysis: Dict) -> Dict:
        """
        Find consensus between market analyzer and breakout service.
        
        Args:
            market_analysis: Results from Market Analyzer Service
            breakout_analysis: Results from Breakout Entry Service
            
        Returns:
            Dictionary with consensus strikes and confidence levels
        """
        # Extract potential strikes from both services
        market_strikes = market_analysis.get("potential_strikes", [])
        breakout_entry = breakout_analysis.get("entry_decision", {})
        
        # Find common ground
        consensus_strikes = self._find_common_strikes(
            market_strikes, breakout_entry
        )
        
        # Calculate consensus confidence
        consensus_confidence = self._calculate_consensus_confidence(
            market_analysis, breakout_analysis, consensus_strikes
        )
        
        # Determine if consensus is strong enough for LLM review
        llm_review_required = consensus_confidence >= 0.6
        
        return {
            "timestamp": datetime.now().isoformat(),
            "consensus_strikes": consensus_strikes,
            "consensus_confidence": consensus_confidence,
            "llm_review_required": llm_review_required,
            "market_analysis_summary": self._summarize_market_analysis(market_analysis),
            "breakout_analysis_summary": self._summarize_breakout_analysis(breakout_analysis),
            "recommendation": self._make_recommendation(consensus_confidence, llm_review_required)
        }
    
    def _find_common_strikes(self, market_strikes: List[Dict], 
                            breakout_entry: Dict) -> List[Dict]:
        """Find strikes that both services agree on"""
        consensus_strikes = []
        
        # If breakout service has a specific strike recommendation
        if breakout_entry.get("signal") in ["BUY CE", "BUY PE"]:
            breakout_strike = breakout_entry.get("strike")
            breakout_type = breakout_entry.get("entry_type")
            
            # Handle OTM/ATM strike types
            if breakout_strike in ["OTM", "ATM"]:
                # For OTM/ATM, we'll use the best market strike as consensus
                if market_strikes:
                    best_market_strike = max(market_strikes, key=lambda x: x.get("oi", 0))
                    consensus_strikes.append({
                        "strike": best_market_strike["strike"],
                        "breakout_strike": breakout_strike,
                        "entry_type": breakout_type,
                        "market_confidence": best_market_strike.get("recommendation"),
                        "breakout_confidence": breakout_entry.get("signal")
                    })
            else:
                # If breakout service gives a specific numeric strike
                try:
                    breakout_strike_num = float(breakout_strike)
                    # Check if market analyzer also likes this area
                    for market_strike in market_strikes:
                        # If they're in the same area (within 50 points for indices)
                        if abs(market_strike["strike"] - breakout_strike_num) <= 50:
                            consensus_strikes.append({
                                "strike": market_strike["strike"],
                                "breakout_strike": breakout_strike,
                                "entry_type": breakout_type,
                                "market_confidence": market_strike.get("recommendation"),
                                "breakout_confidence": breakout_entry.get("signal")
                            })
                except (ValueError, TypeError):
                    # If strike is not numeric, skip comparison
                    pass
        
        return consensus_strikes
    
    def _calculate_consensus_confidence(self, market_analysis: Dict,
                                       breakout_analysis: Dict,
                                       consensus_strikes: List[Dict]) -> float:
        """Calculate overall consensus confidence"""
        if not consensus_strikes:
            return 0.0
        
        # Market confidence
        market_confidence = market_analysis.get("confidence", 0.0)
        
        # Breakout confidence (based on strength)
        breakout_strength = breakout_analysis.get("strength", "WEAK")
        if breakout_strength == "STRONG":
            breakout_confidence = 0.9
        elif breakout_strength == "MODERATE":
            breakout_confidence = 0.7
        else:
            breakout_confidence = 0.3
        
        # Weighted average
        consensus_confidence = (market_confidence * 0.6) + (breakout_confidence * 0.4)
        
        return consensus_confidence
    
    def _summarize_market_analysis(self, market_analysis: Dict) -> Dict:
        """Summarize market analysis for LLM context"""
        return {
            "pcr_bias": market_analysis.get("market_analysis", {}).get("pcr_bias"),
            "oi_signal": market_analysis.get("market_analysis", {}).get("oi_analysis", {}).get("oi_signal"),
            "vwap_position": market_analysis.get("market_analysis", {}).get("vwap_analysis", {}).get("position"),
            "market_strength": market_analysis.get("market_analysis", {}).get("market_strength"),
            "confidence": market_analysis.get("confidence")
        }
    
    def _summarize_breakout_analysis(self, breakout_analysis: Dict) -> Dict:
        """Summarize breakout analysis for LLM context"""
        return {
            "breakout_direction": breakout_analysis.get("breakout"),
            "breakout_strength": breakout_analysis.get("strength"),
            "entry_type": breakout_analysis.get("entry_decision", {}).get("entry_type"),
            "strike_selection": breakout_analysis.get("entry_decision", {}).get("strike")
        }
    
    def _make_recommendation(self, consensus_confidence: float,
                           llm_review_required: bool) -> str:
        """Make preliminary recommendation"""
        if not llm_review_required:
            return "REJECT - Insufficient consensus"
        elif consensus_confidence >= 0.8:
            return "STRONG CONSENSUS - High priority LLM review"
        elif consensus_confidence >= 0.6:
            return "MODERATE CONSENSUS - Standard LLM review"
        else:
            return "WEAK CONSENSUS - Low priority LLM review"
    
    def prepare_llm_payload(self, consensus_result: Dict) -> Dict:
        """
        Prepare payload for LLM final decision.
        
        Args:
            consensus_result: Results from consensus analysis
            
        Returns:
            Dictionary formatted for LLM analysis
        """
        return {
            "request_type": "TRADE_DECISION",
            "timestamp": datetime.now().isoformat(),
            "consensus_data": {
                "confidence": consensus_result["consensus_confidence"],
                "strikes": consensus_result["consensus_strikes"],
                "market_summary": consensus_result["market_analysis_summary"],
                "breakout_summary": consensus_result["breakout_analysis_summary"]
            },
            "decision_required": "YES" if consensus_result["llm_review_required"] else "NO",
            "context": {
                "independent_services": ["market_analyzer", "breakout_entry"],
                "consensus_mechanism": "strike_agreement + confidence_scoring",
                "final_authority": "LLM_ANALYZER"
            }
        }
    
    def request_llm_decision(self, consensus_result: Dict) -> Dict:
        """
        Request final decision from LLM Analyzer Service.
        
        Args:
            consensus_result: Results from consensus analysis
            
        Returns:
            Dictionary with LLM decision (BUY/SKIP) and reason
        """
        if not self.llm_analyzer_service:
            logger.warning("[CONSENSUS] LLM Analyzer Service not available - REJECTING trade")
            return {
                "decision": "SKIP",
                "reason": "[CONSENSUS] LLM Analyzer Service not available",
                "confidence": 0,
                "source": "CONSENSUS_SERVICE"
            }
        
        # Prepare payload for LLM
        llm_payload = self.prepare_llm_payload(consensus_result)
        
        # Request decision from LLM Analyzer Service
        logger.info("[CONSENSUS] Requesting final decision from LLM Analyzer Service...")
        llm_decision = self.llm_analyzer_service.evaluate_consensus_trade(llm_payload)
        
        return llm_decision
    
    def get_service_info(self) -> Dict:
        """Get service information for service discovery"""
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "consensus_building",
                "strike_agreement",
                "confidence_scoring",
                "llm_payload_preparation",
                "service_coordination"
            ]
        }

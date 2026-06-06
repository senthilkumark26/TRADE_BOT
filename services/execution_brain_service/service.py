"""
Execution Brain Service - Final decision authority for trade execution
Evaluates: Bias alignment, breakout strength, OI confirmation, distance to support/resistance
Output: EXECUTE / PROBING / LLM_REVIEW / SKIP
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionBrainService:
    """
    Execution Brain Service - Final decision authority for trade execution.
    
    This replaces the consensus bottleneck and makes execution decisions based on:
    - Bias alignment (PCR + OI + trend)
    - Breakout strength
    - OI confirmation
    - Distance to support/resistance
    
    Output: EXECUTE / PROBING / LLM_REVIEW / SKIP
    """
    
    def __init__(self):
        """Initialize the Execution Brain Service"""
        self.service_name = "execution_brain_service"
        self.version = "1.0.0"
        self.dependencies = []  # No dependencies
        self.dependents = ["trading_bot"]
        self.protection_level = "CRITICAL"
        
        # Execution thresholds
        self.execute_threshold = 80  # Score >= 80: EXECUTE
        self.probing_threshold = 60  # Score >= 60: PROBING
        self.llm_review_min = 40     # Score 40-60: LLM_REVIEW
        self.llm_review_max = 60
        
        logger.info(f"Execution Brain Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"Execution Thresholds: EXECUTE >= {self.execute_threshold}, PROBING >= {self.probing_threshold}, LLM_REVIEW {self.llm_review_min}-{self.llm_review_max}")
    
    def evaluate_execution(self, signal_package: Dict) -> Dict:
        """
        Evaluate signal package and make execution decision.
        
        Args:
            signal_package: Dictionary with all signal data
                - bias: Market bias (PCR + OI + trend)
                - breakout: Breakout signal
                - oi_signal: OI signal
                - levels: OptionStar support/resistance data
                - spot: Current spot price
                - vwap: Current VWAP
                
        Returns:
            Dictionary with execution decision
        """
        logger.info(f"[EXECUTION BRAIN] Evaluating signal package...")
        
        # Extract signal data
        bias = signal_package.get("bias", {})
        breakout = signal_package.get("breakout", {})
        oi_signal = signal_package.get("oi_signal", {})
        levels = signal_package.get("levels", {})
        spot = signal_package.get("spot", 0)
        vwap = signal_package.get("vwap", 0)
        
        # Calculate execution score
        score = self._calculate_execution_score(bias, breakout, oi_signal, levels, spot, vwap)
        
        # Determine action based on score
        if score >= self.execute_threshold:
            action = "EXECUTE"
            lot_size = self._calculate_lot_size(score, "CONFIRMED")
        elif score >= self.probing_threshold:
            action = "PROBING"
            lot_size = self._calculate_lot_size(score, "PROBING")
        elif self.llm_review_min <= score < self.llm_review_max:
            action = "LLM_REVIEW"
            lot_size = 0
        else:
            action = "SKIP"
            lot_size = 0
        
        # Build decision
        decision = {
            "action": action,
            "score": score,
            "lot_size": lot_size,
            "reason": self._get_decision_reason(action, score),
            "timestamp": datetime.now().isoformat(),
            "signal_package": signal_package
        }
        
        # Print execution log
        self._print_execution_log(decision)
        
        return decision
    
    def _calculate_execution_score(self, bias: Dict, breakout: Dict, 
                                 oi_signal: Dict, levels: Dict, 
                                 spot: float, vwap: float) -> int:
        """Calculate execution score (0-100)"""
        score = 0
        
        # Bias alignment (0-30 points)
        pcr_bias = bias.get("pcr_bias", "NEUTRAL")
        oi_signal_type = oi_signal.get("oi_signal", "NEUTRAL")
        
        if pcr_bias in ["BULLISH", "OVERBULLISH"] and oi_signal_type == "LONG_BUILDUP":
            score += 30
        elif pcr_bias in ["BEARISH", "STRONG_BEARISH"] and oi_signal_type == "SHORT_BUILDUP":
            score += 30
        elif pcr_bias in ["BULLISH", "BEARISH"]:
            score += 20
        elif pcr_bias == "NEUTRAL":
            score += 10
        
        # Breakout strength (0-30 points)
        breakout_direction = breakout.get("breakout", "NONE")
        breakout_strength = breakout.get("strength", "WEAK")
        
        if breakout_direction != "NONE":
            if breakout_strength == "STRONG":
                score += 30
            elif breakout_strength == "MODERATE":
                score += 20
            elif breakout_strength == "WEAK":
                score += 10
        
        # VWAP alignment (0-20 points)
        if spot > vwap and breakout_direction == "BULLISH":
            score += 20
        elif spot < vwap and breakout_direction == "BEARISH":
            score += 20
        elif abs(spot - vwap) / vwap < 0.002:  # Within 0.2% of VWAP
            score += 10
        
        # Support/Resistance proximity (0-20 points)
        support = levels.get("support", 0)
        resistance = levels.get("resistance", 0)
        
        if support > 0 and abs(spot - support) / spot < 0.005:  # Within 0.5% of support
            score += 20
        elif resistance > 0 and abs(spot - resistance) / spot < 0.005:  # Within 0.5% of resistance
            score += 20
        elif support > 0 or resistance > 0:
            score += 10
        
        return min(score, 100)
    
    def _calculate_lot_size(self, score: int, mode: str) -> int:
        """Calculate lot size based on score and mode"""
        if mode == "CONFIRMED":
            if score >= 90:
                return 3
            elif score >= 80:
                return 2
            else:
                return 1
        elif mode == "PROBING":
            return 1
        else:
            return 0
    
    def _get_decision_reason(self, action: str, score: int) -> str:
        """Get reason for decision"""
        if action == "EXECUTE":
            return f"Strong signal alignment (Score: {score})"
        elif action == "PROBING":
            return f"Moderate signal alignment (Score: {score})"
        elif action == "LLM_REVIEW":
            return f"Ambiguous signal - LLM review required (Score: {score})"
        else:
            return f"Weak signal alignment (Score: {score})"
    
    def _print_execution_log(self, decision: Dict):
        """Print execution decision log"""
        signal_package = decision["signal_package"]
        
        bias = signal_package.get("bias", {})
        breakout = signal_package.get("breakout", {})
        oi_signal = signal_package.get("oi_signal", {})
        levels = signal_package.get("levels", {})
        
        print(f"""
[FINAL DECISION ENGINE]

Bias PCR: {bias.get('pcr_bias', 'N/A')}
Bias OI: {oi_signal.get('oi_signal', 'N/A')}
Breakout: {breakout.get('breakout', 'N/A')} ({breakout.get('strength', 'N/A')})
Support: {levels.get('support', 0)}
Resistance: {levels.get('resistance', 0)}

Action: {decision['action']}
Score: {decision['score']}/100
Lot Size: {decision['lot_size']}
Reason: {decision['reason']}
""")
    
    def get_service_info(self) -> Dict:
        """Get service information for service discovery"""
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "execution_decision",
                "bias_evaluation",
                "breakout_validation",
                "oi_confirmation",
                "support_resistance_analysis",
                "lot_sizing"
            ]
        }

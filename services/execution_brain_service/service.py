"""
Execution Brain Service - Final decision authority for trade execution
Evaluates: Bias alignment, breakout strength, OI confirmation, distance to support/resistance
NOW WITH: Confidence-driven execution (OptionStar integration) + Signal Ranking (Multi-signal selection) + Entry Timing Filter
Output: EXECUTE / PROBING / LLM_REVIEW / SKIP
"""

import logging
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, time
from services.signal_ranking_service import get_signal_ranker

logger = logging.getLogger(__name__)


class EntryTimingFilter:
    """
    Entry Timing Filter - Time-based risk control
    Blocks late-day trades, expiry-risk trades, and early market noise
    """
    
    def __init__(self):
        # Configurable thresholds (from config.json)
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                execution_settings = config.get('execution_settings', {})
                self.expiry_buffer_days = execution_settings.get('expiry_buffer_days', 1)
        except Exception as e:
            logger.warning(f"Could not load execution settings from config: {e}")
            self.expiry_buffer_days = 1  # Default fallback
        
        self.market_end_buffer_min = 45   # avoid last 45 mins
        self.market_start_buffer = time(9, 20)  # avoid first 20 mins
    
    def is_valid_entry_time(self, signal: Dict) -> Tuple[bool, str]:
        """
        Check if entry timing is valid.
        
        Args:
            signal: Signal dictionary with expiry info
            
        Returns:
            (is_valid, reason) tuple
        """
        now = datetime.now().time()
        
        # -------------------------------
        # RULE 1: AVOID LATE DAY ENTRY
        # -------------------------------
        market_end = time(15, 30)
        
        minutes_left = (
            (market_end.hour * 60 + market_end.minute) -
            (now.hour * 60 + now.minute)
        )
        
        if minutes_left <= self.market_end_buffer_min:
            return False, f"BLOCKED: Late market entry ({minutes_left} mins left)"
        
        # -------------------------------
        # RULE 2: AVOID EXPIRY DAY
        # -------------------------------
        if "expiry" in signal and signal["expiry"]:
            try:
                expiry_date = datetime.strptime(signal["expiry"], "%Y-%m-%d").date()
                today = datetime.now().date()
                
                days_left = (expiry_date - today).days
                
                if days_left <= self.expiry_buffer_days:
                    return False, f"BLOCKED: Near expiry risk ({days_left} days left)"
            except Exception as e:
                logger.warning(f"Could not parse expiry date: {e}")
        
        # -------------------------------
        # RULE 3: OPTIONAL - EARLY NOISE FILTER
        # -------------------------------
        if now < self.market_start_buffer:
            return False, "BLOCKED: Early market noise"
        
        return True, "VALID"


class ExecutionBrainService:
    """
    Execution Brain Service - Final decision authority for trade execution.
    
    This replaces the consensus bottleneck and makes execution decisions based on:
    - Bias alignment (PCR + OI + trend)
    - Breakout strength
    - OI confirmation
    - Distance to support/resistance
    - CONFIDENCE-driven execution (NEW)
    
    Output: EXECUTE / PROBING / LLM_REVIEW / SKIP
    """
    
    def __init__(self):
        """Initialize the Execution Brain Service"""
        self.service_name = "execution_brain_service"
        self.version = "2.2.0"  # Upgraded for entry timing filter
        self.dependencies = []  # No dependencies
        self.dependents = ["trading_bot"]
        self.protection_level = "CRITICAL"
        
        # Signal Ranking Service integration
        self.signal_ranker = get_signal_ranker()
        
        # Entry Timing Filter integration
        self.timing_filter = EntryTimingFilter()
        
        # Execution thresholds (from config.json - FIX 4: Lower thresholds for realistic trading)
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                execution_settings = config.get('execution_settings', {})
                self.execute_threshold = execution_settings.get('execute_threshold', 35)
                self.probing_threshold = execution_settings.get('probing_threshold', 25)
                self.llm_review_min = execution_settings.get('llm_review_min', 15)
                self.llm_review_max = execution_settings.get('llm_review_max', 25)
        except Exception as e:
            logger.warning(f"Could not load execution thresholds from config: {e}")
            # Default fallback values
            self.execute_threshold = 35
            self.probing_threshold = 25
            self.llm_review_min = 15
            self.llm_review_max = 25
        
        # Trade limits per confidence level
        self.max_trades_high = 5
        self.max_trades_medium = 3
        self.max_trades_low = 1
        
        # Daily trade tracking
        self.trades_today = 0
        self.trades_by_confidence = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        
        logger.info(f"Execution Brain Service initialized (v{self.version})")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
        logger.info(f"Execution Thresholds: EXECUTE >= {self.execute_threshold}, PROBING >= {self.probing_threshold}, LLM_REVIEW {self.llm_review_min}-{self.llm_review_max}")
        logger.info(f"Confidence-Driven Execution: ENABLED (Trade Limits: HIGH={self.max_trades_high}, MEDIUM={self.max_trades_medium}, LOW={self.max_trades_low})")
    
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
                - expiry: Option expiry date (for timing filter)
                
        Returns:
            Dictionary with execution decision
        """
        logger.info(f"[EXECUTION BRAIN] Evaluating signal package...")
        
        # STEP 1: Entry Timing Filter (FIRST CHECK)
        is_valid_timing, timing_reason = self.timing_filter.is_valid_entry_time(signal_package)
        if not is_valid_timing:
            logger.warning(f"[TIMING FILTER] {timing_reason}")
            return {
                "action": "SKIP",
                "score": 0,
                "lot_size": 0,
                "reason": timing_reason,
                "confidence": "LOW",
                "trade_limit_reached": False,
                "timing_blocked": True
            }
        
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
        """Calculate execution score (0-100) - Realistic scoring system"""
        score = 0
        
        # FIX 1: Set proper base scores
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
            score += 10  # Give points for neutral (not zero)
        
        # FIX 2: Breakout strength (0-30 points) - more lenient
        breakout_direction = breakout.get("breakout", "NONE")
        breakout_strength = breakout.get("strength", "WEAK")
        
        if breakout_direction != "NONE":
            if breakout_strength == "STRONG":
                score += 30
            elif breakout_strength == "MODERATE":
                score += 20
            elif breakout_strength == "WEAK":
                score += 15  # Increased from 10 to 15
        
        # FIX 3: VWAP alignment (0-20 points) - more lenient
        if vwap > 0 and spot > 0:  # Prevent division by zero
            if spot > vwap and breakout_direction == "BULLISH":
                score += 20
            elif spot < vwap and breakout_direction == "BEARISH":
                score += 20
            elif abs(spot - vwap) / vwap < 0.005:  # Increased from 0.2% to 0.5%
                score += 15  # Increased from 10 to 15
            else:
                score += 5  # Give partial points for having VWAP data
        
        # FIX 4: Support/Resistance proximity (0-20 points) - more lenient
        support = levels.get("support", 0)
        resistance = levels.get("resistance", 0)
        
        if spot > 0:  # Prevent division by zero
            if support > 0 and abs(spot - support) / spot < 0.01:  # Increased from 0.5% to 1%
                score += 20
            elif resistance > 0 and abs(spot - resistance) / spot < 0.01:  # Increased from 0.5% to 1%
                score += 20
            elif support > 0 or resistance > 0:
                score += 10  # Give points for having level data
        
        # FIX 5: Add base score for having valid data
        score += 10  # Base score for valid signal
        
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
    
    # ==================== CONFIDENCE-DRIVEN EXECUTION (NEW) ====================
    
    def should_enter_trade(self, confidence: str, breakout_strength: str, proximity_to_level: str) -> tuple:
        """
        Entry filtering based on confidence level
        
        Args:
            confidence: HIGH/MEDIUM/LOW from OptionStar
            breakout_strength: STRONG/MODERATE/WEAK from signal
            proximity_to_level: NEAR/FAR from support/resistance
            
        Returns:
            (allowed: bool, reason: str)
        """
        if confidence == "LOW":
            return False, "LOW_CONFIDENCE"
        
        if confidence == "MEDIUM":
            if breakout_strength != "STRONG":
                return False, "WEAK_BREAKOUT_MEDIUM_CONF"
        
        if proximity_to_level == "TOO_CLOSE_TO_RESISTANCE":
            return False, "NEAR_RESISTANCE"
        
        return True, "VALID"
    
    def get_position_size(self, base_lot: int, confidence: str) -> int:
        """
        Position sizing based on confidence level
        
        Args:
            base_lot: Base lot size from risk management
            confidence: HIGH/MEDIUM/LOW from OptionStar
            
        Returns:
            Adjusted lot size
        """
        if confidence == "HIGH":
            multiplier = 1.0
        elif confidence == "MEDIUM":
            multiplier = 0.6
        else:  # LOW
            multiplier = 0.3
        
        return max(1, int(base_lot * multiplier))
    
    def adjust_sl(self, entry: float, original_sl: float, confidence: str) -> float:
        """
        Stop loss adjustment based on confidence level
        
        Args:
            entry: Entry price
            original_sl: Original stop loss
            confidence: HIGH/MEDIUM/LOW from OptionStar
            
        Returns:
            Adjusted stop loss
        """
        risk = abs(entry - original_sl)
        
        if confidence == "HIGH":
            # Tighter SL (better precision)
            adjusted_sl = entry - (risk * 0.8)
        elif confidence == "MEDIUM":
            # Keep original
            adjusted_sl = original_sl
        else:  # LOW
            # Wider SL or skip trade
            adjusted_sl = entry - (risk * 1.2)
        
        return adjusted_sl
    
    def max_trades_allowed(self, confidence: str) -> int:
        """
        Trade limit control based on confidence level
        
        Args:
            confidence: HIGH/MEDIUM/LOW from OptionStar
            
        Returns:
            Maximum trades allowed for this confidence level
        """
        if confidence == "HIGH":
            return self.max_trades_high
        elif confidence == "MEDIUM":
            return self.max_trades_medium
        else:  # LOW
            return self.max_trades_low
    
    def evaluate_trade_with_confidence(self, signal: Dict, optionstar_data: Dict) -> Dict:
        """
        Master evaluation function with confidence-driven logic
        
        Args:
            signal: Signal dictionary with entry, sl, base_lot, breakout_strength, level_proximity, expiry
            optionstar_data: OptionStar data with confidence, support, resistance
            
        Returns:
            Decision dictionary with action, lot, sl, confidence, reason
        """
        # STEP 0: Entry Timing Filter (FIRST CHECK)
        is_valid_timing, timing_reason = self.timing_filter.is_valid_entry_time(signal)
        if not is_valid_timing:
            logger.warning(f"[TIMING FILTER] {timing_reason}")
            return {
                "action": "SKIP",
                "reason": timing_reason,
                "confidence": "LOW",
                "lot": 0,
                "sl": signal.get("sl", 0),
                "timing_blocked": True
            }
        
        confidence = optionstar_data.get("confidence", {}).get("level", "MEDIUM")
        breakout = signal.get("breakout_strength", "MODERATE")
        proximity = signal.get("level_proximity", "FAR")
        
        # STEP 1: Entry filter
        allowed, reason = self.should_enter_trade(confidence, breakout, proximity)
        if not allowed:
            return {
                "action": "SKIP",
                "reason": reason,
                "confidence": confidence,
                "lot": 0,
                "sl": signal.get("sl", 0)
            }
        
        # STEP 2: Trade limit check
        max_allowed = self.max_trades_allowed(confidence)
        current_trades = self.trades_by_confidence.get(confidence, 0)
        
        if current_trades >= max_allowed:
            return {
                "action": "SKIP",
                "reason": f"TRADE_LIMIT_REACHED ({confidence}: {current_trades}/{max_allowed})",
                "confidence": confidence,
                "lot": 0,
                "sl": signal.get("sl", 0)
            }
        
        # STEP 3: Position sizing
        base_lot = signal.get("base_lot", 1)
        lot = self.get_position_size(base_lot, confidence)
        
        # STEP 4: SL adjustment
        entry = signal.get("entry", 0)
        original_sl = signal.get("sl", 0)
        sl = self.adjust_sl(entry, original_sl, confidence)
        
        # STEP 5: Execute trade
        self.trades_today += 1
        self.trades_by_confidence[confidence] += 1
        
        return {
            "action": "EXECUTE",
            "lot": lot,
            "sl": sl,
            "confidence": confidence,
            "confidence_score": optionstar_data.get("confidence", {}).get("score", 0.5),
            "reason": f"VALID ({confidence} confidence)",
            "trade_count": self.trades_by_confidence[confidence]
        }
    
    def reset_daily_limits(self):
        """Reset daily trade limits (call at market open)"""
        self.trades_today = 0
        self.trades_by_confidence = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        logger.info("[EXECUTION BRAIN] Daily trade limits reset")
    
    def evaluate_and_select_best_trade(self, signals: List[Dict]) -> Optional[Dict]:
        """
        Evaluate multiple signals, rank them, and select the best trade.
        
        This is the main entry point for multi-signal trading:
        1. Rank all signals using Signal Ranking Service
        2. Select the best signal
        3. Apply confidence-driven execution rules
        4. Return execution decision
        
        Args:
            signals: List of signal dictionaries with optionstar data
            
        Returns:
            Best signal with execution decision, or None if no valid trade
        """
        try:
            if not signals:
                logger.warning("[EXECUTION BRAIN] No signals to evaluate")
                return None
            
            logger.info(f"[EXECUTION BRAIN] Evaluating {len(signals)} signals...")
            
            # Step 1: Rank signals using Signal Ranking Service
            ranked_signals = self.signal_ranker.rank_signals(signals)
            
            if not ranked_signals:
                logger.warning("[EXECUTION BRAIN] No valid signals after ranking")
                return None
            
            # Step 2: Select best trade
            best_signal = self.signal_ranker.select_best_trade(signals)
            
            if not best_signal:
                logger.info("[EXECUTION BRAIN] No signal meets minimum score threshold")
                # Log all rejected signals
                self.signal_ranker.log_ranking_decision(ranked_signals, None)
                return None
            
            # Step 3: Apply confidence-driven execution
            optionstar = best_signal.get("optionstar", {})
            confidence = optionstar.get("confidence", "LOW")
            
            logger.info(f"[EXECUTION BRAIN] Best signal: {best_signal.get('symbol')} (Score: {best_signal.get('score')}, Confidence: {confidence})")
            
            # Step 4: Evaluate trade with confidence
            decision = self.evaluate_trade_with_confidence(best_signal, optionstar)
            
            # Step 5: Log ranking decision
            if decision["action"] == "EXECUTE":
                self.signal_ranker.log_ranking_decision(ranked_signals, best_signal)
            else:
                self.signal_ranker.log_ranking_decision(ranked_signals, None)
            
            # Return best signal with decision
            best_signal["execution_decision"] = decision
            return best_signal
            
        except Exception as e:
            logger.error(f"[EXECUTION BRAIN] Error in evaluate_and_select_best_trade: {e}")
            return None
    
    def should_execute(self, symbol: str, trade_signal: Dict, market_analysis: Dict, institutional_walls: Dict) -> Dict:
        """
        Legacy method for backward compatibility.
        Wraps evaluate_execution with the old interface.
        
        Args:
            symbol: Trading symbol
            trade_signal: Trade signal dictionary
            market_analysis: Market analysis data
            institutional_walls: Institutional walls data
            
        Returns:
            Execution decision dictionary
        """
        # Extract spot price with fallback
        spot = trade_signal.get('spot_price', 0)
        if spot == 0:
            spot = market_analysis.get('market_analysis', {}).get('spot', 0)
        
        # Extract VWAP with fallback
        vwap = trade_signal.get('vwap', 0)
        if vwap == 0:
            vwap = market_analysis.get('market_analysis', {}).get('vwap', spot)  # Fallback to spot if VWAP not available
        
        # Build signal package for evaluate_execution
        signal_package = {
            "bias": {
                "pcr_bias": market_analysis.get('market_analysis', {}).get('bias', 'NEUTRAL')
            },
            "breakout": {
                "breakout": trade_signal.get('direction', 'NONE'),
                "strength": market_analysis.get('market_analysis', {}).get('market_strength', 1)
            },
            "oi_signal": {
                "oi_signal": institutional_walls.get('trend_bias', 'NEUTRAL')
            },
            "levels": {
                "support": institutional_walls.get('support', {}).get('strike', 0),
                "resistance": institutional_walls.get('resistance', {}).get('strike', 0)
            },
            "spot": spot,
            "vwap": vwap,
            "expiry": trade_signal.get('expiry', '')
        }
        
        return self.evaluate_execution(signal_package)
    
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
                "lot_sizing",
                "confidence_driven_execution",
                "dynamic_position_sizing",
                "adaptive_stop_loss",
                "trade_limit_control",
                "multi_signal_ranking",  # NEW
                "signal_selection"  # NEW
            ],
            "confidence_settings": {
                "high_trades_limit": self.max_trades_high,
                "medium_trades_limit": self.max_trades_medium,
                "low_trades_limit": self.max_trades_low,
                "high_lot_multiplier": 1.0,
                "medium_lot_multiplier": 0.6,
                "low_lot_multiplier": 0.3
            },
            "ranking_settings": {
                "min_score_threshold": self.signal_ranker.min_score_threshold,
                "scoring_weights": self.signal_ranker.weights
            }
        }

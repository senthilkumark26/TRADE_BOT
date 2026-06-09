"""
Signal Ranking Service - Multi-signal ranking and selection
Intelligent selection of best trade opportunities from multiple signals
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
import csv
import os

logger = logging.getLogger(__name__)


class SignalRankingService:
    """
    Signal Ranking Service - Multi-signal ranking and selection.
    
    Provides:
    - Signal scoring based on multiple factors
    - Ranking of multiple signals
    - Selection of best trade opportunity
    - CSV tracking of ranking decisions
    - Safety rules for confidence filtering
    """
    
    def __init__(self, csv_path: str = "signal_ranking_log.csv"):
        """
        Initialize Signal Ranking Service.
        
        Args:
            csv_path: Path to CSV log file for tracking ranking decisions
        """
        self.csv_path = csv_path
        self.csv_initialized = False
        
        # Scoring weights (configurable)
        self.weights = {
            "confidence": 0.4,
            "breakout": 0.25,
            "oi_strength": 0.2,
            "level_quality": 0.15
        }
        
        # Minimum score threshold for execution
        self.min_score_threshold = 0.55
        
        # Confidence penalty for LOW confidence
        self.low_confidence_penalty = 0.5
        
        logger.info("Signal Ranking Service initialized")
        logger.info(f"Scoring weights: {self.weights}")
        logger.info(f"Minimum score threshold: {self.min_score_threshold}")
    
    def get_confidence_score(self, confidence: str) -> float:
        """
        Get confidence score from OptionStar confidence level.
        
        Args:
            confidence: Confidence level ("HIGH", "MEDIUM", "LOW")
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        return {
            "HIGH": 1.0,
            "MEDIUM": 0.6,
            "LOW": 0.2
        }.get(confidence, 0.0)
    
    def get_breakout_score(self, signal: Dict) -> float:
        """
        Get breakout strength score from signal.
        
        Args:
            signal: Signal data dictionary
            
        Returns:
            Breakout score (0.0 to 1.0)
        """
        breakout_type = signal.get("breakout_type", "WEAK")
        
        if breakout_type == "STRONG":
            return 1.0
        elif breakout_type == "WEAK":
            return 0.5
        else:
            return 0.2
    
    def get_oi_strength(self, oi_gap: float) -> float:
        """
        Get OI strength score from OI gap percentage.
        
        Args:
            oi_gap: OI gap percentage (0.0 to 1.0)
            
        Returns:
            OI strength score (0.0 to 1.0)
        """
        if oi_gap > 0.3:
            return 1.0
        elif oi_gap > 0.15:
            return 0.6
        else:
            return 0.3
    
    def get_level_quality(self, price: float, support: float, resistance: float) -> float:
        """
        Get level quality score based on price proximity to support/resistance.
        
        Args:
            price: Current price
            support: Support level
            resistance: Resistance level
            
        Returns:
            Level quality score (0.0 to 1.0)
        """
        distance_to_res = abs(resistance - price)
        distance_to_sup = abs(price - support)
        
        # Too close to resistance (bad for longs)
        if distance_to_res < 50:
            return 0.2
        
        # Close to support (good for longs)
        if distance_to_sup < 50:
            return 0.8
        
        # Mid-range (neutral)
        return 1.0
    
    def compute_signal_score(self, signal: Dict, optionstar: Dict) -> float:
        """
        Compute final score for a signal based on multiple factors.
        
        Args:
            signal: Signal data dictionary
            optionstar: OptionStar analysis data
            
        Returns:
            Final score (0.0 to 1.0)
        """
        try:
            # Component scores
            confidence_score = self.get_confidence_score(optionstar.get("confidence", "LOW"))
            breakout_score = self.get_breakout_score(signal)
            oi_strength = self.get_oi_strength(optionstar.get("oi_gap", 0.0))
            
            level_quality = self.get_level_quality(
                signal.get("price", 0),
                optionstar.get("support", 0),
                optionstar.get("resistance", 0)
            )
            
            # Apply confidence penalty for LOW confidence
            if optionstar.get("confidence") == "LOW":
                confidence_score *= self.low_confidence_penalty
            
            # Weighted final score
            final_score = (
                self.weights["confidence"] * confidence_score +
                self.weights["breakout"] * breakout_score +
                self.weights["oi_strength"] * oi_strength +
                self.weights["level_quality"] * level_quality
            )
            
            return round(final_score, 3)
            
        except Exception as e:
            logger.error(f"Error computing signal score: {e}")
            return 0.0
    
    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """
        Rank multiple signals by quality score.
        
        Args:
            signals: List of signal dictionaries with optionstar data
            
        Returns:
            Ranked list of signals (descending by score)
        """
        try:
            scored_signals = []
            
            for signal in signals:
                optionstar = signal.get("optionstar", {})
                
                if not optionstar:
                    logger.warning(f"Signal missing optionstar data: {signal.get('symbol')}")
                    continue
                
                score = self.compute_signal_score(signal, optionstar)
                signal["score"] = score
                signal["rank"] = None  # Will be assigned after sorting
                
                scored_signals.append(signal)
            
            # Sort descending by score
            scored_signals.sort(key=lambda x: x["score"], reverse=True)
            
            # Assign ranks
            for rank, signal in enumerate(scored_signals, 1):
                signal["rank"] = rank
            
            logger.info(f"Ranked {len(scored_signals)} signals")
            
            return scored_signals
            
        except Exception as e:
            logger.error(f"Error ranking signals: {e}")
            return []
    
    def select_best_trade(self, signals: List[Dict]) -> Optional[Dict]:
        """
        Select the best trade from multiple signals.
        
        Args:
            signals: List of signal dictionaries
            
        Returns:
            Best signal or None if no signal meets threshold
        """
        try:
            if not signals:
                logger.warning("No signals to rank")
                return None
            
            ranked = self.rank_signals(signals)
            
            if not ranked:
                logger.warning("No valid signals after ranking")
                return None
            
            best = ranked[0]
            
            # Check minimum threshold
            if best["score"] < self.min_score_threshold:
                logger.info(f"Best signal score {best['score']} below threshold {self.min_score_threshold}")
                return None
            
            logger.info(f"Selected best trade: {best.get('symbol')} (Score: {best['score']}, Rank: 1)")
            
            return best
            
        except Exception as e:
            logger.error(f"Error selecting best trade: {e}")
            return None
    
    def log_ranking_decision(self, ranked_signals: List[Dict], selected: Optional[Dict] = None):
        """
        Log ranking decision to CSV for tracking and analysis.
        
        Args:
            ranked_signals: List of ranked signals
            selected: Selected signal (if any)
        """
        try:
            # Initialize CSV file with headers
            if not self.csv_initialized:
                if not os.path.exists(self.csv_path):
                    with open(self.csv_path, 'w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            "timestamp",
                            "symbol",
                            "score",
                            "rank",
                            "confidence",
                            "breakout_type",
                            "oi_gap",
                            "support",
                            "resistance",
                            "status"
                        ])
                self.csv_initialized = True
            
            # Write ranking decisions
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                timestamp = datetime.now().isoformat()
                
                for signal in ranked_signals:
                    symbol = signal.get("symbol", "UNKNOWN")
                    score = signal.get("score", 0.0)
                    rank = signal.get("rank", 0)
                    confidence = signal.get("optionstar", {}).get("confidence", "UNKNOWN")
                    breakout_type = signal.get("breakout_type", "UNKNOWN")
                    oi_gap = signal.get("optionstar", {}).get("oi_gap", 0.0)
                    support = signal.get("optionstar", {}).get("support", 0.0)
                    resistance = signal.get("optionstar", {}).get("resistance", 0.0)
                    
                    # Determine status
                    if selected and symbol == selected.get("symbol"):
                        status = "EXECUTED"
                    elif score < self.min_score_threshold:
                        status = "LOW_SCORE"
                    else:
                        status = "SKIPPED"
                    
                    writer.writerow([
                        timestamp,
                        symbol,
                        score,
                        rank,
                        confidence,
                        breakout_type,
                        oi_gap,
                        support,
                        resistance,
                        status
                    ])
            
            logger.info(f"Logged {len(ranked_signals)} ranking decisions to {self.csv_path}")
            
        except Exception as e:
            logger.error(f"Error logging ranking decision: {e}")
    
    def get_service_info(self) -> Dict:
        """Get service information."""
        return {
            "service_name": "signal_ranking_service",
            "version": "1.0.0",
            "weights": self.weights,
            "min_score_threshold": self.min_score_threshold,
            "low_confidence_penalty": self.low_confidence_penalty,
            "csv_path": self.csv_path
        }


# Global instance
_signal_ranker = None

def get_signal_ranker(csv_path: str = "signal_ranking_log.csv") -> SignalRankingService:
    """
    Get global signal ranking service instance.
    
    Args:
        csv_path: Path to CSV log file
        
    Returns:
        SignalRankingService instance
    """
    global _signal_ranker
    if _signal_ranker is None:
        _signal_ranker = SignalRankingService(csv_path)
    return _signal_ranker
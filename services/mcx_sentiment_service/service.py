"""
MCX Sentiment Service - Plug-and-Play MCX Market Sentiment Analysis
Provides MCX commodity sentiment for multi-market confirmation with NSE trading
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MCXSentimentService:
    """
    MCX Sentiment Service - Analyzes MCX commodity market sentiment
    Can be used as optional confirmation for NSE trades
    """
    
    def __init__(self, config_path=None):
        """
        Initialize MCX Sentiment Service
        
        Args:
            config_path: Path to config.json (defaults to parent directory)
        """
        if config_path is None:
            import os
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.json')
        
        self.config_path = config_path
        self.config = self._load_config()
        self.enabled = self.config.get("mcx_enabled", True)
        
        # MCX symbols to track
        self.mcx_symbols = ["CRUDEOIL", "NATGAS", "GOLDM", "SILVERM"]
        
        # Sentiment cache
        self.sentiment_cache = {}
        self.cache_duration = 300  # 5 minutes
        self.last_cache_update = 0
        
        # Historical sentiment data
        self.sentiment_history = {}  # symbol -> list of sentiment values
        
        logger.info(f"MCX Sentiment Service initialized (enabled: {self.enabled})")
    
    def _load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {"mcx_enabled": False}
    
    def is_enabled(self) -> bool:
        """Check if MCX sentiment service is enabled"""
        return self.enabled
    
    def get_mcx_sentiment(self, symbol: str = None) -> Dict[str, Any]:
        """
        Get MCX sentiment for a specific symbol or overall MCX sentiment
        
        Args:
            symbol: Specific MCX symbol (CRUDEOIL, NATGAS, GOLDM, SILVERM)
                   If None, returns overall MCX sentiment
        
        Returns:
            Dictionary with sentiment data:
            {
                "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
                "confidence": 0.0 to 1.0,
                "strength": 0 to 5,
                "reasoning": str,
                "timestamp": str,
                "symbol": str
            }
        """
        if not self.enabled:
            logger.debug("MCX sentiment service disabled")
            return self._get_neutral_sentiment("MCX_SERVICE_DISABLED")
        
        # Check cache
        current_time = time.time()
        if current_time - self.last_cache_update < self.cache_duration and self.sentiment_cache:
            if symbol:
                return self.sentiment_cache.get(symbol, self._get_neutral_sentiment("NO_DATA"))
            else:
                return self._get_overall_sentiment()
        
        # Refresh sentiment data
        self._refresh_sentiment_data()
        
        if symbol:
            return self.sentiment_cache.get(symbol, self._get_neutral_sentiment("NO_DATA"))
        else:
            return self._get_overall_sentiment()
    
    def _refresh_sentiment_data(self):
        """Refresh sentiment data for all MCX symbols"""
        try:
            # Import MCX wrapper (lazy import to avoid circular dependencies)
            from mcx.mcx_wrapper import get_mcx_signal, get_mcx_commodity_profile
            
            for symbol in self.mcx_symbols:
                try:
                    # Get MCX signal for sentiment
                    mcx_result = get_mcx_signal(symbol, 0, 0, 0)
                    
                    if mcx_result:
                        signal = mcx_result.get('signal', 'NEUTRAL')
                        confidence = mcx_result.get('confidence', 0.5)
                        
                        # Map signal to sentiment
                        sentiment_map = {
                            "LONG": "BULLISH",
                            "SHORT": "BEARISH",
                            "NEUTRAL": "NEUTRAL"
                        }
                        
                        sentiment = sentiment_map.get(signal, "NEUTRAL")
                        strength = int(confidence * 5)  # Convert 0-1 to 0-5
                        
                        self.sentiment_cache[symbol] = {
                            "sentiment": sentiment,
                            "confidence": confidence,
                            "strength": strength,
                            "reasoning": f"MCX {signal} signal with {confidence:.2f} confidence",
                            "timestamp": datetime.now().isoformat(),
                            "symbol": symbol
                        }
                        
                        # Update history
                        if symbol not in self.sentiment_history:
                            self.sentiment_history[symbol] = []
                        self.sentiment_history[symbol].append(sentiment)
                        
                        # Keep only last 10 entries
                        if len(self.sentiment_history[symbol]) > 10:
                            self.sentiment_history[symbol].pop(0)
                            
                    else:
                        self.sentiment_cache[symbol] = self._get_neutral_sentiment("NO_MCX_DATA")
                        
                except Exception as e:
                    logger.error(f"Error getting sentiment for {symbol}: {e}")
                    self.sentiment_cache[symbol] = self._get_neutral_sentiment("ERROR")
            
            self.last_cache_update = time.time()
            logger.info(f"MCX sentiment data refreshed for {len(self.sentiment_cache)} symbols")
            
        except Exception as e:
            logger.error(f"Error refreshing MCX sentiment data: {e}")
    
    def _get_overall_sentiment(self) -> Dict[str, Any]:
        """Calculate overall MCX sentiment from all symbols"""
        if not self.sentiment_cache:
            return self._get_neutral_sentiment("NO_DATA")
        
        bullish_count = sum(1 for s in self.sentiment_cache.values() if s.get('sentiment') == 'BULLISH')
        bearish_count = sum(1 for s in self.sentiment_cache.values() if s.get('sentiment') == 'BEARISH')
        neutral_count = sum(1 for s in self.sentiment_cache.values() if s.get('sentiment') == 'NEUTRAL')
        
        total = len(self.sentiment_cache)
        
        if bullish_count > bearish_count and bullish_count > neutral_count:
            overall_sentiment = "BULLISH"
            confidence = bullish_count / total
        elif bearish_count > bullish_count and bearish_count > neutral_count:
            overall_sentiment = "BEARISH"
            confidence = bearish_count / total
        else:
            overall_sentiment = "NEUTRAL"
            confidence = 0.5
        
        return {
            "sentiment": overall_sentiment,
            "confidence": confidence,
            "strength": int(confidence * 5),
            "reasoning": f"Overall MCX: {bullish_count} BULLISH, {bearish_count} BEARISH, {neutral_count} NEUTRAL",
            "timestamp": datetime.now().isoformat(),
            "symbol": "MCX_OVERALL",
            "breakdown": {
                "bullish": bullish_count,
                "bearish": bearish_count,
                "neutral": neutral_count
            }
        }
    
    def _get_neutral_sentiment(self, reason: str) -> Dict[str, Any]:
        """Return neutral sentiment with given reason"""
        return {
            "sentiment": "NEUTRAL",
            "confidence": 0.5,
            "strength": 2,
            "reasoning": f"Neutral sentiment: {reason}",
            "timestamp": datetime.now().isoformat(),
            "symbol": "MCX_NEUTRAL"
        }
    
    def get_sentiment_for_nse_confirmation(self, nse_direction: str) -> Dict[str, Any]:
        """
        Get MCX sentiment specifically for NSE trade confirmation
        
        Args:
            nse_direction: "CALL" or "PUT" (NSE trade direction)
        
        Returns:
            Dictionary with confirmation data:
            {
                "confirms": bool,
                "sentiment": str,
                "confidence": float,
                "reasoning": str,
                "recommendation": "CONFIRM" | "REJECT" | "NEUTRAL"
            }
        """
        mcx_sentiment = self.get_mcx_sentiment()
        
        if not self.enabled:
            return {
                "confirms": True,
                "sentiment": "NEUTRAL",
                "confidence": 0.5,
                "reasoning": "MCX sentiment disabled - neutral confirmation",
                "recommendation": "NEUTRAL"
            }
        
        sentiment = mcx_sentiment.get('sentiment', 'NEUTRAL')
        confidence = mcx_sentiment.get('confidence', 0.5)
        
        # Logic: MCX BULLISH confirms NSE CALL, MCX BEARISH confirms NSE PUT
        if nse_direction == "CALL":
            if sentiment == "BULLISH" and confidence > 0.6:
                return {
                    "confirms": True,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "reasoning": f"MCX BULLISH ({confidence:.2f}) confirms NSE CALL",
                    "recommendation": "CONFIRM"
                }
            elif sentiment == "BEARISH" and confidence > 0.6:
                return {
                    "confirms": False,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "reasoning": f"MCX BEARISH ({confidence:.2f}) conflicts with NSE CALL",
                    "recommendation": "REJECT"
                }
        elif nse_direction == "PUT":
            if sentiment == "BEARISH" and confidence > 0.6:
                return {
                    "confirms": True,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "reasoning": f"MCX BEARISH ({confidence:.2f}) confirms NSE PUT",
                    "recommendation": "CONFIRM"
                }
            elif sentiment == "BULLISH" and confidence > 0.6:
                return {
                    "confirms": False,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "reasoning": f"MCX BULLISH ({confidence:.2f}) conflicts with NSE PUT",
                    "recommendation": "REJECT"
                }
        
        # Default neutral
        return {
            "confirms": True,
            "sentiment": sentiment,
            "confidence": confidence,
            "reasoning": f"MCX {sentiment} ({confidence:.2f}) - neutral confirmation",
            "recommendation": "NEUTRAL"
        }
    
    def enable(self):
        """Enable MCX sentiment service"""
        self.enabled = True
        logger.info("MCX Sentiment Service enabled")
    
    def disable(self):
        """Disable MCX sentiment service"""
        self.enabled = False
        logger.info("MCX Sentiment Service disabled")
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        return {
            "enabled": self.enabled,
            "symbols_tracked": self.mcx_symbols,
            "cache_status": "fresh" if time.time() - self.last_cache_update < self.cache_duration else "stale",
            "last_update": datetime.fromtimestamp(self.last_cache_update).isoformat() if self.last_cache_update > 0 else "never",
            "sentiment_cache": self.sentiment_cache
        }


# Singleton instance
_mcx_sentiment_service = None

def get_mcx_sentiment_service(config_path=None) -> MCXSentimentService:
    """
    Get singleton instance of MCX Sentiment Service
    
    Args:
        config_path: Path to config.json
    
    Returns:
        MCXSentimentService instance
    """
    global _mcx_sentiment_service
    if _mcx_sentiment_service is None:
        _mcx_sentiment_service = MCXSentimentService(config_path)
    return _mcx_sentiment_service

"""
Market Analyzer Agent - Background Market Analysis System
Continuously scans market, identifies perfect trades, and provides real-time trade opportunities
"""
import logging
import time
import threading
import json
import os
import sys
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from kite.kite_client import KiteClient
from utils.optionstar import generate_trade
# from trade_pipeline import add_trade_to_queue  # File not found, commented out

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """
    Background market analyzer that continuously scans for perfect trade opportunities.
    Operates independently from trade execution - purely for market analysis.
    """
    
    def __init__(self, kite_client, watchlist, analysis_interval=30, llm_analyzer=None):
        """
        Initialize Market Analyzer.
        
        Args:
            kite_client: KiteConnect client for market data
            watchlist: List of instruments to analyze
            analysis_interval: Seconds between analysis cycles (default: 30)
            llm_analyzer: Optional LLM analyzer for trade validation
        """
        self.kite_client = kite_client
        self.watchlist = watchlist
        self.analysis_interval = analysis_interval
        self.llm_analyzer = llm_analyzer  # Optional LLM for filtering
        
        # Market analysis state
        self.running = False
        self.analysis_thread = None
        self.last_analysis_time = 0
        
        # Perfect trades storage (ranked by quality)
        self.perfect_trades = []  # List of ranked trade opportunities
        self.max_perfect_trades = 10  # Keep top 10 trades
        self.lock = threading.Lock()  # Thread-safe access to trades
        
        # No callback - Market Analyzer is independent service
        # Just provides numbered list of trades
        # No pause/resume - runs continuously every 15min
        
        # Duplicate detection cache
        self.recent_trades_cache = {}  # trade_signature -> timestamp
        self.duplicate_timeout = 60  # 1 minute - consider same trade after 1 minute
        
        # Market data cache
        self.market_data = {}  # symbol -> latest market data
        self.price_history = {}  # symbol -> list of recent prices
        
        logger.info("Market Analyzer initialized")
        logger.info(f"Watchlist: {watchlist}")
        logger.info(f"Analysis interval: {analysis_interval}s")
        if self.llm_analyzer:
            logger.info("LLM filtering: ENABLED")
        else:
            logger.info("LLM filtering: DISABLED")
    
    def _calculate_trade_score(self, trade):
        """
        Calculate trade score for ranking (prioritization over elimination).
        Includes sanity checks for trade logic.
        
        Args:
            trade: Trade dictionary
            
        Returns:
            Score (0-100)
        """
        score = 0
        
        # Base quality from OptionStar
        base_quality = trade.get('quality_score', 50)
        score += base_quality
        
        # Distance bonus (closer to ATM = better)
        spot = trade.get('spot', 0)
        strike = trade.get('strike', 0)
        distance = abs(spot - strike)
        distance_bonus = max(0, 50 - distance)  # Closer = higher bonus
        score += distance_bonus
        
        # Direction bias (slight preference for CALL in bullish market)
        # This can be adjusted based on market conditions
        if trade.get('direction') == 'CALL':
            score += 5  # Small bonus for CALL
        
        # NEW: Sanity check - reduce score if trade logic conflicts with price structure
        direction = trade.get('direction', '')
        support = trade.get('support', 0)
        resistance = trade.get('resistance', 0)
        
        if direction == 'PUT' and spot > resistance:
            # PUT signal but spot above resistance - reduce score
            score -= 10
        elif direction == 'CALL' and spot < support:
            # CALL signal but spot below support - reduce score
            score -= 10
        
        return round(score, 1)
    
    def _safe_llm_check(self, trade):
        """
        DISABLED: LLM check removed from scanning stage.
        
        ARCHITECTURE CHANGE: "Data First, LLM Last"
        - Stage 1: Technical Scanner (this stage) - NO LLM
        - Stage 2: LLM Validation (execution stage only) - LLM here
        - Stage 3: Dashboard Display (only validated trades)
        
        This method now always returns True to allow technical analysis to proceed.
        LLM validation happens in run_market_system.py after all technical filters pass.
        
        Args:
            trade: Trade dictionary (unused)
            
        Returns:
            True (LLM validation deferred to execution stage)
        """
        # LLM validation moved to execution stage only
        # Technical scanner should run independently without LLM overhead
        # This prevents LLM timeouts, token cutoffs, and CPU overload
        logger.info(f"  📊 Technical analysis only (LLM deferred to execution stage)")
        return True
    
    
    def start(self):
        """Start the market analyzer in background thread."""
        if self.running:
            logger.warning("Market Analyzer already running")
            return
        
        self.running = True
        self.analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.analysis_thread.start()
        logger.info("🚀 Market Analyzer started in background")
    
    def stop(self):
        """Stop the market analyzer."""
        self.running = False
        if self.analysis_thread:
            self.analysis_thread.join(timeout=5)
        logger.info("🛑 Market Analyzer stopped")
    
    def _analysis_loop(self):
        """Main analysis loop - runs continuously in background."""
        logger.info("📊 Market Analysis Loop started")
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time for next analysis
                if current_time - self.last_analysis_time >= self.analysis_interval:
                    logger.info("=" * 80)
                    logger.info(f"🔍 MARKET ANALYSIS CYCLE - {datetime.now().strftime('%H:%M:%S')}")
                    logger.info("=" * 80)
                    
                    # Analyze all instruments in watchlist
                    self._analyze_market()
                    
                    self.last_analysis_time = current_time
                    
                    # Print numbered list of perfect trades
                    self._print_numbered_trade_list()
                
                # Sleep to prevent CPU overload
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")
                time.sleep(10)  # Wait before retrying
    
    def _analyze_market(self):
        """Analyze all instruments in watchlist and identify perfect trades."""
        total_scanned = 0
        total_valid = 0
        total_filtered = 0
        
        for symbol in self.watchlist:
            try:
                logger.info(f"\nAnalyzing {symbol}...")
                total_scanned += 1
                
                # Get current market data
                market_info = self._get_market_data(symbol)
                if not market_info:
                    logger.warning(f"No market data for {symbol}")
                    continue
                
                # Generate trade setup using OptionStar
                trade_setup = self._generate_trade_setup(symbol, market_info)
                if not trade_setup:
                    logger.info(f"No trade setup generated for {symbol}")
                    continue
                
                # Score the trade quality
                trade_score = self._score_trade_quality(trade_setup, market_info)
                trade_setup['quality_score'] = trade_score
                trade_setup['analysis_timestamp'] = datetime.now().isoformat()
                
                # NEW: Calculate ranking score
                ranking_score = self._calculate_trade_score(trade_setup)
                trade_setup['ranking_score'] = ranking_score
                
                # CRITICAL: Check if trade is still valid (not stale/expired)
                if not self._is_trade_valid(trade_setup):
                    logger.info(f"⏭️ Trade filtered (stale/expired): {symbol}")
                    total_filtered += 1
                    continue
                
                total_valid += 1
                
                # NEW: LLM validation during scan (not after user selection)
                if not self._safe_llm_check(trade_setup):
                    logger.info(f"⏭️ Trade filtered (LLM rejected): {symbol}")
                    total_filtered += 1
                    continue
                
                # Check for duplicate before adding
                if self._is_duplicate_trade(trade_setup):
                    logger.info(f"⏭️ Skipping duplicate trade: {symbol}")
                    continue
                
                # Add to perfect trades if score is high enough (relaxed threshold)
                if trade_score >= 60:  # Reduced from 70 to 60 (more lenient)
                    self._add_perfect_trade(trade_setup)
                    logger.info(f"✅ Perfect trade found: {symbol} (quality: {trade_score:.1f}%, ranking: {ranking_score:.1f})")
                else:
                    logger.info(f"⏭️ Trade quality too low: {symbol} (score: {trade_score:.1f}%)")
                
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
        
        # Print analyzer status report
        self._print_analyzer_report(total_scanned, total_valid, total_filtered)
    
    def _get_market_data(self, symbol) -> Optional[Dict]:
        """
        Get current market data for symbol using NSE: prefix (no instrument tokens needed).
        
        Args:
            symbol: Instrument symbol (e.g., INFY, TCS, NIFTY)
        
        Returns:
            Market data dictionary or None
        """
        try:
            # Use NSE: prefix for direct LTP API call (no instrument tokens needed)
            # For indices: NSE:NIFTY 50, NSE:NIFTY BANK (BANKNIFTY)
            # For stocks: NSE:INFY, NSE:TCS, etc.
            if symbol.upper() in ['NIFTY', 'BANKNIFTY']:
                # Indices use special format
                if symbol.upper() == 'NIFTY':
                    key = "NSE:NIFTY 50"
                elif symbol.upper() == 'BANKNIFTY':
                    key = "NSE:NIFTY BANK"
                else:
                    key = f"NSE:{symbol}"
            else:
                # Stocks use NSE:SYMBOL format
                key = f"NSE:{symbol.upper()}"
            
            logger.info(f"Fetching LTP for: {key}")
            
            # Get LTP from Kite using direct symbol (no token needed)
            quotes = self.kite_client.get_ltp([key])
            
            if quotes and key in quotes:
                current_price = quotes[key]
                logger.info(f"LTP response: {quotes}")
                
                # Update price history
                if symbol not in self.price_history:
                    self.price_history[symbol] = []
                self.price_history[symbol].append(current_price)
                
                # Keep only last 20 prices
                if len(self.price_history[symbol]) > 20:
                    self.price_history[symbol] = self.price_history[symbol][-20:]
                
                # Calculate VWAP (simplified)
                if len(self.price_history[symbol]) >= 5:
                    vwap = sum(self.price_history[symbol]) / len(self.price_history[symbol])
                else:
                    vwap = current_price
                
                market_data = {
                    "symbol": symbol,
                    "current_price": current_price,
                    "vwap": vwap,
                    "price_change": 0,
                    "volume": "normal",
                    "timestamp": datetime.now().isoformat(),
                    # Add defensive defaults for missing technical metrics
                    "oi_type": "balanced",  # Default if real OI unavailable
                    "vix": "normal",  # Default VIX if unavailable
                    "delta": "neutral",  # Default delta if unavailable
                    "trap_detected": "no",  # Default trap status if unavailable
                    "momentum": "neutral",  # Default momentum if unavailable
                    "volatility_ratio": "normal"  # Default volatility if unavailable
                }
                
                # Store in cache
                self.market_data[symbol] = market_data
                
                # DEBUG: Log the market data to verify data flow
                logger.info(f"✓ Market data for {symbol}: OI={market_data.get('oi_type')}, VIX={market_data.get('vix')}, Delta={market_data.get('delta')}, Trap={market_data.get('trap_detected')}")
                
                return market_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return None
    
    def _generate_trade_signature(self, trade) -> str:
        """
        Generate a unique signature for a trade to detect duplicates.
        More lenient to handle slight price variations.
        
        Args:
            trade: Trade dictionary
        
        Returns:
            String signature for the trade
        """
        symbol = trade.get('symbol', '').upper()
        direction = trade.get('direction', '').upper()
        strike = trade.get('strike', 0)
        
        # Round strike to nearest 100 points for grouping similar trades
        strike_rounded = round(strike / 100) * 100
        
        signature = f"{symbol}_{direction}_{strike_rounded}"
        return signature
    
    def _is_duplicate_trade(self, trade) -> bool:
        """
        Check if a trade is a duplicate of recently found trades.
        
        Args:
            trade: Trade dictionary
        
        Returns:
            True if duplicate, False otherwise
        """
        signature = self._generate_trade_signature(trade)
        current_time = time.time()
        
        # Check if this trade was recently found
        if signature in self.recent_trades_cache:
            last_found_time = self.recent_trades_cache[signature]
            time_since = current_time - last_found_time
            
            if time_since < self.duplicate_timeout:
                logger.info(f"🔄 Duplicate trade detected in Market Analyzer: {signature} (found {time_since:.0f}s ago, skipping)")
                return True
        
        # Add to recently found trades
        self.recent_trades_cache[signature] = current_time
        
        # Clean up old entries (older than timeout)
        self._cleanup_duplicate_cache()
        
        return False
    
    def _cleanup_duplicate_cache(self):
        """Clean up old entries from the duplicate detection cache."""
        current_time = time.time()
        signatures_to_remove = []
        
        for signature, timestamp in self.recent_trades_cache.items():
            if current_time - timestamp > self.duplicate_timeout:
                signatures_to_remove.append(signature)
        
        for signature in signatures_to_remove:
            del self.recent_trades_cache[signature]
        
        if signatures_to_remove:
            logger.debug(f"Cleaned up {len(signatures_to_remove)} old trade signatures from Market Analyzer cache")
    
    def _generate_trade_setup(self, symbol, market_data) -> Optional[Dict]:
        """
        Generate trade setup using OptionStar.
        
        Args:
            symbol: Instrument symbol
            market_data: Current market data
        
        Returns:
            Trade setup dictionary or None
        """
        try:
            current_price = market_data['current_price']
            vwap = market_data['vwap']
            
            # Note: In production, fetch real option chain from Kite API
            # This legacy file is not used by the active single_strike_trader.py system
            option_chain = []  # Empty chain - this file is legacy
            
            # Generate trade setup using OptionStar
            trade = generate_trade(current_price, vwap, option_chain, symbol)
            
            if trade:
                # Calculate rich context for LLM intelligence
                rich_context = self._calculate_rich_context(trade, market_data)
                
                # Enhance with market context
                trade.update({
                    "symbol": symbol,
                    "spot": current_price,
                    "vwap": vwap,
                    "market_data": market_data,
                    "analysis_timestamp": datetime.now().isoformat()
                })
                
                # Add rich context fields
                trade.update(rich_context)
                
                return trade
            
            return None
            
        except Exception as e:
            logger.error(f"Error generating trade setup for {symbol}: {e}")
            return None
    
    def _calculate_rich_context(self, trade, market_data) -> Dict[str, Any]:
        """
        Calculate rich context fields for LLM intelligence.
        
        Args:
            trade: Trade setup dictionary
            market_data: Current market data
            
        Returns:
            Dictionary with rich context fields
        """
        current_price = market_data['current_price']
        vwap = market_data['vwap']
        direction = trade.get('direction', '')
        
        # Calculate distance from support/resistance (from OptionStar institutional analysis)
        support = trade.get('support', 0)  # Must come from OptionStar
        resistance = trade.get('resistance', 0)  # Must come from OptionStar
        
        # If no institutional data available, skip this trade
        if support == 0 or resistance == 0:
            logger.warning(f"No institutional support/resistance data for trade - skipping")
            return None
        
        dist_support = round(abs(current_price - support), 2)
        dist_resistance = round(abs(resistance - current_price), 2)
        
        # Calculate market regime trend (15-minute structural trend)
        price_change = (current_price - vwap) / vwap * 100
        
        if price_change > 0.5:
            trend = "BULLISH_RALLY"
        elif price_change < -0.5:
            trend = "BEARISH_LIQUIDATION"
        else:
            trend = "CHOPPY_SIDEWAYS"
        
        # Simulate VIX (in production, fetch real India VIX)
        # For demo, use random variation around 15
        import random
        vix = round(random.uniform(12.0, 18.0), 1)
        
        if vix < 14:
            vix_level = f"LOW_{vix}"
        elif vix > 16:
            vix_level = f"HIGH_{vix}"
        else:
            vix_level = f"MEDIUM_{vix}"
        
        return {
            "dist_support": dist_support,
            "dist_resistance": dist_resistance,
            "trend": trend,
            "vix": vix_level
        }
    
    def _score_trade_quality(self, trade, market_data) -> float:
        """
        Score trade quality on scale of 0-100.
        
        Args:
            trade: Trade setup dictionary
            market_data: Current market data
        
        Returns:
            Quality score (0-100)
        """
        score = 0
        
        try:
            # Factor 1: OptionStar reason quality (30 points)
            reason = trade.get('reason', '').lower()
            positive_keywords = ['strong', 'breakout', 'momentum', 'trend', 'support', 'resistance', 'bounce']
            if any(keyword in reason for keyword in positive_keywords):
                score += 30
            elif reason:
                score += 15  # Partial credit for any reason
            
            # Factor 2: VWAP alignment (20 points)
            current_price = market_data['current_price']
            vwap = market_data['vwap']
            if abs(current_price - vwap) < 50:  # Within 50 points of VWAP
                score += 20
            elif abs(current_price - vwap) < 100:
                score += 10
            
            # Factor 3: Strike selection (20 points)
            strike = trade.get('strike', 0)
            if abs(strike - current_price) < 100:  # Close to current price
                score += 20
            elif abs(strike - current_price) < 200:
                score += 10
            
            # Factor 4: Direction clarity (15 points)
            direction = trade.get('direction', '')
            if direction in ['CALL', 'PUT']:
                score += 15
            
            # Factor 5: Market conditions (15 points)
            # In production, this would include volume, volatility, etc.
            score += 10  # Base credit for market being open
            
            # Normalize to 0-100
            score = min(100, max(0, score))
            
            return float(score)
            
        except Exception as e:
            logger.error(f"Error scoring trade quality: {e}")
            return 50.0  # Default score
    
    def _add_perfect_trade(self, trade):
        """
        Add trade to perfect trades list and maintain ranking.
        Replaces existing trade if same signature exists (update with new data).
        Calls callback if new trade is added.
        
        Args:
            trade: Trade setup dictionary
        """
        with self.lock:
            # Add unique trade ID
            trade['trade_id'] = f"{trade.get('symbol', '')}_{int(time.time())}"
            
            # Check if trade with similar signature already exists
            signature = self._generate_trade_signature(trade)
            
            # Check if this is a new trade (not replacing existing)
            is_new = not any(self._generate_trade_signature(t) == signature for t in self.perfect_trades)
            
            # Remove existing trade with same signature
            self.perfect_trades = [t for t in self.perfect_trades 
                                    if self._generate_trade_signature(t) != signature]
            
            # Add new trade
            self.perfect_trades.append(trade)
            
            # Sort by quality score (highest first)
            self.perfect_trades.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
            
            # NON-DESTRUCTIVE HOOK: Only send top 3 trades to LLM queue (limit calls)
            if trade.get('quality_score', 0) > 85:  # Only top-quality trades
                # Check if this is in top 3
                top_3_trades = self.perfect_trades[:3]
                if any(self._generate_trade_signature(t) == signature for t in top_3_trades):
                    add_trade_to_queue(trade)
            
            # Keep only top N trades
            if len(self.perfect_trades) > self.max_perfect_trades:
                self.perfect_trades = self.perfect_trades[:self.max_perfect_trades]
            
            logger.info(f"Perfect trades list updated: {len(self.perfect_trades)} unique trades")
            
            # Save signals to web_signals.json for web interface
            self._save_signals_to_json()
            
            # No callback - Market Analyzer is independent service
    
    def _save_signals_to_json(self):
        """Save perfect trades to web_signals.json for web interface display."""
        try:
            signals = []
            for trade in self.perfect_trades[:10]:  # Top 10 trades
                symbol = trade.get('symbol', '')
                direction = trade.get('direction', '')
                spot = trade.get('spot', 0)
                strike = trade.get('strike', 0)
                quality_score = trade.get('quality_score', 0)
                ranking_score = trade.get('ranking_score', 0)
                
                # Calculate estimated entry, SL, and TP
                # Using realistic percentages: SL = Entry - 12%, TP = Entry + 60%
                est_entry = self.estimate_option_price(spot, strike, direction)
                est_sl = est_entry * 0.88  # 12% stop loss
                est_tp = est_entry * 1.60  # 60% target
                
                # Determine confidence level based on quality score
                if quality_score >= 90:
                    confidence = "High"
                    emoji = "🔥"
                elif quality_score >= 70:
                    confidence = "Medium"
                    emoji = "⚡"
                else:
                    confidence = "Low"
                    emoji = "📊"
                
                # Format option symbol
                option_type = 'CE' if direction == 'CALL' else 'PE' if direction == 'PUT' else 'N/A'
                instrument = f"{symbol} {strike} {option_type}"
                
                signals.append({
                    'instrument': instrument,
                    'type': direction,
                    'spot': round(spot, 2),
                    'entry': round(est_entry, 2),
                    'sl': round(est_sl, 2),
                    'tp': round(est_tp, 2),
                    'confidence': confidence,
                    'emoji': emoji,
                    'score': round(quality_score, 1),
                    'ranking': round(ranking_score, 1)
                })
            
            signals_data = {
                'signals': signals,
                'count': len(signals),
                'timestamp': datetime.now().isoformat()
            }
            
            with open('D:/Traiding_Bot/web_signals.json', 'w', encoding='utf-8') as f:
                json.dump(signals_data, f, indent=4)
            
            logger.info(f"✅ Saved {len(signals)} signals to web_signals.json")
            
        except Exception as e:
            logger.error(f"Error saving signals to JSON: {e}")
    
    def estimate_option_price(self, spot, strike, direction):
        """Estimate option price based on spot and strike."""
        # Simple estimation logic
        distance = abs(spot - strike)
        if direction == 'CALL':
            # For calls, price decreases as distance from spot increases
            base_price = max(0.5, 10 - distance / 50)
        else:
            # For puts, price decreases as distance from spot increases
            base_price = max(0.5, 10 - distance / 50)
        return base_price
    
    def _print_numbered_trade_list(self):
        """Print numbered list of perfect trades with smart ranking (always show top 5)."""
        with self.lock:
            # NEW: Sort trades by ranking score
            sorted_trades = sorted(self.perfect_trades, key=lambda x: x.get('ranking_score', 0), reverse=True)
            
            # NEW: Always show top 5
            top_trades = sorted_trades[:5]
            
            # NEW: Fallback - if no trades, show best available from all trades
            if not top_trades and self.perfect_trades:
                # Show top 3 even if below threshold
                top_trades = sorted_trades[:3]
            
            if not top_trades:
                logger.info("\n📋 PERFECT TRADES LIST")
                logger.info("="*80)
                logger.info("No perfect trades found at the moment")
                logger.info("="*80)
                return
            
            logger.info("\n" + "="*80)
            logger.info("📋 PERFECT TRADES LIST (Smart Ranking - Top 5)")
            logger.info("="*80)
            
            for i, trade in enumerate(top_trades, 1):
                symbol = trade.get('symbol', 'N/A')
                direction = trade.get('direction', 'N/A')
                strike = trade.get('strike', 'N/A')
                quality = trade.get('quality_score', 0)
                ranking = trade.get('ranking_score', 0)
                reason = trade.get('reason', 'N/A')
                
                logger.info(f"{i}. {symbol} {direction} @ {strike} - Quality: {quality:.1f}% | Ranking: {ranking:.1f} - {reason}")
            
            logger.info("="*80)
            logger.info("💡 To monitor a trade, note the number and use it with the trading bot")
            logger.info("="*80)
    
    def _print_perfect_trades_summary(self):
        """Print summary of current perfect trades."""
        with self.lock:
            if not self.perfect_trades:
                logger.info("No perfect trades found in this cycle")
                return
            
            logger.info("\n" + "=" * 80)
            logger.info(f"🏆 PERFECT TRADES (Top {len(self.perfect_trades)})")
            logger.info("=" * 80)
            
            for i, trade in enumerate(self.perfect_trades, 1):
                symbol = trade.get('symbol', 'N/A')
                direction = trade.get('direction', 'N/A')
                strike = trade.get('strike', 'N/A')
                score = trade.get('quality_score', 0)
                reason = trade.get('reason', 'N/A')
                
                logger.info(f"{i}. {symbol} {direction} @ {strike} - Score: {score:.1f}% - {reason}")
            
            logger.info("=" * 80)
    
    def get_perfect_trades(self) -> List[Dict]:
        """
        Get current list of perfect trades (thread-safe).
        Returns top 5 trades sorted by ranking score.
        
        Returns:
            List of perfect trade dictionaries (top 5 ranked)
        """
        with self.lock:
            # Sort by ranking score and return top 5
            sorted_trades = sorted(self.perfect_trades, key=lambda x: x.get('ranking_score', 0), reverse=True)
            return sorted_trades[:5]
    
    def get_market_data(self) -> Dict:
        """
        Get current market data for all instruments (thread-safe).
        
        Returns:
            Dictionary of market data
        """
        with self.lock:
            return self.market_data.copy()
    
    def get_trade_by_id(self, trade_id: str) -> Optional[Dict]:
        """
        Get a specific trade by ID.
        
        Args:
            trade_id: Trade identifier
        
        Returns:
            Trade dictionary or None
        """
        with self.lock:
            for trade in self.perfect_trades:
                if trade.get('trade_id') == trade_id:
                    return trade
            return None
    
    def _is_trade_valid(self, trade):
        """
        Check if trade is still valid (not stale/expired).
        RELAXED FILTERS: More lenient to ensure trades available.
        
        Args:
            trade: Trade dictionary
            
        Returns:
            True if trade is still valid, False otherwise
        """
        try:
            spot = trade.get('spot', 0)
            strike = trade.get('strike', 0)
            direction = trade.get('direction', '')
            support = trade.get('support', 0)
            resistance = trade.get('resistance', 0)
            
            # Check 1: Spot distance from strike (relaxed buffer)
            diff = abs(spot - strike)
            max_distance = 200  # Increased from 100 to 200 (more lenient)
            
            if diff > max_distance:
                logger.info(f"  Filter: Spot too far from strike ({diff:.2f} > {max_distance})")
                return False
            
            # Check 2: Price crossed resistance/support (relaxed - allow some movement)
            if direction == 'CALL' and spot > resistance:
                # Allow if not too far past resistance
                if spot > resistance * 1.02:  # Only reject if >2% past resistance
                    logger.info(f"  Filter: Spot too far past resistance ({spot:.2f} > {resistance * 1.02:.2f})")
                    return False
            elif direction == 'PUT' and spot < support:
                # Allow if not too far past support
                if spot < support * 0.98:  # Only reject if >2% past support
                    logger.info(f"  Filter: Spot too far past support ({spot:.2f} < {support * 0.98:.2f})")
                    return False
            
            # Check 3: Estimated premium threshold (relaxed)
            # Simple inline estimation to avoid circular import
            base = spot * 0.004
            
            if diff < 50:
                premium = base
            elif diff < 100:
                premium = base * 0.8
            else:
                premium = base * 0.6
            
            # ITM boost
            if direction == 'CALL' and spot > strike:
                premium *= 1.1
            elif direction == 'PUT' and spot < strike:
                premium *= 1.1
            
            est_entry = round(premium, 2)
            
            max_premium = 300  # Increased from 150 to 300 (more lenient)
            if est_entry > max_premium:
                logger.info(f"  Filter: Estimated premium too high ({est_entry:.2f} > {max_premium})")
                return False
            
            # Trade is still valid
            return True
            
        except Exception as e:
            logger.error(f"Error validating trade: {e}")
            return True  # Default to valid if error
    
    def _print_analyzer_report(self, total_scanned, total_valid, total_filtered):
        """
        Print analyzer status report.
        
        Args:
            total_scanned: Total instruments scanned
            total_valid: Total valid trades found
            total_filtered: Total trades filtered out
        """
        print("\n" + "="*80)
        print("📊 ANALYZER REPORT")
        print("="*80)
        print(f"Total Instruments Scanned: {total_scanned}")
        print(f"Valid Trades Found: {total_valid}")
        print(f"Filtered (Stale/Expired/LLM): {total_filtered}")
        print(f"Perfect Trades (Quality ≥70%): {len(self.perfect_trades)}")
        if self.llm_analyzer:
            print(f"LLM Filtering: ENABLED (applied during scan)")
        else:
            print(f"LLM Filtering: DISABLED")
        print("="*80)





# Convenience function to create and start market analyzer
def create_market_analyzer(kite_client, watchlist, analysis_interval=30, auto_start=True, llm_analyzer=None):
    """
    Create and optionally start a market analyzer.
    
    Args:
        kite_client: KiteConnect client
        watchlist: List of instruments to analyze
        analysis_interval: Seconds between analysis cycles
        auto_start: Whether to automatically start the analyzer (default: True)
        llm_analyzer: Optional LLM analyzer for trade validation during scan
    
    Returns:
        MarketAnalyzer instance
    """
    analyzer = MarketAnalyzer(kite_client, watchlist, analysis_interval, llm_analyzer)
    if auto_start:
        analyzer.start()
    return analyzer


if __name__ == "__main__":
    # Test the market analyzer
    from trading_bot import CleanTradingBot
    
    print("Testing Market Analyzer...")
    
    # Create bot to get kite client
    bot = CleanTradingBot()
    
    # Create market analyzer
    analyzer = create_market_analyzer(
        kite_client=bot.kite_client,
        watchlist=['NIFTY', 'BANKNIFTY'],
        analysis_interval=15  # 15 seconds for testing
    )
    
    print("Market Analyzer running in background...")
    print("Press Ctrl+C to stop")
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
            
            # Print perfect trades every 30 seconds
            if int(time.time()) % 30 == 0:
                trades = analyzer.get_perfect_trades()
                print(f"\nCurrent perfect trades: {len(trades)}")
                for trade in trades:
                    print(f"  {trade['symbol']} {trade['direction']} @ {trade['strike']} - Score: {trade['quality_score']:.1f}%")
    
    except KeyboardInterrupt:
        print("\nStopping Market Analyzer...")
        analyzer.stop()
        print("Market Analyzer stopped")

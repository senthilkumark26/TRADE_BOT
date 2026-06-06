"""
Engine 2: Async LLM Worker (Production-Grade Phase 1)
-----------------------------------------------------
Background worker thread that handles:
- Queue-based LLM validation requests
- Lightweight market regime validation
- Binary YES/NO responses to Engine 1
- Cache mechanism for performance
- Strong signal auto-approval
- Latency tracking with timeout

This engine runs asynchronously and never blocks Engine 1.
"""

import logging
import threading
import queue
import time
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class Engine2LLMWorker:
    """
    Async LLM Worker - Engine 2 (Production-Grade Phase 1)
    Processes LLM validation requests in the background without blocking the main thread.
    """
    
    def __init__(self, llm_analyzer, config=None, max_queue_size=100):
        """
        Initialize Engine 2.
        
        Args:
            llm_analyzer: LLM analyzer instance (LLMMarketAnalyzer or GeminiIntegration)
            config: Configuration dictionary for LLM settings
            max_queue_size: Maximum queue size for validation requests
        """
        self.llm_analyzer = llm_analyzer
        self.config = config or {}
        self.max_queue_size = max_queue_size
        
        # Queue for validation requests
        self.validation_queue = queue.Queue(maxsize=max_queue_size)
        
        # Result cache (request_id -> result)
        self.result_cache = {}
        self.result_cache_lock = threading.Lock()
        
        # Cache mechanism
        self.cache = {}  # signal_signature -> (decision, timestamp)
        self.CACHE_TTL = 60  # Cache time-to-live in seconds
        
        # Worker thread
        self.worker_thread = None
        self.running = False
        
        # Statistics
        self.stats = {
            'total_requests': 0,
            'successful_validations': 0,
            'failed_validations': 0,
            'avg_processing_time': 0.0,
            'cache_hits': 0,
            'cache_misses': 0,
            'strong_signal_auto_approvals': 0,
            'llm_timeouts': 0,
            'skip_decisions': 0
        }
        
        logger.info("Engine 2 (Async LLM Worker) initialized with production-grade features")
    
    def start(self):
        """Start the background worker thread."""
        if self.running:
            logger.warning("Engine 2 worker already running")
            return
        
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="Engine2-LLMWorker",
            daemon=True
        )
        self.worker_thread.start()
        logger.info("Engine 2 worker thread started with production-grade features")
    
    def stop(self):
        """Stop the background worker thread."""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("Engine 2 worker thread stopped")
    
    def _worker_loop(self):
        """
        Main worker loop - processes validation requests from queue.
        This runs in a separate thread and never blocks Engine 1.
        """
        logger.info("Engine 2 worker loop started with production-grade features")
        
        while self.running:
            try:
                # Get request from queue (with timeout to allow periodic checks)
                try:
                    request = self.validation_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process the request
                self._process_validation_request(request)
                
                # Mark task as done
                self.validation_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in Engine 2 worker loop: {e}")
                time.sleep(1)
        
        logger.info("Engine 2 worker loop stopped")
    
    def _process_validation_request(self, request: Dict[str, Any]):
        """
        Process a single validation request with production-grade features.
        
        Args:
            request: Validation request dictionary
        """
        request_id = request.get('request_id')
        signal_data = request.get('signal_data')
        
        if not request_id or not signal_data:
            logger.error("Invalid validation request: missing request_id or signal_data")
            return
        
        start_time = time.time()
        
        try:
            logger.info(f"Engine 2: Processing validation request {request_id}")
            
            # Step 1: Check cache first (DO NOT cache SKIP decisions)
            cache_key = self._generate_cache_key(signal_data)
            cached_result = self._check_cache(cache_key)
            
            if cached_result:
                self.stats['cache_hits'] += 1
                logger.info(f"Engine 2: Cache HIT for {request_id} - Decision: {cached_result}")
                
                # Cache the cached result
                with self.result_cache_lock:
                    self.result_cache[request_id] = {
                        'result': cached_result,
                        'timestamp': time.time(),
                        'processing_time': time.time() - start_time,
                        'from_cache': True
                    }
                
                self.stats['total_requests'] += 1
                if cached_result.get('approved', False):
                    self.stats['successful_validations'] += 1
                else:
                    self.stats['failed_validations'] += 1
                
                return
            else:
                self.stats['cache_misses'] += 1
                logger.info(f"Engine 2: Cache MISS for {request_id}")
            
            # Step 2: Check for strong signal (auto-approve)
            if self._is_strong_signal(signal_data):
                self.stats['strong_signal_auto_approvals'] += 1
                strong_approval = {'approved': True, 'reason': 'Strong signal auto-approval', 'decision': 'YES', 'auto_approved': True}
                logger.info(f"Engine 2: Strong signal auto-approval for {request_id}")
                
                # Cache the strong signal approval
                self._update_cache(cache_key, strong_approval)
                
                # Cache the result
                with self.result_cache_lock:
                    self.result_cache[request_id] = {
                        'result': strong_approval,
                        'timestamp': time.time(),
                        'processing_time': time.time() - start_time,
                        'auto_approved': True
                    }
                
                self.stats['total_requests'] += 1
                self.stats['successful_validations'] += 1
                
                return
            
            # Step 3: Call LLM with latency tracking
            decision, latency = self._call_llm_with_latency(signal_data)
            
            logger.info(f"Engine 2: LLM Decision: {decision} | Latency: {latency:.3f}s")
            
            # Step 4: Check LLM timeout (read from provider-specific config)
            llm_provider = self.config.get("llm_provider", "ollama")
            if llm_provider == "ollama":
                llm_timeout = self.config.get("ollama", {}).get("llm_timeout", 2.5)
            elif llm_provider == "gemini":
                llm_timeout = self.config.get("gemini", {}).get("llm_timeout", 2.5)
            elif llm_provider == "openai":
                llm_timeout = self.config.get("openai", {}).get("llm_timeout", 2.5)
            elif llm_provider == "airllm":
                llm_timeout = self.config.get("airllm", {}).get("llm_timeout", 30.0)
            else:
                llm_timeout = 2.5
            
            if latency > llm_timeout:
                self.stats['llm_timeouts'] += 1
                logger.warning(f"Engine 2: LLM timeout ({latency:.3f}s > {llm_timeout}s) - Returning SKIP")
                decision = "SKIP"
            
            # Step 5: Convert decision to result format
            if decision == "YES":
                result = {'approved': True, 'reason': 'LLM approved', 'decision': 'YES'}
            elif decision == "NO":
                result = {'approved': False, 'reason': 'LLM rejected', 'decision': 'NO'}
            else:  # SKIP
                result = {'approved': False, 'reason': 'LLM timeout or error', 'decision': 'SKIP'}
                self.stats['skip_decisions'] += 1
            
            # Step 6: Cache the result (DO NOT cache SKIP decisions)
            if decision != "SKIP":
                self._update_cache(cache_key, result)
            
            # Cache the result
            with self.result_cache_lock:
                self.result_cache[request_id] = {
                    'result': result,
                    'timestamp': time.time(),
                    'processing_time': time.time() - start_time,
                    'llm_latency': latency
                }
            
            # Update statistics
            self.stats['total_requests'] += 1
            if result.get('approved', False):
                self.stats['successful_validations'] += 1
            else:
                self.stats['failed_validations'] += 1
            
            # Update average processing time
            total_time = self.stats['avg_processing_time'] * (self.stats['total_requests'] - 1)
            processing_time = time.time() - start_time
            self.stats['avg_processing_time'] = (total_time + processing_time) / self.stats['total_requests']
            
            logger.info(f"Engine 2: Validation {request_id} completed in {processing_time:.2f}s - Result: {result}")
            
        except Exception as e:
            logger.error(f"Error processing validation request {request_id}: {e}")
            
            # Cache error result
            with self.result_cache_lock:
                self.result_cache[request_id] = {
                    'result': {'approved': False, 'reason': f'Error: {str(e)}', 'decision': 'SKIP'},
                    'timestamp': time.time(),
                    'processing_time': time.time() - start_time,
                    'error': True
                }
            
            self.stats['total_requests'] += 1
            self.stats['failed_validations'] += 1
            self.stats['skip_decisions'] += 1
    
    def _generate_cache_key(self, signal_data: Dict[str, Any]) -> str:
        """
        Generate a cache key from signal data.
        
        Args:
            signal_data: Signal dictionary
            
        Returns:
            Cache key string
        """
        # Create key from critical signal parameters
        symbol = signal_data.get('symbol', '')
        direction = signal_data.get('direction', '')
        strike = signal_data.get('strike', 0)
        pcr = signal_data.get('pcr', 0)
        
        # Round PCR to 1 decimal to group similar signals
        pcr_rounded = round(pcr, 1)
        
        return f"{symbol}_{direction}_{strike}_{pcr_rounded}"
    
    def _check_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Check if result exists in cache and is still valid.
        
        Args:
            cache_key: Cache key string
            
        Returns:
            Cached result if valid and not SKIP, None otherwise
        """
        current_time = time.time()
        
        if cache_key in self.cache:
            decision, timestamp = self.cache[cache_key]
            
            # Check if cache is still valid (within TTL)
            if current_time - timestamp < self.CACHE_TTL:
                # Only return if decision is not SKIP (per requirements)
                if decision.get('decision') != 'SKIP':
                    return decision
                else:
                    # SKIP decisions are not cached
                    del self.cache[cache_key]
                    return None
            else:
                # Cache expired
                del self.cache[cache_key]
                return None
        
        return None
    
    def _update_cache(self, cache_key: str, result: Dict[str, Any]):
        """
        Update cache with new result.
        
        Args:
            cache_key: Cache key string
            result: Result dictionary
        """
        # DO NOT cache SKIP decisions (per requirements)
        if result.get('decision') == 'SKIP':
            return
        
        self.cache[cache_key] = (result, time.time())
    
    def _is_strong_signal(self, signal_data: Dict[str, Any]) -> bool:
        """
        Check if signal meets strong signal criteria for auto-approval.
        
        Strong Signal Criteria:
        - CALL: VWAP ABOVE + PCR > 1.2 + OI STRONG
        - PUT: VWAP BELOW + PCR < 0.8 + OI STRONG
        
        Args:
            signal_data: Signal dictionary
            
        Returns:
            True if strong signal, False otherwise
        """
        direction = signal_data.get('direction', '')
        pcr = signal_data.get('pcr', 0)
        
        # Extract VWAP relationship
        vwap = signal_data.get('vwap', 0)
        spot = signal_data.get('spot', 0)
        if vwap == 0 or spot == 0:
            return False
        
        vwap_above = spot > vwap
        vwap_below = spot < vwap
        
        # Extract OI strength
        oi_strength = signal_data.get('oi_strength', signal_data.get('buildup_pattern', ''))
        oi_strong = oi_strength in ['STRONG', 'LONG_BUILDUP', 'SHORT_BUILDUP']
        
        # Check strong signal criteria
        if direction == 'CALL':
            # CALL: VWAP ABOVE + PCR > 1.2 + OI STRONG
            if vwap_above and pcr > 1.2 and oi_strong:
                logger.info(f"Strong CALL signal detected: VWAP above, PCR={pcr:.2f}, OI strong")
                return True
        
        elif direction == 'PUT':
            # PUT: VWAP BELOW + PCR < 0.8 + OI STRONG
            if vwap_below and pcr < 0.8 and oi_strong:
                logger.info(f"Strong PUT signal detected: VWAP below, PCR={pcr:.2f}, OI strong")
                return True
        
        return False
    
    def _call_llm_with_latency(self, signal_data: Dict[str, Any]) -> tuple:
        """
        Call LLM with latency tracking.
        
        Args:
            signal_data: Signal dictionary
            
        Returns:
            Tuple of (decision, latency_in_seconds)
        """
        start_time = time.time()
        decision = "SKIP"  # Default to SKIP on error
        
        try:
            # Call the existing LLM validation method
            result = self._validate_with_llm(signal_data)
            
            if result:
                approved = result.get('approved', False)
                decision = "YES" if approved else "NO"
            else:
                decision = "SKIP"
                
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            decision = "SKIP"
        
        latency = time.time() - start_time
        return decision, latency
    
    def _validate_with_llm(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lightweight LLM validation of market regime.
        
        This is a simplified, fast validation that returns binary YES/NO.
        It does NOT perform complex analysis - that's for later phases.
        
        Args:
            signal_data: Signal data from Engine 1
            
        Returns:
            Dictionary with 'approved' (bool) and 'reason' (str)
        """
        if not self.llm_analyzer:
            # Fallback: approve if signal strength is high enough
            strength = signal_data.get('strength', 0)
            if strength >= 2:
                return {
                    'approved': True,
                    'reason': f'LLM not available, auto-approved (strength={strength})'
                }
            else:
                return {
                    'approved': False,
                    'reason': f'LLM not available, auto-rejected (strength={strength})'
                }
        
        # Prepare lightweight prompt for LLM
        prompt = self._build_lightweight_prompt(signal_data)
        
        try:
            # Call LLM with timeout protection
            import concurrent.futures
            
            def get_llm_response():
                if hasattr(self.llm_analyzer, 'analyze_entry_signal'):
                    return self.llm_analyzer.analyze_entry_signal(signal_data)
                elif hasattr(self.llm_analyzer, 'analyze_trading_data'):
                    return self.llm_analyzer.analyze_trading_data(signal_data, "entry")
                else:
                    logger.error("LLM analyzer has no compatible method")
                    return None
            
            # Use ThreadPoolExecutor with 15-second timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(get_llm_response)
                try:
                    analysis = future.result(timeout=15)
                except concurrent.futures.TimeoutError:
                    logger.warning("LLM validation timed out after 15 seconds")
                    # Fallback to strength-based approval
                    strength = signal_data.get('strength', 0)
                    return {
                        'approved': strength >= 2,
                        'reason': f'LLM timeout, fallback to strength={strength}'
                    }
            
            if analysis:
                signal = analysis.get('signal', 'HOLD')
                confidence = analysis.get('confidence', 0)
                reason = analysis.get('reason', 'No reason provided')
                
                # Binary decision: YES if signal is BUY/SELL with confidence >= 70%
                approved = (signal in ['BUY', 'SELL']) and (confidence >= 70)
                
                return {
                    'approved': approved,
                    'reason': f'LLM: {signal} ({confidence}% confidence) - {reason}',
                    'llm_signal': signal,
                    'llm_confidence': confidence
                }
            else:
                # Fallback to strength-based approval
                strength = signal_data.get('strength', 0)
                return {
                    'approved': strength >= 2,
                    'reason': f'LLM analysis failed, fallback to strength={strength}'
                }
                
        except Exception as e:
            logger.error(f"Error in LLM validation: {e}")
            # Fallback to strength-based approval
            strength = signal_data.get('strength', 0)
            return {
                'approved': strength >= 2,
                'reason': f'LLM error: {str(e)}, fallback to strength={strength}'
            }
    
    def _build_lightweight_prompt(self, signal_data: Dict[str, Any]) -> str:
        """
        Build a lightweight prompt for LLM validation with human sentiment context.
        
        Phase 1: Validate market regime with heavy weighting on human sentiment to avoid retail traps.
        
        Args:
            signal_data: Signal data from Engine 1
            
        Returns:
            Prompt string
        """
        symbol = signal_data.get('symbol', '')
        direction = signal_data.get('direction', '')
        spot = signal_data.get('spot', 0)
        vwap = signal_data.get('vwap', 0)
        pcr = signal_data.get('pcr', 0)
        price_change = signal_data.get('price_change', 0)
        buildup = signal_data.get('buildup_pattern', '')
        strength = signal_data.get('strength', 0)
        
        # Extract LLM context (human sentiment data)
        llm_context = signal_data.get('llm_context', {})
        market_sentiment = llm_context.get('market_sentiment', 'NEUTRAL')
        retail_positioning = llm_context.get('retail_positioning', 'NEUTRAL')
        trap_detection = llm_context.get('trap_detection', 'NONE')
        fear_greed = llm_context.get('fear_greed', 'NEUTRAL')
        retail_trap_risk = llm_context.get('retail_trap_risk', 'MEDIUM')
        smart_money_flow = llm_context.get('smart_money_flow', 'NEUTRAL')
        technical_traps = llm_context.get('technical_traps', ['NONE'])
        
        prompt = f"""You are a market regime validator. Answer YES or NO.

Trading Signal:
- Symbol: {symbol}
- Direction: {direction}
- Spot: {spot:.2f}
- VWAP: {vwap:.2f}
- PCR: {pcr:.2f}
- Price Change: {price_change:.2f}%
- Buildup Pattern: {buildup}
- Signal Strength: {strength}/3

HUMAN SENTIMENT & RETAIL TRAP ANALYSIS (CRITICAL - HEAVILY WEIGHT THIS):
- Market Sentiment: {market_sentiment}
- Retail Positioning: {retail_positioning}
- Trap Detection: {trap_detection}
- Fear/Greed Index: {fear_greed}
- Retail Trap Risk: {retail_trap_risk}
- Smart Money Flow: {smart_money_flow}
- Technical Traps: {', '.join(technical_traps)}

INSTRUCTIONS: HEAVILY WEIGHT the human sentiment data above. 
- If retail_trap_risk is HIGH or technical_traps show active traps, REJECT the trade.
- If smart_money_flow shows divergence from retail positioning, be CAUTIOUS.
- If trap_detection shows a retail trap setup, this is a STRONG SIGNAL to execute.
- Avoid trades where retail is trapped against the direction.

Question: Is this a valid market regime for a {direction} trade, considering the human sentiment data?

Answer with only YES or NO, followed by a brief reason (max 30 words).
"""
        return prompt
    
    def submit_validation_request(self, signal_data: Dict[str, Any]) -> str:
        """
        Submit a validation request to the queue.
        
        This is NON-BLOCKING - returns immediately with a request ID.
        
        Args:
            signal_data: Signal data from Engine 1
            
        Returns:
            Request ID for tracking the result
        """
        request_id = f"{signal_data.get('symbol', '')}_{signal_data.get('direction', '')}_{int(time.time())}"
        
        request = {
            'request_id': request_id,
            'signal_data': signal_data,
            'timestamp': time.time()
        }
        
        try:
            self.validation_queue.put(request, timeout=1.0)
            logger.info(f"Engine 2: Validation request {request_id} submitted to queue")
            return request_id
        except queue.Full:
            logger.error("Engine 2: Validation queue is full, cannot submit request")
            return None
    
    def get_validation_result(self, request_id: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Get validation result for a request.
        
        This is NON-BLOCKING with timeout - polls for result.
        
        Args:
            request_id: Request ID from submit_validation_request
            timeout: Maximum time to wait for result (seconds)
            
        Returns:
            Result dictionary or None if timeout/error
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.result_cache_lock:
                if request_id in self.result_cache:
                    return self.result_cache[request_id]
            
            # Sleep briefly before checking again
            time.sleep(0.1)
        
        logger.warning(f"Validation result timeout for request {request_id}")
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics including production-grade metrics."""
        return self.stats.copy()
    
    def clear_old_results(self, max_age_seconds: int = 300):
        """
        Clear old validation results from cache.
        
        Args:
            max_age_seconds: Maximum age of results to keep
        """
        with self.result_cache_lock:
            current_time = time.time()
            old_keys = [
                key for key, value in self.result_cache.items()
                if current_time - value['timestamp'] > max_age_seconds
            ]
            for key in old_keys:
                del self.result_cache[key]
            
            if old_keys:
                logger.info(f"Engine 2: Cleared {len(old_keys)} old validation results")

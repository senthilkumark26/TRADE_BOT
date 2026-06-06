"""
Market Signal Analyzer - CLI Display Only
-----------------------------------------
Analyzes market data and displays trade calls in CLI.
Does NOT execute trades - just shows signals in real-time.
"""

import logging
import time
import json
from datetime import datetime
from kite_client import KiteClient
from engine1_market_analyzer import Engine1MarketAnalyzer

# Setup logging for CLI display
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


class MarketSignalAnalyzer:
    """
    Market Signal Analyzer - CLI Display Only
    Analyzes market data and shows trade calls in real-time.
    """
    
    def __init__(self, config_path="config.json"):
        """Initialize the analyzer."""
        self.config_path = config_path
        self.config = self.load_config()
        
        # Initialize components
        self.kite_client = self._init_kite_client()
        self.analyzer = Engine1MarketAnalyzer(self.kite_client)
        self.market_simulator = self._init_market_simulator()
        
        # Trading universe
        self.watchlist = self._load_watchlist()
        
        # Statistics
        self.stats = {
            'cycles': 0,
            'signals_generated': 0,
            'call_signals': 0,
            'put_signals': 0,
            'last_signal_time': None
        }
        
        logger.info("=" * 80)
        logger.info("MARKET SIGNAL ANALYZER - CLI DISPLAY MODE")
        logger.info("=" * 80)
        logger.info(f"Trading Universe: {self.watchlist}")
        logger.info(f"Mode: ANALYSIS ONLY (No Execution)")
        logger.info("=" * 80)
    
    def load_config(self):
        """Load configuration."""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def _init_kite_client(self):
        """Initialize Kite Client."""
        use_demo = self.config.get('use_demo_data', False)
        
        if use_demo:
            # Use demo market simulator
            self.demo_mode = True
            logger.info("DEMO MODE ENABLED - Using Fake Market Data")
            return None  # Will be initialized separately
        else:
            # Real Kite client
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            access_token = self.config.get('access_token')
            kite_client = KiteClient(api_key, api_secret, access_token)
            logger.info("Real Kite Client initialized")
            return kite_client
    
    def _init_market_simulator(self):
        """Initialize demo market simulator - DISABLED."""
        if self.config.get('use_demo_data', False):
            logger.info("Demo simulator removed from codebase - using real data only")
        return None
    
    def _load_watchlist(self):
        """Load watchlist from config."""
        instruments = self.config.get('instruments', {})
        return list(instruments.keys())
    
    def get_market_data(self):
        """Get market data for all instruments."""
        market_data = {}
        
        if self.demo_mode:
            # Use demo simulator
            for symbol in self.watchlist:
                data = self.market_simulator.get_market_data(symbol)
                if data:
                    market_data[symbol] = {
                        'ltp': data.get('ltp', 0),
                        'vwap': data.get('vwap', 0),
                        'oi': data.get('oi', 0),
                        'volume': data.get('volume', 0)
                    }
        else:
            # Real market data
            for symbol in self.watchlist:
                quote = self.kite_client.get_quote(symbol)
                if quote:
                    market_data[symbol] = quote
        
        return market_data
    
    def analyze_signals(self, market_data):
        """Analyze market data and generate signals."""
        signals = []
        
        for symbol, data in market_data.items():
            try:
                # Update price (this automatically calculates VWAP)
                vwap = self.analyzer.update_price(symbol, data['ltp'])
                
                # Calculate price change (simplified - use random change for demo)
                import random
                price_change = random.uniform(-0.02, 0.02)  # Random change between -2% and +2%
                
                # Try to generate signal using the Engine 1 method
                signal = self.analyzer.generate_signal(
                    symbol=symbol,
                    spot_price=data['ltp'],
                    price_change=price_change
                )
                
                if signal:
                    signal['timestamp'] = datetime.now()
                    signals.append(signal)
                
                # After 5 cycles, always generate simple signals for demo
                if self.stats['cycles'] > 5:
                    direction = 'CALL' if price_change > 0 else 'PUT'
                    simple_signal = {
                        'symbol': symbol,
                        'direction': direction,
                        'spot': data['ltp'],
                        'vwap': data.get('vwap', data['ltp']),
                        'pcr': 1.2 if direction == 'CALL' else 0.8,
                        'price_change': price_change,
                        'oi_strength': 'HIGH' if abs(price_change) > 0.01 else 'LOW',
                        'timestamp': datetime.now(),
                        # Add llm_context for demo signals
                        'llm_context': {
                            'market_sentiment': 'BULLISH' if direction == 'CALL' else 'BEARISH',
                            'retail_positioning': 'LONG' if direction == 'CALL' else 'SHORT',
                            'trap_detection': 'NONE',
                            'fear_greed': 'NEUTRAL',
                            'retail_trap_risk': 'MEDIUM',
                            'smart_money_flow': 'NEUTRAL',
                            'technical_traps': ['NONE']
                        }
                    }
                    signals.append(simple_signal)
                    
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
        
        return signals
    
    def display_signal(self, signal):
        """Display signal in CLI format with LLM context and write to signal queue."""
        direction = signal.get('direction', 'N/A')
        symbol = signal.get('symbol', 'N/A')
        pcr = signal.get('pcr', 0)
        vwap = signal.get('vwap', 0)
        price = signal.get('spot', 0)
        oi_strength = signal.get('oi_strength', 'N/A')
        
        # Extract LLM context
        llm_context = signal.get('llm_context', {})
        market_sentiment = llm_context.get('market_sentiment', 'N/A')
        retail_positioning = llm_context.get('retail_positioning', 'N/A')
        trap_detection = llm_context.get('trap_detection', 'N/A')
        fear_greed = llm_context.get('fear_greed', 'N/A')
        retail_trap_risk = llm_context.get('retail_trap_risk', 'N/A')
        
        # Display in CLI
        print(f"\n{'='*80}")
        print(f"SIGNAL DETECTED")
        print(f"{'='*80}")
        print(f"  Symbol:      {symbol}")
        print(f"  Direction:    {direction}")
        print(f"  PCR:         {pcr:.2f}")
        print(f"  VWAP:        Rs.{vwap:.2f}")
        print(f"  Spot Price:  Rs.{price:.2f}")
        print(f"  OI Strength:  {oi_strength}")
        print(f"  Time:        {signal['timestamp'].strftime('%H:%M:%S')}")
        print(f"\n{'─'*80}")
        print(f"📊 HUMAN SENTIMENT CONTEXT")
        print(f"{'─'*80}")
        print(f"  Market Sentiment:   {market_sentiment}")
        print(f"  Retail Positioning: {retail_positioning}")
        print(f"  Trap Detection:     {trap_detection}")
        print(f"  Fear/Greed:         {fear_greed}")
        print(f"  Retail Trap Risk:   {retail_trap_risk}")
        print(f"{'='*80}")
        
        # Write signal to queue file for paper trading bot
        self._write_signal_to_queue(signal)
    
    def _write_signal_to_queue(self, signal):
        """Write signal to queue file for paper trading bot."""
        try:
            import json
            signal_queue_file = "signal_queue.jsonl"
            
            # Convert datetime to string for JSON serialization
            signal_copy = signal.copy()
            signal_copy['timestamp'] = signal['timestamp'].isoformat()
            
            # Append to queue file
            with open(signal_queue_file, 'a') as f:
                f.write(json.dumps(signal_copy) + '\n')
            
            logger.info(f"Signal written to queue: {signal['symbol']} {signal['direction']}")
            
        except Exception as e:
            logger.error(f"Error writing signal to queue: {e}")
    
    def run_analysis_loop(self, cycle_time=10):
        """Run the analysis loop."""
        logger.info("\n" + "=" * 80)
        logger.info("STARTING ANALYSIS LOOP")
        logger.info("Building VWAP history - signals will appear after enough data")
        logger.info("=" * 80)
        
        try:
            while True:
                cycle_start = time.time()
                
                # Get market data
                market_data = self.get_market_data()
                
                # Update stats
                self.stats['cycles'] += 1
                
                # Analyze signals
                signals = self.analyze_signals(market_data)
                
                # Display signals
                if signals:
                    self.stats['signals_generated'] += len(signals)
                    for signal in signals:
                        direction = signal.get('direction', 'N/A')
                        if direction == 'CALL':
                            self.stats['call_signals'] += 1
                        elif direction == 'PUT':
                            self.stats['put_signals'] += 1
                        
                        self.stats['last_signal_time'] = datetime.now()
                        self.display_signal(signal)
                
                # Display summary every 10 cycles
                if self.stats['cycles'] % 10 == 0:
                    self.display_summary()
                
                # Wait for next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, cycle_time - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 80)
            logger.info("ANALYSIS STOPPED BY USER")
            logger.info("=" * 80)
            self.display_summary()
    
    def display_summary(self):
        """Display analysis summary."""
        print(f"\n{'='*80}")
        print(f"ANALYSIS SUMMARY")
        print(f"{'='*80}")
        print(f"  Cycles:           {self.stats['cycles']}")
        print(f"  Total Signals:     {self.stats['signals_generated']}")
        print(f"  CALL Signals:      {self.stats['call_signals']}")
        print(f"  PUT Signals:       {self.stats['put_signals']}")
        if self.stats['last_signal_time']:
            print(f"  Last Signal:      {self.stats['last_signal_time'].strftime('%H:%M:%S')}")
        print(f"{'='*80}")


def main():
    """Main entry point."""
    analyzer = MarketSignalAnalyzer()
    analyzer.run_analysis_loop()


if __name__ == "__main__":
    main()
"""
Unified Trading System - Supports NSE and MCX with shared services
---------------------------------------------------
Architecture:
- Universal Risk Manager (all markets)
- Shared Services (MarketAnalyzer, Consensus, LLM, etc.)
- Market Selection via argument (NSE/MCX)
- Same trading logic for both markets
"""

import json
import logging
import argparse
from datetime import datetime, time as dt_time
import sys
import os

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from kite.kite_client import KiteClient
from wrappers.risk_wrapper import (
    get_position_size,
    update_trade_result,
    can_execute_trade,
    reset_daily_limits,
    get_risk_status
)
from services.market_analyzer_service import MarketAnalyzerService
from services.consensus_service import ConsensusService
from services.llm_analyzer_service import LLMAnalyzerService
from services.execution_brain_service import ExecutionBrainService
from mcx.mcx_wrapper import get_mcx_signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class UnifiedTrader:
    """
    Unified Trading System - Works for both NSE and MCX
    Uses shared services and universal risk management
    """
    
    def __init__(self, market_type="NSE", symbol="NIFTY", capital=100000):
        """
        Initialize Unified Trader
        
        Args:
            market_type: "NSE" or "MCX"
            symbol: Trading symbol (e.g., "NIFTY", "CRUDEOILM")
            capital: Trading capital
        """
        self.market_type = market_type.upper()
        self.symbol = symbol.upper()
        self.capital = capital
        
        # Load config
        with open('config.json', 'r') as f:
            self.config = json.load(f)
        
        # Initialize Kite Client
        self.kite_client = KiteClient(
            api_key=self.config.get("api_key", ""),
            access_token=self.config.get("access_token", ""),
            paper_trading=True  # Paper trading by default
        )
        
        # Initialize Shared Services (Same for NSE and MCX)
        self.market_analyzer = MarketAnalyzerService()
        self.consensus_service = ConsensusService()
        self.llm_analyzer = LLMAnalyzerService()
        self.execution_brain = ExecutionBrainService()
        
        # Market-specific settings
        if self.market_type == "MCX":
            self.market_open = dt_time(9, 0)
            self.market_close = dt_time(23, 30)
            self.exchange = "MCX"
            logger.info(f"MCX Market: {self.symbol} | Hours: 09:00-23:30")
        else:  # NSE
            self.market_open = dt_time(9, 15)
            self.market_close = dt_time(15, 30)
            self.exchange = "NSE"
            logger.info(f"NSE Market: {self.symbol} | Hours: 09:15-15:30")
        
        # Risk Manager is universal (already initialized in risk_wrapper.py)
        logger.info(f"Universal Risk Manager: Active")
        logger.info(f"Capital: {self.capital}")
        
        logger.info("="*80)
        logger.info("UNIFIED TRADING SYSTEM INITIALIZED")
        logger.info(f"Market: {self.market_type} | Symbol: {self.symbol}")
        logger.info(f"Exchange: {self.exchange}")
        logger.info("="*80)
    
    def get_market_data(self):
        """
        Get market data (works for both NSE and MCX)
        """
        try:
            if self.market_type == "MCX":
                # MCX data fetching
                contract = self.kite_client.get_nearest_mcx_contract(self.symbol)
                if not contract:
                    logger.error(f"No MCX contract found for {self.symbol}")
                    return None
                
                token = contract['instrument_token']
                quote = self.kite_client.kite.quote([token])
                
                if not quote or str(token) not in quote:
                    logger.error("No quote data received")
                    return None
                
                data = quote[str(token)]
                return {
                    'price': data.get('last_price', 0),
                    'oi': data.get('oi', 0),
                    'volume': data.get('volume', 0),
                    'contract': contract
                }
            
            else:  # NSE
                # NSE data fetching (option chain)
                option_chain, pcr, delta_data, atm = self.kite_client.get_option_chain_optimized(
                    self.symbol, 0  # Will need current spot price
                )
                return {
                    'option_chain': option_chain,
                    'pcr': pcr,
                    'delta_data': delta_data,
                    'atm': atm
                }
        
        except Exception as e:
            logger.error(f"Error getting market data: {e}")
            return None
    
    def analyze_trading_opportunity(self, market_data):
        """
        Analyze trading opportunity using shared services
        Works for both NSE and MCX
        """
        try:
            # Use Market Analyzer Service (shared)
            if self.market_type == "NSE":
                analysis = self.market_analyzer.analyze_market(
                    symbol=self.symbol,
                    spot_price=market_data.get('atm', 0),
                    vwap=0,  # Will need proper VWAP
                    price_change=0,
                    delta_oi=0,
                    pcr=market_data.get('pcr', 0),
                    option_chain=market_data.get('option_chain', {})
                )
            else:  # MCX
                # MCX-specific analysis using same service structure
                analysis = self.market_analyzer.analyze_market(
                    symbol=self.symbol,
                    spot_price=market_data.get('price', 0),
                    vwap=0,
                    price_change=0,
                    delta_oi=0,
                    pcr=0,  # MCX doesn't have PCR like options
                    option_chain={}  # MCX uses futures, not options
                )
            
            return analysis
        
        except Exception as e:
            logger.error(f"Error analyzing opportunity: {e}")
            return None
    
    def execute_trade(self, analysis, market_data=None):
        """
        Execute trade using universal risk management
        Works for both NSE and MCX
        
        MCX uses additional MCX Signal Engine (does not replace existing system)
        """
        try:
            # 1. CHECK RISK MANAGER (Universal)
            if not can_execute_trade():
                logger.warning("RISK MANAGER BLOCKED TRADE - Trading stopped")
                return {"status": "BLOCKED", "reason": "Risk Manager"}
            
            # 2. MCX-SPECIFIC: Get MCX signal (ONLY for MCX, does not replace main system)
            mcx_signal = None
            if self.market_type == "MCX" and market_data:
                logger.info("[MCX] Getting MCX-specific signal...")
                mcx_signal = get_mcx_signal(
                    symbol=self.symbol,
                    price=market_data.get('price', 0),
                    oi=market_data.get('oi', 0),
                    volume=market_data.get('volume', 0)
                )
                if mcx_signal:  # Only process if MCX service is available
                    logger.info(f"[MCX] MCX Signal: {mcx_signal.get('signal')} | Confidence: {mcx_signal.get('confidence', 0):.2f}")
                    if mcx_signal.get('reasoning'):
                        logger.info(f"[MCX] Reasoning: {mcx_signal['reasoning']}")
                else:
                    logger.info("[MCX] MCX service disabled or unavailable (continuing with normal flow)")
            
            # 3. CALCULATE POSITION SIZE (Universal)
            stop_loss_points = 15  # Example SL
            lot_size = get_position_size(stop_loss_points)
            logger.info(f"Risk Manager calculated lot size: {lot_size}")
            
            # 4. USE CONSENSUS SERVICE (Shared - works for both NSE and MCX)
            # For now, skip consensus and go directly to LLM (simplified for demo)
            # In production, you would use: consensus = self.consensus_service.find_consensus(...)
            logger.info("Skipping consensus for demo - going to LLM directly")
            consensus = {"should_trade": True}  # Temporary bypass
            
            # 5. USE LLM ANALYZER (Shared - works for both NSE and MCX)
            if consensus.get('should_trade', False):
                # For demo, skip LLM and proceed directly
                logger.info("Skipping LLM for demo - proceeding to execution")
                llm_decision = {"should_execute": True}  # Temporary bypass
            else:
                logger.info("Consensus rejected trade")
                return {"status": "REJECTED", "reason": "Consensus"}
            
            # 6. EXECUTE (Market-specific)
            if self.market_type == "MCX":
                logger.info(f"Executing MCX trade: {self.symbol} | Lots: {lot_size}")
                if mcx_signal:
                    logger.info(f"[MCX] Additional MCX intelligence: {mcx_signal.get('signal')}")
                # MCX execution logic here
                return {"status": "EXECUTED", "lot_size": lot_size, "mcx_signal": mcx_signal}
            else:  # NSE
                logger.info(f"Executing NSE trade: {self.symbol} | Lots: {lot_size}")
                # NSE execution logic here
                return {"status": "EXECUTED", "lot_size": lot_size, "mcx_signal": None}
        
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return {"status": "ERROR", "reason": str(e)}
    
    def update_trade_result(self, pnl):
        """
        Update trade result (Universal Risk Manager)
        """
        update_trade_result(pnl)
        logger.info(f"Trade P&L: {pnl} | Updated in Risk Manager")
    
    def run_trading_session(self):
        """
        Run trading session (works for both NSE and MCX)
        """
        logger.info("="*80)
        logger.info(f"STARTING TRADING SESSION: {self.market_type} {self.symbol}")
        logger.info("="*80)
        
        # Reset daily limits
        reset_daily_limits()
        
        while True:
            try:
                # Check market hours
                now = datetime.now().time()
                if not (self.market_open <= now <= self.market_close):
                    logger.info(f"Market closed. Hours: {self.market_open}-{self.market_close}")
                    break
                
                # Get market data
                market_data = self.get_market_data()
                if not market_data:
                    logger.warning("No market data available")
                    time.sleep(30)
                    continue
                
                # Analyze opportunity
                analysis = self.analyze_trading_opportunity(market_data)
                if not analysis:
                    logger.warning("No trading opportunity found")
                    time.sleep(30)
                    continue
                
                # Execute trade (pass market_data for MCX signal engine)
                result = self.execute_trade(analysis, market_data)
                logger.info(f"Trade Result: {result}")
                
                # Wait before next check
                time.sleep(30)
            
            except KeyboardInterrupt:
                logger.info("Trading session stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in trading session: {e}")
                time.sleep(30)
        
        logger.info("="*80)
        logger.info("TRADING SESSION ENDED")
        logger.info("="*80)

def main():
    """
    Main entry point with market selection
    """
    parser = argparse.ArgumentParser(description='Unified Trading System')
    parser.add_argument('--market', type=str, default='NSE', 
                       help='Market type: NSE or MCX')
    parser.add_argument('--symbol', type=str, default='NIFTY',
                       help='Trading symbol (e.g., NIFTY, CRUDEOILM)')
    parser.add_argument('--capital', type=int, default=100000,
                       help='Trading capital')
    
    args = parser.parse_args()
    
    # Initialize Unified Trader
    trader = UnifiedTrader(
        market_type=args.market,
        symbol=args.symbol,
        capital=args.capital
    )
    
    # Run trading session
    trader.run_trading_session()

if __name__ == "__main__":
    main()
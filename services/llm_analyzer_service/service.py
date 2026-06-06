"""
LLM Analyzer Service - Independent LLM-based trade decision service
Provides: Human sentiment analysis, market psychology, final trade decisions
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from ollama_integration import OllamaIntegration
from airllm_integration import AirLLMIntegration

logger = logging.getLogger(__name__)


class LLMAnalyzerService:
    """
    LLM Analyzer Service - Standalone microservice for LLM-based trade decisions.
    Provides human sentiment analysis, market psychology, and final trade decisions.
    
    This service operates independently and makes final YES/NO decisions
    based on consensus data from other services.
    """
    
    def __init__(
        self,
        provider: str = "ollama",
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2:7b",
        mode: str = "moderate",
        fast_mode: bool = False,
        airllm_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the LLM Analyzer Service.
        
        Args:
            provider: LLM provider ('ollama', 'airllm', etc.)
            ollama_url: Ollama server URL (for ollama provider)
            model: Model name/path to use
            mode: Trading mode (conservative, moderate, aggressive)
            fast_mode: If True, use compact prompt for faster responses
            airllm_config: AirLLM-specific configuration (for airllm provider)
        """
        self.service_name = "llm_analyzer_service"
        self.version = "1.0.0"
        self.dependencies = []  # No dependencies (independent LLM service)
        self.dependents = ["consensus_service", "trading_bot"]
        self.protection_level = "CRITICAL"
        
        self.provider = provider
        self.ollama_url = ollama_url
        self.model = model
        self.mode = mode
        self.fast_mode = fast_mode
        self.airllm_config = airllm_config or {}
        
        # Initialize the appropriate LLM integration
        if provider == "airllm":
            self.llm = AirLLMIntegration(
                model_path=model,
                compression=self.airllm_config.get("compression", "4bit"),
                max_length=self.airllm_config.get("max_length", 128),
                fast_mode=fast_mode,
                layer_shards_saving_path=self.airllm_config.get("layer_shards_saving_path"),
                hf_token=self.airllm_config.get("hf_token")
            )
        else:  # default to ollama
            self.llm = OllamaIntegration(base_url=ollama_url, default_model=model, fast_mode=fast_mode)
        
        # Mode-specific settings
        self.mode_settings = {
            "conservative": {
                "risk_tolerance": "low",
                "confidence_threshold": 80,
                "risk_reward_ratio": "1:5",
                "position_size": "small"
            },
            "moderate": {
                "risk_tolerance": "medium",
                "confidence_threshold": 70,
                "risk_reward_ratio": "1:3",
                "position_size": "medium"
            },
            "aggressive": {
                "risk_tolerance": "high",
                "confidence_threshold": 60,
                "risk_reward_ratio": "1:2",
                "position_size": "large"
            }
        }
        
        self.current_settings = self.mode_settings.get(mode, self.mode_settings["moderate"])
        
        logger.info(f"LLM Analyzer Service initialized (v{self.version})")
        logger.info(f"Provider: {provider}, Mode: {mode}, Model: {model}")
        logger.info(f"Dependencies: {self.dependencies}")
        logger.info(f"Dependents: {self.dependents}")
        logger.info(f"Protection Level: {self.protection_level}")
    
    def evaluate_consensus_trade(self, consensus_payload: Dict) -> Dict:
        """
        Evaluate consensus payload and make final YES/NO decision.
        
        Args:
            consensus_payload: Consensus data from Consensus Service
            
        Returns:
            Dictionary with final decision ("BUY" or "SKIP") and reason
        """
        try:
            logger.info(f"[LLM SERVICE] Evaluating consensus trade...")
            
            # Extract consensus data
            consensus_data = consensus_payload.get("consensus_data", {})
            market_summary = consensus_data.get("market_summary", {})
            breakout_summary = consensus_data.get("breakout_summary", {})
            
            # Build LLM prompt for consensus evaluation
            prompt = self._build_consensus_prompt(
                consensus_data, market_summary, breakout_summary
            )
            
            logger.info(f"[LLM SERVICE] Sending consensus evaluation to LLM...")
            
            # Call LLM with consensus payload
            response = self.llm.generate(
                prompt=prompt,
                model=self.model,
                timeout=10.0  # 10-second timeout for LLM response
            )
            
            if response:
                decision = self._parse_llm_response(response)
                logger.info(f"[LLM SERVICE] LLM Decision: {decision['decision']} ({decision['reason']})")
                return decision
            else:
                # SAFE FALLBACK: REJECT trade if LLM fails
                logger.warning("[LLM SERVICE] LLM timeout/failure - SAFE DEFAULT: REJECT TRADE")
                return {
                    "decision": "SKIP",
                    "reason": "[SAFE_DEFAULT] LLM timeout - REJECTING trade (safety first)",
                    "confidence": 0,
                    "source": "SAFE_DEFAULT"
                }
                
        except Exception as e:
            logger.error(f"[LLM SERVICE] Error evaluating consensus trade: {e}")
            # SAFE FALLBACK: REJECT trade on error
            logger.warning("[LLM SERVICE] LLM error - SAFE DEFAULT: REJECT TRADE")
            return {
                "decision": "SKIP",
                "reason": f"[SAFE_DEFAULT] LLM error: {str(e)} - REJECTING trade (safety first)",
                "confidence": 0,
                "source": "SAFE_DEFAULT"
            }
    
    def _build_consensus_prompt(self, consensus_data: Dict, market_summary: Dict, 
                              breakout_summary: Dict) -> str:
        """Build LLM prompt for consensus evaluation"""
        
        confidence = consensus_data.get("confidence", 0.0)
        strikes = consensus_data.get("strikes", [])
        
        pcr_bias = market_summary.get("pcr_bias", "NEUTRAL")
        oi_signal = market_summary.get("oi_signal", "NEUTRAL")
        vwap_position = market_summary.get("vwap_position", "UNKNOWN")
        market_strength = market_summary.get("market_strength", 0)
        
        breakout_direction = breakout_summary.get("breakout_direction", "NONE")
        breakout_strength = breakout_summary.get("breakout_strength", "WEAK")
        entry_type = breakout_summary.get("entry_type", "NONE")
        
        prompt = f"""You are the final authority for trade decisions. 
Independent services have reached consensus on a potential trade. 
Evaluate the consensus data and make your final YES/NO decision.

CONSENSUS DATA:
- Consensus Confidence: {confidence:.2f} (0.0-1.0)
- Common Strikes: {len(strikes)}
- Independent Services: ['market_analyzer', 'breakout_entry']

MARKET ANALYSIS (Market Analyzer Service):
- PCR Bias: {pcr_bias}
- OI Signal: {oi_signal}
- VWAP Position: {vwap_position}
- Market Strength: {market_strength}/3

BREAKOUT ANALYSIS (Breakout Entry Service):
- Breakout Direction: {breakout_direction}
- Breakout Strength: {breakout_strength}
- Entry Type: {entry_type}

DECISION RULES:
- APPROVE (BUY) if: Consensus confidence >= 0.6 AND strong technical confluence
- REJECT (SKIP) if: Consensus confidence < 0.6 OR weak technical confluence OR conflicting signals

Respond with ONLY this JSON format (no other text):
{{"decision": "BUY" or "SKIP", "reason": "brief explanation based on consensus data"}}"""
        
        return prompt
    
    def _parse_llm_response(self, response: str) -> Dict:
        """Parse LLM response and extract decision"""
        try:
            # Try to parse JSON response
            import json
            response_dict = json.loads(response)
            
            # Validate decision
            decision = response_dict.get("decision", "SKIP")
            if decision not in ["BUY", "SKIP"]:
                decision = "SKIP"  # Default to skip for safety
            
            return {
                "decision": decision,
                "reason": response_dict.get("reason", "No reason provided"),
                "confidence": 0.8 if decision == "BUY" else 0.0,
                "source": "LLM_ANALYZER"
            }
            
        except Exception as e:
            logger.error(f"[LLM SERVICE] Error parsing LLM response: {e}")
            return {
                "decision": "SKIP",
                "reason": f"[ERROR] Failed to parse LLM response: {str(e)}",
                "confidence": 0,
                "source": "LLM_ANALYZER"
            }
    
    def get_service_info(self) -> Dict:
        """Get service information for service discovery"""
        return {
            "service_name": self.service_name,
            "version": self.version,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "protection_level": self.protection_level,
            "capabilities": [
                "consensus_evaluation",
                "final_trade_decision",
                "human_sentiment_analysis",
                "market_psychology",
                "risk_assessment"
            ]
        }

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from ollama_integration import OllamaIntegration
from airllm_integration import AirLLMIntegration

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class LLMMarketAnalyzer:
    """
    AI-powered market analyzer using local LLM (Ollama, AirLLM, or others).
    Replaces hardcoded trading logic with intelligent AI analysis.
    """
    
    def __init__(
        self,
        provider: str = "ollama",
        ollama_url: str = "http://localhost:11434",
        model: str = "mistral:7b",
        mode: str = "conservative",
        fast_mode: bool = False,
        airllm_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize LLM Market Analyzer.

        Args:
            provider: LLM provider ('ollama', 'airllm', etc.)
            ollama_url: Ollama server URL (for ollama provider)
            model: Model name/path to use
            mode: Trading mode (conservative, moderate, aggressive)
            fast_mode: If True, use compact prompt for faster responses
            airllm_config: AirLLM-specific configuration (for airllm provider)
        """
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
        logger.info(f"LLM Market Analyzer initialized with provider: {provider}, mode: {mode}, model: {model}")
    
    def switch_mode(self, mode: str) -> bool:
        """
        Switch trading mode.
        
        Args:
            mode: New mode (conservative, moderate, aggressive)
            
        Returns:
            True if successful
        """
        if mode in self.mode_settings:
            self.mode = mode
            self.current_settings = self.mode_settings[mode]
            logger.info(f"Switched to {mode} mode")
            return True
        else:
            logger.error(f"Invalid mode: {mode}")
            return False
    
    def switch_model(self, model_name: str) -> bool:
        """
        Switch to a different model.
        
        Args:
            model_name: Name/path of the model to switch to
            
        Returns:
            True if successful
        """
        if self.provider == "airllm":
            success = self.llm.switch_model(model_name)
        else:  # ollama
            success = self.llm.set_model(model_name)
        
        if success:
            self.model = model_name
            logger.info(f"Switched to model: {model_name}")
        return success
    
    def analyze_entry_signal(
        self,
        market_data: Dict[str, Any],
        custom_context: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze market data to generate entry signal using LLM.
        
        Args:
            market_data: Dictionary containing market information
            custom_context: Additional context for the LLM
            
        Returns:
            Dictionary with entry signal analysis
        """
        logger.info("Analyzing entry signal using LLM...")
        
        # Prepare market data for LLM
        enriched_data = {
            "analysis_type": "entry",
            "trading_mode": self.mode,
            "risk_tolerance": self.current_settings["risk_tolerance"],
            "confidence_threshold": self.current_settings["confidence_threshold"],
            "target_risk_reward": self.current_settings["risk_reward_ratio"],
            "timestamp": datetime.now().isoformat(),
            "market_data": market_data
        }
        
        if custom_context:
            enriched_data["custom_context"] = custom_context
        
        # Get LLM analysis
        analysis = self.llm.analyze_trading_data(enriched_data, "entry")
        
        if analysis:
            # Validate and enhance analysis
            analysis = self._validate_entry_analysis(analysis)
            logger.info(f"Entry signal generated: {analysis.get('signal')} with confidence {analysis.get('confidence')}%")
            return analysis
        else:
            logger.error("Failed to generate entry signal")
            return None
    
    def evaluate_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a trade setup for execution (SPEED OPTIMIZED - Compact JSON).
        
        Args:
            trade: Trade dictionary with symbol, direction, strike, spot, etc.
            
        Returns:
            Dictionary with decision ("TAKE" or "SKIP") and reason
        """
        try:
            # COMPACT JSON PAYLOAD - Only essential metrics for speed
            # This reduces LLM latency to <1.5 seconds
            # Calculate distance from key level (support/resistance)
            spot = trade.get("spot", 0)
            strike = trade.get("strike", 0)
            distance_from_key_level = abs(spot - strike) if spot and strike else 0
            
            compact_payload = {
                "symbol": trade.get("symbol", ""),
                "direction": trade.get("direction", ""),
                "spot_vs_vwap": "above" if spot > trade.get("vwap", 0) else "below",
                "oi_bias": trade.get("market_data", {}).get("oi_type", "balanced"),
                "ranking": trade.get("ranking_score", 0),
                "confidence_threshold": self.current_settings["confidence_threshold"],
                "distance_from_key_level": distance_from_key_level
            }
            
            logger.info(f"🚀 Compact LLM payload: {compact_payload}")
            
            # Use compact analysis
            analysis = self._compact_analyze(compact_payload)
            
            if analysis:
                return analysis
            else:
                # SAFE FALLBACK: REJECT trade if LLM fails
                logger.warning("⚠️ LLM timeout/failure - SAFE DEFAULT: REJECT TRADE")
                return {
                    "decision": "SKIP",  # SAFE DEFAULT - REJECT when LLM fails
                    "reason": "[SAFE_DEFAULT] LLM timeout - REJECTING trade (safety first)",
                    "confidence": 0,
                    "source": "SAFE_DEFAULT"
                }
        except Exception as e:
            logger.error(f"Error evaluating trade: {e}")
            # SAFE FALLBACK: REJECT trade on error
            logger.warning("⚠️ LLM error - SAFE DEFAULT: REJECT TRADE")
            return {
                "decision": "SKIP",  # SAFE DEFAULT - REJECT when error occurs
                "reason": f"[SAFE_DEFAULT] LLM error: {str(e)} - REJECTING trade (safety first)",
                "confidence": 0,
                "source": "SAFE_DEFAULT"
            }
    
    def _compact_analyze(self, compact_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Binary LLM analysis with strict confluence evaluation.
        Uses YES/NO classification with absolute confluence rules.
        
        Args:
            compact_payload: Compact JSON with only essential metrics
            
        Returns:
            Dictionary with decision or None if timeout
        """
        try:
            # Extract required fields for confluence evaluation
            symbol = compact_payload.get('symbol', 'UNKNOWN')
            direction = compact_payload.get('direction', 'UNKNOWN')
            oi_bias = compact_payload.get('oi_bias', 'balanced')
            spot_vs_vwap = compact_payload.get('spot_vs_vwap', 'unknown')
            distance_from_key_level = compact_payload.get('distance_from_key_level', 'unknown')
            
            # Build strict confluence evaluation prompt (optimized for TinyLlama)
            prompt = f"""You are a strict algorithmic trading gatekeeper. 
Evaluate the incoming technical setup data and respond with JSON only.

Evaluation Rules:
- Say YES if and only if there is absolute confluence: (Direction matches OI Bias) AND (Spot position aligns with VWAP trend) AND (Price is near a major Support/Resistance boundary).
- Say NO if there is any mismatch, missing data, flat bias, or low-probability setup.

Input Data:
{{
  "Symbol": "{symbol}",
  "Trade_Direction": "{direction}",
  "OI_Bias": "{oi_bias}",
  "Spot_vs_VWAP": "{spot_vs_vwap}",
  "Distance_From_Key_Level": "{distance_from_key_level} points"
}}

Respond with ONLY this JSON format (no other text):
{{"decision": "YES" or "NO", "reason": "brief explanation"}}"""
            
            logger.info("🚀 Sending binary confluence LLM request (10.0-second timeout)...")
            
            # Call Ollama with strict binary parameters
            response = self.llm.generate(
                prompt=prompt,
                model=self.model,
                timeout=10.0,  # Increased to 10.0 seconds for Ollama response time
                fast_mode=True,
                max_tokens=50,  # Increased to allow JSON response
                format="json",  # Force JSON output for speed
                temperature=0.0,  # LOCKED temperature for deterministic output
                stop=["\n"]  # STOP sequence to prevent extra text
            )
            
            if response:
                # Parse JSON response
                try:
                    # Try to extract JSON from response
                    import json
                    clean_response = response.strip()
                    
                    # Find JSON in response (handle TinyLlama's extra text)
                    start_idx = clean_response.find('{')
                    end_idx = clean_response.rfind('}') + 1
                    
                    if start_idx != -1 and end_idx > start_idx:
                        json_str = clean_response[start_idx:end_idx]
                        parsed = json.loads(json_str)
                        
                        decision = parsed.get('decision', 'NO').upper()
                        reason = parsed.get('reason', 'No reason provided')
                        
                        if decision == "YES":
                            logger.info(f"✅ Binary confluence LLM response: YES - {reason}")
                            return {
                                "decision": "TAKE",
                                "reason": f"Binary confluence classifier: YES - {reason}",
                                "confidence": 95,
                                "source": "BINARY_CONFLUENCE_CLASSIFIER"
                            }
                        else:
                            logger.info(f"❌ Binary confluence LLM response: {decision} - {reason}")
                            return {
                                "decision": "SKIP",
                                "reason": f"Binary confluence classifier: {decision} - {reason}",
                                "confidence": 5,
                                "source": "BINARY_CONFLUENCE_CLASSIFIER"
                            }
                    else:
                        # Fallback to simple text parsing
                        if "YES" in clean_response.upper():
                            logger.info(f"✅ Binary confluence LLM response: YES (text fallback)")
                            return {
                                "decision": "TAKE",
                                "reason": "Binary confluence classifier: YES (text fallback)",
                                "confidence": 90,
                                "source": "BINARY_CONFLUENCE_CLASSIFIER"
                            }
                        else:
                            logger.info(f"❌ Binary confluence LLM response: NO (text fallback)")
                            return {
                                "decision": "SKIP",
                                "reason": "Binary confluence classifier: NO (text fallback)",
                                "confidence": 5,
                                "source": "BINARY_CONFLUENCE_CLASSIFIER"
                            }
                            
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ JSON parse error: {e}, using text fallback")
                    # Fallback to text parsing
                    clean_response = response.strip()
                    if "YES" in clean_response.upper():
                        return {
                            "decision": "TAKE",
                            "reason": "Binary confluence classifier: YES (parse fallback)",
                            "confidence": 85,
                            "source": "BINARY_CONFLUENCE_CLASSIFIER"
                        }
                    else:
                        return {
                            "decision": "SKIP",
                            "reason": "Binary confluence classifier: NO (parse fallback)",
                            "confidence": 5,
                            "source": "BINARY_CONFLUENCE_CLASSIFIER"
                        }
            else:
                logger.warning("⚠️ LLM no response - SAFE DEFAULT: REJECT TRADE")
                return {
                    "decision": "SKIP",  # SAFE DEFAULT - REJECT when LLM fails
                    "reason": "[SAFE_DEFAULT] LLM timeout - REJECTING trade (safety first)",
                    "confidence": 0,
                    "source": "SAFE_DEFAULT"
                }
                
        except Exception as e:
            logger.warning(f"⚠️ LLM timeout/error ({str(e)}) - SAFE DEFAULT: REJECT TRADE")
            return {
                "decision": "SKIP",  # SAFE DEFAULT - REJECT when error occurs
                "reason": f"[SAFE_DEFAULT] LLM error: {str(e)} - REJECTING trade (safety first)",
                "confidence": 0,
                "source": "SAFE_DEFAULT"
            }
    
    
    def analyze_exit_signal(
        self,
        market_data: Dict[str, Any],
        position_info: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze market data to generate exit signal using LLM.
        
        Args:
            market_data: Dictionary containing market information
            position_info: Current position information (entry price, quantity, etc.)
            
        Returns:
            Dictionary with exit signal analysis
        """
        logger.info("Analyzing exit signal using LLM...")
        
        # Prepare data for LLM
        enriched_data = {
            "analysis_type": "exit",
            "trading_mode": self.mode,
            "risk_tolerance": self.current_settings["risk_tolerance"],
            "timestamp": datetime.now().isoformat(),
            "market_data": market_data
        }
        
        if position_info:
            enriched_data["position_info"] = position_info
        
        # Get LLM analysis
        analysis = self.llm.analyze_trading_data(enriched_data, "exit")
        
        if analysis:
            analysis = self._validate_exit_analysis(analysis)
            logger.info(f"Exit signal generated: {analysis.get('action')} with confidence {analysis.get('confidence')}%")
            return analysis
        else:
            logger.error("Failed to generate exit signal")
            return None
    
    def analyze_market_state(
        self,
        market_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze overall market state and sentiment.
        
        Args:
            market_data: Dictionary containing market information
            
        Returns:
            Dictionary with market state analysis
        """
        logger.info("Analyzing market state using LLM...")
        
        enriched_data = {
            "analysis_type": "general",
            "timestamp": datetime.now().isoformat(),
            "market_data": market_data
        }
        
        analysis = self.llm.analyze_trading_data(enriched_data, "general")
        
        if analysis:
            logger.info(f"Market state: {analysis.get('trend')}, sentiment: {analysis.get('overall_sentiment')}")
            return analysis
        else:
            logger.error("Failed to analyze market state")
            return None
    
    def get_trading_recommendation(
        self,
        market_data: Dict[str, Any],
        position_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive trading recommendation based on current state.
        
        Args:
            market_data: Current market data
            position_info: Optional position information
            
        Returns:
            Complete trading recommendation
        """
        logger.info("Generating comprehensive trading recommendation...")
        
        # Analyze market state
        market_state = self.analyze_market_state(market_data)
        
        # Determine if we need entry or exit analysis
        if position_info and position_info.get("active_position"):
            # Exit analysis for existing position
            exit_analysis = self.analyze_exit_signal(market_data, position_info)
            recommendation = {
                "type": "exit",
                "market_state": market_state,
                "exit_analysis": exit_analysis,
                "timestamp": datetime.now().isoformat()
            }
        else:
            # Entry analysis for new position
            entry_analysis = self.analyze_entry_signal(market_data)
            recommendation = {
                "type": "entry",
                "market_state": market_state,
                "entry_analysis": entry_analysis,
                "timestamp": datetime.now().isoformat()
            }
        
        return recommendation
    
    def _validate_entry_analysis(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize entry analysis from professional trading LLM with new JSON API format."""
        # Handle new JSON API format with enhanced analysis fields
        if "decision" in analysis and "oi_analysis" in analysis:
            # New JSON API format - already structured
            decision = analysis.get("decision", "SKIP")
            confidence = analysis.get("confidence", 0)
            score = analysis.get("score", 5)

            # Build comprehensive reason from analysis fields
            reason_parts = []
            
            # Handle both OptionStar and legacy field names
            if "risk_reward_check" in analysis:
                # New OptionStar format with BOT-calculated levels
                reason_parts.append(f"R/R: {analysis.get('risk_reward_check', 'N/A')}")
                reason_parts.append(f"Entry: {analysis.get('entry_validation', 'N/A')}")
                reason_parts.append(f"SL: {analysis.get('stoploss_check', 'N/A')}")
                reason_parts.append(f"Target: {analysis.get('target_feasibility', 'N/A')}")
                reason_parts.append(f"Reason: {analysis.get('final_reason', 'N/A')}")
            elif "direction_check" in analysis:
                # Legacy OptionStar format
                reason_parts.append(f"Direction: {analysis.get('direction_check', 'N/A')}")
                reason_parts.append(f"VWAP: {analysis.get('vwap_analysis', 'N/A')}")
                reason_parts.append(f"Strike: {analysis.get('strike_analysis', 'N/A')}")
                reason_parts.append(f"S/R: {analysis.get('support_resistance_check', 'N/A')}")
                reason_parts.append(f"Reason: {analysis.get('final_reason', 'N/A')}")
            else:
                # Legacy format
                reason_parts.append(f"OI: {analysis.get('oi_analysis', 'N/A')}")
                reason_parts.append(f"VIX: {analysis.get('vix_condition', 'N/A')}")
                reason_parts.append(f"Delta: {analysis.get('delta_check', 'N/A')}")
                reason_parts.append(f"Trap: {analysis.get('trap_status', 'N/A')}")
                reason_parts.append(f"Reason: {analysis.get('reason', analysis.get('final_reason', 'N/A'))}")

            # Convert to standard format
            standardized = {
                "signal": analysis.get("signal", "HOLD"),
                "confidence": confidence,
                "reason": " | ".join(reason_parts),
                "decision": decision,
                "score": score,
                "oi_analysis": analysis.get('oi_analysis', analysis.get('direction_check', 'N/A')),
                "vix_condition": analysis.get('vix_condition', analysis.get('vwap_analysis', 'N/A')),
                "delta_check": analysis.get('delta_check', analysis.get('strike_analysis', 'N/A')),
                "trap_status": analysis.get('trap_status', analysis.get('support_resistance_check', 'N/A')),
                "raw_analysis": analysis  # Keep raw analysis for debugging
            }

            analysis = standardized

        # Handle legacy professional prompt format
        elif "decision" in analysis and "direction" in analysis:
            # Convert professional format to standard format
            decision = analysis.get("decision", "SKIP")
            direction = analysis.get("direction", "HOLD")
            confidence = analysis.get("confidence", 0)
            analysis_details = analysis.get("analysis", {})

            # Map decision to signal
            if decision == "TAKE":
                if "BUY" in direction.upper():
                    signal = "BUY"
                elif "SELL" in direction.upper():
                    signal = "SELL"
                else:
                    signal = "HOLD"
            else:
                signal = "HOLD"

            # Build reason from analysis details
            reason_parts = []
            if analysis_details:
                reason_parts.append(f"OI: {analysis_details.get('oi_interpretation', 'N/A')}")
                reason_parts.append(f"VIX: {analysis_details.get('vix_condition', 'N/A')}")
                reason_parts.append(f"Delta: {analysis_details.get('delta_check', 'N/A')}")
                reason_parts.append(f"Trap: {analysis_details.get('trap_status', 'N/A')}")
                reason_parts.append(f"Reason: {analysis_details.get('final_reason', 'N/A')}")

            # Convert to standard format
            standardized = {
                "signal": signal,
                "confidence": confidence,
                "reason": " | ".join(reason_parts) if reason_parts else analysis.get("reason", "No reason provided"),
                "entry_level": analysis.get("entry", 0),
                "stop_loss": analysis.get("stop_loss", 0),
                "target": analysis.get("target", 0),
                "direction": direction,
                "raw_analysis": analysis  # Keep raw analysis for debugging
            }

            analysis = standardized

        # Ensure required fields exist (for backward compatibility)
        required_fields = ["signal", "confidence", "reason"]
        for field in required_fields:
            if field not in analysis:
                analysis[field] = "UNKNOWN" if field == "signal" or field == "reason" else 0

        # Validate confidence is within range
        try:
            analysis["confidence"] = max(0, min(100, int(analysis["confidence"])))
        except (ValueError, TypeError):
            analysis["confidence"] = 0

        # Validate signal
        valid_signals = ["BUY", "SELL", "HOLD", "BUY_CALL", "BUY_PUT"]
        if analysis["signal"] not in valid_signals:
            analysis["signal"] = "HOLD"

        # Apply mode-based confidence threshold
        if analysis["confidence"] < self.current_settings["confidence_threshold"]:
            analysis["signal"] = "HOLD"
            original_reason = analysis.get("reason", "")
            analysis["reason"] = f"Confidence {analysis['confidence']}% below threshold {self.current_settings['confidence_threshold']}%. {original_reason}"

        return analysis
    
    def _validate_exit_analysis(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize exit analysis from LLM."""
        required_fields = ["action", "confidence", "reason"]
        for field in required_fields:
            if field not in analysis:
                analysis[field] = "UNKNOWN" if field == "action" or field == "reason" else 0
        
        try:
            analysis["confidence"] = max(0, min(100, int(analysis["confidence"])))
        except (ValueError, TypeError):
            analysis["confidence"] = 0
        
        valid_actions = ["EXIT_NOW", "EXIT_SOON", "HOLD", "PARTIAL_BOOK"]
        if analysis["action"] not in valid_actions:
            analysis["action"] = "HOLD"
        
        return analysis
    
    def chat_with_analyst(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Optional[str]:
        """
        Have a conversation with the AI trading analyst.
        
        Args:
            user_message: User's question or message
            conversation_history: Previous conversation context
            
        Returns:
            AI response
        """
        system_prompt = f"""You are an expert trading analyst for Indian markets (NIFTY, BANKNIFTY).
Current trading mode: {self.mode}
Risk tolerance: {self.current_settings['risk_tolerance']}
Target risk-reward ratio: {self.current_settings['risk_reward_ratio']}

Provide clear, actionable trading advice. Focus on risk management and realistic expectations.
Be specific about entry/exit levels, stop losses, and targets."""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        if conversation_history:
            messages.extend(conversation_history)
        
        messages.append({"role": "user", "content": user_message})
        
        # Use generate_chat for ollama, fallback to generate for other providers
        if self.provider == "ollama" and hasattr(self.llm, 'generate_chat'):
            response = self.llm.generate_chat(messages, temperature=0.7)
        else:
            # For other providers, combine messages into a single prompt
            combined_prompt = ""
            for msg in messages:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                combined_prompt += f"{role.upper()}: {content}\n"
            response = self.llm.generate(combined_prompt, temperature=0.7)
        return response


# Convenience functions
def create_analyzer(
    provider: str = "ollama",
    ollama_url: str = "http://localhost:11434",
    model: str = "mistral:7b",
    mode: str = "conservative",
    airllm_config: Optional[Dict[str, Any]] = None
) -> LLMMarketAnalyzer:
    """Create and return an LLM market analyzer."""
    return LLMMarketAnalyzer(provider, ollama_url, model, mode, airllm_config=airllm_config)


def quick_entry_analysis(market_data: Dict[str, Any], provider: str = "ollama") -> Optional[Dict[str, Any]]:
    """Quick entry analysis with default settings."""
    analyzer = create_analyzer(provider=provider)
    return analyzer.analyze_entry_signal(market_data)


def quick_exit_analysis(market_data: Dict[str, Any], position_info: Dict[str, Any], provider: str = "ollama") -> Optional[Dict[str, Any]]:
    """Quick exit analysis with default settings."""
    analyzer = create_analyzer(provider=provider)
    return analyzer.analyze_exit_signal(market_data, position_info)


if __name__ == "__main__":
    # Test the LLM analyzer
    print("Testing LLM Market Analyzer...")
    
    analyzer = LLMMarketAnalyzer(mode="moderate")
    
    # Test entry analysis
    print("\nTesting Entry Analysis...")
    test_market_data = {
        "symbol": "NIFTY",
        "current_price": 23600,
        "resistance_levels": [23650, 23700, 23750],
        "support_levels": [23550, 23500, 23450],
        "price_history": [23580, 23590, 23600, 23605, 23600],
        "volume": "high",
        "time": "14:30"
    }
    
    entry_result = analyzer.analyze_entry_signal(test_market_data)
    if entry_result:
        print("Entry Analysis Result:")
        print(json.dumps(entry_result, indent=2))
    
    # Test exit analysis
    print("\nTesting Exit Analysis...")
    test_position = {
        "active_position": True,
        "entry_price": 23600,
        "option_type": "CE",
        "quantity": 65,
        "entry_premium": 124
    }
    
    exit_result = analyzer.analyze_exit_signal(test_market_data, test_position)
    if exit_result:
        print("Exit Analysis Result:")
        print(json.dumps(exit_result, indent=2))
    
    # Test mode switching
    print("\nTesting Mode Switching...")
    analyzer.switch_mode("aggressive")
    print(f"Current mode: {analyzer.mode}")
    print(f"Current settings: {analyzer.current_settings}")
    
    # Test model switching
    print("\nTesting Model Switching...")
    available_models = analyzer.ollama.list_models()
    if available_models:
        print(f"Available models: {available_models}")
        if len(available_models) > 1:
            analyzer.switch_model(available_models[1])
            print(f"Switched to: {analyzer.model}")
import requests
import json
import logging
import time
import os
from typing import Optional, Dict, Any, List
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class OllamaIntegration:
    """
    Integration with Ollama for local LLM inference.
    Supports multiple models and easy switching between them.
    """

    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "tinyllama:latest", prompt_file: str = "utils/trading_prompt.txt", fast_mode: bool = False):
        """
        Initialize Ollama integration.

        Args:
            base_url: Ollama API base URL (default: http://localhost:11434)
            default_model: Default model to use (default: tinyllama:latest)
            prompt_file: Path to strict trading prompt file (default: utils/trading_prompt.txt)
            fast_mode: If True, use compact prompt for faster responses (default: False)
        """
        self.base_url = base_url.rstrip('/')
        self.default_model = default_model
        self.current_model = default_model
        self.prompt_file = prompt_file
        self.fast_mode = fast_mode  # Fast mode for quick validation
        # Don't use persistent Session to avoid memory accumulation
        self.session = None
        self.headers = {
            'Content-Type': 'application/json'
        }

        # Load strict trading prompt
        self.strict_prompt = self._load_strict_prompt()

        # Verify Ollama is running (non-blocking, just logs warning if fails)
        self.connection_ok = self._check_connection()

    def _check_connection(self, max_retries: int = 2, retry_delay: float = 1.0) -> bool:
        """Check if Ollama server is running and accessible with retry logic."""
        for attempt in range(max_retries):
            try:
                response = requests.get(f"{self.base_url}/api/tags", headers=self.headers, timeout=3)
                if response.status_code == 200:
                    logger.info(f"✓ Connected to Ollama at {self.base_url}")
                    return True
                else:
                    logger.warning(f"Ollama responded with status {response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
            except requests.exceptions.Timeout:
                logger.warning(f"Connection timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        logger.error(f"✗ Cannot connect to Ollama at {self.base_url} after {max_retries} attempts")
        logger.error("Make sure Ollama is running: 'ollama serve'")
        return False

    def _load_strict_prompt(self) -> str:
        """Load strict trading decision prompt from file."""
        try:
            # Use fast prompt if fast_mode is enabled
            if self.fast_mode:
                fast_prompt_file = "utils/trading_prompt_fast.txt"
                if os.path.exists(fast_prompt_file):
                    with open(fast_prompt_file, 'r') as f:
                        prompt = f.read()
                    logger.info(f"✓ Loaded fast trading prompt from {fast_prompt_file}")
                    return prompt
            
            # Default to detailed prompt
            with open(self.prompt_file, 'r') as f:
                prompt = f.read()
            logger.info(f"✓ Loaded strict trading prompt from {self.prompt_file}")
            return prompt
        except Exception as e:
            logger.warning(f"Could not load prompt file {self.prompt_file}: {e}")
            logger.warning("Using default prompt")
            return "You are a trading decision engine. Analyze data and return TAKE or SKIP."

    def list_models(self) -> List[str]:
        """List all available models in Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", headers=self.headers, timeout=5)  # Reduced from 10 to 5
            if response.status_code == 200:
                data = response.json()
                models = [model['name'] for model in data.get('models', [])]
                logger.info(f"Available models: {models}")
                return models
            else:
                logger.error(f"Failed to list models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []

    def set_model(self, model_name: str) -> bool:
        """
        Switch to a different model.

        Args:
            model_name: Name of the model to switch to

        Returns:
            True if successful, False otherwise
        """
        available_models = self.list_models()
        if model_name in available_models:
            self.current_model = model_name
            logger.info(f"✓ Switched to model: {model_name}")
            return True
        else:
            logger.error(f"Model '{model_name}' not found. Available: {available_models}")
            return False

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        format: Optional[str] = None,
        fast_mode: bool = False,
        timeout: float = 120.0,  # Default 120s timeout, can be overridden
        stop: Optional[List[str]] = None  # Stop sequence to prevent extra text
    ) -> Optional[str]:
        """
        Generate text using Ollama.

        Args:
            prompt: The input prompt
            model: Model to use (overrides current_model if provided)
            temperature: Sampling temperature (0.0 - 1.0)
            max_tokens: Maximum tokens to generate
            system_prompt: System prompt to guide the model
            format: Output format ('json' for JSON output)
            fast_mode: If True, use ultra-fast settings (num_predict=5, temp=0.1)
            timeout: Request timeout in seconds (strict timeout for speed)
            stop: Stop sequence to prevent extra text generation

        Returns:
            Generated text or None if error
        """
        model_to_use = model or self.current_model

        # Fast mode: ultra-fast settings for instant responses
        if fast_mode:
            temperature = 0.1
            max_tokens = 256  # Increased to 256 for complete JSON response without cutoff
        
        payload = {
            "model": model_to_use,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "keep_alive": -1  # Keep model warm in memory to prevent timeout
            }
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        if system_prompt:
            payload["system"] = system_prompt

        if format:
            payload["format"] = format
        
        if stop:
            payload["options"]["stop"] = stop

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                headers=self.headers,
                timeout=timeout  # Use the provided timeout parameter
            )

            if response.status_code == 200:
                data = response.json()
                result = data.get('response', '')
                logger.info(f"✓ Generated response using {model_to_use}")
                # Explicitly clean up response to free memory
                del response
                return result
            else:
                logger.error(f"Generation failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error generating text: {e}")
            return None

    def generate_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        format: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate text using chat API with conversation history.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            format: Output format ('json' for JSON output)

        Returns:
            Generated text or None if error
        """
        model_to_use = model or self.current_model

        payload = {
            "model": model_to_use,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        if format:
            payload["format"] = format

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers=self.headers,
                timeout=120  # Increased to handle longer inference times
            )

            if response.status_code == 200:
                data = response.json()
                result = data.get('message', {}).get('content', '')
                logger.info(f"✓ Chat response generated using {model_to_use}")
                # Explicitly clean up response to free memory
                del response
                return result
            else:
                logger.error(f"Chat generation failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error in chat generation: {e}")
            return None

    def analyze_trading_data(
        self,
        market_data: Dict[str, Any],
        analysis_type: str = "general"
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze trading data using LLM with strict trading decision engine prompt.

        Args:
            market_data: Dictionary containing market data with keys:
                        - spot, vix, symbol, oi_type, delta, price_change, oi_change, trap_detected,
                          momentum, volatility_ratio, price_history_count, current_vs_avg
            analysis_type: Type of analysis ('entry', 'exit', 'general')

        Returns:
            Dictionary with analysis results or None if error
        """
        # Use strict trading decision prompt
        system_prompt = self.strict_prompt

        # Extract trading data - handle both OptionStar and legacy formats
        # OptionStar format with BOT-calculated levels
        if "direction" in market_data and "strike" in market_data and "entry" in market_data:
            direction = market_data.get("direction", "N/A")
            strike = market_data.get("strike", "N/A")
            entry = market_data.get("entry", "N/A")
            target = market_data.get("target", "N/A")
            stoploss = market_data.get("stoploss", "N/A")
            action = market_data.get("action", "N/A")
            
            vwap = market_data.get("vwap", "N/A")
            support = market_data.get("support", "N/A")
            resistance = market_data.get("resistance", "N/A")
            optionstar_reason = market_data.get("optionstar_reason", "N/A")
            
            spot = market_data.get("spot", "N/A")
            symbol = market_data.get("symbol", "N/A")
            
            # Use OptionStar structured prompt format with BOT-calculated levels
            if analysis_type == "entry":
                # OPTIMIZED: Compact JSON response with increased token budget
                prompt = f"""DIR: {direction} STRIKE: {strike} ENTRY: {entry} TARGET: {target} SL: {stoploss}
SPOT: {spot} VWAP: {vwap} SUP: {support} RES: {resistance}
REASON: {optionstar_reason}

Return JSON: {{"decision": "TAKE" or "SKIP", "reason": "brief"}}"""
                response = self.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.1,  # Lower temperature for deterministic responses
                    fast_mode=True  # Enable ultra-fast mode for instant responses
                )
        else:
            # Legacy format (backward compatibility)
            spot = market_data.get("spot", "N/A")
            vix = market_data.get("vix", "N/A")
            symbol = market_data.get("symbol", "N/A")
            oi_type = market_data.get("oi_type", "N/A")
            delta = market_data.get("delta", "N/A")
            price_change = market_data.get("price_change", "N/A")
            trap_detected = market_data.get("trap_detected", "no")
            momentum = market_data.get("momentum", "NEUTRAL")
            volatility_ratio = market_data.get("volatility_ratio", "N/A")

            # Use legacy structured prompt format
            if analysis_type == "entry":
                # OPTIMIZED: Compact JSON response with increased token budget
                prompt = f"""SYM: {symbol} SPOT: {spot} OI: {oi_type} DELTA: {delta} VIX: {vix}
PRICE: {price_change} TRAP: {trap_detected} MOM: {momentum} VOL: {volatility_ratio}

Return JSON: {{"decision": "TAKE" or "SKIP", "reason": "brief"}}"""
                response = self.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.1,  # Lower temperature for deterministic responses
                    fast_mode=True  # Enable ultra-fast mode for instant responses
                )

            if response:
                try:
                    # Parse JSON response (standard format)
                    import json
                    result = json.loads(response.strip())

                    # Validate and extract fields with strict validation
                    score = self._validate_int(result.get('score', 5), 1, 10)
                    decision = self._validate_decision(result.get('decision', 'SKIP'))
                    confidence = self._validate_int(result.get('confidence', score * 10), 1, 100)

                    # Extract analysis fields - handle both OptionStar and legacy formats
                    if "risk_reward_check" in result:
                        # New OptionStar format with BOT-calculated levels
                        risk_reward_check = result.get('risk_reward_check', 'N/A')
                        entry_validation = result.get('entry_validation', 'N/A')
                        stoploss_check = result.get('stoploss_check', 'N/A')
                        target_feasibility = result.get('target_feasibility', 'N/A')
                        final_reason = result.get('final_reason', 'No reason provided')
                        
                        # Map to standard field names for consistency
                        oi_analysis = risk_reward_check
                        vix_condition = entry_validation
                        delta_check = stoploss_check
                        trap_status = target_feasibility
                    elif "direction_check" in result:
                        # Legacy OptionStar format
                        direction_check = result.get('direction_check', 'N/A')
                        vwap_analysis = result.get('vwap_analysis', 'N/A')
                        strike_analysis = result.get('strike_analysis', 'N/A')
                        support_resistance_check = result.get('support_resistance_check', 'N/A')
                        final_reason = result.get('final_reason', 'No reason provided')
                        
                        # Map to standard field names for consistency
                        oi_analysis = direction_check
                        vix_condition = vwap_analysis
                        delta_check = strike_analysis
                        trap_status = support_resistance_check
                    else:
                        # Legacy format
                        oi_analysis = result.get('oi_analysis', 'N/A')
                        vix_condition = result.get('vix_condition', 'N/A')
                        delta_check = result.get('delta_check', 'N/A')
                        trap_status = result.get('trap_status', 'N/A')
                        final_reason = result.get('final_reason', 'No reason provided')

                    # Convert to trading signal format
                    if decision == "TAKE" and score >= 7:
                        signal = "BUY"
                    else:
                        signal = "HOLD"

                    logger.info(f"API Decision: Score={score}, Decision={decision}, Confidence={confidence}%, Signal={signal}")
                    logger.info(f"Analysis: OI={oi_analysis}, VIX={vix_condition}, Delta={delta_check}, Trap={trap_status}")

                    return {
                        "signal": signal,
                        "confidence": confidence,
                        "reason": final_reason,
                        "decision": decision,
                        "score": score,
                        "oi_analysis": oi_analysis,
                        "vix_condition": vix_condition,
                        "delta_check": delta_check,
                        "trap_status": trap_status
                    }

                except json.JSONDecodeError as e:
                    # Try to extract JSON from response (handle TinyLlama format)
                    logger.warning(f"JSON parse error, attempting extraction: {e}")
                    try:
                        clean_response = response.strip()
                        start_idx = clean_response.find('{')
                        end_idx = clean_response.rfind('}') + 1
                        
                        if start_idx != -1 and end_idx > start_idx:
                            json_str = clean_response[start_idx:end_idx]
                            parsed = json.loads(json_str)
                            
                            # Extract decision from JSON
                            decision = parsed.get('decision', parsed.get('signal', 'HOLD')).upper()
                            
                            # Map decision to signal
                            if decision in ['YES', 'TAKE', 'BUY']:
                                signal = 'BUY'
                                confidence = 85
                            elif decision in ['NO', 'SKIP', 'SELL']:
                                signal = 'HOLD'
                                confidence = 15
                            else:
                                signal = 'HOLD'
                                confidence = 50
                            
                            logger.info(f"Extracted JSON decision: {decision} -> {signal}")
                            
                            return {
                                "signal": signal,
                                "confidence": confidence,
                                "reason": f"Extracted from JSON: {decision}",
                                "decision": decision
                            }
                    except Exception as extract_error:
                        logger.error(f"JSON extraction also failed: {extract_error}")
                    
                    logger.error(f"Raw response: {response}")
                    return self._fallback_decision(market_data)
                except Exception as e:
                    logger.error(f"Error processing LLM response: {e}")
                    return self._fallback_decision(market_data)

        # Fallback for other analysis types
        return None

    def _validate_int(self, value: Any, min_val: int, max_val: int) -> int:
        """Validate and clamp integer values."""
        try:
            int_value = int(value)
            return max(min_val, min(max_val, int_value))
        except (ValueError, TypeError):
            return (min_val + max_val) // 2  # Return middle value as fallback

    def _validate_decision(self, decision: str) -> str:
        """Validate decision field to be only TAKE or SKIP."""
        if isinstance(decision, str):
            decision_upper = decision.upper().strip()
            if decision_upper in ["TAKE", "SKIP"]:
                return decision_upper
        logger.warning(f"Invalid decision '{decision}', defaulting to SKIP")
        return "SKIP"

    def _fallback_decision(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Provide fallback decision when LLM fails."""
        logger.warning("Using fallback decision logic")
        return {
            "signal": "HOLD",
            "confidence": 50,
            "reason": "LLM parsing failed - using fallback logic",
            "decision": "SKIP",
            "score": 5,
            "oi_analysis": "N/A",
            "vix_condition": "N/A",
            "delta_check": "N/A",
            "trap_status": "N/A"
        }

    def get_model_info(self, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get information about a specific model."""
        model_to_use = model or self.current_model

        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": model_to_use},
                headers=self.headers,
                timeout=120
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get model info: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting model info: {e}")
            return None

    def unload_model(self, model: Optional[str] = None) -> bool:
        """
        Unload a model from memory to free up RAM.
        
        Args:
            model: Model to unload (defaults to current model)
            
        Returns:
            True if successful
        """
        model_to_use = model or self.current_model
        
        try:
            # Use Ollama's keep_alive functionality to unload
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model_to_use,
                    "prompt": "",
                    "keep_alive": 0  # Immediately unload after response
                },
                headers=self.headers,
                timeout=120
            )
            
            logger.info(f"✓ Model {model_to_use} unloaded from memory")
            return True
            
        except Exception as e:
            logger.error(f"Error unloading model: {e}")
            return False

    def cleanup(self):
        """Clean up resources and free memory."""
        try:
            # Unload current model from memory
            self.unload_model()
            
            # Clear any cached data
            self.strict_prompt = None
            
            logger.info("✓ Ollama integration cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


# Convenience functions for quick usage
def create_ollama_client(base_url: str = "http://localhost:11434", model: str = "qwen2:7b") -> OllamaIntegration:
    """Create and return an Ollama client."""
    return OllamaIntegration(base_url=base_url, default_model=model)


def quick_analyze(market_data: Dict[str, Any], analysis_type: str = "general") -> Optional[Dict[str, Any]]:
    """Quick analysis with default settings."""
    client = create_ollama_client()
    return client.analyze_trading_data(market_data, analysis_type)


if __name__ == "__main__":
    # Test the integration
    print("Testing Ollama Integration...")

    # Create client
    client = OllamaIntegration()

    # List available models
    print("\nAvailable Models:")
    models = client.list_models()
    for model in models:
        print(f"  - {model}")

    # Use first available model if default is not available
    if models and client.default_model not in models:
        print(f"\nDefault model '{client.default_model}' not available, switching to '{models[0]}'")
        client.set_model(models[0])

    # Test basic generation
    print("\nTesting basic generation...")
    response = client.generate("Say hello in one sentence.")
    print(f"Response: {response}")

    # Test trading analysis
    print("\nTesting trading analysis...")
    test_data = {
        "symbol": "NIFTY",
        "spot": 23600,
        "vix": 15,
        "oi_type": "LONG_BUILDUP",
        "delta": 0.5,
        "price_change": "+0.5%",
        "oi_change": "N/A",
        "trap_detected": "no"
    }

    analysis = client.analyze_trading_data(test_data, "entry")
    if analysis:
        print(f"Analysis Result:")
        print(json.dumps(analysis, indent=2))
    else:
        print("Analysis failed")

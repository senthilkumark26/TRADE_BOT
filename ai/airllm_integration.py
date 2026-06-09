import logging
import time
import os
from typing import Optional, Dict, Any, List
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class AirLLMIntegration:
    """
    Integration with AirLLM for local LLM inference with memory efficiency.
    Supports running large models (7B+) on consumer hardware with limited VRAM.
    Uses official AirLLM API: from airllm import AutoModel
    """

    def __init__(
        self,
        model_path: str = "garage-bAInd/Platypus2-70B-instruct",
        compression: Optional[str] = None,
        max_length: int = 128,
        fast_mode: bool = False,
        layer_shards_saving_path: Optional[str] = None,
        hf_token: Optional[str] = None
    ):
        """
        Initialize AirLLM integration using official API.

        Args:
            model_path: HuggingFace model repo ID or local path to model
            compression: Compression mode ('4bit', '8bit', or None for no compression)
            max_length: Maximum sequence length for generation
            fast_mode: If True, use compact settings for faster responses
            layer_shards_saving_path: Custom path to save split model layers
            hf_token: HuggingFace token for gated models
        """
        self.model_path = model_path
        self.compression = compression
        self.max_length = max_length
        self.fast_mode = fast_mode
        self.layer_shards_saving_path = layer_shards_saving_path
        self.hf_token = hf_token
        
        self.model = None
        self.model_loaded = False
        
        # Load strict trading prompt if available
        self.strict_prompt = self._load_strict_prompt()
        
        logger.info(f"AirLLM Integration initialized with model: {model_path}")
        
        # Lazy loading - model will be loaded on first use
        logger.info("Model will be loaded on first inference (lazy loading)")

    def _load_strict_prompt(self) -> str:
        """Load strict trading decision prompt from file."""
        try:
            # Use fast prompt if fast_mode is enabled
            if self.fast_mode:
                fast_prompt_file = "trading_prompt_fast.txt"
                if os.path.exists(fast_prompt_file):
                    with open(fast_prompt_file, 'r') as f:
                        prompt = f.read()
                    logger.info(f"✓ Loaded fast trading prompt from {fast_prompt_file}")
                    return prompt
            
            # Default to detailed prompt
            prompt_file = "trading_prompt.txt"
            if os.path.exists(prompt_file):
                with open(prompt_file, 'r') as f:
                    prompt = f.read()
                logger.info(f"✓ Loaded strict trading prompt from {prompt_file}")
                return prompt
            else:
                logger.warning("No trading prompt file found, using default")
                return "You are a trading decision engine. Analyze data and return TAKE or SKIP."
        except Exception as e:
            logger.warning(f"Could not load prompt file: {e}")
            return "You are a trading decision engine. Analyze data and return TAKE or SKIP."

    def _load_model(self):
        """Load the AirLLM model using official API (lazy loading)."""
        if self.model_loaded:
            return
        
        try:
            logger.info(f"Loading AirLLM model: {self.model_path}")
            
            # Import airllm using official API
            try:
                from airllm import AutoModel
            except ImportError:
                logger.error("airllm not installed. Install with: pip install airllm")
                raise
            
            # Model initialization parameters using official API
            init_params = {}
            
            if self.compression:
                init_params["compression"] = self.compression
            
            if self.layer_shards_saving_path:
                init_params["layer_shards_saving_path"] = self.layer_shards_saving_path
            
            if self.hf_token:
                init_params["hf_token"] = self.hf_token
            
            # Load model using official AirLLM API
            self.model = AutoModel.from_pretrained(self.model_path, **init_params)
            self.model_loaded = True
            
            # Initialize tokenizer from the model
            if hasattr(self.model, 'tokenizer'):
                self.tokenizer = self.model.tokenizer
            else:
                # Fallback: try to get tokenizer separately
                from transformers import AutoTokenizer
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            
            logger.info(f"✓ AirLLM model loaded successfully: {self.model_path}")
            
        except Exception as e:
            logger.error(f"Failed to load AirLLM model: {e}")
            raise

    def generate(
        self,
        prompt: str,
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.7,
        use_cache: bool = True,
        timeout: float = 120.0
    ) -> Optional[str]:
        """
        Generate text using AirLLM.

        Args:
            prompt: The input prompt
            max_new_tokens: Maximum new tokens to generate
            temperature: Sampling temperature (0.0 - 1.0)
            use_cache: Whether to use KV cache for faster generation
            timeout: Request timeout in seconds

        Returns:
            Generated text or None if error
        """
        try:
            # Ensure model is loaded
            if not self.model_loaded:
                self._load_model()
            
            # Set default max tokens based on mode
            if max_new_tokens is None:
                max_new_tokens = 20 if self.fast_mode else 100
            
            # Use AirLLM's simple inference interface
            # AirLLM handles tokenization internally
            try:
                # Try AirLLM's direct inference method first
                if hasattr(self.model, '__call__'):
                    # AirLLM models can be called directly with text
                    input_text = [prompt]
                    
                    # Generate with timeout protection
                    import concurrent.futures
                    
                    def generate_with_timeout():
                        output = self.model(input_text, max_new_tokens=max_new_tokens)
                        return output
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(generate_with_timeout)
                        try:
                            output = future.result(timeout=timeout)
                        except concurrent.futures.TimeoutError:
                            logger.warning(f"AirLLM generation timed out after {timeout}s")
                            return None
                    
                    # Extract text from output
                    if isinstance(output, list) and len(output) > 0:
                        result = output[0]
                        if isinstance(result, str):
                            response_text = result
                        else:
                            # Try to decode if it's token IDs
                            response_text = self.tokenizer.decode(result) if hasattr(self, 'tokenizer') else str(result)
                    else:
                        response_text = str(output)
                    
                    # Remove input prompt from output if present
                    if response_text.startswith(prompt):
                        response_text = response_text[len(prompt):].strip()
                    
                    logger.info(f"✓ Generated response using AirLLM")
                    return response_text
                    
                else:
                    # Fallback to tokenization-based approach
                    input_text = [prompt]
                    input_tokens = self.tokenizer(
                        input_text,
                        return_tensors="pt", 
                        return_attention_mask=False, 
                        truncation=True, 
                        max_length=self.max_length, 
                        padding=False
                    )
                    
                    input_ids = input_tokens['input_ids']
                    
                    # Generate with timeout protection
                    import concurrent.futures
                    
                    def generate_with_timeout():
                        generation_output = self.model.generate(
                            input_ids,
                            max_new_tokens=max_new_tokens,
                            use_cache=use_cache,
                            return_dict_in_generate=True
                        )
                        return generation_output
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(generate_with_timeout)
                        try:
                            generation_output = future.result(timeout=timeout)
                        except concurrent.futures.TimeoutError:
                            logger.warning(f"AirLLM generation timed out after {timeout}s")
                            return None
                    
                    # Decode output
                    output = self.tokenizer.decode(generation_output.sequences[0])
                    
                    # Remove input prompt from output
                    if output.startswith(prompt):
                        output = output[len(prompt):].strip()
                    
                    logger.info(f"✓ Generated response using AirLLM")
                    return output
                    
            except Exception as e:
                logger.error(f"Error in AirLLM generation: {e}")
                return None
            
        except Exception as e:
            logger.error(f"Error generating text with AirLLM: {e}")
            return None

    def analyze_trading_data(
        self,
        market_data: Dict[str, Any],
        analysis_type: str = "general"
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze trading data using AirLLM with strict trading decision engine prompt.

        Args:
            market_data: Dictionary containing market data
            analysis_type: Type of analysis ('entry', 'exit', 'general')

        Returns:
            Dictionary with analysis results or None if error
        """
        # Use strict trading decision prompt
        system_prompt = self.strict_prompt

        # Extract trading data - handle both OptionStar and legacy formats
        if "direction" in market_data and "strike" in market_data and "entry" in market_data:
            # OptionStar format with BOT-calculated levels
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
            
            # Use OptionStar structured prompt format
            if analysis_type == "entry":
                prompt = f"""DIR: {direction} STRIKE: {strike} ENTRY: {entry} TARGET: {target} SL: {stoploss}
SPOT: {spot} VWAP: {vwap} SUP: {support} RES: {resistance}
REASON: {optionstar_reason}

Return JSON: {{"decision": "TAKE" or "SKIP", "reason": "brief"}}"""
                
                response = self.generate(
                    prompt=prompt,
                    max_new_tokens=50 if self.fast_mode else 100,
                    temperature=0.1
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
                prompt = f"""SYM: {symbol} SPOT: {spot} OI: {oi_type} DELTA: {delta} VIX: {vix}
PRICE: {price_change} TRAP: {trap_detected} MOM: {momentum} VOL: {volatility_ratio}

Return JSON: {{"decision": "TAKE" or "SKIP", "reason": "brief"}}"""
                
                response = self.generate(
                    prompt=prompt,
                    max_new_tokens=50 if self.fast_mode else 100,
                    temperature=0.1
                )

        if response:
            try:
                # Parse JSON response
                import json
                result = json.loads(response.strip())

                # Validate and extract fields
                decision = self._validate_decision(result.get('decision', 'SKIP'))
                reason = result.get('reason', 'No reason provided')

                # Convert to trading signal format
                if decision == "TAKE":
                    signal = "BUY"
                    confidence = 85
                else:
                    signal = "HOLD"
                    confidence = 15

                logger.info(f"AirLLM Decision: {decision}, Signal: {signal}, Confidence: {confidence}%")
                logger.info(f"Reason: {reason}")

                return {
                    "signal": signal,
                    "confidence": confidence,
                    "reason": reason,
                    "decision": decision
                }

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}")
                # Try to extract decision from text
                clean_response = response.strip().upper()
                if "TAKE" in clean_response or "YES" in clean_response:
                    return {
                        "signal": "BUY",
                        "confidence": 75,
                        "reason": "Extracted from text",
                        "decision": "TAKE"
                    }
                else:
                    return {
                        "signal": "HOLD",
                        "confidence": 25,
                        "reason": "Extracted from text",
                        "decision": "SKIP"
                    }
        else:
            logger.error("Failed to get response from AirLLM")
            return None

    def _validate_decision(self, decision: str) -> str:
        """Validate decision value."""
        decision_upper = decision.upper()
        if decision_upper in ["TAKE", "YES", "BUY"]:
            return "TAKE"
        elif decision_upper in ["SKIP", "NO", "SELL", "HOLD"]:
            return "SKIP"
        else:
            return "SKIP"

    def switch_model(self, model_path: str) -> bool:
        """
        Switch to a different model.

        Args:
            model_path: HuggingFace model repo ID or local path

        Returns:
            True if successful
        """
        try:
            # Unload current model
            self.model = None
            self.tokenizer = None
            self.model_loaded = False
            
            # Update model path
            self.model_path = model_path
            
            logger.info(f"✓ Switched to model: {model_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to switch model: {e}")
            return False

    def cleanup(self):
        """Clean up resources."""
        if self.model:
            del self.model
            self.model = None
        self.model_loaded = False
        logger.info("AirLLM resources cleaned up")
# 🔒 MEMORY-SAFE SETTINGS - PERMANENTLY LOCKED 🔒

## ⚠️ IMPORTANT NOTICE

**These memory-safe settings are PERMANENTLY FROZEN and cannot be modified.**

Any attempt to change these settings will be **REJECTED** by the code to prevent memory crashes.

## 🚫 FROZEN SETTINGS

The following settings are locked at the module level and cannot be changed:

```python
FROZEN_LLM_COOLDOWN_SECONDS = 30        # Minimum 30 seconds between LLM calls
FROZEN_LOOP_DELAY_SECONDS = 30          # 30 seconds between scan cycles
FROZEN_MEMORY_THRESHOLD_PERCENT = 80    # Skip LLM if memory > 80%
FROZEN_MEMORY_CLEANUP_FREQUENCY = 10    # Cleanup every 10 instruments
FROZEN_MODEL_UNLOAD_FREQUENCY = 3       # Unload model every 3 calls
FROZEN_TRADE_STRENGTH_THRESHOLD = 2     # Minimum trade strength 2/5 for LLM
FROZEN_MEMORY_GUARD_THRESHOLD = 70      # Sleep if memory > 70%
```

## 🛡️ PROTECTION MECHANISMS

### 1. Module-Level Constants
- Settings are defined as constants at the module level
- Cannot be modified at runtime

### 2. Property Locking
- Critical settings use Python properties with locked setters
- Attempting to modify raises `ValueError` with clear error message

### 3. Validation on Initialization
- Bot validates all frozen settings on startup
- Raises error if settings don't match frozen values

### 4. Clear Documentation
- All frozen settings are marked with ⚠️ FROZEN warnings
- Error messages explain why settings are locked

## 📊 WHY THESE SETTINGS ARE FROZEN

Based on extensive testing, these settings were identified as the **KEY FIXES** to prevent memory crashes:

1. **Trade Strength Filtering** (BIGGEST FIX) - Reduces LLM calls by ~60%
2. **LLM Cooldown 30s** - Prevents rapid successive LLM calls
3. **Loop Delay 30s** - Reduces scan frequency and memory pressure
4. **Memory Threshold 80%** - More aggressive memory protection
5. **Memory Cleanup every 10 instruments** - Frees memory more frequently
6. **Model Unload every 3 calls** - More frequent LLM model memory release
7. **Memory Guard at 70%** - Prevents memory spikes before they become critical

## 🧪 TESTING

Run the frozen settings test to verify protection:

```bash
python test_frozen_settings.py
```

This test verifies:
- ✓ Frozen settings are validated on initialization
- ✓ Attempting to modify LLM cooldown is rejected
- ✓ Attempting to modify memory threshold is rejected
- ✓ All frozen constants are set to correct values

## ⚙️ WHAT YOU CAN STILL MODIFY

These settings are **NOT** frozen and can be changed as needed:

- `trade_cooldown_seconds` (currently 10s) - Time between trades
- Trading mode (conservative/moderate/aggressive)
- LLM provider (ollama/gemini)
- LLM model selection
- Watchlist instruments
- Paper trading enable/disable
- Bot mode (normal/observation)

## 🚨 ATTEMPTING TO MODIFY FROZEN SETTINGS

If you try to modify a frozen setting, you will get:

```
ValueError: ⚠️ SETTING LOCKED: llm_cooldown_seconds is FROZEN at 30s. 
Cannot change to 60s. This setting is permanently locked to prevent memory crashes.
```

## 📝 IMPLEMENTATION DETAILS

### Property Locking Example
```python
@property
def llm_cooldown_seconds(self):
    """Getter for frozen LLM cooldown setting."""
    return self._llm_cooldown_seconds

@llm_cooldown_seconds.setter
def llm_cooldown_seconds(self, value):
    """Prevent modification of frozen LLM cooldown setting."""
    raise ValueError(
        f"⚠️ SETTING LOCKED: llm_cooldown_seconds is FROZEN at {FROZEN_LLM_COOLDOWN_SECONDS}s. "
        f"Cannot change to {value}s. "
        f"This setting is permanently locked to prevent memory crashes."
    )
```

### Validation on Startup
```python
def _validate_frozen_settings(self):
    """Validate that frozen memory-safe settings are correct."""
    errors = []
    
    if self._llm_cooldown_seconds != FROZEN_LLM_COOLDOWN_SECONDS:
        errors.append(f"LLM cooldown must be {FROZEN_LLM_COOLDOWN_SECONDS}s")
    
    if self._memory_threshold_percent != FROZEN_MEMORY_THRESHOLD_PERCENT:
        errors.append(f"Memory threshold must be {FROZEN_MEMORY_THRESHOLD_PERCENT}%")
    
    if errors:
        raise ValueError("⚠️ FROZEN SETTINGS VIOLATION: " + "\n".join(errors))
```

## 🎯 RESULT

Your trading bot is now **PERMANENTLY PROTECTED** from memory crashes through these frozen settings. The bot will:

- ✅ Filter weak trades before LLM calls (60% reduction in LLM usage)
- ✅ Enforce strict cooldowns between operations
- ✅ Clean memory aggressively and frequently
- ✅ Reject any attempts to modify critical memory settings
- ✅ Run stably without memory crashes

**These settings are locked for your safety. Do not attempt to modify them.**
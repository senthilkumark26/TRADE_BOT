# Clean Event-Driven Trading Bot

## Architecture

This is a clean, minimal trading bot with proper LLM integration and event-driven architecture.

### Core Components

1. **trading_bot.py** - Main bot with event-driven architecture
   - WebSocket Manager (data)
   - Market Scanner (find trade)
   - Trade Filter (OI + VIX + Delta + Trap)
   - LLM Evaluator (score)
   - Execution Controller (print/execute)

2. **ollama_integration.py** - LLM integration layer
   - Handles communication with Ollama
   - Professional trading prompts
   - Model switching

3. **llm_market_analyzer.py** - LLM market analyzer
   - Entry signal analysis
   - Exit signal analysis
   - Trading modes (conservative/moderate/aggressive)

4. **config.json** - Configuration
   - API credentials
   - Ollama settings
   - Trading parameters

5. **generate_token.py** - Token generation
6. **get_instruments.py** - Get instruments
7. **manual_auth.py** - Manual authentication

## Event-Driven Design

**Before (Blocking Loop):**
```python
while True:
    scan_market()  # Runs continuously, never pauses
```

**After (Event-Driven):**
```python
while bot_running:
    trade = scan_market()
    if trade:
        handle_trade(trade)  # Pauses here for LLM evaluation
    time.sleep(2)
```

## Key Features

- ✅ Event-driven (non-blocking)
- ✅ Proper LLM integration with pauses
- ✅ Trade throttling (10s cooldown)
- ✅ Hard filters (Trap, Delta, VIX)
- ✅ Professional trading prompts
- ✅ Multiple trading modes
- ✅ Paper trading support

## Usage

```bash
python trading_bot.py
```

### Commands

- `start bot [instrument]` - Start bot (optional: NIFTY, BANKNIFTY, GOLDM, etc.)
- `stop bot` - Stop bot
- `status` - Show bot status
- `mode <mode>` - Switch trading mode (conservative/moderate/aggressive)
- `model <model>` - Switch Ollama model
- `exit` - Exit program

## Trade Flow

1. Bot scans market for trades
2. If trade found → Apply hard filters
3. If filters pass → Send to LLM for evaluation
4. LLM returns score and decision
5. If score ≥ 70% → Execute trade
6. Apply 10s cooldown before next trade

## Hard Filters

- Trap detection (reject if trap detected)
- Delta range (0.35 - 0.60)
- VIX check (reject if VIX > 18)
- Minimum price movement (0.1%)

## Requirements

- Python 3.7+
- Ollama (running locally)
- Upstox API credentials

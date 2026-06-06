# Recommended Services for Code Manager

## Overview

This document lists all recommended services that can be registered with the Code Manager for centralized service management and dependency tracking.

## Service Categories

### 1. LLM Integration Services
Services that integrate with different LLM providers for AI-powered analysis.

#### gemini_integration
- **File**: gemini_integration.py
- **Description**: Gemini LLM integration service for market analysis
- **Dependencies**: None
- **Use Case**: Google Gemini AI for trade evaluation

#### ollama_integration
- **File**: ollama_integration.py
- **Description**: Ollama LLM integration service for local AI models
- **Dependencies**: None
- **Use Case**: Local LLM models for offline analysis

#### openai_integration
- **File**: openai_integration.py
- **Description**: OpenAI LLM integration service for GPT models
- **Dependencies**: None
- **Use Case**: OpenAI GPT for advanced market analysis

---

### 2. LLM Analyzer Services
Services that use LLM for market analysis and trade evaluation.

#### llm_market_analyzer
- **File**: llm_market_analyzer.py
- **Description**: LLM-based market analysis service for trade evaluation
- **Dependencies**: gemini_integration
- **Use Case**: AI-powered trade scoring and evaluation

#### llm_state_worker
- **File**: llm_state_worker.py
- **Description**: LLM state management worker for decoupled LLM operations
- **Dependencies**: llm_market_analyzer
- **Use Case**: Background LLM processing without blocking main thread

#### llm_worker
- **File**: llm_worker.py
- **Description**: LLM worker service for background LLM processing
- **Dependencies**: llm_market_analyzer
- **Use Case**: Async LLM operations for trade analysis

---

### 3. Market Analysis Services
Services that perform technical analysis and signal generation.

#### market_analyzer
- **File**: market_analyzer.py
- **Description**: Market analysis service for technical analysis and signal generation
- **Dependencies**: kite_service
- **Use Case**: Technical indicators and market signals

#### market_signal_analyzer
- **File**: market_signal_analyzer.py
- **Description**: Market signal analysis service for trade signal evaluation
- **Dependencies**: market_analyzer
- **Use Case**: Signal filtering and validation

#### engine1_market_analyzer
- **File**: engine1_market_analyzer.py
- **Description**: Engine 1 market analyzer - Breakout detection and signal generation
- **Dependencies**: kite_service, expiry_manager
- **Use Case**: VWAP breakout detection with PCR filtering

#### engine2_llm_worker
- **File**: engine2_llm_worker.py
- **Description**: Engine 2 LLM worker - LLM-based trade evaluation and scoring
- **Dependencies**: llm_market_analyzer, engine1_market_analyzer
- **Use Case**: AI-powered trade scoring and evaluation

---

### 4. Risk Management Services
Services that manage trading risk and execution safety.

#### execution_risk_manager
- **File**: execution_risk_manager.py
- **Description**: Execution risk management service for trade risk assessment
- **Dependencies**: kite_service
- **Use Case**: Position sizing, stop-loss, and risk calculation

---

### 5. Trade Management Services
Services that manage trade lifecycle and execution.

#### trade_queue_system
- **File**: trade_queue_system.py
- **Description**: Trade queue system for event-driven trade management
- **Dependencies**: llm_market_analyzer
- **Use Case**: Queue-based trade execution with LLM approval

#### trade_memory
- **File**: trade_memory.py
- **Description**: Trade memory service for storing and retrieving trade history
- **Dependencies**: None
- **Use Case**: Trade history and performance tracking

#### trade_pipeline
- **File**: trade_pipeline.py
- **Description**: Trade pipeline service for coordinating trade execution
- **Dependencies**: trade_queue_system
- **Use Case**: End-to-end trade execution pipeline

---

### 6. Simulation Services
Services for testing and simulation.

#### demo_market_simulator
- **File**: demo_market_simulator.py
- **Description**: Demo market simulator for testing without live data
- **Dependencies**: None
- **Use Case**: Paper trading and testing with simulated data

---

### 7. Trading Services
Services that implement specific trading strategies.

#### single_strike_trader
- **File**: single_strike_trader.py
- **Description**: Single strike trading service for focused option trading
- **Dependencies**: kite_service, expiry_manager
- **Use Case**: Single strike option trading strategy

#### streamlit_single_strike_trader
- **File**: streamlit_single_strike_trader.py
- **Description**: Streamlit-based single strike trading UI service
- **Dependencies**: single_strike_trader
- **Use Case**: Web UI for single strike trading

#### web_interface
- **File**: web_interface.py
- **Description**: Web interface service for trading bot monitoring
- **Dependencies**: trading_bot
- **Use Case**: Web dashboard for bot monitoring

---

### 8. Core Trading Bot
Main trading system service.

#### trading_bot
- **File**: trading_bot.py
- **Description**: Main trading bot service - Event-driven trading system
- **Dependencies**: 
  - kite_service
  - expiry_manager
  - llm_market_analyzer
  - engine1_market_analyzer
  - engine2_llm_worker
  - trade_queue_system
- **Use Case**: Complete event-driven trading system

---

## Already Registered Services

These services are already registered with the Code Manager:

### expiry_manager
- **File**: expiry_manager.py
- **Description**: Expiry Auto-Switch Engine - Automatically selects correct trading expiry
- **Dependencies**: None

### kite_service
- **File**: kite_service.py
- **Description**: Kite Service - Centralized KiteConnect integration with rate limiting
- **Dependencies**: None

### code_manager
- **File**: code_manager.py
- **Description**: Code Manager - Code governance system with approval workflow
- **Dependencies**: None

---

## How to Register All Services

### Quick Registration:
```bash
python register_all_services.py
```

### Manual Registration:
```python
from code_manager import code_manager

success, message = code_manager.register_service(
    service_name="my_service",
    service_file="my_service.py",
    description="My custom service",
    version="1.0",
    dependencies=["kite_service", "expiry_manager"]
)
```

---

## Service Dependency Graph

```
trading_bot
├── kite_service
├── expiry_manager
├── llm_market_analyzer
│   └── gemini_integration
├── engine1_market_analyzer
│   ├── kite_service
│   └── expiry_manager
├── engine2_llm_worker
│   ├── llm_market_analyzer
│   └── engine1_market_analyzer
└── trade_queue_system
    └── llm_market_analyzer
```

---

## Benefits of Service Registration

1. **Dependency Tracking**: Know which services depend on which
2. **Version Management**: Track service versions
3. **Centralized Management**: All services in one place
4. **Critical File Protection**: Protect service files from deletion
5. **Audit Trail**: Track service changes
6. **Validation**: Validate dependencies before deployment

---

## Files NOT to Register as Services

### Scripts (Entry Points):
- run_*.py - Entry point scripts
- test_*.py - Test scripts
- check_*.py - Check scripts
- fetch_*.py - Fetch scripts
- get_*.py - Get scripts
- update_*.py - Update scripts

### Utilities:
- diagnose_*.py - Diagnostic utilities
- verify_*.py - Verification utilities
- validate_*.py - Validation utilities
- generate_*.py - Generation utilities
- inject_*.py - Injection utilities
- cleanup_*.py - Cleanup utilities

### One-time Scripts:
- manual_auth.py
- generate_token.py
- generate_zerodha_token.py
- exchange_zerodha_token.py
- exchange_token_sdk.py
- official_sdk_auth.py
- zerodha_integration.py
- zerodha_login_guide.py

These are scripts, not reusable services, and should not be registered.

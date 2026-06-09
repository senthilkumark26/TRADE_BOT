# AI CONTEXT - Trading Bot Project

## 🎯 PROJECT OVERVIEW

**Purpose:** Multi-mode automated trading system for Indian markets (NSE + MCX)
**Current Focus:** MCX Options Trading with Safety Filters
**Architecture:** Modular microservices with risk management

---

## 🏗️ CORE ARCHITECTURE

### **Main Entry Points**
- `main.py` - Unified entry point for all bots
- `mcx_only_bot.py` - MCX-only trading (futures + options)
- `telegram_only_bot.py` - Telegram signal executor
- `bots/trading_bot.py` - Main unified trading bot
- `bots/single_strike_trader.py` - Single strike options trader

### **Key Services**
- `services/trade_manager_service/` - Trade execution & risk management
- `services/token_manager_service/` - Dynamic token management
- `mcx/services/` - MCX signal generation
- `analyzers/` - Market analysis engines
- `kite/` - Kite API wrapper

---

## 🔧 EXISTING INFRASTRUCTURE (DO NOT DUPLICATE)

### **WebSocket Implementation** ✅ ALREADY EXISTS
**Location:** `data_layer/websocket_client.py`
**Features:**
- Real-time market data streaming
- Token Manager integration
- Dynamic instrument loading
- Reconnection logic
- State Manager integration

**DO NOT:** Create new WebSocket implementations
**USE:** `data_layer/websocket_client.py` for any WebSocket needs

### **Options WebSocket** ✅ ALREADY EXISTS
**Location:** `data_layer/options_websocket.py`
**Features:**
- Options-specific WebSocket handling
- Option chain streaming
- Greeks updates

**DO NOT:** Create duplicate options WebSocket code

### **State Management** ✅ ALREADY EXISTS
**Location:** `data_layer/state_manager.py`
**Features:**
- Centralized state storage
- WebSocket data integration
- Price history tracking

**USE:** State Manager for any data storage needs

---

## 📦 MODULE STRUCTURE

### **MCX Module** (`mcx/`)
- `mcx_wrapper.py` - MCX signal generation interface
- `services/service.py` - MCX signal engine
- `mcx_options_safety.py` - MCX options safety filters & strike selectors

### **Kite Module** (`kite/`)
- `kite_client.py` - Kite API wrapper with authentication
- `login_manager.py` - Session management

### **Risk Module** (`risk/`)
- `risk_wrapper.py` - Risk management interface
- Position sizing, stop-loss, daily limits

### **Data Layer** (`data_layer/`)
- `websocket_client.py` - WebSocket infrastructure
- `options_websocket.py` - Options WebSocket
- `state_manager.py` - State management

---

## 🎯 MCX OPTIONS TRADING (CURRENT FOCUS)

### **Configuration**
- **File:** `mcx_only_bot.py`
- **Modes:** `--mode futures` (default) or `--mode options`
- **Instruments:** CRUDEOIL (big contract), NATGAS, GOLDM, SILVERM
- **CRUDEOIL Config:** Lot size 100, strict safety filters

### **Safety Filters** (`mcx/mcx_options_safety.py`)
**CRUDEOIL (Strict Mode):**
- Volume > 200
- OI > 10,000
- Spread < 3%

**Other Commodities (Normal Mode):**
- Volume > 100
- OI > 5,000
- Spread < 5%

### **Strike Selection**
- `select_mcx_option_strike()` - Smart strike selector
- `select_mcx_like_nifty()` - NIFTY-style selector
- ATM preference with liquidity fallback

### **Direction Detection**
- `mcx_direction_module()` - Breakout/breakdown detection
- Sideways market filtering
- Momentum confirmation

---

## 🔐 AUTHENTICATION & CONFIG

### **Config File:** `config.json`
**Critical Settings:**
- `api_key` - Kite API key
- `access_token` - Kite access token
- `paper_trading` - True/False
- `mcx_enabled` - True for MCX trading

### **Authentication Flow**
1. Check login status via `kite/login_manager.py`
2. Refresh token if expired
3. Initialize KiteClient with paper/live mode

---

## 🚫 COMMON PITFALLS TO AVOID

### **1. Rate Limiting**
**Problem:** Too many REST API calls
**Solution:** Use caching + existing WebSocket
**Files:** 
- `mcx/mcx_options_safety.py` (instrument caching)
- `mcx_only_bot.py` (contract caching)

### **2. Code Duplication**
**Problem:** Creating duplicate WebSocket implementations
**Solution:** Use existing `data_layer/websocket_client.py`

### **3. Hardcoded Values**
**Problem:** Magic numbers in code
**Solution:** Use config.json or constants

### **4. Missing Error Handling**
**Problem:** API failures crash system
**Solution:** Try-catch with fallbacks

---

## 📋 CODING STANDARDS

### **File Organization**
- Each module has `__init__.py`
- Services in `services/` directory
- Wrappers in `wrappers/` directory
- Data layer in `data_layer/` directory

### **Naming Conventions**
- Classes: PascalCase (`MCXOnlyBot`)
- Functions: snake_case (`generate_mcx_signals`)
- Constants: UPPER_SNAKE_CASE (`MAX_DAILY_LOSS`)

### **Logging**
- Use `logging` module
- INFO for normal operations
- WARNING for recoverable issues
- ERROR for critical failures
- DEBUG for detailed diagnostics

---

## 🔄 DATA FLOW PATTERNS

### **Signal Generation Flow**
```
Market Data → Analyzer → Signal → Risk Check → Execution → Monitoring
```

### **MCX Options Flow**
```
MCX Futures Price → Direction Module → Strike Selector → Safety Filter → Option Trade
```

### **WebSocket Data Flow**
```
WebSocket → State Manager → Analyzer → Signal Generation
```

---

## 🎯 CURRENT IMPLEMENTATION STATUS

### **✅ Working Components**
- MCX futures trading
- MCX options trading (with safety filters)
- Risk management
- Paper trading mode
- Live trading mode
- Telegram signal execution
- WebSocket infrastructure
- Token management
- State management

### **🚧 Current Focus**
- MCX options optimization
- Strike selection accuracy
- Safety filter tuning
- Rate limiting solutions

---

## 🔧 DEVELOPMENT RULES

### **Before Adding New Code:**
1. **Search existing codebase** - Check if functionality already exists
2. **Use existing infrastructure** - WebSocket, state management, etc.
3. **Follow existing patterns** - Don't reinvent the wheel
4. **Check config.json** - Add settings there instead of hardcoding
5. **Add proper error handling** - Try-catch with fallbacks

### **When Modifying Code:**
1. **Maintain backward compatibility** - Don't break existing features
2. **Update documentation** - Keep this file current
3. **Test thoroughly** - Both paper and live modes
4. **Consider rate limits** - Use caching strategies

### **Code Review Checklist:**
- [ ] No duplicate functionality
- [ ] Uses existing infrastructure
- [ ] Proper error handling
- [ ] Configurable via config.json
- [ ] Follows naming conventions
- [ ] Has appropriate logging
- [ ] Handles rate limiting
- [ ] Maintains backward compatibility

---

## 📚 KEY FILES TO UNDERSTAND

### **Must Read:**
1. `config.json` - Configuration
2. `main.py` - Entry point
3. `mcx_only_bot.py` - MCX trading logic
4. `mcx/mcx_options_safety.py` - Safety filters
5. `data_layer/websocket_client.py` - WebSocket infrastructure

### **Important:**
1. `kite/kite_client.py` - Kite API wrapper
2. `services/trade_manager_service/service.py` - Trade execution
3. `wrappers/risk_wrapper.py` - Risk management
4. `data_layer/state_manager.py` - State management

---

## 🎯 PROJECT GOALS

### **Primary Goals:**
1. Safe automated trading with risk management
2. Multi-asset support (NSE + MCX)
3. Multiple trading modes (futures, options)
4. Professional-grade execution

### **Current Phase:**
- MCX options trading optimization
- Safety filter refinement
- Strike selection accuracy
- Rate limiting solutions

### **Future Phases:**
- WebSocket integration for MCX
- Advanced option strategies
- Machine learning signals
- Portfolio optimization

---

## 🔍 DEBUGGING TIPS

### **Common Issues:**
1. **Rate Limiting:** Check caching strategies, reduce API calls
2. **Authentication:** Check access_token validity
3. **Market Data:** Verify WebSocket connection or REST API status
4. **Signal Generation:** Check analyzer logs for detailed analysis
5. **Execution:** Verify risk limits and paper/live mode

### **Log Analysis:**
- Look for "ERROR" and "WARNING" messages
- Check "MCX DETAILED ANALYSIS" for signal generation details
- Monitor "SKIP" messages for safety filter activity
- Track "WebSocket" status for data feed issues

---

## 📞 CONTACT & SUPPORT

### **For Questions:**
- Check existing codebase first
- Review this AI_CONTEXT.md
- Check AGENTS.md for project-specific rules
- Review docs/ directory for additional documentation

### **Before Making Changes:**
1. Understand existing architecture
2. Check for duplicate functionality
3. Plan integration with existing systems
4. Consider impact on other components

---

## 🎉 SUCCESS METRICS

### **System Health Indicators:**
- ✅ No rate limiting errors
- ✅ Real-time price updates working
- ✅ Safety filters active
- ✅ Risk management functioning
- ✅ Professional signal detection
- ✅ Clean execution without errors

### **Trading Performance:**
- ✅ Capital protection working
- ✅ Risk limits respected
- ✅ No forced trades in bad conditions
- ✅ Professional discipline maintained

---

**Last Updated:** 2026-06-08
**Status:** MCX Options Trading - Production Ready
**Next Phase:** WebSocket Integration & Advanced Options Strategies
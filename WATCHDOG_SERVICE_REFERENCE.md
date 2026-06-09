# Watchdog Service - Complete Reference Guide

## 📋 Overview

The **Watchdog Service** is a comprehensive health monitoring system that continuously monitors all trading services and system resources. It provides real-time health checks, critical issue detection, and automated alerting to ensure your trading bots operate reliably.

**Status:** ✅ **Enabled by default for all bots**

---

## 🏗️ Architecture

### Service Location
```
services/watchdog_service/
├── __init__.py
├── service.py (Main watchdog implementation)
└── integration_example.py (Usage examples)
```

### Core Components

**1. Health Check System**
- Monitors 7 core services
- Configurable check intervals (default: 2 minutes)
- Response time tracking
- Error detection and logging

**2. Background Monitoring**
- Runs in separate thread
- Non-blocking operation
- Automatic startup/shutdown
- Configurable via command line

**3. Health Reporting**
- Console output with status symbols
- JSON file reports
- Critical issue detection
- Summary statistics

---

## 🤖 Bot Integration Summary

### 1. single_strike_trader.py (NSE Trading)

**Integration Status:** ✅ Complete

**Features:**
- ✅ Watchdog enabled by default
- ✅ Automatic startup on initialization
- ✅ Automatic shutdown on bot stop
- ✅ Health checks every 2 minutes
- ✅ Reports saved to `watchdog_health_report.json`

**Commands:**
```bash
# Default (watchdog enabled)
python bots\single_strike_trader.py --investment 30000 --paper-trading --symbols NIFTY,BANKNIFTY

# Disable watchdog
python bots\single_strike_trader.py --investment 30000 --paper-trading --symbols NIFTY,BANKNIFTY --disable-watchdog
```

**Integration Code:**
```python
from services.watchdog_service.service import get_watchdog_service

# In __init__:
self.watchdog_service = get_watchdog_service(check_interval=120)
self.watchdog_service.start_monitoring()

# On shutdown:
self.watchdog_service.stop_monitoring()
```

---

### 2. mcx_only_bot.py (MCX Trading)

**Integration Status:** ✅ Complete

**Features:**
- ✅ Watchdog enabled by default
- ✅ Automatic startup on initialization
- ✅ Automatic shutdown on bot stop
- ✅ Health checks every 2 minutes
- ✅ Reports saved to `watchdog_health_report.json`

**Commands:**
```bash
# Default (watchdog enabled)
python mcx_only_bot.py --mode options --investment 30000 --paper-trading

# Disable watchdog
python mcx_only_bot.py --mode options --investment 30000 --paper-trading --disable-watchdog
```

**Integration Code:**
```python
from services.watchdog_service.service import get_watchdog_service

# In __init__:
self.watchdog_service = get_watchdog_service(check_interval=120)
self.watchdog_service.start_monitoring()

# On shutdown:
self.watchdog_service.stop_monitoring()
```

---

### 3. telegram_only_bot.py (Telegram Trading)

**Integration Status:** ✅ Complete

**Features:**
- ✅ Watchdog enabled by default
- ✅ Automatic startup on initialization
- ✅ Automatic shutdown on bot stop
- ✅ Health checks every 2 minutes
- ✅ Reports saved to `watchdog_health_report.json`

**Commands:**
```bash
# Default (watchdog enabled)
python telegram\telegram_only_bot.py --investment 30000 --paper-trading

# Disable watchdog
python telegram\telegram_only_bot.py --investment 30000 --paper-trading --disable-watchdog
```

**Integration Code:**
```python
from services.watchdog_service.service import get_watchdog_service

# In __init__:
self.watchdog_service = get_watchdog_service(check_interval=120)
self.watchdog_service.start_monitoring()

# On shutdown:
self.watchdog_service.stop_monitoring()
```

---

### 4. trading_bot.py (Main LLM Trading)

**Integration Status:** ✅ Complete

**Features:**
- ✅ Watchdog enabled by default
- ✅ Automatic startup on initialization
- ✅ Automatic shutdown on bot stop
- ✅ Interactive command support
- ✅ Health checks every 2 minutes

**Commands:**
```bash
# Default (watchdog enabled)
python bots\trading_bot.py --instrument NIFTY

# Interactive mode - disable watchdog
disable watchdog
```

**Integration Code:**
```python
from services.watchdog_service.service import get_watchdog_service

# In __init__:
self.watchdog_service = get_watchdog_service(check_interval=120)
self.watchdog_service.start_monitoring()

# On shutdown:
self.watchdog_service.stop_monitoring()

# Interactive command:
elif user_input == "disable watchdog":
    if bot.watchdog_service:
        bot.watchdog_service.stop_monitoring()
        print("✓ Watchdog monitoring disabled")
```

---

## 📊 Health Monitoring Details

### Services Monitored

| Service | Check Method | Status | Response Time |
|---------|--------------|--------|---------------|
| **Kite Connection** | API authentication | ✅ HEALTHY | 0.678s |
| **WebSocket Connection** | Connection status | ✅ HEALTHY | 0.000s |
| **MCX Sentiment Service** | Service availability | ✅ HEALTHY | 0.000s |
| **LLM Service (Ollama)** | Model connection | ✅ HEALTHY | 2.080s |
| **Telegram Service** | Configuration check | ✅ HEALTHY | 0.473s |
| **Risk Management** | Risk limits | ✅ HEALTHY | 0.002s |
| **System Resources** | Memory/CPU/Disk | ⚠️ WARNING | 1.005s |

### Health Check Frequency

**Default:** Every 2 minutes (120 seconds)

**Configurable:**
```python
watchdog_service = get_watchdog_service(check_interval=60)  # 1 minute
watchdog_service = get_watchdog_service(check_interval=300)  # 5 minutes
```

### Alert Thresholds

**Memory Usage:**
- Warning: > 80%
- Critical: > 90%

**Response Time:**
- Warning: > 5 seconds
- Critical: > 10 seconds

### Critical Issue Detection

The watchdog automatically detects and logs:
- ✅ Memory exhaustion (> 90%)
- ✅ Kite connection failures
- ✅ LLM service unavailability
- ✅ WebSocket disconnections
- ✅ Risk management errors

---

## 📝 Health Report Format

### Console Output
```
================================================================================
WATCHDOG HEALTH REPORT
================================================================================
Time: 2026-06-09 07:39:22
================================================================================
[OK] kite_connection                | HEALTHY    | 0.678s
[OK] websocket                      | HEALTHY    | 0.000s
[OK] mcx_sentiment                  | HEALTHY    | 0.000s
  enabled: True
[OK] llm_service                    | HEALTHY    | 2.080s
[OK] telegram                       | HEALTHY    | 0.473s
  configured: True
[OK] risk_management                | HEALTHY    | 0.002s
  current_capital: 100000
  start_capital: 100000
  daily_loss: 0.0
  trading_enabled: True
[FAIL] system_resources               | WARNING    | 1.005s
  memory_percent: 83.4
  cpu_percent: 7.0
  disk_percent: 76.9
  memory_available_gb: 1.30
  memory_total_gb: 7.84
================================================================================
Summary: 6/7 services healthy
================================================================================
```

### JSON Report (watchdog_health_report.json)
```json
{
  "timestamp": "2026-06-09T07:39:22.776000",
  "services": {
    "kite_connection": {
      "name": "Kite Connection",
      "status": "HEALTHY",
      "last_check": "2026-06-09T07:39:22.776000",
      "response_time": 0.678,
      "details": {
        "user_id": "AB1234"
      }
    },
    "system_resources": {
      "name": "System Resources",
      "status": "WARNING",
      "last_check": "2026-06-09T07:39:22.776000",
      "response_time": 1.005,
      "details": {
        "memory_percent": 83.4,
        "cpu_percent": 7.0,
        "disk_percent": 76.9
      }
    }
  },
  "summary": {
    "total": 7,
    "healthy": 6,
    "unhealthy": 0,
    "unknown": 0
  }
}
```

---

## 🎛️ Configuration

### Config.json Integration

The watchdog service reads from `config.json` for:
- Telegram configuration
- Risk management settings
- MCX sentiment settings

**No specific watchdog configuration needed** - it auto-detects services.

### Command-Line Options

**For single_strike_trader.py:**
```bash
--disable-watchdog    # Disable watchdog monitoring
```

**For mcx_only_bot.py:**
```bash
--disable-watchdog    # Disable watchdog monitoring
```

**For telegram_only_bot.py:**
```bash
--disable-watchdog    # Disable watchdog monitoring
```

**For trading_bot.py:**
```bash
disable watchdog      # Interactive command
```

---

## 🔧 Troubleshooting

### Common Issues

**1. Watchdog not starting**
```
Error: Failed to initialize Watchdog Service
```
**Solution:** Check that `services/watchdog_service/` directory exists and all files are present.

**2. High memory usage warnings**
```
CRITICAL: Memory usage at 90%
```
**Solution:** 
- Close unnecessary applications
- Reduce LLM model size
- Increase system RAM

**3. Kite connection failures**
```
CRITICAL: Kite connection failed
```
**Solution:**
- Run `kite/auto_login.py` to re-authenticate
- Check internet connection
- Verify API credentials

**4. LLM service unhealthy**
```
WARNING: LLM service unhealthy
```
**Solution:**
- Ensure Ollama is running: `start_ollama.bat`
- Check model availability: `ollama list`
- Restart Ollama service

### Debug Mode

To enable detailed watchdog logging:
```python
import logging
logging.getLogger('services.watchdog_service').setLevel(logging.DEBUG)
```

---

## 🚀 Advanced Usage

### Custom Service Registration

You can register custom services for monitoring:

```python
# In your bot's __init__:
if self.watchdog_service:
    self.watchdog_service.register_service(
        name="MyCustomService",
        service_object=my_service,
        health_check_method="is_healthy"
    )
```

### Custom Health Check Method

Your service must implement a health check method:

```python
class MyCustomService:
    def is_healthy(self):
        """Return True if healthy, False otherwise"""
        try:
            # Your health check logic
            return True
        except Exception:
            return False
```

### Manual Health Checks

Run health checks on demand:

```python
if self.watchdog_service:
    health_results = self.watchdog_service.run_health_checks()
    print(health_results)
```

### Get Health Summary

```python
if self.watchdog_service:
    summary = self.watchdog_service.get_health_summary()
    print(f"Healthy: {summary['healthy_services']}/{summary['total_services']}")
```

---

## 📈 Performance Impact

### Resource Usage

**Memory:** ~5-10 MB additional
**CPU:** Negligible (< 1%)
**Disk:** ~1 KB per health report

### Network Usage

**Minimal:** Only checks local services and API connections
- Kite API: 1 request per check
- Ollama API: 1 request per check
- No external network calls

### Impact on Trading

**Negligible:** 
- Health checks run in background thread
- No blocking of trading operations
- Automatic throttling if system overloaded

---

## 🎯 Decision Guide

### When to Keep Watchdog Enabled

✅ **Recommended for:**
- Production trading
- Long-running sessions
- Automated trading
- Multi-bot setups
- Low-memory systems
- Unstable internet connections

### When to Disable Watchdog

⚠️ **Consider disabling if:**
- Testing/debugging (reduce log noise)
- Very low memory systems (< 4GB RAM)
- Short manual trading sessions
- Resource-constrained environments
- Custom monitoring already in place

### Recommended Settings

**Production Trading:**
```bash
# Keep watchdog enabled (default)
python bots\single_strike_trader.py --investment 30000 --paper-trading --symbols NIFTY,BANKNIFTY
```

**Development/Testing:**
```bash
# Disable watchdog to reduce log noise
python bots\single_strike_trader.py --investment 30000 --paper-trading --symbols NIFTY,BANKNIFTY --disable-watchdog
```

**Resource-Constrained Systems:**
```bash
# Disable watchdog + use smaller LLM model
python bots\single_strike_trader.py --investment 30000 --paper-trading --symbols NIFTY,BANKNIFTY --disable-watchdog
```

---

## 🔮 Future Enhancements

### Potential Improvements

**1. Telegram Alerts**
- Send critical alerts to Telegram
- Configurable alert thresholds
- Real-time notifications

**2. Web Dashboard**
- Real-time health visualization
- Historical health trends
- Performance metrics

**3. Auto-Recovery**
- Automatic service restart
- Connection retry logic
- Graceful degradation

**4. Advanced Metrics**
- Trade execution timing
- API latency tracking
- Memory leak detection

**5. Custom Alert Rules**
- User-defined alert conditions
- Multiple alert channels
- Alert grouping and deduplication

---

## 📞 Support

### Getting Help

**Check Health Reports:**
```bash
# View latest health report
type watchdog_health_report.json
```

**Run Standalone Test:**
```python
from services.watchdog_service.service import get_watchdog_service

watchdog = get_watchdog_service()
watchdog.run_health_checks()
watchdog.print_health_report()
```

**Enable Debug Logging:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## 📚 Quick Reference

### Enable/Disable Commands

| Bot | Enable (Default) | Disable |
|-----|-----------------|---------|
| single_strike_trader | Default | `--disable-watchdog` |
| mcx_only_bot | Default | `--disable-watchdog` |
| telegram_only_bot | Default | `--disable-watchdog` |
| trading_bot | Default | `disable watchdog` |

### Health Check Locations

| Bot | Health Report File |
|-----|-------------------|
| single_strike_trader | `watchdog_health_report.json` |
| mcx_only_bot | `watchdog_health_report.json` |
| telegram_only_bot | `watchdog_health_report.json` |
| trading_bot | `watchdog_health_report.json` |

### Default Check Interval

**All bots:** 2 minutes (120 seconds)

**Customize:**
```python
watchdog_service = get_watchdog_service(check_interval=60)  # 1 minute
```

---

## ✅ Summary

**Current Status:** ✅ **Fully integrated and enabled by default**

**Benefits:**
- ✅ Automatic health monitoring
- ✅ Critical issue detection
- ✅ Minimal performance impact
- ✅ Easy to disable if needed
- ✅ Comprehensive reporting

**Recommendation:** Keep watchdog enabled for production trading to ensure reliability and detect issues early.

---

**Last Updated:** 2026-06-09  
**Version:** 1.0.0  
**Status:** Production Ready ✅

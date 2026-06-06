# Analysis Service - Microservice

## Overview
This service provides REST API endpoints for technical analysis. It demonstrates microservice communication by calling the Market Data Service.

## Port
**8002**

## Dependencies
- Market Data Service (port 8001)

## How It Works
1. Receives analysis request
2. Calls Market Data Service via HTTP
3. Gets market data
4. Performs technical analysis
5. Returns analysis result

## Endpoints

### Health Check
```
GET /health
```
Returns service health status and connection to Market Data Service.

### Analyze Symbol
```
GET /api/analysis/<symbol>
```
Get complete analysis for a symbol.

**Example:**
```
GET /api/analysis/NIFTY
```

**Response:**
```json
{
  "symbol": "NIFTY",
  "market_data": {
    "last_price": 25000.50,
    "change": 100.25,
    "change_percent": 0.4
  },
  "analysis": {
    "trend": "UP",
    "momentum": "WEAK",
    "volume_signal": "HIGH",
    "recommendation": "BUY"
  }
}
```

### Get Trend
```
GET /api/analysis/trend/<symbol>
```
Get simple trend analysis (UP/DOWN/SIDEWAYS).

**Example:**
```
GET /api/analysis/trend/BANKNIFTY
```

**Response:**
```json
{
  "symbol": "BANKNIFTY",
  "trend": "UP",
  "strength": "MODERATE",
  "change": 50.00,
  "change_percent": 0.2
}
```

### Simple Analysis
```
GET /api/analysis/simple/<symbol>
```
Simple analysis for testing service communication.

**Example:**
```
GET /api/analysis/simple/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "last_price": 2500.75,
  "change": 25.50,
  "signal": "BUY"
}
```

### Analyze Multiple Symbols
```
POST /api/analysis/multiple
```
Analyze multiple symbols at once.

**Body:**
```json
{
  "symbols": ["NIFTY", "BANKNIFTY", "RELIANCE"]
}
```

**Response:**
```json
{
  "NIFTY": {
    "last_price": 25000.50,
    "change": 100.25,
    "signal": "BUY"
  },
  "BANKNIFTY": {
    "last_price": 24650.00,
    "change": 50.00,
    "signal": "BUY"
  },
  "RELIANCE": {
    "last_price": 2500.75,
    "change": 25.50,
    "signal": "BUY"
  }
}
```

## How to Run

### Prerequisite:
Market Data Service must be running on port 8001

```bash
# Start Market Data Service first
python microservices/market_service/service.py
```

### Start Analysis Service:
```bash
cd D:\Traiding_Bot
python microservices/analysis_service/service.py
```

## Configuration
Edit `config.json` to change:
- Port (default: 8002)
- Host (default: 0.0.0.0)
- Market Service URL (default: http://localhost:8001)

## Testing

### Test with curl:
```bash
# Health check
curl http://localhost:8002/health

# Analyze symbol
curl http://localhost:8002/api/analysis/NIFTY

# Get trend
curl http://localhost:8002/api/analysis/trend/BANKNIFTY

# Simple analysis
curl http://localhost:8002/api/analysis/simple/RELIANCE

# Multiple symbols
curl -X POST http://localhost:8002/api/analysis/multiple \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["NIFTY", "BANKNIFTY"]}'
```

### Test with Python:
```python
import requests

# Analyze symbol
response = requests.get('http://localhost:8002/api/analysis/NIFTY')
print(response.json())
```

## Microservice Communication

This service demonstrates how microservices communicate:

1. **Analysis Service** receives request
2. **Analysis Service** calls **Market Data Service** via HTTP
3. **Market Data Service** returns market data
4. **Analysis Service** performs analysis
5. **Analysis Service** returns result

Example call to Market Data Service:
```python
response = requests.get('http://localhost:8001/api/market/NIFTY')
market_data = response.json()
```

## Tweaking the Code

### Add New Analysis:
```python
def perform_technical_analysis(market_data):
    # Add your custom analysis logic here
    return {
        "custom_indicator": calculate_custom(market_data)
    }
```

### Change Analysis Logic:
```python
# Modify trend calculation
if change > 50:  # Changed threshold
    trend = "STRONG_UP"
elif change > 0:
    trend = "WEAK_UP"
```

### Add New Endpoint:
```python
@app.route('/api/analysis/custom/<symbol>', methods=['GET'])
def custom_analysis(symbol):
    # Your custom analysis
    return jsonify({"result": "custom analysis"})
```

## Key Learning Points

1. **Service Communication**: Services call each other via HTTP
2. **Static Configuration**: URLs are hardcoded in config
3. **Error Handling**: Handle failures when calling other services
4. **Separation of Concerns**: Each service does one thing well
5. **Independent Deployment**: Each service can be started/stopped independently

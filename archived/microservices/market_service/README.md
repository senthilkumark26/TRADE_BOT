# Market Data Service - Microservice

## Overview
This service provides REST API endpoints to fetch market data from Kite.

## Port
**8001**

## Endpoints

### Health Check
```
GET /health
```
Returns service health status and Kite connection status.

### Get Market Data
```
GET /api/market/<symbol>
```
Get complete market data for a symbol.

**Example:**
```
GET /api/market/NIFTY
```

**Response:**
```json
{
  "symbol": "NIFTY",
  "last_price": 25000.50,
  "change": 100.25,
  "change_percent": 0.4,
  "volume": 1000000,
  "oi": 500000,
  "timestamp": "2024-06-04 09:15:30"
}
```

### Get LTP (Last Traded Price)
```
GET /api/market/ltp/<symbol>
```
Get only the last traded price.

**Example:**
```
GET /api/market/ltp/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "ltp": 2500.75
}
```

### Get OHLC Data
```
GET /api/market/ohlc/<symbol>
```
Get Open, High, Low, Close data.

**Example:**
```
GET /api/market/ohlc/BANKNIFTY
```

**Response:**
```json
{
  "symbol": "BANKNIFTY",
  "open": 24500.00,
  "high": 24700.00,
  "low": 24400.00,
  "close": 24650.00
}
```

### Get Watchlist Data
```
GET /api/market/watchlist?symbols=NIFTY,BANKNIFTY,RELIANCE
```
Get market data for multiple symbols.

**Example:**
```
GET /api/market/watchlist?symbols=NIFTY,BANKNIFTY
```

**Response:**
```json
{
  "NIFTY": {
    "last_price": 25000.50,
    "change": 100.25,
    "change_percent": 0.4
  },
  "BANKNIFTY": {
    "last_price": 24650.00,
    "change": 50.00,
    "change_percent": 0.2
  }
}
```

## How to Run

### From Project Root:
```bash
cd D:\Traiding_Bot
python microservices/market_service/service.py
```

### From Service Directory:
```bash
cd microservices/market_service
python service.py
```

## Dependencies
- Flask (REST API framework)
- kite_service (existing service)

## Configuration
Edit `config.json` to change:
- Port (default: 8001)
- Host (default: 0.0.0.0)

## Testing

### Test with curl:
```bash
# Health check
curl http://localhost:8001/health

# Get market data
curl http://localhost:8001/api/market/NIFTY

# Get LTP
curl http://localhost:8001/api/market/ltp/RELIANCE

# Get OHLC
curl http://localhost:8001/api/market/ohlc/BANKNIFTY

# Get watchlist
curl "http://localhost:8001/api/market/watchlist?symbols=NIFTY,BANKNIFTY"
```

### Test with Python:
```python
import requests

# Health check
response = requests.get('http://localhost:8001/health')
print(response.json())

# Get market data
response = requests.get('http://localhost:8001/api/market/NIFTY')
print(response.json())
```

## Tweaking the Code

### Add New Endpoint:
```python
@app.route('/api/market/volume/<symbol>', methods=['GET'])
def get_volume(symbol):
    # Your code here
    return jsonify({"symbol": symbol, "volume": 1000000})
```

### Change Response Format:
```python
# Add more fields to response
return jsonify({
    "symbol": symbol,
    "last_price": data.get("last_price"),
    "new_field": "new_value"  # Add this
})
```

### Add Error Handling:
```python
try:
    # Your code
except Exception as e:
    return jsonify({"error": str(e)}), 500
```

## Notes
- Uses existing kite_service for Kite integration
- Runs on Flask (lightweight REST API framework)
- Can be called by other microservices
- Easy to extend with new endpoints

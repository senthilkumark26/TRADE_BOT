# Execution Service - Microservice

## Overview
This service manages trade execution and order lifecycle. It handles trade submission, execution, cancellation, and exit with P&L calculation.

## Port
**8003**

## Dependencies
- Kite Service (for actual trade execution)

## Trade Lifecycle

```
PENDING → EXECUTED → EXITED
   ↓
CANCELLED
```

## Endpoints

### Health Check
```
GET /health
```
Returns service health status and trade statistics.

**Response:**
```json
{
  "service": "execution_service",
  "status": "healthy",
  "kite_connected": true,
  "active_trades": 5,
  "pending_trades": 2
}
```

### Submit Trade
```
POST /api/trade/submit
```
Submit a new trade for execution.

**Body:**
```json
{
  "symbol": "NIFTY",
  "direction": "CALL",
  "strike": 25000,
  "quantity": 1
}
```

**Response:**
```json
{
  "trade_id": "uuid-string",
  "status": "SUBMITTED",
  "message": "Trade submitted successfully"
}
```

### Execute Trade
```
POST /api/trade/execute/<trade_id>
```
Execute a pending trade.

**Response:**
```json
{
  "trade_id": "uuid-string",
  "status": "EXECUTED",
  "executed_at": "2024-06-04T09:15:30",
  "entry_price": 25000
}
```

### Cancel Trade
```
POST /api/trade/cancel/<trade_id>
```
Cancel a pending trade.

**Response:**
```json
{
  "trade_id": "uuid-string",
  "status": "CANCELLED",
  "message": "Trade cancelled successfully"
}
```

### Get Trade Status
```
GET /api/trade/status/<trade_id>
```
Get status of a specific trade.

**Response:**
```json
{
  "trade_id": "uuid-string",
  "symbol": "NIFTY",
  "direction": "CALL",
  "strike": 25000,
  "quantity": 1,
  "status": "EXECUTED",
  "submitted_at": "2024-06-04T09:15:00",
  "executed_at": "2024-06-04T09:15:30",
  "entry_price": 25000,
  "exit_price": null,
  "pnl": null
}
```

### Exit Trade
```
POST /api/trade/exit/<trade_id>
```
Exit an executed trade with P&L calculation.

**Body:**
```json
{
  "exit_price": 25100
}
```

**Response:**
```json
{
  "trade_id": "uuid-string",
  "status": "EXITED",
  "entry_price": 25000,
  "exit_price": 25100,
  "pnl": 100
}
```

### List All Trades
```
GET /api/trade/list
```
List all trades.

**Query params:**
- status: Filter by status (PENDING, EXECUTED, EXITED, CANCELLED)

**Example:**
```
GET /api/trade/list?status=EXECUTED
```

**Response:**
```json
{
  "trade-id-1": {
    "symbol": "NIFTY",
    "status": "EXECUTED"
  },
  "trade-id-2": {
    "symbol": "BANKNIFTY",
    "status": "EXECUTED"
  }
}
```

### Get Trade Queue
```
GET /api/trade/queue
```
Get current trade queue (pending trades).

**Response:**
```json
{
  "queue_size": 2,
  "trades": [
    {
      "trade_id": "uuid-string",
      "symbol": "NIFTY",
      "status": "PENDING"
    }
  ]
}
```

### Full Trading Pipeline
```
POST /api/trade/pipeline
```
Full trading pipeline: Submit → Analyze → Execute in one call.

This demonstrates the complete service chain:
**Execution Service → Analysis Service → Market Data Service**

**Body:**
```json
{
  "symbol": "NIFTY",
  "direction": "CALL",
  "strike": 25000,
  "quantity": 1
}
```

**Response:**
```json
{
  "trade_id": "uuid-string",
  "step1_submit": "SUCCESS",
  "step2_analysis": {
    "symbol": "NIFTY",
    "signal": "BUY",
    "last_price": 25000
  },
  "step3_execute": "SUCCESS",
  "final_status": "EXECUTED"
}
```

This endpoint demonstrates:
- Service-to-service communication
- Analysis validation before execution
- Complete trading pipeline in one call

## How to Run

```bash
cd D:\Traiding_Bot
python microservices/execution_service/service.py
```

## Configuration
Edit `config.json` to change:
- Port (default: 8003)
- Host (default: 0.0.0.0)

## Testing

### Test with curl:

```bash
# Health check
curl http://localhost:8003/health

# Submit trade
curl -X POST http://localhost:8003/api/trade/submit \
  -H "Content-Type: application/json" \
  -d '{"symbol":"NIFTY","direction":"CALL","strike":25000,"quantity":1}'

# Get trade status
curl http://localhost:8003/api/trade/status/<trade_id>

# Execute trade
curl -X POST http://localhost:8003/api/trade/execute/<trade_id>

# Exit trade
curl -X POST http://localhost:8003/api/trade/exit/<trade_id> \
  -H "Content-Type: application/json" \
  -d '{"exit_price":25100}'

# List all trades
curl http://localhost:8003/api/trade/list

# Get trade queue
curl http://localhost:8003/api/trade/queue
```

### Test with Python:

```python
import requests
import json

# Submit trade
trade_data = {
    "symbol": "NIFTY",
    "direction": "CALL",
    "strike": 25000,
    "quantity": 1
}
response = requests.post('http://localhost:8003/api/trade/submit', json=trade_data)
result = response.json()
trade_id = result['trade_id']

# Execute trade
response = requests.post(f'http://localhost:8003/api/trade/execute/{trade_id}')
print(response.json())

# Exit trade
exit_data = {"exit_price": 25100}
response = requests.post(f'http://localhost:8003/api/trade/exit/{trade_id}', json=exit_data)
print(response.json())
```

## Trade Lifecycle Example

```python
# 1. Submit trade
POST /api/trade/submit
→ Status: PENDING

# 2. Execute trade
POST /api/trade/execute/<trade_id>
→ Status: EXECUTED
→ Entry price set

# 3. Exit trade
POST /api/trade/exit/<trade_id>
→ Status: EXITED
→ Exit price set
→ P&L calculated

# OR Cancel trade
POST /api/trade/cancel/<trade_id>
→ Status: CANCELLED
```

## Tweaking the Code

### Add Trade Validation:
```python
def submit_trade():
    # Add validation logic
    if trade_data["quantity"] <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400
    
    if trade_data["direction"] not in ["CALL", "PUT"]:
        return jsonify({"error": "Direction must be CALL or PUT"}), 400
```

### Add Stop-Loss:
```python
trade = {
    "stop_loss": trade_data.get("stop_loss"),
    "take_profit": trade_data.get("take_profit")
}
```

### Add Real Kite Execution:
```python
def execute_trade(trade_id):
    # Call Kite API to place real order
    order = kite_service.place_order(
        symbol=trade["symbol"],
        quantity=trade["quantity"],
        direction=trade["direction"]
    )
```

### Add Trade History:
```python
trade_history = []
def exit_trade(trade_id):
    # Add to history
    trade_history.append(trades[trade_id])
    # Remove from active trades
    del trades[trade_id]
```

## Key Learning Points

1. **Trade Lifecycle Management**: Managing state transitions (PENDING → EXECUTED → EXITED)
2. **Trade Queue**: Managing pending trades
3. **State Tracking**: Keeping track of trade status
4. **P&L Calculation**: Calculating profit/loss on exit
5. **Error Handling**: Handling invalid states and missing trades
6. **Unique IDs**: Using UUID for unique trade identification

import requests
import json

# Test Execution Service
base_url = "http://localhost:8003"

print("Testing Execution Service...")

# Test 1: Health check
print("\n1. Health Check:")
response = requests.get(f"{base_url}/health")
print(response.json())

# Test 2: Submit trade
print("\n2. Submit Trade:")
trade_data = {
    "symbol": "NIFTY",
    "direction": "CALL",
    "strike": 25000,
    "quantity": 1
}
response = requests.post(f"{base_url}/api/trade/submit", json=trade_data)
result = response.json()
print(result)
trade_id = result.get("trade_id")

# Test 3: Get trade status
print("\n3. Get Trade Status:")
response = requests.get(f"{base_url}/api/trade/status/{trade_id}")
print(response.json())

# Test 4: Execute trade
print("\n4. Execute Trade:")
response = requests.post(f"{base_url}/api/trade/execute/{trade_id}")
print(response.json())

# Test 5: Exit trade
print("\n5. Exit Trade:")
exit_data = {"exit_price": 25100}
response = requests.post(f"{base_url}/api/trade/exit/{trade_id}", json=exit_data)
print(response.json())

# Test 6: List all trades
print("\n6. List All Trades:")
response = requests.get(f"{base_url}/api/trade/list")
print(response.json())

# Test 7: Get trade queue
print("\n7. Get Trade Queue:")
response = requests.get(f"{base_url}/api/trade/queue")
print(response.json())

print("\nAll tests completed!")

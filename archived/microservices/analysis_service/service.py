"""
Analysis Service - Microservice
------------------------------
Provides REST API for technical analysis
Calls Market Data Service for market data
Port: 8002
"""

from flask import Flask, jsonify, request
import requests
import json
import os

app = Flask(__name__)

# Global variables
config = {}
market_service_url = ""

def load_config():
    """Load configuration from config.json"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def get_market_data(symbol):
    """
    Call Market Data Service to get market data
    This demonstrates microservice communication
    """
    try:
        url = f"{market_service_url}/api/market/{symbol}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error calling Market Data Service: {e}")
        return None

# ==================== REST API ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "service": "analysis_service",
        "status": "healthy",
        "market_service_connected": True
    })

@app.route('/api/analysis/<symbol>', methods=['GET'])
def analyze_symbol(symbol):
    """
    Analyze a symbol - Calls Market Data Service
    
    Args:
        symbol: Stock/Index symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
    
    Returns:
        JSON with analysis result
    """
    try:
        # Step 1: Get market data from Market Data Service
        market_data = get_market_data(symbol)
        
        if not market_data:
            return jsonify({"error": f"Could not get market data for {symbol}"}), 500
        
        if "error" in market_data:
            return jsonify(market_data), 400
        
        # Step 2: Perform technical analysis
        analysis = perform_technical_analysis(market_data)
        
        return jsonify({
            "symbol": symbol,
            "market_data": market_data,
            "analysis": analysis
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/trend/<symbol>', methods=['GET'])
def get_trend(symbol):
    """
    Get trend analysis for a symbol
    
    Args:
        symbol: Stock/Index symbol
    
    Returns:
        JSON with trend (UP/DOWN/SIDEWAYS)
    """
    try:
        market_data = get_market_data(symbol)
        
        if not market_data or "error" in market_data:
            return jsonify({"error": "Could not get market data"}), 400
        
        # Determine trend based on change
        change = market_data.get("change", 0)
        
        if change > 0:
            trend = "UP"
            strength = "STRONG" if change > 100 else "MODERATE"
        elif change < 0:
            trend = "DOWN"
            strength = "STRONG" if change < -100 else "MODERATE"
        else:
            trend = "SIDEWAYS"
            strength = "NEUTRAL"
        
        return jsonify({
            "symbol": symbol,
            "trend": trend,
            "strength": strength,
            "change": change,
            "change_percent": market_data.get("change_percent", 0)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/simple/<symbol>', methods=['GET'])
def simple_analysis(symbol):
    """
    Simple analysis without complex calculations
    Good for testing service communication
    """
    try:
        # Call Market Data Service
        market_data = get_market_data(symbol)
        
        if not market_data or "error" in market_data:
            return jsonify({"error": "Could not get market data"}), 400
        
        # Simple analysis
        last_price = market_data.get("last_price", 0)
        change = market_data.get("change", 0)
        
        return jsonify({
            "symbol": symbol,
            "last_price": last_price,
            "change": change,
            "signal": "BUY" if change > 0 else "SELL" if change < 0 else "HOLD"
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/multiple', methods=['POST'])
def analyze_multiple():
    """
    Analyze multiple symbols at once
    
    Body should be JSON:
    {
        "symbols": ["NIFTY", "BANKNIFTY", "RELIANCE"]
    }
    """
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])
        
        if not symbols:
            return jsonify({"error": "No symbols provided"}), 400
        
        results = {}
        for symbol in symbols:
            # Call simple analysis for each symbol
            market_data = get_market_data(symbol)
            
            if market_data and "error" not in market_data:
                results[symbol] = {
                    "last_price": market_data.get("last_price"),
                    "change": market_data.get("change"),
                    "signal": "BUY" if market_data.get("change", 0) > 0 else "SELL"
                }
            else:
                results[symbol] = {"error": "Could not get data"}
        
        return jsonify(results)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== ANALYSIS FUNCTIONS ====================

def perform_technical_analysis(market_data):
    """
    Perform technical analysis on market data
    Simplified for learning purposes
    """
    last_price = market_data.get("last_price", 0)
    change = market_data.get("change", 0)
    change_percent = market_data.get("change_percent", 0)
    volume = market_data.get("volume", 0)
    
    # Simple technical indicators
    trend = "UP" if change > 0 else "DOWN" if change < 0 else "NEUTRAL"
    
    # Momentum (simplified)
    momentum = "STRONG" if abs(change_percent) > 0.5 else "WEAK"
    
    # Volume analysis
    volume_signal = "HIGH" if volume > 1000000 else "LOW"
    
    return {
        "trend": trend,
        "momentum": momentum,
        "volume_signal": volume_signal,
        "recommendation": "BUY" if change > 0 and change_percent > 0.2 else "SELL" if change < 0 else "HOLD"
    }

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 80)
    print("ANALYSIS SERVICE - Microservice")
    print("=" * 80)
    
    # Load config
    config = load_config()
    print(f"Config loaded: {config}")
    
    # Get Market Data Service URL from config
    market_service_url = config.get('market_service_url', 'http://localhost:8001')
    print(f"Market Data Service URL: {market_service_url}")
    
    # Test connection to Market Data Service
    try:
        response = requests.get(f"{market_service_url}/health", timeout=2)
        if response.status_code == 200:
            print("OK Connected to Market Data Service")
        else:
            print("WARNING Could not connect to Market Data Service")
    except Exception as e:
        print(f"WARNING Error connecting to Market Data Service: {e}")
    
    # Start Flask server
    port = config.get('port', 8002)
    host = config.get('host', '0.0.0.0')
    
    print(f"STARTING Analysis Service on http://{host}:{port}")
    print("=" * 80)
    print("Available endpoints:")
    print("  GET  /health")
    print("  GET  /api/analysis/<symbol>")
    print("  GET  /api/analysis/trend/<symbol>")
    print("  GET  /api/analysis/simple/<symbol>")
    print("  POST /api/analysis/multiple")
    print("=" * 80)
    print("This service calls Market Data Service (port 8001)")
    print("=" * 80)
    
    app.run(host=host, port=port, debug=True)

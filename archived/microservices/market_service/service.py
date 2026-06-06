"""
Market Data Service - Microservice
----------------------------------
Provides REST API for market data from Kite
Port: 8001
"""

from flask import Flask, jsonify, request
import sys
import os

# Add parent directory to path to import existing services
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from kite_service import KiteService
import json

app = Flask(__name__)

# Global variables
kite_service = None
config = {}

def load_config():
    """Load configuration from config.json"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def init_kite_service():
    """Initialize Kite Service"""
    global kite_service
    try:
        # Load main config
        main_config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../config.json'))
        with open(main_config_path, 'r') as f:
            main_config = json.load(f)
        
        # Initialize Kite Service
        kite_service = KiteService(
            api_key=main_config.get("api_key", ""),
            access_token=main_config.get("access_token", ""),
            demo_mode=main_config.get("use_demo_data", False)
        )
        
        print("OK Kite Service initialized")
        return True
    except Exception as e:
        print(f"ERROR initializing Kite Service: {e}")
        return False

# ==================== REST API ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "service": "market_data_service",
        "status": "healthy",
        "kite_connected": kite_service is not None
    })

@app.route('/api/market/<symbol>', methods=['GET'])
def get_market_data(symbol):
    """
    Get market data for a symbol
    
    Args:
        symbol: Stock/Index symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
    
    Returns:
        JSON with market data
    """
    try:
        if not kite_service:
            return jsonify({"error": "Kite Service not initialized"}), 500
        
        # Get quote from Kite
        instrument_token = f"NSE:{symbol}"
        quote = kite_service.get_quote(instrument_token)
        
        if quote and instrument_token in quote:
            data = quote[instrument_token]
            return jsonify({
                "symbol": symbol,
                "last_price": data.get("last_price"),
                "change": data.get("change"),
                "change_percent": data.get("net_change_percent"),
                "volume": data.get("volume"),
                "oi": data.get("oi"),
                "timestamp": data.get("last_trade_time")
            })
        else:
            return jsonify({"error": f"No data found for {symbol}"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/market/ltp/<symbol>', methods=['GET'])
def get_ltp(symbol):
    """
    Get Last Traded Price (LTP) for a symbol
    
    Args:
        symbol: Stock/Index symbol
    
    Returns:
        JSON with LTP
    """
    try:
        if not kite_service:
            return jsonify({"error": "Kite Service not initialized"}), 500
        
        instrument_token = f"NSE:{symbol}"
        ltp_data = kite_service.get_ltp([instrument_token])
        
        if ltp_data and instrument_token in ltp_data:
            return jsonify({
                "symbol": symbol,
                "ltp": ltp_data[instrument_token].get("last_price")
            })
        else:
            return jsonify({"error": f"No LTP found for {symbol}"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/market/ohlc/<symbol>', methods=['GET'])
def get_ohlc(symbol):
    """
    Get OHLC data for a symbol
    
    Args:
        symbol: Stock/Index symbol
    
    Returns:
        JSON with OHLC data
    """
    try:
        if not kite_service:
            return jsonify({"error": "Kite Service not initialized"}), 500
        
        instrument_token = f"NSE:{symbol}"
        ohlc_data = kite_service.get_ohlc(instrument_token)
        
        if ohlc_data and instrument_token in ohlc_data:
            data = ohlc_data[instrument_token]
            return jsonify({
                "symbol": symbol,
                "open": data.get("ohlc", {}).get("open"),
                "high": data.get("ohlc", {}).get("high"),
                "low": data.get("ohlc", {}).get("low"),
                "close": data.get("ohlc", {}).get("close")
            })
        else:
            return jsonify({"error": f"No OHLC found for {symbol}"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/market/watchlist', methods=['GET'])
def get_watchlist():
    """
    Get market data for watchlist symbols
    
    Query params:
        symbols: Comma-separated list of symbols (e.g., NIFTY,BANKNIFTY,RELIANCE)
    
    Returns:
        JSON with market data for all symbols
    """
    try:
        if not kite_service:
            return jsonify({"error": "Kite Service not initialized"}), 500
        
        symbols = request.args.get('symbols', '').split(',')
        symbols = [s.strip() for s in symbols if s.strip()]
        
        if not symbols:
            return jsonify({"error": "No symbols provided"}), 400
        
        results = {}
        for symbol in symbols:
            instrument_token = f"NSE:{symbol}"
            quote = kite_service.get_quote(instrument_token)
            
            if quote and instrument_token in quote:
                data = quote[instrument_token]
                results[symbol] = {
                    "last_price": data.get("last_price"),
                    "change": data.get("change"),
                    "change_percent": data.get("net_change_percent")
                }
        
        return jsonify(results)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 80)
    print("MARKET DATA SERVICE - Microservice")
    print("=" * 80)
    
    # Load config
    config = load_config()
    print(f"Config loaded: {config}")
    
    # Initialize Kite Service
    if init_kite_service():
        print("OK Kite Service ready")
    else:
        print("FAILED to initialize Kite Service")
        sys.exit(1)
    
    # Start Flask server
    port = config.get('port', 8001)
    host = config.get('host', '0.0.0.0')
    
    print(f"STARTING Market Data Service on http://{host}:{port}")
    print("=" * 80)
    print("Available endpoints:")
    print("  GET  /health")
    print("  GET  /api/market/<symbol>")
    print("  GET  /api/market/ltp/<symbol>")
    print("  GET  /api/market/ohlc/<symbol>")
    print("  GET  /api/market/watchlist?symbols=NIFTY,BANKNIFTY")
    print("=" * 80)
    
    app.run(host=host, port=port, debug=True)

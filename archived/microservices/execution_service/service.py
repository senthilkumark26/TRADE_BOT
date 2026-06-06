"""
Execution Service - Microservice
-------------------------------
Manages trade execution and order lifecycle
Port: 8003
"""

from flask import Flask, jsonify, request
import json
import uuid
from datetime import datetime
import sys
import os
import requests

# Add parent directory to path to import existing services
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from kite_service import KiteService

app = Flask(__name__)

# Global variables
kite_service = None
config = {}
trades = {}  # trade_id -> trade data
trade_queue = []  # list of pending trades
analysis_service_url = ""

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

def get_analysis(symbol):
    """
    Call Analysis Service to get analysis for a symbol
    This demonstrates service-to-service communication
    """
    try:
        url = f"{analysis_service_url}/api/analysis/simple/{symbol}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error calling Analysis Service: {e}")
        return None

# ==================== REST API ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "service": "execution_service",
        "status": "healthy",
        "kite_connected": kite_service is not None,
        "active_trades": len(trades),
        "pending_trades": len(trade_queue)
    })

@app.route('/api/trade/submit', methods=['POST'])
def submit_trade():
    """
    Submit a new trade for execution
    
    Body should be JSON:
    {
        "symbol": "NIFTY",
        "direction": "CALL",
        "strike": 25000,
        "quantity": 1
    }
    """
    try:
        trade_data = request.get_json()
        
        # Validate trade data
        required_fields = ["symbol", "direction", "strike", "quantity"]
        for field in required_fields:
            if field not in trade_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Generate unique trade ID
        trade_id = str(uuid.uuid4())
        
        # Create trade object
        trade = {
            "trade_id": trade_id,
            "symbol": trade_data["symbol"],
            "direction": trade_data["direction"],
            "strike": trade_data["strike"],
            "quantity": trade_data["quantity"],
            "status": "PENDING",
            "submitted_at": datetime.now().isoformat(),
            "executed_at": None,
            "entry_price": None,
            "exit_price": None,
            "pnl": None
        }
        
        # Add to trades
        trades[trade_id] = trade
        
        # Add to queue
        trade_queue.append(trade_id)
        
        return jsonify({
            "trade_id": trade_id,
            "status": "SUBMITTED",
            "message": "Trade submitted successfully"
        }), 201
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/execute/<trade_id>', methods=['POST'])
def execute_trade(trade_id):
    """
    Execute a pending trade with analysis check
    
    Args:
        trade_id: Trade ID to execute
    
    Returns:
        Execution result
    """
    try:
        if trade_id not in trades:
            return jsonify({"error": "Trade not found"}), 404
        
        trade = trades[trade_id]
        
        if trade["status"] != "PENDING":
            return jsonify({"error": f"Trade already {trade['status']}"}), 400
        
        # Step 1: Get analysis from Analysis Service (Service-to-service communication)
        print(f"Getting analysis for {trade['symbol']} from Analysis Service...")
        analysis = get_analysis(trade["symbol"])
        
        if analysis:
            print(f"Analysis received: {analysis}")
            # Check if analysis suggests executing the trade
            signal = analysis.get("signal", "HOLD")
            
            if signal == "SELL":
                # Analysis suggests not to execute
                trade["status"] = "REJECTED_BY_ANALYSIS"
                return jsonify({
                    "trade_id": trade_id,
                    "status": "REJECTED",
                    "reason": "Analysis suggested SELL/REJECT",
                    "analysis": analysis
                })
        else:
            print("Could not get analysis, proceeding with execution")
        
        # Step 2: Execute trade (simulation for learning)
        trade["status"] = "EXECUTED"
        trade["executed_at"] = datetime.now().isoformat()
        trade["entry_price"] = trade["strike"]  # Simplified: use strike as entry price
        
        # Store analysis if available
        if analysis:
            trade["analysis"] = analysis
        
        # Remove from queue
        if trade_id in trade_queue:
            trade_queue.remove(trade_id)
        
        return jsonify({
            "trade_id": trade_id,
            "status": "EXECUTED",
            "executed_at": trade["executed_at"],
            "entry_price": trade["entry_price"],
            "analysis": analysis
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/cancel/<trade_id>', methods=['POST'])
def cancel_trade(trade_id):
    """
    Cancel a pending trade
    
    Args:
        trade_id: Trade ID to cancel
    
    Returns:
        Cancellation result
    """
    try:
        if trade_id not in trades:
            return jsonify({"error": "Trade not found"}), 404
        
        trade = trades[trade_id]
        
        if trade["status"] != "PENDING":
            return jsonify({"error": f"Cannot cancel trade with status {trade['status']}"}), 400
        
        # Cancel trade
        trade["status"] = "CANCELLED"
        
        # Remove from queue
        if trade_id in trade_queue:
            trade_queue.remove(trade_id)
        
        return jsonify({
            "trade_id": trade_id,
            "status": "CANCELLED",
            "message": "Trade cancelled successfully"
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/status/<trade_id>', methods=['GET'])
def get_trade_status(trade_id):
    """
    Get status of a trade
    
    Args:
        trade_id: Trade ID
    
    Returns:
        Trade status
    """
    try:
        if trade_id not in trades:
            return jsonify({"error": "Trade not found"}), 404
        
        return jsonify(trades[trade_id])
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/exit/<trade_id>', methods=['POST'])
def exit_trade(trade_id):
    """
    Exit an executed trade
    
    Body should be JSON:
    {
        "exit_price": 25100
    }
    
    Args:
        trade_id: Trade ID to exit
    
    Returns:
        Exit result with P&L
    """
    try:
        if trade_id not in trades:
            return jsonify({"error": "Trade not found"}), 404
        
        trade = trades[trade_id]
        
        if trade["status"] != "EXECUTED":
            return jsonify({"error": f"Cannot exit trade with status {trade['status']}"}), 400
        
        exit_data = request.get_json()
        exit_price = exit_data.get("exit_price", trade["entry_price"])
        
        # Calculate P&L
        if trade["direction"] == "CALL":
            pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
        else:  # PUT
            pnl = (trade["entry_price"] - exit_price) * trade["quantity"]
        
        # Update trade
        trade["status"] = "EXITED"
        trade["exit_price"] = exit_price
        trade["pnl"] = pnl
        trade["exited_at"] = datetime.now().isoformat()
        
        return jsonify({
            "trade_id": trade_id,
            "status": "EXITED",
            "entry_price": trade["entry_price"],
            "exit_price": exit_price,
            "pnl": pnl
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/list', methods=['GET'])
def list_trades():
    """
    List all trades
    
    Query params:
        status: Filter by status (PENDING, EXECUTED, EXITED, CANCELLED)
    
    Returns:
        List of trades
    """
    try:
        status_filter = request.args.get('status')
        
        if status_filter:
            filtered_trades = {k: v for k, v in trades.items() if v["status"] == status_filter}
            return jsonify(filtered_trades)
        else:
            return jsonify(trades)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/queue', methods=['GET'])
def get_trade_queue():
    """
    Get current trade queue
    
    Returns:
        List of pending trades in queue
    """
    try:
        pending_trades = []
        for trade_id in trade_queue:
            if trade_id in trades:
                pending_trades.append(trades[trade_id])
        
        return jsonify({
            "queue_size": len(pending_trades),
            "trades": pending_trades
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/trade/pipeline', methods=['POST'])
def full_pipeline():
    """
    Full trading pipeline: Submit → Analyze → Execute
    
    This demonstrates the complete service chain:
    Execution Service → Analysis Service → Market Data Service
    
    Body should be JSON:
    {
        "symbol": "NIFTY",
        "direction": "CALL",
        "strike": 25000,
        "quantity": 1
    }
    
    Returns:
        Complete pipeline result with all service responses
    """
    try:
        trade_data = request.get_json()
        
        # Validate trade data
        required_fields = ["symbol", "direction", "strike", "quantity"]
        for field in required_fields:
            if field not in trade_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Step 1: Submit trade
        print("Step 1: Submitting trade...")
        trade_id = str(uuid.uuid4())
        
        trade = {
            "trade_id": trade_id,
            "symbol": trade_data["symbol"],
            "direction": trade_data["direction"],
            "strike": trade_data["strike"],
            "quantity": trade_data["quantity"],
            "status": "PENDING",
            "submitted_at": datetime.now().isoformat()
        }
        
        trades[trade_id] = trade
        
        # Step 2: Get analysis from Analysis Service
        print(f"Step 2: Getting analysis for {trade_data['symbol']} from Analysis Service...")
        analysis = get_analysis(trade_data["symbol"])
        
        pipeline_result = {
            "trade_id": trade_id,
            "step1_submit": "SUCCESS",
            "step2_analysis": analysis if analysis else "FAILED",
        }
        
        # Step 3: Check analysis and execute
        if analysis:
            signal = analysis.get("signal", "HOLD")
            
            if signal == "SELL":
                # Analysis suggests not to execute
                trade["status"] = "REJECTED_BY_ANALYSIS"
                pipeline_result["step3_execute"] = "REJECTED"
                pipeline_result["final_status"] = "REJECTED"
            else:
                # Execute trade
                trade["status"] = "EXECUTED"
                trade["executed_at"] = datetime.now().isoformat()
                trade["entry_price"] = trade["strike"]
                trade["analysis"] = analysis
                pipeline_result["step3_execute"] = "SUCCESS"
                pipeline_result["final_status"] = "EXECUTED"
        else:
            # Could not get analysis, execute anyway
            trade["status"] = "EXECUTED"
            trade["executed_at"] = datetime.now().isoformat()
            trade["entry_price"] = trade["strike"]
            pipeline_result["step2_analysis"] = "FAILED - Proceeding without analysis"
            pipeline_result["step3_execute"] = "SUCCESS"
            pipeline_result["final_status"] = "EXECUTED"
        
        return jsonify(pipeline_result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 80)
    print("EXECUTION SERVICE - Microservice")
    print("=" * 80)
    
    # Load config
    config = load_config()
    print(f"Config loaded: {config}")
    
    # Get Analysis Service URL from config
    analysis_service_url = config.get('analysis_service_url', 'http://localhost:8002')
    
    # Initialize Kite Service
    if init_kite_service():
        print("OK Kite Service ready")
    else:
        print("FAILED to initialize Kite Service")
        sys.exit(1)
    
    print(f"Analysis Service URL: {analysis_service_url}")
    
    # Test connection to Analysis Service
    try:
        response = requests.get(f"{analysis_service_url}/health", timeout=2)
        if response.status_code == 200:
            print("OK Connected to Analysis Service")
        else:
            print("WARNING Could not connect to Analysis Service")
    except Exception as e:
        print(f"WARNING Error connecting to Analysis Service: {e}")
    
    # Start Flask server
    port = config.get('port', 8003)
    host = config.get('host', '0.0.0.0')
    
    print(f"STARTING Execution Service on http://{host}:{port}")
    print("=" * 80)
    print("Available endpoints:")
    print("  GET  /health")
    print("  POST /api/trade/submit")
    print("  POST /api/trade/execute/<trade_id>")
    print("  POST /api/trade/cancel/<trade_id>")
    print("  GET  /api/trade/status/<trade_id>")
    print("  POST /api/trade/exit/<trade_id>")
    print("  GET  /api/trade/list")
    print("  GET  /api/trade/queue")
    print("  POST /api/trade/pipeline  <-- FULL PIPELINE DEMO")
    print("=" * 80)
    print("This service manages trade execution and order lifecycle")
    print("Calls Analysis Service for trade validation")
    print("=" * 80)
    
    app.run(host=host, port=port, debug=True)

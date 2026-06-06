"""
Web Interface for Market Analyzer - Flask Front-End
Provides real-time view of perfect trades and market analysis
"""
from flask import Flask, render_template, jsonify, request
import logging
import threading
import webbrowser
import time
from datetime import datetime
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global market analyzer instance (will be set from main application)
market_analyzer = None

# Thread-safe file lock for cross-component data integrity
file_lock = threading.Lock()

# Centralized path to trade manifest file (must match trading_bot.py)
TRADE_MANIFEST_PATH = "D:\\Traiding_Bot\\active_trades.json"

# Global storage for manual signals (thread-safe)
manual_signals = []
manual_signals_lock = threading.Lock()


def set_market_analyzer(analyzer):
    """Set the global market analyzer instance."""
    global market_analyzer
    market_analyzer = analyzer
    logger.info("Market Analyzer connected to web interface")


def add_manual_signal(signal_data):
    """
    Thread-safe function to add a manual signal to the global storage.
    
    Args:
        signal_data: Dictionary with signal status, signal text, trade_id, timestamp
    """
    global manual_signals
    with manual_signals_lock:
        manual_signals.append(signal_data)
        # Keep only last 20 signals to prevent memory bloat
        if len(manual_signals) > 20:
            manual_signals = manual_signals[-20:]
        logger.info(f"📢 Manual signal added: {signal_data.get('status', 'UNKNOWN')}")
        
        # Auto-open manual signals API when new signal is added
        try:
            if signal_data.get('status') == 'APPROVED':
                signals_url = "http://localhost:5000/api/manual-signals"
                logger.info(f"🌐 Auto-opening manual signals API: {signals_url}")
                webbrowser.open(signals_url)
                time.sleep(1)  # Small delay
        except Exception as e:
            logger.error(f"Failed to auto-open manual signals: {e}")


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/trades')
def get_trades():
    """API endpoint to get perfect trades from both market analyzer and trade manifest."""
    try:
        all_trades = []

        # 1. Get scanned perfect trades from market analyzer
        if market_analyzer:
            try:
                scanned_trades = market_analyzer.get_perfect_trades()
                for trade in scanned_trades:
                    formatted_trade = {
                        'trade_id': trade.get('trade_id', ''),
                        'symbol': trade.get('symbol', 'N/A'),
                        'direction': trade.get('direction', 'N/A'),
                        'strike': trade.get('strike', 0),
                        'spot': trade.get('spot', 0),
                        'vwap': trade.get('vwap', 0),
                        'quality_score': trade.get('quality_score', 0),
                        'reason': trade.get('reason', 'N/A'),
                        'support': trade.get('support', 0),
                        'resistance': trade.get('resistance', 0),
                        'analysis_timestamp': trade.get('analysis_timestamp', ''),
                        'option_type': 'CE' if trade.get('direction') == 'CALL' else 'PE' if trade.get('direction') == 'PUT' else 'N/A',
                        'source': 'scanner'  # Mark as scanned trade
                    }
                    all_trades.append(formatted_trade)
            except Exception as e:
                logger.warning(f"Error getting scanner trades: {e}")

        # 2. Get executed trades from trade manifest (paper trading)
        active_trades_count = 0
        completed_trades_count = 0
        total_pnl = 0

        try:
            if os.path.exists(TRADE_MANIFEST_PATH):
                with file_lock:
                    with open(TRADE_MANIFEST_PATH, 'r') as f:
                        manifest_data = json.load(f)

                executed_trades = manifest_data.get('trades', [])
                for trade in executed_trades:
                    # Format executed trades
                    execution = trade.get('execution', {})
                    entry_price = execution.get('entry_price', 0)
                    current_price = execution.get('current_price', 0)
                    target = execution.get('take_profit', 0)
                    stoploss = execution.get('current_stoploss', 0)
                    status = trade.get('status', 'UNKNOWN')
                    pnl = current_price - entry_price
                    pnl_percentage = (pnl / entry_price * 100) if entry_price > 0 else 0

                    # Count trades
                    if status == 'ACTIVE':
                        active_trades_count += 1
                    else:
                        completed_trades_count += 1
                        total_pnl += pnl

                    formatted_trade = {
                        'trade_id': trade.get('trade_id', ''),
                        'symbol': trade.get('underlying', 'N/A'),
                        'direction': 'CALL' if trade.get('option_type') == 'CE' else 'PUT' if trade.get('option_type') == 'PE' else 'N/A',
                        'strike': trade.get('strike_price', 0),
                        'spot': 0,  # Will need to get current spot price
                        'vwap': 0,
                        'quality_score': 0,
                        'reason': f"Executed trade - Status: {status}",
                        'support': 0,
                        'resistance': 0,
                        'analysis_timestamp': trade.get('timestamp', ''),
                        'option_type': trade.get('option_type', 'N/A'),
                        'source': 'execution',  # Mark as executed trade
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'target': target,
                        'stoploss': stoploss,
                        'pnl': pnl,
                        'pnl_percentage': pnl_percentage,
                        'status': status
                    }
                    all_trades.append(formatted_trade)

                    # Log detailed trade information
                    if status == 'ACTIVE':
                        logger.info(f"[ACTIVE TRADE] {trade.get('underlying')} {trade.get('strike_price')} {trade.get('option_type')} - Entry: {entry_price}, Current: {current_price}, Target: {target}, SL: {stoploss}, P&L: {pnl:+.2f} ({pnl_percentage:+.2f}%)")
                    elif status == 'TARGET_HIT':
                        logger.info(f"[TARGET HIT] {trade.get('underlying')} {trade.get('strike_price')} {trade.get('option_type')} - Entry: {entry_price}, Exit: {current_price}, P&L: {pnl:+.2f} ({pnl_percentage:+.2f}%)")
                    elif status == 'SL_HIT':
                        logger.info(f"[STOP LOSS HIT] {trade.get('underlying')} {trade.get('strike_price')} {trade.get('option_type')} - Entry: {entry_price}, Exit: {current_price}, P&L: {pnl:+.2f} ({pnl_percentage:+.2f}%)")

        except Exception as e:
            logger.warning(f"Error getting executed trades from manifest: {e}")

        # Log summary
        logger.info(f"[TRADE SUMMARY] Active: {active_trades_count}, Completed: {completed_trades_count}, Total P&L: {total_pnl:+.2f}")

        return jsonify({
            'trades': all_trades,
            'count': len(all_trades),
            'active_count': active_trades_count,
            'completed_count': completed_trades_count,
            'total_pnl': total_pnl,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/market-data')
def get_market_data():
    """API endpoint to get market data for all instruments."""
    if not market_analyzer:
        return jsonify({'error': 'Market Analyzer not connected'}), 500
    
    try:
        market_data = market_analyzer.get_market_data()
        
        # Format market data for JSON response
        formatted_data = {}
        for symbol, data in market_data.items():
            formatted_data[symbol] = {
                'current_price': data.get('current_price', 0),
                'vwap': data.get('vwap', 0),
                'timestamp': data.get('timestamp', '')
            }
        
        return jsonify({
            'market_data': formatted_data,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting market data: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/trade/<trade_id>')
def get_trade_detail(trade_id):
    """API endpoint to get detailed information about a specific trade."""
    if not market_analyzer:
        return jsonify({'error': 'Market Analyzer not connected'}), 500
    
    try:
        trade = market_analyzer.get_trade_by_id(trade_id)
        
        if not trade:
            return jsonify({'error': 'Trade not found'}), 404
        
        return jsonify(trade)
        
    except Exception as e:
        logger.error(f"Error getting trade detail: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/status')
def get_status():
    """API endpoint to get system status."""
    try:
        status = {
            'market_analyzer_running': market_analyzer is not None and market_analyzer.running,
            'timestamp': datetime.now().isoformat(),
            'perfect_trades_count': len(market_analyzer.get_perfect_trades()) if market_analyzer else 0
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/trade-manifest')
def get_trade_manifest():
    """API endpoint to get the complete trade manifest from active_trades.json with thread-safe reading."""
    with file_lock:  # Ensures no concurrent write during read
        try:
            if not os.path.exists(TRADE_MANIFEST_PATH):
                return jsonify({
                    'system_metadata': {
                        'engine_id': '12edf3',
                        'automated_mode': True,
                        'timeframe': '15m',
                        'ema_filter': '9_21_crossover'
                    },
                    'trades': [],
                    'timestamp': datetime.now().isoformat()
                })
            
            with open(TRADE_MANIFEST_PATH, 'r') as f:
                manifest_data = json.load(f)
            
            # Add current timestamp
            manifest_data['timestamp'] = datetime.now().isoformat()
            
            return jsonify(manifest_data)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in trade manifest: {e}")
            return jsonify({
                'system_metadata': {
                    'engine_id': '12edf3',
                    'automated_mode': True,
                    'timeframe': '15m',
                    'ema_filter': '9_21_crossover'
                },
                'trades': [],
                'timestamp': datetime.now().isoformat(),
                'error': 'File corruption detected, using empty state'
            })
        except Exception as e:
            logger.error(f"Error getting trade manifest: {e}")
            return jsonify({'error': str(e)}), 500


@app.route('/api/manual-signals')
def get_manual_signals():
    """API endpoint to get AI-generated manual trading signals."""
    global manual_signals
    with manual_signals_lock:
        # Return signals with most recent first
        signals_reversed = manual_signals[::-1]
        return jsonify({
            'count': len(signals_reversed),
            'timestamp': datetime.now().isoformat(),
            'signals': signals_reversed
        })


@app.route('/api/signals')
def get_signals():
    """API endpoint to get latest scanner signals from web_signals.json."""
    try:
        signals_file = "D:/Traiding_Bot/web_signals.json"

        if not os.path.exists(signals_file):
            logger.info("[SIGNALS] No signals file available yet")
            return jsonify({
                'signals': [],
                'count': 0,
                'timestamp': datetime.now().isoformat(),
                'message': 'No signals available yet'
            })

        with open(signals_file, 'r', encoding='utf-8') as f:
            signals_data = json.load(f)

        signals = signals_data.get('signals', [])
        signal_count = len(signals)

        # Log signal information
        if signal_count > 0:
            latest_signal = signals[0] if signals else None
            if latest_signal:
                symbol = latest_signal.get('symbol', 'N/A')
                direction = latest_signal.get('direction', 'N/A')
                confidence = latest_signal.get('confidence', 0)
                logger.info(f"[SIGNAL UPDATE] {symbol} - {direction} signal, Confidence: {confidence}%, Total Signals: {signal_count}")
        else:
            logger.info("[SIGNAL UPDATE] No active signals")

        signals_data['timestamp'] = datetime.now().isoformat()
        return jsonify(signals_data)

    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return jsonify({
            'signals': [],
            'count': 0,
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 500


@app.route('/api/daily-pnl')
def get_daily_pnl():
    """API endpoint to get daily P&L tracking data."""
    try:
        manifest_path = TRADE_MANIFEST_PATH

        if not os.path.exists(manifest_path):
            logger.info("[P&L] No trades yet - starting fresh")
            return jsonify({
                'realized_pnl': 0.0,
                'unrealized_pnl': 0.0,
                'total_pnl': 0.0,
                'daily_profit_goal': 5000,
                'goal_progress': 0.0,
                'goal_reached': False,
                'active_positions': 0,
                'timestamp': datetime.now().isoformat(),
                'message': 'No trades yet'
            })

        with file_lock:
            with open(manifest_path, 'r') as f:
                manifest_data = json.load(f)

        # Calculate realized P&L from closed trades
        trades = manifest_data.get('trades', [])
        realized_pnl = 0.0
        win_count = 0
        loss_count = 0

        for trade in trades:
            execution = trade.get('execution', {})
            pnl = execution.get('pnl', 0)
            status = trade.get('status', '')

            if status in ['TARGET_HIT', 'SL_HIT', 'MARKET_CLOSE']:
                realized_pnl += pnl
                if pnl > 0:
                    win_count += 1
                else:
                    loss_count += 1

        # Get daily P&L tracking from latest trade if available
        latest_trade = trades[-1] if trades else None
        if latest_trade and 'daily_pnl_tracking' in latest_trade:
            pnl_tracking = latest_trade['daily_pnl_tracking']
            total_pnl = pnl_tracking.get('total_pnl', realized_pnl)
            daily_profit_goal = pnl_tracking.get('daily_profit_goal', 5000)
            goal_progress = pnl_tracking.get('goal_progress', 0.0)
        else:
            total_pnl = realized_pnl
            daily_profit_goal = 5000
            goal_progress = (total_pnl / daily_profit_goal) * 100 if daily_profit_goal > 0 else 0

        goal_reached = total_pnl >= daily_profit_goal

        # Count active positions (not closed)
        active_positions = sum(1 for trade in trades if trade.get('status') == 'ACTIVE')

        # Calculate win rate
        total_completed = win_count + loss_count
        win_rate = (win_count / total_completed * 100) if total_completed > 0 else 0

        # Log P&L information
        logger.info(f"[P&L UPDATE] Realized: {realized_pnl:+.2f}, Total: {total_pnl:+.2f}, Goal: {daily_profit_goal}, Progress: {goal_progress:.1f}%, Active: {active_positions}, Win Rate: {win_rate:.1f}% ({win_count}W/{loss_count}L)")

        return jsonify({
            'realized_pnl': realized_pnl,
            'unrealized_pnl': 0.0,
            'total_pnl': total_pnl,
            'daily_profit_goal': daily_profit_goal,
            'goal_progress': goal_progress,
            'goal_reached': goal_reached,
            'active_positions': active_positions,
            'win_rate': win_rate,
            'win_count': win_count,
            'loss_count': loss_count,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting daily P&L: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """
    Run the Flask web server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Debug mode
    """
    logger.info(f"Starting web interface on {host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    # For testing without market analyzer
    logger.info("Starting web interface in test mode...")
    run_web_server(debug=True)

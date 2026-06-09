"""
Automated Zerodha Login using Kite Connect SDK
Opens browser for login and automatically captures request token
"""

import json
import webbrowser
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
from kiteconnect import KiteConnect

# Load config
import os
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
with open(config_path, 'r') as f:
    config = json.load(f)

api_key = config.get("api_key", "")
api_secret = config.get("api_secret", "")

print("="*70)
print("ZERODHA AUTOMATED LOGIN USING SDK")
print("="*70)
print(f"API Key: {api_key}")
print(f"API Secret: {api_secret[:10]}...")
print("="*70)

# Global variable to store the request token
captured_token = None

class TokenCaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global captured_token
        try:
            # Parse the request URL to extract request_token
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            
            if 'request_token' in params:
                captured_token = params['request_token'][0]
                print(f"Captured request_token: {captured_token}")

                # Send success response
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"""
                <html>
                <head><title>Login Successful</title></head>
                <body>
                    <h1>Login Successful!</h1>
                    <p>Request token captured. You can close this window.</p>
                    <p>The system will automatically generate your access token.</p>
                </body>
                </html>
                """)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No request_token found in URL")
        except Exception as e:
            print(f"Error capturing token: {e}")
            self.send_response(500)
            self.end_headers()

def start_local_server():
    """Start a local server to capture the redirect."""
    server = HTTPServer(('127.0.0.1', 5000), TokenCaptureHandler)
    print("Local server started on http://127.0.0.1:5000")
    server.handle_request()  # Handle one request
    server.server_close()
    print("Local server stopped")

# Generate login URL
login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

print("\nStarting automated login process...")
print(f"Opening browser for Zerodha login...")
print(f"Login URL: {login_url}")
print()

# Start local server in background thread
server_thread = threading.Thread(target=start_local_server)
server_thread.daemon = True
server_thread.start()

# Give server time to start
time.sleep(1)

# Open browser for login
webbrowser.open(login_url)

print("Waiting for login and redirect...")
print("Please login to Zerodha in the browser window...")
print("After login, you'll be redirected back automatically...")
print()

# Wait for token capture (with timeout)
timeout = 120  # 2 minutes
start_time = time.time()

while captured_token is None and (time.time() - start_time) < timeout:
    time.sleep(1)
    if captured_token:
        break

if captured_token:
    print(f"\nRequest token captured: {captured_token}")

    # Exchange for access token using SDK
    try:
        print("\nExchanging request token for access token using SDK...")
        kite = KiteConnect(api_key=api_key)
        data = kite.generate_session(captured_token, api_secret=api_secret)

        if 'access_token' in data:
            access_token = data['access_token']
            user_id = data.get('user_id', 'unknown')

            # Update config
            config['access_token'] = access_token
            config['request_token'] = captured_token
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)

            print("="*70)
            print("SUCCESS! Access token generated and saved")
            print("="*70)
            print(f"Access Token: {access_token}")
            print(f"User ID: {user_id}")
            print(f"Token saved to config.json")
            print("You can now start your trading bot!")
            print("="*70)
        else:
            print("ERROR: No access token in response")
            print(f"Response: {data}")

    except Exception as e:
        print(f"ERROR: {e}")
        print(f"Error type: {type(e).__name__}")
else:
    print("\nERROR: Timeout - No request token captured")
    print("Please try again or use manual token generation")
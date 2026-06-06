import json
import urllib.parse
import http.server
import socketserver
import webbrowser
import threading
import urllib.request

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

api_key = config['api_key']
redirect_uri = config['redirect_uri']

# Generate authorization URL
auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?client_id={api_key}&redirect_uri={urllib.parse.quote(redirect_uri)}"

print("=" * 60)
print("Upstox Access Token Generator")
print("=" * 60)
print(f"Opening browser for authentication...")
print(f"Authorization URL: {auth_url}")
print("=" * 60)

# Global variable to store the token
received_token = None

class TokenHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global received_token
        if 'code' in self.path:
            # Extract the authorization code
            query = self.path.split('?')[1]
            params = urllib.parse.parse_qs(query)
            code = params.get('code', [''])[0]
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            if code:
                self.wfile.write(b"<h1>Authentication Successful!</h1>")
                self.wfile.write(b"<p>Authorization code received. You can close this window.</p>")
                received_token = code
            else:
                self.wfile.write(b"<h1>Authentication Failed</h1>")
                self.wfile.write(b"<p>No authorization code received.</p>")
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Waiting for authentication...</h1>")

# Start local server
port = 8080
handler = TokenHandler

with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
    print(f"Local server started on http://127.0.0.1:{port}")
    
    # Open browser in a separate thread
    def open_browser():
        webbrowser.open(auth_url)
    
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.start()
    
    # Wait for token (timeout after 5 minutes)
    print("Waiting for authorization... (timeout: 5 minutes)")
    httpd.timeout = 300
    
    try:
        httpd.handle_request()
        
        if received_token:
            print(f"\nAuthorization Code received: {received_token}")
            
            # Now exchange the code for access token
            print("\nExchanging authorization code for access token...")
            
            token_url = "https://api.upstox.com/v2/login/authorization/token"
            
            token_data = {
                "code": received_token,
                "client_id": api_key,
                "client_secret": config['api_secret'],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }
            
            data = urllib.parse.urlencode(token_data).encode("utf-8")
            req = urllib.request.Request(token_url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("Accept", "application/json")
            
            try:
                with urllib.request.urlopen(req) as response:
                    res_body = response.read().decode("utf-8")
                    res_json = json.loads(res_body)
                    
                    if res_json.get("status") == "success":
                        access_token = res_json.get("data", {}).get("access_token")
                        
                        if access_token:
                            # Update config
                            config['access_token'] = access_token
                            with open('config.json', 'w') as f:
                                json.dump(config, f, indent=4)
                            
                            print("=" * 60)
                            print("SUCCESS! Access token generated and saved to config.json")
                            print("=" * 60)
                            print(f"Access Token: {access_token}")
                            print("\nYou can now start your trading bot!")
                        else:
                            print("ERROR: No access token in response")
                            print(f"Response: {res_json}")
                    else:
                        print("ERROR: Token exchange failed")
                        print(f"Response: {res_json}")
            except Exception as e:
                print(f"ERROR exchanging token: {e}")
        else:
            print("ERROR: No authorization code received")
            
    except Exception as e:
        print(f"ERROR: {e}")
    
    httpd.server_close()

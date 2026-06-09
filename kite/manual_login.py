"""
Zerodha Kite Connect Access Token Generator
Manual authentication flow for Zerodha
"""

import json
import hashlib
import urllib.request
import urllib.parse

# Load config
import os
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
with open(config_path, 'r') as f:
    config = json.load(f)

api_key = config['api_key']
api_secret = config['api_secret']
redirect_uri = config.get('redirect_uri', 'http://127.0.0.1:5000/')

print("="*60)
print("ZERODHA KITE CONNECT ACCESS TOKEN GENERATOR")
print("="*60)
print(f"API Key: {api_key}")
print(f"API Secret: {api_secret[:10]}...")
print(f"Redirect URI: {redirect_uri}")
print("="*60)

# Step 1: Generate login URL
login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

print("\nSTEP 1: Manual Authentication")
print("-"*60)
print(f"1. Open this URL in your browser:")
print(f"   {login_url}")
print("\n2. Login to your Zerodha account")
print("3. After login, you'll be redirected to a URL like:")
print(f"   {redirect_uri}?request_token=xxxxx")
print("\n4. Copy the 'request_token' parameter from the URL")
print("-"*60)

# Step 2: Get request token from user
request_token = input("\nEnter the request_token from the redirect URL: ").strip()

if not request_token:
    print("ERROR: No request token provided")
    exit(1)

print(f"\nSTEP 2: Exchanging request token for access token...")
print(f"Request Token: {request_token}")

# Step 3: Generate checksum and exchange for access token
try:
    checksum = f"{api_key}{request_token}{api_secret}"
    checksum = hashlib.sha256(checksum.encode('utf-8')).hexdigest()

    token_url = "https://kite.zerodha.com/api/session"
    data = {
        "api_key": api_key,
        "request_token": request_token,
        "checksum": checksum
    }

    encoded_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(token_url, data=encoded_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    print(f"Checksum: {checksum[:20]}...")

    with urllib.request.urlopen(req) as response:
        res_body = response.read().decode('utf-8')
        res_json = json.loads(res_body)

        print(f"\nZerodha API Response: {res_json}")

        if 'data' in res_json and 'access_token' in res_json['data']:
            access_token = res_json['data']['access_token']
            user_id = res_json['data'].get('user_id', 'unknown')

            # Update config
            config['access_token'] = access_token
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)

            print("="*60)
            print("SUCCESS! Access token generated and saved")
            print("="*60)
            print(f"Access Token: {access_token}")
            print(f"User ID: {user_id}")
            print(f"\nToken saved to config.json")
            print("You can now start your trading bot!")
        else:
            print("ERROR: Token generation failed")
            print(f"Response: {res_json}")

except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} - {e.reason}")
    try:
        error_body = e.read().decode('utf-8')
        print(f"Error response body: {error_body}")
    except:
        pass
except Exception as e:
    print(f"ERROR: {e}")

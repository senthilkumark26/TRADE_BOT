import json
import urllib.parse

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

api_key = config['api_key']
api_secret = config['api_secret']
redirect_uri = config['redirect_uri']

# Generate authorization URL
auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?client_id={api_key}&redirect_uri={urllib.parse.quote(redirect_uri)}"

print("=" * 70)
print("Upstox Manual Authentication Guide")
print("=" * 70)
print("\nStep 1: Click on this authorization link:")
print(f"\n{auth_url}\n")
print("Step 2: Login to Upstox with your credentials")
print("Step 3: After successful login, you'll be redirected to:")
print(f"   {redirect_uri}?code=YOUR_AUTH_CODE")
print("\nStep 4: Copy the 'code' parameter from the redirected URL")
print("Step 5: Paste it below when prompted")
print("=" * 70)

# Open browser automatically
import webbrowser
print("\nOpening browser in 3 seconds...")
import time
time.sleep(3)
webbrowser.open(auth_url)

# Get authorization code from user
auth_code = input("\nEnter the authorization code from the redirected URL: ").strip()

if auth_code:
    print(f"\nAuthorization code received: {auth_code}")
    print("\nExchanging for access token...")
    
    import urllib.request
    
    token_url = "https://api.upstox.com/v2/login/authorization/token"
    
    token_data = {
        "code": auth_code,
        "client_id": api_key,
        "client_secret": api_secret,
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
                    
                    print("=" * 70)
                    print("SUCCESS! Access token generated and saved to config.json")
                    print("=" * 70)
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
    print("No authorization code provided. Process cancelled.")

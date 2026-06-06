import logging
import json
from kiteconnect import KiteConnect

logging.basicConfig(level=logging.INFO)

# 1. Load your local configurations
with open("config.json", "r") as f:
    config = json.load(f)

api_key = config["api_key"]
api_secret = config["api_secret"]

# 2. Active browser token from morning login redirect
request_token_here = "g4326O18mggtqSZQZmxyzZR68kAsKi8F"

try:
    print("Executing secure session exchange via official Kite Connect SDK...")
    print(f"Request Token: {request_token_here}")
    print(f"API Key: {api_key}")
    
    # Initialize official SDK instance
    kite = KiteConnect(api_key=api_key)
    
    # Use official SDK method to generate session
    data = kite.generate_session(request_token_here, api_secret=api_secret)
    
    print(f"SDK Response: {data}")
    
    if 'access_token' in data:
        access_token = data['access_token']
        
        # Update config matrix safely
        config["access_token"] = access_token
        config["paper_trading"] = True
        
        with open("config.json", "w") as f:
            json.dump(config, f, indent=4)
        
        print("==========================================================")
        print("SUCCESS: Real Zerodha Pipeline Link Authenticated!")
        print(f"Token Saved: {access_token[:15]}...")
        print("==========================================================")
    else:
        print("ERROR: No access token in response")
        print(f"Response: {data}")

except Exception as e:
    print(f"ERROR: Session Generation Error: {str(e)}")
    import traceback
    traceback.print_exc()
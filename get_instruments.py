import json
import urllib.request
import urllib.parse

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

access_token = config.get('access_token', '')

headers = {
    'accept': 'application/json',
    'Authorization': f'Bearer {access_token}',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

print("Fetching instrument master from Upstox...")
print("=" * 70)

try:
    # Get instrument master for MCX
    url = "https://api.upstox.com/v2/market/instruments"
    params = {
        'exchange': 'MCX_FO',
        'instrument_key': 'MCX_FO'
    }
    
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full_url, headers=headers, method="GET")
    
    with urllib.request.urlopen(req) as response:
        res_body = response.read().decode("utf-8")
        
        # Save to file
        with open('mcx_instruments.json', 'w') as f:
            f.write(res_body)
        
        print(f"Successfully saved MCX instruments to mcx_instruments.json")
        
        # Try to parse and search for GOLDM
        lines = res_body.split('\n')
        goldm_found = False
        
        print("\nSearching for GOLDM instruments...")
        print("=" * 70)
        
        for line in lines:
            if 'GOLDM' in line.upper():
                print(line)
                goldm_found = True
                
        if not goldm_found:
            print("No GOLDM instruments found in MCX_FO segment")
            
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.reason}")
    try:
        error_body = e.read().decode('utf-8')
        print(f"Error details: {error_body}")
    except:
        pass
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 70)

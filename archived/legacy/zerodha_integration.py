"""
Zerodha Kite Connect Integration
Separate module for Zerodha API - can be swapped with Upstox integration
"""

import json
import logging
import urllib.request
import urllib.parse
import hashlib
import hmac
import base64
from typing import Dict, Any, List, Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class ZerodhaIntegration:
    """
    Zerodha Kite Connect API integration
    Can be swapped with Upstox integration in the trading bot
    """
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize Zerodha Kite Connect integration
        
        Args:
            api_key: Zerodha API key
            api_secret: Zerodha API secret
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.kite.trade"
        self.access_token = None
        self.session_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Try to load existing token from config
        self.load_token()
    
    def generate_login_url(self) -> str:
        """
        Generate Kite Connect login URL for manual authentication
        
        Returns:
            Login URL that user can open in browser
        """
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"
        logger.info(f"Login URL: {login_url}")
        logger.info("Open this URL in browser, login, and copy the 'request_token' from the redirect URL")
        return login_url
    
    def generate_access_token(self, request_token: str) -> bool:
        """
        Exchange request token for access token

        Args:
            request_token: Token received from Kite Connect after login

        Returns:
            True if successful, False otherwise
        """
        try:
            checksum = f"{self.api_key}{request_token}{self.api_secret}"
            checksum = hashlib.sha256(checksum.encode('utf-8')).hexdigest()

            token_url = f"{self.base_url}/api/session"
            data = {
                "api_key": self.api_key,
                "request_token": request_token,
                "checksum": checksum
            }

            encoded_data = urllib.parse.urlencode(data).encode('utf-8')
            req = urllib.request.Request(token_url, data=encoded_data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            logger.info(f"Requesting access token with request_token: {request_token}")
            logger.info(f"Checksum: {checksum[:20]}...")

            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)

                logger.info(f"Zerodha API Response: {res_json}")

                if 'data' in res_json and 'access_token' in res_json['data']:
                    self.access_token = res_json['data']['access_token']
                    logger.info(f"✓ Access token generated successfully")
                    logger.info(f"Token: {self.access_token[:20]}...")
                    return True
                else:
                    logger.error(f"Token generation failed: {res_json}")
                    return False

        except urllib.error.HTTPError as e:
            logger.error(f"HTTP Error: {e.code} - {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                logger.error(f"Error response body: {error_body}")
            except:
                pass
            return False
        except Exception as e:
            logger.error(f"Error generating access token: {e}")
            return False
    
    def set_access_token(self, access_token: str):
        """Set access token manually"""
        self.access_token = access_token
        logger.info(f"✓ Access token set manually")
    
    def save_token(self, config_file: str = "config.json"):
        """Save access token to config file"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            config['access_token'] = self.access_token
            config['api_key'] = self.api_key
            config['api_secret'] = self.api_secret
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
            
            logger.info(f"✓ Token saved to {config_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving token: {e}")
            return False
    
    def load_token(self, config_file: str = "config.json"):
        """Load access token from config file"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            if 'access_token' in config and config['access_token']:
                self.access_token = config['access_token']
                logger.info(f"✓ Token loaded from {config_file}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Could not load token from config: {e}")
            return False
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with authentication"""
        headers = self.session_headers.copy()
        if self.access_token:
            headers['Authorization'] = f'token {self.api_key}:{self.access_token}'
        return headers
    
    def get_live_quotes(self, instrument_keys: List[str]) -> Dict[str, Any]:
        """
        Get live quotes for instruments

        Args:
            instrument_keys: List of Zerodha instrument keys (e.g., ['NSE:NIFTY', 'NSE:NIFTYBANK'])

        Returns:
            Dictionary with live quotes data
        """
        if not self.access_token:
            logger.error("No access token available")
            return {}

        try:
            # Build URL with multiple i parameters (one per instrument)
            params = []
            for key in instrument_keys:
                # URL encode each instrument key
                encoded_key = urllib.parse.quote(key)
                params.append(f"i={encoded_key}")

            url = f"{self.base_url}/quote/ltp?{'&'.join(params)}"

            logger.info(f"Requesting URL: {url}")
            logger.info(f"Headers: {self.get_headers()}")

            req = urllib.request.Request(url, headers=self.get_headers(), method="GET")
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)

                logger.info(f"RAW ZERODHA RESPONSE: {res_json}")

                if res_json.get('status') == 'success':
                    return res_json.get('data', {})
                else:
                    logger.error(f"Quote failed: {res_json}")
                    return {}

        except urllib.error.HTTPError as e:
            logger.error(f"HTTP Error: {e.code} - {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                logger.error(f"Error response body: {error_body}")
            except:
                pass
            return {}
        except Exception as e:
            logger.error(f"Error fetching quotes: {e}")
            return {}
    
    def get_instruments(self) -> List[Dict[str, Any]]:
        """
        Get instruments list from Zerodha
        Returns list of instruments
        """
        if not self.access_token:
            logger.error("No access token available")
            return []
        
        try:
            url = f"{self.base_url}/api/instruments"
            req = urllib.request.Request(url, headers=self.get_headers(), method="GET")
            
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode("utf-8")
                instruments = json.loads(res_body)
                logger.info(f"✓ Loaded {len(instruments)} instruments from Zerodha")
                return instruments
                
        except Exception as e:
            logger.error(f"Error fetching instruments: {e}")
            return []
    
    def get_historical_data(self, instrument_token: str, from_date: str, to_date: str, interval: str = "day") -> List[Dict]:
        """
        Get historical candle data
        
        Args:
            instrument_token: Zerodha instrument token
            from_date: From date (YYYY-MM-DD)
            to_date: To date (YYYY-MM-DD)
            interval: candle interval (minute, day, week, month)
            
        Returns:
            List of historical candles
        """
        if not self.access_token:
            logger.error("No access token available")
            return []
        
        try:
            url = f"{self.base_url}/api/historical/candle/{instrument_token}/{interval}/{from_date}/{to_date}"
            req = urllib.request.Request(url, headers=self.get_headers(), method="GET")
            
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode("utf-8")
                data = json.loads(res_body)
                
                if data.get('status') == 'success':
                    candles = data['data']['candles']
                    logger.info(f"✓ Loaded {len(candles)} candles for {instrument_token}")
                    return candles
                else:
                    logger.error(f"Historical data failed: {data}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return []
    
    def get_profile(self) -> Dict[str, Any]:
        """Get user profile information"""
        if not self.access_token:
            logger.error("No access token available")
            return {}
        
        try:
            url = f"{self.base_url}/api/user/profile"
            req = urllib.request.Request(url, headers=self.get_headers(), method="GET")
            
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode("utf-8")
                data = json.loads(res_body)
                
                if data.get('status') == 'success':
                    logger.info(f"✓ User profile loaded")
                    return data['data']
                else:
                    logger.error(f"Profile failed: {data}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            return {}


# Convenience functions
def create_zerodha_client(api_key: str, api_secret: str) -> ZerodhaIntegration:
    """Create and return a Zerodha client"""
    return ZerodhaIntegration(api_key, api_secret)


if __name__ == "__main__":
    # Test Zerodha integration
    print("Testing Zerodha Integration...")
    
    # Your credentials
    api_key = "e5qiy37bu9l3o7hi"
    api_secret = "3hfgragrkhgm84j7cbtya28iupn5kufp"
    
    client = ZerodhaIntegration(api_key, api_secret)
    
    # Generate login URL
    print("\n" + "="*60)
    print("STEP 1: Get Login URL")
    print("="*60)
    login_url = client.generate_login_url()
    print(f"\n1. Open this URL in browser: {login_url}")
    print("2. Login to Zerodha")
    print("3. Copy the 'request_token' from the redirect URL")
    print("4. Run the token exchange script")
    print("="*60)

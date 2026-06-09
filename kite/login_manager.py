"""
Kite Login Manager - Centralized authentication for all trading bots
Checks login status and triggers auto-login if needed
"""

import json
import os
import logging
from kiteconnect import KiteConnect

logger = logging.getLogger(__name__)

class LoginManager:
    """Manages Kite Connect authentication for all trading bots"""
    
    def __init__(self, config_path=None):
        """
        Initialize Login Manager
        
        Args:
            config_path: Path to config.json (defaults to parent directory)
        """
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        
        self.config_path = config_path
        self.config = self._load_config()
        
    def _load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return None
    
    def _save_config(self):
        """Save configuration to config.json"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False
    
    def check_login_status(self):
        """
        Check if current login credentials are valid
        
        Returns:
            dict: {'valid': bool, 'message': str, 'needs_login': bool}
        """
        if not self.config:
            return {'valid': False, 'message': 'Config not loaded', 'needs_login': True}
        
        api_key = self.config.get('api_key', '')
        access_token = self.config.get('access_token', '')
        
        # Check if credentials are placeholders
        if api_key in ['YOUR_API_KEY_HERE', ''] or access_token in ['YOUR_ACCESS_TOKEN_HERE', '']:
            return {
                'valid': False, 
                'message': 'API credentials are placeholders', 
                'needs_login': True
            }
        
        # Try to validate credentials with a simple API call
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            
            # Try to get profile to validate credentials
            profile = kite.profile()
            
            if profile and 'user_id' in profile:
                return {
                    'valid': True,
                    'message': f"Login valid for user: {profile.get('user_id', 'unknown')}",
                    'needs_login': False
                }
            else:
                return {
                    'valid': False,
                    'message': 'Invalid access token',
                    'needs_login': True
                }
                
        except Exception as e:
            error_msg = str(e)
            if 'Incorrect' in error_msg or 'invalid' in error_msg.lower():
                return {
                    'valid': False,
                    'message': f'Invalid credentials: {error_msg}',
                    'needs_login': True
                }
            else:
                return {
                    'valid': False,
                    'message': f'API error: {error_msg}',
                    'needs_login': True
                }
    
    def trigger_auto_login(self):
        """
        Trigger the auto-login process
        
        Returns:
            dict: {'success': bool, 'message': str}
        """
        logger.info("="*80)
        logger.info("TRIGGERING AUTO-LOGIN PROCESS")
        logger.info("="*80)
        
        try:
            # Import and run the auto_login script
            import subprocess
            import sys
            
            auto_login_path = os.path.join(os.path.dirname(__file__), 'auto_login.py')
            
            logger.info(f"Running auto-login from: {auto_login_path}")
            
            # Run auto_login.py
            result = subprocess.run(
                [sys.executable, auto_login_path],
                capture_output=True,
                text=True,
                timeout=120  # 2 minutes timeout
            )
            
            # Reload config after login attempt
            self.config = self._load_config()
            
            if result.returncode == 0:
                # Check if login was successful
                login_status = self.check_login_status()
                if login_status['valid']:
                    return {
                        'success': True,
                        'message': 'Auto-login completed successfully'
                    }
                else:
                    return {
                        'success': False,
                        'message': f'Auto-login completed but credentials invalid: {login_status["message"]}'
                    }
            else:
                return {
                    'success': False,
                    'message': f'Auto-login failed: {result.stderr}'
                }
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Auto-login timed out after 2 minutes'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Auto-login error: {str(e)}'
            }
    
    def ensure_login(self, max_attempts=2):
        """
        Ensure login is valid, trigger auto-login if needed
        
        Args:
            max_attempts: Maximum number of login attempts
            
        Returns:
            dict: {'success': bool, 'message': str}
        """
        logger.info("Checking login status...")
        
        # Check current login status
        login_status = self.check_login_status()
        
        if login_status['valid']:
            logger.info(f"✓ Login valid: {login_status['message']}")
            return {'success': True, 'message': login_status['message']}
        
        logger.warning(f"✗ Login invalid: {login_status['message']}")
        logger.info("Login required. Triggering auto-login...")
        
        # Try auto-login
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Login attempt {attempt}/{max_attempts}")
            
            login_result = self.trigger_auto_login()
            
            if login_result['success']:
                # Verify login after auto-login
                login_status = self.check_login_status()
                if login_status['valid']:
                    logger.info(f"✓ Login successful after attempt {attempt}")
                    return {'success': True, 'message': f'Login successful: {login_status["message"]}'}
            
            if attempt < max_attempts:
                logger.warning(f"Attempt {attempt} failed: {login_result['message']}")
                logger.info("Retrying...")
            else:
                logger.error(f"All {max_attempts} login attempts failed")
                return {
                    'success': False,
                    'message': f'Failed after {max_attempts} attempts: {login_result["message"]}'
                }
        
        return {'success': False, 'message': 'Login failed'}


def get_authenticated_kite_client(config_path=None):
    """
    Get an authenticated Kite client, handling login if needed
    
    Args:
        config_path: Path to config.json
        
    Returns:
        tuple: (kite_client, success, message)
    """
    login_manager = LoginManager(config_path)
    
    # Ensure login is valid
    login_result = login_manager.ensure_login()
    
    if not login_result['success']:
        return None, False, login_result['message']
    
    # Create and return authenticated Kite client
    try:
        from kite.kite_client import KiteClient
        
        config = login_manager.config
        kite_client = KiteClient(
            api_key=config.get('api_key', ''),
            access_token=config.get('access_token', ''),
            paper_trading=config.get('paper_trading', True)
        )
        
        return kite_client, True, 'Kite client authenticated successfully'
        
    except Exception as e:
        return None, False, f'Error creating Kite client: {str(e)}'


# Convenience function for bots to use
def ensure_authenticated_bot(config_path=None):
    """
    Ensure bot is authenticated before starting trading
    This is the main function bots should call
    
    Args:
        config_path: Path to config.json
        
    Returns:
        dict: {'success': bool, 'message': str, 'kite_client': object or None}
    """
    logger.info("="*80)
    logger.info("BOT AUTHENTICATION CHECK")
    logger.info("="*80)
    
    login_manager = LoginManager(config_path)
    
    # Check and ensure login
    login_result = login_manager.ensure_login()
    
    if not login_result['success']:
        logger.error(f"Authentication failed: {login_result['message']}")
        logger.error("Bot cannot start without valid authentication")
        return {
            'success': False,
            'message': login_result['message'],
            'kite_client': None
        }
    
    # Create authenticated Kite client
    try:
        from kite.kite_client import KiteClient
        
        config = login_manager.config
        kite_client = KiteClient(
            api_key=config.get('api_key', ''),
            access_token=config.get('access_token', ''),
            paper_trading=config.get('paper_trading', True)
        )
        
        logger.info("✓ Bot authentication successful")
        logger.info("="*80)
        
        return {
            'success': True,
            'message': login_result['message'],
            'kite_client': kite_client
        }
        
    except Exception as e:
        logger.error(f"Error creating authenticated client: {str(e)}")
        return {
            'success': False,
            'message': f'Client creation error: {str(e)}',
            'kite_client': None
        }


if __name__ == "__main__":
    # Test the login manager
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Login Manager...")
    result = ensure_authenticated_bot()
    
    if result['success']:
        print(f"✓ Success: {result['message']}")
        print(f"✓ Kite client ready: {result['kite_client'] is not None}")
    else:
        print(f"✗ Failed: {result['message']}")
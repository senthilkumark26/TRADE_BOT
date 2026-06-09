"""
Expiry Auto-Switch Engine - Production-Ready Service
Always picks correct trading expiry automatically
Handles weekly expiry, expiry day (Thursday), post-expiry rollover
No manual intervention needed
"""

import logging
from datetime import datetime, date
from datetime import time as datetime_time

logger = logging.getLogger(__name__)


class ExpiryManager:
    """
    Expiry Auto-Switch Engine - Production-Ready
    Always picks correct trading expiry automatically
    Handles weekly expiry, expiry day (Thursday), post-expiry rollover
    No manual intervention needed
    """
    
    def __init__(self, cutoff_hour=15, cutoff_minute=20):
        """
        Initialize ExpiryManager with cutoff time.
        Default: 3:20 PM (after market closes on expiry day)
        
        Args:
            cutoff_hour: Hour for cutoff time (default 15 = 3 PM)
            cutoff_minute: Minute for cutoff time (default 20)
        """
        self.cutoff_time = datetime_time(cutoff_hour, cutoff_minute)
        logger.info(f"ExpiryManager initialized with cutoff time: {cutoff_hour}:{cutoff_minute:02d}")
    
    def get_expiries(self, options):
        """
        Get all unique expiries from options, sorted.
        
        Args:
            options: List of option instruments with expiry field
            
        Returns:
            Sorted list of unique expiry dates
        """
        expiries = sorted(set(o.get("expiry") for o in options if o.get("expiry")))
        logger.debug(f"Found {len(expiries)} unique expiries: {expiries}")
        return expiries
    
    def get_current_expiry(self, options):
        """
        Find current trading expiry with auto-switch logic.
        
        Logic:
        1. Get all future expiries
        2. Pick nearest future expiry
        3. If today is expiry day and after cutoff, switch to next expiry
        
        Args:
            options: List of option instruments with expiry field
            
        Returns:
            Current expiry date or None
        """
        today = datetime.now().date()
        now = datetime.now().time()
        
        expiries = self.get_expiries(options)
        
        # Filter future expiries only
        future_expiries = [exp for exp in expiries if exp >= today]
        
        if not future_expiries:
            logger.warning("No future expiries found")
            return None
        
        nearest = future_expiries[0]
        
        # Expiry day switch logic
        if nearest == today:
            # If it's expiry day and after cutoff, switch to next expiry
            if now >= self.cutoff_time:
                if len(future_expiries) > 1:
                    logger.info(f"Expiry day detected, after cutoff {self.cutoff_time}, switching to next expiry: {future_expiries[1]}")
                    return future_expiries[1]
                else:
                    logger.warning("Expiry day but no next expiry available")
        
        return nearest
    
    def filter_options(self, options):
        """
        Filter options to current expiry only.
        
        Args:
            options: List of option instruments with expiry field
            
        Returns:
            Tuple of (filtered_options, current_expiry)
        """
        expiry = self.get_current_expiry(options)
        
        if not expiry:
            logger.warning("Could not determine current expiry, using all options")
            return options, None
        
        expiry_str = expiry.strftime('%Y-%m-%d') if isinstance(expiry, date) else str(expiry)
        filtered = [o for o in options if o.get("expiry") == expiry]
        
        if len(filtered) == 0:
            logger.warning(f"No options found for selected expiry {expiry_str}, using all options")
            return options, expiry
        
        logger.info(f"Filtered to expiry: {expiry_str} ({len(filtered)} options)")
        return filtered, expiry
    
    def get_expiry_status(self, options):
        """
        Get expiry status information for debugging.
        
        Args:
            options: List of option instruments with expiry field
            
        Returns:
            Dict with expiry status information
        """
        today = datetime.now().date()
        now = datetime.now().time()
        
        expiries = self.get_expiries(options)
        current_expiry = self.get_current_expiry(options)
        
        future_expiries = [exp for exp in expiries if exp >= today]
        
        status = {
            "today": today,
            "now": now,
            "cutoff_time": self.cutoff_time,
            "all_expiries": expiries,
            "future_expiries": future_expiries,
            "current_expiry": current_expiry,
            "is_expiry_day": current_expiry == today if current_expiry else False,
            "is_after_cutoff": now >= self.cutoff_time
        }
        
        return status

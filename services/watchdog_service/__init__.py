"""
Watchdog Service - Monitors health of all trading services
Provides continuous monitoring, health checks, and alerts
"""

from .service import WatchdogService

__all__ = ['WatchdogService']

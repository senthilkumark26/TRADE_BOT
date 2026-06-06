"""
Trade Manager Service - Live trade execution and management
Manages: Active trades, P&L tracking, trailing SL, kill switch, live dashboard
"""

from .service import TradeManagerService

__version__ = "1.0.0"
__all__ = ["TradeManagerService"]

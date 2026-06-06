"""
Breakout Entry Service - Microservice for breakout detection and entry timing
Handles: Breakout detection, strength classification, entry timing, strike selection
"""

from .service import BreakoutEntryService

__version__ = "1.0.0"
__all__ = ["BreakoutEntryService"]

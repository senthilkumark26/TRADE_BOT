"""
Consensus Service - Coordinates between independent services for trade decisions
Combines: Market analysis + Breakout detection → Consensus → LLM final decision
"""

from .service import ConsensusService

__version__ = "1.0.0"
__all__ = ["ConsensusService"]

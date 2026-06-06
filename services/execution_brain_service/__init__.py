"""
Execution Brain Service - Final decision authority for trade execution
Evaluates: Bias alignment, breakout strength, OI confirmation, distance to support/resistance
Output: EXECUTE / PROBING / LLM_REVIEW / SKIP
"""

from .service import ExecutionBrainService

__version__ = "1.0.0"
__all__ = ["ExecutionBrainService"]

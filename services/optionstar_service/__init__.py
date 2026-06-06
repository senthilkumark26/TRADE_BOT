"""
OptionStar Service Package
Protected microservice for institutional OI analysis
"""

from .service import OptionStarService, get_optionstar_service
from .service import calculate_institutional_walls, generate_trade

__all__ = [
    'OptionStarService',
    'get_optionstar_service', 
    'calculate_institutional_walls',
    'generate_trade'
]

__version__ = '1.0.0'
__service_name__ = 'optionstar_service'
__protection_level__ = 'CRITICAL'
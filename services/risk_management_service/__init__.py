"""
Risk Management Service Package
Protected microservice for capital protection and risk management
"""

from .service import RiskManagementService, get_risk_management_service

__all__ = [
    'RiskManagementService',
    'get_risk_management_service'
]

__version__ = '1.0.0'
__service_name__ = 'risk_management_service'
__protection_level__ = 'CRITICAL'
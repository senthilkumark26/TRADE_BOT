"""
Register services with Code Manager
"""

from code_manager import code_manager

def register_all_services():
    """Register all project services with Code Manager."""
    
    print("=" * 80)
    print("REGISTERING SERVICES WITH CODE MANAGER")
    print("=" * 80)
    
    # Register Expiry Manager
    success, message = code_manager.register_service(
        service_name="expiry_manager",
        service_file="expiry_manager.py",
        description="Expiry Auto-Switch Engine - Automatically selects correct trading expiry",
        version="1.0",
        dependencies=[]
    )
    print(f"Expiry Manager: {message}")
    
    # Register Kite Service
    success, message = code_manager.register_service(
        service_name="kite_service",
        service_file="kite_service.py",
        description="Kite Service - Centralized KiteConnect integration with rate limiting",
        version="1.0",
        dependencies=[]
    )
    print(f"Kite Service: {message}")
    
    # Register Code Manager itself (self-registration)
    success, message = code_manager.register_service(
        service_name="code_manager",
        service_file="code_manager.py",
        description="Code Manager - Code governance system with approval workflow",
        version="1.0",
        dependencies=[]
    )
    print(f"Code Manager: {message}")
    
    print("\n" + "=" * 80)
    print("SERVICES REGISTERED SUCCESSFULLY")
    print("=" * 80)
    
    # List all registered services
    print("\nRegistered Services:")
    services = code_manager.list_services()
    
    for service in services:
        print(f"\n  Service: {service['service_name']}")
        print(f"  File: {service['service_file']}")
        print(f"  Version: {service['version']}")
        print(f"  Description: {service['description']}")
        print(f"  Dependencies: {', '.join(service['dependencies']) if service['dependencies'] else 'None'}")
        print(f"  Registered: {service['registered_at']}")
        print(f"  Status: {service['status']}")


if __name__ == "__main__":
    register_all_services()

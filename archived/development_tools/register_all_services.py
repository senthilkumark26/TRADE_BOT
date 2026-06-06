"""
Register All Recommended Services with Code Manager
"""

from code_manager import code_manager

def register_recommended_services():
    """Register all recommended project services with Code Manager."""
    
    print("=" * 80)
    print("REGISTERING RECOMMENDED SERVICES WITH CODE MANAGER")
    print("=" * 80)
    
    # ==================== LLM INTEGRATION SERVICES ====================
    
    # Register Gemini Integration
    success, message = code_manager.register_service(
        service_name="gemini_integration",
        service_file="gemini_integration.py",
        description="Gemini LLM integration service for market analysis",
        version="1.0",
        dependencies=[]
    )
    print(f"Gemini Integration: {message}")
    
    # Register Ollama Integration
    success, message = code_manager.register_service(
        service_name="ollama_integration",
        service_file="ollama_integration.py",
        description="Ollama LLM integration service for local AI models",
        version="1.0",
        dependencies=[]
    )
    print(f"Ollama Integration: {message}")
    
    # Register OpenAI Integration
    success, message = code_manager.register_service(
        service_name="openai_integration",
        service_file="openai_integration.py",
        description="OpenAI LLM integration service for GPT models",
        version="1.0",
        dependencies=[]
    )
    print(f"OpenAI Integration: {message}")
    
    # ==================== LLM ANALYZER SERVICES ====================
    
    # Register LLM Market Analyzer
    success, message = code_manager.register_service(
        service_name="llm_market_analyzer",
        service_file="llm_market_analyzer.py",
        description="LLM-based market analysis service for trade evaluation",
        version="1.0",
        dependencies=["gemini_integration"]
    )
    print(f"LLM Market Analyzer: {message}")
    
    # Register LLM State Worker
    success, message = code_manager.register_service(
        service_name="llm_state_worker",
        service_file="llm_state_worker.py",
        description="LLM state management worker for decoupled LLM operations",
        version="1.0",
        dependencies=["llm_market_analyzer"]
    )
    print(f"LLM State Worker: {message}")
    
    # Register LLM Worker
    success, message = code_manager.register_service(
        service_name="llm_worker",
        service_file="llm_worker.py",
        description="LLM worker service for background LLM processing",
        version="1.0",
        dependencies=["llm_market_analyzer"]
    )
    print(f"LLM Worker: {message}")
    
    # ==================== MARKET ANALYSIS SERVICES ====================
    
    # Register Market Analyzer
    success, message = code_manager.register_service(
        service_name="market_analyzer",
        service_file="market_analyzer.py",
        description="Market analysis service for technical analysis and signal generation",
        version="1.0",
        dependencies=["kite_service"]
    )
    print(f"Market Analyzer: {message}")
    
    # Register Market Signal Analyzer
    success, message = code_manager.register_service(
        service_name="market_signal_analyzer",
        service_file="market_signal_analyzer.py",
        description="Market signal analysis service for trade signal evaluation",
        version="1.0",
        dependencies=["market_analyzer"]
    )
    print(f"Market Signal Analyzer: {message}")
    
    # Register Engine 1 Market Analyzer
    success, message = code_manager.register_service(
        service_name="engine1_market_analyzer",
        service_file="engine1_market_analyzer.py",
        description="Engine 1 market analyzer - Breakout detection and signal generation",
        version="1.0",
        dependencies=["kite_service", "expiry_manager"]
    )
    print(f"Engine 1 Market Analyzer: {message}")
    
    # Register Engine 2 LLM Worker
    success, message = code_manager.register_service(
        service_name="engine2_llm_worker",
        service_file="engine2_llm_worker.py",
        description="Engine 2 LLM worker - LLM-based trade evaluation and scoring",
        version="1.0",
        dependencies=["llm_market_analyzer", "engine1_market_analyzer"]
    )
    print(f"Engine 2 LLM Worker: {message}")
    
    # ==================== RISK MANAGEMENT SERVICES ====================
    
    # Register Execution Risk Manager
    success, message = code_manager.register_service(
        service_name="execution_risk_manager",
        service_file="execution_risk_manager.py",
        description="Execution risk management service for trade risk assessment",
        version="1.0",
        dependencies=["kite_service"]
    )
    print(f"Execution Risk Manager: {message}")
    
    # ==================== TRADE MANAGEMENT SERVICES ====================
    
    # Register Trade Queue System
    success, message = code_manager.register_service(
        service_name="trade_queue_system",
        service_file="trade_queue_system.py",
        description="Trade queue system for event-driven trade management",
        version="1.0",
        dependencies=["llm_market_analyzer"]
    )
    print(f"Trade Queue System: {message}")
    
    # Register Trade Memory
    success, message = code_manager.register_service(
        service_name="trade_memory",
        service_file="trade_memory.py",
        description="Trade memory service for storing and retrieving trade history",
        version="1.0",
        dependencies=[]
    )
    print(f"Trade Memory: {message}")
    
    # Register Trade Pipeline
    success, message = code_manager.register_service(
        service_name="trade_pipeline",
        service_file="trade_pipeline.py",
        description="Trade pipeline service for coordinating trade execution",
        version="1.0",
        dependencies=["trade_queue_system"]
    )
    print(f"Trade Pipeline: {message}")
    
    # ==================== SIMULATION SERVICES ====================
    
    # Register Demo Market Simulator
    success, message = code_manager.register_service(
        service_name="demo_market_simulator",
        service_file="demo_market_simulator.py",
        description="Demo market simulator for testing without live data",
        version="1.0",
        dependencies=[]
    )
    print(f"Demo Market Simulator: {message}")
    
    # ==================== TRADING SERVICES ====================
    
    # Register Single Strike Trader
    success, message = code_manager.register_service(
        service_name="single_strike_trader",
        service_file="single_strike_trader.py",
        description="Single strike trading service for focused option trading",
        version="1.0",
        dependencies=["kite_service", "expiry_manager"]
    )
    print(f"Single Strike Trader: {message}")
    
    # Register Streamlit Single Strike Trader
    success, message = code_manager.register_service(
        service_name="streamlit_single_strike_trader",
        service_file="streamlit_single_strike_trader.py",
        description="Streamlit-based single strike trading UI service",
        version="1.0",
        dependencies=["single_strike_trader"]
    )
    print(f"Streamlit Single Strike Trader: {message}")
    
    # Register Web Interface
    success, message = code_manager.register_service(
        service_name="web_interface",
        service_file="web_interface.py",
        description="Web interface service for trading bot monitoring",
        version="1.0",
        dependencies=["trading_bot"]
    )
    print(f"Web Interface: {message}")
    
    # ==================== CORE TRADING BOT ====================
    
    # Register Trading Bot
    success, message = code_manager.register_service(
        service_name="trading_bot",
        service_file="trading_bot.py",
        description="Main trading bot service - Event-driven trading system",
        version="1.0",
        dependencies=[
            "kite_service",
            "expiry_manager",
            "llm_market_analyzer",
            "engine1_market_analyzer",
            "engine2_llm_worker",
            "trade_queue_system"
        ]
    )
    print(f"Trading Bot: {message}")
    
    print("\n" + "=" * 80)
    print("ALL RECOMMENDED SERVICES REGISTERED SUCCESSFULLY")
    print("=" * 80)
    
    # List all registered services
    print("\nRegistered Services:")
    services = code_manager.list_services()
    
    for service in services:
        print(f"\n  Service: {service['service_name']}")
        print(f"  File: {service['service_file']}")
        print(f"  Version: {service['version']}")
        print(f"  Dependencies: {', '.join(service['dependencies']) if service['dependencies'] else 'None'}")


if __name__ == "__main__":
    register_recommended_services()

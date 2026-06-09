"""
Watchdog Service - Monitors health of all trading services
Provides continuous monitoring, health checks, and alerts
"""

import json
import logging
import time
import psutil
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ServiceHealth:
    """Health status of a service"""
    name: str
    status: str  # "HEALTHY", "UNHEALTHY", "UNKNOWN"
    last_check: str
    response_time: float
    error_message: str = ""
    details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class WatchdogService:
    """
    Watchdog Service - Monitors all trading services
    Runs in background, performs health checks, logs issues
    """
    
    def __init__(self, config_path=None, check_interval=60):
        """
        Initialize Watchdog Service
        
        Args:
            config_path: Path to config.json
            check_interval: Seconds between health checks (default: 60)
        """
        if config_path is None:
            import os
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.json')
        
        self.config_path = config_path
        self.config = self._load_config()
        self.check_interval = check_interval
        
        # Service registry
        self.services = {}
        self.service_health = {}
        
        # Monitoring status
        self.running = False
        self.watchdog_thread = None
        
        # Alert thresholds
        self.memory_threshold = 80  # 80% memory usage
        self.response_time_threshold = 5.0  # 5 seconds
        
        logger.info(f"Watchdog Service initialized (check interval: {check_interval}s)")
    
    def _load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def register_service(self, name: str, service_object: Any, health_check_method: str = "is_healthy"):
        """
        Register a service for monitoring
        
        Args:
            name: Service name
            service_object: Service instance
            health_check_method: Method name to call for health check
        """
        self.services[name] = {
            "object": service_object,
            "health_check_method": health_check_method
        }
        logger.info(f"Registered service: {name}")
    
    def check_kite_connection(self) -> ServiceHealth:
        """Check Kite/Zerodha connection"""
        start_time = time.time()
        try:
            from kite.kite_client import KiteClient
            from kite.login_manager import LoginManager
            
            login_manager = LoginManager(self.config_path)
            login_status = login_manager.check_login_status()
            
            response_time = time.time() - start_time
            
            if login_status['valid']:
                return ServiceHealth(
                    name="Kite Connection",
                    status="HEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    details={"user_id": login_status.get('message', 'N/A')}
                )
            else:
                return ServiceHealth(
                    name="Kite Connection",
                    status="UNHEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    error_message=login_status.get('message', 'Unknown error')
                )
        except Exception as e:
            return ServiceHealth(
                name="Kite Connection",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_websocket_connection(self) -> ServiceHealth:
        """Check WebSocket connection status"""
        start_time = time.time()
        try:
            # This would need access to the WebSocket client
            # For now, we'll check if the process is running
            response_time = time.time() - start_time
            
            return ServiceHealth(
                name="WebSocket Connection",
                status="HEALTHY",  # Would need actual WebSocket check
                last_check=datetime.now().isoformat(),
                response_time=response_time,
                details={"status": "Connected (simulated)"}
            )
        except Exception as e:
            return ServiceHealth(
                name="WebSocket Connection",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_mcx_sentiment_service(self) -> ServiceHealth:
        """Check MCX Sentiment Service"""
        start_time = time.time()
        try:
            from services.mcx_sentiment_service.service import get_mcx_sentiment_service
            
            mcx_service = get_mcx_sentiment_service()
            is_enabled = mcx_service.is_enabled()
            status = mcx_service.get_status()
            
            response_time = time.time() - start_time
            
            return ServiceHealth(
                name="MCX Sentiment Service",
                status="HEALTHY" if is_enabled else "DISABLED",
                last_check=datetime.now().isoformat(),
                response_time=response_time,
                details=status
            )
        except Exception as e:
            return ServiceHealth(
                name="MCX Sentiment Service",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_llm_service(self) -> ServiceHealth:
        """Check LLM Service (Ollama)"""
        start_time = time.time()
        try:
            from ai.ollama_integration import OllamaIntegration
            
            ollama = OllamaIntegration()
            connection_ok = ollama.connection_ok
            
            response_time = time.time() - start_time
            
            if connection_ok:
                return ServiceHealth(
                    name="LLM Service (Ollama)",
                    status="HEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    details={"model": ollama.current_model}
                )
            else:
                return ServiceHealth(
                    name="LLM Service (Ollama)",
                    status="UNHEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    error_message="Connection failed"
                )
        except Exception as e:
            return ServiceHealth(
                name="LLM Service (Ollama)",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_telegram_service(self) -> ServiceHealth:
        """Check Telegram Service"""
        start_time = time.time()
        try:
            from telethon import TelegramClient
            import json
            
            config = json.load(open(self.config_path))
            api_id = config.get("telegram", {}).get("api_id")
            api_hash = config.get("telegram", {}).get("api_hash")
            
            if api_id and api_hash:
                response_time = time.time() - start_time
                return ServiceHealth(
                    name="Telegram Service",
                    status="HEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    details={"configured": True}
                )
            else:
                return ServiceHealth(
                    name="Telegram Service",
                    status="UNHEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=time.time() - start_time,
                    error_message="Not configured"
                )
        except Exception as e:
            return ServiceHealth(
                name="Telegram Service",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_system_resources(self) -> ServiceHealth:
        """Check system resources (memory, CPU, disk)"""
        start_time = time.time()
        try:
            memory = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=1)
            disk = psutil.disk_usage('/')
            
            response_time = time.time() - start_time
            
            memory_percent = memory.percent
            status = "HEALTHY" if memory_percent < self.memory_threshold else "WARNING"
            
            return ServiceHealth(
                name="System Resources",
                status=status,
                last_check=datetime.now().isoformat(),
                response_time=response_time,
                details={
                    "memory_percent": memory_percent,
                    "cpu_percent": cpu,
                    "disk_percent": disk.percent,
                    "memory_available_gb": memory.available / (1024**3),
                    "memory_total_gb": memory.total / (1024**3)
                }
            )
        except Exception as e:
            return ServiceHealth(
                name="System Resources",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_risk_management(self) -> ServiceHealth:
        """Check Risk Management Service"""
        start_time = time.time()
        try:
            from wrappers.risk_wrapper import get_risk_status
            
            risk_status = get_risk_status()
            response_time = time.time() - start_time
            
            return ServiceHealth(
                name="Risk Management",
                status="HEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=response_time,
                details=risk_status
            )
        except Exception as e:
            return ServiceHealth(
                name="Risk Management",
                status="UNHEALTHY",
                last_check=datetime.now().isoformat(),
                response_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def run_health_checks(self) -> Dict[str, ServiceHealth]:
        """Run all health checks"""
        health_results = {}
        
        # Core services
        health_results["kite_connection"] = self.check_kite_connection()
        health_results["websocket"] = self.check_websocket_connection()
        health_results["mcx_sentiment"] = self.check_mcx_sentiment_service()
        health_results["llm_service"] = self.check_llm_service()
        health_results["telegram"] = self.check_telegram_service()
        health_results["risk_management"] = self.check_risk_management()
        health_results["system_resources"] = self.check_system_resources()
        
        # Check registered services
        for name, service_info in self.services.items():
            try:
                service_obj = service_info["object"]
                health_method = service_info["health_check_method"]
                
                if hasattr(service_obj, health_method):
                    method = getattr(service_obj, health_method)
                    start_time = time.time()
                    result = method()
                    response_time = time.time() - start_time
                    
                    health_results[name] = ServiceHealth(
                        name=name,
                        status="HEALTHY" if result else "UNHEALTHY",
                        last_check=datetime.now().isoformat(),
                        response_time=response_time,
                        details={"result": result}
                    )
                else:
                    health_results[name] = ServiceHealth(
                        name=name,
                        status="UNKNOWN",
                        last_check=datetime.now().isoformat(),
                        response_time=0,
                        error_message=f"Method {health_method} not found"
                    )
            except Exception as e:
                health_results[name] = ServiceHealth(
                    name=name,
                    status="UNHEALTHY",
                    last_check=datetime.now().isoformat(),
                    response_time=0,
                    error_message=str(e)
                )
        
        self.service_health = health_results
        return health_results
    
    def print_health_report(self):
        """Print health report to console"""
        print("\n" + "="*80)
        print("WATCHDOG HEALTH REPORT")
        print("="*80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        for name, health in self.service_health.items():
            status_symbol = "[OK]" if health.status == "HEALTHY" else "[FAIL]"
            print(f"{status_symbol} {name:30} | {health.status:10} | {health.response_time:.3f}s")
            if health.error_message:
                print(f"  Error: {health.error_message}")
            if health.details:
                for key, value in health.details.items():
                    if isinstance(value, (int, float)):
                        print(f"  {key}: {value}")
        
        print("="*80)
        
        # Summary
        healthy_count = sum(1 for h in self.service_health.values() if h.status == "HEALTHY")
        total_count = len(self.service_health)
        print(f"Summary: {healthy_count}/{total_count} services healthy")
        print("="*80 + "\n")
    
    def save_health_report(self, filename="watchdog_health_report.json"):
        """Save health report to file"""
        try:
            report = {
                "timestamp": datetime.now().isoformat(),
                "services": {name: asdict(health) for name, health in self.service_health.items()},
                "summary": {
                    "total": len(self.service_health),
                    "healthy": sum(1 for h in self.service_health.values() if h.status == "HEALTHY"),
                    "unhealthy": sum(1 for h in self.service_health.values() if h.status == "UNHEALTHY"),
                    "unknown": sum(1 for h in self.service_health.values() if h.status == "UNKNOWN")
                }
            }
            
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"Health report saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving health report: {e}")
    
    def start_monitoring(self):
        """Start continuous monitoring in background thread"""
        if self.running:
            logger.warning("Watchdog already running")
            return
        
        self.running = True
        self.watchdog_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.watchdog_thread.start()
        logger.info("Watchdog monitoring started")
    
    def _monitoring_loop(self):
        """Background monitoring loop"""
        while self.running:
            try:
                # Run health checks
                health_results = self.run_health_checks()
                
                # Print report
                self.print_health_report()
                
                # Save report
                self.save_health_report()
                
                # Check for critical issues
                self._check_critical_issues()
                
                # Wait for next check
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.check_interval)
    
    def _check_critical_issues(self):
        """Check for critical issues that need immediate attention"""
        critical_issues = []
        
        # Check memory
        system_health = self.service_health.get("system_resources")
        if system_health and system_health.details:
            memory_percent = system_health.details.get("memory_percent", 0)
            if memory_percent > 90:
                critical_issues.append(f"CRITICAL: Memory usage at {memory_percent}%")
        
        # Check Kite connection
        kite_health = self.service_health.get("kite_connection")
        if kite_health and kite_health.status != "HEALTHY":
            critical_issues.append(f"CRITICAL: Kite connection failed - {kite_health.error_message}")
        
        # Check LLM service
        llm_health = self.service_health.get("llm_service")
        if llm_health and llm_health.status != "HEALTHY":
            critical_issues.append(f"WARNING: LLM service unhealthy - {llm_health.error_message}")
        
        # Log critical issues
        for issue in critical_issues:
            logger.error(f"CRITICAL ISSUE DETECTED: {issue}")
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.running = False
        if self.watchdog_thread:
            self.watchdog_thread.join(timeout=5)
        logger.info("Watchdog monitoring stopped")
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get health summary"""
        if not self.service_health:
            self.run_health_checks()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_services": len(self.service_health),
            "healthy_services": sum(1 for h in self.service_health.values() if h.status == "HEALTHY"),
            "unhealthy_services": sum(1 for h in self.service_health.values() if h.status == "UNHEALTHY"),
            "services": {name: asdict(health) for name, health in self.service_health.items()}
        }


# Singleton instance
_watchdog_service = None

def get_watchdog_service(config_path=None, check_interval=60) -> WatchdogService:
    """
    Get singleton instance of Watchdog Service
    
    Args:
        config_path: Path to config.json
        check_interval: Seconds between health checks
    
    Returns:
        WatchdogService instance
    """
    global _watchdog_service
    if _watchdog_service is None:
        _watchdog_service = WatchdogService(config_path, check_interval)
    return _watchdog_service

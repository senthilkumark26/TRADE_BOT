"""
Centralized Code Manager - Code Governance System
Requires approval before code creation or deletion
Tracks all code changes and maintains audit log
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CodeManager:
    """
    Centralized Code Manager - Code Governance System
    
    Features:
    - Requires approval before code creation
    - Requires approval before code deletion
    - Tracks all code changes
    - Maintains audit log
    - Manages code permissions
    """
    
    def __init__(self, project_root="D:\\Traiding_Bot", approval_required=True):
        """
        Initialize Code Manager.
        
        Args:
            project_root: Root directory of the project
            approval_required: Whether approval is required for code changes
        """
        self.project_root = project_root
        self.approval_required = approval_required
        self.audit_log_file = os.path.join(project_root, ".code_audit_log.json")
        self.pending_approvals_file = os.path.join(project_root, ".pending_approvals.json")
        self.services_file = os.path.join(project_root, ".registered_services.json")
        
        # Initialize audit log
        self.audit_log = self._load_audit_log()
        
        # Initialize pending approvals
        self.pending_approvals = self._load_pending_approvals()
        
        # Initialize registered services
        self.registered_services = self._load_services()
        
        # Initialize critical files (protected from deletion/modification)
        self.critical_files_file = os.path.join(project_root, ".critical_files.json")
        self.critical_files = self._load_critical_files()
        
        logger.info(f"Code Manager initialized for {project_root}")
        logger.info(f"Approval required: {approval_required}")
        logger.info(f"Registered services: {len(self.registered_services)}")
        logger.info(f"Critical files: {len(self.critical_files)}")
    
    def _load_audit_log(self) -> Dict:
        """Load audit log from file."""
        if os.path.exists(self.audit_log_file):
            try:
                with open(self.audit_log_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading audit log: {e}")
        
        return {
            "created": [],
            "deleted": [],
            "modified": [],
            "approved": [],
            "rejected": []
        }
    
    def _save_audit_log(self):
        """Save audit log to file."""
        try:
            with open(self.audit_log_file, 'w') as f:
                json.dump(self.audit_log, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving audit log: {e}")
    
    def _load_pending_approvals(self) -> Dict:
        """Load pending approvals from file."""
        if os.path.exists(self.pending_approvals_file):
            try:
                with open(self.pending_approvals_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading pending approvals: {e}")
        
        return {}
    
    def _load_services(self) -> Dict:
        """Load registered services from file."""
        if os.path.exists(self.services_file):
            try:
                with open(self.services_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading services: {e}")
        
        return {}
    
    def _load_critical_files(self) -> Dict:
        """Load critical files from file."""
        if os.path.exists(self.critical_files_file):
            try:
                with open(self.critical_files_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading critical files: {e}")
        
        # Default critical files if file doesn't exist
        default_critical = {
            "config.json": {
                "file_path": "config.json",
                "protection_level": "HIGH",
                "description": "Contains API keys and credentials",
                "allowed_operations": ["READ"]
            },
            ".env": {
                "file_path": ".env",
                "protection_level": "HIGH",
                "description": "Environment variables with secrets",
                "allowed_operations": ["READ"]
            },
            "kite_client.py": {
                "file_path": "kite_client.py",
                "protection_level": "MEDIUM",
                "description": "Core Kite integration module",
                "allowed_operations": ["READ", "MODIFY"]
            },
            "expiry_manager.py": {
                "file_path": "expiry_manager.py",
                "protection_level": "MEDIUM",
                "description": "Expiry management service",
                "allowed_operations": ["READ", "MODIFY"]
            },
            "kite_service.py": {
                "file_path": "kite_service.py",
                "protection_level": "MEDIUM",
                "description": "Kite service module",
                "allowed_operations": ["READ", "MODIFY"]
            }
        }
        
        # Save default critical files
        self._save_critical_files(default_critical)
        return default_critical
    
    def _save_pending_approvals(self):
        """Save pending approvals to file."""
        try:
            with open(self.pending_approvals_file, 'w') as f:
                json.dump(self.pending_approvals, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving pending approvals: {e}")
    
    def _save_services(self):
        """Save registered services to file."""
        try:
            with open(self.services_file, 'w') as f:
                json.dump(self.registered_services, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving services: {e}")
    
    def _save_critical_files(self, critical_files: Dict):
        """Save critical files to file."""
        try:
            with open(self.critical_files_file, 'w') as f:
                json.dump(critical_files, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving critical files: {e}")
    
    def request_code_creation(self, file_path: str, description: str = "", requester: str = "system") -> Tuple[bool, str]:
        """
        Request approval for code creation.
        
        Args:
            file_path: Path to the file to be created
            description: Description of the code to be created
            requester: Name of the requester
            
        Returns:
            Tuple of (approved: bool, message: str)
        """
        if not self.approval_required:
            # Auto-approve if approval not required
            self._log_approval("created", file_path, description, requester, "AUTO_APPROVED")
            return True, "Auto-approved (approval not required)"
        
        # Create pending approval request
        request_id = f"CREATE_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.pending_approvals)}"
        
        approval_request = {
            "request_id": request_id,
            "type": "CREATE",
            "file_path": file_path,
            "description": description,
            "requester": requester,
            "timestamp": datetime.now().isoformat(),
            "status": "PENDING"
        }
        
        self.pending_approvals[request_id] = approval_request
        self._save_pending_approvals()
        
        logger.warning(f"Code creation request pending approval: {file_path}")
        logger.warning(f"Request ID: {request_id}")
        logger.warning(f"Description: {description}")
        logger.warning(f"Requester: {requester}")
        logger.warning(f"Use: code_manager.approve_request('{request_id}') to approve")
        
        return False, f"Approval required. Request ID: {request_id}"
    
    def request_code_deletion(self, file_path: str, reason: str = "", requester: str = "system") -> Tuple[bool, str]:
        """
        Request approval for code deletion.
        
        Args:
            file_path: Path to the file to be deleted
            reason: Reason for deletion
            requester: Name of the requester
            
        Returns:
            Tuple of (approved: bool, message: str)
        """
        # Check if file is critical
        allowed, message = self.is_operation_allowed(file_path, "DELETE")
        
        if not allowed:
            return False, message
        
        if not self.approval_required:
            # Auto-approve if approval not required
            self._log_approval("deleted", file_path, reason, requester, "AUTO_APPROVED")
            return True, "Auto-approved (approval not required)"
        
        # Check if file exists
        if not os.path.exists(file_path):
            return False, f"File does not exist: {file_path}"
        
        # Create pending approval request
        request_id = f"DELETE_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.pending_approvals)}"
        
        approval_request = {
            "request_id": request_id,
            "type": "DELETE",
            "file_path": file_path,
            "description": reason,
            "requester": requester,
            "timestamp": datetime.now().isoformat(),
            "status": "PENDING"
        }
        
        self.pending_approvals[request_id] = approval_request
        self._save_pending_approvals()
        
        logger.warning(f"Code deletion request pending approval: {file_path}")
        logger.warning(f"Request ID: {request_id}")
        logger.warning(f"Reason: {reason}")
        logger.warning(f"Requester: {requester}")
        logger.warning(f"Use: code_manager.approve_request('{request_id}') to approve")
        
        return False, f"Approval required. Request ID: {request_id}"
    
    def request_code_modification(self, file_path: str, description: str = "", requester: str = "system") -> Tuple[bool, str]:
        """
        Request approval for code modification.
        
        Args:
            file_path: Path to the file to be modified
            description: Description of the modification
            requester: Name of the requester
            
        Returns:
            Tuple of (approved: bool, message: str)
        """
        # Check if file is critical
        allowed, message = self.is_operation_allowed(file_path, "MODIFY")
        
        if not allowed:
            return False, message
        
        if not self.approval_required:
            # Auto-approve if approval not required
            self._log_approval("modified", file_path, description, requester, "AUTO_APPROVED")
            return True, "Auto-approved (approval not required)"
        
        # Check if file exists
        if not os.path.exists(file_path):
            return False, f"File does not exist: {file_path}"
        
        # Create pending approval request
        request_id = f"MODIFY_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.pending_approvals)}"
        
        approval_request = {
            "request_id": request_id,
            "type": "MODIFY",
            "file_path": file_path,
            "description": description,
            "requester": requester,
            "timestamp": datetime.now().isoformat(),
            "status": "PENDING"
        }
        
        self.pending_approvals[request_id] = approval_request
        self._save_pending_approvals()
        
        logger.warning(f"Code modification request pending approval: {file_path}")
        logger.warning(f"Request ID: {request_id}")
        logger.warning(f"Description: {description}")
        logger.warning(f"Requester: {requester}")
        logger.warning(f"Use: code_manager.approve_request('{request_id}') to approve")
        
        return False, f"Approval required. Request ID: {request_id}"
    
    def approve_request(self, request_id: str, approver: str = "admin") -> Tuple[bool, str]:
        """
        Approve a pending code change request.
        
        Args:
            request_id: ID of the request to approve
            approver: Name of the approver
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if request_id not in self.pending_approvals:
            return False, f"Request not found: {request_id}"
        
        request = self.pending_approvals[request_id]
        
        if request["status"] != "PENDING":
            return False, f"Request already {request['status']}: {request_id}"
        
        # Update request status
        request["status"] = "APPROVED"
        request["approver"] = approver
        request["approval_timestamp"] = datetime.now().isoformat()
        
        # Log to audit log
        self._log_approval(
            request["type"].lower(),
            request["file_path"],
            request["description"],
            request["requester"],
            "APPROVED",
            approver
        )
        
        # Store request details for execution
        request_details = request.copy()
        
        # Remove from pending approvals
        del self.pending_approvals[request_id]
        self._save_pending_approvals()
        
        logger.info(f"Request approved: {request_id}")
        logger.info(f"Type: {request['type']}")
        logger.info(f"File: {request['file_path']}")
        logger.info(f"Approver: {approver}")
        
        # Store approved request for execution
        self._store_approved_request(request_id, request_details)
        
        return True, f"Request approved: {request_id}"
    
    def _store_approved_request(self, request_id: str, request_details: Dict):
        """Store approved request for execution."""
        approved_file = os.path.join(self.project_root, ".approved_requests.json")
        
        try:
            approved_requests = {}
            if os.path.exists(approved_file):
                with open(approved_file, 'r') as f:
                    approved_requests = json.load(f)
            
            approved_requests[request_id] = request_details
            
            with open(approved_file, 'w') as f:
                json.dump(approved_requests, f, indent=2)
        except Exception as e:
            logger.error(f"Error storing approved request: {e}")
    
    def get_approved_requests(self) -> List[Dict]:
        """Get all approved requests waiting for execution."""
        approved_file = os.path.join(self.project_root, ".approved_requests.json")
        
        try:
            if os.path.exists(approved_file):
                with open(approved_file, 'r') as f:
                    approved_requests = json.load(f)
                return list(approved_requests.values())
        except Exception as e:
            logger.error(f"Error getting approved requests: {e}")
        
        return []
    
    def clear_approved_requests(self):
        """Clear all approved requests after execution."""
        approved_file = os.path.join(self.project_root, ".approved_requests.json")
        
        try:
            if os.path.exists(approved_file):
                os.remove(approved_file)
        except Exception as e:
            logger.error(f"Error clearing approved requests: {e}")
    
    def reject_request(self, request_id: str, reason: str = "", rejecter: str = "admin") -> Tuple[bool, str]:
        """
        Reject a pending code change request.
        
        Args:
            request_id: ID of the request to reject
            reason: Reason for rejection
            rejecter: Name of the rejecter
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if request_id not in self.pending_approvals:
            return False, f"Request not found: {request_id}"
        
        request = self.pending_approvals[request_id]
        
        if request["status"] != "PENDING":
            return False, f"Request already {request['status']}: {request_id}"
        
        # Update request status
        request["status"] = "REJECTED"
        request["rejecter"] = rejecter
        request["rejection_reason"] = reason
        request["rejection_timestamp"] = datetime.now().isoformat()
        
        # Log to audit log
        self._log_approval(
            request["type"].lower(),
            request["file_path"],
            request["description"],
            request["requester"],
            "REJECTED",
            rejecter,
            reason
        )
        
        # Remove from pending approvals
        del self.pending_approvals[request_id]
        self._save_pending_approvals()
        
        logger.warning(f"Request rejected: {request_id}")
        logger.warning(f"Type: {request['type']}")
        logger.warning(f"File: {request['file_path']}")
        logger.warning(f"Rejecter: {rejecter}")
        logger.warning(f"Reason: {reason}")
        
        return True, f"Request rejected: {request_id}"
    
    def _log_approval(self, action_type: str, file_path: str, description: str, 
                    requester: str, status: str, approver: str = "", reason: str = ""):
        """
        Log approval to audit log.
        
        Args:
            action_type: Type of action (created, deleted, modified)
            file_path: Path to the file
            description: Description of the action
            requester: Name of the requester
            status: Status of the approval
            approver: Name of the approver (if approved/rejected)
            reason: Reason for rejection (if rejected)
        """
        # Normalize action type to lowercase for audit log keys
        action_type_normalized = action_type.lower()
        
        # Ensure audit log has the key
        if action_type_normalized not in self.audit_log:
            self.audit_log[action_type_normalized] = []
        
        log_entry = {
            "action_type": action_type_normalized,
            "file_path": file_path,
            "description": description,
            "requester": requester,
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
        
        if approver:
            log_entry["approver"] = approver
        
        if reason:
            log_entry["reason"] = reason
        
        self.audit_log[action_type_normalized].append(log_entry)
        self._save_audit_log()
    
    def get_pending_requests(self) -> List[Dict]:
        """
        Get all pending approval requests.
        
        Returns:
            List of pending requests
        """
        return [req for req in self.pending_approvals.values() if req["status"] == "PENDING"]
    
    def get_audit_log(self, action_type: Optional[str] = None) -> Dict:
        """
        Get audit log.
        
        Args:
            action_type: Filter by action type (created, deleted, modified, approved, rejected)
            
        Returns:
            Audit log
        """
        if action_type:
            return {action_type: self.audit_log.get(action_type, [])}
        
        return self.audit_log
    
    def list_all_files(self) -> List[str]:
        """
        List all Python files in the project.
        
        Returns:
            List of file paths
        """
        python_files = []
        
        for root, dirs, files in os.walk(self.project_root):
            # Skip hidden directories and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    python_files.append(file_path)
        
        return sorted(python_files)
    
    def enable_approval_mode(self):
        """Enable approval mode."""
        self.approval_required = True
        logger.info("Approval mode ENABLED")
    
    def disable_approval_mode(self):
        """Disable approval mode."""
        self.approval_required = False
        logger.info("Approval mode DISABLED")
    
    # ==================== SERVICE MANAGEMENT ====================
    
    def register_service(self, service_name: str, service_file: str, description: str = "", 
                       version: str = "1.0", dependencies: List[str] = None) -> Tuple[bool, str]:
        """
        Register a service with the Code Manager.
        
        Args:
            service_name: Name of the service
            service_file: Path to the service file
            description: Description of the service
            version: Version of the service
            dependencies: List of service dependencies
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        service_info = {
            "service_name": service_name,
            "service_file": service_file,
            "description": description,
            "version": version,
            "dependencies": dependencies or [],
            "registered_at": datetime.now().isoformat(),
            "status": "ACTIVE"
        }
        
        self.registered_services[service_name] = service_info
        self._save_services()
        
        logger.info(f"Service registered: {service_name} (v{version})")
        return True, f"Service registered: {service_name}"
    
    def unregister_service(self, service_name: str) -> Tuple[bool, str]:
        """
        Unregister a service from the Code Manager.
        
        Args:
            service_name: Name of the service to unregister
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if service_name not in self.registered_services:
            return False, f"Service not found: {service_name}"
        
        del self.registered_services[service_name]
        self._save_services()
        
        logger.info(f"Service unregistered: {service_name}")
        return True, f"Service unregistered: {service_name}"
    
    def get_service(self, service_name: str) -> Optional[Dict]:
        """
        Get information about a registered service.
        
        Args:
            service_name: Name of the service
            
        Returns:
            Service information or None
        """
        return self.registered_services.get(service_name)
    
    def list_services(self) -> List[Dict]:
        """
        List all registered services.
        
        Returns:
            List of service information
        """
        return list(self.registered_services.values())
    
    def get_service_dependencies(self, service_name: str) -> List[str]:
        """
        Get dependencies for a service.
        
        Args:
            service_name: Name of the service
            
        Returns:
            List of dependency names
        """
        service = self.get_service(service_name)
        if service:
            return service.get("dependencies", [])
        return []
    
    def validate_service_dependencies(self, service_name: str) -> Tuple[bool, List[str]]:
        """
        Validate that all service dependencies are registered.
        
        Args:
            service_name: Name of the service to validate
            
        Returns:
            Tuple of (valid: bool, missing_dependencies: List[str])
        """
        dependencies = self.get_service_dependencies(service_name)
        missing = []
        
        for dep in dependencies:
            if dep not in self.registered_services:
                missing.append(dep)
        
        return len(missing) == 0, missing
    
    # ==================== CRITICAL FILE PROTECTION ====================
    
    def is_file_critical(self, file_path: str) -> bool:
        """
        Check if a file is marked as critical.
        
        Args:
            file_path: Path to the file (can be relative or absolute)
            
        Returns:
            True if file is critical, False otherwise
        """
        # Normalize file path
        file_name = os.path.basename(file_path)
        
        # Check if file name or full path is in critical files
        for key, file_info in self.critical_files.items():
            if file_name == key or file_path == file_info["file_path"]:
                return True
        
        return False
    
    def get_file_protection(self, file_path: str) -> Optional[Dict]:
        """
        Get protection level for a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            File protection info or None
        """
        file_name = os.path.basename(file_path)
        
        for key, file_info in self.critical_files.items():
            if file_name == key or file_path == file_info["file_path"]:
                return file_info
        
        return None
    
    def is_operation_allowed(self, file_path: str, operation: str) -> Tuple[bool, str]:
        """
        Check if an operation is allowed on a file.
        
        Args:
            file_path: Path to the file
            operation: Operation type (CREATE, DELETE, MODIFY, READ)
            
        Returns:
            Tuple of (allowed: bool, message: str)
        """
        if not self.is_file_critical(file_path):
            return True, "File not critical"
        
        protection = self.get_file_protection(file_path)
        
        if not protection:
            return True, "File not critical"
        
        allowed_operations = protection.get("allowed_operations", [])
        
        if operation.upper() in [op.upper() for op in allowed_operations]:
            return True, f"Operation {operation} allowed for critical file"
        else:
            logger.error(f"BLOCKED: {operation} not allowed on critical file: {file_path}")
            logger.error(f"Protection level: {protection['protection_level']}")
            logger.error(f"Description: {protection['description']}")
            return False, f"Operation {operation} BLOCKED - Critical file protection (Level: {protection['protection_level']})"
    
    def add_critical_file(self, file_path: str, protection_level: str = "MEDIUM", 
                        description: str = "", allowed_operations: List[str] = None) -> Tuple[bool, str]:
        """
        Add a file to the critical files list.
        
        Args:
            file_path: Path to the file
            protection_level: Protection level (HIGH, MEDIUM, LOW)
            description: Description of why this file is critical
            allowed_operations: List of allowed operations
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        file_info = {
            "file_path": file_path,
            "protection_level": protection_level,
            "description": description,
            "allowed_operations": allowed_operations or ["READ"],
            "added_at": datetime.now().isoformat()
        }
        
        file_name = os.path.basename(file_path)
        self.critical_files[file_name] = file_info
        self._save_critical_files(self.critical_files)
        
        logger.info(f"Critical file added: {file_path} (Level: {protection_level})")
        return True, f"Critical file added: {file_path}"
    
    def remove_critical_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Remove a file from the critical files list.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        file_name = os.path.basename(file_path)
        
        if file_name not in self.critical_files:
            return False, f"File not in critical files list: {file_path}"
        
        del self.critical_files[file_name]
        self._save_critical_files(self.critical_files)
        
        logger.info(f"Critical file removed: {file_path}")
        return True, f"Critical file removed: {file_path}"
    
    def list_critical_files(self) -> List[Dict]:
        """
        List all critical files.
        
        Returns:
            List of critical file information
        """
        return list(self.critical_files.values())


# Global Code Manager instance
code_manager = CodeManager()

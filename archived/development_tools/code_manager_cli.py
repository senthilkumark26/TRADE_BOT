"""
Code Manager CLI - Command Line Interface for Code Governance System
"""

import sys
from code_manager import code_manager
from code_operations import execute_approved_requests


def main():
    """Main CLI function."""
    
    print("=" * 80)
    print("CODE MANAGER CLI - Code Governance System")
    print("=" * 80)
    
    if len(sys.argv) < 2:
        print("\nAvailable Commands:")
        print("  list-pending           - List all pending approval requests")
        print("  approve <request_id>   - Approve a pending request")
        print("  reject <request_id>    - Reject a pending request")
        print("  list-files             - List all Python files in project")
        print("  audit-log              - Show audit log")
        print("  enable-approval        - Enable approval mode")
        print("  disable-approval       - Disable approval mode")
        print("  status                 - Show code manager status")
        print("  execute                - Execute all approved requests")
        print("  list-services           - List all registered services")
        print("  register-service <name> - Register a new service")
        print("  unregister-service <name> - Unregister a service")
        print("  list-critical           - List all critical files")
        print("  add-critical <file>     - Add file to critical list")
        print("  remove-critical <file>  - Remove file from critical list")
        print("\nExamples:")
        print("  python code_manager_cli.py list-pending")
        print("  python code_manager_cli.py approve CREATE_20241219_143000_0")
        print("  python code_manager_cli.py reject DELETE_20241219_143001_1")
        return
    
    command = sys.argv[1].lower()
    
    if command == "list-pending":
        print("\n" + "=" * 80)
        print("PENDING APPROVAL REQUESTS")
        print("=" * 80)
        
        pending = code_manager.get_pending_requests()
        
        if not pending:
            print("\nNo pending requests.")
            return
        
        for req in pending:
            print(f"\nRequest ID: {req['request_id']}")
            print(f"Type: {req['type']}")
            print(f"File: {req['file_path']}")
            print(f"Description: {req['description']}")
            print(f"Requester: {req['requester']}")
            print(f"Timestamp: {req['timestamp']}")
            print(f"Status: {req['status']}")
    
    elif command == "approve":
        if len(sys.argv) < 3:
            print("Error: Request ID required")
            print("Usage: python code_manager_cli.py approve <request_id>")
            return
        
        request_id = sys.argv[2]
        success, message = code_manager.approve_request(request_id)
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    elif command == "reject":
        if len(sys.argv) < 3:
            print("Error: Request ID required")
            print("Usage: python code_manager_cli.py reject <request_id> [reason]")
            return
        
        request_id = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else ""
        success, message = code_manager.reject_request(request_id, reason)
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    elif command == "list-files":
        print("\n" + "=" * 80)
        print("ALL PYTHON FILES IN PROJECT")
        print("=" * 80)
        
        files = code_manager.list_all_files()
        
        for file_path in files:
            print(f"  {file_path}")
        
        print(f"\nTotal: {len(files)} files")
    
    elif command == "audit-log":
        print("\n" + "=" * 80)
        print("AUDIT LOG")
        print("=" * 80)
        
        audit_log = code_manager.get_audit_log()
        
        for action_type, entries in audit_log.items():
            print(f"\n{action_type.upper()} ({len(entries)} entries):")
            for entry in entries[-10:]:  # Show last 10 entries
                print(f"  File: {entry['file_path']}")
                print(f"  Description: {entry['description']}")
                print(f"  Requester: {entry['requester']}")
                print(f"  Status: {entry['status']}")
                print(f"  Timestamp: {entry['timestamp']}")
                if 'approver' in entry:
                    print(f"  Approver: {entry['approver']}")
                if 'reason' in entry:
                    print(f"  Reason: {entry['reason']}")
                print()
    
    elif command == "enable-approval":
        code_manager.enable_approval_mode()
        print("\n[OK] Approval mode ENABLED")
    
    elif command == "disable-approval":
        code_manager.disable_approval_mode()
        print("\n[OK] Approval mode DISABLED")
    
    elif command == "status":
        print("\n" + "=" * 80)
        print("CODE MANAGER STATUS")
        print("=" * 80)
        
        pending = code_manager.get_pending_requests()
        audit_log = code_manager.get_audit_log()
        approved = code_manager.get_approved_requests()
        services = code_manager.list_services()
        critical_files = code_manager.list_critical_files()
        
        print(f"\nApproval Mode: {'ENABLED' if code_manager.approval_required else 'DISABLED'}")
        print(f"Pending Requests: {len(pending)}")
        print(f"Approved Requests: {len(approved)} (waiting execution)")
        print(f"Registered Services: {len(services)}")
        print(f"Critical Files: {len(critical_files)} (protected)")
        print(f"Total Audit Entries: {sum(len(entries) for entries in audit_log.values())}")
        
        print(f"\nAudit Log Breakdown:")
        for action_type, entries in audit_log.items():
            print(f"  {action_type.upper()}: {len(entries)}")
        
        print(f"\nRegistered Services:")
        for service in services:
            print(f"  - {service['service_name']} (v{service['version']})")
        
        print(f"\nCritical Files (Protected):")
        for file_info in critical_files:
            print(f"  - {file_info['file_path']} [{file_info['protection_level']}]")
    
    elif command == "execute":
        print("\n" + "=" * 80)
        print("EXECUTING APPROVED REQUESTS")
        print("=" * 80)
        
        executed, message = execute_approved_requests()
        
        print(f"\n{message}")
    
    elif command == "list-services":
        print("\n" + "=" * 80)
        print("REGISTERED SERVICES")
        print("=" * 80)
        
        services = code_manager.list_services()
        
        if not services:
            print("\nNo services registered.")
            return
        
        for service in services:
            print(f"\nService: {service['service_name']}")
            print(f"File: {service['service_file']}")
            print(f"Version: {service['version']}")
            print(f"Description: {service['description']}")
            print(f"Dependencies: {', '.join(service['dependencies']) if service['dependencies'] else 'None'}")
            print(f"Registered: {service['registered_at']}")
            print(f"Status: {service['status']}")
        
        print(f"\nTotal: {len(services)} services")
    
    elif command == "register-service":
        if len(sys.argv) < 3:
            print("Error: Service name required")
            print("Usage: python code_manager_cli.py register-service <service_name>")
            return
        
        service_name = sys.argv[2]
        success, message = code_manager.register_service(
            service_name=service_name,
            service_file=f"{service_name}.py",
            description=f"Service: {service_name}"
        )
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    elif command == "unregister-service":
        if len(sys.argv) < 3:
            print("Error: Service name required")
            print("Usage: python code_manager_cli.py unregister-service <service_name>")
            return
        
        service_name = sys.argv[2]
        success, message = code_manager.unregister_service(service_name)
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    elif command == "list-critical":
        print("\n" + "=" * 80)
        print("CRITICAL FILES (PROTECTED)")
        print("=" * 80)
        
        critical_files = code_manager.list_critical_files()
        
        if not critical_files:
            print("\nNo critical files protected.")
            return
        
        for file_info in critical_files:
            print(f"\nFile: {file_info['file_path']}")
            print(f"Protection Level: {file_info['protection_level']}")
            print(f"Description: {file_info['description']}")
            print(f"Allowed Operations: {', '.join(file_info['allowed_operations'])}")
            if 'added_at' in file_info:
                print(f"Added: {file_info['added_at']}")
        
        print(f"\nTotal: {len(critical_files)} critical files")
    
    elif command == "add-critical":
        if len(sys.argv) < 3:
            print("Error: File path required")
            print("Usage: python code_manager_cli.py add-critical <file_path>")
            return
        
        file_path = sys.argv[2]
        success, message = code_manager.add_critical_file(
            file_path=file_path,
            protection_level="HIGH",
            description=f"Critical file: {file_path}"
        )
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    elif command == "remove-critical":
        if len(sys.argv) < 3:
            print("Error: File path required")
            print("Usage: python code_manager_cli.py remove-critical <file_path>")
            return
        
        file_path = sys.argv[2]
        success, message = code_manager.remove_critical_file(file_path)
        
        if success:
            print(f"\n[OK] {message}")
        else:
            print(f"\n[FAIL] {message}")
    
    else:
        print(f"\nUnknown command: {command}")
        print("Run without arguments to see available commands.")


if __name__ == "__main__":
    main()

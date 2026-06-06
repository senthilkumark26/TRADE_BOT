# Code Manager - Code Governance System

## Overview

The Code Manager is a centralized code governance system that requires approval before any code is created, modified, or deleted. This ensures code quality and prevents accidental or unauthorized changes.

## Components

### 1. code_manager.py
Core Code Manager service that:
- Manages approval requests
- Tracks audit log
- Maintains pending approvals
- **Manages registered services**
- Provides approval/rejection functionality

### 2. code_manager_cli.py
Command-line interface for:
- Listing pending requests
- Approving/rejecting requests
- Viewing audit logs
- Managing approval mode
- **Managing registered services**

### 3. code_operations.py
Wrapper functions for:
- Creating files with approval
- Deleting files with approval
- Modifying files with approval
- Safe file operations

### 4. register_services.py
Script to register all project services with Code Manager

## Critical File Protection

The Code Manager protects critical files from accidental deletion or modification. Critical files are marked with protection levels and allowed operations.

### Default Critical Files

### config.json (HIGH Protection)
- **File**: config.json
- **Protection Level**: HIGH
- **Description**: Contains API keys and credentials
- **Allowed Operations**: READ only
- **DELETE**: BLOCKED
- **MODIFY**: BLOCKED

### .env (HIGH Protection)
- **File**: .env
- **Protection Level**: HIGH
- **Description**: Environment variables with secrets
- **Allowed Operations**: READ only
- **DELETE**: BLOCKED
- **MODIFY**: BLOCKED

### kite_client.py (MEDIUM Protection)
- **File**: kite_client.py
- **Protection Level**: MEDIUM
- **Description**: Core Kite integration module
- **Allowed Operations**: READ, MODIFY
- **DELETE**: BLOCKED
- **MODIFY**: Allowed (with approval)

### expiry_manager.py (MEDIUM Protection)
- **File**: expiry_manager.py
- **Protection Level**: MEDIUM
- **Description**: Expiry management service
- **Allowed Operations**: READ, MODIFY
- **DELETE**: BLOCKED
- **MODIFY**: Allowed (with approval)

### kite_service.py (MEDIUM Protection)
- **File**: kite_service.py
- **Protection Level**: MEDIUM
- **Description**: Kite service module
- **Allowed Operations**: READ, MODIFY
- **DELETE**: BLOCKED
- **MODIFY**: Allowed (with approval)

## What Happens When You Try to Delete Kite Login (config.json)?

### Attempt to DELETE config.json:
```
Success: False
Message: Operation DELETE BLOCKED - Critical file protection (Level: HIGH)
```

### Attempt to MODIFY config.json:
```
Success: False
Message: Operation MODIFY BLOCKED - Critical file protection (Level: HIGH)
```

### Attempt to DELETE kite_client.py (MEDIUM Protection):
```
Success: False
Message: Operation DELETE BLOCKED - Critical file protection (Level: MEDIUM)
```

### Attempt to MODIFY kite_client.py (MEDIUM Protection):
```
Success: False
Message: Approval required. Request ID: MODIFY_20241219_143000_0
```
(MODIFY is allowed but requires approval)

### Attempt to DELETE non-critical file:
```
Success: False
Message: Approval required. Request ID: DELETE_20241219_143000_1
```
(Normal approval process)

## Registered Services

The Code Manager tracks all project services:

### expiry_manager
- **File**: expiry_manager.py
- **Version**: 1.0
- **Description**: Expiry Auto-Switch Engine - Automatically selects correct trading expiry
- **Dependencies**: None

### kite_service
- **File**: kite_service.py
- **Version**: 1.0
- **Description**: Kite Service - Centralized KiteConnect integration with rate limiting
- **Dependencies**: None

### code_manager
- **File**: code_manager.py
- **Version**: 1.0
- **Description**: Code Manager - Code governance system with approval workflow
- **Dependencies**: None

## Usage

### Enable Approval Mode (Default)
```python
from code_manager import code_manager

code_manager.enable_approval_mode()
```

### Disable Approval Mode (For Development)
```python
code_manager.disable_approval_mode()
```

### Create File with Approval
```python
from code_operations import create_file_with_approval

success, message = create_file_with_approval(
    file_path="new_file.py",
    content="# New file content",
    description="New trading strategy",
    requester="developer"
)

if not success:
    print(f"Approval required: {message}")
    # Request ID will be in the message
```

### Delete File with Approval
```python
from code_operations import delete_file_with_approval

success, message = delete_file_with_approval(
    file_path="old_file.py",
    reason="No longer needed",
    requester="developer"
)

if not success:
    print(f"Approval required: {message}")
```

### Modify File with Approval
```python
from code_operations import modify_file_with_approval

success, message = modify_file_with_approval(
    file_path="existing_file.py",
    content="# Updated content",
    description="Bug fix",
    requester="developer"
)

if not success:
    print(f"Approval required: {message}")
```

## CLI Commands

### List Pending Requests
```bash
python code_manager_cli.py list-pending
```

### Approve Request
```bash
python code_manager_cli.py approve CREATE_20241219_143000_0
```

### Reject Request
```bash
python code_manager_cli.py reject DELETE_20241219_143001_1 "Reason for rejection"
```

### List All Files
```bash
python code_manager_cli.py list-files
```

### View Audit Log
```bash
python code_manager_cli.py audit-log
```

### Enable Approval Mode
```bash
python code_manager_cli.py enable-approval
```

### Disable Approval Mode
```bash
python code_manager_cli.py disable-approval
```

### Check Status
```bash
python code_manager_cli.py status
```

### List Registered Services
```bash
python code_manager_cli.py list-services
```

### Register New Service
```bash
python code_manager_cli.py register-service <service_name>
```

### Unregister Service
```bash
python code_manager_cli.py unregister-service <service_name>
```

### List Critical Files
```bash
python code_manager_cli.py list-critical
```

### Add Critical File
```bash
python code_manager_cli.py add-critical <file_path>
```

### Remove Critical File
```bash
python code_manager_cli.py remove-critical <file_path>
```

## Approval Workflow

### Step 1: Request Code Change
```python
from code_operations import create_file_with_approval

success, message = create_file_with_approval(
    file_path="new_strategy.py",
    content="# Strategy code",
    description="New breakout strategy",
    requester="developer"
)
```

### Step 2: Check Pending Requests
```bash
python code_manager_cli.py list-pending
```

### Step 3: Approve or Reject
```bash
python code_manager_cli.py approve CREATE_20241219_143000_0
```

### Step 4: Code Change Executed
- File is created automatically after approval
- Logged in audit log
- Removed from pending approvals

## Service Management

### Register All Services
```bash
python register_services.py
```

### List Registered Services
```bash
python code_manager_cli.py list-services
```

### Register a New Service
```python
from code_manager import code_manager

success, message = code_manager.register_service(
    service_name="my_service",
    service_file="my_service.py",
    description="My custom service",
    version="1.0",
    dependencies=["expiry_manager"]
)
```

### Unregister a Service
```python
from code_manager import code_manager

success, message = code_manager.unregister_service("my_service")
```

### Get Service Information
```python
from code_manager import code_manager

service_info = code_manager.get_service("expiry_manager")
print(service_info)
```

### Validate Service Dependencies
```python
from code_manager import code_manager

valid, missing = code_manager.validate_service_dependencies("my_service")
if not valid:
    print(f"Missing dependencies: {missing}")
```

## Critical File Management

### List Critical Files
```bash
python code_manager_cli.py list-critical
```

### Add a Critical File
```python
from code_manager import code_manager

success, message = code_manager.add_critical_file(
    file_path="my_important_file.py",
    protection_level="HIGH",
    description="Contains sensitive logic",
    allowed_operations=["READ"]
)
```

### Remove a Critical File
```python
from code_manager import code_manager

success, message = code_manager.remove_critical_file("my_important_file.py")
```

### Check if File is Critical
```python
from code_manager import code_manager

is_critical = code_manager.is_file_critical("config.json")
if is_critical:
    print("This file is protected!")
```

### Check if Operation is Allowed
```python
from code_manager import code_manager

allowed, message = code_manager.is_operation_allowed("config.json", "DELETE")
if not allowed:
    print(f"Operation blocked: {message}")
```

### Protection Levels

**HIGH Protection:**
- Only READ operations allowed
- DELETE and MODIFY are BLOCKED
- Used for: config.json, .env, files with credentials

**MEDIUM Protection:**
- READ and MODIFY operations allowed
- DELETE is BLOCKED
- MODIFY requires approval
- Used for: Core service files, important modules

**LOW Protection:**
- All operations allowed with approval
- Used for: Less critical files

## Audit Log

The audit log tracks all code changes:
- Created files
- Deleted files
- Modified files
- Approved requests
- Rejected requests

Audit log location: `.code_audit_log.json`

## Pending Approvals

Pending approval requests are stored in: `.pending_approvals.json`

## Integration with Existing Tools

To integrate with existing tools (like Devin CLI), wrap file operations:

```python
from code_operations import create_file_with_approval, delete_file_with_approval

# Instead of:
write(file_path, content)

# Use:
success, message = create_file_with_approval(file_path, content, description, requester)
```

## Benefits

1. **Code Quality**: Prevents accidental or low-quality code changes
2. **Audit Trail**: Complete history of all code changes
3. **Governance**: Centralized approval process
4. **Security**: Prevents unauthorized code changes
5. **Traceability**: Clear requester and approver information

## Best Practices

1. Always provide clear descriptions for code changes
2. Review pending requests regularly
3. Document reasons for rejections
4. Keep approval mode enabled in production
5. Disable approval mode only for development/testing

## Files

- `code_manager.py` - Core Code Manager service
- `code_manager_cli.py` - Command-line interface
- `code_operations.py` - File operation wrappers
- `register_services.py` - Service registration script
- `.code_audit_log.json` - Audit log (auto-generated)
- `.pending_approvals.json` - Pending approvals (auto-generated)
- `.approved_requests.json` - Approved requests (auto-generated)
- `.registered_services.json` - Registered services (auto-generated)
- `.critical_files.json` - Critical files configuration (auto-generated)

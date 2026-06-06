"""
Code Operations Wrapper - Enforces Code Governance
All file operations must go through this wrapper
"""

import os
from code_manager import code_manager


def create_file_with_approval(file_path: str, content: str, description: str = "", requester: str = "system") -> tuple[bool, str]:
    """
    Create a file with approval from Code Manager.
    
    Args:
        file_path: Path to the file to create
        content: Content to write to the file
        description: Description of the file being created
        requester: Name of the requester
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Request approval
    approved, message = code_manager.request_code_creation(file_path, description, requester)
    
    if not approved:
        return False, message
    
    # Create the file
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        
        return True, f"File created successfully: {file_path}"
    except Exception as e:
        return False, f"Error creating file: {e}"


def delete_file_with_approval(file_path: str, reason: str = "", requester: str = "system") -> tuple[bool, str]:
    """
    Delete a file with approval from Code Manager.
    
    Args:
        file_path: Path to the file to delete
        reason: Reason for deletion
        requester: Name of the requester
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Request approval
    approved, message = code_manager.request_code_deletion(file_path, reason, requester)
    
    if not approved:
        return False, message
    
    # Delete the file
    try:
        os.remove(file_path)
        return True, f"File deleted successfully: {file_path}"
    except Exception as e:
        return False, f"Error deleting file: {e}"


def modify_file_with_approval(file_path: str, content: str, description: str = "", requester: str = "system") -> tuple[bool, str]:
    """
    Modify a file with approval from Code Manager.
    
    Args:
        file_path: Path to the file to modify
        content: New content to write to the file
        description: Description of the modification
        requester: Name of the requester
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Request approval
    approved, message = code_manager.request_code_modification(file_path, description, requester)
    
    if not approved:
        return False, message
    
    # Modify the file
    try:
        with open(file_path, 'w') as f:
            f.write(content)
        return True, f"File modified successfully: {file_path}"
    except Exception as e:
        return False, f"Error modifying file: {e}"


def check_file_exists(file_path: str) -> bool:
    """
    Check if a file exists.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file exists, False otherwise
    """
    return os.path.exists(file_path)


def read_file_safe(file_path: str) -> tuple[bool, str, str]:
    """
    Read a file safely (no approval required for reading).
    
    Args:
        file_path: Path to the file to read
        
    Returns:
        Tuple of (success: bool, content: str, message: str)
    """
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        return True, content, "File read successfully"
    except Exception as e:
        return False, "", f"Error reading file: {e}"


def execute_approved_requests():
    """
    Execute all approved requests.
    This function should be called after approval to actually perform the file operations.
    """
    approved_requests = code_manager.get_approved_requests()
    
    if not approved_requests:
        return 0, "No approved requests to execute"
    
    executed = 0
    failed = 0
    
    for request in approved_requests:
        try:
            request_type = request["type"]
            file_path = request["file_path"]
            
            if request_type == "CREATE":
                # For CREATE requests, create an empty file with metadata
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w') as f:
                    f.write(f"# Auto-created file\n# Description: {request['description']}\n# Requester: {request['requester']}\n")
                executed += 1
                logger.info(f"Executed CREATE request: {file_path}")
            
            elif request_type == "DELETE":
                if os.path.exists(file_path):
                    os.remove(file_path)
                    executed += 1
                    logger.info(f"Executed DELETE request: {file_path}")
                else:
                    logger.warning(f"File not found for DELETE request: {file_path}")
                    failed += 1
            
            elif request_type == "MODIFY":
                logger.warning(f"MODIFY request execution not implemented: {file_path}")
                failed += 1
            
        except Exception as e:
            logger.error(f"Error executing request: {e}")
            failed += 1
    
    # Clear approved requests after execution
    code_manager.clear_approved_requests()
    
    return executed, f"Executed {executed} requests, {failed} failed"

"""
Password validation utilities
"""
import re
from typing import Tuple

def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password meets security requirements
    
    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        return False, "Password must contain at least one special character (!@#$%^&* etc.)"
    
    return True, ""

def get_password_requirements() -> dict:
    """Get password requirements for display to users"""
    return {
        "min_length": 8,
        "requires_uppercase": True,
        "requires_lowercase": True,
        "requires_number": True,
        "requires_special": True,
        "message": "Password must be at least 8 characters and contain uppercase, lowercase, number, and special character"
    }
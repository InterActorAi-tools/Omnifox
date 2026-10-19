from fastapi import HTTPException, status
from typing import List

# 🔥 DASHBOARD ACCESS - Restricted to specific emails only
DASHBOARD_EMAILS = [
    "dena.t@in2-comms.com",
    "m.alsamarrai@in2-comms.com",
    "superadmin@in2-comms.com",
    "ali.a@in2-comms.com"
]

# 🔥 BASIC ACCESS - Allow entire domains
ALLOWED_DOMAINS = [
    "in2-comms.com",
]

# 🔥 SPECIFIC EMAILS - Additional allowed emails
ALLOWED_EMAILS = []

def get_default_roles_for_email(email: str) -> List[str]:
    """Determine which roles to assign based on email"""
    
    # Dashboard access (restricted)
    if email.lower() in [e.lower() for e in DASHBOARD_EMAILS]:
        return ['dashboard_user']  # Can access dashboard
    
    # Domain-based access (basic users)
    email_domain = email.split('@')[-1].lower()
    if email_domain in [d.lower() for d in ALLOWED_DOMAINS]:
        return ['basic_user']  # Can access main site, not dashboard
    
    # Specific allowed emails
    if email.lower() in [e.lower() for e in ALLOWED_EMAILS]:
        return ['basic_user']
    
    # Not allowed
    return []

def check_email_allowed(email: str) -> bool:
    """Check if email can register"""
    return len(get_default_roles_for_email(email)) > 0

def require_whitelisted_email(email: str):
    """Raise exception if email not allowed"""
    if not check_email_allowed(email):
        email_domain = email.split('@')[-1]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email domain '@{email_domain}' is not authorized. Please contact your administrator."
        )


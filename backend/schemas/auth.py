from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, Dict, Any, List
import json  # ← ADD THIS IMPORT

# Request schemas
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    token: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class GoogleLogin(BaseModel):
    credential: str  # Google JWT token

class TwoFactorVerify(BaseModel):
    code: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None  # browsers send {} and use the cookie

# Response schemas
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    auth_provider: str
    email_verified: bool
    two_factor_enabled: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    # 🔥 NEW: Include roles
    roles: List[str] = []
    permissions: List[str] = []
    
    @classmethod
    def from_user(cls, user):
        """Create UserResponse from User model"""
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            picture_url=user.picture_url,
            auth_provider=user.auth_provider,
            email_verified=user.email_verified,
            two_factor_enabled=user.two_factor_enabled,
            created_at=user.created_at,
            last_login=user.last_login,
            roles=user.get_role_names(),
            permissions=user.get_permission_names()
        )

class TokenResponse(BaseModel):
    # H10: tokens are no longer returned in the response body. The
    # backend now sets HttpOnly cookies (access_token, refresh_token)
    # plus a JS-readable XSRF-TOKEN cookie. Frontends must rely on
    # cookies for credential transport; only the `user` payload remains
    # useful in the response body.
    #
    # The legacy `access_token` / `refresh_token` fields are retained
    # in the schema as empty strings purely so any callers (e.g. CI
    # smoke scripts) that still destructure them do not raise a key
    # error. A future deploy can drop them entirely.
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "cookie"
    user: UserResponse
    requires_2fa: bool = False

class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    device_name: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    last_used: datetime

# 🔧 FIXED: ActivityLogResponse with JSON validator
class ActivityLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    action: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    # ✅ ADD THIS VALIDATOR - This is the fix!
    @field_validator('details', mode='before')
    @classmethod
    def parse_details_json(cls, v):
        """
        Parse details from JSON string to dict if needed.
        Handles SQLAlchemy JSON column returning string instead of dict.
        """
        if v is None:
            return None
        
        # If it's already a dict, return it
        if isinstance(v, dict):
            return v
        
        # If it's a string, parse it as JSON
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If parsing fails, return empty dict
                return {}
        
        return v

class ActivityLogStats(BaseModel):
    total_activities: int
    unique_actions: List[str]
    date_range: Dict[str, str]
    top_actions: List[Dict[str, Any]]

def activity_log_to_response(log, admin_view: bool = False) -> ActivityLogResponse:
    """Convert ActivityLog model to ActivityLogResponse schema.

    admin_view: admins see who did what and when (security log), never the
    user's IP, device or the details (file names, URLs).
    """
    if admin_view:
        return ActivityLogResponse(
            id=log.id,
            user_id=log.user_id,
            user_email=log.user.email if log.user else "System",
            user_name=log.user.name if log.user else "System",
            action=log.action,
            created_at=log.created_at,
        )
    return ActivityLogResponse(
        id=log.id,
        user_id=log.user_id,
        user_email=log.user.email if log.user else "System",
        user_name=log.user.name if log.user else "System",
        action=log.action,
        ip_address=log.ip_address or "Unknown",
        user_agent=log.user_agent,
        details=log.extra_data,  # ← Map extra_data to details (validator will handle it)
        created_at=log.created_at
    )
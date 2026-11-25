from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from config import settings
from database import get_db
from models import User, Role, RefreshToken, Invitation, JoinRequest
from schemas.auth import UserResponse, SessionResponse
from utils.dependencies import find_user_by_email, get_admin_user, log_activity
from services.privacy import delete_user_data
from utils.security import hash_token
from utils.whitelist import require_whitelisted_email
from utils.email_service import send_invite_email, send_welcome_email
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import secrets

router = APIRouter(prefix="/admin", tags=["Admin"])

# Schemas
class UpdateUserRolesRequest(BaseModel):
    role_names: List[str]

class AcceptJoinRequest(BaseModel):
    role: str = "basic_user"

class GenerateInviteRequest(BaseModel):
    email: EmailStr
    name: str
    role: str = "basic_user"

# Get all users (Admin only)
@router.get("/users", response_model=List[UserResponse])
def get_all_users(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all users - Admin only"""
    users = db.query(User).all()
    return [UserResponse.from_user(user) for user in users]

# Update user roles (Admin only)
@router.put("/users/{user_id}/roles", response_model=UserResponse)
def update_user_roles(
    user_id: int,
    roles_data: UpdateUserRolesRequest,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Update user roles - Admin only"""
    
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Can't modify own roles
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify your own roles"
        )
    
    # Clear existing roles
    user.roles.clear()
    
    # Add new roles
    for role_name in roles_data.role_names:
        role = db.query(Role).filter(Role.name == role_name).first()
        if role:
            user.roles.append(role)
    
    db.commit()
    db.refresh(user)
    log_activity(db, current_user.id, "admin_roles_changed", request.client.host, None,
                 {"target_email": user.email, "roles": user.get_role_names()})

    return UserResponse.from_user(user)

# Delete user (Admin only)
@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Delete user - Admin only"""
    
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Can't delete yourself
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    target_email = user.email
    delete_user_data(db, user, delete_account=True)
    log_activity(db, current_user.id, "admin_user_deleted", request.client.host, None, {"target_email": target_email})

    return {"message": "User deleted successfully"}

# Make a password reset link to send by hand (no email server needed)
@router.post("/users/{user_id}/reset-link")
def create_reset_link(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Create a 24-hour password reset link for a user - Admin only"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = secrets.token_urlsafe(32)
    user.reset_token_hash = hash_token(token)
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=24)
    db.commit()
    log_activity(db, current_user.id, "admin_reset_link_created", request.client.host, None, {"target_email": user.email})

    return {"link": f"{settings.frontend_url}/reset-password?token={token}"}

# Get all available roles
@router.get("/roles")
def get_all_roles(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all available roles - Admin only"""
    roles = db.query(Role).all()
    return [
        {
            "name": role.name,
            "description": role.description,
            "permissions": [p.name for p in role.permissions]
        }
        for role in roles
    ]

# Admin Session Management
@router.get("/users/{user_id}/sessions", response_model=List[SessionResponse])
def get_user_sessions_admin(
    user_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """(Admin) A user's active sessions, without device or IP (personal data)."""
    sessions = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False,
    ).order_by(RefreshToken.last_used.desc()).all()

    return [SessionResponse(id=s.id, created_at=s.created_at, last_used=s.last_used) for s in sessions]

@router.get("/invitations")
def get_pending_invitations(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all pending (unused) invitations.

    M3: the raw token + the constructed registration link were both
    returned for every pending invite. A compromised admin session
    could lift all pending tokens at once and pre-register accounts
    on behalf of every invited user. The raw token is now only
    returned ONCE - at the moment the invitation is generated by
    /admin/invitations/generate - and never again. The list endpoint
    is purely metadata.
    """
    invites = db.query(Invitation).filter(
        Invitation.is_used == False,
        Invitation.expires_at > datetime.utcnow()
    ).all()

    return [
        {
            "id": inv.id,
            "email": inv.email,
            "name": inv.name,
            "role": inv.role,
            "expires_at": inv.expires_at,
            "created_at": inv.created_at,
        }
        for inv in invites
    ]

@router.delete("/users/{user_id}/sessions/{session_id}")
def revoke_user_session_admin(
    user_id: int,
    session_id: int,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """(Admin) Revoke a specific session for a user"""
    session = db.query(RefreshToken).filter(
        RefreshToken.id == session_id,
        RefreshToken.user_id == user_id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    db.delete(session)
    db.commit()
    log_activity(db, current_user.id, "admin_session_revoked", request.client.host, request.headers.get("user-agent"), {"target_user_id": user_id})
    return {"message": "Session revoked successfully"}

# Invite Generator
@router.post("/invitations/generate")
def generate_invitation_link(
    data: GenerateInviteRequest,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Generate a unique registration link for a specific person"""
    if find_user_by_email(db, data.email):
        raise HTTPException(status_code=400, detail="User with this email already exists")
    require_whitelisted_email(data.email)  # @in2-comms.com only

    if not db.query(Role).filter(Role.name == data.role).first():
        raise HTTPException(status_code=400, detail=f"Unknown role '{data.role}'")

    token = secrets.token_urlsafe(32)
    
    invite = Invitation(
        token=token,
        email=data.email.strip().lower(),
        name=data.name,
        role=data.role,
        created_by=current_user.id,
        expires_at=datetime.utcnow() + timedelta(hours=24)
    )
    
    db.add(invite)
    db.commit()
    
    # H12: invitation base URL must come from server config, never from
    # the request's Origin header. Trusting Origin lets a compromised
    # admin session (or an admin tricked into hitting an attacker-crafted
    # admin-tool URL with a forged Origin) generate phishing links that
    # arrive from Omnifox's legitimate Resend sender domain.
    invite_link = f"{settings.frontend_url}/register?token={token}"
    
    email_sent = send_invite_email(invite.email, data.name, invite_link)
    log_activity(db, current_user.id, "invitation_generated", request.client.host, None,
                 {"target_email": data.email, "email_sent": email_sent})

    return {
        "link": invite_link,
        "token": token,
        "expires_at": invite.expires_at,
        "email_sent": email_sent,
    }

# Join requests (people asking to join without an invitation)
@router.get("/join-requests")
def get_join_requests(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Requests waiting for an admin - Admin only"""
    requests = db.query(JoinRequest).order_by(JoinRequest.created_at).all()
    return [{"id": r.id, "email": r.email, "name": r.name, "created_at": r.created_at} for r in requests]

@router.post("/join-requests/{request_id}/accept", response_model=UserResponse)
def accept_join_request(
    request_id: int,
    data: AcceptJoinRequest,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Create the account with the password the person chose - Admin only"""
    join = db.query(JoinRequest).filter(JoinRequest.id == request_id).first()
    if not join:
        raise HTTPException(status_code=404, detail="Request not found")
    role = db.query(Role).filter(Role.name == data.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role '{data.role}'")
    if find_user_by_email(db, join.email):
        raise HTTPException(status_code=400, detail="User with this email already exists")

    user = User(email=join.email, name=join.name, hashed_password=join.hashed_password,
                auth_provider="email", email_verified=True)
    user.roles.append(role)
    db.add(user)
    db.delete(join)
    db.commit()
    db.refresh(user)
    email_sent = send_welcome_email(user.email, user.name)
    log_activity(db, current_user.id, "join_request_accepted", request.client.host, None,
                 {"target_email": user.email, "role": role.name, "email_sent": email_sent})
    return UserResponse.from_user(user)

@router.delete("/join-requests/{request_id}")
def reject_join_request(
    request_id: int,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Reject a request; the person can ask again - Admin only"""
    join = db.query(JoinRequest).filter(JoinRequest.id == request_id).first()
    if not join:
        raise HTTPException(status_code=404, detail="Request not found")
    target_email = join.email
    db.delete(join)
    db.commit()
    log_activity(db, current_user.id, "join_request_rejected", request.client.host, None, {"target_email": target_email})
    return {"message": "Request rejected"}

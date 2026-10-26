import asyncio

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from schemas.auth import ActivityLogResponse, activity_log_to_response # <-- 1. IMPORT THE HELPER
from database import get_db
from models import User, RefreshToken, ActivityLog
from schemas.auth import UserResponse, SessionResponse
from utils import keys
from utils.dependencies import current_session, get_current_user, log_activity
from utils.cookies import ACCESS_TOKEN_COOKIE, clear_auth_cookies
from models import Role
from services.privacy import delete_result, delete_user_data, export_user_data
from utils.rate_limit import USER_OR_IP, limiter
# 1. Add these imports at the top
from pydantic import BaseModel
from utils.password_validator import validate_password_strength
from utils.security import (
    verify_password,
    hash_password,
    generate_totp_secret,
    get_totp_uri,
    verify_totp,
    generate_verification_token,
    hash_backup_codes,
    verify_token,
)

router = APIRouter(prefix="/users", tags=["Users"])

class Confirm2FARequest(BaseModel):
    code: str

class Disable2FARequest(BaseModel):
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ================================================
#          2FA MANAGEMENT ENDPOINTS
# ================================================

@router.post("/me/2fa/enable")
def enable_2fa(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a new 2FA secret and return a QR code URI.
    Does not fully enable 2FA until confirmed.
    """
    if current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled."
        )

    # Generate a new secret
    secret = generate_totp_secret()
    current_user.two_factor_secret = secret
    db.commit()
    
    qr_code_uri = get_totp_uri(secret, current_user.email)
    
    log_activity(db, current_user.id, "2fa_enable_started", request.client.host)
    
    return {"qr_code_uri": qr_code_uri, "secret": secret}

@router.post("/me/2fa/confirm")
def confirm_2fa(
    data: Confirm2FARequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirm and activate 2FA with a valid code.
    """
    if not current_user.two_factor_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup was not initiated. Please enable first."
        )

    if not verify_totp(current_user.two_factor_secret, data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid 2FA code."
        )

    # Generate backup codes (6 codes, ~60 bits of entropy each).
    # Plaintext is returned to the user ONCE in the response below; what
    # we persist is Argon2 hashes (H3 / L6) so a DB dump cannot replay
    # them and the runtime comparison is constant-time.
    backup_codes = [generate_verification_token()[:10] for _ in range(6)]

    current_user.two_factor_enabled = True
    current_user.backup_codes = hash_backup_codes(backup_codes)
    db.commit()

    log_activity(db, current_user.id, "2fa_enable_success", request.client.host)

    return {
        "message": "2FA enabled successfully.",
        "backup_codes": backup_codes
    }

@router.post("/me/2fa/disable")
def disable_2fa(
    data: Disable2FARequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Disable 2FA by verifying the user's password.
    """
    if not current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not currently enabled."
        )
        
    # Password, or a current 2FA code (Google accounts have no password).
    verified = (bool(current_user.hashed_password) and verify_password(data.password, current_user.hashed_password)) \
        or verify_totp(current_user.two_factor_secret, data.password)
    if not verified:
        log_activity(db, current_user.id, "2fa_disable_failed", request.client.host, request.headers.get("user-agent", "unknown"), {"reason": "invalid_password"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password"
        )
    
    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    current_user.backup_codes = None
    db.commit()
    
    log_activity(db, current_user.id, "2fa_disable_success", request.client.host)
    
    return {"message": "2FA has been disabled."}

# ================================================
@router.post("/me/change-password")
async def change_current_user_password(
    data: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change the current user's password"""
    
    # 1. Verify current password
    if not current_user.hashed_password or not verify_password(data.current_password, current_user.hashed_password):
        log_activity(db, current_user.id, "change_password_failed", request.client.host, request.headers.get("user-agent", "unknown"), {"reason": "invalid_current_password"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid current password"
        )
    
    # 2. Validate new password strength
    is_valid, error_message = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )
    
    # 3. Hash and save new password; the private-project key follows it
    current_user.hashed_password = hash_password(data.new_password)
    private = keys.open_private_key(current_user, data.current_password)
    if private:
        keys.relock_private_key(current_user, private, data.new_password)

    # End all other sessions; keep the one making this request.
    token = request.cookies.get(ACCESS_TOKEN_COOKIE) or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    current_session_id = (verify_token(token) or {}).get("session_id") if token else None
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.id != current_session_id,
    ).delete(synchronize_session=False)
    db.commit()
    
    # 4. Log success
    log_activity(db, current_user.id, "change_password_success", request.client.host, request.headers.get("user-agent", "unknown"))
    
    return {"message": "Password changed successfully"}

class RecoverKeyRequest(BaseModel):
    recovery_code: str
    password: str


class ResetKeyRequest(BaseModel):
    password: str


def _require_password(user: User, password: str) -> None:
    if not user.hashed_password or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid password")


@router.get("/me/keys")
async def get_my_keys(current_user: User = Depends(get_current_user)):
    """Whether you have a private-project key and this session has it unlocked."""
    return {"has_keys": bool(current_user.public_key), "unlocked": keys.is_unlocked(),
            "has_password": bool(current_user.hashed_password)}


@router.post("/me/keys/recover")
@limiter.limit("5/minute", key_func=USER_OR_IP)
async def recover_my_key(
    data: RecoverKeyRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """After a password reset: unlock your key with the recovery code and lock it with the new password."""
    _require_password(current_user, data.password)
    private = keys.open_private_key(current_user, data.recovery_code, recovery=True)
    if not private:
        log_activity(db, current_user.id, "key_recovery_failed", request.client.host)
        raise HTTPException(status_code=400, detail="That recovery code does not match")
    keys.relock_private_key(current_user, private, data.password)
    keys.start_session(db, current_user, current_session(request, db), response, {"private": private})
    log_activity(db, current_user.id, "key_recovered", request.client.host)
    return {"message": "Your private projects are unlocked again"}


@router.post("/me/keys/reset")
@limiter.limit("5/minute", key_func=USER_OR_IP)
async def reset_my_key(
    data: ResetKeyRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Without the recovery code: start over with a new key. Private projects
    nobody else can open are deleted; owners must share theirs with you again."""
    _require_password(current_user, data.password)
    private, code, fields = keys.new_user_keys(data.password)
    keys.drop_user_keys(db, current_user)
    for name, value in fields.items():
        setattr(current_user, name, value)
    keys.start_session(db, current_user, current_session(request, db), response, {"private": private})
    log_activity(db, current_user.id, "key_reset", request.client.host)
    return {"recovery_code": code}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user information"""
    return UserResponse.from_user(current_user)  # ← CHANGE THIS LINE

@router.get("/me/sessions", response_model=list[SessionResponse])
def get_user_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all active sessions for current user"""
    # Rotated rows are kept (is_revoked=True) only for reuse detection.
    sessions = db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False,
    ).order_by(RefreshToken.last_used.desc()).all()
    
    return sessions

@router.get("/me/activity", response_model=list[ActivityLogResponse])
def get_user_activity(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get activity history for current user"""
    activities = db.query(ActivityLog).filter(
        ActivityLog.user_id == current_user.id
    ).order_by(ActivityLog.created_at.desc()).limit(limit).all()
    
    # v--- 2. CONVERT THE MODELS BEFORE RETURNING
    return [activity_log_to_response(log) for log in activities] # <--- ✅ THIS IS THE FIX

@router.delete("/me/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific session"""
    session = db.query(RefreshToken).filter(
        RefreshToken.id == session_id,
        RefreshToken.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@router.post("/me/logout-all")
def logout_all_devices(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Logout from all devices"""
    # Delete all refresh tokens except current one
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id
    ).delete()
    
    db.commit()
    
    log_activity(db, current_user.id, "logout_all_devices", request.client.host)
    
    return {"message": "Logged out from all devices"}


# ================================================
#          YOUR DATA (GDPR)
# ================================================

class ConfirmByEmailRequest(BaseModel):
    confirm_email: str


def _require_email_confirmation(data: ConfirmByEmailRequest, user: User) -> None:
    if data.confirm_email.strip().lower() != user.email.lower():
        raise HTTPException(status_code=400, detail="Type your email address to confirm.")


@router.get("/me/export")
@limiter.limit("5/hour", key_func=USER_OR_IP)
async def export_my_data(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download everything held about you as a ZIP (GDPR access and portability)."""
    log_activity(db, current_user.id, "data_exported", request.client.host, request.headers.get("user-agent"))
    # Building the ZIP decrypts every file: keep it off the event loop.
    content = await asyncio.to_thread(export_user_data, db, current_user)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="omnifox-my-data.zip"'},
    )


@router.delete("/me/results/{filename}")
def delete_my_result(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete one of your results (file and stored analysis)."""
    if not delete_result(db, current_user.email, filename):
        raise HTTPException(status_code=404, detail="Result not found")
    return {"message": "Result deleted"}


@router.post("/me/delete-data")
def delete_my_data(
    data: ConfirmByEmailRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erase all your files, analyses and activity. Your account stays."""
    _require_email_confirmation(data, current_user)
    delete_user_data(db, current_user)
    log_activity(db, current_user.id, "data_deleted", request.client.host, request.headers.get("user-agent"))
    return {"message": "All your data has been deleted"}


@router.post("/me/delete-account")
def delete_my_account(
    data: ConfirmByEmailRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erase your account and everything linked to it (right to erasure)."""
    _require_email_confirmation(data, current_user)
    if any(r.name == "admin" for r in current_user.roles):
        admins = db.query(User).filter(User.roles.any(Role.name == "admin")).count()
        if admins <= 1:
            raise HTTPException(status_code=400, detail="You are the only admin. Make someone else an admin first.")
    delete_user_data(db, current_user, delete_account=True)
    clear_auth_cookies(response)
    return {"message": "Your account has been deleted"}


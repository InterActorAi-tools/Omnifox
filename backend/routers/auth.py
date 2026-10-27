import logging
from fastapi import APIRouter, Depends, HTTPException, Response, status, Request
from sqlalchemy.orm import Session
from google.oauth2 import id_token
from google.auth.transport import requests
from datetime import datetime, timedelta, timezone
from models import Invitation, JoinRequest

logger = logging.getLogger(__name__)

from utils.email_service import send_password_reset_email
from utils.security import generate_verification_token, verify_totp
from pydantic import BaseModel, EmailStr

from utils.password_validator import validate_password_strength, get_password_requirements
from database import get_db
from models import User, RefreshToken, Role
from schemas.auth import (
    UserRegister, UserLogin, GoogleLogin, TokenResponse, 
    UserResponse, RefreshTokenRequest
)
from utils.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, verify_token, hash_token,
    consume_backup_code, create_pending_2fa_token,
)
from utils.cookies import (
    ACCESS_TOKEN_COOKIE,
    PENDING_2FA_COOKIE,
    REFRESH_TOKEN_COOKIE,
    clear_auth_cookies,
    clear_pending_2fa_cookie,
    set_auth_cookies,
    set_pending_2fa_cookie,
)
from utils.dependencies import find_user_by_email, log_activity, get_current_user
from utils import keys
from utils.rate_limit import limiter
from utils.whitelist import require_whitelisted_email, get_default_roles_for_email
from config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


class Verify2FARequest(BaseModel):
    email: EmailStr
    code: str


class JoinRequestCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


REFRESH_REUSE_GRACE_SECONDS = 30


def _is_future(dt: datetime | None) -> bool:
    """Compare a DB timestamp against now. Postgres returns tz-aware
    values while SQLite returns naive UTC, so normalize before comparing."""
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > datetime.now(timezone.utc)

# 1. ADD THIS NEW ENDPOINT
@router.get("/invitation/{token}")
def get_invitation_details(token: str, db: Session = Depends(get_db)):
    """Get details of an invitation token"""
    invite = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.is_used == False,
        Invitation.expires_at > datetime.utcnow()
    ).first()
    
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")
        
    return {
        "email": invite.email,
        "name": invite.name,
        "role": invite.role
    }

@router.post("/register", response_model=TokenResponse)
async def register(
    user_data: UserRegister,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Register new user (Requires Invitation Token)"""    
    
    # 1. Validate Invitation Token
    invite = db.query(Invitation).filter(
        Invitation.token == user_data.token,
        Invitation.is_used == False,
        Invitation.expires_at > datetime.utcnow()
    ).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation link."
        )

# 🔥 CRITICAL: Enforce that the registering email matches the invite
    if invite.email.lower() != user_data.email.lower():
         raise HTTPException(status_code=400, detail="This invitation is for a different email address.")
    
    # 2. Validate password strength
    is_valid, error_message = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    
    # 3. Check if email exists
    if find_user_by_email(db, user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # 4. Create user
    hashed = hash_password(user_data.password)
    new_user = User(
        email=user_data.email.strip().lower(),
        hashed_password=hashed,
        name=user_data.name,
        auth_provider="email",
        email_verified=True # Verified because they had an invite code
    )
    
    db.add(new_user)
    
    # 5. Assign Role from Invitation
    role = db.query(Role).filter(Role.name == invite.role).first()
    if role:
        new_user.roles.append(role)

    # 6. Mark Invitation as Used
    invite.is_used = True
    
    db.commit()
    db.refresh(new_user)
    
    # Log activity
    log_activity(db, new_user.id, "user_registered", request.client.host, request.headers.get("user-agent", "unknown"))
    
    # --- FIX STARTS HERE ---
    # 1. Create Refresh Token Record FIRST to get the ID
    refresh_token_str = create_refresh_token(new_user.id)
    token_hash = hash_token(refresh_token_str)
    
    refresh_record = RefreshToken(
        user_id=new_user.id,
        token_hash=token_hash,
        device_name=request.headers.get("user-agent", "Unknown")[:255],
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent", "Unknown"),
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_record)
    db.commit()
    db.refresh(refresh_record) 
    
    # 2. Create Access Token WITH the Session ID
    access_token = create_access_token(new_user.id, new_user.email, session_id=refresh_record.id)
    # --- FIX ENDS HERE ---

    # H10: tokens flow to the browser via HttpOnly cookies, not JSON.
    set_auth_cookies(response, access_token, refresh_token_str)
    recovery_code = keys.start_session(db, new_user, refresh_record, response, keys.login_keys(new_user, user_data.password))

    return TokenResponse(
        user=UserResponse.from_user(new_user),
        recovery_code=recovery_code,
    )

@router.post("/join-request")
@limiter.limit("5/hour")
def request_to_join(
    data: JoinRequestCreate,
    request: Request,
    response: Response,  # slowapi writes rate-limit headers here
    db: Session = Depends(get_db)
):
    """Ask to join without an invitation. An admin accepts or rejects it."""
    email = data.email.strip().lower()
    require_whitelisted_email(email)  # @in2-comms.com only
    is_valid, error_message = validate_password_strength(data.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    if find_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(JoinRequest).filter(JoinRequest.email == email).first():
        raise HTTPException(status_code=400, detail="A request for this email is already waiting for an admin")

    db.add(JoinRequest(email=email, name=data.name.strip(), hashed_password=hash_password(data.password)))
    db.commit()
    return {"message": "Request sent. You can log in once an admin accepts it."}


@router.get("/password-requirements")
def get_requirements():
    """Get password requirements for frontend display"""
    return get_password_requirements()


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # H2: brute-force defense per source IP
async def login(
    credentials: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Login with email/password"""
    
    # Find user
    user = find_user_by_email(db, credentials.email)
    if not user:
        pending = db.query(JoinRequest).filter(JoinRequest.email == credentials.email.strip().lower()).first()
        if pending and verify_password(credentials.password, pending.hashed_password):
            raise HTTPException(status_code=403, detail="Your request to join is waiting for an admin to accept it.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check account lock. L7: never echo the precise lockout timestamp
    # back to the caller - it confirms the account exists for that
    # email (enumeration) and tells the attacker exactly when to retry.
    # Log the timestamp server-side; return a generic message.
    if _is_future(user.locked_until):
        logger.info(
            "Login attempt on locked account user_id=%s locked_until=%s",
            user.id, user.locked_until,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked. Try again later.",
        )
    
    # Verify password
    if not user.hashed_password or not verify_password(credentials.password, user.hashed_password):
        user.failed_login_attempts += 1
        
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(hours=1)
            log_activity(db, user.id, "account_locked", request.client.host, request.headers.get("user-agent", "unknown"))
        
        db.commit()
        log_activity(db, user.id, "login_failed", request.client.host, request.headers.get("user-agent", "unknown"))
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Check 2FA - no session cookies are issued here. A short-lived
    # pending-2FA cookie proves the password step passed; /auth/verify-2fa
    # requires it so the second factor cannot be used on its own.
    login_keys = keys.login_keys(user, credentials.password)
    if user.two_factor_enabled:
        set_pending_2fa_cookie(response, create_pending_2fa_token(user.id, keys.pack(login_keys)))
        return TokenResponse(
            user=UserResponse.from_user(user),
            requires_2fa=True,
        )
    
    # Success - reset failed attempts
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()
    
    log_activity(db, user.id, "user_login", request.client.host, request.headers.get("user-agent", "unknown"))
    
    # Create tokens (Fixed Order for Instant Revocation)
    refresh_token_str = create_refresh_token(user.id)
    token_hash = hash_token(refresh_token_str)
    
    # Store refresh token first
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        device_name=request.headers.get("user-agent", "Unknown")[:255],
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent", "Unknown"),
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_record)
    db.commit()
    db.refresh(refresh_record)
    
    # Create access token linked to session ID
    access_token = create_access_token(user.id, user.email, session_id=refresh_record.id)

    # H10: cookies, not JSON tokens.
    set_auth_cookies(response, access_token, refresh_token_str)
    recovery_code = keys.start_session(db, user, refresh_record, response, login_keys)

    return TokenResponse(
        user=UserResponse.from_user(user),
        recovery_code=recovery_code,
        keys_locked=bool(user.public_key) and not login_keys["private"],
    )

# --- ADD THIS MODEL ---
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ================================================
#          2FA VERIFICATION ENDPOINT
# ================================================
@router.post("/verify-2fa", response_model=TokenResponse)
@limiter.limit("5/minute")  # H2: secondary brute-force defense on top of H3 lockout
async def verify_2fa(
    data: Verify2FARequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Verify the 2FA code (TOTP) OR a backup code.

    Hardened per H3:
      - reuses the same `failed_login_attempts` / `locked_until` lockout
        mechanism as `/auth/login` so brute-force across the 1M-code TOTP
        keyspace stops at 5 wrong tries per hour
      - backup codes are compared via `consume_backup_code` (constant-time;
        Argon2-hashed at rest after re-issue)
      - failure response is identical for unknown email, missing 2FA,
        wrong TOTP, and wrong backup code - no enumeration
    """
    user = find_user_by_email(db, data.email)

    # 1. Basic user check. Identical 401 for "no such user" and
    # "user exists but 2FA not enabled" so neither leaks via response.
    generic_invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid 2FA code or backup code",
    )
    if not user:
        raise generic_invalid
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise generic_invalid

    # The pending-2FA cookie is issued only after a successful first
    # factor (password or Google) for this same user.
    pending = verify_token(request.cookies.get(PENDING_2FA_COOKIE) or "")
    if not pending or pending.get("type") != "2fa_pending" or pending.get("sub") != str(user.id):
        raise generic_invalid

    # 2. Lockout check (mirrors /auth/login behaviour).
    if _is_future(user.locked_until):
        # Keep the message generic for the same reason as L7 (no precise
        # timestamp leaked); status 403 distinguishes "locked" from
        # "wrong code" for legitimate users hitting the same endpoint.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked. Try again later.",
        )

    # 3. Try TOTP first, fall back to backup code. Both branches funnel
    # into the same failure path so timing differs only by Argon2 cost.
    totp_ok = verify_totp(user.two_factor_secret, data.code)

    backup_ok = False
    if not totp_ok:
        matched, new_blob = consume_backup_code(user.backup_codes, data.code)
        if matched:
            user.backup_codes = new_blob
            backup_ok = True

    if not (totp_ok or backup_ok):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(hours=1)
            log_activity(
                db, user.id, "account_locked_2fa",
                request.client.host,
                request.headers.get("user-agent", "unknown"),
            )
        db.commit()
        log_activity(db, user.id, "2fa_login_failed", request.client.host)
        raise generic_invalid

    if backup_ok:
        log_activity(db, user.id, "login_with_backup_code", request.client.host)

    # 4. Login Success - clear lockout state and proceed.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()
    
    log_activity(db, user.id, "user_login_2fa_success", request.client.host, request.headers.get("user-agent", "unknown"))
    
    # Create tokens (Fixed Order for Instant Revocation)
    refresh_token_str = create_refresh_token(user.id)
    token_hash = hash_token(refresh_token_str)
    
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        device_name=request.headers.get("user-agent", "Unknown")[:255],
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent", "Unknown"),
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_record)
    db.commit()
    db.refresh(refresh_record)
    
    access_token = create_access_token(user.id, user.email, session_id=refresh_record.id)

    set_auth_cookies(response, access_token, refresh_token_str)  # H10
    clear_pending_2fa_cookie(response)
    login_keys = keys.unpack(pending.get("keys"))
    recovery_code = keys.start_session(db, user, refresh_record, response, login_keys)

    return TokenResponse(
        user=UserResponse.from_user(user),
        recovery_code=recovery_code,
        keys_locked=bool(user.public_key) and "private" in login_keys and not login_keys["private"],
    )


# ================================================
#          FORGOT PASSWORD ENDPOINT
# ================================================
@router.post("/forgot-password")
@limiter.limit("3/minute")  # H2: limit reset-email abuse per source IP
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    response: Response,  # slowapi writes rate-limit headers here
    db: Session = Depends(get_db)
):
    """
    Send a password reset link to the user's email.
    """
    user = find_user_by_email(db, data.email)
    
    if user:
        # Generate a secure token
        token = generate_verification_token() # Re-using this function is perfect
        
        # Hash and store the token
        user.reset_token_hash = hash_token(token)
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1) # 1 hour expiry
        db.commit()
        
        # Send the email
        email_sent = await send_password_reset_email(user.email, token)
        
        # Same response whether or not the email went out, otherwise a
        # 500 here would reveal that the account exists.
        action = "forgot_password_requested" if email_sent else "forgot_password_email_failed"
        log_activity(db, user.id, action, request.client.host)

    # Always return a success message to prevent email enumeration attacks
    return {"message": "If an account with that email exists, a password reset link has been sent."}


# ================================================
#          RESET PASSWORD ENDPOINT
# ================================================
@router.post("/reset-password")
@limiter.limit("5/minute")  # H2
def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    response: Response,  # slowapi writes rate-limit headers here
    db: Session = Depends(get_db)
):
    """
    Reset the user's password using a valid token.
    """
    
    # Validate new password strength
    is_valid, error_message = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )
        
    # Find user by the hashed token
    token_hash = hash_token(data.token)
    
    user = db.query(User).filter(
        User.reset_token_hash == token_hash,
        User.reset_token_expires > datetime.utcnow()
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token."
        )
        
    # Set the new password
    user.hashed_password = hash_password(data.new_password)
    
    # Invalidate the token
    user.reset_token_hash = None
    user.reset_token_expires = None
    user.failed_login_attempts = 0
    user.locked_until = None

    # A reset usually means the old password may be compromised, so
    # end every existing session.
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).delete(synchronize_session=False)
    
    # Log the successful reset
    log_activity(db, user.id, "password_reset_success", request.client.host)
    
    db.commit()
    
    return {"message": "Password has been reset successfully. Please log in."}    


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")  # H2
def google_login(
    google_data: GoogleLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Login with Google OAuth"""
    
    # Without a configured client ID, verify_oauth2_token skips the
    # audience check and would accept ID tokens minted for any app.
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured"
        )

    try:
        # Verify Google token
        idinfo = id_token.verify_oauth2_token(
            google_data.credential,
            requests.Request(),
            settings.google_client_id
        )
        
        if not idinfo.get('email_verified'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account email is not verified"
            )

        google_id = idinfo['sub']
        email = idinfo['email'].strip().lower()
        name = idinfo.get('name')
        picture = idinfo.get('picture')
        
        # Find or create user. An existing email/password account with the
        # same verified email is linked instead of hitting the unique
        # constraint on users.email.
        user = db.query(User).filter(User.google_id == google_id).first()
        if not user:
            user = find_user_by_email(db, email)
            if user:
                user.google_id = google_id

        if user and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )

        if not user:
            # Check whitelist for new users
            require_whitelisted_email(email)
            
            # Create new user
            user = User(
                email=email,
                google_id=google_id,
                name=name,
                picture_url=picture,
                auth_provider="google",
                email_verified=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Assign roles
            role_names = get_default_roles_for_email(email)
            for role_name in role_names:
                role = db.query(Role).filter(Role.name == role_name).first()
                if role:
                    user.roles.append(role)
            
            db.commit()
            db.refresh(user)
            
            log_activity(db, user.id, "user_registered", request.client.host, request.headers.get("user-agent", "unknown"), {"method": "google"})
        else:
            # Update user info
            user.name = name
            user.picture_url = picture
            user.last_login = datetime.utcnow()
            db.commit()
            log_activity(db, user.id, "user_login", request.client.host, request.headers.get("user-agent", "unknown"), {"method": "google"})
        
        # Check 2FA - no session cookies issued yet; client must POST /verify-2fa.
        if user.two_factor_enabled:
            set_pending_2fa_cookie(response, create_pending_2fa_token(user.id))
            return TokenResponse(
                user=UserResponse.from_user(user),
                requires_2fa=True,
            )
        
        # Create tokens
        refresh_token_str = create_refresh_token(user.id)
        token_hash = hash_token(refresh_token_str)
        
        # Store refresh token
        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            device_name=request.headers.get("user-agent", "Unknown")[:255],
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent", "Unknown"),
            expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
        )
        db.add(refresh_record)
        db.commit()
        db.refresh(refresh_record)
        
        access_token = create_access_token(user.id, user.email, session_id=refresh_record.id)

        set_auth_cookies(response, access_token, refresh_token_str)  # H10

        return TokenResponse(
            user=UserResponse.from_user(user),
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google token"
        )

@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    token_data: RefreshTokenRequest | None = None,
):
    """Rotate refresh + access tokens.

    Each call issues a NEW refresh token and soft-revokes the old row.
    Replaying a previously-rotated (is_revoked=True) token is treated as a
    compromise signal: all of that user's refresh tokens are deleted,
    forcing every session to log in again.

    H10: the refresh token is read from the HttpOnly cookie. The legacy
    JSON-body path is kept for non-browser callers (admin curl,
    automated session tests). Cookie wins when both are present.
    """
    refresh_token_value = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token_value and token_data is not None:
        refresh_token_value = token_data.refresh_token
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    payload = verify_token(refresh_token_value)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    token_hash = hash_token(refresh_token_value)
    stored_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash
    ).first()

    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or expired. Please login again."
        )

    # Reuse detection: a token that was already rotated is being replayed.
    # Either the legitimate user replayed an old token (e.g., cached on
    # another tab) OR an attacker stole and is replaying a token whose
    # rotation already happened. We cannot tell which, so the safe action
    # is to nuke every refresh token for this user.
    # A token rotated seconds ago is the browser racing itself (two tabs
    # refreshing at once, a response lost to a reload or network drop), not
    # theft: rotate again instead of logging every device out.
    just_rotated = stored_token.last_used is not None and _is_future(
        stored_token.last_used + timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS))
    if stored_token.is_revoked and not just_rotated:
        # Cache the user_id BEFORE the bulk delete: SQLAlchemy expires the
        # instance on commit and re-reading attributes from the deleted
        # row raises ObjectDeletedError.
        compromised_user_id = stored_token.user_id
        db.query(RefreshToken).filter(
            RefreshToken.user_id == compromised_user_id
        ).delete(synchronize_session=False)
        db.commit()
        log_activity(
            db,
            compromised_user_id,
            "refresh_token_reuse_detected",
            request.client.host,
            request.headers.get("user-agent", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session compromised. All sessions have been logged out."
        )

    # Expiry check (defense in depth; JWT exp also enforces).
    if stored_token.expires_at and not _is_future(stored_token.expires_at):
        db.delete(stored_token)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired. Please login again."
        )

    user = db.query(User).filter(User.id == stored_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # --- Rotate -----------------------------------------------------------
    # 1. Mark the old row as revoked (kept for reuse detection above).
    stored_token.is_revoked = True
    stored_token.last_used = datetime.utcnow()

    # 2. Mint and persist a new refresh token row.
    new_refresh_token_str = create_refresh_token(user.id)
    new_token_hash = hash_token(new_refresh_token_str)
    new_record = RefreshToken(
        user_id=user.id,
        token_hash=new_token_hash,
        device_name=stored_token.device_name,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent", "Unknown")[:255],
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
        data_key=stored_token.data_key,  # the browser's data_key cookie still unlocks it
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    # 3. Mint a new access token bound to the NEW session row.
    access_token = create_access_token(user.id, user.email, session_id=new_record.id)

    # H10: rotation also issues fresh cookies. The browser overwrites
    # the previous access_token + refresh_token cookies (plus a fresh
    # CSRF token, matching the new session row's lifetime).
    set_auth_cookies(response, access_token, new_refresh_token_str)

    return TokenResponse(
        user=UserResponse.from_user(user),
    )

@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Logout the current session.

    Deletes the RefreshToken row tied to this access token so the session
    is gone immediately - the refresh token can no longer be used to mint
    new access tokens, and other sessions for this user are unaffected.

    H10: also clears all auth cookies on the response so the browser
    drops them on the way out.
    """
    # The session_id lives inside the access-token JWT. Resolve the
    # raw token the same way get_current_user did - cookie first, then
    # Authorization header.
    raw_token = (
        request.cookies.get(ACCESS_TOKEN_COOKIE)
        or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        or None
    )
    payload = verify_token(raw_token) if raw_token else {}
    payload = payload or {}
    session_id = payload.get("session_id")
    if session_id:
        deleted = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.id == session_id,
                RefreshToken.user_id == current_user.id,
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            db.commit()

    clear_auth_cookies(response)

    log_activity(
        db,
        current_user.id,
        "user_logout",
        request.client.host,
        request.headers.get("user-agent", "unknown"),
    )

    return {"message": "Logged out successfully"}
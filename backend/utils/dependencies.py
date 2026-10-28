from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import SessionLocal, get_db
from models import User, RefreshToken
from utils import keys
from utils.cookies import ACCESS_TOKEN_COOKIE, DATA_KEY_COOKIE
from utils.security import verify_token
from task_manager import task_manager, TaskStatus

# `auto_error=False`: we don't want HTTPBearer to raise 403 when the
# Authorization header is missing, because the primary credential source
# is now the HttpOnly access_token cookie (H10). Bearer is kept as a
# fallback for non-browser callers (admin curl, CI smoke).
security = HTTPBearer(auto_error=False)


def _extract_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Resolve the access token from cookie (preferred) or Bearer header.

    Returns None if neither source has a value. The cookie wins when
    both are present so a stale Authorization header from an old client
    cannot override the current session.
    """
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    if credentials and credentials.credentials:
        return credentials.credentials
    return None


PASSWORD_CHANGE_PATHS = {"/api/users/me", "/api/users/me/change-password", "/api/auth/logout"}


def _user_from_token(token: str, db: Session, request: Request | None = None) -> User:
    """Validate a JWT and return the corresponding User row.

    Mirrors the previous inline logic in get_current_user. Lifted out
    so the cookie path, the Bearer path, and the SSE cookie path can
    share one implementation.
    """
    payload = verify_token(token)
    # Only access tokens authenticate requests; a refresh or pending-2FA
    # token carries no session_id and would otherwise bypass revocation.
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # If the token has a session_id, verify the session row exists AND has
    # not been revoked. A revoked row is kept for refresh-token reuse
    # detection but its access tokens must stop working immediately.
    session_id = payload.get("session_id")
    session = None
    if session_id:
        session = db.query(RefreshToken).filter(RefreshToken.id == session_id).first()
        if not session or session.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has been revoked",
            )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # An account made by an admin can do nothing until its password is changed.
    if user.must_change_password and request is not None and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please change your password first")

    # Unlock this user's private-project keys for the rest of the request.
    keys.unlock(db, user, session, request.cookies.get(DATA_KEY_COOKIE) if request else None)
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Get current authenticated user from cookie (preferred) or Bearer.

    H10: the browser-facing credential is the HttpOnly access_token
    cookie. Non-browser callers (admin scripts, CI) may still use
    Authorization: Bearer, which keeps server-side tooling working
    after the migration. Both code paths are equivalent credential
    sources - same JWT validation, same session-revocation check.
    """
    token = _extract_access_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return _user_from_token(token, db, request)

# 🔥 NEW: Role-based dependencies
# 🔥 NEW: Permission-based dependencies
# 🔥 Convenience dependencies
async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role"""
    if not current_user.has_role('admin'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

async def get_dashboard_user(current_user: User = Depends(get_current_user)) -> User:
    """Require dashboard access"""
    if not current_user.has_permission('view_dashboard'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard access required. Please contact your administrator."
        )
    return current_user

def require_task_ownership(task, current_user: User) -> None:
    """404 unless the task belongs to the requesting user (task IDOR)."""
    if not task or task.client_id != current_user.email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def require_client_ownership(client_id: str, current_user: User) -> None:
    """Enforce that `client_id` belongs to the requesting user (H5).

    The frontend uses the user's email as `client_id` for upload, download,
    and URL-extraction endpoints. Without this check, an authenticated user
    can target another user's files / tasks by knowing their email -
    classic IDOR. We compare case-insensitively because email addresses
    are case-insensitive per RFC 5321 and the frontend lowercases on send.

    Raises HTTPException(403) on mismatch. Returns None on success so it
    can be called inline at the top of route handlers.
    """
    if not client_id or client_id.lower() != (current_user.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_id does not match authenticated user",
        )


def authenticate_sse_cookie(request: Request, db: Session) -> User:
    """Validate the access_token cookie for SSE endpoints.

    H10 follow-up: the C8 fix passed the access token in `?token=`
    because EventSource cannot send custom headers. With H10's cookie
    migration, EventSource sends the HttpOnly cookie automatically on
    same-origin requests, so we no longer need the query-param hack
    (which was a token-in-URL leak risk: server logs, browser history,
    referer headers).

    Raises HTTPException(401) on any invalid/expired/revoked-session/
    missing-user condition.
    """
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return _user_from_token(token, db, request)


def current_session(request: Request, db: Session) -> RefreshToken | None:
    """The session (refresh-token row) this request's access token belongs to."""
    payload = verify_token(_extract_access_token(request, None) or "") or {}
    session_id = payload.get("session_id")
    return db.get(RefreshToken, session_id) if session_id else None


def require_no_running_task(client_id: str) -> None:
    """409 while the user already has an extraction or analysis running (one at a time)."""
    running = (TaskStatus.EXTRACTING, TaskStatus.PROCESSING)
    if any(t.status in running for t in task_manager.get_client_tasks(client_id, limit=5)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A processing task is already running. Please wait for it to complete or cancel it first.",
        )


def log_activity(db: Session, user_id: int, action: str, ip: str = None, user_agent: str = None, extra: dict = None):
    """Helper to log user activity"""
    from models import ActivityLog

    log = ActivityLog(
        user_id=user_id,
        action=action,
        ip_address=ip,
        user_agent=user_agent,
        extra_data=extra if extra else None
    )
    db.add(log)
    db.commit()


def log_activity_now(user_id: int, action: str, ip: str = None, user_agent: str = None, extra: dict = None):
    """log_activity on its own short session, so a long background job never holds a pooled connection."""
    db = SessionLocal()
    try:
        log_activity(db, user_id, action, ip, user_agent, extra)
    finally:
        db.close()


def find_user_by_email(db: Session, email: str):
    """Emails are case-insensitive: Basic@x.com and basic@x.com are one account."""
    email = (email or "").strip()
    # If legacy accounts differ only by case (migration 0005 then skips its
    # index), prefer the exact spelling, then the oldest - never a random one.
    return (db.query(User).filter(func.lower(User.email) == email.lower())
            .order_by((User.email == email).desc(), User.id).first())

from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
from config import settings
import hmac
import json
import secrets
import hashlib

# Use argon2 instead of bcrypt (works better with Python 3.13)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using argon2"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against hash"""
    return pwd_context.verify(plain_password, hashed_password)

# JWT Tokens
# In utils/security.py

# Update this function signature to accept session_id
def create_access_token(user_id: int, email: str, session_id: int = None) -> str:
    """Create access token (15 min expiry)"""
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "type": "access"
    }
    # Add session_id if provided
    if session_id:
        to_encode["session_id"] = session_id
        
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def create_refresh_token(user_id: int) -> str:
    """Create refresh token.

    A random jti is included so two tokens minted in the same microsecond
    (rotation tests, concurrent requests, race conditions) cannot collide
    on the (sub, exp, type) tuple. This also makes every refresh token
    independently revocable by jti if we ever want a tighter audit trail.
    """
    expire = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def create_pending_2fa_token(user_id: int, keys: str | None = None) -> str:
    """Short-lived token proving the first login factor passed (5 min).
    `keys` carries the (encrypted) private-project key past the 2FA step."""
    expire = datetime.utcnow() + timedelta(minutes=5)
    to_encode = {"sub": str(user_id), "exp": expire, "type": "2fa_pending", "keys": keys}
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def verify_token(token: str) -> dict | None:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.PyJWTError:
        return None

def hash_token(token: str) -> str:
    """Hash token for storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def generate_verification_token() -> str:
    """Generate random verification token"""
    return secrets.token_urlsafe(32)

# 2FA
def generate_totp_secret() -> str:
    """Generate TOTP secret for 2FA"""
    import pyotp
    return pyotp.random_base32()

def verify_totp(secret: str, code: str) -> bool:
    """Verify TOTP code"""
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

def get_totp_uri(secret: str, email: str) -> str:
    """Get TOTP URI for QR code"""
    import pyotp
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name="OmniFox"
    )


# ---- Backup codes (H3 / L6) ------------------------------------------------
#
# Backup codes used to be stored as plaintext JSON in users.backup_codes and
# checked with `if code in backup_codes:`, which is list-membership using
# non-constant-time string equality. The fix:
#   - hash each code with Argon2 at issue time (same hasher as passwords)
#   - on verify, walk the stored hashes with `verify_password`
#     (passlib's argon2 verifier is constant-time internally)
#   - on success, drop the matched hash (one-time-use semantics preserved)
#
# Backwards compatibility: rows written before this change contain plaintext
# codes. We detect those (no `$argon2` prefix) and fall back to a
# constant-time comparison via `hmac.compare_digest`. Operators should
# encourage users to regenerate, but live accounts keep working.
_ARGON2_PREFIX = "$argon2"


def hash_backup_codes(codes: list[str]) -> str:
    """Return a JSON list of Argon2 hashes for the given plaintext codes."""
    return json.dumps([hash_password(code) for code in codes])


def _load_codes(blob: str | None) -> list[str]:
    """Decode the JSON blob in users.backup_codes; tolerate None / garbage."""
    if not blob:
        return []
    try:
        loaded = json.loads(blob)
    except (ValueError, TypeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(entry) for entry in loaded]


def _matches_stored_code(submitted: str, stored: str) -> bool:
    """Constant-time match against either an Argon2 hash or legacy plaintext."""
    if stored.startswith(_ARGON2_PREFIX):
        try:
            return verify_password(submitted, stored)
        except Exception:
            return False
    return hmac.compare_digest(submitted, stored)


def consume_backup_code(blob: str | None, submitted: str) -> tuple[bool, str | None]:
    """Try to consume a backup code from the stored blob.

    Returns `(matched, new_blob)`. On match, `new_blob` is the JSON of the
    remaining codes with the matched entry removed - assign it back to
    `user.backup_codes`. On no match, `new_blob` is None and the caller
    should leave the column untouched.

    All stored entries are walked so the runtime does not depend on the
    matching index (defense in depth on top of the per-entry
    constant-time compare).
    """
    if not submitted:
        return False, None
    stored_codes = _load_codes(blob)
    if not stored_codes:
        return False, None

    matched_index = -1
    for index, stored in enumerate(stored_codes):
        if _matches_stored_code(submitted, stored) and matched_index == -1:
            matched_index = index
            # do NOT break - keep walking to flatten timing across indices

    if matched_index == -1:
        return False, None

    remaining = stored_codes[:matched_index] + stored_codes[matched_index + 1:]
    return True, json.dumps(remaining)
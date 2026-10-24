"""
First-boot bootstrap: ensure baseline roles, permissions, and (optionally)
a first admin user exist.

All functions are idempotent: re-running on an already-seeded database is a
no-op. Designed to be called from the FastAPI lifespan on every startup and
from the CLI on demand.

The first-admin step is gated on environment variables (FIRST_ADMIN_EMAIL,
FIRST_ADMIN_PASSWORD) and only runs when the users table is empty - so it
is safe to leave wired in for the life of the deployment.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Permission, Role, User
from utils.security import hash_password

logger = logging.getLogger(__name__)


# ---- Catalog of seed data --------------------------------------------------

@dataclass(frozen=True)
class _PermissionDef:
    name: str
    description: str


@dataclass(frozen=True)
class _RoleDef:
    name: str
    description: str
    permissions: tuple[str, ...]


PERMISSIONS: tuple[_PermissionDef, ...] = (
    _PermissionDef("view_dashboard", "Access to analytics dashboard"),
    _PermissionDef("manage_users", "Create, edit, and delete users"),
    _PermissionDef("view_reports", "View analysis reports"),
    _PermissionDef("create_reports", "Create new analysis reports"),
    _PermissionDef("manage_roles", "Manage roles and permissions"),
    _PermissionDef("view_activity_logs", "View system activity logs"),
    _PermissionDef("create_private_projects", "Create private projects only they and people they share with can see"),
)

_ALL_PERMISSIONS = tuple(p.name for p in PERMISSIONS)

ROLES: tuple[_RoleDef, ...] = (
    _RoleDef("admin", "Full system access", _ALL_PERMISSIONS),
    _RoleDef(
        "dashboard_user",
        "Access to dashboard and reports",
        ("view_dashboard", "view_reports", "create_reports"),
    ),
    _RoleDef(
        "basic_user",
        "Basic website access",
        ("view_reports", "create_reports"),
    ),
    _RoleDef(
        "project_manager",
        "Private projects and reports",
        ("view_dashboard", "view_reports", "create_reports", "create_private_projects"),
    ),
    _RoleDef("viewer", "Read-only access", ("view_reports",)),
)


# ---- Password validation ---------------------------------------------------

# Common weak roots. Any password whose lowercase form starts with one of
# these is rejected, so `changeme1234`, `password123!`, and `admin-2025` are
# all caught even though the literal default itself does not appear.
_WEAK_PASSWORD_PREFIXES = (
    "change-me",
    "changeme",
    "password",
    "passw0rd",
    "admin",
    "letmein",
    "qwerty",
    "welcome",
    "test1234",
    "mypassworda@1a",  # the old hardcoded default in create_first_admin.py
)

_MIN_PASSWORD_LEN = 12


class WeakPasswordError(ValueError):
    """Raised when a candidate admin password fails strength checks."""


def validate_admin_password(password: str) -> None:
    """Raise WeakPasswordError if password is missing or too weak.

    Rules:
    - Non-empty, at least _MIN_PASSWORD_LEN characters.
    - Does not start with a known weak root (`password`, `changeme`, ...).
    - Contains at least one letter and one non-letter character.
    """
    if not password:
        raise WeakPasswordError("Password is empty.")
    if len(password) < _MIN_PASSWORD_LEN:
        raise WeakPasswordError(
            f"Password too short ({len(password)} chars; need >= {_MIN_PASSWORD_LEN})."
        )
    lowered = password.lower()
    for prefix in _WEAK_PASSWORD_PREFIXES:
        if lowered.startswith(prefix):
            raise WeakPasswordError(
                f"Password starts with a common weak root ({prefix!r}); pick something unrelated."
            )
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[^A-Za-z]", password):
        raise WeakPasswordError(
            "Password must contain at least one letter and one non-letter character."
        )


def validate_admin_email(email: str) -> None:
    """Raise ValueError if email is obviously malformed.

    Not a full RFC 5322 validator - just rejects empty/whitespace/no-@ values
    so we fail loudly instead of writing nonsense to the users table.
    """
    if not email or not email.strip():
        raise ValueError("Email is empty.")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError(f"Email is malformed: {email!r}")


# ---- Idempotent seeders ----------------------------------------------------

def ensure_permissions(db: Session) -> int:
    """Create any missing baseline permissions. Returns count created."""
    existing = {p.name for p in db.query(Permission.name).all()}
    created = 0
    for perm in PERMISSIONS:
        if perm.name in existing:
            continue
        db.add(Permission(name=perm.name, description=perm.description))
        created += 1
    if created:
        db.commit()
        logger.info("bootstrap: created %d new permissions", created)
    return created


def ensure_roles(db: Session) -> int:
    """Create any missing baseline roles and reconcile their permissions.

    Existing roles keep any extra permissions an operator added; this function
    only ever *adds* the baseline permissions, never removes.
    """
    perms_by_name = {p.name: p for p in db.query(Permission).all()}
    created = 0
    for role_def in ROLES:
        role = db.query(Role).filter(Role.name == role_def.name).first()
        if role is None:
            role = Role(name=role_def.name, description=role_def.description)
            db.add(role)
            db.flush()  # need an id before we wire permissions
            created += 1

        current_perms = {p.name for p in role.permissions}
        for perm_name in role_def.permissions:
            if perm_name in current_perms:
                continue
            perm = perms_by_name.get(perm_name)
            if perm is None:
                logger.warning(
                    "bootstrap: role %s wants permission %s which does not exist",
                    role_def.name, perm_name,
                )
                continue
            role.permissions.append(perm)

    db.commit()
    if created:
        logger.info("bootstrap: created %d new roles", created)
    return created


def ensure_first_admin(
    db: Session,
    *,
    email: str | None = None,
    password: str | None = None,
    name: str | None = None,
) -> bool:
    """Create a first admin user from env vars on an empty database.

    Reads FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD / FIRST_ADMIN_NAME from
    the environment when the explicit arguments are not provided.

    Skips silently and returns False when:
    - the users table already has any user (any prior seeding wins),
    - the env vars are unset (no implicit insecure default),
    - the admin role is missing (caller forgot to run ensure_roles first).

    Raises WeakPasswordError / ValueError when env vars are present but
    invalid - we fail loud rather than create an unusable admin.

    Returns True only when a new admin was actually created.
    """
    if db.query(User.id).first() is not None:
        logger.debug("bootstrap: users table is non-empty; skipping first-admin seed")
        return False

    email = email if email is not None else os.getenv("FIRST_ADMIN_EMAIL", "").strip()
    password = password if password is not None else os.getenv("FIRST_ADMIN_PASSWORD", "")
    name = name if name is not None else os.getenv("FIRST_ADMIN_NAME", "Super Admin").strip()

    if not email and not password:
        logger.info(
            "bootstrap: users table empty and FIRST_ADMIN_EMAIL not set; "
            "skipping first-admin seed. Set FIRST_ADMIN_EMAIL and "
            "FIRST_ADMIN_PASSWORD or run `python -m cli create-admin`."
        )
        return False

    validate_admin_email(email)
    validate_admin_password(password)

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if admin_role is None:
        raise RuntimeError(
            "bootstrap: 'admin' role not found; run ensure_roles() first."
        )

    user = User(
        email=email.strip().lower(),
        name=name or "Super Admin",
        hashed_password=hash_password(password),
        auth_provider="email",
        email_verified=True,
        is_active=True,
    )
    user.roles.append(admin_role)
    db.add(user)
    db.commit()

    logger.warning(
        "bootstrap: created the first admin user. "
        "REMOVE FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD from your .env now.",
    )
    return True


# ---- Orchestration ---------------------------------------------------------

LEGACY_FILES_MARKER = ".legacy-files-encrypted"


def encrypt_legacy_files() -> int:
    """Encrypt upload/result files written before encryption at rest.

    Runs once (a marker file records it), so later boots and other workers
    skip the scan. Files that vanish or cannot be read are logged and skipped
    rather than failing startup.
    """
    from config import UPLOAD_FOLDER
    from utils.crypto import encrypt_file_in_place

    marker = os.path.join(UPLOAD_FOLDER, LEGACY_FILES_MARKER)
    if os.path.exists(marker):
        return 0
    count = 0
    for root, _dirs, files in os.walk(UPLOAD_FOLDER):
        for name in files:
            if name.endswith(".tmp") or name == LEGACY_FILES_MARKER:
                continue
            try:
                if encrypt_file_in_place(os.path.join(root, name)):
                    count += 1
            except OSError as exc:
                logger.warning("bootstrap: could not encrypt a legacy file: %s", exc)
    try:
        open(marker, "w").close()
    except OSError as exc:
        logger.warning("bootstrap: could not record the legacy scan (it will run again): %s", exc)
    if count:
        logger.info("bootstrap: encrypted %d legacy file(s)", count)
    return count


def run_bootstrap() -> None:
    """Run all idempotent bootstrap steps using a fresh session.

    Safe to call on every FastAPI startup. Failures are logged and re-raised
    only for the first-admin step (because misconfigured env vars are the
    operator's mistake and should block boot).
    """
    db = SessionLocal()
    try:
        ensure_permissions(db)
        ensure_roles(db)
        try:
            ensure_first_admin(db)
        except (WeakPasswordError, ValueError) as exc:
            logger.error(
                "bootstrap: first-admin seed rejected due to invalid env vars: %s",
                exc,
            )
            raise
    finally:
        db.close()
    encrypt_legacy_files()

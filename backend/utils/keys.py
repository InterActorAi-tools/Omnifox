"""Personal and project keys for private projects.

Each user has an X25519 key pair. The private half is stored locked with a
key derived from their password, and again with a recovery code shown once.
At a password login it is unlocked and kept for the session, locked with a
secret only the browser holds (the data_key cookie).

Each private project has its own Fernet key, stored sealed with the public
key of every member. Every request unlocks the user's project keys, so their
private data reads normally; work on one project writes with its key.

So without a member's password, recovery code or live session, nobody - not
an admin, not someone holding the database and the server key - can read a
private project's objectives or results. While a member's request or
analysis runs, the server does hold the key in memory.
"""
import base64
import json
import os
import secrets
from contextvars import ContextVar

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models import Project, ProjectKey, RefreshToken, User
from utils.cookies import set_data_key_cookie
from utils.crypto import decrypt, encrypt, use_read_keys, use_write_key

LOCKED = "This private project is locked. Sign in with your email and password to open it."

_project_keys: ContextVar[dict] = ContextVar("project_keys", default={})  # project id -> raw key
_unlocked: ContextVar[bool] = ContextVar("unlocked", default=False)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode())


def _lock(secret: str, salt: bytes) -> Fernet:
    return Fernet(_b64(Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1).derive(secret.encode())))


def _clean_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


# ---- Personal keys ---------------------------------------------------------

def new_user_keys(password: str) -> tuple[bytes, str, dict]:
    """A new key pair: (private key, recovery code, User fields to store)."""
    private = X25519PrivateKey.generate()
    raw = private.private_bytes_raw()
    salt = os.urandom(16)
    code = base64.b32encode(secrets.token_bytes(15)).decode()
    code = "-".join(code[i:i + 4] for i in range(0, len(code), 4))
    fields = {
        "public_key": _b64(private.public_key().public_bytes_raw()),
        "key_salt": _b64(salt),
        "private_key_enc": _lock(password, salt).encrypt(raw).decode(),
        "private_key_recovery": _lock(_clean_code(code), salt).encrypt(raw).decode(),
    }
    return raw, code, fields


def open_private_key(user: User, secret: str, recovery: bool = False) -> bytes | None:
    """The private key, unlocked with the password (or recovery code); None if it does not fit."""
    if not user.public_key:
        return None
    token = user.private_key_recovery if recovery else user.private_key_enc
    try:
        return _lock(_clean_code(secret) if recovery else secret, _unb64(user.key_salt)).decrypt(token.encode())
    except InvalidToken:
        return None


def relock_private_key(user: User, raw: bytes, password: str) -> None:
    user.private_key_enc = _lock(password, _unb64(user.key_salt)).encrypt(raw).decode()


def seal(public_key: str, data: bytes) -> str:
    """Encrypt data so only the holder of public_key's private half can read it."""
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes_raw()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(_unb64(public_key)))
    key = HKDF(hashes.SHA256(), 32, salt=None, info=b"omnifox-project-key" + ephemeral_public).derive(shared)
    return f"{_b64(ephemeral_public)}.{Fernet(_b64(key)).encrypt(data).decode()}"


def unseal(raw_private: bytes, sealed: str) -> bytes:
    ephemeral_public, token = sealed.split(".", 1)
    shared = X25519PrivateKey.from_private_bytes(raw_private).exchange(
        X25519PublicKey.from_public_bytes(_unb64(ephemeral_public)))
    key = HKDF(hashes.SHA256(), 32, salt=None, info=b"omnifox-project-key" + _unb64(ephemeral_public)).derive(shared)
    return Fernet(_b64(key)).decrypt(token.encode())


# ---- Login and sessions ----------------------------------------------------

def login_keys(user: User, password: str) -> dict:
    """At a password login: the unlocked private key, or a new key pair for a
    user without one. None private key means a reset password locked it."""
    if user.public_key:
        return {"private": open_private_key(user, password)}
    raw, code, fields = new_user_keys(password)
    return {"private": raw, "recovery_code": code, "fields": fields}


def pack(keys: dict) -> str:
    """Carry login keys across the 2FA step (in the short-lived pending cookie)."""
    data = {**keys, "private": _b64(keys["private"]) if keys.get("private") else None}
    return encrypt(json.dumps(data).encode()).decode()


def unpack(packed: str | None) -> dict:
    if not packed:
        return {}
    data = json.loads(decrypt(packed.encode()))
    return {**data, "private": _unb64(data["private"]) if data.get("private") else None}


def start_session(db: Session, user: User, record: RefreshToken, response, keys: dict) -> str | None:
    """Store new keys, keep the private key for this session, move older private
    projects onto their own keys. Returns the recovery code if keys were just made."""
    code = None
    if keys.get("fields") and not user.public_key:
        for name, value in keys["fields"].items():
            setattr(user, name, value)
        code = keys["recovery_code"]
    if keys.get("private") and user.public_key and record is not None:
        attach(record, response, keys["private"])
        db.commit()
        adopt_private_projects(db, user)
    db.commit()
    return code


def attach(record: RefreshToken, response, raw_private: bytes) -> None:
    secret = Fernet.generate_key()
    record.data_key = Fernet(secret).encrypt(raw_private).decode()
    set_data_key_cookie(response, secret.decode())


def unlock(db: Session, user: User, session: RefreshToken | None, secret: str | None) -> None:
    """Unlock this request's project keys from the session and the browser's secret."""
    keys, private = {}, None
    if session is not None and session.data_key and secret:
        try:
            private = Fernet(secret.encode()).decrypt(session.data_key.encode())
        except (InvalidToken, ValueError):
            private = None
    if private:
        for row in db.query(ProjectKey).filter(ProjectKey.user_id == user.id).all():
            keys[row.project_id] = unseal(private, row.sealed_key)
    _unlocked.set(private is not None)
    _set_keys(keys)
    use_write_key(None)


def is_unlocked() -> bool:
    return _unlocked.get()


# ---- Project keys ----------------------------------------------------------

def _set_keys(keys: dict) -> None:
    _project_keys.set(keys)
    use_read_keys(Fernet(raw) for raw in keys.values())


def project_key(project_id: int) -> bytes | None:
    """The project's raw key if this session unlocked it."""
    return _project_keys.get().get(project_id)


def _remember(project_id: int, raw: bytes) -> None:
    _set_keys({**_project_keys.get(), project_id: raw})


def seal_for(project: Project, raw_key: bytes, members) -> None:
    """Give these members (owner included) the project's key."""
    project.keys = [ProjectKey(user_id=u.id, sealed_key=seal(u.public_key, raw_key)) for u in members]


def create_project_key(db: Session, project: Project, owner: User) -> None:
    """Encrypt a new private project's data with a key of its own."""
    raw = Fernet.generate_key()
    use_write_key(Fernet(raw))
    db.add(project)
    db.flush()
    seal_for(project, raw, [owner])
    _remember(project.id, raw)


def adopt_private_projects(db: Session, user: User) -> None:
    """Private projects made before project keys existed get one now."""
    projects = (db.query(Project)
                .filter(Project.owner_id == user.id, Project.is_private == True, ~Project.keys.any())  # noqa: E712
                .all())
    for project in projects:
        objectives = project.objectives or []  # still under the server key
        raw = Fernet.generate_key()
        use_write_key(Fernet(raw))
        project.objectives = objectives
        flag_modified(project, "objectives")  # same value, rewritten under the new key
        seal_for(project, raw, [user] + [u for u in project.shared_with if u.public_key])
        db.flush()
        _remember(project.id, raw)
    use_write_key(None)
    db.commit()


def drop_user_keys(db: Session, user: User) -> None:
    """Remove the user's project keys; delete their private projects that no one can open any more."""
    from services.privacy import delete_project
    mine = db.query(ProjectKey.project_id).filter(ProjectKey.user_id == user.id)
    orphans = db.query(Project).filter(Project.id.in_(mine), ~Project.keys.any(ProjectKey.user_id != user.id)).all()
    db.query(ProjectKey).filter(ProjectKey.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    for project in orphans:
        delete_project(db, project)
    _set_keys({})


def use_project(db: Session, name: str) -> None:
    """Write with the named project's key if it is private (403 if locked here)."""
    project = db.query(Project).filter(Project.name == name).first()
    if project is None or not project.is_private:
        use_write_key(None)
        return
    raw = project_key(project.id)
    if raw is None:
        raise HTTPException(status_code=403, detail=LOCKED)
    use_write_key(Fernet(raw))

"""Tests for SECURITY_ASSESSMENT.md H1: broken logout + refresh-token rotation.

Exercises the auth router's /refresh and /logout endpoints plus the
get_current_user dependency that gates them. All tests use an in-memory
SQLite database via dependency override - no Postgres or pandas needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---- Fixtures --------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch):
    """Fresh in-memory SQLite engine, with database.SessionLocal patched."""
    import database
    import models  # noqa: F401 - register metadata

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    yield TestSession

    database.Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seeded_user(isolated_db):
    """Create a user with a hashed password and the admin role."""
    from bootstrap import ensure_permissions, ensure_roles
    from models import User
    from utils.security import hash_password

    db = isolated_db()
    ensure_permissions(db)
    ensure_roles(db)
    user = User(
        email="alice@example.com",
        name="Alice",
        hashed_password=hash_password("Goodpass-12345"),
        auth_provider="email",
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()

    return user_id


@pytest.fixture
def seeded_session(isolated_db, seeded_user):
    """Create one active RefreshToken row for the seeded user; return
    (refresh_token_string, session_row_id)."""
    from models import RefreshToken
    from utils.security import create_refresh_token, hash_token
    from config import settings

    db = isolated_db()
    refresh_str = create_refresh_token(seeded_user)
    token_hash = hash_token(refresh_str)
    row = RefreshToken(
        user_id=seeded_user,
        token_hash=token_hash,
        device_name="pytest",
        ip_address="127.0.0.1",
        user_agent="pytest",
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    session_id = row.id
    db.close()

    return refresh_str, session_id


def _fake_request():
    """Minimal Request-like object: just request.client.host + headers + cookies."""
    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers.get = lambda k, default=None: {"user-agent": "pytest"}.get(k, default)
    # H10: refresh_tokens / logout read cookies before falling back to body
    # / Authorization header. Empty dict forces the body path.
    req.cookies = {}
    return req


def _fake_response():
    """Real Starlette Response instance used as a placeholder.

    The H10 cookie helpers call .set_cookie() / .delete_cookie() on it -
    direct-call tests can throw the resulting Response away; the cookie
    behaviour itself is covered by test_auth_h10.py.
    """
    from fastapi import Response
    return Response()


# ---- /auth/refresh: rotation ----------------------------------------------

class TestRefreshRotation:
    @pytest.mark.asyncio
    async def test_refresh_returns_new_token(self, isolated_db, seeded_session):
        # H10: tokens no longer live in the response body - they go out
        # as HttpOnly cookies on the response object. The assertion
        # shape here is therefore "rotation occurred at the DB level"
        # rather than "body field changed". test_auth_h10.py covers
        # the cookie-on-response behaviour end-to-end.
        from models import RefreshToken
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest

        old_refresh, old_session_id = seeded_session
        db = isolated_db()
        try:
            response = await refresh_tokens(
                request=_fake_request(),
                response=_fake_response(),
                db=db,
                token_data=RefreshTokenRequest(refresh_token=old_refresh),
            )
            assert response.user.email == "alice@example.com"
            # H10 strips tokens from the body.
            assert response.access_token == ""
            assert response.refresh_token == ""
            # Rotation: old row revoked, exactly one active row remains.
            old_row = db.query(RefreshToken).filter(
                RefreshToken.id == old_session_id
            ).first()
            assert old_row.is_revoked is True
            active = db.query(RefreshToken).filter(
                RefreshToken.user_id == old_row.user_id,
                RefreshToken.is_revoked.is_(False),
            ).count()
            assert active == 1
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_refresh_soft_revokes_old_row(self, isolated_db, seeded_session):
        from models import RefreshToken
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest

        old_refresh, old_session_id = seeded_session
        db = isolated_db()
        try:
            await refresh_tokens(
                request=_fake_request(),
                response=_fake_response(),
                db=db,
                token_data=RefreshTokenRequest(refresh_token=old_refresh),
            )
            old_row = db.query(RefreshToken).filter(RefreshToken.id == old_session_id).first()
            assert old_row is not None
            assert old_row.is_revoked is True
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_refresh_creates_new_session_row(self, isolated_db, seeded_user, seeded_session):
        from models import RefreshToken
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest

        old_refresh, _ = seeded_session
        db = isolated_db()
        try:
            await refresh_tokens(
                request=_fake_request(),
                response=_fake_response(),
                db=db,
                token_data=RefreshTokenRequest(refresh_token=old_refresh),
            )
            rows = db.query(RefreshToken).filter(
                RefreshToken.user_id == seeded_user
            ).all()
            assert len(rows) == 2  # old (revoked) + new (active)
            active = [r for r in rows if not r.is_revoked]
            assert len(active) == 1
        finally:
            db.close()


# ---- /auth/refresh: reuse detection ---------------------------------------

class TestRefreshReuseDetection:
    @pytest.mark.asyncio
    async def test_replay_of_revoked_token_wipes_all_sessions(
        self, isolated_db, seeded_user, seeded_session
    ):
        from fastapi import HTTPException
        from models import RefreshToken
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest
        from utils.security import create_refresh_token, hash_token

        # First rotation: legitimate use, produces a new active session.
        old_refresh, _ = seeded_session
        db = isolated_db()
        try:
            await refresh_tokens(
                request=_fake_request(),
                response=_fake_response(),
                db=db,
                token_data=RefreshTokenRequest(refresh_token=old_refresh),
            )

            # Also add a totally unrelated active session for the same user
            # (e.g., "user logged in on a second device"). Reuse detection
            # must nuke this too - we cannot tell which device is compromised.
            other = RefreshToken(
                user_id=seeded_user,
                token_hash=hash_token(create_refresh_token(seeded_user)),
                expires_at=datetime.utcnow() + timedelta(days=30),
            )
            db.add(other)
            db.commit()

            # Now replay the original (already-revoked) token.
            with pytest.raises(HTTPException) as exc:
                await refresh_tokens(
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                    token_data=RefreshTokenRequest(refresh_token=old_refresh),
                )
            assert exc.value.status_code == 401
            assert "compromised" in exc.value.detail.lower()

            # Every refresh token for this user is gone.
            remaining = db.query(RefreshToken).filter(
                RefreshToken.user_id == seeded_user
            ).count()
            assert remaining == 0
        finally:
            db.close()


# ---- /auth/refresh: rejections --------------------------------------------

class TestRefreshRejections:
    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, isolated_db, seeded_user):
        from fastapi import HTTPException
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest

        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                await refresh_tokens(
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                    token_data=RefreshTokenRequest(refresh_token="not-a-jwt"),
                )
            assert exc.value.status_code == 401
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_unknown_but_valid_jwt_rejected(self, isolated_db, seeded_user):
        from fastapi import HTTPException
        from routers.auth import refresh_tokens
        from schemas.auth import RefreshTokenRequest
        from utils.security import create_refresh_token

        # Valid signature but no DB row (never persisted).
        orphan = create_refresh_token(seeded_user)
        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                await refresh_tokens(
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                    token_data=RefreshTokenRequest(refresh_token=orphan),
                )
            assert exc.value.status_code == 401
        finally:
            db.close()


# ---- /auth/logout ----------------------------------------------------------

class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_deletes_session_row(self, isolated_db, seeded_user, seeded_session):
        # H10: logout reads the access token from the cookie (preferred)
        # or the Authorization header. We stub the cookie path here.
        from models import RefreshToken, User
        from routers.auth import logout
        from utils.cookies import ACCESS_TOKEN_COOKIE
        from utils.security import create_access_token

        _, session_id = seeded_session
        access_token = create_access_token(seeded_user, "alice@example.com", session_id=session_id)

        req = _fake_request()
        req.cookies = {ACCESS_TOKEN_COOKIE: access_token}

        db = isolated_db()
        try:
            user = db.query(User).filter(User.id == seeded_user).first()
            await logout(
                request=req,
                response=_fake_response(),
                current_user=user,
                db=db,
            )
            row = db.query(RefreshToken).filter(RefreshToken.id == session_id).first()
            assert row is None
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_logout_does_not_touch_other_users_sessions(
        self, isolated_db, seeded_user, seeded_session
    ):
        from models import RefreshToken, User
        from routers.auth import logout
        from utils.cookies import ACCESS_TOKEN_COOKIE
        from utils.security import (
            create_access_token,
            create_refresh_token,
            hash_password,
            hash_token,
        )

        _, session_id = seeded_session
        # Create a second user with their own session row.
        db = isolated_db()
        bob = User(
            email="bob@example.com",
            hashed_password=hash_password("Goodpass-12345"),
            auth_provider="email",
            email_verified=True,
            is_active=True,
        )
        db.add(bob)
        db.commit()
        db.refresh(bob)
        bob_session = RefreshToken(
            user_id=bob.id,
            token_hash=hash_token(create_refresh_token(bob.id)),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(bob_session)
        db.commit()
        db.refresh(bob_session)

        # Alice logs out.
        access_token = create_access_token(seeded_user, "alice@example.com", session_id=session_id)
        req = _fake_request()
        req.cookies = {ACCESS_TOKEN_COOKIE: access_token}
        alice = db.query(User).filter(User.id == seeded_user).first()
        await logout(
            request=req,
            response=_fake_response(),
            current_user=alice,
            db=db,
        )

        # Bob's session row must still be there.
        bob_row = db.query(RefreshToken).filter(RefreshToken.id == bob_session.id).first()
        assert bob_row is not None
        db.close()


# ---- get_current_user revoked-session gate --------------------------------

class TestGetCurrentUserRevokedSession:
    @pytest.mark.asyncio
    async def test_revoked_session_rejects_access_token(
        self, isolated_db, seeded_user, seeded_session
    ):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        from models import RefreshToken
        from utils.dependencies import get_current_user
        from utils.security import create_access_token

        _, session_id = seeded_session
        access_token = create_access_token(seeded_user, "alice@example.com", session_id=session_id)

        # Soft-revoke the session (simulating what /refresh does on rotation).
        db = isolated_db()
        try:
            row = db.query(RefreshToken).filter(RefreshToken.id == session_id).first()
            row.is_revoked = True
            db.commit()

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_fake_request(), credentials=creds, db=db)
            assert exc.value.status_code == 401
            assert "revoked" in exc.value.detail.lower()
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_deleted_session_rejects_access_token(
        self, isolated_db, seeded_user, seeded_session
    ):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        from models import RefreshToken
        from utils.dependencies import get_current_user
        from utils.security import create_access_token

        _, session_id = seeded_session
        access_token = create_access_token(seeded_user, "alice@example.com", session_id=session_id)

        db = isolated_db()
        try:
            db.query(RefreshToken).filter(RefreshToken.id == session_id).delete()
            db.commit()

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_fake_request(), credentials=creds, db=db)
            assert exc.value.status_code == 401
        finally:
            db.close()

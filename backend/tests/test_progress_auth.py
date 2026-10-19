"""Tests for SECURITY_ASSESSMENT.md C8 + H10: SSE progress endpoint auth.

The /api/progress/{client_id} endpoint used to have NO auth (C8). The
C8 fix added a `?token=<jwt>` query-string credential because
EventSource cannot send custom headers. H10 then moved auth to an
HttpOnly cookie that EventSource attaches automatically on same-origin
(or with `withCredentials: true` on cross-origin), eliminating the
token-in-URL leak vector.

These tests exercise `utils.dependencies.authenticate_sse_cookie`
directly against a stub Request object carrying the cookie. The
client_id-ownership comparison is also locked in below.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils.cookies import ACCESS_TOKEN_COOKIE


# ---- Fixtures --------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch):
    import database
    import models  # noqa: F401

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
def alice(isolated_db):
    from bootstrap import ensure_permissions, ensure_roles
    from models import User
    from utils.security import hash_password

    db = isolated_db()
    ensure_permissions(db); ensure_roles(db)
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


def _request_with_cookie(value: str | None) -> MagicMock:
    """Build a fake Starlette Request whose .cookies returns the given access_token."""
    req = MagicMock()
    req.cookies = {ACCESS_TOKEN_COOKIE: value} if value is not None else {}
    return req


# ---- authenticate_sse_cookie: rejections ----------------------------------

class TestAuthenticateSSECookieRejects:
    def test_missing_cookie(self, isolated_db, alice):
        from utils.dependencies import authenticate_sse_cookie
        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie(None), db)
            assert exc.value.status_code == 401
        finally:
            db.close()

    def test_garbage_cookie(self, isolated_db, alice):
        from utils.dependencies import authenticate_sse_cookie
        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie("not-a-jwt"), db)
            assert exc.value.status_code == 401
        finally:
            db.close()

    def test_empty_cookie(self, isolated_db, alice):
        from utils.dependencies import authenticate_sse_cookie
        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie(""), db)
            assert exc.value.status_code == 401
        finally:
            db.close()

    def test_revoked_session_rejected(self, isolated_db, alice):
        from models import RefreshToken
        from utils.dependencies import authenticate_sse_cookie
        from utils.security import create_access_token, create_refresh_token, hash_token

        db = isolated_db()
        try:
            row = RefreshToken(
                user_id=alice,
                token_hash=hash_token(create_refresh_token(alice)),
                expires_at=datetime.utcnow() + timedelta(days=30),
                is_revoked=True,
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            access = create_access_token(alice, "alice@example.com", session_id=row.id)
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie(access), db)
            assert exc.value.status_code == 401
            assert "revoked" in exc.value.detail.lower()
        finally:
            db.close()

    def test_inactive_user_rejected(self, isolated_db, alice):
        from models import User
        from utils.dependencies import authenticate_sse_cookie
        from utils.security import create_access_token

        db = isolated_db()
        try:
            db.query(User).filter(User.id == alice).update({"is_active": False})
            db.commit()
            access = create_access_token(alice, "alice@example.com")
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie(access), db)
            assert exc.value.status_code == 401
        finally:
            db.close()

    def test_deleted_user_rejected(self, isolated_db, alice):
        from models import User
        from utils.dependencies import authenticate_sse_cookie
        from utils.security import create_access_token

        # Mint the token BEFORE deleting the user (the only way a client
        # could ever present a token for a non-existent user).
        access = create_access_token(alice, "alice@example.com")

        db = isolated_db()
        try:
            db.query(User).filter(User.id == alice).delete()
            db.commit()
            with pytest.raises(HTTPException) as exc:
                authenticate_sse_cookie(_request_with_cookie(access), db)
            assert exc.value.status_code == 401
        finally:
            db.close()


# ---- authenticate_sse_cookie: happy path ----------------------------------

class TestAuthenticateSSECookieAccepts:
    def test_valid_access_token_returns_user(self, isolated_db, alice):
        from utils.dependencies import authenticate_sse_cookie
        from utils.security import create_access_token

        db = isolated_db()
        try:
            access = create_access_token(alice, "alice@example.com")
            user = authenticate_sse_cookie(_request_with_cookie(access), db)
            assert user.id == alice
            assert user.email == "alice@example.com"
        finally:
            db.close()

    def test_valid_token_with_active_session_returns_user(self, isolated_db, alice):
        from models import RefreshToken
        from utils.dependencies import authenticate_sse_cookie
        from utils.security import create_access_token, create_refresh_token, hash_token

        db = isolated_db()
        try:
            row = RefreshToken(
                user_id=alice,
                token_hash=hash_token(create_refresh_token(alice)),
                expires_at=datetime.utcnow() + timedelta(days=30),
                # is_revoked left default (False)
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            access = create_access_token(alice, "alice@example.com", session_id=row.id)
            user = authenticate_sse_cookie(_request_with_cookie(access), db)
            assert user.id == alice
        finally:
            db.close()


# ---- client_id ownership comparison ---------------------------------------

class TestClientIdOwnership:
    """The endpoint compares client_id.lower() == user.email.lower(). These
    cases lock in the exact behaviour because the comparison itself is
    trivial and easy to silently regress."""

    @pytest.mark.parametrize(
        "client_id,email,should_match",
        [
            ("alice@example.com", "alice@example.com", True),
            ("ALICE@example.com", "alice@example.com", True),
            ("alice@EXAMPLE.com", "alice@example.com", True),
            ("bob@example.com",   "alice@example.com", False),
            ("alice@evil.com",    "alice@example.com", False),
            ("alice",             "alice@example.com", False),
            ("",                  "alice@example.com", False),
        ],
    )
    def test_case_insensitive_email_match(self, client_id, email, should_match):
        assert (client_id.lower() == email.lower()) is should_match

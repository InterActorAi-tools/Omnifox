"""Tests for SECURITY_ASSESSMENT.md H3: 2FA verification lockout + backup-code hashing.

Covers:
  - /verify-2fa now honours the same 5-strike, 1-hour lockout that
    /login uses
  - backup codes are Argon2-hashed at rest and matched in constant time
  - legacy plaintext codes still work (one-shot migration window)
  - identical 401s for unknown email, 2FA-disabled user, wrong TOTP,
    wrong backup code (no enumeration / no leak of which check failed)

Uses the same in-memory-SQLite fixture pattern as test_auth_h1.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pyotp
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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
def seeded_2fa_user(isolated_db):
    """Create a user with TOTP enabled and one Argon2-hashed backup code."""
    from bootstrap import ensure_permissions, ensure_roles
    from models import User
    from utils.security import (
        hash_backup_codes,
        hash_password,
        generate_totp_secret,
    )

    db = isolated_db()
    ensure_permissions(db)
    ensure_roles(db)

    secret = generate_totp_secret()
    plaintext_backup = "backupcode1"
    user = User(
        email="alice@example.com",
        name="Alice",
        hashed_password=hash_password("Goodpass-12345"),
        auth_provider="email",
        email_verified=True,
        is_active=True,
        two_factor_enabled=True,
        two_factor_secret=secret,
        backup_codes=hash_backup_codes([plaintext_backup, "backupcode2"]),
        failed_login_attempts=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()

    return {
        "user_id": user_id,
        "email": "alice@example.com",
        "totp_secret": secret,
        "backup_plaintext": plaintext_backup,
    }


def _fake_request(pending_user_id=None):
    """Fake request; `pending_user_id` adds the pending-2FA cookie that
    /auth/login sets after a correct password."""
    from utils.cookies import PENDING_2FA_COOKIE
    from utils.security import create_pending_2fa_token

    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers.get = lambda k, default=None: {"user-agent": "pytest"}.get(k, default)
    req.cookies = {}
    if pending_user_id is not None:
        req.cookies[PENDING_2FA_COOKIE] = create_pending_2fa_token(pending_user_id)
    return req


def _fake_response():
    """Real Response instance; H10 cookie helpers call .set_cookie on it."""
    from fastapi import Response
    return Response()


def _current_totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# ---- consume_backup_code unit tests ---------------------------------------

class TestConsumeBackupCode:
    def test_matches_argon2_hashed_code(self):
        from utils.security import consume_backup_code, hash_backup_codes

        blob = hash_backup_codes(["alpha", "bravo"])
        matched, new_blob = consume_backup_code(blob, "alpha")
        assert matched is True
        assert new_blob is not None
        remaining = json.loads(new_blob)
        assert len(remaining) == 1

    def test_matched_code_cannot_be_replayed(self):
        from utils.security import consume_backup_code, hash_backup_codes

        blob = hash_backup_codes(["alpha"])
        matched, new_blob = consume_backup_code(blob, "alpha")
        assert matched is True
        # Second use against the new blob must fail (one-time-use).
        matched_again, _ = consume_backup_code(new_blob, "alpha")
        assert matched_again is False

    def test_wrong_code_does_not_mutate(self):
        from utils.security import consume_backup_code, hash_backup_codes

        blob = hash_backup_codes(["alpha", "bravo"])
        matched, new_blob = consume_backup_code(blob, "zzz")
        assert matched is False
        assert new_blob is None

    def test_empty_or_missing_blob(self):
        from utils.security import consume_backup_code

        for empty in (None, "", "[]", "not-json", '{"x": 1}'):
            matched, new_blob = consume_backup_code(empty, "alpha")
            assert matched is False
            assert new_blob is None

    def test_empty_submitted_code_fails(self):
        from utils.security import consume_backup_code, hash_backup_codes

        blob = hash_backup_codes(["alpha"])
        matched, _ = consume_backup_code(blob, "")
        assert matched is False

    def test_accepts_legacy_plaintext_entries(self):
        # Pre-migration row: plaintext JSON list. Must still match so
        # live accounts keep working through the rollout window.
        from utils.security import consume_backup_code

        legacy = json.dumps(["legacycode-1", "legacycode-2"])
        matched, new_blob = consume_backup_code(legacy, "legacycode-1")
        assert matched is True
        remaining = json.loads(new_blob)
        assert remaining == ["legacycode-2"]


# ---- /verify-2fa: happy paths ---------------------------------------------

class TestVerify2FAHappy:
    @pytest.mark.asyncio
    async def test_totp_success(self, isolated_db, seeded_2fa_user):
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            response = await verify_2fa(
                data=Verify2FARequest(
                    email=seeded_2fa_user["email"],
                    code=_current_totp(seeded_2fa_user["totp_secret"]),
                ),
                request=_fake_request(seeded_2fa_user["user_id"]),
                response=_fake_response(),
                db=db,
            )
        finally:
            db.close()

        # H10: tokens flow via cookies, not the body. The TokenResponse
        # carries the user payload; success here means the 2FA path
        # returned a populated user (no requires_2fa flag set), which
        # only happens after the verify step completes successfully.
        assert response.user.email == seeded_2fa_user["email"]
        assert response.requires_2fa is False

    @pytest.mark.asyncio
    async def test_backup_code_success(self, isolated_db, seeded_2fa_user):
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            response = await verify_2fa(
                data=Verify2FARequest(
                    email=seeded_2fa_user["email"],
                    code=seeded_2fa_user["backup_plaintext"],
                ),
                request=_fake_request(seeded_2fa_user["user_id"]),
                response=_fake_response(),
                db=db,
            )
        finally:
            db.close()

        # H10: presence of a populated user (no requires_2fa) signals success.
        assert response.user.email == seeded_2fa_user["email"]
        assert response.requires_2fa is False

    @pytest.mark.asyncio
    async def test_backup_code_is_one_time_use(self, isolated_db, seeded_2fa_user):
        from fastapi import HTTPException
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            # First use succeeds.
            await verify_2fa(
                data=Verify2FARequest(
                    email=seeded_2fa_user["email"],
                    code=seeded_2fa_user["backup_plaintext"],
                ),
                request=_fake_request(seeded_2fa_user["user_id"]),
                response=_fake_response(),
                db=db,
            )
            # Second use must fail.
            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email=seeded_2fa_user["email"],
                        code=seeded_2fa_user["backup_plaintext"],
                    ),
                    request=_fake_request(seeded_2fa_user["user_id"]),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 401
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_success_resets_failed_attempts(self, isolated_db, seeded_2fa_user):
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            db.query(User).filter(User.id == seeded_2fa_user["user_id"]).update(
                {"failed_login_attempts": 3}
            )
            db.commit()

            await verify_2fa(
                data=Verify2FARequest(
                    email=seeded_2fa_user["email"],
                    code=_current_totp(seeded_2fa_user["totp_secret"]),
                ),
                request=_fake_request(seeded_2fa_user["user_id"]),
                response=_fake_response(),
                db=db,
            )

            user = db.query(User).filter(User.id == seeded_2fa_user["user_id"]).first()
            assert user.failed_login_attempts == 0
            assert user.locked_until is None
        finally:
            db.close()


# ---- /verify-2fa: lockout --------------------------------------------------

class TestVerify2FALockout:
    @pytest.mark.asyncio
    async def test_wrong_code_increments_failed_attempts(
        self, isolated_db, seeded_2fa_user
    ):
        from fastapi import HTTPException
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            with pytest.raises(HTTPException):
                await verify_2fa(
                    data=Verify2FARequest(
                        email=seeded_2fa_user["email"],
                        code="000000",
                    ),
                    request=_fake_request(seeded_2fa_user["user_id"]),
                    response=_fake_response(),
                    db=db,
                )

            user = db.query(User).filter(User.id == seeded_2fa_user["user_id"]).first()
            assert user.failed_login_attempts == 1
            assert user.locked_until is None  # not yet
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_locks_after_five_wrong_codes(self, isolated_db, seeded_2fa_user):
        from fastapi import HTTPException
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            for _ in range(5):
                with pytest.raises(HTTPException):
                    await verify_2fa(
                        data=Verify2FARequest(
                            email=seeded_2fa_user["email"],
                            code="000000",
                        ),
                        request=_fake_request(seeded_2fa_user["user_id"]),
                        response=_fake_response(),
                        db=db,
                    )

            user = db.query(User).filter(User.id == seeded_2fa_user["user_id"]).first()
            assert user.failed_login_attempts == 5
            assert user.locked_until is not None
            # Lock should be in the future and within ~1h+epsilon.
            delta = user.locked_until - datetime.utcnow()
            assert timedelta(minutes=55) <= delta <= timedelta(hours=1, minutes=5)
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_locked_account_rejects_even_correct_totp(
        self, isolated_db, seeded_2fa_user
    ):
        # Once locked, /verify-2fa must refuse even if the user now
        # submits a fresh, valid TOTP. This is the actual brute-force
        # defense: lockout supersedes credential validity.
        from fastapi import HTTPException
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            db.query(User).filter(User.id == seeded_2fa_user["user_id"]).update(
                {"locked_until": datetime.utcnow() + timedelta(minutes=30)}
            )
            db.commit()

            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email=seeded_2fa_user["email"],
                        code=_current_totp(seeded_2fa_user["totp_secret"]),
                    ),
                    request=_fake_request(seeded_2fa_user["user_id"]),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 403
            # Error must NOT include the precise unlock timestamp (L7).
            assert "until" not in exc.value.detail.lower() or "later" in exc.value.detail.lower()
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_expired_lock_is_ignored(self, isolated_db, seeded_2fa_user):
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            # Past lockout - should be treated as not locked.
            db.query(User).filter(User.id == seeded_2fa_user["user_id"]).update(
                {"locked_until": datetime.utcnow() - timedelta(minutes=1)}
            )
            db.commit()

            response = await verify_2fa(
                data=Verify2FARequest(
                    email=seeded_2fa_user["email"],
                    code=_current_totp(seeded_2fa_user["totp_secret"]),
                ),
                request=_fake_request(seeded_2fa_user["user_id"]),
                response=_fake_response(),
                db=db,
            )
            # H10: success is signalled by a populated user payload.
            assert response.user.email == seeded_2fa_user["email"]
            assert response.requires_2fa is False
        finally:
            db.close()


# ---- /verify-2fa: no enumeration ------------------------------------------

class TestVerify2FANoEnumeration:
    @pytest.mark.asyncio
    async def test_unknown_email_returns_401_not_404(self, isolated_db):
        from fastapi import HTTPException
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email="ghost@example.com",
                        code="000000",
                    ),
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 401
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_2fa_not_enabled_returns_same_401(self, isolated_db):
        # A user without 2FA hitting /verify-2fa must look identical to
        # a wrong-code 401. Previously this returned a distinct 400
        # ("2FA is not enabled for this user.") which confirmed account
        # existence and 2FA state to anonymous callers.
        from bootstrap import ensure_permissions, ensure_roles
        from fastapi import HTTPException
        from models import User
        from routers.auth import verify_2fa, Verify2FARequest
        from utils.security import hash_password

        db = isolated_db()
        ensure_permissions(db)
        ensure_roles(db)
        user = User(
            email="bob@example.com",
            name="Bob",
            hashed_password=hash_password("Goodpass-12345"),
            auth_provider="email",
            email_verified=True,
            is_active=True,
            two_factor_enabled=False,
        )
        db.add(user)
        db.commit()

        try:
            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email="bob@example.com",
                        code="000000",
                    ),
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 401
        finally:
            db.close()


# ---- /verify-2fa: bound to the password step -------------------------------

class TestVerify2FARequiresFirstFactor:
    @pytest.mark.asyncio
    async def test_valid_totp_without_pending_cookie_is_rejected(self, isolated_db, seeded_2fa_user):
        # Knowing the email and a TOTP/backup code alone must not log in;
        # the pending-2FA cookie from a correct password is required.
        from fastapi import HTTPException
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email=seeded_2fa_user["email"],
                        code=_current_totp(seeded_2fa_user["totp_secret"]),
                    ),
                    request=_fake_request(),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 401
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_pending_cookie_for_other_user_is_rejected(self, isolated_db, seeded_2fa_user):
        from fastapi import HTTPException
        from routers.auth import verify_2fa, Verify2FARequest

        db = isolated_db()
        try:
            with pytest.raises(HTTPException) as exc:
                await verify_2fa(
                    data=Verify2FARequest(
                        email=seeded_2fa_user["email"],
                        code=_current_totp(seeded_2fa_user["totp_secret"]),
                    ),
                    request=_fake_request(seeded_2fa_user["user_id"] + 999),
                    response=_fake_response(),
                    db=db,
                )
            assert exc.value.status_code == 401
        finally:
            db.close()

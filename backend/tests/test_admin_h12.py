"""Tests for SECURITY_ASSESSMENT.md H12: invite link must come from config, not Origin.

Before this fix, generate_invitation_link did:

    base_url = request.headers.get("origin") or "https://staging-omnifox..."

A compromised admin session (or admin tricked into an attacker-prepared
admin-tool URL with a forged Origin) sent invite emails whose link
pointed at an attacker-controlled domain - a phishing primitive against
new invitees who had no prior Omnifox URL to compare against.

This test set asserts:
  - the link uses settings.frontend_url verbatim
  - the Origin header is ignored even when present
  - the link survives an attacker setting Origin to a lookalike domain
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
def admin_user(isolated_db):
    from bootstrap import ensure_permissions, ensure_roles
    from models import Role, User
    from utils.security import hash_password

    db = isolated_db()
    ensure_permissions(db)
    ensure_roles(db)

    user = User(
        email="admin@example.com",
        name="Admin",
        hashed_password=hash_password("Goodpass-12345"),
        auth_provider="email",
        email_verified=True,
        is_active=True,
    )
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if admin_role is not None:
        user.roles.append(admin_role)
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()
    return user_id


def _request_with_origin(origin: str | None):
    """Build a Request stub whose Origin header carries an attacker value."""
    headers = {"user-agent": "pytest"}
    if origin is not None:
        headers["origin"] = origin
    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers.get = lambda k, default=None: headers.get(k.lower(), default)
    return req


# ---- /admin/invitations/generate: link source -----------------------------

class TestInviteLinkSource:
    @pytest.mark.asyncio
    async def test_link_uses_configured_frontend_url(
        self, isolated_db, admin_user, monkeypatch
    ):
        from config import settings
        from models import User
        from routers.admin import generate_invitation_link, GenerateInviteRequest

        monkeypatch.setattr(settings, "frontend_url", "https://omnifox.example.com")

        db = isolated_db()
        try:
            current_admin = db.query(User).filter(User.id == admin_user).first()
            result = generate_invitation_link(
                data=GenerateInviteRequest(
                    email="invitee@in2-comms.com",
                    name="Invitee",
                    role="basic_user",
                ),
                request=_request_with_origin(None),
                current_user=current_admin,
                db=db,
            )
        finally:
            db.close()

        assert result["link"].startswith("https://omnifox.example.com/register?token=")
        assert result["token"] in result["link"]

    @pytest.mark.asyncio
    async def test_forged_origin_is_ignored(
        self, isolated_db, admin_user, monkeypatch
    ):
        # An attacker who controls an admin session sends the request
        # with Origin set to a phishing domain. The link in the email
        # must STILL go to settings.frontend_url, not the forged value.
        from config import settings
        from models import User
        from routers.admin import generate_invitation_link, GenerateInviteRequest

        monkeypatch.setattr(settings, "frontend_url", "https://omnifox.example.com")

        db = isolated_db()
        try:
            current_admin = db.query(User).filter(User.id == admin_user).first()
            result = generate_invitation_link(
                data=GenerateInviteRequest(
                    email="invitee2@in2-comms.com",
                    name="Invitee",
                    role="basic_user",
                ),
                request=_request_with_origin("https://attacker.evil"),
                current_user=current_admin,
                db=db,
            )
        finally:
            db.close()

        assert result["link"].startswith("https://omnifox.example.com/register?token=")
        assert "attacker.evil" not in result["link"]

    @pytest.mark.asyncio
    async def test_lookalike_origin_is_ignored(
        self, isolated_db, admin_user, monkeypatch
    ):
        # Origin set to a typosquat that resembles the real domain.
        # Same outcome: ignored.
        from config import settings
        from models import User
        from routers.admin import generate_invitation_link, GenerateInviteRequest

        monkeypatch.setattr(settings, "frontend_url", "https://omnifox.example.com")

        db = isolated_db()
        try:
            current_admin = db.query(User).filter(User.id == admin_user).first()
            result = generate_invitation_link(
                data=GenerateInviteRequest(
                    email="invitee3@in2-comms.com",
                    name="Invitee",
                    role="basic_user",
                ),
                request=_request_with_origin("https://0mnicat.example.com"),
                current_user=current_admin,
                db=db,
            )
        finally:
            db.close()

        assert result["link"].startswith("https://omnifox.example.com/register?token=")
        assert "0mnicat" not in result["link"]


# ---- Password reset email (M11) -------------------------------------------

class TestPasswordResetURL:
    @pytest.mark.asyncio
    async def test_reset_url_uses_configured_frontend_url(self, monkeypatch):
        # send_password_reset_email previously hardcoded the staging
        # hostname into every reset URL. After the M11 fix, the URL
        # must derive from settings.frontend_url.
        from config import settings
        from utils import email_service

        monkeypatch.setattr(settings, "frontend_url", "https://omnifox.example.com")

        captured = {}

        class _FakeResp:
            def __getitem__(self, key):
                return "email-id"

        def fake_send(params):
            captured["html"] = params["html"]
            return _FakeResp()

        monkeypatch.setattr(email_service.resend.Emails, "send", fake_send)
        # Force the module to think the api key is set so it does not
        # short-circuit to False.
        monkeypatch.setattr(email_service.resend, "api_key", "test-key")

        ok = await email_service.send_password_reset_email(
            "user@example.com", "tok-abc123"
        )
        assert ok is True
        assert "https://omnifox.example.com/reset-password?token=tok-abc123" in captured["html"]
        assert "staging-omnifox.in2-comms.com" not in captured["html"]

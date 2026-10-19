"""Tests for backend/bootstrap.py: idempotent seeding + password validation."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def bootstrap_db_session(monkeypatch):
    """Fresh in-memory SQLite engine; patches database.SessionLocal so
    bootstrap.run_bootstrap() (which calls SessionLocal directly) uses it.
    Yields an open Session for direct assertions; tears down after the test.
    """
    import database
    import models  # noqa: F401 - ensure model metadata is registered

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        database.Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ---- validate_admin_password ----------------------------------------------

class TestValidateAdminPassword:
    def test_empty_password_rejected(self):
        from bootstrap import WeakPasswordError, validate_admin_password
        with pytest.raises(WeakPasswordError, match="empty"):
            validate_admin_password("")

    def test_too_short_rejected(self):
        from bootstrap import WeakPasswordError, validate_admin_password
        with pytest.raises(WeakPasswordError, match="too short"):
            validate_admin_password("Short1!")

    @pytest.mark.parametrize(
        "weak",
        [
            "changeme1234",
            "password!2026",
            "Admin-2025_OK",
            "letmein_999999",
        ],
    )
    def test_weak_prefix_rejected(self, weak):
        from bootstrap import WeakPasswordError, validate_admin_password
        with pytest.raises(WeakPasswordError, match="common weak root"):
            validate_admin_password(weak)

    def test_letters_only_rejected(self):
        from bootstrap import WeakPasswordError, validate_admin_password
        with pytest.raises(WeakPasswordError, match="letter and one non-letter"):
            validate_admin_password("AllLettersOnly")

    def test_digits_only_rejected(self):
        from bootstrap import WeakPasswordError, validate_admin_password
        with pytest.raises(WeakPasswordError, match="letter and one non-letter"):
            validate_admin_password("12345678901234")

    def test_strong_password_accepted(self):
        from bootstrap import validate_admin_password
        validate_admin_password("Goodpass-12345")  # no raise = pass


# ---- validate_admin_email --------------------------------------------------

class TestValidateAdminEmail:
    @pytest.mark.parametrize("bad", ["", "   ", "noatsign", "@leading.com", "trailing@"])
    def test_invalid_emails_rejected(self, bad):
        from bootstrap import validate_admin_email
        with pytest.raises(ValueError):
            validate_admin_email(bad)

    def test_valid_email_accepted(self):
        from bootstrap import validate_admin_email
        validate_admin_email("admin@example.com")  # no raise = pass


# ---- ensure_permissions / ensure_roles idempotency -------------------------

class TestSeedIdempotency:
    def test_first_run_creates_all_baseline(self, bootstrap_db_session):
        from bootstrap import PERMISSIONS, ROLES, ensure_permissions, ensure_roles
        from models import Permission, Role
        db = bootstrap_db_session

        perms_created = ensure_permissions(db)
        roles_created = ensure_roles(db)

        assert perms_created == len(PERMISSIONS)
        assert roles_created == len(ROLES)
        assert db.query(Permission).count() == len(PERMISSIONS)
        assert db.query(Role).count() == len(ROLES)

    def test_second_run_is_noop(self, bootstrap_db_session):
        from bootstrap import ensure_permissions, ensure_roles
        db = bootstrap_db_session

        ensure_permissions(db)
        ensure_roles(db)

        assert ensure_permissions(db) == 0
        assert ensure_roles(db) == 0

    def test_admin_role_has_all_permissions(self, bootstrap_db_session):
        from bootstrap import PERMISSIONS, ensure_permissions, ensure_roles
        from models import Role
        db = bootstrap_db_session

        ensure_permissions(db)
        ensure_roles(db)

        admin = db.query(Role).filter(Role.name == "admin").first()
        admin_perm_names = {p.name for p in admin.permissions}
        baseline = {p.name for p in PERMISSIONS}
        assert admin_perm_names == baseline

    def test_viewer_role_has_only_view_reports(self, bootstrap_db_session):
        from bootstrap import ensure_permissions, ensure_roles
        from models import Role
        db = bootstrap_db_session

        ensure_permissions(db)
        ensure_roles(db)

        viewer = db.query(Role).filter(Role.name == "viewer").first()
        assert {p.name for p in viewer.permissions} == {"view_reports"}


# ---- ensure_first_admin ----------------------------------------------------

class TestEnsureFirstAdmin:
    def test_skips_when_no_env_and_no_args(self, bootstrap_db_session, monkeypatch):
        from bootstrap import ensure_first_admin, ensure_permissions, ensure_roles
        from models import User
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)
        monkeypatch.delenv("FIRST_ADMIN_EMAIL", raising=False)
        monkeypatch.delenv("FIRST_ADMIN_PASSWORD", raising=False)

        assert ensure_first_admin(db) is False
        assert db.query(User).count() == 0

    def test_skips_when_users_table_non_empty(self, bootstrap_db_session, monkeypatch):
        from bootstrap import ensure_first_admin, ensure_permissions, ensure_roles
        from models import User
        from utils.security import hash_password
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)

        # Seed a pre-existing user.
        db.add(User(
            email="someone@example.com",
            hashed_password=hash_password("Goodpass-12345"),
            auth_provider="email",
            email_verified=True,
            is_active=True,
        ))
        db.commit()

        result = ensure_first_admin(
            db, email="admin@example.com", password="Goodpass-12345"
        )
        assert result is False
        assert db.query(User).count() == 1  # no new user

    def test_creates_admin_with_explicit_args(self, bootstrap_db_session):
        from bootstrap import ensure_first_admin, ensure_permissions, ensure_roles
        from models import User
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)

        created = ensure_first_admin(
            db,
            email="admin@example.com",
            password="Goodpass-12345",
            name="Boss",
        )

        assert created is True
        user = db.query(User).filter(User.email == "admin@example.com").first()
        assert user is not None
        assert user.name == "Boss"
        assert user.email_verified is True
        assert user.is_active is True
        assert {r.name for r in user.roles} == {"admin"}

    def test_creates_admin_from_env_vars(self, bootstrap_db_session, monkeypatch):
        from bootstrap import ensure_first_admin, ensure_permissions, ensure_roles
        from models import User
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)
        monkeypatch.setenv("FIRST_ADMIN_EMAIL", "env-admin@example.com")
        monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Goodpass-12345")
        monkeypatch.setenv("FIRST_ADMIN_NAME", "From Env")

        created = ensure_first_admin(db)
        assert created is True
        user = db.query(User).filter(User.email == "env-admin@example.com").first()
        assert user is not None
        assert user.name == "From Env"

    def test_rejects_weak_password_from_env(self, bootstrap_db_session, monkeypatch):
        from bootstrap import WeakPasswordError, ensure_first_admin, ensure_permissions, ensure_roles
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)
        monkeypatch.setenv("FIRST_ADMIN_EMAIL", "admin@example.com")
        monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "short")

        with pytest.raises(WeakPasswordError):
            ensure_first_admin(db)

    def test_rejects_when_admin_role_missing(self, bootstrap_db_session):
        from bootstrap import ensure_first_admin
        db = bootstrap_db_session
        # NOTE: skipping ensure_roles() on purpose.

        with pytest.raises(RuntimeError, match="admin.*role not found"):
            ensure_first_admin(
                db, email="admin@example.com", password="Goodpass-12345"
            )

    def test_password_is_hashed_not_stored_plain(self, bootstrap_db_session):
        from bootstrap import ensure_first_admin, ensure_permissions, ensure_roles
        from models import User
        db = bootstrap_db_session
        ensure_permissions(db); ensure_roles(db)

        plaintext = "Goodpass-12345"
        ensure_first_admin(db, email="admin@example.com", password=plaintext)

        user = db.query(User).filter(User.email == "admin@example.com").first()
        assert user.hashed_password != plaintext
        assert user.hashed_password.startswith("$argon2")

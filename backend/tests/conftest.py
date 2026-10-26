"""Pytest configuration: set env vars and sys.path before any backend import."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-api-key")
os.environ.setdefault("EXPORTCOMMENTS_API_KEY", "test-exportcomments-api-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-bytes-long")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "VGhpcy1pcy1hLXRlc3Qta2V5LW5vdC1mb3ItcHJvZCE=")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("RESEND_API_KEY", "test-resend-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_omnifox.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("FRONTEND_URL", "https://test.example.com")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def _disable_rate_limiter_for_unit_tests():
    """Disable the slowapi limiter for direct-call unit tests.

    The limiter decorator demands a real `starlette.requests.Request`
    object - direct calls to a route handler with a MagicMock crash
    inside slowapi's wrapper before the handler runs. Tests that
    actually want to exercise the limiter (test_rate_limit_h2.py)
    re-enable it inside their own fixture by calling limiter.reset().
    """
    from utils.rate_limit import limiter
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def task_db_session_factory(monkeypatch):
    """Provide an isolated in-memory SQLite engine and patch SessionLocal.

    Each test gets a fresh DB; tables are created from Base.metadata.
    The fixture monkeypatches database.SessionLocal so DatabaseTaskManager
    (which calls SessionLocal() internally) uses the test engine.
    """
    import database
    import models  # noqa: F401 - registers all models before create_all

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    database.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "SessionLocal", TestSession)
    # If task_manager has done `from database import SessionLocal` at module
    # level (it will after Task 4), patch that namespace too. raising=False
    # keeps this a no-op until that import lands.
    import task_manager
    monkeypatch.setattr(task_manager, "SessionLocal", TestSession, raising=False)
    import cache_service
    monkeypatch.setattr(cache_service, "SessionLocal", TestSession)

    yield TestSession

    database.Base.metadata.drop_all(bind=engine)
    engine.dispose()


APP_PASSWORD = "Goodpass-12345"


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """The real app on a temp SQLite DB with three users (basic, dashboard,
    admin; password APP_PASSWORD). client.db is the session factory."""
    from config import settings
    monkeypatch.setattr(settings, "debug", True)

    import database
    import models  # noqa: F401
    import cache_service
    import simple_analytics
    import task_manager
    from services import trends

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)
    for module in (simple_analytics, task_manager, cache_service, trends):
        monkeypatch.setattr(module, "SessionLocal", TestSession)

    from bootstrap import ensure_permissions, ensure_roles
    from models import Role, User
    from utils.security import hash_password

    with TestSession() as db:
        ensure_permissions(db)
        ensure_roles(db)
        for email, role in [("basic@example.com", "basic_user"), ("dash@example.com", "dashboard_user"), ("admin@example.com", "admin")]:
            user = User(email=email, hashed_password=hash_password(APP_PASSWORD), is_active=True)
            user.roles.append(db.query(Role).filter(Role.name == role).first())
            db.add(user)
        db.commit()

    import main
    from fastapi.testclient import TestClient
    from utils.rate_limit import limiter
    limiter.enabled = False

    client = TestClient(main.app)
    client.db = TestSession
    try:
        yield client
    finally:
        database.Base.metadata.drop_all(bind=engine)
        engine.dispose()

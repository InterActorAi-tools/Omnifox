"""Tests for SECURITY_ASSESSMENT.md H2: per-endpoint rate limiting.

Hits the real endpoints through TestClient. slowapi keys its in-memory
store off the limiter instance, so we reset that store between tests
to keep them independent.

We do NOT test the actual auth/AI logic here - we only assert the rate
limiter fires at the documented threshold. Hitting /auth/login with
the wrong password is exactly what an attacker does, so a 401 followed
by 429s is the correct shape.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Force dev mode (settings.is_production=False) so /openapi.json is
    # available if a test needs it, and so HSTS is off.
    from config import settings
    monkeypatch.setattr(settings, "debug", True)

    # Swap the live engine / SessionLocal in `database` for a fresh
    # tmp-sqlite pair. Going through DATABASE_URL + importlib.reload
    # does NOT work in CI: config.settings is a module-level singleton
    # captured at first import, so reloading `database` re-binds to
    # the same already-instantiated settings object - the env-var
    # change never reaches the engine and the test ends up hitting the
    # real Postgres URL (where the `users` table doesn't exist in our
    # ephemeral schema, producing UndefinedTable -> 500). Patching the
    # `database` namespace directly is the pattern conftest.py's
    # task_db_session_factory uses and it sidesteps the singleton
    # problem entirely.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import models  # noqa: F401 - register model metadata before create_all

    db_path = tmp_path / "rl.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    database.Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    import main

    # conftest.py disables the limiter for unit tests; re-enable here
    # since this whole module is about asserting the limiter fires.
    # Reset the storage so each test starts with empty counters.
    from utils.rate_limit import limiter
    limiter.enabled = True
    limiter.reset()

    try:
        yield TestClient(main.app)
    finally:
        database.Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


# ---- /auth/login ----------------------------------------------------------

class TestLoginRateLimit:
    def test_429_after_five_requests_in_one_minute(self, client):
        # 5/minute limit. The 6th request from the same IP must 429.
        body = {"email": "no-such-user@example.com", "password": "wrong"}
        for _ in range(5):
            resp = client.post("/api/auth/login", json=body)
            assert resp.status_code in (401, 422), resp.text  # auth fail, not rate-limited yet

        resp = client.post("/api/auth/login", json=body)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert "Too many requests" in resp.json()["detail"]


# ---- /auth/verify-2fa -----------------------------------------------------

class TestVerify2FARateLimit:
    def test_429_after_five_requests(self, client):
        body = {"email": "no-such-user@example.com", "code": "000000"}
        for _ in range(5):
            resp = client.post("/api/auth/verify-2fa", json=body)
            assert resp.status_code in (401, 403, 422), resp.text

        resp = client.post("/api/auth/verify-2fa", json=body)
        assert resp.status_code == 429


# ---- /auth/forgot-password -------------------------------------------------

class TestForgotPasswordRateLimit:
    def test_429_after_three_requests(self, client):
        # Tighter cap (3/min) because each request can trigger an email.
        body = {"email": "no-such-user@example.com"}
        for _ in range(3):
            resp = client.post("/api/auth/forgot-password", json=body)
            # Endpoint returns 200 even for unknown emails to prevent
            # enumeration. Any non-429 is fine pre-limit.
            assert resp.status_code != 429

        resp = client.post("/api/auth/forgot-password", json=body)
        assert resp.status_code == 429


# ---- 429 response shape ----------------------------------------------------

class TestRateLimitResponseShape:
    def test_429_returns_json_not_plaintext(self, client):
        body = {"email": "x@example.com", "password": "y"}
        # Burst over the limit.
        for _ in range(7):
            resp = client.post("/api/auth/login", json=body)
        assert resp.status_code == 429
        # The handler we registered returns JSON. Default slowapi
        # would return text/plain, which the frontend can't parse.
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert "detail" in body


# ---- Success paths must survive the limiter ---------------------------------
#
# With headers_enabled=True, slowapi writes X-RateLimit-* headers on the
# `response` parameter. A limited endpoint that returns a dict without
# that parameter raised on every successful request (500), which the
# rest of the suite never saw because conftest disables the limiter.

class TestLimitedEndpointsSucceed:
    def test_forgot_password_success_path_is_200(self, client):
        resp = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        assert resp.status_code == 200, resp.text
        assert "X-RateLimit-Limit" in resp.headers

    def test_every_limited_endpoint_accepts_a_response_param(self, client):
        import importlib
        import inspect
        from fastapi import Response
        from utils.rate_limit import limiter

        names = list(limiter._route_limits)
        assert len(names) >= 7
        for name in names:
            module_name, func_name = name.rsplit(".", 1)
            func = getattr(importlib.import_module(module_name), func_name)
            params = inspect.signature(func).parameters.values()
            assert any(p.annotation is Response for p in params), f"{name} lacks `response: Response`"

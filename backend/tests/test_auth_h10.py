"""Tests for SECURITY_ASSESSMENT.md H10: JWT cookie migration + CSRF.

Verifies:
  - /auth/login sets HttpOnly access_token + refresh_token cookies and
    a JS-readable XSRF-TOKEN cookie; the JSON body NO LONGER carries
    the tokens.
  - get_current_user reads the access_token cookie (no Authorization
    header) and authenticates successfully.
  - /auth/refresh reads the refresh_token cookie when no JSON body is
    present (the browser path).
  - /auth/logout clears all three cookies.
  - CSRF middleware blocks state-changing requests that present an
    access_token cookie but no matching X-CSRF-Token header.
  - CSRF middleware lets safe methods (GET) and Bearer-only callers
    (no access_token cookie) through.

Uses TestClient with a tmp-sqlite engine; same pattern as
test_rate_limit_h2.py for parity with how the rest of the suite
bootstraps a clean DB.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils.cookies import (
    ACCESS_TOKEN_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    REFRESH_TOKEN_COOKIE,
)


# ---- Fixtures --------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient backed by a fresh tmp-sqlite engine.

    Patches `database` namespace directly to sidestep the
    config.settings singleton (see test_rate_limit_h2.py for why
    importlib.reload + env-var monkeypatch does not work).
    """
    from config import settings
    monkeypatch.setattr(settings, "debug", True)

    import database
    import models  # noqa: F401

    db_path = tmp_path / "h10.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    database.Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    # Pre-seed roles + permissions + a known user so /auth/login works.
    from bootstrap import ensure_permissions, ensure_roles
    from models import User
    from utils.security import hash_password

    with TestSession() as db:
        ensure_permissions(db)
        ensure_roles(db)
        db.add(User(
            email="alice@example.com",
            name="Alice",
            hashed_password=hash_password("Goodpass-12345"),
            auth_provider="email",
            email_verified=True,
            is_active=True,
        ))
        db.commit()

    import main

    # Disable rate limiter for this suite - we want to exercise auth
    # flow, not slowapi.
    from utils.rate_limit import limiter
    limiter.enabled = False

    try:
        yield TestClient(main.app)
    finally:
        database.Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def _login(client: TestClient) -> dict[str, str]:
    """Helper: log alice in and return the resulting cookie jar."""
    resp = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "Goodpass-12345"},
    )
    assert resp.status_code == 200, resp.text
    return resp.cookies


# ---- /auth/login: cookies are set, JSON tokens are gone -------------------

class TestLoginCookies:
    def test_login_sets_all_three_cookies(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "Goodpass-12345"},
        )
        assert resp.status_code == 200, resp.text

        # All three cookies present on the response.
        cookies = resp.cookies
        assert cookies.get(ACCESS_TOKEN_COOKIE)
        assert cookies.get(REFRESH_TOKEN_COOKIE)
        assert cookies.get(CSRF_COOKIE)

    def test_login_response_body_contains_no_tokens(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "Goodpass-12345"},
        )
        body = resp.json()
        # Schema retains the keys for backward compat but both must be empty.
        assert body.get("access_token") == ""
        assert body.get("refresh_token") == ""
        assert body["user"]["email"] == "alice@example.com"

    def test_access_token_cookie_is_httponly(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "Goodpass-12345"},
        )
        # Inspect the raw Set-Cookie header so we can assert HttpOnly.
        set_cookies = resp.headers.get_list("set-cookie")
        access_header = next(
            (h for h in set_cookies if h.startswith(f"{ACCESS_TOKEN_COOKIE}=")),
            None,
        )
        assert access_header is not None
        assert "HttpOnly" in access_header
        # SameSite=Lax (user's chosen policy).
        assert "SameSite=lax" in access_header.lower() or "samesite=lax" in access_header.lower()

    def test_csrf_cookie_is_NOT_httponly(self, client):
        # The CSRF cookie MUST be readable by JS so the frontend can
        # echo it as a header. HttpOnly on this one would break the
        # double-submit pattern.
        resp = client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "Goodpass-12345"},
        )
        set_cookies = resp.headers.get_list("set-cookie")
        csrf_header = next(
            (h for h in set_cookies if h.startswith(f"{CSRF_COOKIE}=")),
            None,
        )
        assert csrf_header is not None
        assert "HttpOnly" not in csrf_header


# ---- Cookie auth: subsequent requests authenticate from cookies -----------

class TestCookieAuth:
    def test_get_me_works_with_cookie_auth(self, client):
        _login(client)
        # TestClient persists cookies across requests by default.
        resp = client.get("/api/users/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == "alice@example.com"

    def test_get_me_fails_without_cookie(self, client):
        # No login -> no cookie -> 401.
        resp = client.get("/api/users/me")
        assert resp.status_code in (401, 403), resp.text

    def test_refresh_token_is_not_accepted_as_access_token(self, client):
        # A refresh JWT has no session_id, so accepting it as an access
        # token would bypass logout/session revocation.
        _login(client)
        refresh = client.cookies.get(REFRESH_TOKEN_COOKIE)
        client.cookies.clear()
        resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {refresh}"})
        assert resp.status_code == 401, resp.text


# ---- /auth/refresh: cookie-only path ---------------------------------------

class TestRefreshFromCookie:
    def test_refresh_reads_cookie_and_rotates(self, client):
        _login(client)
        old_access = client.cookies.get(ACCESS_TOKEN_COOKIE)
        old_refresh = client.cookies.get(REFRESH_TOKEN_COOKIE)

        # Empty body - the cookie carries the refresh token.
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 200, resp.text

        new_access = resp.cookies.get(ACCESS_TOKEN_COOKIE)
        new_refresh = resp.cookies.get(REFRESH_TOKEN_COOKIE)
        # Rotation occurred: both tokens are fresh.
        assert new_access and new_access != old_access
        assert new_refresh and new_refresh != old_refresh

    def test_refresh_with_empty_json_body_uses_cookie(self, client):
        # The frontend posts {} - that must not fail validation (422).
        _login(client)
        resp = client.post("/api/auth/refresh", json={})
        assert resp.status_code == 200, resp.text

    def test_refresh_without_cookie_or_body_is_401(self, client):
        # No login, no body. Must be 401.
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 401


# ---- /auth/logout: cookies cleared -----------------------------------------

class TestLogoutClearsCookies:
    def test_logout_returns_204_and_drops_cookies(self, client):
        _login(client)
        # /auth/logout is a state-changing POST that has a cookie session,
        # so it goes through the CSRF middleware. Read the CSRF cookie
        # and echo it.
        csrf = client.cookies.get(CSRF_COOKIE)
        resp = client.post(
            "/api/auth/logout",
            headers={CSRF_HEADER: csrf},
        )
        assert resp.status_code == 200, resp.text

        # The response's Set-Cookie headers should expire the cookies.
        set_cookies = resp.headers.get_list("set-cookie")
        joined = " ".join(set_cookies)
        assert ACCESS_TOKEN_COOKIE in joined
        assert REFRESH_TOKEN_COOKIE in joined
        assert CSRF_COOKIE in joined
        # delete_cookie writes Max-Age=0.
        assert "Max-Age=0" in joined or "max-age=0" in joined.lower()


# ---- CSRF middleware -------------------------------------------------------

class TestCSRFMiddleware:
    def test_post_without_csrf_header_is_blocked(self, client):
        _login(client)
        # Try a mutating call without the X-CSRF-Token header.
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 403
        assert "CSRF" in resp.json().get("detail", "")

    def test_post_with_wrong_csrf_header_is_blocked(self, client):
        _login(client)
        resp = client.post(
            "/api/auth/logout",
            headers={CSRF_HEADER: "definitely-not-the-real-token"},
        )
        assert resp.status_code == 403

    def test_post_with_matching_csrf_header_passes(self, client):
        _login(client)
        csrf = client.cookies.get(CSRF_COOKIE)
        resp = client.post(
            "/api/auth/logout",
            headers={CSRF_HEADER: csrf},
        )
        # 200 from the handler, not 403 from the middleware.
        assert resp.status_code == 200

    def test_get_passes_without_csrf(self, client):
        # Safe methods are never CSRF-checked.
        _login(client)
        resp = client.get("/api/users/me")
        assert resp.status_code == 200

    def test_login_is_csrf_exempt(self, client):
        # /auth/login is the bootstrap - the caller has no cookie yet,
        # so there is nothing to CSRF-check against.
        resp = client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "Goodpass-12345"},
        )
        assert resp.status_code == 200

    def test_bearer_only_caller_is_csrf_exempt(self, client):
        # A non-browser caller using Authorization: Bearer has no
        # access_token cookie, so there is no cross-site cookie
        # attack to defend against. CSRF check skips.
        from utils.security import create_access_token
        token = create_access_token(1, "alice@example.com")
        resp = client.post(
            "/api/users/me/logout-all",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Either 200 (logged out) or 401 (token's user/session no
        # longer matches) - the point is NOT 403 (CSRF).
        assert resp.status_code in (200, 401)

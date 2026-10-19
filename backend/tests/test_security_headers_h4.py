"""Tests for SECURITY_ASSESSMENT.md H4: security headers + /docs gating.

Asserts:
  - Every response carries X-Content-Type-Options, X-Frame-Options,
    Referrer-Policy, Permissions-Policy.
  - HSTS is set in production-mode responses only (never in dev, where
    locking localhost to https would brick the dev workflow).
  - /docs, /redoc, /openapi.json are gated:
      * dev: 200
      * prod: 404
  - CORS no longer wildcards methods/headers (M10).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dev_client(monkeypatch):
    # Force a dev-mode app instance. settings.is_production is computed
    # from settings.debug, so flipping debug=True flips is_production to
    # False (i.e. dev). Re-import main inside the fixture so the
    # conditional `docs_url`/HSTS branches pick up the new state.
    from config import settings
    monkeypatch.setattr(settings, "debug", True)

    import importlib
    import main
    importlib.reload(main)
    return TestClient(main.app)


@pytest.fixture
def prod_client(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "debug", False)

    import importlib
    import main
    importlib.reload(main)
    return TestClient(main.app)


# ---- Security headers -----------------------------------------------------

class TestSecurityHeaders:
    def test_dev_response_has_baseline_headers(self, dev_client):
        # /health exists and does not require auth - perfect probe.
        resp = dev_client.get("/test")
        # /test is unauth and returns JSON, but a 200 isn't required for
        # header presence - what matters is the middleware fired.
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in resp.headers.get("Permissions-Policy", "")

    def test_dev_response_has_NO_hsts(self, dev_client):
        # HSTS in dev would lock the developer's browser to https for
        # localhost - a hostile dev experience. Must not be set in dev.
        resp = dev_client.get("/test")
        assert "Strict-Transport-Security" not in resp.headers

    def test_prod_response_has_hsts(self, prod_client):
        resp = prod_client.get("/test")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts

    def test_headers_applied_on_404(self, dev_client):
        # Even error responses must carry the protective headers.
        resp = dev_client.get("/this/does/not/exist")
        assert resp.status_code == 404
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# ---- /docs gating ---------------------------------------------------------

class TestDocsGating:
    def test_dev_exposes_docs(self, dev_client):
        assert dev_client.get("/docs").status_code == 200
        assert dev_client.get("/redoc").status_code == 200
        assert dev_client.get("/openapi.json").status_code == 200

    def test_prod_hides_docs(self, prod_client):
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/redoc").status_code == 404
        assert prod_client.get("/openapi.json").status_code == 404


# ---- CORS narrowing (M10) -------------------------------------------------

class TestCORSNarrowing:
    def test_preflight_reports_explicit_methods_not_wildcard(self, dev_client):
        # An OPTIONS preflight from an allowed origin must echo the
        # explicit method list, not "*". FastAPI's CORSMiddleware sends
        # access-control-allow-methods on preflights only.
        resp = dev_client.options(
            "/test",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        assert "*" not in allow_methods
        assert "POST" in allow_methods
        assert "GET" in allow_methods

    def test_preflight_reports_explicit_headers_not_wildcard(self, dev_client):
        resp = dev_client.options(
            "/test",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "")
        assert "*" not in allow_headers
        assert "Authorization" in allow_headers
        assert "Content-Type" in allow_headers

"""/api/analytics/* must require login and stats need view_dashboard.
Previously every route was anonymous."""
from __future__ import annotations

import pytest

PASSWORD = "Goodpass-12345"  # matches APP_PASSWORD in conftest


@pytest.fixture
def client(app_client):
    return app_client


def _login(client, email):
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def test_anonymous_is_rejected(client):
    assert client.get("/api/analytics/simple-stats").status_code == 401


def test_basic_user_cannot_read_stats(client):
    _login(client, "basic@example.com")
    assert client.get("/api/analytics/simple-stats").status_code == 403


def test_dashboard_user_can_read_stats(client):
    _login(client, "dash@example.com")
    assert client.get("/api/analytics/simple-stats?preset=last_7_days").status_code == 200


def test_debug_and_test_endpoints_are_gone(client):
    _login(client, "admin@example.com")
    assert client.get("/api/analytics/debug-analytics").status_code == 404
    csrf = {"X-CSRF-Token": client.cookies.get("XSRF-TOKEN")}
    assert client.post("/api/analytics/test-analytics", headers=csrf).status_code in (404, 405)

"""Admins create an account as a 24-hour link; the person sets their own password."""
from datetime import datetime, timedelta

APP_PASSWORD = "Goodpass-12345"  # matches conftest
NEW = {"name": "New Person", "email": "new.person@in2-comms.com", "role": "project_manager"}


def _login(client, email, password=APP_PASSWORD):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN") or ""
    return resp


def test_link_creates_account_with_chosen_role(app_client):
    _login(app_client, "admin@example.com")
    resp = app_client.post("/api/admin/invitations/generate", json=NEW)
    assert resp.status_code == 200, resp.text
    expires = datetime.fromisoformat(str(resp.json()["expires_at"]))
    assert timedelta(hours=23) < expires - datetime.utcnow() <= timedelta(hours=24)
    token = resp.json()["token"]

    app_client.cookies.clear()
    app_client.headers.pop("X-CSRF-Token", None)
    resp = app_client.post("/api/auth/register", json={**NEW, "password": "Mypass-67890!", "token": token})
    assert resp.status_code == 200, resp.text
    assert "project_manager" in resp.json()["user"]["roles"]

    app_client.cookies.clear()
    resp = app_client.post("/api/auth/register", json={**NEW, "password": "Mypass-67890!", "token": token})
    assert resp.status_code == 400  # link works once


def test_only_admins_create_links(app_client):
    _login(app_client, "basic@example.com")
    assert app_client.post("/api/admin/invitations/generate", json=NEW).status_code == 403

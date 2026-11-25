"""Resend emails go out only when RESEND_API_KEY and EMAIL_FROM are set; links work either way."""
import pytest
from config import settings
from utils import email_service

APP_PASSWORD = "Goodpass-12345"  # matches conftest
NEW = {"name": "New Person", "email": "new.person@in2-comms.com", "role": "basic_user"}


@pytest.fixture
def sent(monkeypatch):
    sent = []
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda params: sent.append(params))
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    monkeypatch.setattr(settings, "email_from", "OmniFox <omnifox@example.com>")
    return sent


def _login(client):
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": APP_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN") or ""


def test_create_account_emails_the_link(app_client, sent):
    _login(app_client)
    data = app_client.post("/api/admin/invitations/generate", json=NEW).json()
    assert data["email_sent"] is True
    assert sent[0]["to"] == [NEW["email"]] and data["link"] in sent[0]["html"]


def test_accepted_join_request_gets_welcome_email(app_client, sent):
    app_client.post("/api/auth/join-request", json={**NEW, "password": "Joinpass-12345"})
    _login(app_client)
    request_id = app_client.get("/api/admin/join-requests").json()[0]["id"]
    app_client.post(f"/api/admin/join-requests/{request_id}/accept", json={"role": "basic_user"})
    assert sent[0]["subject"] == "Welcome to OmniFox"


def test_without_email_from_nothing_is_sent(app_client, sent, monkeypatch):
    monkeypatch.setattr(settings, "email_from", "")
    _login(app_client)
    data = app_client.post("/api/admin/invitations/generate", json=NEW).json()
    assert data["email_sent"] is False and data["link"]
    assert sent == []

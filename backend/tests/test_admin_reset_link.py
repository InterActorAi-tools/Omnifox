"""Admins make a password reset link to send by hand."""
APP_PASSWORD = "Goodpass-12345"  # matches conftest


def _login(client, email):
    resp = client.post("/api/auth/login", json={"email": email, "password": APP_PASSWORD})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN")


def _user_id(client, email):
    from models import User
    with client.db() as db:
        return db.query(User).filter(User.email == email).first().id


def test_admin_reset_link_sets_a_new_password(app_client):
    _login(app_client, "admin@example.com")
    link = app_client.post(f"/api/admin/users/{_user_id(app_client, 'basic@example.com')}/reset-link").json()["link"]
    token = link.split("token=")[1]

    resp = app_client.post("/api/auth/reset-password", json={"token": token, "new_password": "Newpass-67890!"})
    assert resp.status_code == 200, resp.text
    resp = app_client.post("/api/auth/login", json={"email": "basic@example.com", "password": "Newpass-67890!"})
    assert resp.status_code == 200, resp.text


def test_only_admins_make_reset_links(app_client):
    _login(app_client, "basic@example.com")
    resp = app_client.post(f"/api/admin/users/{_user_id(app_client, 'admin@example.com')}/reset-link")
    assert resp.status_code == 403

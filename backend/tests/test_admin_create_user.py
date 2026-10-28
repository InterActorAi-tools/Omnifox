"""Admins create accounts with a temporary password that must be changed at first sign-in."""
APP_PASSWORD = "Goodpass-12345"  # matches conftest
NEW = {"name": "New Person", "email": "new.person@in2-comms.com", "password": "Temppass-12345", "role": "basic_user"}


def _login(client, email, password=APP_PASSWORD):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN") or ""
    return resp


def test_new_user_must_change_password_first(app_client):
    _login(app_client, "admin@example.com")
    resp = app_client.post("/api/admin/users", json=NEW)
    assert resp.status_code == 200, resp.text
    assert resp.json()["must_change_password"] is True

    app_client.cookies.clear()
    resp = _login(app_client, NEW["email"], NEW["password"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["must_change_password"] is True
    assert app_client.get("/api/projects").status_code == 403
    assert app_client.get("/api/users/me").status_code == 200

    resp = app_client.post("/api/users/me/change-password",
                           json={"current_password": NEW["password"], "new_password": "Mypass-67890!"})
    assert resp.status_code == 200, resp.text
    assert app_client.get("/api/users/me").json()["must_change_password"] is False
    assert app_client.get("/api/projects").status_code == 200


def test_create_user_rules(app_client):
    _login(app_client, "admin@example.com")
    assert app_client.post("/api/admin/users", json={**NEW, "email": "x@gmail.com"}).status_code == 403
    assert app_client.post("/api/admin/users", json={**NEW, "password": "short"}).status_code == 400
    assert app_client.post("/api/admin/users", json={**NEW, "role": "nope"}).status_code == 400
    assert app_client.post("/api/admin/users", json=NEW).status_code == 200
    assert app_client.post("/api/admin/users", json=NEW).status_code == 400


def test_only_admins_create_users(app_client):
    _login(app_client, "basic@example.com")
    assert app_client.post("/api/admin/users", json=NEW).status_code == 403

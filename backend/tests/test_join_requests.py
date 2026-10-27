"""People can ask to join without an invitation; an admin accepts or rejects."""
APP_PASSWORD = "Goodpass-12345"  # matches conftest
NEW = {"name": "New Person", "email": "new.person@in2-comms.com", "password": "Joinpass-12345"}


def _login(client, email, password=APP_PASSWORD):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN") or ""
    return resp


def _request_id(client):
    _login(client, "admin@example.com")
    requests = client.get("/api/admin/join-requests").json()
    assert [r["email"] for r in requests] == [NEW["email"]]
    return requests[0]["id"]


def test_pending_request_cannot_log_in(app_client):
    assert app_client.post("/api/auth/join-request", json=NEW).status_code == 200
    resp = _login(app_client, NEW["email"], NEW["password"])
    assert resp.status_code == 403
    assert "waiting" in resp.json()["detail"]
    assert _login(app_client, NEW["email"], "Wrongpass-12345").status_code == 401


def test_accepted_request_logs_in_with_chosen_role(app_client):
    app_client.post("/api/auth/join-request", json=NEW)
    resp = app_client.post(f"/api/admin/join-requests/{_request_id(app_client)}/accept", json={"role": "dashboard_user"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == ["dashboard_user"]
    assert app_client.get("/api/admin/join-requests").json() == []

    app_client.cookies.clear()
    assert _login(app_client, NEW["email"], NEW["password"]).status_code == 200


def test_rejected_request_is_gone(app_client):
    app_client.post("/api/auth/join-request", json=NEW)
    assert app_client.delete(f"/api/admin/join-requests/{_request_id(app_client)}").status_code == 200
    assert app_client.get("/api/admin/join-requests").json() == []
    app_client.cookies.clear()
    assert _login(app_client, NEW["email"], NEW["password"]).status_code == 401


def test_join_request_rules(app_client):
    outside = {**NEW, "email": "someone@gmail.com"}
    assert app_client.post("/api/auth/join-request", json=outside).status_code == 403
    assert app_client.post("/api/auth/join-request", json={**NEW, "password": "short"}).status_code == 400
    assert app_client.post("/api/auth/join-request", json=NEW).status_code == 200
    assert app_client.post("/api/auth/join-request", json=NEW).status_code == 400


def test_only_admins_handle_requests(app_client):
    app_client.post("/api/auth/join-request", json=NEW)
    _login(app_client, "basic@example.com")
    assert app_client.get("/api/admin/join-requests").status_code == 403
    assert app_client.post("/api/admin/join-requests/1/accept", json={}).status_code == 403
    assert app_client.delete("/api/admin/join-requests/1").status_code == 403

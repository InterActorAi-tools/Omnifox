"""Private projects: only the owner and the people they share with see them."""
APP_PASSWORD = "Goodpass-12345"  # matches conftest


def _login(client, email):
    resp = client.post("/api/auth/login", json={"email": email, "password": APP_PASSWORD})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN")


def _add_manager(client, email="pm@example.com"):
    from models import Role, User
    from utils.security import hash_password
    with client.db() as db:
        user = User(email=email, hashed_password=hash_password(APP_PASSWORD), is_active=True)
        user.roles.append(db.query(Role).filter(Role.name == "project_manager").one())
        db.add(user)
        db.commit()


def _names(client):
    return {p["name"] for p in client.get("/api/projects").json()}


def _create_private(client):
    _add_manager(client)
    _login(client, "pm@example.com")
    resp = client.post("/api/projects", json={"name": "Secret campaign", "objectives": ["Win trust"], "is_private": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_private_project_hidden_from_admin_and_others(app_client):
    project = _create_private(app_client)
    assert project["is_private"] and project["is_owner"]
    assert "Secret campaign" in _names(app_client)

    for email in ("admin@example.com", "basic@example.com"):
        _login(app_client, email)
        assert "Secret campaign" not in _names(app_client)
        assert app_client.delete(f"/api/projects/{project['id']}").status_code == 404


def test_objectives_are_encrypted_at_rest(app_client):
    _create_private(app_client)
    from sqlalchemy import text
    with app_client.db() as db:
        stored = db.execute(text("SELECT objectives FROM projects")).scalar()
    assert "Win trust" not in stored


def test_owner_shares_with_named_users(app_client):
    project = _create_private(app_client)
    resp = app_client.put(f"/api/projects/{project['id']}/shares", json={"emails": ["basic@example.com"]})
    assert resp.status_code == 200 and resp.json()["shared_with"] == ["basic@example.com"]

    _login(app_client, "basic@example.com")
    shared = next(p for p in app_client.get("/api/projects").json() if p["name"] == "Secret campaign")
    assert shared["objectives"] == ["Win trust"] and not shared["is_owner"] and shared["shared_with"] == []
    assert app_client.put(f"/api/projects/{project['id']}/shares", json={"emails": []}).status_code == 403
    assert app_client.delete(f"/api/projects/{project['id']}").status_code == 403

    _login(app_client, "dash@example.com")
    assert "Secret campaign" not in _names(app_client)


def test_only_admins_create_shared_projects(app_client):
    _add_manager(app_client)
    _login(app_client, "pm@example.com")
    assert app_client.post("/api/projects", json={"name": "Team"}).status_code == 403

    _login(app_client, "basic@example.com")
    assert app_client.post("/api/projects", json={"name": "Mine", "is_private": True}).status_code == 403

    _login(app_client, "admin@example.com")
    assert app_client.post("/api/projects", json={"name": "Team"}).status_code == 200
    _login(app_client, "basic@example.com")
    assert "Team" in _names(app_client)


def test_upload_to_someone_elses_private_project_refused(app_client):
    _create_private(app_client)
    _login(app_client, "basic@example.com")
    resp = app_client.post("/api/process/basic@example.com", data={"project": "Secret campaign"},
                           files={"file": ("c.xlsx", b"PK", "application/octet-stream")})
    assert resp.status_code == 404


def test_analytics_hide_private_project_names(app_client):
    _create_private(app_client)
    from simple_analytics import enhanced_analytics
    enhanced_analytics.track_usage("Secret campaign", "pm@example.com", 5, "file_upload")
    stats = enhanced_analytics.get_project_stats_filtered()
    assert [p["project"] for p in stats["project_breakdown"]] == ["Private project"]


def test_deleting_my_data_deletes_my_private_projects(app_client):
    _create_private(app_client)
    from models import Project, User
    from services.privacy import delete_user_data
    with app_client.db() as db:
        delete_user_data(db, db.query(User).filter(User.email == "pm@example.com").one())
        assert db.query(Project).count() == 0

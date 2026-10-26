"""Private projects are locked with keys only their members can open (option B)."""
import pyotp
import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import text

APP_PASSWORD = "Goodpass-12345"  # matches conftest


def _login(client, email, password=APP_PASSWORD):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN")
    return resp.json()


def _add_manager(client, email="pm@example.com"):
    from models import Role, User
    from utils.security import hash_password
    with client.db() as db:
        user = User(email=email, hashed_password=hash_password(APP_PASSWORD), is_active=True)
        user.roles.append(db.query(Role).filter(Role.name == "project_manager").one())
        db.add(user)
        db.commit()


def _create_private(client):
    _add_manager(client)
    first = _login(client, "pm@example.com")
    resp = client.post("/api/projects", json={"name": "Secret campaign", "objectives": ["Win trust"], "is_private": True})
    assert resp.status_code == 200, resp.text
    return first, resp.json()


def _project(client, name="Secret campaign"):
    return next(p for p in client.get("/api/projects").json() if p["name"] == name)


def _server_only_decrypt(token: str):
    """What someone holding the database and the server key can do."""
    import contextvars
    from utils.crypto import decrypt
    return contextvars.Context().run(decrypt, token.encode())


def test_recovery_code_shown_once(app_client):
    first, _ = _create_private(app_client)
    assert first["recovery_code"] and not first["keys_locked"]
    assert _login(app_client, "pm@example.com")["recovery_code"] is None


def test_server_key_cannot_read_private_objectives(app_client):
    _create_private(app_client)
    with app_client.db() as db:
        stored = db.execute(text("SELECT objectives FROM projects")).scalar()
    with pytest.raises(InvalidToken):
        _server_only_decrypt(stored)
    assert _project(app_client)["objectives"] == ["Win trust"]


def test_shared_member_unlocks_with_their_own_key(app_client):
    _create_private(app_client)
    project = _project(app_client)
    resp = app_client.put(f"/api/projects/{project['id']}/shares", json={"emails": ["basic@example.com"]})
    assert resp.status_code == 400  # basic has never signed in, so has no key yet

    _login(app_client, "basic@example.com")
    _login(app_client, "pm@example.com")
    assert app_client.put(f"/api/projects/{project['id']}/shares", json={"emails": ["basic@example.com"]}).status_code == 200

    _login(app_client, "basic@example.com")
    shared = _project(app_client)
    assert shared["objectives"] == ["Win trust"] and not shared["locked"]


def test_session_survives_refresh_and_password_change(app_client):
    _create_private(app_client)
    assert app_client.post("/api/auth/refresh").status_code == 200
    app_client.headers["X-CSRF-Token"] = app_client.cookies.get("XSRF-TOKEN")
    assert _project(app_client)["objectives"] == ["Win trust"]

    resp = app_client.post("/api/users/me/change-password",
                           json={"current_password": APP_PASSWORD, "new_password": "Newpass-67890!"})
    assert resp.status_code == 200, resp.text
    _login(app_client, "pm@example.com", "Newpass-67890!")
    assert _project(app_client)["objectives"] == ["Win trust"]


def _forget_password(client, new_password="Resetpass-1234!"):
    """Simulate a password reset: the stored key still needs the old password."""
    from models import User
    from utils.security import hash_password
    with client.db() as db:
        user = db.query(User).filter(User.email == "pm@example.com").one()
        user.hashed_password = hash_password(new_password)
        db.commit()
    return new_password


def test_reset_password_locks_until_recovery_code(app_client):
    first, _ = _create_private(app_client)
    new_password = _forget_password(app_client)

    login = _login(app_client, "pm@example.com", new_password)
    assert login["keys_locked"]
    locked = _project(app_client)
    assert locked["locked"] and locked["objectives"] == []

    wrong = app_client.post("/api/users/me/keys/recover", json={"recovery_code": "AAAA-BBBB", "password": new_password})
    assert wrong.status_code == 400
    resp = app_client.post("/api/users/me/keys/recover", json={"recovery_code": first["recovery_code"], "password": new_password})
    assert resp.status_code == 200, resp.text
    assert _project(app_client)["objectives"] == ["Win trust"]

    # ...and the new password opens it from now on.
    assert not _login(app_client, "pm@example.com", new_password)["keys_locked"]
    assert _project(app_client)["objectives"] == ["Win trust"]


def test_starting_over_deletes_projects_nobody_can_open(app_client):
    _create_private(app_client)
    new_password = _forget_password(app_client)
    _login(app_client, "pm@example.com", new_password)

    resp = app_client.post("/api/users/me/keys/reset", json={"password": new_password})
    assert resp.status_code == 200 and resp.json()["recovery_code"]
    assert app_client.get("/api/users/me/keys").json() == {"has_keys": True, "unlocked": True, "has_password": True}
    assert all(p["name"] != "Secret campaign" for p in app_client.get("/api/projects").json())


def test_two_factor_login_unlocks_keys(app_client):
    from models import User
    _create_private(app_client)
    secret = pyotp.random_base32()
    with app_client.db() as db:
        user = db.query(User).filter(User.email == "pm@example.com").one()
        user.two_factor_enabled, user.two_factor_secret = True, secret
        db.commit()

    assert _login(app_client, "pm@example.com")["requires_2fa"]
    resp = app_client.post("/api/auth/verify-2fa", json={"email": "pm@example.com", "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 200, resp.text
    app_client.headers["X-CSRF-Token"] = app_client.cookies.get("XSRF-TOKEN")
    assert _project(app_client)["objectives"] == ["Win trust"]


def test_new_user_with_2fa_gets_keys_after_second_step(app_client):
    from models import User
    secret = pyotp.random_base32()
    with app_client.db() as db:
        user = db.query(User).filter(User.email == "basic@example.com").one()
        user.two_factor_enabled, user.two_factor_secret = True, secret
        db.commit()
    assert app_client.post("/api/auth/login", json={"email": "basic@example.com", "password": APP_PASSWORD}).json()["requires_2fa"]
    resp = app_client.post("/api/auth/verify-2fa", json={"email": "basic@example.com", "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 200 and resp.json()["recovery_code"]
    assert app_client.get("/api/users/me/keys").json()["unlocked"]


def test_upload_to_private_project_is_stored_under_its_key(app_client, monkeypatch, tmp_path):
    import asyncio
    from api.routes import upload
    from utils.crypto import read_file
    monkeypatch.setattr(upload, "UPLOAD_FOLDER", str(tmp_path))
    seen = []

    async def fake_processing(file_path, *args):
        seen.append(read_file(file_path))  # the background job can still read it

    monkeypatch.setattr(upload, "process_file_with_progress", fake_processing)
    _create_private(app_client)
    resp = app_client.post("/api/upload/process/pm@example.com", data={"project": "Secret campaign"},
                           files={"file": ("c.xlsx", b"PK comments", "application/octet-stream")})
    assert resp.status_code == 200, resp.text

    stored = next((tmp_path / "pm@example.com").iterdir()).read_bytes()
    with pytest.raises(InvalidToken):
        _server_only_decrypt(stored.decode())
    asyncio.run(asyncio.sleep(0))
    assert seen == [b"PK comments"]


def test_logged_out_member_cannot_upload(app_client):
    _create_private(app_client)
    app_client.cookies.delete("data_key")
    resp = app_client.post("/api/upload/process/pm@example.com", data={"project": "Secret campaign"},
                           files={"file": ("c.xlsx", b"PK", "application/octet-stream")})
    assert resp.status_code == 403


def test_locked_project_trends_refused(app_client):
    _create_private(app_client)
    project = _project(app_client)
    assert app_client.get(f"/api/projects/{project['id']}/trends").status_code == 200
    app_client.cookies.delete("data_key")
    assert app_client.get(f"/api/projects/{project['id']}/trends").status_code == 403

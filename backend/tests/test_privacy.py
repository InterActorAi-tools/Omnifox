"""GDPR: admins see who did what and when, never users' personal data."""
APP_PASSWORD = "Goodpass-12345"  # matches conftest


def _login(client, email):
    resp = client.post("/api/auth/login", json={"email": email, "password": APP_PASSWORD})
    assert resp.status_code == 200, resp.text


def _seed_upload_log(client):
    from models import ActivityLog, User
    with client.db() as db:
        basic = db.query(User).filter(User.email == "basic@example.com").one()
        db.add(ActivityLog(user_id=basic.id, action="file_uploaded", ip_address="203.0.113.9",
                           user_agent="Secret-Browser", extra_data={"filename": "private.xlsx"}))
        db.commit()


def test_admin_audit_log_hides_ip_device_and_details(app_client):
    _seed_upload_log(app_client)
    _login(app_client, "admin@example.com")

    logs = app_client.get("/api/activity-logs/all?action=file_uploaded").json()
    assert logs and logs[0]["user_email"] == "basic@example.com"
    assert logs[0]["ip_address"] is None and logs[0]["user_agent"] is None and logs[0]["details"] is None

    csv = app_client.get("/api/activity-logs/all/export").text
    assert "file_uploaded" in csv
    assert "203.0.113.9" not in csv and "Secret-Browser" not in csv and "private.xlsx" not in csv


def test_user_still_sees_own_details(app_client):
    _seed_upload_log(app_client)
    _login(app_client, "basic@example.com")

    log = next(l for l in app_client.get("/api/activity-logs/me").json() if l["action"] == "file_uploaded")
    assert log["ip_address"] == "203.0.113.9" and log["details"] == {"filename": "private.xlsx"}


def test_admin_session_list_hides_device_and_ip(app_client):
    _login(app_client, "basic@example.com")  # creates a session for basic
    from models import User
    with app_client.db() as db:
        basic_id = db.query(User).filter(User.email == "basic@example.com").one().id

    _login(app_client, "admin@example.com")
    sessions = app_client.get(f"/api/admin/users/{basic_id}/sessions").json()
    assert sessions and sessions[0]["ip_address"] is None and sessions[0]["device_name"] is None


# ---- User data rights -------------------------------------------------------

def _seed_user_data(client, tmp_path, monkeypatch, email="basic@example.com"):
    from models import Task, UsageRecord
    from services import privacy
    from utils.crypto import write_file
    monkeypatch.setattr(privacy, "UPLOAD_FOLDER", str(tmp_path))
    folder = tmp_path / email
    folder.mkdir()
    write_file(str(folder / "result.xlsx"), b"PK result")
    with client.db() as db:
        db.add(Task(task_id="t1", client_id=email, status="completed",
                    result_data={"new_filename": "result.xlsx", "positive_context": "summary"}))
        db.add(UsageRecord(timestamp=1.0, project="P", client_id=email, comments_count=3, operation_type="upload"))
        db.commit()
    return folder


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("XSRF-TOKEN")}


def test_export_contains_decrypted_data(app_client, tmp_path, monkeypatch):
    import io
    import json
    import zipfile
    _seed_user_data(app_client, tmp_path, monkeypatch)
    _login(app_client, "basic@example.com")

    resp = app_client.get("/api/users/me/export")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.read("files/result.xlsx") == b"PK result"
    assert json.loads(zf.read("analyses.json"))[0]["results"]["positive_context"] == "summary"
    assert json.loads(zf.read("profile.json"))["email"] == "basic@example.com"


def test_delete_single_result(app_client, tmp_path, monkeypatch):
    from models import Task
    folder = _seed_user_data(app_client, tmp_path, monkeypatch)
    _login(app_client, "basic@example.com")

    assert app_client.delete("/api/users/me/results/result.xlsx", headers=_csrf(app_client)).status_code == 200
    assert not (folder / "result.xlsx").exists()
    with app_client.db() as db:
        assert db.query(Task).count() == 0
    assert app_client.delete("/api/users/me/results/result.xlsx", headers=_csrf(app_client)).status_code == 404


def test_delete_all_data_keeps_account(app_client, tmp_path, monkeypatch):
    from models import ActivityLog, Task, UsageRecord, User
    folder = _seed_user_data(app_client, tmp_path, monkeypatch)
    _login(app_client, "basic@example.com")

    wrong = app_client.post("/api/users/me/delete-data", json={"confirm_email": "x@example.com"}, headers=_csrf(app_client))
    assert wrong.status_code == 400
    resp = app_client.post("/api/users/me/delete-data", json={"confirm_email": "basic@example.com"}, headers=_csrf(app_client))
    assert resp.status_code == 200
    assert not folder.exists()
    with app_client.db() as db:
        assert db.query(Task).count() == 0
        assert db.query(UsageRecord).one().client_id == "deleted-user"  # counts kept, identity gone
        user = db.query(User).filter(User.email == "basic@example.com").one()
        assert [log.action for log in db.query(ActivityLog).filter(ActivityLog.user_id == user.id)] == ["data_deleted"]


def test_delete_account_erases_everything(app_client, tmp_path, monkeypatch):
    from models import RefreshToken, User
    folder = _seed_user_data(app_client, tmp_path, monkeypatch)
    _login(app_client, "basic@example.com")

    resp = app_client.post("/api/users/me/delete-account", json={"confirm_email": "basic@example.com"}, headers=_csrf(app_client))
    assert resp.status_code == 200
    assert not folder.exists()
    with app_client.db() as db:
        assert db.query(User).filter(User.email == "basic@example.com").count() == 0
        assert db.query(RefreshToken).count() == 0
    assert app_client.get("/api/users/me").status_code == 401


def test_only_admin_cannot_delete_own_account(app_client):
    _login(app_client, "admin@example.com")
    resp = app_client.post("/api/users/me/delete-account", json={"confirm_email": "admin@example.com"}, headers=_csrf(app_client))
    assert resp.status_code == 400


def test_admin_deleting_a_user_erases_their_files(app_client, tmp_path, monkeypatch):
    from models import User
    folder = _seed_user_data(app_client, tmp_path, monkeypatch)
    with app_client.db() as db:
        basic_id = db.query(User).filter(User.email == "basic@example.com").one().id
    _login(app_client, "admin@example.com")

    assert app_client.delete(f"/api/admin/users/{basic_id}", headers=_csrf(app_client)).status_code == 200
    assert not folder.exists()


# ---- Case-variant emails (one account, never two) --------------------------

def test_case_variant_email_cannot_become_a_second_account(app_client):
    _login(app_client, "admin@example.com")
    resp = app_client.post("/api/admin/invitations/generate", headers=_csrf(app_client),
                           json={"email": "Basic@Example.com", "name": "Copy", "role": "basic_user"})
    assert resp.status_code == 400


def test_login_ignores_email_case(app_client):
    resp = app_client.post("/api/auth/login", json={"email": "BASIC@example.com", "password": APP_PASSWORD})
    assert resp.status_code == 200


def test_upload_folder_comes_from_the_account_not_the_url(app_client, tmp_path, monkeypatch):
    import api.routes.upload as upload
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(upload, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(upload, "process_file_with_progress", lambda *a, **k: _noop())
    _login(app_client, "basic@example.com")

    resp = app_client.post("/api/upload/process/BASIC@example.com", headers=_csrf(app_client),
                           files={"file": ("a.xlsx", b"PK data", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                           data={"project": "P"})

    assert resp.status_code == 200, resp.text
    assert [p.name for p in uploads.iterdir()] == ["basic@example.com"]


async def _noop():
    return None


def test_account_whose_email_cannot_be_a_folder_can_still_be_erased(app_client, monkeypatch, tmp_path):
    from models import User
    from services import privacy
    from utils.security import hash_password
    monkeypatch.setattr(privacy, "UPLOAD_FOLDER", str(tmp_path))
    with app_client.db() as db:
        db.add(User(email="o'brien@example.com", hashed_password=hash_password(APP_PASSWORD), is_active=True))
        db.commit()
    _login(app_client, "o'brien@example.com")

    assert app_client.get("/api/users/me/export").status_code == 200
    resp = app_client.post("/api/users/me/delete-account", json={"confirm_email": "o'brien@example.com"}, headers=_csrf(app_client))
    assert resp.status_code == 200



def test_login_prefers_the_exact_spelling_among_legacy_case_duplicates(app_client):
    from models import User
    from utils.dependencies import find_user_by_email
    with app_client.db() as db:
        # Simulates a database where migration 0005 skipped its index.
        db.execute(__import__("sqlalchemy").text("DROP INDEX IF EXISTS ux_users_email_lower"))
        db.add(User(email="Basic@example.com", is_active=True))
        db.commit()
        assert find_user_by_email(db, "basic@example.com").email == "basic@example.com"
        assert find_user_by_email(db, "Basic@example.com").email == "Basic@example.com"

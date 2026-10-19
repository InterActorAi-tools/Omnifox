"""Retention: results, files and task data 30 days; activity logs 365 days."""
import os
import time
from datetime import datetime, timedelta, timezone

from models import ActivityLog, RefreshToken, Task, UsageRecord, User
from services import privacy


def test_retention_removes_only_expired_data(task_db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "UPLOAD_FOLDER", str(tmp_path))
    now = datetime.now(timezone.utc)
    old, recent = now - timedelta(days=31), now - timedelta(days=1)

    user_dir = tmp_path / "alice@example.com"
    user_dir.mkdir()
    (user_dir / "old.xlsx").write_bytes(b"x")
    os.utime(user_dir / "old.xlsx", (old.timestamp(), old.timestamp()))
    (user_dir / "new.xlsx").write_bytes(b"x")

    with task_db_session_factory() as db:
        user = User(email="alice@example.com")
        db.add(user)
        db.flush()
        db.add_all([
            Task(task_id="old", client_id=user.email, status="completed", created_at=old),
            Task(task_id="new", client_id=user.email, status="completed", created_at=recent),
            ActivityLog(user_id=user.id, action="login", created_at=now - timedelta(days=366)),
            ActivityLog(user_id=user.id, action="login", created_at=now - timedelta(days=300)),
            UsageRecord(timestamp=old.timestamp(), project="P", client_id=user.email, comments_count=5, operation_type="upload"),
            UsageRecord(timestamp=time.time(), project="P", client_id=user.email, comments_count=5, operation_type="upload"),
            RefreshToken(user_id=user.id, token_hash="expired", expires_at=now - timedelta(days=1)),
        ])
        db.commit()

        counts = privacy.run_retention(db)

        assert [t.task_id for t in db.query(Task).all()] == ["new"]
        assert db.query(ActivityLog).count() == 1
        assert sorted(u.client_id for u in db.query(UsageRecord).all()) == ["alice@example.com", privacy.ANONYMOUS]
        assert db.query(RefreshToken).count() == 0
    assert counts["files"] == 1
    assert os.listdir(user_dir) == ["new.xlsx"]


def test_retention_removes_old_empty_folders_but_not_new_ones(task_db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "UPLOAD_FOLDER", str(tmp_path))
    old = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    (tmp_path / "gone@example.com").mkdir()
    os.utime(tmp_path / "gone@example.com", (old, old))
    (tmp_path / "uploading@example.com").mkdir()  # just created by an upload

    with task_db_session_factory() as db:
        privacy.run_retention(db)

    assert os.listdir(tmp_path) == ["uploading@example.com"]

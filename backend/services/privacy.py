"""GDPR: retention, erasure and export of personal data.

Retention: results, files, task data and chats 30 days; activity logs 365 days.
Usage counts are kept for analytics but lose the user's identity.
"""
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import UPLOAD_FOLDER
from models import ActivityLog, ChatMessage, Invitation, RefreshToken, Task, UrlCacheEntry, UsageRecord, User
from utils.crypto import read_file
from utils.paths import safe_upload_path

LEGACY_FILES_MARKER = ".legacy-files-encrypted"  # written by bootstrap.encrypt_legacy_files

logger = logging.getLogger(__name__)

RESULT_RETENTION_DAYS = 30
LOG_RETENTION_DAYS = 365
ANONYMOUS = "deleted-user"


def _user_folder(email: str):
    """The user's upload folder, or None if the email cannot be a folder name
    (e.g. o'brien@x.com: such accounts could never upload, so no files exist)."""
    try:
        return safe_upload_path(UPLOAD_FOLDER, email)
    except HTTPException:
        return None


def _tasks_of(db: Session, email: str):
    return db.query(Task).filter(Task.client_id == email)


def delete_result(db: Session, email: str, filename: str) -> bool:
    """Delete one result file and every record that points at it."""
    path = safe_upload_path(UPLOAD_FOLDER, email, filename)
    found = os.path.exists(path)
    if found:
        os.remove(path)

    for task in _tasks_of(db, email).all():
        if (task.result_data or {}).get("new_filename") == filename:
            db.delete(task)
            found = True
    for entry in db.query(UrlCacheEntry).filter(
        UrlCacheEntry.client_id == email,
        UrlCacheEntry.processed_filename == filename,
    ).all():
        extracted = safe_upload_path(UPLOAD_FOLDER, email, entry.extracted_filename)
        if os.path.exists(extracted):
            os.remove(extracted)
        db.delete(entry)
        found = True
    db.query(ChatMessage).filter(ChatMessage.client_id == email, ChatMessage.filename == filename).delete(synchronize_session=False)
    db.commit()
    return found


def delete_user_data(db: Session, user: User, delete_account: bool = False) -> None:
    """Erase everything held about a user. Usage counts stay, anonymised."""
    email = user.email
    folder = _user_folder(email)
    if folder:
        shutil.rmtree(folder, ignore_errors=True)
    _tasks_of(db, email).delete(synchronize_session=False)
    db.query(UrlCacheEntry).filter(UrlCacheEntry.client_id == email).delete(synchronize_session=False)
    db.query(ChatMessage).filter(ChatMessage.client_id == email).delete(synchronize_session=False)
    db.query(UsageRecord).filter(UsageRecord.client_id == email).update(
        {UsageRecord.client_id: ANONYMOUS}, synchronize_session=False)
    db.query(ActivityLog).filter(ActivityLog.user_id == user.id).delete(synchronize_session=False)
    if delete_account:
        db.query(Invitation).filter(func.lower(Invitation.email) == email.lower()).delete(synchronize_session=False)
        db.delete(user)  # cascades to sessions and roles
    db.commit()


def export_user_data(db: Session, user: User) -> bytes:
    """A ZIP with everything held about the user (GDPR access/portability)."""
    profile = {
        "email": user.email, "name": user.name, "auth_provider": user.auth_provider,
        "roles": [r.name for r in user.roles], "two_factor_enabled": user.two_factor_enabled,
        "created_at": user.created_at, "last_login": user.last_login,
    }
    sessions = [
        {"device": s.device_name, "ip_address": s.ip_address, "user_agent": s.user_agent,
         "created_at": s.created_at, "last_used": s.last_used}
        for s in db.query(RefreshToken).filter(RefreshToken.user_id == user.id).all()
    ]
    activity = [
        {"action": a.action, "ip_address": a.ip_address, "user_agent": a.user_agent,
         "details": a.extra_data, "created_at": a.created_at}
        for a in db.query(ActivityLog).filter(ActivityLog.user_id == user.id).order_by(ActivityLog.created_at).all()
    ]
    tasks = [
        {"task_id": t.task_id, "type": t.task_type, "status": t.status, "message": t.message,
         "details": t.metadata_json, "results": t.result_data, "created_at": t.created_at}
        for t in _tasks_of(db, user.email).all()
    ]
    usage = [
        {"project": u.project, "comments": u.comments_count, "operation": u.operation_type,
         "at": datetime.fromtimestamp(u.timestamp, timezone.utc)}
        for u in db.query(UsageRecord).filter(UsageRecord.client_id == user.email).all()
    ]

    chats = [
        {"result_file": m.filename, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in db.query(ChatMessage).filter(ChatMessage.client_id == user.email).order_by(ChatMessage.id).all()
    ]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in [("profile", profile), ("sessions", sessions), ("activity", activity),
                           ("analyses", tasks), ("usage", usage), ("chats", chats)]:
            zf.writestr(f"{name}.json", json.dumps(data, indent=2, default=str))
        folder = _user_folder(user.email)
        if folder and os.path.isdir(folder):
            for filename in sorted(os.listdir(folder)):
                path = os.path.join(folder, filename)
                if os.path.isfile(path) and not filename.endswith(".tmp"):
                    zf.writestr(f"files/{filename}", read_file(path))
    return buffer.getvalue()


def run_retention(db: Session) -> dict:
    """Delete or anonymise data past its retention period. Idempotent."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RESULT_RETENTION_DAYS)
    counts = {
        "tasks": db.query(Task).filter(Task.created_at < cutoff).delete(synchronize_session=False),
        "url_cache": db.query(UrlCacheEntry).filter(UrlCacheEntry.created_at < cutoff.timestamp()).delete(synchronize_session=False),
        "chat_messages": db.query(ChatMessage).filter(ChatMessage.created_at < cutoff).delete(synchronize_session=False),
        "usage_anonymised": db.query(UsageRecord).filter(
            UsageRecord.timestamp < cutoff.timestamp(), UsageRecord.client_id != ANONYMOUS,
        ).update({UsageRecord.client_id: ANONYMOUS}, synchronize_session=False),
        "activity_logs": db.query(ActivityLog).filter(
            ActivityLog.created_at < now - timedelta(days=LOG_RETENTION_DAYS)).delete(synchronize_session=False),
        "expired_sessions": db.query(RefreshToken).filter(RefreshToken.expires_at < now).delete(synchronize_session=False),
        "invitations": db.query(Invitation).filter(Invitation.expires_at < cutoff).delete(synchronize_session=False),
    }
    db.commit()

    files = 0
    # Every worker runs this, and uploads write concurrently: anything may
    # vanish under us, and a folder created just now is about to be used.
    for root, _dirs, names in os.walk(UPLOAD_FOLDER, topdown=False):
        for name in names:
            path = os.path.join(root, name)
            if name == LEGACY_FILES_MARKER:
                continue
            try:
                if os.path.getmtime(path) < cutoff.timestamp():
                    os.remove(path)
                    files += 1
            except FileNotFoundError:
                pass
        try:
            if root != UPLOAD_FOLDER and not os.listdir(root) and os.path.getmtime(root) < cutoff.timestamp():
                os.rmdir(root)
        except OSError:
            pass
    counts["files"] = files

    if any(counts.values()):
        logger.info("retention: %s", counts)
    return counts

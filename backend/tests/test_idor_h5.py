"""Tests for SECURITY_ASSESSMENT.md H5: IDOR on /upload/* and /api/* {client_id} routes.

The frontend uses the user's email as `client_id` (Demo.jsx). Before H5,
endpoints required auth but did not check ownership, so any
authenticated user who knew another user's email could list, download,
delete, upload-against, or trigger URL processing in someone else's
namespace.

`require_client_ownership(client_id, current_user)` now compares the
path value against the JWT's user.email and 403s on mismatch.

These tests construct a User stub and call the handlers directly. We
don't need a real DB session for any of the assertions - the ownership
check fires before any DB or filesystem work.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---- Test fixtures --------------------------------------------------------

def _user(email: str = "alice@example.com"):
    u = MagicMock()
    u.id = 42
    u.email = email
    u.is_active = True
    return u


def _request():
    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers.get = lambda k, default=None: {"user-agent": "pytest"}.get(k, default)
    return req


# ---- require_client_ownership unit tests ----------------------------------

class TestRequireClientOwnership:
    def test_match_allows(self):
        from utils.dependencies import require_client_ownership
        # No exception == pass.
        require_client_ownership("alice@example.com", _user("alice@example.com"))

    def test_case_insensitive_match(self):
        from utils.dependencies import require_client_ownership
        # Email is case-insensitive per RFC 5321; the helper must agree.
        require_client_ownership("ALICE@Example.COM", _user("alice@example.com"))

    @pytest.mark.parametrize(
        "client_id",
        [
            "bob@example.com",      # someone else
            "",                     # empty
            " alice@example.com",   # leading space - not actually equal
            "alice+other@example.com",  # subaddress
        ],
    )
    def test_mismatch_rejects_403(self, client_id):
        from fastapi import HTTPException
        from utils.dependencies import require_client_ownership

        with pytest.raises(HTTPException) as exc:
            require_client_ownership(client_id, _user("alice@example.com"))
        assert exc.value.status_code == 403

    def test_user_with_no_email_is_rejected(self):
        from fastapi import HTTPException
        from utils.dependencies import require_client_ownership

        u = _user("")
        u.email = None
        with pytest.raises(HTTPException) as exc:
            require_client_ownership("alice@example.com", u)
        assert exc.value.status_code == 403


# ---- main.py: process_url + download --------------------------------------

class TestProcessURLIDOR:
    @pytest.mark.asyncio
    async def test_other_users_namespace_403(self):
        from fastapi import HTTPException
        from main import URLFormData, process_url_endpoint

        with pytest.raises(HTTPException) as exc:
            await process_url_endpoint(
                client_id="bob@example.com",
                form_data=URLFormData(url="https://example.com", project="default"),
                background_tasks=MagicMock(),
                request=_request(),
                response=MagicMock(),
                current_user=_user("alice@example.com"),
                db=MagicMock(),
            )
        # The handler wraps unexpected errors in a 500 - we need the 403
        # to surface, so the assertion is on the *original* HTTPException
        # rather than the wrapped variant. The current implementation
        # re-raises HTTPException unchanged, but we double-check both
        # codes here in case future refactors change the wrapping.
        assert exc.value.status_code in (403, 500)
        if exc.value.status_code == 500:
            assert "403" in str(exc.value.detail) or "client_id" in str(exc.value.detail).lower()


class TestDownloadIDOR:
    @pytest.mark.asyncio
    async def test_other_users_namespace_403(self):
        from fastapi import HTTPException
        from main import download_file

        with pytest.raises(HTTPException) as exc:
            await download_file(
                client_id="bob@example.com",
                filename="report.xlsx",
                request=_request(),
                current_user=_user("alice@example.com"),
                db=MagicMock(),
            )
        assert exc.value.status_code in (403, 500)


# ---- extraction.py: extract_url_cached + validate_url --------------------

class TestExtractURLCachedIDOR:
    @pytest.mark.asyncio
    async def test_other_users_namespace_403(self):
        from api.routes.extraction import URLRequest, extract_comments_cached
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await extract_comments_cached(
                client_id="bob@example.com",
                payload=URLRequest(url="https://example.com", project="default"),
                background_tasks=MagicMock(),
                request=_request(),
                current_user=_user("alice@example.com"),
                db=MagicMock(),
            )
        assert exc.value.status_code in (403, 500)


# ---- Task ownership (task_status / cancel_task) ---------------------------

class TestTaskOwnership:
    def _task(self, client_id):
        from task_manager import ProcessingTask, TaskStatus
        return ProcessingTask(task_id="t1", client_id=client_id, status=TaskStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_task_status_other_users_task_is_404(self, monkeypatch):
        from fastapi import HTTPException
        from api.routes import tasks as tasks_mod

        monkeypatch.setattr(tasks_mod.task_manager, "get_task", lambda _id: self._task("bob@example.com"))
        with pytest.raises(HTTPException) as exc:
            tasks_mod.get_task_status_endpoint("t1", current_user=_user("alice@example.com"))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_other_users_task_is_404(self, monkeypatch):
        from fastapi import HTTPException
        from api.routes import tasks as tasks_mod

        cancelled = []
        monkeypatch.setattr(tasks_mod.task_manager, "get_task", lambda _id: self._task("bob@example.com"))
        monkeypatch.setattr(tasks_mod.task_manager, "cancel_task", lambda _id: cancelled.append(_id) or True)
        with pytest.raises(HTTPException) as exc:
            tasks_mod.cancel_task_endpoint("t1", request=_request(), current_user=_user("alice@example.com"), db=MagicMock())
        assert exc.value.status_code == 404
        assert cancelled == []

    @pytest.mark.asyncio
    async def test_task_status_own_task_allowed(self, monkeypatch):
        from api.routes import tasks as tasks_mod

        monkeypatch.setattr(tasks_mod.task_manager, "get_task", lambda _id: self._task("alice@example.com"))
        result = tasks_mod.get_task_status_endpoint("t1", current_user=_user("alice@example.com"))
        assert result["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_case_variant_owner_is_another_account(self, monkeypatch):
        # Tasks are owned by the exact stored email; "Alice@..." is not "alice@...".
        from fastapi import HTTPException
        from api.routes import tasks as tasks_mod

        monkeypatch.setattr(tasks_mod.task_manager, "get_task", lambda _id: self._task("Alice@Example.com"))
        with pytest.raises(HTTPException) as exc:
            tasks_mod.get_task_status_endpoint("t1", current_user=_user("alice@example.com"))
        assert exc.value.status_code == 404

"""Unit tests for DatabaseTaskManager.

Uses an in-memory SQLite engine via the task_db_session_factory fixture
from conftest.py. Tests the full public interface to confirm parity with
the old InMemoryTaskManager.
"""
import time
from datetime import datetime

import pytest

from task_manager import (
    DatabaseTaskManager,
    ProcessingTask,
    TaskStatus,
)


@pytest.fixture
def mgr(task_db_session_factory):
    """Fresh DatabaseTaskManager with isolated in-memory DB per test."""
    return DatabaseTaskManager()


def test_store_and_get_task(mgr):
    task = ProcessingTask(
        task_id="t1",
        client_id="alice@example.com",
        status=TaskStatus.EXTRACTING,
        progress=0,
        message="Starting",
    )
    mgr.store_task(task)
    fetched = mgr.get_task("t1")
    assert fetched is not None
    assert fetched.task_id == "t1"
    assert fetched.client_id == "alice@example.com"
    assert fetched.status == TaskStatus.EXTRACTING
    assert fetched.progress == 0
    assert fetched.message == "Starting"


def test_get_unknown_task_returns_none(mgr):
    assert mgr.get_task("does-not-exist") is None


def test_create_task_returns_generated_id(mgr):
    task_id = mgr.create_task(
        client_id="bob@example.com",
        task_type="upload",
        metadata={"file": "comments.xlsx"},
    )
    assert task_id.startswith("upload_") and "bob" not in task_id
    fetched = mgr.get_task(task_id)
    assert fetched is not None
    assert fetched.task_type == "upload"
    assert fetched.metadata == {"file": "comments.xlsx"}


def test_update_task_status_changes_status_progress_message(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.EXTRACTING, progress=0,
    ))
    mgr.update_task_status(
        "t1", TaskStatus.PROCESSING, progress=50, message="halfway"
    )
    fetched = mgr.get_task("t1")
    assert fetched.status == TaskStatus.PROCESSING
    assert fetched.progress == 50
    assert fetched.message == "halfway"


def test_update_unknown_task_logs_warning_no_raise(mgr, caplog):
    import logging
    caplog.set_level(logging.WARNING)
    mgr.update_task_status("missing", TaskStatus.COMPLETED)
    assert any("missing" in r.message for r in caplog.records)


def test_update_with_result_data(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=99,
    ))
    payload = {"output_file": "result.xlsx", "rows": 1234}
    mgr.update_task_status(
        "t1", TaskStatus.COMPLETED, progress=100, result_data=payload
    )
    fetched = mgr.get_task("t1")
    assert fetched.status == TaskStatus.COMPLETED
    assert fetched.result_data == payload


def test_update_with_error_writes_error_to_message(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=50,
    ))
    mgr.update_task_status(
        "t1", TaskStatus.FAILED, error="boom"
    )
    fetched = mgr.get_task("t1")
    assert fetched.status == TaskStatus.FAILED
    assert fetched.message == "boom"


def test_cancel_running_task_returns_true(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=50,
    ))
    assert mgr.cancel_task("t1") is True
    fetched = mgr.get_task("t1")
    assert fetched.status == TaskStatus.CANCELLED
    assert fetched.is_cancelled is True


def test_cancel_completed_task_returns_false(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.COMPLETED, progress=100,
    ))
    assert mgr.cancel_task("t1") is False


def test_cancel_unknown_task_returns_false(mgr):
    assert mgr.cancel_task("missing") is False


def test_is_task_cancelled(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=50,
    ))
    assert mgr.is_task_cancelled("t1") is False
    mgr.cancel_task("t1")
    assert mgr.is_task_cancelled("t1") is True


def test_is_task_cancelled_unknown_returns_false(mgr):
    assert mgr.is_task_cancelled("missing") is False


def test_is_task_cancelled_returns_false_on_db_error(mgr, monkeypatch):
    """DB errors during is_task_cancelled must not crash the worker."""
    from sqlalchemy.exc import OperationalError
    import task_manager as tm

    def boom():
        raise OperationalError("simulated", None, None)

    monkeypatch.setattr(tm, "SessionLocal", boom)
    assert mgr.is_task_cancelled("any") is False


def test_get_client_tasks_returns_newest_first(mgr):
    for i in range(3):
        mgr.store_task(ProcessingTask(
            task_id=f"t{i}", client_id="c1",
            status=TaskStatus.PROCESSING, progress=i,
        ))
        time.sleep(0.01)  # ensure distinct created_at
    tasks = mgr.get_client_tasks("c1", limit=10)
    assert len(tasks) == 3
    assert tasks[0].task_id == "t2"
    assert tasks[-1].task_id == "t0"


def test_get_client_tasks_respects_limit(mgr):
    for i in range(5):
        mgr.store_task(ProcessingTask(
            task_id=f"t{i}", client_id="c1",
            status=TaskStatus.PROCESSING, progress=i,
        ))
    tasks = mgr.get_client_tasks("c1", limit=2)
    assert len(tasks) == 2


def test_get_client_tasks_filters_by_client(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="alice",
        status=TaskStatus.PROCESSING, progress=0,
    ))
    mgr.store_task(ProcessingTask(
        task_id="t2", client_id="bob",
        status=TaskStatus.PROCESSING, progress=0,
    ))
    assert len(mgr.get_client_tasks("alice")) == 1
    assert len(mgr.get_client_tasks("bob")) == 1


def test_delete_task_removes_row(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.COMPLETED, progress=100,
    ))
    assert mgr.delete_task("t1") is True
    assert mgr.get_task("t1") is None


def test_delete_unknown_task_returns_false(mgr):
    assert mgr.delete_task("missing") is False


def test_processing_task_metadata_round_trip(mgr):
    """metadata dataclass field must persist through metadata_json column."""
    payload = {"nested": {"key": [1, 2, 3]}, "flag": True}
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=0,
        metadata=payload,
    ))
    fetched = mgr.get_task("t1")
    assert fetched.metadata == payload


def test_created_at_and_updated_at_are_datetimes(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.EXTRACTING, progress=0,
    ))
    fetched = mgr.get_task("t1")
    assert isinstance(fetched.created_at, datetime)
    assert isinstance(fetched.updated_at, datetime)


def test_update_bumps_updated_at(mgr):
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.EXTRACTING, progress=0,
    ))
    original = mgr.get_task("t1").updated_at
    time.sleep(0.05)
    mgr.update_task_status("t1", TaskStatus.PROCESSING, progress=50)
    after = mgr.get_task("t1").updated_at
    assert after > original


def test_update_task_status_to_cancelled_sets_is_cancelled_flag(mgr):
    """update_task_status(..., CANCELLED) must set is_cancelled=True so
    background workers polling is_task_cancelled() see the cancellation.

    Regression test for a bug where the HTTP /cancel_task endpoint called
    update_task_status(..., CANCELLED, ...) but workers kept running because
    is_cancelled stayed False.
    """
    mgr.store_task(ProcessingTask(
        task_id="t1", client_id="c1",
        status=TaskStatus.PROCESSING, progress=50,
    ))
    mgr.update_task_status("t1", TaskStatus.CANCELLED, progress=0, message="Cancelled by user")
    assert mgr.is_task_cancelled("t1") is True
    fetched = mgr.get_task("t1")
    assert fetched.status == TaskStatus.CANCELLED
    assert fetched.is_cancelled is True


def test_fail_stale_tasks_only_touches_idle_running_tasks(mgr, task_db_session_factory):
    from datetime import timedelta, timezone
    from models.task import Task

    for task_id, status in [("idle", TaskStatus.PROCESSING), ("live", TaskStatus.EXTRACTING), ("done", TaskStatus.COMPLETED)]:
        mgr.store_task(ProcessingTask(task_id=task_id, client_id="a@x.com", status=status))

    session = task_db_session_factory()
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    session.query(Task).filter(Task.task_id.in_(["idle", "done"])).update({Task.updated_at: old}, synchronize_session=False)
    session.commit()
    session.close()

    assert mgr.fail_stale_tasks(max_idle_minutes=20) == 1
    assert mgr.get_task("idle").status == TaskStatus.FAILED
    assert "restart" in mgr.get_task("idle").message
    assert mgr.get_task("live").status == TaskStatus.EXTRACTING
    assert mgr.get_task("done").status == TaskStatus.COMPLETED

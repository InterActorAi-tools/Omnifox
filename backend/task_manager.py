"""Postgres-backed task manager for Omnifox.

Replaces the previous in-memory dict-based implementation. The public
interface (TaskStatus, ProcessingTask, task_manager singleton, and all
manager methods) is preserved so call sites in routes/, services/, and
main.py require no changes.

Tasks persist across Gunicorn workers and container restarts. Retention
is unbounded (audit trail); cleanup_old_tasks() is a no-op.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal
from models.task import Task

logger = logging.getLogger(__name__)


class SmoothProgressTracker:
    """Tracks progress smoothly without sudden jumps.

    Kept verbatim from the previous implementation - external callers
    import smooth_progress from this module.
    """

    def __init__(self):
        self.phase_ranges = {
            "UPLOADING": (0, 5),
            "EXTRACTING": (5, 40),
            "PROCESSING_INIT": (40, 45),
            "PROCESSING": (45, 85),
            "FINALIZING": (85, 95),
            "COMPLETED": (95, 100),
        }

    def get_smooth_progress(self, phase: str, phase_progress: float = 0.5) -> int:
        if phase not in self.phase_ranges:
            return 0
        start, end = self.phase_ranges[phase]
        phase_progress = max(0.0, min(1.0, phase_progress))
        progress = start + (end - start) * phase_progress
        return int(progress)


smooth_progress = SmoothProgressTracker()


def user_error(e: Exception) -> str:
    """Text for a failed task's message. Our own ValueErrors explain what the user
    can fix ("Required 'Text' column not found"); anything else may expose
    internals (paths, SQL, API responses), so it is logged, not shown."""
    return str(e) if isinstance(e, ValueError) else "an unexpected error occurred. Please try again."


class TaskStatus(Enum):
    EXTRACTING = "extracting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_RUNNING_STATUSES = (TaskStatus.EXTRACTING, TaskStatus.PROCESSING)


@dataclass
class ProcessingTask:
    """In-memory representation of a task row.

    Returned by manager read methods. Mutating a returned instance does
    NOT persist - use task_manager.update_task_status(...) instead.
    """

    task_id: str
    client_id: str
    status: TaskStatus
    progress: int = 0
    message: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    result_data: Optional[Dict[str, Any]] = None
    is_cancelled: bool = False
    task_type: str = "generic"
    metadata: Dict[str, Any] = field(default_factory=dict)


def _row_to_dataclass(row: Task) -> ProcessingTask:
    """Convert a SQLAlchemy Task row into a ProcessingTask dataclass."""
    return ProcessingTask(
        task_id=row.task_id,
        client_id=row.client_id,
        status=TaskStatus(row.status),
        progress=row.progress,
        message=row.message or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
        result_data=row.result_data,
        is_cancelled=row.is_cancelled,
        task_type=row.task_type,
        metadata=row.metadata_json or {},
    )


class DatabaseTaskManager:
    """Postgres-backed task store. Same public interface as the old in-memory manager."""

    def store_task(self, task: ProcessingTask) -> None:
        session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            row = Task(
                task_id=task.task_id,
                client_id=task.client_id,
                status=task.status.value,
                progress=task.progress,
                message=task.message,
                task_type=task.task_type,
                metadata_json=task.metadata or {},
                result_data=task.result_data,
                is_cancelled=task.is_cancelled,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            logger.info(f"Stored task: {task.task_id}")
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to store task {task.task_id}: {exc}")
            raise
        finally:
            session.close()

    def create_task(
        self,
        client_id: str,
        task_type: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        task_id = f"{task_type}_{uuid.uuid4().hex}"
        task = ProcessingTask(
            task_id=task_id,
            client_id=client_id,
            status=TaskStatus.EXTRACTING,
            progress=0,
            message="Initializing...",
            task_type=task_type,
            metadata=metadata or {},
        )
        self.store_task(task)
        return task_id

    def get_task(self, task_id: str) -> Optional[ProcessingTask]:
        session = SessionLocal()
        try:
            row = session.query(Task).filter(Task.task_id == task_id).first()
            return _row_to_dataclass(row) if row else None
        except SQLAlchemyError as exc:
            logger.error(f"Failed to get task {task_id}: {exc}")
            return None
        finally:
            session.close()

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        session = SessionLocal()
        try:
            row = session.query(Task).filter(Task.task_id == task_id).first()
            if row is None:
                logger.warning(f"Task not found for update: {task_id}")
                return

            row.status = status.value
            row.updated_at = datetime.now(timezone.utc)
            if status == TaskStatus.CANCELLED:
                row.is_cancelled = True
            if progress is not None:
                row.progress = progress
            if message is not None:
                row.message = message
            if result_data is not None:
                row.result_data = result_data
            if metadata is not None:
                row.metadata_json = metadata
            if error and status == TaskStatus.FAILED:
                row.message = error

            session.commit()
            logger.info(f"Updated task {task_id}: {status.value} ({progress}%)")
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to update task {task_id}: {exc}")
            raise
        finally:
            session.close()

    def cancel_task(self, task_id: str) -> bool:
        session = SessionLocal()
        try:
            row = session.query(Task).filter(Task.task_id == task_id).first()
            if row is None:
                return False
            if TaskStatus(row.status) not in _RUNNING_STATUSES:
                return False
            row.status = TaskStatus.CANCELLED.value
            row.is_cancelled = True
            row.message = "Task cancelled by user"
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"Cancelled task: {task_id}")
            return True
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to cancel task {task_id}: {exc}")
            return False
        finally:
            session.close()

    def is_task_cancelled(self, task_id: str) -> bool:
        session = None
        try:
            session = SessionLocal()
            row = session.query(Task.is_cancelled).filter(
                Task.task_id == task_id
            ).first()
            return bool(row[0]) if row else False
        except SQLAlchemyError as exc:
            logger.warning(f"DB error in is_task_cancelled for {task_id}: {exc}")
            return False
        finally:
            if session is not None:
                session.close()

    def get_client_tasks(self, client_id: str, limit: int = 20) -> List[ProcessingTask]:
        session = SessionLocal()
        try:
            rows = (
                session.query(Task)
                .filter(Task.client_id == client_id)
                .order_by(Task.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dataclass(r) for r in rows]
        finally:
            session.close()

    def delete_task(self, task_id: str) -> bool:
        session = SessionLocal()
        try:
            deleted = (
                session.query(Task).filter(Task.task_id == task_id).delete()
            )
            session.commit()
            if deleted:
                logger.info(f"Deleted task: {task_id}")
            return bool(deleted)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to delete task {task_id}: {exc}")
            return False
        finally:
            session.close()

    def fail_stale_tasks(self, max_idle_minutes: int = 20) -> int:
        """Mark running tasks that stopped updating as failed.

        Jobs run inside the web worker, so a deploy or crash kills them
        without a final status, and the user would otherwise watch a
        frozen progress bar forever. Live jobs update their row at least
        every few seconds, so a long-idle row means the job is gone.
        """
        session = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_idle_minutes)
            count = (
                session.query(Task)
                .filter(
                    Task.status.in_([s.value for s in _RUNNING_STATUSES]),
                    Task.updated_at < cutoff,
                )
                .update(
                    {
                        Task.status: TaskStatus.FAILED.value,
                        Task.message: "Interrupted by a server restart. Please run it again.",
                        Task.updated_at: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            if count:
                logger.warning(f"Marked {count} interrupted task(s) as failed")
            return count
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to fail stale tasks: {exc}")
            return 0
        finally:
            session.close()

    def cleanup_old_tasks(self) -> int:
        """No-op under the keep-forever audit-trail policy."""
        return 0

# Global task manager instance - same name and import path as before.
task_manager = DatabaseTaskManager()

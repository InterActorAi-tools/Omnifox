"""
Task management routes with authentication and logging
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from database import get_db
from utils.dependencies import get_current_user, log_activity, require_task_ownership
from models import User
from task_manager import task_manager, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/task_status/{task_id}")
async def get_task_status_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get task status (authenticated) - matches frontend endpoint"""
    task = task_manager.get_task(task_id)
    require_task_ownership(task, current_user)
    
    # Format response to match what frontend expects
    response = {
        "task_id": task_id,
        "status": task.status.value,
        "progress": task.progress,
        "message": task.message if hasattr(task, 'message') else "Processing...",
    }
    
    # ✅ FIX: Convert timestamp to ISO format string
    if hasattr(task, 'created_at') and task.created_at:
        if isinstance(task.created_at, (int, float)):
            response["created_at"] = datetime.fromtimestamp(task.created_at).isoformat()
        elif hasattr(task.created_at, 'isoformat'):
            response["created_at"] = task.created_at.isoformat()
        else:
            response["created_at"] = str(task.created_at)
    
    if hasattr(task, 'updated_at') and task.updated_at:
        if isinstance(task.updated_at, (int, float)):
            response["updated_at"] = datetime.fromtimestamp(task.updated_at).isoformat()
        elif hasattr(task.updated_at, 'isoformat'):
            response["updated_at"] = task.updated_at.isoformat()
        else:
            response["updated_at"] = str(task.updated_at)
    
    # Add completion status flag for frontend
    response["is_complete"] = task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
    
    # Add result or error
    if task.status == TaskStatus.COMPLETED and hasattr(task, 'result_data') and task.result_data:
        response["data"] = task.result_data
    
    if task.status == TaskStatus.FAILED and hasattr(task, 'error') and task.error:
        response["error"] = task.error
    
    return response

@router.post("/cancel_task/{task_id}")
async def cancel_task_endpoint(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a running task"""
    task = task_manager.get_task(task_id)
    require_task_ownership(task, current_user)
    
    # Only running tasks can be cancelled; finished results stay intact.
    if not task_manager.cancel_task(task_id):
        raise HTTPException(status_code=409, detail="Task is not running")
    
    # Log cancellation
    try:
        log_activity(
            db,
            current_user.id,
            "task_cancelled",
            request.client.host,
            request.headers.get("user-agent", "unknown"),
            {
                "task_id": task_id
            }
        )
    except Exception as e:
        logger.error(f"Failed to log task cancellation: {e}")
    
    logger.info(f"Task {task_id} cancelled by user {current_user.id}")
    
    return {
        "success": True,
        "message": "Task cancelled",
        "task_id": task_id
    }

@router.get("/me/active")
async def get_my_active_task(current_user: User = Depends(get_current_user)):
    """Return the caller's currently running task, if any.

    The client_id is derived from the user's email so it is stable across
    logout/login and across different devices on the same account.
    """
    client_id = current_user.email
    tasks = task_manager.get_client_tasks(client_id, limit=10)
    running = [t for t in tasks if t.status in [TaskStatus.EXTRACTING, TaskStatus.PROCESSING]]

    if not running:
        return {"active_task": None}

    # A running link queue is shown by its own panel, not as one of its links.
    task = next((t for t in running if t.task_type == "url_queue"), running[0])
    return {
        "active_task": {
            "task_id": task.task_id,
            "status": task.status.value,
            "progress": task.progress,
            "message": getattr(task, "message", ""),
            "task_type": getattr(task, "task_type", "generic"),
            "metadata": getattr(task, "metadata", {}),
            "created_at": datetime.fromtimestamp(task.created_at).isoformat()
            if isinstance(task.created_at, (int, float))
            else str(task.created_at),
        }
    }


@router.get("/me/queue")
async def get_my_url_queue(current_user: User = Depends(get_current_user)):
    """Return the caller's latest link queue (POST /api/process_url_queue), if any."""
    tasks = task_manager.get_client_tasks(current_user.email, limit=20)
    queue = next((t for t in tasks if t.task_type == "url_queue"), None)
    if not queue:
        return {"queue": None}
    items = queue.metadata.get("items", [])
    for item in items:
        if item["status"] == "running" and item.get("task_id"):
            running = task_manager.get_task(item["task_id"])
            item["progress"] = running.progress if running else 0
    return {"queue": {"queue_id": queue.task_id, "status": queue.status.value, "items": items}}

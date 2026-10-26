"""File upload route: store an uploaded Excel file and analyse it in the background."""
import os
import time
import uuid
import asyncio
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Form, Request, Response
from sqlalchemy.orm import Session

from config import settings, UPLOAD_FOLDER
from services.processing import ProcessingService
from utils.file_utils import sanitize_filename
from utils.paths import safe_upload_path
from utils.crypto import write_file
from database import get_db
from utils.dependencies import (
    get_current_user, log_activity, log_activity_now, require_client_ownership, require_no_running_task,
)
from routers.projects import require_project_access
from utils import keys
from utils.rate_limit import limiter, USER_OR_IP
from models import User
from task_manager import ProcessingTask, TaskStatus, task_manager, smooth_progress, user_error
from api.dependencies import get_processing_service

logger = logging.getLogger(__name__)
router = APIRouter()

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Strong references to in-flight processing jobs (see process_uploaded_file).
_running_jobs: set[asyncio.Task] = set()

@router.post("/process/{client_id}")
@limiter.limit("30/hour", key_func=USER_OR_IP)  # H2: per-user AI cap
async def process_uploaded_file(
    client_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project: str = Form(default="default"),
    post_context: str = Form(default=""),
    request: Request = None,  # <-- Added for logging
    response: Response = None,  # slowapi writes rate-limit headers here
    current_user: User = Depends(get_current_user),  # <-- Added Auth
    db: Session = Depends(get_db),  # <-- Added DB
    processing_service: ProcessingService = Depends(get_processing_service)
):
    """Process an uploaded Excel file for sentiment analysis with optional post context"""
    try:
        # H5: client_id is derived from the JWT subject - reject any
        # caller attempting to operate against another user's namespace.
        require_client_ownership(client_id, current_user)
        require_project_access(db, current_user, project)
        keys.use_project(db, project)  # a private project's files and results use its own key
        client_id = current_user.email  # canonical: never trust the case/spelling in the URL

        logger.info(f"User {current_user.id} uploaded a file for project {project}")
        if post_context:
            logger.info("📝 Post context provided")

        # Validate client_id format (length + character class + traversal).
        # safe_upload_path() is called again below to actually build the
        # write path; the length check here gives a more specific error.
        if not client_id or len(client_id) < 3:
            raise HTTPException(status_code=400, detail="Invalid client ID")

        require_no_running_task(client_id)

        # M12/H11: same 2 KB post_context cap as the URL endpoints.
        if len(post_context) > 2048:
            raise HTTPException(status_code=422, detail="post_context exceeds 2048 characters")

        # Validate file extension
        # .xlsx only: old .xls files need a reader (xlrd) that is not installed.
        if not file.filename.lower().endswith('.xlsx'):
            raise HTTPException(status_code=400, detail="Only Excel .xlsx files are supported. Please save the file as .xlsx and upload it again.")
        
        # Create unique filename
        timestamp = int(time.time())
        safe_original_filename = sanitize_filename(file.filename)
        unique_filename = f"{timestamp}_{uuid.uuid4().hex[:6]}_{safe_original_filename}"
        
        # Build write paths through safe_upload_path so client_id /
        # filename cannot escape UPLOAD_FOLDER.
        client_folder = safe_upload_path(UPLOAD_FOLDER, client_id)
        os.makedirs(client_folder, exist_ok=True)

        file_path = safe_upload_path(UPLOAD_FOLDER, client_id, unique_filename)
        
        # Read in 1 MB chunks and stop as soon as the size limit is passed.
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content += chunk
            if len(content) > settings.max_file_size:
                break
        file_size = len(content)

        if file_size > settings.max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {settings.max_file_size // (1024*1024)}MB"
            )
        write_file(file_path, bytes(content))
            
        # Log file upload (Auth System)
        log_activity(
            db,
            current_user.id,
            "file_uploaded",
            request.client.host,
            request.headers.get("user-agent", "unknown"),
            {
                "filename": file.filename,
                "file_size_bytes": file_size,
                "project": project,
                "client_id": client_id
            }
        )
        
        # Create task
        task_id = f"upload_{uuid.uuid4().hex}"
        
        task = ProcessingTask(
            task_id=task_id,
            client_id=client_id,
            status=TaskStatus.PROCESSING,
            progress=10,
            message="File uploaded successfully, starting processing...",
            metadata={
                "filename": file.filename,
                "project": project,
                "user_id": current_user.id,
                "post_context": post_context,
            }
        )
        task_manager.store_task(task)
        
        # Log extraction start
        log_activity(
            db,
            current_user.id,
            "extraction_started",
            request.client.host,
            request.headers.get("user-agent", "unknown"),
            {"filename": file.filename, "task_id": task_id}
        )
        
        # Start background processing. Keep a reference until it finishes:
        # the event loop only holds weak references to tasks, so an
        # unreferenced task can be garbage-collected mid-run.
        job = asyncio.create_task(
            process_file_with_progress(
                file_path, client_id, safe_original_filename, task_id, 
                processing_service, task_manager, project, post_context,
                current_user.id, request.client.host, request.headers.get("user-agent", "unknown") # <-- Passed for logging
            )
        )
        _running_jobs.add(job)
        job.add_done_callback(_running_jobs.discard)
        
        return {
            "success": True,
            "task_id": task_id,
            "message": "File uploaded successfully, processing started",
            "status_url": f"/api/tasks/task_status/{task_id}",
            "estimated_time": "2-5 minutes depending on file size",
            "has_context": bool(post_context)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # Log error
        try:
            log_activity(db, current_user.id, "upload_failed", request.client.host, None, {"error": str(e)})
        except: pass
        
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail="Upload failed")

async def process_file_with_progress(
    file_path: str, client_id: str, 
    original_filename: str, task_id: str,
    processing_service: ProcessingService, 
    task_mgr, project: str = "default", 
    post_context: str = "",
    user_id: int = None,       # <-- ADDED
    ip_address: str = None,    # <-- ADDED
    user_agent: str = None     # <-- ADDED
):
    """Background task to process file with smooth progress, context, and logging"""
    try:
        # Phase 1: Initialize
        task_mgr.update_task_status(
            task_id, TaskStatus.PROCESSING,
            smooth_progress.get_smooth_progress('UPLOADING', 1.0),
            "File uploaded, initializing processing..."
        )
        
        result_data = await processing_service.process_file_contents(
            file_path, client_id, original_filename, task_id, task_mgr,
            project, post_context=post_context
        )
        
        # None means the task was cancelled before processing finished.
        if result_data is None:
            return

        # Fix keys for JSON
        if "sentiment_counts" in result_data:
            result_data["sentiment_counts"] = {str(k): v for k, v in result_data["sentiment_counts"].items()}
        if "category_counts" in result_data:
            result_data["category_counts"] = {str(k): v for k, v in result_data["category_counts"].items()}
        
        # Update Task
        task_mgr.update_task_status(
            task_id, TaskStatus.COMPLETED,
            smooth_progress.get_smooth_progress('COMPLETED', 1.0),
            "Processing completed successfully", result_data
        )
        
        # Log Success (Auth System)
        if user_id:
            log_activity_now(
                user_id, "extraction_completed", ip_address, user_agent,
                {
                    "filename": original_filename,
                    "comment_count": result_data.get("total_comments", 0),
                    "task_id": task_id
                }
            )
            
    except Exception as e:
        logger.error(f"Error in background processing: {str(e)}")
        
        # Log Failure (Auth System)
        if user_id:
            log_activity_now(
                user_id, "extraction_failed", ip_address, user_agent,
                {"filename": original_filename, "error": str(e), "task_id": task_id}
            )
            
        task_mgr.update_task_status(task_id, TaskStatus.FAILED, 0, f"Processing failed: {user_error(e)}")
    finally:
        # Data minimisation: the upload is only needed while processing;
        # the result file holds everything the user downloads.
        if os.path.exists(file_path):
            os.remove(file_path)

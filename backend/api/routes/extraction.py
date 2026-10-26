"""URL extraction pipeline behind POST /api/process_url (see main.py)."""
import asyncio
import logging
import uuid
from fastapi import HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal
from utils.dependencies import log_activity, log_activity_now, require_client_ownership
from routers.projects import require_project_access
from utils import keys
from models import User
from cache_service import cache_service
from services.export_service import ExportCommentsService, process_and_cache
from task_manager import task_manager, TaskStatus, ProcessingTask, user_error

logger = logging.getLogger(__name__)

# M12/H11: cap post_context at the API boundary so an attacker cannot
# blow up token costs by submitting a 100 KB context block per call.
# The Gemini service caps again at prompt-build time (MAX_POST_CONTEXT_LEN)
# as defense in depth.
class URLRequest(BaseModel):
    url: str
    project: str
    post_context: str = Field(default="", max_length=2048)

async def extract_comments_cached(
    client_id: str,
    payload: URLRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User,
    db: Session,
):
    """
    Start (or serve from cache) a URL extraction. Called by
    POST /api/process_url, which does auth, ownership and rate limiting;
    this is no longer a route of its own.
    """
    try:
        require_client_ownership(client_id, current_user)  # H5
        require_project_access(db, current_user, payload.project)
        keys.use_project(db, payload.project)  # a private project's files and results use its own key
        client_id = current_user.email  # canonical: never trust the case/spelling in the URL
        logger.info(f"User {current_user.id} processing a URL for project {payload.project}")
        if payload.post_context:
            logger.info("📝 Post context provided")
        
        # Log start of attempt
        try:
            log_activity(
                db,
                current_user.id,
                "url_extraction_started",
                request.client.host,
                request.headers.get("user-agent", "unknown"),
                {
                    "url": payload.url,
                    "project": payload.project,
                    "client_id": client_id,
                    "has_context": bool(payload.post_context)
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log start activity: {log_error}")

        # STEP 1: Quick cache check.
        # Use the disk-validated variant so stale entries pointing at files
        # that have since been deleted (volume wipes, redeploys) auto-evict
        # and fall through to a fresh extraction instead of returning a
        # filename the /api/download endpoint will 404 on.
        cached_entry = cache_service.get_cached_url_validated(
            payload.url, payload.project, client_id
        )
        
        if cached_entry:
            logger.info("Found cached data for URL")
            
            if cached_entry.is_processed and cached_entry.processed_filename:
                # Log cached success
                try:
                    log_activity(
                        db,
                        current_user.id,
                        "url_extraction_completed",
                        request.client.host,
                        request.headers.get("user-agent", "unknown"),
                        {
                            "url": payload.url,
                            "project": payload.project,
                            "comments_count": cached_entry.comments_count,
                            "cached": True,
                            "filename": cached_entry.processed_filename
                        }
                    )
                except Exception:
                    pass

                return {
                    "success": True,
                    "cached": True,
                    "completed": True,
                    "new_filename": cached_entry.processed_filename,
                    "comments_count": cached_entry.comments_count,
                    "message": f"Retrieved cached results ({cached_entry.comments_count} comments)",
                    **(cached_entry.sentiment_data or {})
                }
            elif cached_entry.extracted_filename:
                # Have extracted data, need to process
                task_id = f"process_cached_{uuid.uuid4().hex}"
                
                task = ProcessingTask(
                    task_id=task_id,
                    client_id=client_id,
                    status=TaskStatus.PROCESSING,
                    progress=50,
                    message="Processing cached extracted comments...",
                    metadata={"project": payload.project, "post_context": payload.post_context, "url": payload.url},
                )
                task_manager.store_task(task)
                
                # Process cached extraction in background with context AND user_id
                background_tasks.add_task(
                    process_cached_extraction_async, 
                    task_id, 
                    client_id, 
                    cached_entry.extracted_filename, 
                    cached_entry.url_hash, 
                    current_user.id,        # <-- Pass User ID
                    request.client.host,    # <-- Pass IP
                    request.headers.get("user-agent", "unknown"), # <-- Pass UA
                    payload.post_context,   # <-- Pass Context
                    payload.project,
                )
                
                return {
                    "success": True,
                    "cached": True,
                    "completed": False,
                    "task_id": task_id,
                    "estimated_duration": "2-5 minutes",
                    "message": f"Processing cached data ({cached_entry.comments_count} comments)",
                    "status_url": f"/api/tasks/task_status/{task_id}",
                    "has_context": bool(payload.post_context)
                }
        
        # STEP 2: No cache - start background extraction
        logger.info("No cache found, starting background extraction")
        
        task_id = f"extract_{uuid.uuid4().hex}"
        
        task = ProcessingTask(
            task_id=task_id,
            client_id=client_id,
            status=TaskStatus.EXTRACTING,
            progress=0,
            message="Starting comment extraction...",
            metadata={"project": payload.project, "post_context": payload.post_context, "url": payload.url},
        )
        task_manager.store_task(task)
        
        # Add to background tasks with ALL required info
        background_tasks.add_task(
            background_extract_and_cache_async, 
            task_id, 
            client_id, 
            payload,
            current_user.id,
            request.client.host,
            request.headers.get("user-agent", "unknown")
        )
        
        return {
            "success": True,
            "cached": False,
            "completed": False,
            "task_id": task_id,
            "estimated_duration": "5-20 minutes",
            "message": "Started comment extraction - check status for progress",
            "status_url": f"/api/tasks/task_status/{task_id}",
            "polling_interval": 5,
            "platform_warning": get_platform_warning(payload.url),
            "has_context": bool(payload.post_context)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in extract_comments_cached")
        # Log failure
        try:
            log_activity(
                db,
                current_user.id,
                "url_extraction_failed",
                request.client.host,
                request.headers.get("user-agent", "unknown"),
                {"url": payload.url, "error": str(e)}
            )
        except Exception:
            pass
            
        raise HTTPException(status_code=500, detail="Extraction failed")

def get_platform_warning(url: str) -> str:
    """Get platform-specific timing warnings"""
    url_lower = url.lower()
    if "facebook.com" in url_lower:
        return "Facebook posts may take 10-20 minutes for large comment volumes"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube videos may take 5-15 minutes depending on comment count"
    elif "instagram.com" in url_lower:
        return "Instagram posts typically take 3-10 minutes"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "Twitter posts usually take 2-8 minutes"
    return "Processing time varies by platform and comment volume"

async def background_extract_and_cache_async(
    task_id: str,
    client_id: str,
    payload: URLRequest,
    user_id: int,
    client_host: str,
    user_agent: str
):
    """
    ASYNC BACKGROUND TASK: Handle long-running ExportComments extraction with context
    """
    try:
        export_service = ExportCommentsService()
        
        task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, 5, "Connecting to ExportComments API...")
        
        # Pass user_id and project to service
        await export_service.background_extract_and_cache_v2(
            task_id, 
            client_id, 
            payload, 
            cache_service, 
            task_manager,
            user_id=user_id,     # <-- Pass user_id
            project=payload.project
        )
        
        # Check final status and log
        final_task = task_manager.get_task(task_id)
        if final_task and final_task.status == TaskStatus.COMPLETED and final_task.result_data:
            log_activity_now(
                user_id, "url_extraction_completed", client_host, user_agent,
                {
                    "url": payload.url,
                    "project": payload.project,
                    "comments_count": final_task.result_data.get("total_comments", 0),
                    "cached": False,
                    "filename": final_task.result_data.get("new_filename")
                }
            )
        elif final_task:
            log_activity_now(
                user_id, "url_extraction_failed", client_host, user_agent,
                {"url": payload.url, "error": final_task.message}
            )
        
    except Exception as e:
        logger.error(f"Error in background_extract_and_cache_async: {str(e)}")
        task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, f"Extraction failed: {user_error(e)}")
        log_activity_now(
            user_id, "url_extraction_failed", client_host, user_agent,
            {"url": payload.url, "error": f"Critical task error: {e}"}
        )

async def process_cached_extraction_async(
    task_id: str,
    client_id: str,
    extracted_filename: str,
    url_hash: str,
    user_id: int,
    client_host: str,
    user_agent: str,
    post_context: str = "",
    project: str = "default",
):
    """
    ASYNC BACKGROUND TASK: Process cached extracted file with optional context
    """
    result_data = await process_and_cache(task_id, client_id, extracted_filename, url_hash, project, post_context)
    task = task_manager.get_task(task_id)
    if result_data:
        log_activity_now(
            user_id, "url_processing_completed", client_host, user_agent,
            {"filename": extracted_filename, "comments_count": result_data.get("total_comments", 0), "cached_extraction": True}
        )
    elif task and task.status == TaskStatus.FAILED:
        log_activity_now(
            user_id, "url_processing_failed", client_host, user_agent,
            {"filename": extracted_filename, "error": task.message}
        )


def _save_queue(queue_id: str, items: list, finished: bool = False):
    """Store the queue's per-link state on its task row; also keeps the row fresh for fail_stale_tasks."""
    done = sum(item["status"] not in ("queued", "running") for item in items)
    task = task_manager.get_task(queue_id)
    if task.is_cancelled:
        status = TaskStatus.CANCELLED
    else:
        status = TaskStatus.COMPLETED if finished else TaskStatus.PROCESSING
    task_manager.update_task_status(
        queue_id, status, int(100 * done / len(items)), f"{done} of {len(items)} links done",
        metadata={**task.metadata, "items": items},
    )


async def run_url_queue(queue_id: str, client_id: str, user_id: int, payload: URLRequest, urls: list, request: Request):
    """
    BACKGROUND TASK: run each queued URL through the normal pipeline, one after another.
    Started by POST /api/process_url_queue (see main.py).
    """
    items = [{"url": url, "status": "queued"} for url in urls]
    for item in items:
        if task_manager.is_task_cancelled(queue_id):
            break
        item["status"] = "running"
        _save_queue(queue_id, items)
        try:
            # Short session: only for starting the link, not while it runs.
            with SessionLocal() as db:
                user = db.get(User, user_id)
                jobs = BackgroundTasks()
                result = await extract_comments_cached(
                    client_id, payload.model_copy(update={"url": item["url"]}), jobs, request, user, db
                )
            item["task_id"] = result.get("task_id")
            run = asyncio.ensure_future(jobs())
            while not run.done():
                await asyncio.wait({run}, timeout=10)
                if task_manager.is_task_cancelled(queue_id) and item["task_id"]:
                    task_manager.cancel_task(item["task_id"])
                _save_queue(queue_id, items)
            await run

            task = task_manager.get_task(item["task_id"]) if item["task_id"] else None
            if task is None or task.status == TaskStatus.COMPLETED:
                item["status"] = "done"
                item["filename"] = (task.result_data or {}).get("new_filename") if task else result.get("new_filename")
            else:
                item["status"] = task.status.value  # failed or cancelled
                item["message"] = task.message
        except Exception as e:
            logger.error(f"Queued URL failed in {queue_id}: {e}")
            item["status"] = "failed"
            item["message"] = e.detail if isinstance(e, HTTPException) else user_error(e)

    for item in items:
        if item["status"] == "queued":
            item["status"] = "cancelled"
    _save_queue(queue_id, items, finished=True)

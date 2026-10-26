"""
Combined OmniFox Application - Auth System + Comment Analysis
Merges authentication with main features on single server
"""
import asyncio
import logging
import os
import time
import uuid
from fastapi import FastAPI, Request, Response, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from config import settings, UPLOAD_FOLDER

# 🔥 SIMPLE FIX: Configure logging with production awareness
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 🔥 Simple production logging
if not settings.debug:
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("google_genai").setLevel(logging.ERROR)
    logging.getLogger("google.genai").setLevel(logging.ERROR)
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)
    logging.getLogger("services.gemini_service").setLevel(logging.ERROR)
    logging.getLogger("services.processing").setLevel(logging.WARNING)
    print("📱 Production mode: Minimal logging enabled")
else:
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    print("🔧 Development mode: Full logging enabled")

# Import modules
from cache_service import cache_service
from task_manager import task_manager, TaskStatus, ProcessingTask
from database import SessionLocal, run_migrations, get_db, bootstrap_lock
from bootstrap import run_bootstrap
from utils.dependencies import get_current_user, log_activity, authenticate_sse_cookie, require_client_ownership
from utils.paths import safe_upload_path
from cryptography.fernet import InvalidToken
from utils import keys
from utils.crypto import read_file
from services.privacy import run_retention
from utils.rate_limit import limiter, rate_limit_exceeded_handler, USER_OR_IP
from utils.cookies import ACCESS_TOKEN_COOKIE, CSRF_COOKIE, CSRF_HEADER
from slowapi.errors import RateLimitExceeded
from models import User

# Import ALL routers
from api.routes import api_router
from routers import auth, users, admin, activity_logs, projects, analysis
from routers.projects import require_project_access

# CLOUDFLARE-SAFE Settings
CLOUDFLARE_TIMEOUT_LIMIT = 150
SAFE_REQUEST_TIMEOUT = 120
SSE_CHUNK_INTERVAL = 5

logger = logging.getLogger(__name__)

def _apply_retention():
    db = SessionLocal()
    try:
        run_retention(db)
    finally:
        db.close()


async def cleanup_task():
    """Background housekeeping: fail interrupted jobs, expire the URL cache,
    and apply the data retention policy (at start, then hourly)."""
    last_retention = 0.0
    while True:
        try:
            if time.time() - last_retention >= 3600:
                last_retention = time.time()  # a failed run is retried next hour, not in a tight loop
                await asyncio.to_thread(_apply_retention)
            task_manager.fail_stale_tasks()
            expired_cache = cache_service.cleanup_expired()
            if expired_cache > 0:
                logger.info(f"Cleaned up {expired_cache} expired cache entries")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cleanup task error: {e}")
        try:
            await asyncio.sleep(300)  # always, even after an error
        except asyncio.CancelledError:
            break

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger.info(f"🚀 Starting {settings.app_title} v{settings.app_version}")
    logger.info("🔐 Auth System: Enabled")
    logger.info("🎯 Analysis System: Enabled")
    #logger.info(f"📊 Database: {settings.database_url}")
    
    # Multi-worker safety: serialize schema-create and seed inserts via
    # a Postgres advisory lock. First worker through does the work; others
    # block briefly then see everything already initialized.
    with bootstrap_lock():
        run_migrations()
        run_bootstrap()
    # Jobs that were running when the previous process stopped will never finish.
    task_manager.fail_stale_tasks()
    logger.info("✅ Bootstrap complete (schema, roles, permissions, first-admin check)")
    
    cleanup_task_handle = asyncio.create_task(cleanup_task())
    
    yield
    
    logger.info("Shutting down Combined OmniFox application...")
    cleanup_task_handle.cancel()
    try:
        await cleanup_task_handle
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    debug=settings.debug,
    description="Advanced comment sentiment analysis platform",
    lifespan=lifespan,
    # H4: Swagger and ReDoc UIs are unauthenticated and expose the full
    # API schema. Disable in production; keep available in dev for
    # local exploration.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# H2: rate-limiting middleware. slowapi reads `app.state.limiter` from
# the request scope; each @limiter.limit decorator on a route handler
# enforces per-key counts using that shared limiter.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# H10: CSRF defense for cookie-authenticated mutations.
#
# Browser caller flow: at login the backend sets a JS-readable
# `XSRF-TOKEN` cookie. The frontend reads it via document.cookie and
# echoes the value in an `X-CSRF-Token` header on every state-changing
# request. The middleware compares the header against the cookie -
# any cross-site form attacker can issue a request that carries the
# user's cookies (SameSite=Lax allows it for top-level POSTs in some
# browsers) but cannot read XSRF-TOKEN to construct the matching header.
#
# Pre-auth and refresh routes are exempt because no cookie session
# exists yet at that point in the flow.
_CSRF_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/google",
    "/api/auth/verify-2fa",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/refresh",
)

_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """Reject cookie-authenticated mutations that fail the double-submit check."""
    method = request.method.upper()
    if method in _CSRF_SAFE_METHODS:
        return await call_next(request)

    path = request.url.path
    if any(path.startswith(prefix) for prefix in _CSRF_EXEMPT_PREFIXES):
        return await call_next(request)

    # No cookie session - the request is using Bearer (or no auth at
    # all, which the route handler will reject). Either way, there is
    # no cross-site cookie attack to defend against, so skip CSRF.
    if ACCESS_TOKEN_COOKIE not in request.cookies:
        return await call_next(request)

    cookie_value = request.cookies.get(CSRF_COOKIE)
    header_value = request.headers.get(CSRF_HEADER)
    if not cookie_value or not header_value or cookie_value != header_value:
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF token missing or invalid"},
        )

    return await call_next(request)

# M10: narrow CORS from `allow_methods=["*"]` / `allow_headers=["*"]` to
# the actual set we use. Combined with `allow_credentials=True`, the
# wildcards previously reflected any header back to the client.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", CSRF_HEADER],
)


# H4: response headers that defend against MIME-sniff, clickjacking, mixed
# content, and (eventually) cross-site script injection. Applied to every
# response so static assets, /api/*, and the SPA HTML all get them.
# CSP is intentionally left to the edge (nginx / CDN) per H7 - the
# backend serves the SPA shell but the real script-src allowlist needs
# to know about the deployed asset domain, which the backend should not.
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    if settings.is_production:
        # HSTS only in production. In dev we hit http://localhost which
        # would lock the dev origin to https forever on the developer's
        # browser - exactly the wrong outcome.
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    return response


# Uploads stream up to 50 MB; on a slow connection that legitimately
# takes longer than the general request timeout.
# Uploads stream up to 50 MB; a chat turn or Apply can make several Gemini
# calls. Both may legitimately take longer than SAFE_REQUEST_TIMEOUT.
_TIMEOUT_EXEMPT_PREFIXES = ("/api/upload/process", "/api/analysis/")


@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    if request.url.path.startswith(_TIMEOUT_EXEMPT_PREFIXES):
        return await call_next(request)
    try:
        response = await asyncio.wait_for(call_next(request), timeout=SAFE_REQUEST_TIMEOUT)
        return response
    except asyncio.TimeoutError:
        route = request.scope.get("route")
        logger.error(f"Request timeout: {request.method} {route.path if route else 'unknown route'}")
        return JSONResponse(
            status_code=408,
            content={"error": "Request timeout", "message": "Request took too long to process."}
        )
    except Exception as e:
        logger.error(f"Middleware error: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

# 🔥 Include ALL routers
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(api_router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(activity_logs.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")

# SSE Progress Endpoint
@app.get("/api/progress/{client_id}")
async def get_progress_stream(
    client_id: str,
    request: Request,
    task_id: str = None,
):
    """Stream task progress as Server-Sent Events.

    Auth: H10 moves the access token to an HttpOnly cookie that browsers
    attach to EventSource requests automatically (same-origin or with
    `withCredentials: true` on cross-origin). The pre-H10 query-string
    fallback (`?token=<jwt>`) is gone - it was a token-in-URL leak risk
    (server logs, browser history, referer headers). We then enforce
    that `client_id` matches the requesting user's email, which is how
    the frontend addresses task streams today. Anyone calling with a
    client_id they don't own gets 403.

    Accepts an optional ?task_id= query param so the frontend can pin the
    stream to a specific task rather than relying on "most recent running
    task", which can flip on reconnect.
    """
    # Own short session: a request-scoped one would stay open (idle in
    # transaction, holding a pooled connection) for the whole stream.
    db = SessionLocal()
    try:
        user = authenticate_sse_cookie(request, db)
        user_email = user.email
    finally:
        db.close()

    # The frontend addresses task streams by the user's email, so we accept
    # the request only when client_id matches. Compared case-insensitive so
    # browser URL casing differences don't accidentally lock a user out.
    if client_id.lower() != user_email.lower():
        raise HTTPException(status_code=403, detail="Forbidden")
    client_id = user_email

    async def event_generator():
        last_sent = -1
        # Allow up to 30 minutes for large files; the Cloudflare proxy limit
        # is per-request — the frontend reconnects automatically if needed.
        max_iterations = (30 * 60) // SSE_CHUNK_INTERVAL
        iteration = 0

        try:
            while iteration < max_iterations:
                try:
                    # Prefer the pinned task_id when provided
                    if task_id:
                        task = task_manager.get_task(task_id)
                        # Only stream tasks owned by this user.
                        if task and task.client_id != user_email:
                            task = None
                        # Cancelled elsewhere, or deleted: tell the page to stop waiting.
                        if not task:
                            yield "data: -1\n\n"
                            break
                        if task.status == TaskStatus.CANCELLED:
                            yield "data: cancelled\n\n"
                            break
                        client_tasks = [task] if task else []
                        running_tasks = [task] if task and task.status in [TaskStatus.EXTRACTING, TaskStatus.PROCESSING] else []
                    else:
                        client_tasks = task_manager.get_client_tasks(client_id, limit=5)
                        running_tasks = [t for t in client_tasks if t.status in [TaskStatus.EXTRACTING, TaskStatus.PROCESSING]]

                    if running_tasks:
                        current_task = running_tasks[0]
                        current_progress = current_task.progress

                        if current_progress != last_sent:
                            yield f"data: {current_progress}\n\n"
                            last_sent = current_progress

                        # The status may have changed to COMPLETED/FAILED between
                        # our two reads — handle that here too.
                        if current_task.status == TaskStatus.COMPLETED:
                            yield "data: 100\n\n"
                            break
                        elif current_task.status == TaskStatus.FAILED:
                            yield "data: -1\n\n"
                            break
                    else:
                        # No active task found — check whether one recently finished.
                        if client_tasks:
                            most_recent = client_tasks[0]
                            if most_recent.status == TaskStatus.COMPLETED:
                                yield "data: 100\n\n"
                                break
                            elif most_recent.status == TaskStatus.FAILED:
                                yield "data: -1\n\n"
                                break
                        # Nothing running yet (task may still be queuing) or task
                        # not found — send last known progress only if we have one,
                        # never send -1 speculatively.
                        if last_sent >= 0:
                            yield f"data: {last_sent}\n\n"

                    await asyncio.sleep(SSE_CHUNK_INTERVAL)
                    iteration += 1
                except Exception as e:
                    logger.error(f"Error in SSE stream: {e}")
                    yield "data: -1\n\n"
                    break

            if iteration >= max_iterations:
                yield "data: timeout\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# 🔥 UPDATED MODEL: Now includes post_context
# M12/H11: 2 KB cap on post_context applied at the API boundary so an
# attacker cannot inflate Gemini token usage with a giant context block.
class URLFormData(BaseModel):
    url: str
    project: str = "default"
    post_context: str = Field(default="", max_length=2048)

@app.post("/api/process_url/{client_id}")
@limiter.limit("30/hour", key_func=USER_OR_IP)  # H2: per-user AI cap
async def process_url_endpoint(
    client_id: str,
    form_data: URLFormData,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,  # slowapi writes rate-limit headers here
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process URL endpoint with immediate response"""
    try:
        require_client_ownership(client_id, current_user)  # H5
        client_id = current_user.email  # canonical: never trust the case/spelling in the URL
        # Enforce one active process per user
        existing = task_manager.get_client_tasks(current_user.email, limit=5)
        running = [t for t in existing if t.status in [TaskStatus.EXTRACTING, TaskStatus.PROCESSING]]
        if running:
            raise HTTPException(
                status_code=409,
                detail=f"A processing task is already running ({running[0].task_id}). Please wait for it to complete or cancel it first."
            )

        # Forward to the extraction service
        from api.routes.extraction import extract_comments_cached
        
        result = await extract_comments_cached(
            client_id, 
            form_data, 
            background_tasks,
            request,
            current_user,
            db
        )
        return result

    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in process_url_endpoint")
        raise HTTPException(status_code=500, detail="URL processing failed")

MAX_QUEUED_URLS = 10

class URLQueueData(BaseModel):
    urls: list[str] = Field(min_length=1)
    project: str = "default"
    post_context: str = Field(default="", max_length=2048)

# 3 lists of at most 10 links an hour keeps the same AI cap as process_url (H2).
@app.post("/api/process_url_queue/{client_id}")
@limiter.limit("3/hour", key_func=USER_OR_IP)
async def process_url_queue_endpoint(
    client_id: str,
    form_data: URLQueueData,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,  # slowapi writes rate-limit headers here
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Queue a list of URLs; they are processed one after another in the background."""
    require_client_ownership(client_id, current_user)  # H5
    client_id = current_user.email
    urls = list(dict.fromkeys(u.strip() for u in form_data.urls if u.strip()))
    if not urls or len(urls) > MAX_QUEUED_URLS:
        raise HTTPException(status_code=400, detail=f"Add between 1 and {MAX_QUEUED_URLS} links.")
    require_project_access(db, current_user, form_data.project)
    keys.use_project(db, form_data.project)  # the queue and its links' results use a private project's key
    existing = task_manager.get_client_tasks(client_id, limit=5)
    if any(t.status in [TaskStatus.EXTRACTING, TaskStatus.PROCESSING] for t in existing):
        raise HTTPException(status_code=409, detail="A processing task is already running. Please wait for it to complete or cancel it first.")

    from api.routes.extraction import URLRequest, run_url_queue
    queue_id = f"url_queue_{uuid.uuid4().hex}"
    items = [{"url": url, "status": "queued"} for url in urls]
    task_manager.store_task(ProcessingTask(
        task_id=queue_id,
        client_id=client_id,
        status=TaskStatus.PROCESSING,
        message=f"0 of {len(urls)} links done",
        task_type="url_queue",
        metadata={"project": form_data.project, "items": items},
    ))
    payload = URLRequest(url="", project=form_data.project, post_context=form_data.post_context)
    background_tasks.add_task(run_url_queue, queue_id, client_id, current_user.id, payload, urls, request)
    return {"queue_id": queue_id, "status": "processing", "items": items}

# File download endpoint
@app.get("/api/download/{client_id}/{filename}")
async def download_file(
    client_id: str, 
    filename: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download processed file"""
    try:
        require_client_ownership(client_id, current_user)  # H5
        client_id = current_user.email  # canonical: never trust the case/spelling in the URL
        # Reject traversal/special chars before touching the filesystem;
        # also resolves through symlinks and asserts the result is inside
        # UPLOAD_FOLDER.
        file_path = safe_upload_path(UPLOAD_FOLDER, client_id, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        try:
            content = read_file(file_path)
        except InvalidToken:  # a private project this session cannot unlock
            raise HTTPException(status_code=403, detail=keys.LOCKED)
        file_size = len(content)

        # Log download
        try:
            log_activity(db, current_user.id, "file_downloaded", request.client.host, 
                        request.headers.get("user-agent", "unknown"),
                        {"filename": filename, "size": file_size})
        except: pass
        
        return Response(
            content=content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        raise HTTPException(status_code=500, detail="Download failed")

@app.get("/health")
def health_check():
    """Liveness probe for the Docker healthcheck. Deliberately reveals nothing."""
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        timeout_keep_alive=30
    )
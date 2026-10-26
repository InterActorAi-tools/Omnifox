"""Chat about a finished analysis and apply the changes it proposes."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from config import UPLOAD_FOLDER
from database import get_db
from models import ChatMessage, Task, User
from task_manager import TaskStatus
from services import chat
from services.analysis import Analysis
from services.gemini_service import get_gemini
from utils import keys
from utils.dependencies import get_current_user
from utils.paths import safe_upload_path
from utils.rate_limit import USER_OR_IP, limiter

router = APIRouter(prefix="/analysis", tags=["Analysis chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=chat.MAX_MESSAGE_LEN)


# One apply at a time per result, so two applies cannot overwrite each other.
# key -> [lock, number of requests using it]; the entry is removed only when
# no request holds or waits for it (a waiter may not have woken up yet).
_apply_locks: dict = {}


@asynccontextmanager
async def _result_lock(key):
    entry = _apply_locks.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            _apply_locks.pop(key, None)


async def _analysis(db: Session, user: User, filename: str) -> Analysis:
    if not os.path.exists(safe_upload_path(UPLOAD_FOLDER, user.email, filename)):
        raise HTTPException(status_code=404, detail="This result is no longer available.")
    # Decrypting and parsing the report is blocking work: keep it off the event loop.
    try:
        analysis = await asyncio.to_thread(Analysis, db, user.email, filename)
    except InvalidToken:
        raise HTTPException(status_code=403, detail=keys.LOCKED)
    keys.use_project(db, analysis.project)  # chat and edits stay under a private project's key
    return analysis


def _pending_proposal(db: Session, user: User, filename: str, proposal_id: int) -> ChatMessage:
    proposal = db.get(ChatMessage, proposal_id)
    if (not proposal or proposal.role != "proposal" or proposal.client_id != user.email
            or proposal.filename != filename or proposal.content.get("status") != "pending"):
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.get("")
def list_results(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """My results from the last 30 days, newest first (works on any device)."""
    tasks = (db.query(Task)
             .filter(Task.client_id == current_user.email, Task.status == TaskStatus.COMPLETED.value)
             .order_by(Task.created_at.desc()).all())
    results, seen = [], set()
    for task in tasks:
        data, meta = task.result_data or {}, task.metadata_json or {}
        filename = data.get("new_filename")
        if not filename or filename in seen or not os.path.exists(safe_upload_path(UPLOAD_FOLDER, current_user.email, filename)):
            continue
        seen.add(filename)
        results.append({
            "filename": filename,
            "created_at": task.created_at,
            "source": meta.get("filename") or meta.get("url") or "Post link",
            "project": meta.get("project", ""),
            "total_comments": data.get("total_comments", 0),
            "sentiment_counts": data.get("sentiment_counts", {}),
        })
    return results


@router.get("/{filename}")
async def get_result(filename: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (await _analysis(db, current_user, filename)).result()


@router.get("/{filename}/chat")
def get_chat(filename: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The conversation so far, with proposals and their status."""
    return [{"id": m.id, "role": m.role, **m.content} for m in chat.history(db, current_user.email, filename)]


@router.post("/{filename}/chat")
@limiter.limit("20/minute", key_func=USER_OR_IP)
async def send_message(
    filename: str,
    data: ChatRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analysis = await _analysis(db, current_user, filename)
    return await chat.reply(db, get_gemini(), analysis, data.message.strip())


@router.post("/{filename}/proposals/{proposal_id}/apply")
@limiter.limit("30/minute", key_func=USER_OR_IP)
async def apply_proposal(
    filename: str, proposal_id: int, request: Request, response: Response,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _pending_proposal(db, current_user, filename, proposal_id)  # 404 before any lock is created
    async with _result_lock((current_user.email, filename)):
        db.expire_all()  # another apply may have finished while we waited
        proposal = _pending_proposal(db, current_user, filename, proposal_id)
        return await chat.apply_proposal(get_gemini(), await _analysis(db, current_user, filename), proposal)


@router.post("/{filename}/proposals/{proposal_id}/dismiss")
def dismiss_proposal(
    filename: str, proposal_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    proposal = _pending_proposal(db, current_user, filename, proposal_id)
    proposal.content = {**proposal.content, "status": "dismissed"}
    db.commit()
    return {"status": "dismissed"}

"""Rate limiting (H2).

Defines a single `slowapi.Limiter` instance and the key functions every
sensitive endpoint should use. Importing this module is side-effect-free
(no Redis connection, no global state mutation) so routers can decorate
their handlers without pulling in main.py.

Wire-up in main.py:

    from utils.rate_limit import limiter, rate_limit_exceeded_handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

Decorate routes:

    from utils.rate_limit import limiter, USER_OR_IP

    @router.post("/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...): ...

    @router.post("/process_url/{client_id}")
    @limiter.limit("30/hour", key_func=USER_OR_IP)
    async def process_url(request: Request, ...): ...

slowapi requires the decorated handler to accept `request: Request` as
a parameter so the limiter can read the client identity. Every endpoint
in this codebase already does.

Limits are intentionally conservative defaults. They can be overridden
per-endpoint and (later) sourced from settings. The default storage is
in-process memory - fine for a single gunicorn worker. With multiple
workers, counts diverge across workers, which means the practical limit
is `limit * worker_count` rather than `limit`. Acceptable for brute-force
defense at the 5/min scale we use; if we ever need precise enforcement,
swap to a Redis backend by passing `storage_uri="redis://...""`.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from utils.cookies import ACCESS_TOKEN_COOKIE
from utils.security import verify_token


def _user_id_from_request(request: Request) -> str | None:
    """Best-effort extraction of the JWT subject from an authed request.

    Returns the user id as a string, or None if no valid token was
    presented. We never reject here - this is purely the rate-limit
    bucket key; auth enforcement still happens in `get_current_user`.
    """
    # H10: browsers authenticate with the access_token cookie; Bearer is
    # the fallback for non-browser callers.
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return None
        token = auth.split(" ", 1)[1].strip()
    payload = verify_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    return str(user_id) if user_id is not None else None


def user_or_ip_key(request: Request) -> str:
    """Key by authenticated user id when available, IP otherwise.

    AI endpoints care about per-user cost, not per-IP - office NAT would
    otherwise share a single bucket across the whole company. Falling
    back to IP for unauthenticated calls keeps the same key available
    for routes that mix auth/anon (none today, but future-proof).
    """
    user_id = _user_id_from_request(request)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


# Public aliases. Routers import these symbols and the choice of key
# function is part of the route's documented behaviour.
USER_OR_IP = user_or_ip_key
IP_ONLY = get_remote_address

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a JSON 429 instead of slowapi's default text/plain response.

    The frontend's fetch wrapper expects JSON for error bodies and would
    otherwise log a parse error on top of the 429.
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down and try again shortly.",
        },
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )

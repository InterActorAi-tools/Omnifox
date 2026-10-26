"""Auth cookie management (H10).

Three cookies are issued at login (and refreshed on /auth/refresh):

  access_token   - HttpOnly, Secure (prod), SameSite=Lax, Path=/
                   Carries the JWT access token. The JS layer NEVER sees
                   this value. Browser-only XHR / SSE / EventSource
                   automatically attach it.
  refresh_token  - HttpOnly, Secure (prod), SameSite=Lax,
                   Path=/api/auth   (narrows the cookie surface so only
                   the refresh endpoint receives it)
                   Carries the long-lived refresh token. The JS layer
                   NEVER sees this value.
  XSRF-TOKEN     - readable from JS by design (CSRF double-submit).
                   Random per-session token. The JS layer reads this
                   cookie and echoes its value in an `X-CSRF-Token`
                   header on every state-changing request. The CSRF
                   middleware compares the header against the cookie -
                   any cross-site form attacker cannot read the cookie
                   to construct the matching header.

`set_auth_cookies` is called from /auth/login, /auth/register,
/auth/verify-2fa, /auth/google, and /auth/refresh.
`clear_auth_cookies` is called from /auth/logout.

Cookie attribute rationale:
- HttpOnly:    blocks JS read access on the token cookies. Even with
               XSS, the attacker cannot exfiltrate the tokens.
- Secure:      only sent over https. Disabled in dev (`settings.is_production`
               is False) so http://localhost works.
- SameSite=Lax: cookies sent on top-level GET navigation from external
               sites (so deep links / email links to the SPA still
               carry the user's session), blocked on cross-site POSTs.
               Combined with the CSRF double-submit, this defeats CSRF.
- Path:        access_token is Path=/ because every API route needs it;
               refresh_token narrows to Path=/api/auth so other routes
               don't receive it at all.
- Max-Age:     matches the JWT exp claim.
"""
from __future__ import annotations

import secrets

from fastapi import Response

from config import settings


# Cookie names. Centralized constants so the auth router, the CSRF
# middleware, and the test suite all agree on the spelling.
ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_COOKIE = "XSRF-TOKEN"
CSRF_HEADER = "X-CSRF-Token"
PENDING_2FA_COOKIE = "pending_2fa"
# Unlocks the user's private-project key for this session (utils/keys.py).
DATA_KEY_COOKIE = "data_key"

# Refresh token cookie is scoped to the refresh endpoint only. /api/auth
# matches all auth endpoints; if we ever want even tighter scoping the
# right path is /api/auth/refresh, but Set-Cookie Path matches by
# prefix and we also need the cookie sent to /auth/logout to clear it.
REFRESH_TOKEN_PATH = "/api/auth"


def _common_kwargs() -> dict:
    """Cookie attributes shared by every auth-related cookie we set."""
    return {
        "secure": settings.is_production,
        "samesite": "lax",
        "domain": None,  # default: cookie locked to the response host
    }


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> str:
    """Set the access + refresh + CSRF cookies on `response`.

    Returns the freshly-minted CSRF token so the caller can log/audit
    if it wants. The browser stores it under the `XSRF-TOKEN` cookie
    (JS-readable), and the frontend echoes it back as `X-CSRF-Token`
    on mutating requests.

    The caller is responsible for inserting `response` into the route
    return path (FastAPI handles this when a handler accepts a
    `response: Response` parameter and mutates it before return).
    """
    common = _common_kwargs()

    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        httponly=True,
        path="/",
        max_age=settings.access_token_expire_minutes * 60,
        **common,
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        httponly=True,
        path=REFRESH_TOKEN_PATH,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        **common,
    )

    # CSRF token: not HttpOnly (frontend must read it), random per call.
    # Bound to the same TTL as the refresh token so a single login
    # produces a CSRF that survives access-token rotations.
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        path="/",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        **common,
    )
    return csrf_token


def set_data_key_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        DATA_KEY_COOKIE,
        secret,
        httponly=True,
        path="/",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        **_common_kwargs(),
    )


def clear_auth_cookies(response: Response) -> None:
    """Drop all three auth cookies. Called from /auth/logout."""
    # delete_cookie writes Max-Age=0 + an expired Expires for the named
    # cookie. The `path` MUST match what was used at set time for the
    # browser to accept the deletion.
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path=REFRESH_TOKEN_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(DATA_KEY_COOKIE, path="/")


def set_pending_2fa_cookie(response: Response, token: str) -> None:
    """Bind the 2FA step to a completed password/Google step."""
    response.set_cookie(
        PENDING_2FA_COOKIE,
        token,
        httponly=True,
        path=REFRESH_TOKEN_PATH,
        max_age=5 * 60,
        **_common_kwargs(),
    )


def clear_pending_2fa_cookie(response: Response) -> None:
    response.delete_cookie(PENDING_2FA_COOKIE, path=REFRESH_TOKEN_PATH)

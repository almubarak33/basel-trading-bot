"""Shared-secret authentication for the API.

Everything behind `/api` can move money-adjacent state — enabling the auto
engine, submitting orders, flattening positions — so the API is closed by
default. If no `API_TOKEN` is configured one is generated at startup and logged,
which keeps local development working without ever leaving the bot open.

Clients authenticate once with the token and then hold an HttpOnly,
SameSite=Strict session cookie, so the token itself is never readable from
JavaScript and cross-site requests cannot ride the session.
"""
from __future__ import annotations
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field

from fastapi import Cookie, Header, HTTPException, Request, Response

from .config import settings

log = logging.getLogger("basel.auth")

COOKIE_NAME = "basel_session"
SESSION_TTL_SECONDS = 12 * 3600
# Login throttling: a short lockout makes online guessing impractical without
# getting in the way of someone who simply mistyped.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


def _resolve_token() -> tuple[str, bool]:
    configured = (settings.api_token or "").strip()
    if configured:
        return configured, False
    generated = secrets.token_urlsafe(24)
    log.warning(
        "API_TOKEN is not set. Generated a temporary token for this process:\n"
        "    %s\n"
        "It changes on every restart — set API_TOKEN in the environment for a stable login.",
        generated,
    )
    return generated, True


API_TOKEN, TOKEN_IS_EPHEMERAL = _resolve_token()

# Sessions are opaque random ids kept in memory; a restart signs everyone out.
_SESSIONS: dict[str, float] = {}


@dataclass
class _Attempts:
    count: int = 0
    locked_until: float = 0.0


_ATTEMPTS: dict[str, _Attempts] = {}


def _client_key(request: Request) -> str:
    """Identify the caller for throttling. Hashed so logs/memory hold no raw IPs."""
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode()).hexdigest()[:16]


def _prune() -> None:
    now = time.time()
    for token, expires in list(_SESSIONS.items()):
        if expires <= now:
            _SESSIONS.pop(token, None)


def is_valid_session(session: str | None) -> bool:
    if not session:
        return False
    _prune()
    return session in _SESSIONS


def create_session() -> str:
    _prune()
    session = secrets.token_urlsafe(32)
    _SESSIONS[session] = time.time() + SESSION_TTL_SECONDS
    return session


def destroy_session(session: str | None) -> None:
    if session:
        _SESSIONS.pop(session, None)


def throttle_state(request: Request) -> float:
    """Seconds remaining on a lockout, or 0 when the caller may try again."""
    record = _ATTEMPTS.get(_client_key(request))
    if not record:
        return 0.0
    return max(0.0, record.locked_until - time.time())


def register_failure(request: Request) -> None:
    record = _ATTEMPTS.setdefault(_client_key(request), _Attempts())
    record.count += 1
    if record.count >= MAX_ATTEMPTS:
        record.locked_until = time.time() + LOCKOUT_SECONDS
        record.count = 0


def clear_failures(request: Request) -> None:
    _ATTEMPTS.pop(_client_key(request), None)


def token_matches(candidate: str) -> bool:
    """Constant-time comparison so a wrong token leaks nothing through timing."""
    return secrets.compare_digest((candidate or "").strip(), API_TOKEN)


def set_session_cookie(response: Response, request: Request, session: str) -> None:
    response.set_cookie(
        COOKIE_NAME, session,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        # Browsers reject Secure cookies over plain http, which would break a
        # local run, so mirror whatever scheme the request arrived on.
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def require_auth(
    basel_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Dependency guarding every protected route.

    Accepts either the session cookie or a bearer token, so scripts and the
    dashboard can both talk to the API.
    """
    if is_valid_session(basel_session):
        return
    if authorization and authorization.lower().startswith("bearer "):
        if token_matches(authorization[7:]):
            return
    raise HTTPException(401, "Authentication required.")

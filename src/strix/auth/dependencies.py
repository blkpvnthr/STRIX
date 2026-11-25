"""FastAPI authentication dependencies.

``require_user`` is attached to every protected route. It reads the bearer token,
verifies it with the app's :class:`~strix.auth.supabase_jwt.JWTVerifier`, and
returns the :class:`~strix.auth.supabase_jwt.AuthUser`. Unauthenticated or
invalid requests get ``401`` and never reach the research engine — so no
anonymous caller can ever spend OpenAI credit or read another user's research.

For offline development without a Supabase project, setting ``STRIX_AUTH_MODE=dev``
yields a single fixed development user. This is explicit and off by default; in
production a real verifier is required and a missing one returns ``503`` rather
than silently allowing access.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import HTTPException

from strix.auth.supabase_jwt import AuthError, AuthUser, JWTVerifier

#: The fixed principal used only when STRIX_AUTH_MODE=dev.
DEV_USER = AuthUser(
    id="00000000-0000-0000-0000-000000000000",
    email="dev@localhost",
    role="authenticated",
    claims={"sub": "00000000-0000-0000-0000-000000000000", "dev": True},
)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    return header[7:].strip()


def require_user(request: Request) -> AuthUser:
    """Resolve the authenticated caller, or raise 401/503."""
    verifier: JWTVerifier | None = getattr(request.app.state, "verifier", None)
    dev_mode: bool = bool(getattr(request.app.state, "auth_dev_mode", False))

    if verifier is None:
        if dev_mode:
            return DEV_USER
        raise HTTPException(status_code=503, detail="authentication is not configured")

    token = _bearer_token(request)
    try:
        return verifier.verify(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def ensure_owns(user: AuthUser, owner_id: str) -> None:
    """Enforce resource ownership; raise 404 (not 403) to avoid leaking
    existence of another user's resource."""
    if user.id != owner_id:
        raise HTTPException(status_code=404, detail="not found")

"""Server-side authentication for the hosted STRIX research API.

Authentication is Supabase Auth: the browser obtains a JWT from Supabase and
sends it as ``Authorization: Bearer <jwt>``. This package verifies that token
*server-side* and resolves it to an :class:`AuthUser`. Authorization decisions
use only the cryptographically-signed ``sub`` (and ``app_metadata``), never the
user-editable ``user_metadata`` — the Supabase security rule.

- :mod:`strix.auth.supabase_jwt` — token verification (asymmetric JWKS + legacy
  HS256), framework-independent and unit-testable.
- :mod:`strix.auth.dependencies` — the FastAPI ``require_user`` dependency and
  ownership helpers.
"""

from __future__ import annotations

from strix.auth.supabase_jwt import AuthConfigError, AuthError, AuthUser, JWTVerifier

__all__ = ["AuthConfigError", "AuthError", "AuthUser", "JWTVerifier"]

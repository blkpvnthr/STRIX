"""Supabase JWT verification (framework-independent).

Supports both signing schemes Supabase projects use:

- **Asymmetric (current default)** — the project publishes a JWKS at
  ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``; tokens are RS256/ES256 and
  verified against the fetched public key (cached by :class:`PyJWKClient`).
- **Legacy HS256** — a shared ``SUPABASE_JWT_SECRET`` symmetric key.

Verification enforces signature, expiry, and ``aud == "authenticated"``. Only the
signed ``sub`` claim is trusted for identity; ``user_metadata`` is deliberately
ignored for authorization because it is user-editable in Supabase. The verifier
is constructed once and reused (warm serverless instances keep the JWKS cache).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient

#: The audience Supabase stamps on authenticated-user access tokens.
_EXPECTED_AUDIENCE = "authenticated"


class AuthError(Exception):
    """A presented token was missing, malformed, expired, or untrusted."""


class AuthConfigError(Exception):
    """Authentication is not configured (no JWKS URL and no JWT secret)."""


@dataclass(frozen=True)
class AuthUser:
    """A verified caller. ``id`` is the Supabase ``sub`` (a UUID string).

    ``institution_id`` is the STRIX instance the caller is bound to, read ONLY from
    the admin-controlled (signed) ``app_metadata`` — never from user-editable
    ``user_metadata``. ``None`` means the token carries no instance binding.
    """

    id: str
    email: str | None
    role: str | None
    claims: Mapping[str, Any]
    institution_id: str | None = None


class JWTVerifier:
    """Verifies Supabase access tokens.

    Prefer :meth:`from_env`. Pass ``hs256_secret`` for the legacy symmetric
    scheme, or ``jwks_url`` for the asymmetric scheme. ``jwks_client`` may be
    injected in tests. If both are configured, HS256 is tried only when the token
    header advertises it, so a single verifier can serve a mixed fleet.
    """

    def __init__(
        self,
        *,
        hs256_secret: str | None = None,
        jwks_url: str | None = None,
        jwks_client: PyJWKClient | None = None,
        audience: str | None = _EXPECTED_AUDIENCE,
        issuer: str | None = None,
        leeway_seconds: int = 10,
    ) -> None:
        if not hs256_secret and not jwks_url and jwks_client is None:
            raise AuthConfigError(
                "authentication is not configured: set SUPABASE_JWT_SECRET "
                "(legacy HS256) or SUPABASE_URL (asymmetric JWKS)"
            )
        self._secret = hs256_secret
        self._audience = audience
        self._issuer = issuer
        self._leeway = leeway_seconds
        self._jwks_client = jwks_client or (PyJWKClient(jwks_url) if jwks_url else None)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> JWTVerifier:
        """Build from environment. Asymmetric is preferred; HS256 is the
        fallback. When ``SUPABASE_URL`` is set the issuer is derived and ENFORCED.
        Raises :class:`AuthConfigError` if neither scheme is present."""
        secret = (env.get("SUPABASE_JWT_SECRET") or "").strip() or None
        url = (env.get("SUPABASE_URL") or "").strip().rstrip("/")
        jwks_url = f"{url}/auth/v1/.well-known/jwks.json" if url else None
        # Prefer an explicit SUPABASE_JWT_ISSUER (so even a secret-only legacy
        # deployment can still pin + enforce the issuer), else derive it from the
        # project URL. A secret-only config with neither set does not enforce issuer.
        explicit_issuer = (env.get("SUPABASE_JWT_ISSUER") or "").strip() or None
        issuer = explicit_issuer or (f"{url}/auth/v1" if url else None)
        return cls(hs256_secret=secret, jwks_url=jwks_url, issuer=issuer)

    def verify(self, token: str) -> AuthUser:
        """Verify ``token`` and return the caller, or raise :class:`AuthError`."""
        token = (token or "").strip()
        if not token:
            raise AuthError("missing bearer token")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise AuthError("malformed token") from exc

        alg = header.get("alg", "")
        try:
            if alg == "HS256":
                claims = self._verify_hs256(token)
            else:
                claims = self._verify_asymmetric(token, alg)
        except AuthError:
            raise
        except InvalidTokenError as exc:
            raise AuthError(f"token rejected: {exc}") from exc
        except Exception as exc:
            raise AuthError("token could not be verified") from exc

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthError("token has no subject")
        return AuthUser(
            id=sub,
            email=_opt_str(claims.get("email")),
            role=_opt_str(claims.get("role")),
            claims=claims,
            institution_id=_institution_from_claims(claims),
        )

    # -- internals ---------------------------------------------------------

    def _decode_kwargs(self) -> dict[str, Any]:
        """Shared jwt.decode options: enforce exp/sub, and iss when an issuer is set."""
        required = ["exp", "sub"]
        kwargs: dict[str, Any] = {
            "audience": self._audience,
            "leeway": self._leeway,
        }
        if self._issuer is not None:
            kwargs["issuer"] = self._issuer
            required.append("iss")
        kwargs["options"] = {"require": required}
        return kwargs

    def _verify_hs256(self, token: str) -> dict[str, Any]:
        if not self._secret:
            raise AuthError("HS256 token presented but no JWT secret configured")
        return jwt.decode(token, self._secret, algorithms=["HS256"], **self._decode_kwargs())

    def _verify_asymmetric(self, token: str, alg: str) -> dict[str, Any]:
        if self._jwks_client is None:
            raise AuthError(f"{alg} token presented but no JWKS source configured")
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token, signing_key.key, algorithms=["RS256", "ES256"], **self._decode_kwargs()
        )


def _institution_from_claims(claims: Mapping[str, Any]) -> str | None:
    """Extract the bound institution id from the SIGNED, admin-only ``app_metadata``.

    ``user_metadata`` is user-editable and is deliberately never consulted.
    """
    app_metadata = claims.get("app_metadata")
    if isinstance(app_metadata, Mapping):
        return _opt_str(app_metadata.get("institution_id"))
    return None


def ensure_instance(user: AuthUser, allowed: Collection[str]) -> None:
    """Raise :class:`AuthError` unless ``user`` is bound to an allowed instance.

    Fail-closed: a caller with no institution binding is rejected when an instance
    is required.
    """
    if user.institution_id is None:
        raise AuthError("caller is not bound to any institutional instance")
    if user.institution_id not in allowed:
        raise AuthError(
            f"caller instance {user.institution_id!r} is not authorized here"
        )


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

"""Hardening of Supabase JWT verification (§2 findings).

Adds explicit trusted-ISSUER validation and binding of the authenticated identity to
an authorized STRIX institutional instance — derived only from the admin-controlled
(signed) ``app_metadata``, never user-editable ``user_metadata``.
"""

from __future__ import annotations

import time

import jwt
import pytest

from strix.auth.supabase_jwt import AuthError, JWTVerifier, ensure_instance

SECRET = "unit-test-secret-at-least-32-bytes-long!!"
ISSUER = "https://proj.supabase.co/auth/v1"


def _token(*, secret: str = SECRET, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": "user-123",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def verifier() -> JWTVerifier:
    return JWTVerifier(hs256_secret=SECRET, issuer=ISSUER)


# --- trusted issuer validation --------------------------------------------


def test_accepts_matching_issuer(verifier: JWTVerifier) -> None:
    assert verifier.verify(_token()).id == "user-123"


def test_rejects_wrong_issuer(verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify(_token(iss="https://evil.example.com/auth/v1"))


def test_rejects_missing_issuer_when_issuer_configured(verifier: JWTVerifier) -> None:
    # Build a token with NO iss claim at all -> required -> rejected.
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 3600},
        SECRET, algorithm="HS256",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_from_env_derives_issuer_from_supabase_url() -> None:
    v = JWTVerifier.from_env({
        "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_URL": "https://proj.supabase.co"
    })
    assert v.verify(_token()).id == "user-123"
    with pytest.raises(AuthError):
        v.verify(_token(iss="https://evil.example.com/auth/v1"))


def test_from_env_enforces_explicit_issuer_in_secret_only_mode() -> None:
    # Secret-only (no SUPABASE_URL) can still pin + enforce issuer via env var,
    # closing the shared-secret cross-project acceptance gap.
    v = JWTVerifier.from_env({"SUPABASE_JWT_SECRET": SECRET, "SUPABASE_JWT_ISSUER": ISSUER})
    assert v.verify(_token()).id == "user-123"
    with pytest.raises(AuthError):
        v.verify(_token(iss="https://evil.example.com/auth/v1"))


# --- institutional-instance binding ---------------------------------------


def test_institution_id_read_from_signed_app_metadata(verifier: JWTVerifier) -> None:
    user = verifier.verify(_token(app_metadata={"institution_id": "INST-abc123def456"}))
    assert user.institution_id == "INST-abc123def456"


def test_user_editable_metadata_is_ignored_for_instance(verifier: JWTVerifier) -> None:
    # A caller putting institution in user_metadata must NOT be bound to it.
    user = verifier.verify(_token(user_metadata={"institution_id": "INST-forged"}))
    assert user.institution_id is None


def test_ensure_instance_enforces_membership(verifier: JWTVerifier) -> None:
    user = verifier.verify(_token(app_metadata={"institution_id": "INST-abc123def456"}))
    ensure_instance(user, {"INST-abc123def456"})  # no raise
    with pytest.raises(AuthError):
        ensure_instance(user, {"INST-other"})


def test_ensure_instance_fails_closed_without_binding(verifier: JWTVerifier) -> None:
    user = verifier.verify(_token())  # no app_metadata -> no institution binding
    with pytest.raises(AuthError):
        ensure_instance(user, {"INST-abc123def456"})

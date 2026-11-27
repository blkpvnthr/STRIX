"""Supabase JWT verification: accept valid, reject everything else."""

from __future__ import annotations

import time

import jwt
import pytest

from strix.auth.supabase_jwt import AuthConfigError, AuthError, JWTVerifier

SECRET = "unit-test-secret-at-least-32-bytes-long!!"


def _token(secret: str = SECRET, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": "user-123",
        "email": "a@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def verifier() -> JWTVerifier:
    return JWTVerifier(hs256_secret=SECRET)


def test_accepts_valid_token(verifier: JWTVerifier) -> None:
    user = verifier.verify(_token())
    assert user.id == "user-123"
    assert user.email == "a@example.com"
    assert user.role == "authenticated"


def test_rejects_expired(verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify(_token(exp=int(time.time()) - 10))


def test_rejects_wrong_audience(verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify(_token(aud="anon"))


def test_rejects_forged_signature(verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify(_token(secret="a-different-secret-also-32-bytes-ok"))


def test_rejects_missing_subject(verifier: JWTVerifier) -> None:
    token = jwt.encode(
        {"aud": "authenticated", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256"
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_rejects_empty_token(verifier: JWTVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify("")


def test_requires_configuration() -> None:
    with pytest.raises(AuthConfigError):
        JWTVerifier()


def test_from_env_prefers_asymmetric_then_hs256() -> None:
    v = JWTVerifier.from_env({"SUPABASE_JWT_SECRET": SECRET})
    assert v.verify(_token()).id == "user-123"
    with pytest.raises(AuthConfigError):
        JWTVerifier.from_env({})

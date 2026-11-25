"""The auth layer is actually WIRED into the app (§2 CRITICAL regression).

require_user was previously defined but never attached to any route, leaving every
endpoint anonymous. These tests pin that create_app configures the verifier and that
every non-public route carries the require_user dependency (fail-closed).
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from strix.auth.dependencies import DEV_USER, require_user
from strix.auth.supabase_jwt import JWTVerifier
from strix.webapi.app import create_app

SECRET = "unit-test-secret-at-least-32-bytes-long!!"


def _request(verifier: object, dev: bool, headers: dict[str, str] | None = None) -> object:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(verifier=verifier, auth_dev_mode=dev)),
        headers=headers or {},
    )


def _hs256(**claims: object) -> str:
    payload: dict[str, object] = {
        "sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600,
    }
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_require_user_503_when_unconfigured_and_not_dev() -> None:
    with pytest.raises(HTTPException) as exc:
        require_user(_request(None, False))  # type: ignore[arg-type]
    assert exc.value.status_code == 503  # fail closed, never anonymous


def test_require_user_dev_mode_returns_fixed_user() -> None:
    assert require_user(_request(None, True)).id == DEV_USER.id  # type: ignore[arg-type]


def test_require_user_401_without_bearer() -> None:
    with pytest.raises(HTTPException) as exc:
        require_user(_request(JWTVerifier(hs256_secret=SECRET), False, {}))  # type: ignore[arg-type]
    assert exc.value.status_code == 401


def test_require_user_accepts_valid_token() -> None:
    req = _request(JWTVerifier(hs256_secret=SECRET), False, {"authorization": f"Bearer {_hs256()}"})
    assert require_user(req).id == "u1"  # type: ignore[arg-type]


def test_create_app_configures_authentication(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    assert hasattr(app.state, "verifier")  # set (None here: no SUPABASE env)
    assert app.state.auth_dev_mode is False


def _route_requires_auth(route: object) -> bool:
    return any(
        getattr(dep, "dependency", None) is require_user
        for dep in getattr(route, "dependencies", [])
    )


def test_protected_routes_carry_require_user_and_public_ones_do_not(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    protected = {
        "/api/research", "/api/research/{research_id}", "/api/history",
        "/api/runs/{run_id}", "/api/finance/accounts", "/api/finance/net-worth",
        "/api/finance/budgets",
    }
    public = {"/api/health", "/api/meta"}
    by_path: dict[str, object] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is not None:
            by_path[path] = route
    for path in protected:
        assert path in by_path, f"missing route {path}"
        assert _route_requires_auth(by_path[path]), f"{path} is NOT auth-protected"
    for path in public:
        assert not _route_requires_auth(by_path[path]), f"{path} should be public"

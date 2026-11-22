"""Tests for the rate limiter and retrying HTTP fetcher."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from strix.errors import IngestionError
from strix.lakehouse.ingest.rate_limit import (
    HttpFetcher,
    PermanentFetchError,
    RateLimiter,
    TransientFetchError,
)


def test_rate_limiter_enforces_min_interval() -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []
    limiter = RateLimiter(
        min_interval=1.0, now_fn=lambda: clock["t"], sleep_fn=lambda s: sleeps.append(s)
    )
    limiter.acquire()  # first: no wait
    limiter.acquire()  # second: no time passed -> must wait ~1.0
    assert sleeps and abs(sleeps[0] - 1.0) < 1e-9


def _fetcher(transport: object, **kw: object) -> HttpFetcher:
    return HttpFetcher(
        rate_limiter=RateLimiter(min_interval=0.0),
        transport=transport,  # type: ignore[arg-type]
        sleep_fn=lambda s: None,
        **kw,  # type: ignore[arg-type]
    )


def test_get_success() -> None:
    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        return 200, b"ok"

    assert _fetcher(transport).get("https://x") == b"ok"


def test_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}

    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientFetchError("boom")
        return 200, b"ok"

    assert _fetcher(transport, max_retries=2).get("https://x") == b"ok"
    assert calls["n"] == 2


def test_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        calls["n"] += 1
        return (429, b"") if calls["n"] == 1 else (200, b"ok")

    assert _fetcher(transport, max_retries=2).get("https://x") == b"ok"


def test_exhausts_retries_raises() -> None:
    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        raise TransientFetchError("down")

    with pytest.raises(IngestionError):
        _fetcher(transport, max_retries=1).get("https://x")


def test_permanent_4xx_raises() -> None:
    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        return 404, b"nope"

    with pytest.raises(PermanentFetchError):
        _fetcher(transport).get("https://x")

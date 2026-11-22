"""Rate limiting and bounded-retry HTTP fetching for ingestion.

``RateLimiter`` enforces a minimum interval between requests (injectable clock and
sleep, so tests never actually wait). ``HttpFetcher`` performs GET requests with
the rate limiter plus bounded exponential-backoff retries on transient failures
(timeouts, connection errors, HTTP 429/5xx). Transport is injectable, so unit
tests run fully offline.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from strix.errors import IngestionError

#: HTTP statuses worth retrying.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 30.0


class TransientFetchError(Exception):
    """A retryable transport/HTTP failure."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PermanentFetchError(IngestionError):
    """A non-retryable HTTP failure (e.g. 4xx other than 429)."""


@dataclass
class RateLimiter:
    """Minimum-interval limiter. ``min_interval`` seconds between acquisitions."""

    min_interval: float
    now_fn: Callable[[], float] = time.monotonic
    sleep_fn: Callable[[float], None] = time.sleep
    _last: float | None = field(default=None, init=False)

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        now = self.now_fn()
        if self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                self.sleep_fn(wait)
        self._last = self.now_fn()


#: A transport: (url, headers) -> (status, body_bytes).
Transport = Callable[[str, Mapping[str, str]], "tuple[int, bytes]"]


@dataclass
class HttpFetcher:
    """GET with rate limiting + bounded exponential-backoff retries."""

    rate_limiter: RateLimiter
    transport: Transport | None = None
    max_retries: int = 3
    timeout: float = 30.0
    user_agent: str = "STRIX/0.3 lakehouse ingestion (contact@quantumquant.trade)"
    sleep_fn: Callable[[float], None] = time.sleep

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        hdrs = {"User-Agent": self.user_agent, **(headers or {})}
        transport = self.transport or self._urllib_transport
        attempt = 0
        while True:
            self.rate_limiter.acquire()
            try:
                status, body = transport(url, hdrs)
            except TransientFetchError as exc:
                if attempt >= self.max_retries:
                    raise IngestionError(f"GET {url} failed after retries: {exc}") from exc
                self._backoff(attempt)
                attempt += 1
                continue
            if status in _RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    raise IngestionError(f"GET {url} returned HTTP {status} after retries")
                self._backoff(attempt)
                attempt += 1
                continue
            if status >= 400:
                raise PermanentFetchError(f"GET {url} returned HTTP {status}")
            return body

    def _backoff(self, attempt: int) -> None:
        self.sleep_fn(min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP))

    def _urllib_transport(self, url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        request = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return int(response.status), bytes(response.read())
        except urllib.error.HTTPError as exc:  # has a status code
            body = b""
            try:
                body = bytes(exc.read())
            except Exception:
                body = b""
            if exc.code in _RETRYABLE_STATUS:
                raise TransientFetchError(str(exc), status=exc.code) from exc
            # Return the status so .get() raises a PermanentFetchError uniformly.
            return int(exc.code), body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransientFetchError(str(exc)) from exc

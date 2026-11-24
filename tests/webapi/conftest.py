"""Override the global no-network guard for in-process TestClient tests.

Starlette's ``TestClient`` runs the ASGI app through an anyio event-loop portal
that opens a loopback self-pipe (``socketpair``) — not outbound network. These
tests inject stub triggers/runners, so no real OpenAI or database call is made;
allowing the local socketpair is safe and necessary for the client to run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def no_network() -> Iterator[None]:
    yield

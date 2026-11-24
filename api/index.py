"""Vercel Python Function entry point for the STRIX research API.

Vercel's Python runtime detects the ASGI ``app`` exported here and serves it. The
whole FastAPI application (every ``/api/*`` route plus the internal execute and
cron sweeper routes) runs as one function with the ``maxDuration`` configured in
``vercel.json`` — ample headroom over the engine's 120s research budget for
checkpointing, artifact upload, and finalization.

No persistent process is started; each invocation handles one request and the
durable job store (Supabase Postgres) carries all state between invocations.
"""

from __future__ import annotations

import pathlib
import sys

# The package lives under ``src/`` (src-layout); add it to the path so the
# function can ``import strix`` without an editable install on the builder.
_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from strix.webapi.cloud_app import app  # noqa: E402

__all__ = ["app"]

"""FastAPI application exposing the shared STRIX research engine.

Endpoints (all under ``/api``):

- ``GET  /api/health``              liveness
- ``GET  /api/meta``                model, pricing version, budget, web-search flag
- ``POST /api/research``            {question, as_of?} -> {research_id}
- ``GET  /api/research/{id}``       job status, progress events, and final result
- ``POST /api/research/{id}/cancel``cooperative cancel
- ``GET  /api/history``             persisted agent-research runs (summaries)
- ``GET  /api/runs/{run_id}``       a persisted run's full answer

The API key is loaded server-side only and never returned to the client. The
built web UI (``web/dist``) is served at ``/`` when present, so one command
serves both.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from strix.agent import AGENT_VERSION
from strix.agent.config import AgentConfig
from strix.errors import AgentError, error_code
from strix.run_store import resolve_state_dir
from strix.webapi.service import ResearchService


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of: str | None = None
    #: Conversation thread to continue (follow-ups). Omitted → a new thread.
    thread_id: str | None = Field(default=None, max_length=64)


def create_app(
    state_dir: Path | None = None, *, service: ResearchService | None = None
) -> FastAPI:
    state = state_dir or resolve_state_dir(None)
    service = service or ResearchService(state)
    app = FastAPI(title="STRIX Research API", version=AGENT_VERSION)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "agent_version": AGENT_VERSION}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        try:
            config = AgentConfig.load()
        except AgentError as exc:
            return {"configured": False, "error": f"[{error_code(exc)}] {exc}"}
        return {
            "configured": True,
            "model": config.model,
            "pricing_version": config.pricing.pricing_version,
            "max_cost_usd": str(config.max_cost_usd),
            "web_search_enabled": config.web_search_enabled,
            "agent_version": AGENT_VERSION,
        }

    @app.post("/api/research")
    def submit(request: ResearchRequest) -> dict[str, str | None]:
        job = service.submit(request.question, request.as_of, request.thread_id)
        return {"research_id": job.id, "thread_id": job.thread_id}

    @app.get("/api/research/{research_id}")
    def status(research_id: str) -> JSONResponse:
        job = service.get(research_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown research id")
        return JSONResponse(content=job.public())

    @app.post("/api/research/{research_id}/cancel")
    def cancel(research_id: str) -> dict[str, bool]:
        return {"cancelled": service.cancel(research_id)}

    @app.get("/api/history")
    def history() -> JSONResponse:
        return JSONResponse(content={"runs": service.history()})

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> JSONResponse:
        detail = service.run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown run id")
        return JSONResponse(content=detail)

    _mount_static(app)
    return app


def _mount_static(app: FastAPI) -> None:
    dist = Path(os.environ.get("STRIX_WEB_DIST", "web/dist"))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")


def serve() -> None:  # pragma: no cover - runtime entry
    import uvicorn

    host = os.environ.get("STRIX_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("STRIX_WEB_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port)


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    serve()

"""Background research jobs for the web API.

Each submitted question runs in a worker thread calling the shared research
engine. Progress strings are captured for the UI to poll; a cooperative cancel
flag lets the orchestrator stop between model calls. Nothing here fabricates a
result — on failure the job records a safe error message (never the API key or a
traceback).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from strix.agent.config import AgentConfig
from strix.agent.orchestrator import run_research_question
from strix.canonical import to_jsonable
from strix.errors import AgentError, StrixError, error_code
from strix.run_store import RunStore
from strix.webapi.serializers import serialize_answer, serialize_claims, serialize_usage


@dataclass
class Job:
    id: str
    question: str
    as_of: str | None
    status: str = "queued"  # queued | running | completed | failed | cancelled
    events: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    cancelled: bool = False
    created_at: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "research_id": self.id,
            "question": self.question,
            "status": self.status,
            "events": list(self.events),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
        }


class ResearchService:
    """Owns research jobs and reads persisted run history."""

    def __init__(
        self,
        state_dir: Path,
        *,
        config_loader: Callable[[], AgentConfig] = AgentConfig.load,
        runner: Callable[..., Any] = run_research_question,
    ) -> None:
        self._state_dir = state_dir
        self._config_loader = config_loader
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # -- jobs --------------------------------------------------------------

    def submit(self, question: str, as_of: str | None = None) -> Job:
        job = Job(
            id="RQ-" + uuid.uuid4().hex[:16],
            question=question,
            as_of=as_of,
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job.id,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("completed", "failed", "cancelled"):
                return False
            job.cancelled = True
            if job.status == "queued":
                job.status = "cancelled"
            return True

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None or job.cancelled:
            return
        job.status = "running"
        try:
            config = self._config_loader()
        except AgentError as exc:
            job.status = "failed"
            job.error = f"[{error_code(exc)}] {exc}"
            return

        parsed_as_of: date | None = None
        if job.as_of:
            try:
                parsed_as_of = date.fromisoformat(job.as_of)
            except ValueError:
                job.status = "failed"
                job.error = "invalid as_of date (expected ISO YYYY-MM-DD)"
                return

        try:
            outcome = self._runner(
                job.question,
                config=config,
                state_dir=self._state_dir,
                as_of=parsed_as_of,
                progress=lambda m: job.events.append(m),
                cancel_check=lambda: job.cancelled,
            )
        except AgentError as exc:
            job.status = "failed"
            job.error = f"[{error_code(exc)}] {exc}"
            return
        except Exception:  # pragma: no cover - defensive; never leak internals
            job.status = "failed"
            job.error = "research failed unexpectedly"
            return

        job.result = {
            "run_id": outcome.run_id,
            "answer": serialize_answer(outcome.answer),
            "usage": serialize_usage(outcome.usage),
            "claims": serialize_claims(outcome.claims),
        }
        job.status = "cancelled" if job.cancelled else "completed"

    # -- history -----------------------------------------------------------

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._state_dir.is_dir():
            return []
        store = RunStore(self._state_dir)
        runs: list[dict[str, Any]] = []
        for entry in sorted(self._state_dir.iterdir(), reverse=True):
            if not entry.name.startswith("RUN-") or not entry.is_dir():
                continue
            try:
                manifest = store.load_json(entry.name, "manifest.json")
            except StrixError:
                continue
            if not isinstance(manifest, dict) or manifest.get("mode") != "agent_research":
                continue
            question = ""
            try:
                q = store.load_json(entry.name, "question.json")
                question = q.get("question", "") if isinstance(q, dict) else ""
            except StrixError:
                pass
            runs.append(
                {
                    "run_id": entry.name,
                    "question": question,
                    "verified_count": manifest.get("verified_count", 0),
                    "created_at": manifest.get("created_at", ""),
                    "model": manifest.get("model", ""),
                }
            )
            if len(runs) >= limit:
                break
        return runs

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        store = RunStore(self._state_dir)
        try:
            manifest = store.load_json(run_id, "manifest.json")
            if not isinstance(manifest, dict) or manifest.get("mode") != "agent_research":
                return None
            answer = store.load_json(run_id, "answer.json")
            usage = store.load_json(run_id, "usage.json")
        except StrixError:
            return None
        return {
            "run_id": run_id,
            "answer": to_jsonable(answer),
            "usage": to_jsonable(usage),
            "created_at": manifest.get("created_at", ""),
        }

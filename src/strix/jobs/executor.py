"""The durable, Vercel-agnostic research-job executor.

:func:`execute_job` is the one entry point that drives a persisted job to a
terminal state. It is deliberately independent of any web framework or hosting
platform: a Vercel Function, the cron sweeper, and a future standalone queue
worker all call it identically. That is what makes the architecture
"queue-ready" — introducing a separate worker never touches the research engine
(:func:`strix.agent.orchestrator.run_research_question`), which this module wraps
but never modifies.

Guarantees provided here (the spec's durable-execution requirements):

- **Duplicate-execution protection** — work starts only after an atomic lease
  claim; a second caller for the same job gets ``None`` and does nothing.
- **Idempotent, bounded retry** — transient (provider/infra) failures re-queue
  the job up to ``max_attempts``; deterministic failures (bad config, failed
  fail-closed validation) fail immediately without burning more budget.
- **Honest state mapping** — a clean finish is ``completed``; a budget/time
  bound with results is ``partial``; a user cancel is ``cancelled``; a lost
  lease past deadline becomes ``timed_out`` (decided by the sweeper). Unverified
  claims are *never* promoted to verified — that invariant lives in the engine
  and verifier and is preserved untouched.
- **Progress + checkpoint persistence** — every engine progress event is
  persisted and renews the lease (heartbeat); a lightweight checkpoint records
  recovery metadata.
- **Lease-scoped writes** — all mutations require the lease; if the lease is lost
  mid-run (a stale takeover), the losing worker discards its result rather than
  overwriting the winner.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from strix.agent.config import AgentConfig
from strix.agent.orchestrator import ResearchOutcome, run_research_question
from strix.canonical import to_jsonable
from strix.errors import (
    AgentConfigError,
    AgentError,
    ResponseValidationError,
    ToolError,
    error_code,
)
from strix.jobs.models import JobRecord, JobState
from strix.jobs.store import JobStore, new_worker_id

#: Deterministic failures: retrying only re-spends budget on the same outcome.
_NON_RETRIABLE: tuple[type[AgentError], ...] = (
    AgentConfigError,
    ResponseValidationError,
    ToolError,
)


class ArtifactSink(Protocol):
    """Uploads a completed run's on-disk artifacts to durable object storage.

    Implementations return a storage reference (e.g. a bucket path) or ``None``.
    Upload is best-effort: a storage hiccup must never discard a successful,
    already-computed research result.
    """

    def upload_run(self, job: JobRecord, run_dir: Path) -> str | None: ...


class NullArtifactSink:
    """No-op sink for local/offline execution (artifacts stay on disk)."""

    def upload_run(self, job: JobRecord, run_dir: Path) -> str | None:
        return None


@dataclass(frozen=True)
class ExecutionResult:
    """What :func:`execute_job` did, for logging/telemetry (never user-facing)."""

    job_id: str
    claimed: bool
    status: JobState | None
    detail: str


def execute_job(
    job_id: str,
    *,
    store: JobStore,
    worker_id: str | None = None,
    config: AgentConfig | None = None,
    config_loader: Callable[[], AgentConfig] = AgentConfig.load,
    runner: Callable[..., ResearchOutcome] = run_research_question,
    artifact_sink: ArtifactSink | None = None,
    lease_seconds: int = 180,
    deadline_seconds: int = 240,
    state_dir_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ExecutionResult:
    """Claim, run, and finalize one research job. Safe to call concurrently.

    The caller supplies the ``store`` and (optionally) a prebuilt ``config`` /
    ``artifact_sink``. ``lease_seconds`` is the per-renewal lease window;
    ``deadline_seconds`` is the absolute wall-clock budget the sweeper uses to
    declare a stuck job ``timed_out`` — both must exceed
    ``config.max_research_seconds`` with headroom for checkpointing/finalization.
    """
    worker = worker_id or new_worker_id()
    sink = artifact_sink or NullArtifactSink()
    now_fn = clock or (lambda: datetime.now(UTC))

    leased = store.claim_for_execution(
        job_id,
        worker_id=worker,
        lease_seconds=lease_seconds,
        deadline_seconds=deadline_seconds,
    )
    if leased is None:
        # Already leased by a live worker, cancelled, or terminal — not ours.
        return ExecutionResult(job_id, claimed=False, status=None, detail="not claimable")

    # From here we hold the lease and are responsible for a terminal transition.
    config_obj = config
    if config_obj is None:
        try:
            config_obj = config_loader()
        except AgentError as exc:
            store.finish_job(
                job_id,
                worker_id=worker,
                status=JobState.FAILED,
                error=f"[{error_code(exc)}] {exc}",
            )
            return ExecutionResult(job_id, True, JobState.FAILED, "config error")

    parsed_as_of = _parse_as_of(leased.as_of)
    if parsed_as_of is _INVALID:
        store.finish_job(
            job_id,
            worker_id=worker,
            status=JobState.FAILED,
            error="invalid as_of date (expected ISO YYYY-MM-DD)",
        )
        return ExecutionResult(job_id, True, JobState.FAILED, "invalid as_of")

    state_dir = _state_dir(state_dir_root, job_id)

    def on_progress(message: str) -> None:
        store.append_progress(job_id, message, worker_id=worker)
        # Heartbeat: a progress event means we are alive — extend the lease.
        store.renew_lease(job_id, worker_id=worker, lease_seconds=lease_seconds)

    def cancel_check() -> bool:
        return store.is_cancel_requested(job_id)

    store.save_checkpoint(
        job_id,
        {"phase": "started", "attempt": leased.attempt, "at": now_fn().isoformat()},
        worker_id=worker,
    )

    try:
        outcome = runner(
            leased.question,
            config=config_obj,
            state_dir=state_dir,
            as_of=parsed_as_of,
            progress=on_progress,
            cancel_check=cancel_check,
        )
    except _NON_RETRIABLE as exc:
        store.finish_job(
            job_id,
            worker_id=worker,
            status=JobState.FAILED,
            error=f"[{error_code(exc)}] {exc}",
        )
        return ExecutionResult(job_id, True, JobState.FAILED, "deterministic failure")
    except AgentError as exc:
        # Transient (provider/network/server): bounded retry, else fail.
        return _handle_transient(store, job_id, worker, f"[{error_code(exc)}] {exc}")
    except Exception:
        return _handle_transient(store, job_id, worker, "research failed unexpectedly")

    return _finalize_success(store, sink, job_id, worker, leased, outcome, state_dir)


def _finalize_success(
    store: JobStore,
    sink: ArtifactSink,
    job_id: str,
    worker: str,
    leased: JobRecord,
    outcome: ResearchOutcome,
    state_dir: Path,
) -> ExecutionResult:
    """Map a completed engine run to a terminal state and persist the result."""
    status = _classify(store, job_id, outcome)

    # Best-effort artifact upload; a storage failure must not lose the result.
    artifact_ref: str | None = None
    artifact_error: str | None = None
    try:
        artifact_ref = sink.upload_run(leased, outcome.run_dir)
    except Exception as exc:
        artifact_error = f"artifact upload failed: {type(exc).__name__}"

    usage = outcome.usage
    total_cost = usage.estimated_cost_usd + usage.tool_cost_usd
    result: dict[str, Any] = {
        "run_id": outcome.run_id,
        "answer": to_jsonable(outcome.answer.model_dump()),
        "usage": to_jsonable(usage.model_dump()),
        "claims": to_jsonable([c.model_dump() for c in outcome.claims]),
        "artifact_ref": artifact_ref,
    }
    # Embed the small structured artifacts so evidence inspection and the recorded
    # integrity hashes are durable in Postgres without a storage round-trip. Raw
    # bytes stay in object storage for full byte-level replay.
    for name, key in (("evidence.json", "evidence"), ("manifest.json", "manifest")):
        loaded = _read_json(outcome.run_dir / name)
        if loaded is not None:
            result[key] = loaded
    if artifact_error:
        result["artifact_error"] = artifact_error

    finished = store.finish_job(
        job_id,
        worker_id=worker,
        status=status,
        run_id=outcome.run_id,
        result=result,
        error=None,
        cost_usd=str(total_cost),
    )
    if finished is None:
        # Lost the lease to a stale-takeover; the winner owns the job now.
        return ExecutionResult(job_id, True, None, "lease lost before finish")
    return ExecutionResult(job_id, True, status, "finished")


def _classify(store: JobStore, job_id: str, outcome: ResearchOutcome) -> JobState:
    """Decide the terminal state from the engine outcome and cancel flag.

    ``completed`` — the loop finished on its own (no budget exhaustion).
    ``cancelled`` — the user requested cancellation.
    ``partial``   — a budget/time bound stopped the loop but verified findings
                    (possibly zero) were produced and persisted; unverified
                    claims remain unverified (never promoted).
    """
    reason = outcome.usage.exhausted_reason
    if store.is_cancel_requested(job_id) or (reason and "cancel" in reason.lower()):
        return JobState.CANCELLED
    if reason:
        return JobState.PARTIAL
    return JobState.COMPLETED


def _handle_transient(
    store: JobStore, job_id: str, worker: str, error: str
) -> ExecutionResult:
    """Requeue a transient failure for bounded retry, or fail if exhausted."""
    requeued = store.requeue_for_retry(job_id, worker_id=worker, error=error)
    if requeued is not None:
        return ExecutionResult(job_id, True, JobState.QUEUED, "requeued for retry")
    store.finish_job(job_id, worker_id=worker, status=JobState.FAILED, error=error)
    return ExecutionResult(job_id, True, JobState.FAILED, "retries exhausted")


# -- helpers ---------------------------------------------------------------

#: Sentinel distinguishing "no as_of given" from "as_of present but malformed".
_INVALID = object()


def _parse_as_of(as_of: str | None) -> date | object | None:
    if not as_of:
        return None
    try:
        return date.fromisoformat(as_of)
    except ValueError:
        return _INVALID


def _state_dir(root: Path | None, job_id: str) -> Path:
    base = root or Path(os.environ.get("STRIX_STATE_DIR", "research_runs"))
    return base / job_id


def _read_json(path: Path) -> Any | None:
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

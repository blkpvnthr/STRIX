"""Interactive command-line interface for STRIX.

This module is a presentation and input layer only:

    CLI -> ResearchSpec -> run_research(spec) -> ResearchResult -> renderer

It performs no financial calculation, builds no evidence, and verifies
nothing. All injectable seams (input function, output streams, clock,
reasoner, fixture path, environment) exist so tests run deterministically
with no terminal, network, or wall clock.

Data sources: the DEMO ticker uses the bundled synthetic fixture (fully
offline); any other ticker fetches real filings from SEC EDGAR (network
required at fetch time only — the fetched bytes are preserved in the run
directory, so replay is always offline).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import TextIO

from strix import PIPELINE_VERSION, __version__
from strix.errors import EngineeringSourceError, StrixError, error_code
from strix.models import ResearchSpec, VerificationStatus
from strix.pipeline import Clock, SystemClock, run_research
from strix.reasoning.base import Reasoner
from strix.rendering.terminal import (
    BANNER,
    failures_text,
    finding_text,
    progress_line,
    replay_text,
)
from strix.replay import replay_run
from strix.run_store import RunStore, resolve_state_dir
from strix.sources import connector_for, parse_source
from strix.sources.base import FetchedSource, SourceConnector, SourceDocument
from strix.sources.demo import DEMO_TICKER, DemoConnector

DEFAULT_QUESTION = "Is operating profitability improving?"

_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")

_EPILOG = (
    "The DEMO ticker runs entirely offline on bundled synthetic data. Real "
    "tickers fetch public filings from SEC EDGAR (no credentials; network "
    "needed at fetch time only). STRIX produces no investment advice and "
    "cannot place trades."
)


class _Cancelled(Exception):
    """User declined or ended input; exit cleanly with success."""


def _build_ingest_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """`strix ingest` — lakehouse Bronze ingestion (DE-2)."""
    ingest = subparsers.add_parser(
        "ingest",
        help="lakehouse data ingestion: backfill, incremental, status, coverage, verify",
        description=(
            "Historical and incremental ingestion of authoritative source data into "
            "the immutable Bronze layer. Operates on a lakehouse root "
            "(--lakehouse-dir / STRIX_LAKEHOUSE_DIR / ./lakehouse)."
        ),
    )
    sub = ingest.add_subparsers(dest="ingest_command", required=True)

    def _common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--lakehouse-dir", dest="lakehouse_dir", metavar="PATH", default=None)

    def _universe(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--source", default="all", help="all | alpaca | sec_edgar | "
                            "us_treasury | bls | fred (or a full <source>.<dataset> key)")
        parser.add_argument("--symbols", default=None, help="comma-separated equity symbols")
        parser.add_argument("--tickers", default=None, help="comma-separated SEC tickers")
        parser.add_argument("--series", default=None, help="comma-separated FRED/BLS series ids")

    bf = sub.add_parser("backfill", help="historical backfill over a date range")
    bf.add_argument("--start", required=True, metavar="YYYY-MM-DD")
    bf.add_argument("--end", default=None, metavar="YYYY-MM-DD", help="default: today")
    _universe(bf)
    _common(bf)

    inc = sub.add_parser("incremental", help="ingest new data since the last checkpoint")
    _universe(inc)
    _common(inc)

    for name, helptext in (
        ("status", "show incremental checkpoints/watermarks"),
        ("coverage", "summarize ingested dataset coverage"),
        ("verify", "re-verify Bronze artifact integrity (hashes)"),
    ):
        p = sub.add_parser(name, help=helptext)
        _common(p)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strix",
        description=(
            "STRIX — Structured Traceability, Retrieval, and Intelligence "
            "eXtraction. Evidence-grounded research CLI."
        ),
        epilog=_EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"strix {__version__}")
    parser.add_argument(
        "--state-dir",
        metavar="PATH",
        default=None,
        help=(
            "directory for research run artifacts (default: ./research_runs, "
            "or the STRIX_STATE_DIR environment variable)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    replay_parser = subparsers.add_parser(
        "replay",
        help="replay a preserved run and verify its deterministic hashes",
        description=(
            "Recompute a preserved research run from its stored spec and raw "
            "source bytes, then compare every deterministic hash with the "
            "run's manifest. Replay never touches the network."
        ),
    )
    replay_parser.add_argument(
        "run_id", metavar="RUN-ID", help="run identifier, e.g. RUN-20260808-001"
    )
    replay_parser.add_argument(
        "--state-dir",
        metavar="PATH",
        # SUPPRESS: when the flag is omitted after the subcommand, the root
        # parser's value survives instead of being clobbered with None.
        default=argparse.SUPPRESS,
        dest="state_dir",
        help="directory containing the run (same default as the root command)",
    )

    ask_parser = subparsers.add_parser(
        "ask",
        help="ask an evidence-verified research question (OpenAI research agent)",
        description=(
            "Research a natural-language question about markets, securities, or "
            "economic conditions using the STRIX OpenAI research agent. Retrieves "
            "real data, independently recomputes every quantitative claim from "
            "preserved observations, and prints a cited, verified answer. Requires "
            "an OpenAI API key in the environment or .env."
        ),
    )
    ask_parser.add_argument("question", metavar="QUESTION", help="the research question")
    ask_parser.add_argument(
        "--as-of",
        metavar="DATE",
        default=None,
        help="observation cutoff date (ISO, e.g. 2026-11-22; default: today)",
    )
    ask_parser.add_argument(
        "--state-dir",
        metavar="PATH",
        default=argparse.SUPPRESS,
        dest="state_dir",
        help="directory for research run artifacts (same default as the root command)",
    )

    _build_ingest_parser(subparsers)

    engineer_parser = subparsers.add_parser(
        "engineer",
        help="engineering data compiler (synthetic demonstration mode)",
        description=(
            "Compile heterogeneous legacy engineering records into an "
            "evidence-backed system model. Offline; synthetic public data "
            "only in this version."
        ),
    )
    engineer_sub = engineer_parser.add_subparsers(dest="engineer_command", required=True)
    compile_parser = engineer_sub.add_parser(
        "compile",
        help="compile a declared input directory into a verified model run",
        description=(
            "Read the engineering-project.json manifest in INPUT_DIR, parse "
            "every declared source with its declared-format adapter, verify "
            "the candidate model, and persist a replayable run with a "
            "deterministic model.json export. Undeclared files are never "
            "ingested."
        ),
    )
    compile_parser.add_argument(
        "input_dir", metavar="INPUT_DIR", help="directory containing the project manifest"
    )
    compile_parser.add_argument(
        "--project-id",
        required=True,
        metavar="ID",
        help="project identifier; must match the manifest project_id",
    )
    compile_parser.add_argument(
        "--as-of",
        required=True,
        metavar="DATE",
        help="epistemic cutoff date (ISO, e.g. 2026-08-09)",
    )
    compile_parser.add_argument(
        "--state-dir",
        metavar="PATH",
        default=argparse.SUPPRESS,
        dest="state_dir",
        help="directory for run artifacts (same default as the root command)",
    )
    compile_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any candidate is quarantined (display-only flag; "
        "never part of the run's deterministic content)",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[], str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    clock: Clock | None = None,
    reasoner: Reasoner | None = None,
    fixture_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """CLI entry point. Returns a process exit code."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    read_line = input_fn if input_fn is not None else _default_input
    clock = clock or SystemClock()

    args = build_parser().parse_args(argv)
    state_dir = resolve_state_dir(getattr(args, "state_dir", None), environ)

    try:
        if args.command == "replay":
            return _cmd_replay(args.run_id, state_dir, out, err, reasoner)
        if args.command == "ask":
            return _cmd_ask(args, state_dir, out, err)
        if args.command == "ingest":
            from strix.lakehouse.ingest.cli import run_ingest

            return run_ingest(args, out=out, err=err)
        if args.command == "engineer":
            return _cmd_engineer_compile(args, state_dir, out, err, clock)
        return _cmd_research(
            state_dir,
            out=out,
            read_line=read_line,
            clock=clock,
            reasoner=reasoner,
            fixture_path=fixture_path,
        )
    except _Cancelled:
        out.write("\nCancelled. No research run was created.\n")
        return 0
    except KeyboardInterrupt:
        out.write("\nCancelled.\n")
        return 130
    except StrixError as exc:
        err.write(f"Error: {exc}\n")
        return 1


def _default_input() -> str:
    return input()


# --------------------------------------------------------------------------
# Interactive research command
# --------------------------------------------------------------------------


def _cmd_research(
    state_dir: Path,
    *,
    out: TextIO,
    read_line: Callable[[], str],
    clock: Clock,
    reasoner: Reasoner | None,
    fixture_path: Path | None,
) -> int:
    out.write(BANNER + "\n")

    ticker = _prompt_ticker(out, read_line)
    question = _prompt(out, read_line, "Research question", DEFAULT_QUESTION)
    as_of_date = _prompt_date(out, read_line, clock.now().date())

    fetched, document = _acquire_source(ticker, as_of_date, out=out, fixture_path=fixture_path)

    out.write("\nResearch scope\n\n")
    out.write(f"  Company: {document.company_name}\n")
    out.write(f"  Ticker: {document.ticker}\n")
    out.write(f"  Question: {question}\n")
    out.write(f"  As-of date: {_format_date(as_of_date)}\n")
    out.write(f"  Historical periods: {document.periods[0]} and {document.periods[1]}\n")
    out.write(f"  Data source: {fetched.description}\n\n")
    if not _confirm(out, read_line):
        raise _Cancelled

    spec = ResearchSpec(
        company_id=document.company_id,
        ticker=document.ticker,
        company_name=document.company_name,
        question=question,
        as_of_date=as_of_date,
        historical_periods=document.periods,
        pipeline_version=PIPELINE_VERSION,
    )

    out.write("\n")

    def progress(step: int, total: int, label: str, status: str) -> None:
        out.write(progress_line(step, total, label, status) + "\n")

    result = run_research(
        spec,
        state_dir=state_dir,
        fetched=fetched,
        clock=clock,
        reasoner=reasoner,
        progress=progress,
    )

    out.write("\n" + finding_text(result.report))
    if result.verification.status is not VerificationStatus.PASSED:
        out.write("\n" + failures_text(result.verification))
        return 1
    return 0


def _acquire_source(
    ticker: str,
    as_of_date: date,
    *,
    out: TextIO,
    fixture_path: Path | None,
) -> tuple[FetchedSource, SourceDocument]:
    """Fetch raw source bytes for the ticker and parse the research scope."""
    connector: SourceConnector
    if ticker == DEMO_TICKER:
        connector = DemoConnector(fixture_path)
    else:
        connector = connector_for(ticker)
        out.write(f"\nFetching SEC EDGAR company facts for {ticker}...\n")
    fetched = connector.fetch(ticker)
    document = parse_source(fetched.source_type, fetched.raw, ticker=ticker, as_of_date=as_of_date)
    return fetched, document


def _prompt(out: TextIO, read_line: Callable[[], str], label: str, default: str) -> str:
    out.write(f"{label} [{default}]:\n> ")
    out.flush()
    try:
        value = read_line().strip()
    except EOFError:
        raise _Cancelled from None
    return value or default


def _prompt_ticker(out: TextIO, read_line: Callable[[], str]) -> str:
    while True:
        value = _prompt(out, read_line, "Ticker", DEMO_TICKER).upper()
        if _TICKER_RE.fullmatch(value):
            return value
        out.write("Please enter a ticker symbol (letters, digits, '.', '-'; e.g. DEMO or AAPL).\n")


def _prompt_date(out: TextIO, read_line: Callable[[], str], default: date) -> date:
    while True:
        value = _prompt(out, read_line, "As-of date", default.isoformat())
        try:
            return date.fromisoformat(value)
        except ValueError:
            out.write("Please enter a date as YYYY-MM-DD.\n")


def _confirm(out: TextIO, read_line: Callable[[], str]) -> bool:
    while True:
        out.write("Proceed? [Y/n]: ")
        out.flush()
        try:
            value = read_line().strip().lower()
        except EOFError:
            return False
        if value in ("", "y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        out.write("Please answer y or n.\n")


def _format_date(value: date) -> str:
    return f"{value:%B} {value.day}, {value.year}"


# --------------------------------------------------------------------------
# Replay command (mode dispatch)
# --------------------------------------------------------------------------


def _cmd_replay(
    run_id: str, state_dir: Path, out: TextIO, err: TextIO, reasoner: Reasoner | None
) -> int:
    # Dispatch on the RAW manifest dict before any model validation: v1
    # manifests are extra="forbid" and carry no "mode" key, so old on-disk
    # runs take the v1 path unchanged.
    raw_manifest = RunStore(state_dir).load_json(run_id, "manifest.json")
    if isinstance(raw_manifest, dict) and raw_manifest.get("mode") == "agent_research":
        from strix.agent.replay import replay_agent_run

        try:
            agent_outcome = replay_agent_run(run_id, state_dir)
        except StrixError as exc:
            err.write(f"Error [{error_code(exc)}]: {exc}\n")
            return 1
        out.write(_agent_replay_text(agent_outcome))
        return 0 if agent_outcome.passed else 1
    if isinstance(raw_manifest, dict) and raw_manifest.get("mode") == "engineering":
        from strix.engineering.replay import replay_engineering_run

        try:
            outcome = replay_engineering_run(run_id, state_dir)
        except StrixError as exc:
            err.write(f"Error [{error_code(exc)}]: {exc}\n")
            return 1
        out.write(replay_text(outcome))
        return 0 if outcome.passed else 1
    v1_outcome = replay_run(run_id, state_dir, reasoner=reasoner)
    out.write(replay_text(v1_outcome))
    return 0 if v1_outcome.passed else 1


# --------------------------------------------------------------------------
# Research agent (ask) command
# --------------------------------------------------------------------------


def _cmd_ask(args: argparse.Namespace, state_dir: Path, out: TextIO, err: TextIO) -> int:
    from strix.agent.config import AgentConfig
    from strix.agent.orchestrator import run_research_question
    from strix.agent.response_builder import render_answer
    from strix.errors import AgentError

    try:
        config = AgentConfig.load()
    except AgentError as exc:
        err.write(f"Error [{error_code(exc)}]: {exc}\n")
        return 1

    as_of = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            err.write(f"Error: invalid --as-of {args.as_of!r}; expected an ISO date\n")
            return 1

    out.write(BANNER + "\n")
    out.write(f"Researching: {args.question}\n\n")

    def progress(message: str) -> None:
        out.write(f"  … {message}\n")
        out.flush()

    try:
        outcome = run_research_question(
            args.question,
            config=config,
            state_dir=state_dir,
            as_of=as_of,
            progress=progress,
        )
    except AgentError as exc:
        err.write(f"\nError [{error_code(exc)}]: {exc}\n")
        return 1

    out.write("\n" + render_answer(outcome.answer))
    usage = outcome.usage
    out.write(
        f"\nUsage: {usage.model_calls} model calls, {usage.tool_calls} tool calls, "
        f"{usage.usage.input_tokens} in / {usage.usage.output_tokens} out tokens, "
        f"est. ${usage.estimated_cost_usd} ({usage.elapsed_seconds}s)\n"
    )
    return 0


def _agent_replay_text(outcome: object) -> str:
    from strix.agent.replay import AgentReplayOutcome

    assert isinstance(outcome, AgentReplayOutcome)
    lines = [f"Replay of {outcome.run_id}: {'PASS' if outcome.passed else 'FAIL'}", ""]
    for claim in outcome.claims:
        mark = "ok" if claim.matches else "MISMATCH"
        lines.append(
            f"  [{mark}] {claim.claim_id}: {claim.recomputed_status} "
            f"(stored {claim.stored_status})"
            + (
                f"; recomputed {claim.recomputed_value} (stored {claim.stored_value})"
                if claim.recomputed_value is not None
                else ""
            )
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Engineering compile command
# --------------------------------------------------------------------------

_PROJECT_ID_RE = re.compile(r"^[A-Z][A-Z0-9\-]{1,31}$")


def _cmd_engineer_compile(
    args: argparse.Namespace, state_dir: Path, out: TextIO, err: TextIO, clock: Clock
) -> int:
    from strix.engineering.models import ModelStatus
    from strix.engineering.pipeline import PROGRESS_LABELS, compile_project
    from strix.engineering.render import compile_summary

    try:
        if not _PROJECT_ID_RE.fullmatch(args.project_id):
            raise EngineeringSourceError(
                f"invalid --project-id {args.project_id!r}; expected pattern "
                f"{_PROJECT_ID_RE.pattern}"
            )
        try:
            as_of_date = date.fromisoformat(args.as_of)
        except ValueError as exc:
            raise EngineeringSourceError(
                f"invalid --as-of {args.as_of!r}; expected an ISO date"
            ) from exc

        out.write(BANNER + "\n")
        total = len(PROGRESS_LABELS)
        counter = {"n": 0}

        def step(label: str) -> None:
            counter["n"] += 1
            out.write(progress_line(counter["n"], total, label, "complete") + "\n")

        def on_ignored(name: str) -> None:
            out.write(f"Ignoring undeclared file: {name}\n")

        result = compile_project(
            Path(args.input_dir),
            project_id=args.project_id,
            as_of_date=as_of_date,
            state_dir=state_dir,
            clock=clock,
            step=step,
            on_ignored=on_ignored,
        )
    except StrixError as exc:
        # Integrity failures carry a machine-readable code and exit 1.
        err.write(f"Error [{error_code(exc)}]: {exc}\n")
        return 1

    out.write(compile_summary(result))
    status = result.verification.status
    if status is ModelStatus.FAILED_MODEL:
        return 1
    if status is ModelStatus.COMPLETED_WITH_REJECTIONS and args.strict:
        return 1
    return 0

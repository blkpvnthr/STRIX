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
from strix.errors import StrixError
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
from strix.run_store import resolve_state_dir
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
        default=None,
        dest="state_dir",
        help="directory containing the run (same default as the root command)",
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
    state_dir = resolve_state_dir(args.state_dir, environ)

    try:
        if args.command == "replay":
            return _cmd_replay(args.run_id, state_dir, out, reasoner)
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
# Replay command
# --------------------------------------------------------------------------


def _cmd_replay(run_id: str, state_dir: Path, out: TextIO, reasoner: Reasoner | None) -> int:
    outcome = replay_run(run_id, state_dir, reasoner=reasoner)
    out.write(replay_text(outcome))
    return 0 if outcome.passed else 1

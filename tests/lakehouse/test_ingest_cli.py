"""Tests for the `strix ingest` CLI (offline; fake fetcher)."""

from __future__ import annotations

import argparse
import io
import json
from collections.abc import Mapping
from pathlib import Path

from strix.lakehouse.ingest.cli import run_ingest
from strix.lakehouse.ingest.rate_limit import HttpFetcher, RateLimiter

_ALPACA_ENV = {"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s"}


def _fake_fetcher() -> HttpFetcher:
    bars = json.dumps(
        {"bars": [{"t": "2026-11-20T05:00:00Z", "c": 1}], "next_page_token": None}
    ).encode()

    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        return 200, bars

    return HttpFetcher(rate_limiter=RateLimiter(0.0), transport=transport, sleep_fn=lambda s: None)


def _ns(**kw: object) -> argparse.Namespace:
    base = {
        "lakehouse_dir": None, "source": "all", "symbols": None, "tickers": None, "series": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _run(args: argparse.Namespace, tmp_path: Path, **kw: object) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    args.lakehouse_dir = str(tmp_path)
    code = run_ingest(args, out=out, err=err, **kw)  # type: ignore[arg-type]
    return code, out.getvalue() + err.getvalue()


def test_backfill_then_status_coverage_verify(tmp_path: Path) -> None:
    # Backfill Alpaca only, with a fake fetcher (no network).
    code, text = _run(
        _ns(ingest_command="backfill", source="alpaca", start="2026-11-20", end="2026-11-20"),
        tmp_path,
        environ=_ALPACA_ENV,
        fetcher=_fake_fetcher(),
    )
    assert code == 0
    assert "alpaca.equity_bars_daily" in text

    # Status shows the advanced watermark.
    code, text = _run(_ns(ingest_command="status"), tmp_path)
    assert code == 0 and "2026-11-20" in text

    # Coverage summarizes the dataset.
    code, text = _run(_ns(ingest_command="coverage"), tmp_path)
    assert code == 0 and "alpaca/equity_bars_daily" in text

    # Verify integrity passes.
    code, text = _run(_ns(ingest_command="verify"), tmp_path)
    assert code == 0 and "failures 0" in text


def test_unknown_source_errors(tmp_path: Path) -> None:
    code, text = _run(
        _ns(ingest_command="backfill", source="nasdaq", start="2026-11-20", end="2026-11-20"),
        tmp_path,
        environ=_ALPACA_ENV,
        fetcher=_fake_fetcher(),
    )
    assert code == 1 and "unknown source" in text


def test_status_empty(tmp_path: Path) -> None:
    code, text = _run(_ns(ingest_command="status"), tmp_path)
    assert code == 0 and "No ingestion checkpoints" in text

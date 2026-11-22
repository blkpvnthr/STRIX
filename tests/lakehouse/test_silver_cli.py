"""Tests for the `strix normalize` CLI."""

from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from tests.lakehouse.silver_fixtures import ALPACA_BARS

from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.silver.cli import run_normalize
from strix.lakehouse.storage import LocalObjectStore

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _seed(tmp_path: Path) -> None:
    BronzeIngestor(LocalObjectStore(tmp_path)).ingest(
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                   partition="2026-11"),
        ALPACA_BARS,
        endpoint="https://example",
        retrieved_at=_NOW,
        producer="t",
    )


def _ns(command: str, tmp_path: Path, **kw: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "normalize_command": command, "lakehouse_dir": str(tmp_path), "json": False,
        "dataset": "all", "start": None, "end": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _run(command: str, tmp_path: Path, **kw: object) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_normalize(_ns(command, tmp_path, **kw), out=out, err=err)
    return code, out.getvalue() + err.getvalue()


def test_run_then_status_verify_reconcile(tmp_path: Path) -> None:
    _seed(tmp_path)
    code, text = _run("run", tmp_path, dataset="alpaca_equity_bars_daily")
    assert code == 0
    assert "published" in text

    code, text = _run("status", tmp_path)
    assert code == 0 and "alpaca_equity_bars_daily" in text

    code, text = _run("verify", tmp_path)
    assert code == 0 and "failures 0" in text

    code, text = _run("reconcile", tmp_path)
    assert code == 0 and "extracted=2" in text


def test_run_json_output_parses(tmp_path: Path) -> None:
    _seed(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    run_normalize(
        _ns("run", tmp_path, dataset="alpaca_equity_bars_daily", json=True), out=out, err=err
    )
    payload = json.loads(out.getvalue())
    assert payload[0]["dataset"] == "alpaca_equity_bars_daily"
    assert payload[0]["published"] is True


def test_quarantine_empty(tmp_path: Path) -> None:
    _seed(tmp_path)
    _run("run", tmp_path, dataset="alpaca_equity_bars_daily")
    code, text = _run("quarantine", tmp_path)
    assert code == 0 and "No quarantined observations" in text

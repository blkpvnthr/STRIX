"""`strix transform` CLI tests (dispatch, validation, read commands) and offline
Snowflake dialect parsing where the adapter is available."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from tests.lakehouse.transform_fixtures import seed_rich_warehouse

from strix.cli import main
from strix.lakehouse.transform.runner import DbtRunner, resolve_project_dir


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli_lh")
    db = seed_rich_warehouse(root)
    runner = DbtRunner(resolve_project_dir(None), db)
    runner.write_profile()
    runner.invoke("seed")
    runner.invoke("build")
    return root


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["transform", *args, "--lakehouse-dir", str(root)],
        stdout=out, stderr=err, environ={"STRIX_LAKEHOUSE_DIR": str(root)},
    )
    return code, out.getvalue(), err.getvalue()


def test_cli_status(built_root: Path) -> None:
    code, out, _ = _run(built_root, "status")
    assert code == 0
    assert "marts" in out and "staging" in out


def test_cli_profile_lists_models(built_root: Path) -> None:
    code, out, _ = _run(built_root, "profile")
    assert code == 0
    assert "mart_yield_curve" in out and "stg_market_bars" in out


def test_cli_validate_symbol(built_root: Path) -> None:
    code, out, _ = _run(built_root, "validate", "--symbol", "SPY")
    assert code == 0
    assert "cumulative return" in out
    assert "maximum drawdown" in out


def test_cli_validate_margin(built_root: Path) -> None:
    code, out, _ = _run(built_root, "validate", "--cik", "CIK0000320193")
    assert code == 0
    assert "operating_margin" in out


def test_cli_lineage(built_root: Path) -> None:
    code, out, _ = _run(built_root, "lineage", "--select", "mart_yield_curve")
    assert code == 0
    assert "int_treasury_maturity_alignment" in out


def test_cli_rejects_shell_metachar_select(built_root: Path) -> None:
    code, _, err = _run(built_root, "run", "--select", "foo; rm -rf /")
    assert code == 1
    assert "selection" in err or "transform error" in err


def test_cli_validate_requires_target(built_root: Path) -> None:
    code, _, err = _run(built_root, "validate")
    assert code == 1
    assert "requires" in err


def test_cli_docs_generates_catalog(built_root: Path) -> None:
    code, _, _ = _run(built_root, "docs")
    assert code == 0
    catalog = resolve_project_dir(None) / "target" / "catalog.json"
    assert catalog.is_file()


def test_snowflake_offline_parse(tmp_path_factory: pytest.TempPathFactory) -> None:
    pytest.importorskip("dbt.adapters.snowflake")
    root = tmp_path_factory.mktemp("sf_lh")
    db = seed_rich_warehouse(root)
    runner = DbtRunner(resolve_project_dir(None), db, backend="snowflake")
    runner.write_profile()
    # parse does not connect; it validates jinja + adapter dispatch for the dialect.
    result = runner.invoke("parse")
    assert result.success, result.stderr_tail

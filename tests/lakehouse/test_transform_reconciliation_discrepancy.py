"""Discrepancy-detection tests for :class:`WarehouseCrossValidator`.

The existing ``test_transform_dbt.py`` only proves the *happy path* — that an
untampered mart agrees with the independent Decimal recompute. This module
exercises the engine's reason for existing: that when the SQL mart and the
independent recompute DISAGREE (or an input is invalid/absent) the validator
DETECTS it, marks ``status != "confirmed"`` / ``agrees is False``, and PRESERVES
the discrepancy rather than silently accepting the mart's own assertion.

Method: the full dbt DAG is built once (module scope); each negative test takes a
fresh *copy* of that warehouse and tampers exactly one source — either the mart
value (the thing being checked) or the underlying fact observations (the
independent recompute's input) — so the two engines are forced to conflict. The
pristine warehouse is never mutated, so a positive control still confirms.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from tests.lakehouse.transform_fixtures import seed_rich_warehouse

from strix.lakehouse.transform.runner import DbtRunner, resolve_project_dir
from strix.lakehouse.transform.verification import WarehouseCrossValidator

CIK = "CIK0000320193"


# -- shared build (once) + per-test fresh copy ----------------------------


@pytest.fixture(scope="module")
def built_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Seed the rich lakehouse and build the full dbt DAG once; return the db path."""
    root = tmp_path_factory.mktemp("recon_lh")
    db = seed_rich_warehouse(root)
    runner = DbtRunner(resolve_project_dir(None), db)
    runner.write_profile()
    assert runner.invoke("seed").success
    result = runner.invoke("build")
    assert result.success, result.stderr_tail or result.stdout_tail
    return db


@pytest.fixture
def fresh_db(built_db: Path, tmp_path: Path) -> Path:
    """A writable, isolated copy of the built warehouse for one tampering test."""
    con = duckdb.connect(str(built_db))
    try:
        con.execute("CHECKPOINT")  # fold any WAL into the single file before copying
    finally:
        con.close()
    dst = tmp_path / "tampered.duckdb"
    shutil.copy(built_db, dst)
    return dst


def _exec(db: Path, sql: str, params: list[Any] | None = None) -> None:
    con = duckdb.connect(str(db))
    try:
        con.execute(sql, params or [])
    finally:
        con.close()


def _scalar(db: Path, sql: str, params: list[Any] | None = None) -> Any:
    con = duckdb.connect(str(db), read_only=True)
    try:
        row = con.execute(sql, params or []).fetchone()
        return None if row is None else row[0]
    finally:
        con.close()


# =========================================================================
# 9. POSITIVE CONTROL — valid matching datasets still confirm.
#    (Run first so the negatives below are attributable to tampering.)
# =========================================================================


def test_control_untampered_copy_confirms_every_metric(fresh_db: Path) -> None:
    v = WarehouseCrossValidator(fresh_db)
    for cv in (
        v.max_drawdown("SPY"),
        v.cumulative_return("SPY"),
        v.realized_volatility("SPY"),
        v.correlation("SPY", "QQQ"),
        v.margin(CIK, "operating_margin"),
    ):
        assert cv.agrees, (cv.claim, cv.sql_value, cv.python_value, cv.difference)
        assert cv.status == "confirmed", (cv.claim, cv.status)
        assert cv.sql_value is not None and cv.python_value is not None
        assert cv.evidence_artifacts  # lineage preserved on a confirmed result


# =========================================================================
# 1. NUMERIC MISMATCH — mart value tampered beyond tolerance.
# =========================================================================


def test_numeric_mismatch_mart_tampered_is_flagged(fresh_db: Path) -> None:
    # SPY true max_drawdown ~ -0.013861; overwrite with a clearly-wrong value.
    _exec(
        fresh_db,
        "UPDATE marts.mart_market_drawdown SET max_drawdown = 0.5 WHERE instrument_symbol = 'SPY'",
    )
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    assert not cv.agrees
    assert cv.status == "discrepancy"
    assert cv.sql_value is not None and cv.python_value is not None
    assert cv.difference is not None
    assert Decimal(cv.difference) > Decimal(cv.tolerance)  # discrepancy is quantified
    assert cv.evidence_artifacts  # lineage preserved even on disagreement


# =========================================================================
# 2. MISSING RECORDS — mart row absent (missing_mart_value branch).
# =========================================================================


def test_missing_mart_row_is_flagged(fresh_db: Path) -> None:
    _exec(fresh_db, "DELETE FROM marts.mart_market_drawdown WHERE instrument_symbol = 'SPY'")
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    assert not cv.agrees
    assert cv.status == "missing_mart_value"
    assert cv.sql_value is None  # mart produced nothing
    assert cv.python_value is not None  # ...but the recompute could still be made
    assert cv.evidence_artifacts  # absence is reported WITH its lineage, never hidden


# =========================================================================
# 3. DUPLICATE RECORDS.
#    Duplicate-grain detection is NOT owned by WarehouseCrossValidator: it reads
#    a single mart value via fetchone() with no COUNT guard, so a mart row
#    duplicated past its grain is silently reduced to one and still "confirmed".
#    (Grain is instead enforced upstream by dbt `unique` schema tests at build
#    time.) This test encodes the DESIRED reconciliation behavior — a value drawn
#    from a duplicate-grain mart must not be confirmed — and is expected to FAIL
#    until the cross-validator gains a row-count / grain check.
#    NOTE: a value-preserving duplicate FACT observation is undetectable here for
#    an independent reason — the fixture metrics are invariant to it (drawdown /
#    return) or their mart is a view (volatility); see the companion test below.
# =========================================================================


@pytest.mark.xfail(
    strict=True,
    reason="WarehouseCrossValidator reads mart values with fetchone() and no grain / "
    "row-count guard, so a duplicate-grain mart row is silently collapsed to one and "
    "still 'confirmed'. Duplicate detection is delegated to dbt `unique` tests and is "
    "not independently re-checked here (coverage gap).",
)
def test_duplicate_mart_row_should_not_confirm(fresh_db: Path) -> None:
    # Duplicate SPY's drawdown row past its grain (dbt `unique` would fail next build).
    _exec(
        fresh_db,
        "INSERT INTO marts.mart_market_drawdown "
        "SELECT * FROM marts.mart_market_drawdown WHERE instrument_symbol = 'SPY'",
    )
    dupes = _scalar(
        fresh_db, "SELECT count(*) FROM marts.mart_market_drawdown WHERE instrument_symbol = 'SPY'"
    )
    assert dupes == 2  # grain is genuinely violated
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    # Desired: a duplicate-grain mart must not pass reconciliation as "confirmed".
    assert cv.status != "confirmed", "duplicate-grain mart silently confirmed"


def test_view_backed_metric_does_not_catch_fact_duplicate(fresh_db: Path) -> None:
    """LIMITATION (pinned): intermediate marts are VIEWS, so a view-backed metric's
    'sql_value' recomputes live from the same fact rows the Python recompute reads.
    A duplicate fact observation therefore moves BOTH sides together and the
    cross-validator reports 'confirmed' — it corroborates engine-agreement, not
    fact-level integrity, for view-materialized metrics (realized_volatility,
    cumulative_return). Only table-materialized marts give a frozen snapshot to
    diverge from. Documented as a coverage boundary, not hidden."""
    _exec(
        fresh_db,
        "INSERT INTO fact_market_bars "
        "SELECT * REPLACE (silver_natural_key || '-DUP' AS silver_natural_key) "
        "FROM fact_market_bars WHERE symbol = 'SPY' AND session_date = DATE '2026-11-17'",
    )
    cv = WarehouseCrossValidator(fresh_db).realized_volatility("SPY")
    assert cv.agrees and cv.status == "confirmed"  # duplicate NOT caught (view tautology)


# =========================================================================
# 4. INVALID PRECISION — a difference that lives below the mart's display
#    precision but still exceeds the contract tolerance must be caught.
# =========================================================================


def test_sub_precision_difference_exceeding_tolerance_is_flagged(fresh_db: Path) -> None:
    # operating_margin FY2025 is exactly 0.3125; perturb by 1e-6 (> STAT_TOLERANCE 5e-7).
    _exec(
        fresh_db,
        "UPDATE marts.mart_financial_ratios "
        "SET ratio_value = ratio_value + 0.000001 "
        "WHERE ratio_name = 'operating_margin' AND fiscal_year = 2025",
    )
    cv = WarehouseCrossValidator(fresh_db).margin(CIK, "operating_margin")
    assert not cv.agrees
    assert cv.status == "discrepancy"
    assert cv.difference is not None
    diff = Decimal(cv.difference)
    assert diff > Decimal(cv.tolerance)  # beyond tolerance -> flagged
    assert diff < Decimal("0.00001")  # ...yet genuinely a precision-scale difference


# =========================================================================
# 5. CONFLICTING EVIDENCE — fact source and mart disagree. Here the
#    independent recompute's INPUT is tampered (the mart is left intact), the
#    mirror image of scenario 1, proving both directions are detected.
# =========================================================================


def test_conflicting_fact_vs_mart_is_flagged(fresh_db: Path) -> None:
    # Deepen SPY's trough in the fact table only; the drawdown mart is unchanged.
    _exec(
        fresh_db,
        "UPDATE fact_market_bars SET close = 300 "
        "WHERE symbol = 'SPY' AND session_date = DATE '2026-11-17'",
    )
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    assert not cv.agrees
    assert cv.status == "discrepancy"
    assert cv.sql_value is not None and cv.python_value is not None
    assert Decimal(cv.difference) > Decimal("0.1")  # ~ -0.406 vs -0.0139


# =========================================================================
# 6. MISSING PROVENANCE — evidence/lineage absent (or vacuous).
#    The schema prevents NULL (bronze_artifact_id is NOT NULL — a real upstream
#    guard), so true absence is injected as an EMPTY-STRING artifact id. The
#    validator surfaces lineage but does NOT enforce it is meaningful: a vacuous
#    id still yields status "confirmed" with evidence_artifacts=('',). This test
#    encodes the DESIRED contract (a confirmed value must carry real lineage) and
#    is expected to FAIL until the validator gains provenance validation.
# =========================================================================


@pytest.mark.xfail(
    strict=True,
    reason="WarehouseCrossValidator does not validate provenance meaningfulness: an "
    "empty-string bronze_artifact_id yields evidence_artifacts=('',) and the result "
    "is still 'confirmed'. Vacuous lineage is an undetected discrepancy (gap).",
)
def test_missing_provenance_should_not_confirm(fresh_db: Path) -> None:
    _exec(fresh_db, "UPDATE fact_market_bars SET bronze_artifact_id = '' WHERE symbol = 'SPY'")
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    # Desired contract: a confirmed value must be backed by real evidence ids.
    assert cv.evidence_artifacts, "no lineage surfaced at all"
    assert all(a.strip() for a in cv.evidence_artifacts), (
        f"confirmed with vacuous lineage: {cv.evidence_artifacts}"
    )


def test_missing_provenance_current_behavior_is_documented(fresh_db: Path) -> None:
    """Pins the CURRENT (weak) behavior so the gap in #6 is explicit and visible."""
    _exec(fresh_db, "UPDATE fact_market_bars SET bronze_artifact_id = '' WHERE symbol = 'SPY'")
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    # Documented defect: numbers still agree, provenance is a vacuous empty string.
    assert cv.agrees and cv.status == "confirmed"
    assert cv.evidence_artifacts == ("",)


# =========================================================================
# 7. INVALID HASHES — NOT REPRESENTABLE against the current API.
# =========================================================================


@pytest.mark.skip(
    reason="Coverage gap: WarehouseCrossValidator performs NO artifact hash / "
    "content-integrity verification. It reads bronze_artifact_id (an identifier, "
    "not a content hash) and the queried fact tables expose no hash column, so a "
    "tampered-hash scenario cannot exercise any real code path. Requires future "
    "implementation (hash capture + verification) before it can be tested."
)
def test_invalid_artifact_hash_is_flagged() -> None:  # pragma: no cover
    raise NotImplementedError


# =========================================================================
# 8. EMPTY DATASETS — insufficient_data branch (two sources of emptiness).
# =========================================================================


def test_empty_fact_series_is_insufficient_data(fresh_db: Path) -> None:
    _exec(fresh_db, "DELETE FROM fact_market_bars WHERE symbol = 'SPY'")
    cv = WarehouseCrossValidator(fresh_db).max_drawdown("SPY")
    assert not cv.agrees
    assert cv.status == "insufficient_data"
    assert cv.python_value is None  # recompute refused — no fabricated number
    assert cv.note  # the reason is reported


def test_empty_fundamentals_is_insufficient_data(fresh_db: Path) -> None:
    _exec(fresh_db, f"DELETE FROM marts.mart_company_fundamentals WHERE cik = '{CIK}'")
    cv = WarehouseCrossValidator(fresh_db).margin(CIK, "operating_margin")
    assert not cv.agrees
    assert cv.status == "insufficient_data"
    assert cv.python_value is None
    assert cv.note

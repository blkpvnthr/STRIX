"""Shared engineering-test fixtures: fixture dirs, compiled outcomes, helpers."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from strix.engineering.manifest import MANIFEST_NAME
from strix.engineering.pipeline import ModelOutcome, compile_project, compute_model
from strix.models import ResearchSpec  # noqa: F401  (re-export convenience)
from tests.conftest import FIXED_NOW, FixedClock

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_DIR = REPO_ROOT / "examples" / "engineering-demo"
CLEAN_DIR = REPO_ROOT / "examples" / "engineering-demo-clean"
AS_OF = date(2026, 8, 9)
PROJECT_ID = "SYNTH-CTRL"


def read_sources(input_dir: Path) -> tuple[bytes, dict[str, bytes]]:
    """(manifest_raw, declared source bytes) for a fixture directory."""
    manifest_raw = (input_dir / MANIFEST_NAME).read_bytes()
    declared = json.loads(manifest_raw)["sources"]
    return manifest_raw, {
        entry["file"]: (input_dir / entry["file"]).read_bytes() for entry in declared
    }


def compute_fixture(input_dir: Path) -> ModelOutcome:
    manifest_raw, source_raws = read_sources(input_dir)
    return compute_model(
        project_id=PROJECT_ID,
        as_of_date=AS_OF,
        manifest_raw=manifest_raw,
        source_raws=source_raws,
        checked_at=FIXED_NOW,
    )


@pytest.fixture(scope="session")
def triage_outcome() -> ModelOutcome:
    return compute_fixture(TRIAGE_DIR)


@pytest.fixture(scope="session")
def clean_outcome() -> ModelOutcome:
    return compute_fixture(CLEAN_DIR)


@pytest.fixture
def eng_state_dir(tmp_path: Path) -> Path:
    return tmp_path / "eng_runs"


@pytest.fixture
def triage_result(eng_state_dir: Path):
    return compile_project(
        TRIAGE_DIR,
        project_id=PROJECT_ID,
        as_of_date=AS_OF,
        state_dir=eng_state_dir,
        clock=FixedClock(),
    )


@pytest.fixture
def triage_copy(tmp_path: Path) -> Path:
    """A mutable copy of the triage fixture directory."""
    target = tmp_path / "input"
    shutil.copytree(TRIAGE_DIR, target)
    return target

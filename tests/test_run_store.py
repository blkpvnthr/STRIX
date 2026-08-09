"""Run persistence: atomicity, no-overwrite, sanitization, preservation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strix.canonical import sha256_hex
from strix.errors import InvalidRunIdError, RunNotFoundError, RunStoreError
from strix.models import ResearchSpec
from strix.pipeline import run_research
from strix.run_store import RunStore, resolve_state_dir, sanitize_run_id
from strix.sources.demo import FIXTURE_NAME
from tests.conftest import FixedClock

EXPECTED_ARTIFACTS = {
    "spec.json",
    "manifest.json",
    "facts.json",
    "calculations.json",
    "evidence.json",
    "claims.json",
    "verification.json",
    "report.txt",
    "raw",
}


@pytest.fixture
def result(spec: ResearchSpec, state_dir: Path, clock: FixedClock):
    return run_research(spec, state_dir=state_dir, clock=clock)


class TestRunDirectory:
    def test_run_directory_contains_all_artifacts(self, result) -> None:
        names = {entry.name for entry in result.run_directory.iterdir()}
        assert names == EXPECTED_ARTIFACTS
        assert (result.run_directory / "raw" / FIXTURE_NAME).is_file()

    def test_run_id_format_uses_injected_clock(self, result) -> None:
        assert result.manifest.run_id == "RUN-20260808-001"
        assert result.run_directory.name == result.manifest.run_id

    def test_raw_fixture_preserved_byte_exact(self, result, raw_fixture: bytes) -> None:
        preserved = (result.run_directory / "raw" / FIXTURE_NAME).read_bytes()
        assert preserved == raw_fixture
        assert sha256_hex(preserved) == result.manifest.source_hashes[FIXTURE_NAME]

    def test_no_staging_directories_remain(self, result, state_dir: Path) -> None:
        leftovers = [p for p in state_dir.iterdir() if p.name.startswith(".staging-")]
        assert leftovers == []

    def test_manifest_records_versions_and_status(self, result) -> None:
        manifest = json.loads((result.run_directory / "manifest.json").read_text())
        assert manifest["pipeline_version"] == "0.1.0"
        assert manifest["source_version"] == "1.0.0"
        assert manifest["source_type"] == "synthetic_fixture"
        assert manifest["source_name"] == FIXTURE_NAME
        assert manifest["final_status"] == "passed"
        assert set(manifest["calculation_versions"]) == {
            "operating_margin",
            "operating_margin_change_pp",
        }

    def test_report_contains_citations_and_disclaimer(self, result) -> None:
        text = (result.run_directory / "report.txt").read_text()
        for item in result.evidence:
            assert item.evidence_id in text
        assert "Synthetic demonstration data" in text

    def test_json_decimals_stored_as_strings(self, result) -> None:
        facts = json.loads((result.run_directory / "facts.json").read_text())
        values = [fact["value"] for fact in facts]
        assert all(isinstance(value, str) for value in values)
        assert "1000000000" in values


class TestSequencingAndOverwrite:
    def test_sequential_ids_same_day(
        self, spec: ResearchSpec, state_dir: Path, clock: FixedClock
    ) -> None:
        first = run_research(spec, state_dir=state_dir, clock=clock)
        second = run_research(spec, state_dir=state_dir, clock=clock)
        assert first.manifest.run_id == "RUN-20260808-001"
        assert second.manifest.run_id == "RUN-20260808-002"

    def test_existing_completed_run_never_overwritten(
        self, spec: ResearchSpec, state_dir: Path, clock: FixedClock
    ) -> None:
        first = run_research(spec, state_dir=state_dir, clock=clock)
        marker = first.run_directory / "report.txt"
        original = marker.read_bytes()
        second = run_research(spec, state_dir=state_dir, clock=clock)
        assert second.run_directory != first.run_directory
        assert marker.read_bytes() == original

    def test_failure_leaves_no_visible_run(
        self, spec: ResearchSpec, state_dir: Path, clock: FixedClock, monkeypatch
    ) -> None:
        # Simulate a crash while writing the manifest (the last artifact).
        original = RunStore._write_atomic

        def explode(path: Path, data: bytes) -> None:
            if path.name == "manifest.json":
                raise RunStoreError("simulated crash")
            original(path, data)

        monkeypatch.setattr(RunStore, "_write_atomic", staticmethod(explode))
        with pytest.raises(RunStoreError):
            run_research(spec, state_dir=state_dir, clock=clock)
        visible = [p.name for p in state_dir.iterdir() if not p.name.startswith(".")]
        assert visible == []


class TestRunIdSafety:
    @pytest.mark.parametrize(
        "malicious",
        [
            "../evil",
            "RUN-20260808-001/../..",
            "/etc/passwd",
            "RUN-20260808-001x",
            "RUN-2026-001",
            "run-20260808-001",
            "RUN-20260808-001\n",
            "..",
            # Unicode digits match \d without re.ASCII; they must be rejected.
            "RUN-٢٠٢٦٠٨٠٨-٠٠١",
            "RUN-２０２６０８０８-００１",
        ],
    )
    def test_malicious_run_ids_rejected(self, malicious: str, state_dir: Path) -> None:
        with pytest.raises(InvalidRunIdError):
            sanitize_run_id(malicious)
        with pytest.raises(InvalidRunIdError):
            RunStore(state_dir).run_dir(malicious)

    def test_valid_but_absent_run_raises_not_found(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True)
        with pytest.raises(RunNotFoundError):
            RunStore(state_dir).run_dir("RUN-20260808-001")

    @pytest.mark.parametrize(
        "malicious_name",
        ["../manifest.json", "/etc/passwd", "raw/../../x", "..", "a/b.json", "\\evil"],
    )
    def test_artifact_names_cannot_escape_the_run_directory(
        self, malicious_name: str, result
    ) -> None:
        # read_raw/load_json take artifact *names*; a path (e.g. from a
        # tampered manifest) must be rejected before any filesystem access.
        store = RunStore(result.run_directory.parent)
        run_id = result.manifest.run_id
        with pytest.raises(RunStoreError, match="invalid artifact name"):
            store.read_raw(run_id, malicious_name)
        with pytest.raises(RunStoreError, match="invalid artifact name"):
            store.load_json(run_id, malicious_name)


class TestStateDirResolution:
    def test_flag_wins(self) -> None:
        assert resolve_state_dir("/tmp/custom", {"STRIX_STATE_DIR": "/ignored"}) == Path(
            "/tmp/custom"
        )

    def test_env_var_used_when_no_flag(self) -> None:
        assert resolve_state_dir(None, {"STRIX_STATE_DIR": "/from-env"}) == Path("/from-env")

    def test_default_is_research_runs(self) -> None:
        assert resolve_state_dir(None, {}) == Path("research_runs")

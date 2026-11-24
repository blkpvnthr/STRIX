"""Replay: reproducibility of unmodified runs, detection of tampering."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

from strix.errors import InvalidRunIdError, RunNotFoundError
from strix.models import ResearchSpec
from strix.pipeline import run_research
from strix.replay import replay_run
from strix.sources.demo import FIXTURE_NAME
from tests.conftest import FixedClock


@pytest.fixture
def result(spec: ResearchSpec, state_dir: Path, clock: FixedClock):
    return run_research(spec, state_dir=state_dir, clock=clock)


def stage_map(outcome):
    return {stage.name: stage for stage in outcome.stages}


class TestReplayReproducibility:
    def test_unmodified_run_replays_with_identical_hashes(self, result, state_dir: Path) -> None:
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert outcome.passed
        assert all(stage.matched for stage in outcome.stages)
        names = [stage.name for stage in outcome.stages]
        assert names == [
            "Source artifact hash",
            "Input hash",
            "Source facts hash",
            "Calculations hash",
            "Evidence hash",
            "Claims hash",
            "Verification status",
        ]

    def test_replay_is_repeatable(self, result, state_dir: Path) -> None:
        first = replay_run(result.manifest.run_id, state_dir)
        second = replay_run(result.manifest.run_id, state_dir)
        assert first == second


class TestReplayTamperDetection:
    def test_modified_raw_artifact_detected(self, result, state_dir: Path) -> None:
        raw_path = result.run_directory / "raw" / FIXTURE_NAME
        raw_path.write_bytes(raw_path.read_bytes().replace(b"101000000", b"999000000"))
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        assert not stage_map(outcome)["Source artifact hash"].matched

    def test_modified_evidence_detected(self, result, state_dir: Path) -> None:
        evidence_path = result.run_directory / "evidence.json"
        payload = json.loads(evidence_path.read_text())
        payload[0]["value"] = "0.999"
        evidence_path.write_text(json.dumps(payload, indent=2))
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        stage = stage_map(outcome)["Evidence hash"]
        assert not stage.matched
        assert "stored artifact differs" in stage.detail

    def test_modified_claims_detected(self, result, state_dir: Path) -> None:
        claims_path = result.run_directory / "claims.json"
        payload = json.loads(claims_path.read_text())
        payload[0]["statement"] = "Operating margin definitely went up a lot."
        claims_path.write_text(json.dumps(payload, indent=2))
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        assert not stage_map(outcome)["Claims hash"].matched

    def test_unreadable_stage_artifact_detected(self, result, state_dir: Path) -> None:
        (result.run_directory / "facts.json").write_text("not json")
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        assert "unreadable" in stage_map(outcome)["Source facts hash"].detail

    def test_missing_stage_artifact_detected(self, result, state_dir: Path) -> None:
        # A deleted stage artifact (vs. merely corrupt bytes) must still be
        # caught: the stored hash cannot be recomputed, so the stage fails.
        (result.run_directory / "claims.json").unlink()
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        assert "unreadable" in stage_map(outcome)["Claims hash"].detail

    def test_extra_rows_in_stage_artifact_detected(self, result, state_dir: Path) -> None:
        # An appended (extra) record changes the stored artifact hash: the
        # stored content no longer matches the manifest's recorded hash.
        claims_path = result.run_directory / "claims.json"
        payload = json.loads(claims_path.read_text())
        payload.append(dict(payload[0]))
        claims_path.write_text(json.dumps(payload, indent=2))
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert not outcome.passed
        assert not stage_map(outcome)["Claims hash"].matched

    def test_manifest_with_path_source_name_cannot_read_outside_run(
        self, result, state_dir: Path
    ) -> None:
        # A tampered manifest must never steer replay's raw read outside the
        # run directory: path-like source names fail model validation.
        from strix.errors import ReplayError

        manifest_path = result.run_directory / "manifest.json"
        payload = json.loads(manifest_path.read_text())
        payload["source_name"] = "/etc/hosts"
        manifest_path.write_text(json.dumps(payload, indent=2))
        with pytest.raises(ReplayError, match="unreadable manifest"):
            replay_run(result.manifest.run_id, state_dir)


class TestReplaySafety:
    def test_traversal_run_id_rejected(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True)
        with pytest.raises(InvalidRunIdError):
            replay_run("../../etc", state_dir)

    def test_unknown_run_id_raises_not_found(self, result, state_dir: Path) -> None:
        with pytest.raises(RunNotFoundError):
            replay_run("RUN-19990101-001", state_dir)

    def test_replay_ignores_wall_clock_timestamps(
        self, spec: ResearchSpec, state_dir: Path
    ) -> None:
        from datetime import datetime

        # Two runs created at different wall-clock times replay identically:
        # created_at / checked_at are excluded from deterministic content.
        early = run_research(
            spec,
            state_dir=state_dir,
            clock=FixedClock(datetime(2026, 8, 8, 1, 0, tzinfo=UTC)),
        )
        late = run_research(
            spec,
            state_dir=state_dir,
            clock=FixedClock(datetime(2026, 8, 8, 23, 59, tzinfo=UTC)),
        )
        assert early.manifest.created_at != late.manifest.created_at
        for manifest_field in (
            "input_hash",
            "facts_hash",
            "calculations_hash",
            "evidence_hash",
            "claims_hash",
            "verification_hash",
        ):
            assert getattr(early.manifest, manifest_field) == getattr(late.manifest, manifest_field)
        assert replay_run(early.manifest.run_id, state_dir).passed
        assert replay_run(late.manifest.run_id, state_dir).passed

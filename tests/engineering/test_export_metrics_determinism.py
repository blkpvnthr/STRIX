"""Export separation, ground-truth isolation, metrics, hard determinism."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from strix.canonical import canonical_bytes
from strix.engineering.metrics import compute_metrics, load_expected_model
from strix.engineering.models import CandidateStatus
from strix.engineering.pipeline import ModelOutcome, compile_project
from strix.errors import ExportError
from tests.conftest import FixedClock
from tests.engineering.conftest import (
    AS_OF,
    PROJECT_ID,
    TRIAGE_DIR,
)


class TestExport:
    def test_verified_model_and_quarantine_are_separated(
        self, triage_outcome: ModelOutcome
    ) -> None:
        export = triage_outcome.export
        assert set(export["verified_model"].keys()) == {"elements", "relationships"}
        assert len(export["verified_model"]["elements"]) == 13
        assert len(export["verified_model"]["relationships"]) == 12
        assert len(export["quarantine"]["rejected_candidates"]) == 2
        quarantined = {c["candidate_id"] for c in export["quarantine"]["rejected_candidates"]}
        exported = {e["element_id"] for e in export["verified_model"]["elements"]} | {
            r["relationship_id"] for r in export["verified_model"]["relationships"]
        }
        assert not quarantined & exported

    def test_rejected_candidates_carry_codes_and_anchors(
        self, triage_outcome: ModelOutcome
    ) -> None:
        for candidate in triage_outcome.export["quarantine"]["rejected_candidates"]:
            assert candidate["failures"]
            assert candidate["anchors"]
            assert candidate["rule"]

    def test_no_run_id_or_wall_clock_in_export(self, triage_outcome: ModelOutcome) -> None:
        blob = canonical_bytes(triage_outcome.export).decode()
        assert "RUN-" not in blob
        assert "created_at" not in blob
        assert "checked_at" not in blob

    def test_every_citation_resolves_to_preserved_anchor(
        self, triage_outcome: ModelOutcome
    ) -> None:
        export = triage_outcome.export
        hashes = export["provenance"]["analysis_source_hashes"]
        for record in export["evidence"].values():
            assert record["citations"]
            for citation in record["citations"]:
                assert citation["artifact_hash"] == hashes[citation["file"]]
                assert citation["anchor"].startswith(citation["file"] + "#")

    def test_completeness_guard_raises_on_unverified_item(
        self, triage_outcome: ModelOutcome
    ) -> None:
        from strix.engineering.adapters import parser_versions, schema_versions
        from strix.engineering.export import build_export

        tampered_model = triage_outcome.model.model_copy(
            update={
                "elements": tuple(
                    e.model_copy(update={"status": CandidateStatus.PROPOSED})
                    for e in triage_outcome.model.elements
                )
            }
        )
        with pytest.raises(ExportError, match="export-completeness"):
            build_export(
                spec=triage_outcome.spec,
                project=triage_outcome.project,
                model=tampered_model,
                evidence=triage_outcome.evidence,
                facts=triage_outcome.facts,
                artifacts=triage_outcome.artifacts,
                parser_versions=parser_versions(),
                schema_versions=schema_versions(),
                analysis_source_hashes=triage_outcome.analysis_source_hashes,
            )


class TestMetricsAndGroundTruthIsolation:
    def test_metric_counts_and_ratios(self, triage_result) -> None:
        metrics = triage_result.metrics
        assert metrics.elements_accepted == 13
        assert metrics.relationships_accepted == 12
        assert metrics.relationships_rejected == 2
        assert metrics.conflict_count == 1
        assert metrics.traceability_coverage == "1.0000"
        assert metrics.allocation_coverage == "0.8571"
        assert metrics.unsupported_export_count == 0
        assert metrics.ground_truth is not None
        assert metrics.ground_truth.element_precision == "1.0000"
        assert metrics.ground_truth.relationship_recall == "1.0000"

    def test_perturbed_ground_truth_computes_non_unit_recall(
        self, triage_outcome: ModelOutcome
    ) -> None:
        raw = (TRIAGE_DIR / "expected-model.json").read_bytes()
        payload = json.loads(raw)
        payload["elements"].append("PT-9999")  # expected but never verified
        expected = load_expected_model(json.dumps(payload).encode())
        metrics = compute_metrics(
            model=triage_outcome.model,
            elements=triage_outcome.elements,
            relationships=triage_outcome.relationships,
            verification=triage_outcome.verification,
            resolvable_verified=triage_outcome.resolvable_verified,
            expected=expected,
        )
        assert metrics.ground_truth is not None
        assert metrics.ground_truth.element_precision == "1.0000"
        assert metrics.ground_truth.element_recall == "0.9286"  # 13/14

    def test_ratios_are_decimal_strings(self, triage_result) -> None:
        Decimal(triage_result.metrics.traceability_coverage)
        Decimal(triage_result.metrics.allocation_coverage)

    def test_ground_truth_never_influences_model_or_export(self, tmp_path: Path) -> None:
        # Two compiles differing ONLY in expected-model.json: identical
        # model.json bytes and export/model hashes; different metrics hash.
        results = []
        for variant in ("a", "b"):
            input_dir = tmp_path / variant
            shutil.copytree(TRIAGE_DIR, input_dir)
            if variant == "b":
                payload = json.loads((input_dir / "expected-model.json").read_text())
                payload["elements"] = payload["elements"][:3]
                (input_dir / "expected-model.json").write_text(json.dumps(payload))
            results.append(
                compile_project(
                    input_dir,
                    project_id=PROJECT_ID,
                    as_of_date=AS_OF,
                    state_dir=tmp_path / f"runs-{variant}",
                    clock=FixedClock(),
                )
            )
        first, second = results
        assert first.run_manifest.export_hash == second.run_manifest.export_hash
        assert first.run_manifest.model_hash == second.run_manifest.model_hash
        assert first.run_manifest.input_hash == second.run_manifest.input_hash
        assert first.run_manifest.metrics_hash != second.run_manifest.metrics_hash
        model_a = (first.run_directory / "model.json").read_bytes()
        model_b = (second.run_directory / "model.json").read_bytes()
        assert model_a == model_b


class TestHardDeterminism:
    def test_double_compile_is_byte_identical(self, tmp_path: Path) -> None:
        results = [
            compile_project(
                TRIAGE_DIR,
                project_id=PROJECT_ID,
                as_of_date=AS_OF,
                state_dir=tmp_path / f"runs-{n}",
                clock=FixedClock(),
            )
            for n in (1, 2)
        ]
        first, second = results
        # Byte-identical canonical export.
        assert canonical_bytes(first.export) == canonical_bytes(second.export)
        # Identical content-derived ids across every layer.
        assert [a.artifact_id for a in first.artifacts] == [a.artifact_id for a in second.artifacts]
        assert [f.fact_id for f in first.facts] == [f.fact_id for f in second.facts]
        assert [e.evidence_id for e in first.evidence] == [e.evidence_id for e in second.evidence]
        assert [e.element_id for e in first.elements] == [e.element_id for e in second.elements]
        assert [r.relationship_id for r in first.relationships] == [
            r.relationship_id for r in second.relationships
        ]
        # Identical verification minus the explicitly hash-excluded timestamp.
        assert first.verification.model_dump(
            exclude={"checked_at"}
        ) == second.verification.model_dump(exclude={"checked_at"})

    def test_directory_enumeration_order_cannot_affect_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ingestion is manifest-ordered; shuffle Path.iterdir to prove
        # filesystem enumeration order is irrelevant.

        original_iterdir = Path.iterdir

        def reversed_iterdir(self: Path):
            return iter(sorted(original_iterdir(self), reverse=True))

        result_normal = compile_project(
            TRIAGE_DIR,
            project_id=PROJECT_ID,
            as_of_date=AS_OF,
            state_dir=tmp_path / "runs-normal",
            clock=FixedClock(),
        )
        monkeypatch.setattr(Path, "iterdir", reversed_iterdir)
        result_shuffled = compile_project(
            TRIAGE_DIR,
            project_id=PROJECT_ID,
            as_of_date=AS_OF,
            state_dir=tmp_path / "runs-shuffled",
            clock=FixedClock(),
        )
        assert result_normal.run_manifest.export_hash == result_shuffled.run_manifest.export_hash
        assert result_normal.run_manifest.facts_hash == result_shuffled.run_manifest.facts_hash

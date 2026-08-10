"""Engineering CLI contract, replay dispatch, and the tamper matrix."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from strix.cli import main
from tests.conftest import FixedClock
from tests.engineering.conftest import CLEAN_DIR, TRIAGE_DIR


def run_cli(argv: list[str], clock: FixedClock | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(
        argv,
        input_fn=lambda: (_ for _ in ()).throw(EOFError()),
        stdout=out,
        stderr=err,
        clock=clock or FixedClock(),
        environ={},
    )
    return code, out.getvalue(), err.getvalue()


def compile_argv(input_dir: Path, state_dir: Path, *extra: str) -> list[str]:
    return [
        "engineer",
        "compile",
        str(input_dir),
        "--project-id",
        "SYNTH-CTRL",
        "--as-of",
        "2026-08-09",
        "--state-dir",
        str(state_dir),
        *extra,
    ]


class TestEngineerCompileCli:
    def test_triage_exits_zero_with_quarantine_summary(self, eng_state_dir: Path) -> None:
        code, out, err = run_cli(compile_argv(TRIAGE_DIR, eng_state_dir))
        assert code == 0, err
        assert "[7/7] Exporting verified model" in out
        assert "Relationships verified: 12 (rejected 2)" in out
        assert "dangling_allocation" in out
        assert "revision_conflict" in out
        assert "interfaces.xml#id=IF-3005" in out
        assert "Verification: Completed with rejections" in out
        assert "no CUI, classification, export-control, or CMMC" in out

    def test_strict_exits_one_on_rejections(self, eng_state_dir: Path) -> None:
        code, _, _ = run_cli(compile_argv(TRIAGE_DIR, eng_state_dir, "--strict"))
        assert code == 1

    def test_clean_fixture_passes_under_strict(self, eng_state_dir: Path) -> None:
        code, out, _ = run_cli(compile_argv(CLEAN_DIR, eng_state_dir, "--strict"))
        assert code == 0
        assert "Verification: Passed" in out

    def test_missing_manifest_is_integrity_failure_without_run_dir(
        self, tmp_path: Path, eng_state_dir: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        code, _, err = run_cli(compile_argv(empty, eng_state_dir))
        assert code == 1
        assert "Error [engineering_source_error]:" in err  # machine-readable code
        assert not eng_state_dir.exists() or not any(
            p.name.startswith("RUN-") for p in eng_state_dir.iterdir()
        )

    def test_invalid_project_id_is_integrity_failure(self, eng_state_dir: Path) -> None:
        code, _, err = run_cli(
            [
                "engineer",
                "compile",
                str(TRIAGE_DIR),
                "--project-id",
                "bad id!",
                "--as-of",
                "2026-08-09",
                "--state-dir",
                str(eng_state_dir),
            ]
        )
        assert code == 1
        assert "Error [engineering_source_error]:" in err

    def test_root_position_state_dir_is_honored(self, eng_state_dir: Path) -> None:
        # `strix --state-dir X engineer compile ...` must not be silently
        # clobbered by the subcommand's own (omitted) --state-dir option.
        code, _, err = run_cli(
            [
                "--state-dir",
                str(eng_state_dir),
                "engineer",
                "compile",
                str(TRIAGE_DIR),
                "--project-id",
                "SYNTH-CTRL",
                "--as-of",
                "2026-08-09",
            ]
        )
        assert code == 0, err
        assert any(p.name.startswith("RUN-") for p in eng_state_dir.iterdir())

    def test_sequence_overflow_raises_before_committing_invalid_name(
        self, eng_state_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The 1000th same-day run must fail cleanly, never commit RUN-...-1000.
        from strix.run_store import RunStore

        monkeypatch.setattr(RunStore, "_next_sequence", lambda self, today: 1000)
        code, _, err = run_cli(compile_argv(TRIAGE_DIR, eng_state_dir))
        assert code == 1
        assert "exhausted run IDs" in err
        assert not any(p.name.startswith("RUN-") for p in eng_state_dir.iterdir())

    def test_unwritable_state_dir_is_typed_integrity_failure(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where the state dir should be")
        code, _, err = run_cli(compile_argv(TRIAGE_DIR, blocker))
        assert code == 1
        assert "Error [run_store_error]:" in err
        assert "not writable" in err

    def test_undeclared_files_reported_not_ingested(
        self, triage_copy: Path, eng_state_dir: Path
    ) -> None:
        (triage_copy / "stray-notes.txt").write_text("not declared\n")
        code, out, _ = run_cli(compile_argv(triage_copy, eng_state_dir))
        assert code == 0
        assert "Ignoring undeclared file: stray-notes.txt" in out
        run_dir = next(p for p in eng_state_dir.iterdir() if p.name.startswith("RUN-"))
        assert not (run_dir / "raw" / "stray-notes.txt").exists()


class TestReplayDispatchAndTamper:
    @pytest.fixture
    def compiled(self, eng_state_dir: Path) -> Path:
        code, _, err = run_cli(compile_argv(TRIAGE_DIR, eng_state_dir))
        assert code == 0, err
        return next(p for p in eng_state_dir.iterdir() if p.name.startswith("RUN-"))

    def replay(self, run_dir: Path) -> tuple[int, str, str]:
        return run_cli(["replay", run_dir.name, "--state-dir", str(run_dir.parent)])

    def test_untampered_replay_passes_all_nine_stages(self, compiled: Path) -> None:
        code, out, _ = self.replay(compiled)
        assert code == 0
        assert out.count("matched") == 9
        assert "Result: Deterministic replay passed" in out

    def test_source_byte_change_detected(self, compiled: Path) -> None:
        raw = compiled / "raw" / "components.csv"
        raw.write_bytes(raw.read_bytes().replace(b"Coolant Pump", b"Cooling Pump"))
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Source artifacts hash....... MISMATCH" in out
        assert "components.csv (analysis)" in out

    def test_project_manifest_change_detected_as_input_mismatch(self, compiled: Path) -> None:
        raw = compiled / "raw" / "engineering-project.json"
        raw.write_bytes(raw.read_bytes().replace(b"Synthetic Control System", b"Edited System"))
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Input hash.................. MISMATCH" in out

    def test_ground_truth_change_isolates_to_metrics(self, compiled: Path) -> None:
        raw = compiled / "raw" / "expected-model.json"
        payload = json.loads(raw.read_text())
        payload["elements"] = payload["elements"][:5]
        raw.write_text(json.dumps(payload))
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "expected-model.json (evaluation)" in out
        assert "Metrics hash................ MISMATCH" in out
        # Analysis outputs stay reproducible: model/export still match.
        assert "Model hash.................. matched" in out
        assert "Export hash................. matched" in out
        assert "Anchored facts hash......... matched" in out

    def test_xml_sibling_insertion_reports_anchor_drift(self, compiled: Path) -> None:
        raw = compiled / "raw" / "interfaces.xml"
        raw.write_bytes(
            raw.read_bytes().replace(
                b'<allocation requirement="REQ-101" component="PT-0003"/>',
                b'<allocation requirement="REQ-100" component="PT-0001"/>\n'
                b'  <allocation requirement="REQ-101" component="PT-0003"/>',
            )
        )
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "anchor drift" in out
        assert "/interface-control/allocation[" in out

    def test_csv_row_reorder_detected(self, compiled: Path) -> None:
        raw = compiled / "raw" / "components.csv"
        lines = raw.read_bytes().decode().splitlines()
        reordered = "\n".join([*lines[:2], lines[3], lines[2], *lines[4:]]) + "\n"
        raw.write_bytes(reordered.encode())
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Anchored facts hash......... MISMATCH" in out

    def test_reqif_identifier_change_detected(self, compiled: Path) -> None:
        raw = compiled / "raw" / "requirements.reqif"
        raw.write_bytes(raw.read_bytes().replace(b'"REQ-101"', b'"REQ-901"'))
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Anchored facts hash......... MISMATCH" in out

    def test_text_line_change_detected(self, compiled: Path) -> None:
        raw = compiled / "raw" / "system-description.txt"
        raw.write_bytes(
            raw.read_bytes().replace(b"regulates the temperature", b"guesses the temperature")
        )
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Anchored facts hash......... MISMATCH" in out

    def test_stored_run_artifact_alteration_detected(self, compiled: Path) -> None:
        candidates = compiled / "candidates.json"
        payload = json.loads(candidates.read_text())
        payload["elements"][0]["name"] = "Tampered Controller"
        candidates.write_text(json.dumps(payload, indent=2))
        code, out, _ = self.replay(compiled)
        assert code == 1
        assert "Candidates hash............. MISMATCH (stored artifact differs" in out

    def test_replay_survives_input_directory_deletion(self, tmp_path: Path) -> None:
        input_dir = tmp_path / "input"
        shutil.copytree(TRIAGE_DIR, input_dir)
        state_dir = tmp_path / "runs"
        code, _, err = run_cli(compile_argv(input_dir, state_dir))
        assert code == 0, err
        shutil.rmtree(input_dir)
        run_dir = next(p for p in state_dir.iterdir() if p.name.startswith("RUN-"))
        code, out, _ = self.replay(run_dir)
        assert code == 0
        assert "Result: Deterministic replay passed" in out


class TestV1Compat:
    def test_modeless_manifest_dispatches_to_financial_replay(
        self, state_dir: Path, clock: FixedClock
    ) -> None:
        # Fresh v1 run through the current code, replayed through the new
        # dispatch: must take the v1 path and pass.
        code = main(
            ["--state-dir", str(state_dir)],
            input_fn=iter(["", "", "", ""]).__next__,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            clock=clock,
            environ={},
        )
        assert code == 0
        out = io.StringIO()
        code = main(
            ["replay", "RUN-20260808-001", "--state-dir", str(state_dir)],
            stdout=out,
            stderr=io.StringIO(),
            environ={},
        )
        assert code == 0
        assert "Verification status......... matched" in out.getvalue()

    def test_golden_v1_run_directory_replays(self, tmp_path: Path) -> None:
        # The committed golden run pins the v1 on-disk format.
        golden = Path(__file__).resolve().parents[1] / "data" / "v1-run"
        state_dir = tmp_path / "golden"
        shutil.copytree(golden, state_dir)
        out = io.StringIO()
        code = main(
            ["replay", "RUN-20260808-001", "--state-dir", str(state_dir)],
            stdout=out,
            stderr=io.StringIO(),
            environ={},
        )
        assert code == 0
        assert "Result: Deterministic replay passed" in out.getvalue()

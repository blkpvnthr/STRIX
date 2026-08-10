"""Manifest validation, policy separation, adapters, anchors, byte handling."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from strix.engineering.adapters import adapter_for, parser_versions, schema_versions
from strix.engineering.manifest import (
    MANIFEST_NAME,
    enforce_v2_policy,
    load_project_manifest,
)
from strix.engineering.models import (
    ComponentFact,
    CsvAnchor,
    DescriptionFact,
    NumericPropertyFact,
    ReqIfAnchor,
    RequirementFact,
    SourceFormat,
    TextRangeAnchor,
    XmlIdAnchor,
    XmlPathAnchor,
)
from strix.errors import EngineeringSourceError
from tests.engineering.conftest import TRIAGE_DIR, compute_fixture


def manifest_payload() -> dict:
    return json.loads((TRIAGE_DIR / MANIFEST_NAME).read_bytes())


def entry_for(name: str):
    manifest = load_project_manifest((TRIAGE_DIR / MANIFEST_NAME).read_bytes())
    return next(source for source in manifest.sources if source.file == name)


class TestManifest:
    def test_valid_manifest_loads(self) -> None:
        manifest = load_project_manifest((TRIAGE_DIR / MANIFEST_NAME).read_bytes())
        assert manifest.project_id == "SYNTH-CTRL"
        assert [s.format for s in manifest.sources] == [
            SourceFormat.REQIF,
            SourceFormat.COMPONENT_CSV,
            SourceFormat.INTERFACE_XML,
            SourceFormat.TEXT_DESCRIPTION,
            SourceFormat.CHANGE_NOTICE_CSV,
        ]

    def test_unknown_format_rejected(self) -> None:
        payload = manifest_payload()
        payload["sources"][0]["format"] = "pdf"
        with pytest.raises(EngineeringSourceError, match="schema validation"):
            load_project_manifest(json.dumps(payload).encode())

    def test_duplicate_source_rejected(self) -> None:
        payload = manifest_payload()
        payload["sources"].append(payload["sources"][0])
        with pytest.raises(EngineeringSourceError, match="twice"):
            load_project_manifest(json.dumps(payload).encode())

    def test_missing_notice_rejected(self) -> None:
        payload = manifest_payload()
        del payload["notice"]
        with pytest.raises(EngineeringSourceError, match="schema validation"):
            load_project_manifest(json.dumps(payload).encode())

    def test_policy_refusal_is_distinct_from_schema_error(self) -> None:
        # synthetic: false is VALID schema (future real-data capability)...
        payload = manifest_payload()
        payload["synthetic"] = False
        manifest = load_project_manifest(json.dumps(payload).encode())
        assert manifest.synthetic is False
        # ...but the v2 execution policy refuses to run it.
        with pytest.raises(EngineeringSourceError, match="policy refusal"):
            enforce_v2_policy(manifest)

    def test_policy_refuses_markings_outside_public_synthetic(self) -> None:
        payload = manifest_payload()
        payload["sources"][0]["handling"] = ["PUBLIC", "PROPRIETARY"]
        manifest = load_project_manifest(json.dumps(payload).encode())
        with pytest.raises(EngineeringSourceError, match="policy refusal"):
            enforce_v2_policy(manifest)

    def test_adapter_protocol_conformance(self) -> None:
        for fmt in SourceFormat:
            adapter = adapter_for(fmt)
            assert adapter.format is fmt
            assert adapter.parser_version
            assert adapter.schema_version
        assert set(parser_versions()) == {f.value for f in SourceFormat}
        assert set(schema_versions()) == {f.value for f in SourceFormat}


class TestReqIfAdapter:
    def test_parses_requirements_with_reqif_identifier_anchors(self) -> None:
        entry = entry_for("requirements.reqif")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        result = adapter_for(entry.format).parse(entry, raw)
        assert len(result.facts) == 7
        first = result.facts[0]
        assert isinstance(first.payload, RequirementFact)
        assert isinstance(first.anchor, ReqIfAnchor)
        assert first.anchor.render(entry.file) == "requirements.reqif#reqif-id=REQ-101"

    def test_doctype_rejected(self) -> None:
        entry = entry_for("requirements.reqif")
        raw = b'<?xml version="1.0"?><!DOCTYPE REQ-IF []><REQ-IF/>'
        with pytest.raises(EngineeringSourceError, match="DOCTYPE"):
            adapter_for(entry.format).parse(entry, raw)

    def test_changed_identifier_changes_fact_ids(self) -> None:
        entry = entry_for("requirements.reqif")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        adapter = adapter_for(entry.format)
        original = adapter.parse(entry, raw)
        mutated = adapter.parse(entry, raw.replace(b'"REQ-101"', b'"REQ-201"'))
        assert {f.fact_id for f in original.facts} != {f.fact_id for f in mutated.facts}


class TestComponentCsvAdapter:
    def test_component_and_numeric_facts_with_key_row_anchors(self) -> None:
        entry = entry_for("components.csv")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        result = adapter_for(entry.format).parse(entry, raw)
        assert len(result.facts) == 18  # 6 rows x (component + 2 numerics)
        component = result.facts[0]
        assert isinstance(component.payload, ComponentFact)
        assert isinstance(component.anchor, CsvAnchor)
        assert component.anchor.render(entry.file) == "components.csv#key=PT-0001#row=3"

    def test_numeric_properties_are_decimal_with_lexical_original(self) -> None:
        entry = entry_for("components.csv")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        result = adapter_for(entry.format).parse(entry, raw)
        numerics = [f.payload for f in result.facts if isinstance(f.payload, NumericPropertyFact)]
        mass = next(p for p in numerics if p.subject_id == "PT-0001" and p.property_name == "mass")
        assert isinstance(mass.value, Decimal)
        assert mass.value == Decimal("4.20")
        assert mass.original_value == "4.20"  # lexical spelling preserved
        assert mass.unit == "kg" and mass.original_unit == "kg"

    def test_float_notation_rejected(self) -> None:
        entry = entry_for("components.csv")
        raw = (TRIAGE_DIR / entry.file).read_bytes().replace(b"4.20", b"4.2e0")
        with pytest.raises(EngineeringSourceError, match="plain decimal"):
            adapter_for(entry.format).parse(entry, raw)

    def test_missing_notice_preamble_rejected(self) -> None:
        entry = entry_for("components.csv")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        without_preamble = b"\n".join(raw.split(b"\n")[1:])
        with pytest.raises(EngineeringSourceError, match="preamble"):
            adapter_for(entry.format).parse(entry, without_preamble)

    def test_header_mismatch_rejected(self) -> None:
        entry = entry_for("components.csv")
        raw = (TRIAGE_DIR / entry.file).read_bytes().replace(b"part_id,", b"pid,")
        with pytest.raises(EngineeringSourceError, match="header mismatch"):
            adapter_for(entry.format).parse(entry, raw)


class TestInterfaceXmlAdapter:
    def test_interfaces_anchor_by_id_and_allocations_by_fingerprinted_xpath(
        self,
    ) -> None:
        entry = entry_for("interfaces.xml")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        result = adapter_for(entry.format).parse(entry, raw)
        assert len(result.facts) == 17  # 5 x (interface + connection) + 7 allocations
        id_anchors = [f for f in result.facts if isinstance(f.anchor, XmlIdAnchor)]
        path_anchors = [f for f in result.facts if isinstance(f.anchor, XmlPathAnchor)]
        assert len(id_anchors) == 10 and len(path_anchors) == 7
        first_allocation = path_anchors[0]
        assert first_allocation.anchor.xpath == "/interface-control/allocation[1]"
        assert len(first_allocation.anchor.element_fingerprint) == 64

    def test_sibling_insertion_shifts_xpath_but_not_fingerprints(self) -> None:
        # The fingerprint is the semantic identity; the ordinal XPath is
        # location only. Inserting an earlier sibling shifts every ordinal
        # while the unchanged allocations keep their fingerprints.
        entry = entry_for("interfaces.xml")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        inserted = raw.replace(
            b'<allocation requirement="REQ-101" component="PT-0003"/>',
            b'<allocation requirement="REQ-100" component="PT-0001"/>\n'
            b'  <allocation requirement="REQ-101" component="PT-0003"/>',
        )
        adapter = adapter_for(entry.format)
        original = {
            f.anchor.element_fingerprint: f.anchor.xpath
            for f in adapter.parse(entry, raw).facts
            if isinstance(f.anchor, XmlPathAnchor)
        }
        shifted = {
            f.anchor.element_fingerprint: f.anchor.xpath
            for f in adapter.parse(entry, inserted).facts
            if isinstance(f.anchor, XmlPathAnchor)
        }
        surviving = set(original) & set(shifted)
        assert len(surviving) == 7  # all original allocations still present
        assert any(original[fp] != shifted[fp] for fp in surviving)  # ordinals moved

    def test_unknown_element_rejected(self) -> None:
        entry = entry_for("interfaces.xml")
        raw = (
            (TRIAGE_DIR / entry.file)
            .read_bytes()
            .replace(
                b'<allocation requirement="REQ-107" component="PT-0099"/>',
                b"<mystery/>",
            )
        )
        with pytest.raises(EngineeringSourceError, match="unexpected element"):
            adapter_for(entry.format).parse(entry, raw)


class TestTextDescriptionAdapter:
    def test_marked_paragraphs_anchor_by_line_range_with_paragraph_hash(self) -> None:
        entry = entry_for("system-description.txt")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        result = adapter_for(entry.format).parse(entry, raw)
        assert {
            f.payload.part_id for f in result.facts if isinstance(f.payload, DescriptionFact)
        } == {
            "PT-0001",
            "PT-0002",
            "PT-0006",
        }
        anchor = result.facts[0].anchor
        assert isinstance(anchor, TextRangeAnchor)
        assert anchor.render(entry.file).startswith("system-description.txt#lines=")
        assert len(anchor.paragraph_hash) == 64
        assert result.diagnostics  # unmarked paragraphs are noted, not silent

    def test_changed_text_line_changes_paragraph_hash(self) -> None:
        entry = entry_for("system-description.txt")
        raw = (TRIAGE_DIR / entry.file).read_bytes()
        adapter = adapter_for(entry.format)
        original = adapter.parse(entry, raw)
        mutated = adapter.parse(
            entry, raw.replace(b"coordinates all closed-loop", b"ignores all closed-loop")
        )
        original_hashes = {
            f.anchor.paragraph_hash for f in original.facts if isinstance(f.anchor, TextRangeAnchor)
        }
        mutated_hashes = {
            f.anchor.paragraph_hash for f in mutated.facts if isinstance(f.anchor, TextRangeAnchor)
        }
        assert original_hashes != mutated_hashes


class TestByteHandling:
    def test_crlf_yields_identical_logical_facts_but_different_lineage_ids(
        self,
    ) -> None:
        # LF/CRLF identity contract: logical payloads and anchors equal;
        # content_hash, ART id, and downstream FACT ids differ because facts
        # bind their artifact.
        entry = entry_for("components.csv")
        raw_lf = (TRIAGE_DIR / entry.file).read_bytes()
        raw_crlf = raw_lf.replace(b"\n", b"\r\n")
        adapter = adapter_for(entry.format)
        lf = adapter.parse(entry, raw_lf)
        crlf = adapter.parse(entry, raw_crlf)
        assert [f.payload for f in lf.facts] == [f.payload for f in crlf.facts]
        assert [f.anchor for f in lf.facts] == [f.anchor for f in crlf.facts]
        assert lf.artifact.content_hash != crlf.artifact.content_hash
        assert lf.artifact.artifact_id != crlf.artifact.artifact_id
        assert [f.fact_id for f in lf.facts] != [f.fact_id for f in crlf.facts]

    def test_crlf_text_description_keeps_paragraph_hash_stable(self) -> None:
        entry = entry_for("system-description.txt")
        raw_lf = (TRIAGE_DIR / entry.file).read_bytes()
        raw_crlf = raw_lf.replace(b"\n", b"\r\n")
        adapter = adapter_for(entry.format)
        lf_anchors = [
            f.anchor
            for f in adapter.parse(entry, raw_lf).facts
            if isinstance(f.anchor, TextRangeAnchor)
        ]
        crlf_anchors = [
            f.anchor
            for f in adapter.parse(entry, raw_crlf).facts
            if isinstance(f.anchor, TextRangeAnchor)
        ]
        assert lf_anchors == crlf_anchors  # incl. paragraph_hash

    def test_fact_ids_stable_across_double_parse(self) -> None:
        first = compute_fixture(TRIAGE_DIR)
        second = compute_fixture(TRIAGE_DIR)
        assert [f.fact_id for f in first.facts] == [f.fact_id for f in second.facts]

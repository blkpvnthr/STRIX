"""ReqIF adapter: OMG ReqIF XML subset -> requirement facts.

Parses SPEC-OBJECT elements (IDENTIFIER attribute + one
ATTRIBUTE-VALUE-STRING THE-VALUE) using stdlib ElementTree with
wildcard-namespace matching. Anchors are the ReqIF identifiers themselves.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from strix.engineering.adapters.base import (
    AdapterDiagnostic,
    AdapterResult,
    build_artifact,
    decode_utf8,
    make_fact,
    reject_doctype,
)
from strix.engineering.models import (
    AnchoredFact,
    ManifestSource,
    ReqIfAnchor,
    RequirementFact,
    SourceFormat,
)
from strix.errors import EngineeringSourceError


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class ReqIfAdapter:
    format = SourceFormat.REQIF
    parser_version = "1.0.0"
    schema_version = "1.0.0"

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult:
        reject_doctype(raw, entry.file)
        text = decode_utf8(raw, entry.file)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise EngineeringSourceError(f"{entry.file} is not valid XML: {exc}") from exc
        if _localname(root.tag) != "REQ-IF":
            raise EngineeringSourceError(
                f"{entry.file} root element is {_localname(root.tag)!r}, expected REQ-IF"
            )

        artifact = build_artifact(entry, raw, media_type="application/xml")
        facts: list[AnchoredFact] = []
        seen: set[str] = set()
        spec_objects = root.findall(".//{*}SPEC-OBJECT")
        if not spec_objects:
            raise EngineeringSourceError(f"{entry.file} contains no SPEC-OBJECT records")
        for spec_object in spec_objects:
            identifier = (spec_object.get("IDENTIFIER") or "").strip()
            if not identifier:
                raise EngineeringSourceError(
                    f"{entry.file}: SPEC-OBJECT without an IDENTIFIER attribute"
                )
            if identifier in seen:
                raise EngineeringSourceError(
                    f"{entry.file}: duplicate SPEC-OBJECT identifier {identifier!r}"
                )
            seen.add(identifier)
            value = spec_object.find(".//{*}ATTRIBUTE-VALUE-STRING")
            requirement_text = (value.get("THE-VALUE") or "").strip() if value is not None else ""
            if not requirement_text:
                raise EngineeringSourceError(
                    f"{entry.file}: SPEC-OBJECT {identifier} has no "
                    f"ATTRIBUTE-VALUE-STRING THE-VALUE"
                )
            facts.append(
                make_fact(
                    artifact,
                    ReqIfAnchor(identifier=identifier),
                    RequirementFact(requirement_id=identifier, text=requirement_text),
                )
            )
        diagnostics = (
            AdapterDiagnostic(
                code="spec_objects_parsed",
                message=f"parsed {len(facts)} SPEC-OBJECT records",
            ),
        )
        return AdapterResult(artifact=artifact, facts=tuple(facts), diagnostics=diagnostics)

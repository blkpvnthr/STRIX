"""Interface-control XML adapter -> interface, connection, allocation facts.

A simple ICD XML format (no standard claimed). ``<interface>`` elements carry
an id and anchor by it; id-less ``<allocation>`` elements anchor by ordinal
XPath PLUS a content fingerprint - the XPath is display/location only, and
replay reports fingerprint drift instead of accepting a shifted path as
equivalent evidence.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from strix.canonical import canonical_hash
from strix.engineering.adapters.base import (
    AdapterResult,
    build_artifact,
    decode_utf8,
    make_fact,
    reject_doctype,
)
from strix.engineering.models import (
    AllocationFact,
    AnchoredFact,
    ConnectionFact,
    InterfaceFact,
    ManifestSource,
    SourceFormat,
    XmlIdAnchor,
    XmlPathAnchor,
)
from strix.errors import EngineeringSourceError

_INTERFACE_ATTRS = ("id", "from", "from-rev", "to", "to-rev", "medium")
_ALLOCATION_ATTRS = ("requirement", "component")


def element_fingerprint(element: ET.Element) -> str:
    """Deterministic structural/content fingerprint of one XML element."""
    return canonical_hash(
        {
            "tag": element.tag,
            "attrs": dict(sorted(element.attrib.items())),
            "text": (element.text or "").strip(),
        }
    )


def _required_attrs(element: ET.Element, names: tuple[str, ...], filename: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in names:
        value = (element.get(name) or "").strip()
        if not value:
            raise EngineeringSourceError(
                f"{filename}: <{element.tag}> element missing required attribute {name!r}"
            )
        values[name] = value
    return values


class InterfaceXmlAdapter:
    format = SourceFormat.INTERFACE_XML
    parser_version = "1.0.0"
    schema_version = "1.0.0"

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult:
        reject_doctype(raw, entry.file)
        text = decode_utf8(raw, entry.file)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise EngineeringSourceError(f"{entry.file} is not valid XML: {exc}") from exc
        if root.tag != "interface-control":
            raise EngineeringSourceError(
                f"{entry.file} root element is {root.tag!r}, expected interface-control"
            )

        artifact = build_artifact(entry, raw, media_type="application/xml")
        facts: list[AnchoredFact] = []
        seen_interface_ids: set[str] = set()
        allocation_ordinal = 0
        for child in root:
            if child.tag == "interface":
                attrs = _required_attrs(child, _INTERFACE_ATTRS, entry.file)
                if attrs["id"] in seen_interface_ids:
                    raise EngineeringSourceError(
                        f"{entry.file}: duplicate interface id {attrs['id']!r}"
                    )
                seen_interface_ids.add(attrs["id"])
                anchor: XmlIdAnchor | XmlPathAnchor = XmlIdAnchor(id=attrs["id"])
                facts.append(
                    make_fact(
                        artifact,
                        anchor,
                        InterfaceFact(interface_id=attrs["id"], medium=attrs["medium"]),
                    )
                )
                facts.append(
                    make_fact(
                        artifact,
                        anchor,
                        ConnectionFact(
                            interface_id=attrs["id"],
                            from_part=attrs["from"],
                            from_revision=attrs["from-rev"],
                            to_part=attrs["to"],
                            to_revision=attrs["to-rev"],
                        ),
                    )
                )
            elif child.tag == "allocation":
                allocation_ordinal += 1
                attrs = _required_attrs(child, _ALLOCATION_ATTRS, entry.file)
                anchor = XmlPathAnchor(
                    xpath=f"/interface-control/allocation[{allocation_ordinal}]",
                    element_fingerprint=element_fingerprint(child),
                )
                facts.append(
                    make_fact(
                        artifact,
                        anchor,
                        AllocationFact(
                            requirement_id=attrs["requirement"],
                            part_id=attrs["component"],
                        ),
                    )
                )
            else:
                raise EngineeringSourceError(
                    f"{entry.file}: unexpected element <{child.tag}> under interface-control"
                )
        if not facts:
            raise EngineeringSourceError(f"{entry.file} contains no records")
        return AdapterResult(artifact=artifact, facts=tuple(facts), diagnostics=())

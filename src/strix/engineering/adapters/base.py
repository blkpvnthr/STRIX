"""Adapter protocol, shared parsing helpers, and the format registry.

The preserved source BYTES are authoritative; adapter output is derived.
Each adapter therefore records a ``parser_version`` and ``schema_version``
in run metadata so replay can report when identical bytes are interpreted
differently by a later implementation. Versions never enter content-derived
identity.

Byte handling: CRLF is never rejected. Raw bytes are preserved and hashed
exactly; line endings are normalized only here, inside parsing. An LF and a
CRLF encoding of the same logical content yield identical logical payloads
and anchors but different artifact hashes - and therefore different
downstream lineage IDs, because facts bind their artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from strix.canonical import make_id, sha256_hex
from strix.engineering.models import (
    Anchor,
    AnchoredFact,
    EngineeringArtifact,
    FactPayload,
    ManifestSource,
    SourceFormat,
)
from strix.errors import EngineeringSourceError
from strix.models import StrixModel


class AdapterDiagnostic(StrixModel):
    """A typed, non-fatal note produced while parsing a source."""

    code: str
    message: str
    anchor: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    """Everything an adapter derives from one preserved source."""

    artifact: EngineeringArtifact
    facts: tuple[AnchoredFact, ...]
    diagnostics: tuple[AdapterDiagnostic, ...]


class SourceAdapter(Protocol):
    """Parses preserved raw bytes of one declared source into anchored facts."""

    format: SourceFormat
    parser_version: str
    schema_version: str

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult: ...


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def decode_utf8(raw: bytes, filename: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EngineeringSourceError(f"{filename} is not valid UTF-8: {exc}") from exc


def logical_lines(text: str) -> list[str]:
    """Physical lines with line endings normalized away (LF/CRLF agnostic)."""
    return text.splitlines()


def reject_doctype(raw: bytes, filename: str) -> None:
    """No DTD/XXE surface: refuse XML input containing DOCTYPE/ENTITY tokens.

    XXE and entity-expansion (billion-laughs) attacks both require a DTD.
    XML requires these tokens in exact uppercase; with them rejected up
    front, stdlib ElementTree/expat has no entity definitions to expand and
    errors out on any undefined entity reference, so no external fetch or
    expansion path remains. This keeps the offline prototype dependency-free
    (no defusedxml) while closing the attack surface; the guard runs before
    any parser sees the bytes.
    """
    for token in (b"<!DOCTYPE", b"<!ENTITY"):
        if token in raw:
            raise EngineeringSourceError(
                f"{filename} contains a {token.decode()} declaration, which is not permitted"
            )


def build_artifact(entry: ManifestSource, raw: bytes, media_type: str) -> EngineeringArtifact:
    content_hash = sha256_hex(raw)
    return EngineeringArtifact(
        artifact_id=make_id(
            "ART",
            {
                "source_name": entry.file,
                "source_format": entry.format,
                "document_id": entry.document_id,
                "document_revision": entry.revision,
                "content_hash": content_hash,
            },
        ),
        source_name=entry.file,
        source_format=entry.format,
        document_id=entry.document_id,
        document_revision=entry.revision,
        media_type=media_type,
        content_hash=content_hash,
        byte_size=len(raw),
        local_path=f"raw/{entry.file}",
        handling=tuple(sorted(entry.handling)),
    )


def make_fact(artifact: EngineeringArtifact, anchor: Anchor, payload: FactPayload) -> AnchoredFact:
    """Build a fact bound to its physical artifact and logical anchor."""
    fact_id = make_id(
        "FACT",
        {
            "artifact_id": artifact.artifact_id,
            "anchor": anchor.model_dump(),
            "payload": payload.model_dump(),
        },
    )
    return AnchoredFact(
        fact_id=fact_id, artifact_id=artifact.artifact_id, anchor=anchor, payload=payload
    )


def split_strict_csv(
    lines: list[str], filename: str, expected_header: tuple[str, ...]
) -> list[tuple[int, list[str]]]:
    """Validate the one-preamble-line CSV schema; return (physical_line, cells).

    Schema: line 1 is exactly one synthetic-notice preamble starting "# ";
    line 2 is the header (must equal ``expected_header``); data rows follow.
    This adapter's minimal dialect forbids quoting and embedded separators.
    """
    if len(lines) < 3:
        raise EngineeringSourceError(
            f"{filename} must contain a notice line, a header, and at least one row"
        )
    if not lines[0].startswith("# "):
        raise EngineeringSourceError(
            f"{filename} line 1 must be a '# '-prefixed synthetic-notice preamble"
        )
    header = [cell.strip() for cell in lines[1].split(",")]
    if header != list(expected_header):
        raise EngineeringSourceError(
            f"{filename} header mismatch: expected {list(expected_header)}, got {header}"
        )
    rows: list[tuple[int, list[str]]] = []
    for index, line in enumerate(lines[2:], start=3):
        if not line.strip():
            continue
        if '"' in line:
            raise EngineeringSourceError(
                f"{filename} line {index}: quoted fields are not supported by "
                f"this adapter's CSV dialect"
            )
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) != len(expected_header):
            raise EngineeringSourceError(
                f"{filename} line {index}: expected {len(expected_header)} "
                f"columns, got {len(cells)}"
            )
        if any(not cell for cell in cells):
            raise EngineeringSourceError(f"{filename} line {index}: empty cell")
        rows.append((index, cells))
    return rows


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def _registry() -> dict[SourceFormat, SourceAdapter]:
    from strix.engineering.adapters.change_notice_csv import ChangeNoticeCsvAdapter
    from strix.engineering.adapters.component_csv import ComponentCsvAdapter
    from strix.engineering.adapters.interface_xml import InterfaceXmlAdapter
    from strix.engineering.adapters.reqif import ReqIfAdapter
    from strix.engineering.adapters.text_description import TextDescriptionAdapter

    adapters: tuple[SourceAdapter, ...] = (
        ReqIfAdapter(),
        ComponentCsvAdapter(),
        InterfaceXmlAdapter(),
        TextDescriptionAdapter(),
        ChangeNoticeCsvAdapter(),
    )
    return {adapter.format: adapter for adapter in adapters}


def adapter_for(source_format: SourceFormat) -> SourceAdapter:
    """Dispatch by declared manifest format."""
    registry = _registry()
    if source_format not in registry:  # pragma: no cover - enum-closed today
        raise EngineeringSourceError(f"no adapter for format {source_format!r}")
    return registry[source_format]


def parser_versions() -> dict[str, str]:
    """format -> parser_version, for run metadata (never identity)."""
    return {fmt.value: adapter.parser_version for fmt, adapter in _registry().items()}


def schema_versions() -> dict[str, str]:
    """format -> input-schema version, for run metadata (never identity)."""
    return {fmt.value: adapter.schema_version for fmt, adapter in _registry().items()}

"""Structured TXT adapter -> description facts.

Paragraphs are blank-line-delimited blocks of physical lines. A paragraph
containing explicit ``[part: PT-####]`` markers yields one description fact
per distinct marked part (deterministic scan - no NLP). Anchors carry the
1-based physical line range plus a paragraph content hash computed after
line-ending normalization, so the anchor is LF/CRLF-stable and
content-verifiable.
"""

from __future__ import annotations

import re

from strix.canonical import canonical_hash
from strix.engineering.adapters.base import (
    AdapterDiagnostic,
    AdapterResult,
    build_artifact,
    decode_utf8,
    logical_lines,
    make_fact,
)
from strix.engineering.models import (
    AnchoredFact,
    DescriptionFact,
    ManifestSource,
    SourceFormat,
    TextRangeAnchor,
)
from strix.errors import EngineeringSourceError

_MARKER_RE = re.compile(r"\[part:\s*([A-Za-z0-9\-]+)\]")


def paragraph_hash(paragraph_text: str) -> str:
    """Content hash of a normalized paragraph (LF/CRLF-stable)."""
    return canonical_hash(paragraph_text)


def _paragraphs(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start_line, end_line, normalized_text) for each non-blank block."""
    blocks: list[tuple[int, int, str]] = []
    start: int | None = None
    buffer: list[str] = []
    for index, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = index
            buffer.append(line.rstrip())
        elif start is not None:
            blocks.append((start, index - 1, "\n".join(buffer)))
            start, buffer = None, []
    if start is not None:
        blocks.append((start, len(lines), "\n".join(buffer)))
    return blocks


class TextDescriptionAdapter:
    format = SourceFormat.TEXT_DESCRIPTION
    parser_version = "1.0.0"
    schema_version = "1.0.0"

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult:
        text = decode_utf8(raw, entry.file)
        lines = logical_lines(text)
        if not lines or "SYNTHETIC" not in lines[0].upper():
            raise EngineeringSourceError(
                f"{entry.file} line 1 must be a synthetic-notice header line"
            )
        artifact = build_artifact(entry, raw, media_type="text/plain")
        facts: list[AnchoredFact] = []
        diagnostics: list[AdapterDiagnostic] = []
        for start, end, paragraph in _paragraphs(lines):
            markers: list[str] = []
            for match in _MARKER_RE.finditer(paragraph):
                part_id = match.group(1)
                if part_id not in markers:
                    markers.append(part_id)
            anchor = TextRangeAnchor(
                start_line=start, end_line=end, paragraph_hash=paragraph_hash(paragraph)
            )
            if not markers:
                diagnostics.append(
                    AdapterDiagnostic(
                        code="unmarked_paragraph",
                        message="paragraph carries no [part: ...] marker; no fact extracted",
                        anchor=anchor.render(entry.file),
                    )
                )
                continue
            facts.extend(
                make_fact(
                    artifact,
                    anchor,
                    DescriptionFact(part_id=part_id, excerpt=paragraph),
                )
                for part_id in markers
            )
        return AdapterResult(artifact=artifact, facts=tuple(facts), diagnostics=tuple(diagnostics))

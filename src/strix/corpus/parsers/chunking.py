"""Deterministic, paragraph-aware chunking of normalized physical lines.

No tokenizer is used anywhere here -- GPT's or any other provider's. Size
is measured only in deterministic character and UTF-8 byte counts, named
accordingly (``char_count``, ``byte_size``), never called a "token count".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from strix.canonical import make_id, sha256_hex
from strix.corpus.parsers.models import AnchorType, DocumentAnchor, DocumentChunk
from strix.errors import ParseIntegrityError

#: Version of the paragraph-grouping + splitting policy below. Bump this
#: whenever its observable output changes -- every DocumentChunk records
#: this value, and it participates in every chunk_id.
CHUNKING_POLICY_VERSION = "1.0.0"


class ChunkLimitExceededError(Exception):
    """Internal signal only -- callers (TextParser) catch this and turn
    it into a typed ParseFailure; it never escapes this package."""


@dataclass(frozen=True)
class _Paragraph:
    #: 1-based line number of this paragraph's first line.
    start_line: int
    lines: tuple[str, ...]


def _group_into_paragraphs(lines: Sequence[str]) -> tuple[_Paragraph, ...]:
    """Group consecutive non-blank physical lines into paragraphs.

    A blank line (empty after trailing-whitespace normalization) never
    belongs to a paragraph -- it only separates the ones on either side.
    Leading/trailing blank lines in the document belong to no paragraph.
    """
    paragraphs: list[_Paragraph] = []
    current_lines: list[str] = []
    current_start = 0
    for index, line in enumerate(lines, start=1):
        if line == "":
            if current_lines:
                paragraphs.append(_Paragraph(start_line=current_start, lines=tuple(current_lines)))
                current_lines = []
            continue
        if not current_lines:
            current_start = index
        current_lines.append(line)
    if current_lines:
        paragraphs.append(_Paragraph(start_line=current_start, lines=tuple(current_lines)))
    return tuple(paragraphs)


def _split_paragraph(
    paragraph: _Paragraph, max_chars: int
) -> list[tuple[int, int, tuple[str, ...]]]:
    """Split one paragraph into (start_line, end_line, lines) groups.

    Each group's joined text stays within max_chars where possible. A
    single line that alone exceeds max_chars still becomes its own group
    -- this never splits within a line, since DocumentAnchor has no
    sub-line (character-offset) granularity to represent that.
    """
    groups: list[tuple[int, int, tuple[str, ...]]] = []
    group_lines: list[str] = []
    group_start = paragraph.start_line
    for offset, line in enumerate(paragraph.lines):
        line_number = paragraph.start_line + offset
        candidate = (*group_lines, line)
        if group_lines and len(_join(candidate)) > max_chars:
            groups.append((group_start, group_start + len(group_lines) - 1, tuple(group_lines)))
            group_lines = [line]
            group_start = line_number
        else:
            group_lines = list(candidate)
    if group_lines:
        groups.append((group_start, group_start + len(group_lines) - 1, tuple(group_lines)))
    return groups


def _join(lines: Sequence[str]) -> str:
    return "\n".join(lines)


def compute_chunk_id(
    document_id: str,
    anchor: DocumentAnchor,
    normalized_content_hash: str,
    chunking_policy_version: str,
) -> str:
    """Content-derived chunk identity: document, anchor, content hash, and
    chunking-policy version -- no wall clock, no sequence index (an
    anchor's line range is already unique within one document)."""
    return make_id(
        "CHUNK",
        {
            "document_id": document_id,
            "anchor": anchor,
            "normalized_content_hash": normalized_content_hash,
            "chunking_policy_version": chunking_policy_version,
        },
    )


def chunk_document(
    document_id: str,
    lines: Sequence[str],
    *,
    max_chunk_characters: int,
    max_chunks: int,
    parser_version: str,
) -> tuple[DocumentChunk, ...]:
    """Deterministically chunk already decoded, normalized *lines*.

    Raises :class:`ChunkLimitExceededError` (caught by the parser, turned
    into a typed ParseFailure) if the result would exceed *max_chunks*.
    Self-verifies every chunk against *lines* before returning (see
    :func:`verify_chunks_resolve_to_source`) -- a bug here fails loudly
    rather than silently producing a chunk that doesn't match its source.
    """
    chunks: list[DocumentChunk] = []
    for paragraph in _group_into_paragraphs(lines):
        for start_line, end_line, group_lines in _split_paragraph(paragraph, max_chunk_characters):
            if len(chunks) >= max_chunks:
                raise ChunkLimitExceededError(max_chunks)
            text = _join(group_lines)
            normalized_hash = sha256_hex(text.encode("utf-8"))
            anchor = DocumentAnchor(
                document_id=document_id,
                anchor_type=AnchorType.LINE_RANGE,
                start_line=start_line,
                end_line=end_line,
                normalized_content_hash=normalized_hash,
                parser_version=parser_version,
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=compute_chunk_id(
                        document_id, anchor, normalized_hash, CHUNKING_POLICY_VERSION
                    ),
                    document_id=document_id,
                    sequence_index=len(chunks),
                    anchor=anchor,
                    text=text,
                    normalized_content_hash=normalized_hash,
                    byte_size=len(text.encode("utf-8")),
                    char_count=len(text),
                    chunking_policy_version=CHUNKING_POLICY_VERSION,
                )
            )
    ordered = tuple(chunks)
    verify_chunks_resolve_to_source(lines, ordered)
    return ordered


def verify_chunks_resolve_to_source(lines: Sequence[str], chunks: Sequence[DocumentChunk]) -> None:
    """Independently verify every chunk resolves to its declared source.

    For each chunk, re-derives the text its anchor's [start_line, end_line]
    range names from *lines* and requires it to equal the chunk's own
    ``text`` exactly. Also rejects any anchor citing a line outside the
    document (before line 1, or past the end). Raises
    :class:`~strix.errors.ParseIntegrityError` on any mismatch; never
    repairs or rewrites anything -- this is a check, not a correction.
    """
    total_lines = len(lines)
    for chunk in chunks:
        start, end = chunk.anchor.start_line, chunk.anchor.end_line
        if start < 1 or end > total_lines:
            raise ParseIntegrityError(
                f"chunk {chunk.chunk_id!r} anchor [{start}, {end}] cites a line outside "
                f"the document's {total_lines} lines"
            )
        expected_text = _join(lines[start - 1 : end])
        if expected_text != chunk.text:
            raise ParseIntegrityError(
                f"chunk {chunk.chunk_id!r} text does not match source lines [{start}, {end}]"
            )

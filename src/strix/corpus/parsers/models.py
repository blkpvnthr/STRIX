"""Typed models for the parser registry, parse requests/results, and
TXT/Markdown source anchors and chunks.

Lineage for this phase:

    preserved bytes -> decode + normalize -> physical lines
    -> paragraph-aware chunks -> DocumentAnchor + DocumentChunk
    -> ParseResult

Every anchor/chunk hash is independently re-verifiable from its own
content (see the model validators below and
:func:`strix.corpus.parsers.chunking.verify_chunks_resolve_to_source` for
the stronger, source-line-level check that needs the full document).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from strix.canonical import sha256_hex
from strix.corpus.models import CorpusModel


class AnchorType(StrEnum):
    #: Physical 1-based line range — the only anchor type this phase
    #: produces (TXT and Markdown are both anchored as plain text).
    LINE_RANGE = "line_range"


class ParserCapability(CorpusModel):
    """What one registered parser declares it can do.

    Registering a capability is the *only* way a ``(parser_name,
    parser_version)`` is ever associated with an extension — nothing
    infers parser support from the scanner's broader allow-list.
    """

    parser_name: str = Field(min_length=1)
    parser_version: str
    supported_extensions: tuple[str, ...] = Field(min_length=1)
    anchor_type: AnchorType


class ParseLimits(CorpusModel):
    """Configurable bounds on one parse."""

    #: Decoded (post-UTF-8) character count above which parsing fails.
    max_decoded_characters: int = Field(default=5_000_000, ge=1)
    #: Physical line count above which parsing fails.
    max_lines: int = Field(default=200_000, ge=1)
    #: Target maximum characters per chunk. A single physical line that
    #: alone exceeds this still becomes its own one-line chunk — this
    #: phase never splits within a line (the anchor model has no sub-line
    #: granularity) — but any chunk spanning more than one line is kept
    #: within this bound.
    max_chunk_characters: int = Field(default=4000, ge=1)
    #: Total chunks for one document above which parsing fails.
    max_chunks: int = Field(default=10_000, ge=1)


class ParseRequest(CorpusModel):
    """One request to parse a single preserved document."""

    corpus_id: str
    document_id: str
    relative_path: str
    #: Expected hash (from the document's DocumentArtifact) — the parser
    #: independently re-verifies the bytes it is given against this
    #: before parsing anything.
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: ParseLimits = ParseLimits()


class ParseFailureCode(StrEnum):
    #: No parser is registered for the document's extension — distinct
    #: from every content-level failure below.
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"
    INVALID_ENCODING = "invalid_encoding"
    DECODED_CHARACTER_LIMIT_EXCEEDED = "decoded_character_limit_exceeded"
    LINE_LIMIT_EXCEEDED = "line_limit_exceeded"
    CHUNK_LIMIT_EXCEEDED = "chunk_limit_exceeded"
    SOURCE_UNREADABLE = "source_unreadable"


class ParseFailure(CorpusModel):
    code: ParseFailureCode
    message: str


class ParseStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentAnchor(CorpusModel):
    """A physical source-line range within one document."""

    document_id: str
    anchor_type: AnchorType
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    #: SHA-256 of the exact normalized text the anchor spans.
    normalized_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str

    @model_validator(mode="after")
    def _ordered(self) -> DocumentAnchor:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class DocumentChunk(CorpusModel):
    """One chunk of anchored text, content-addressed."""

    chunk_id: str
    document_id: str
    #: 0-based position among this document's chunks. Together with the
    #: ParseResult-level ordering check, this is the validated ordering
    #: invariant: sequence_index must equal position in the chunks tuple.
    sequence_index: int = Field(ge=0)
    anchor: DocumentAnchor
    text: str
    #: Must equal both sha256(text) and anchor.normalized_content_hash —
    #: enforced below, independently of how the chunk was constructed.
    normalized_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: Deterministic UTF-8 byte count of `text`. Not a token count — no
    #: tokenizer (GPT's or otherwise) is used anywhere in this phase.
    byte_size: int = Field(ge=0)
    #: Deterministic character count of `text`.
    char_count: int = Field(ge=0)
    chunking_policy_version: str

    @model_validator(mode="after")
    def _document_id_matches_anchor(self) -> DocumentChunk:
        if self.document_id != self.anchor.document_id:
            raise ValueError("chunk document_id must match its anchor's document_id")
        return self

    @model_validator(mode="after")
    def _hash_matches_recomputed_content(self) -> DocumentChunk:
        expected = sha256_hex(self.text.encode("utf-8"))
        if self.normalized_content_hash != expected:
            raise ValueError("normalized_content_hash does not match the recomputed hash of text")
        if self.anchor.normalized_content_hash != expected:
            raise ValueError(
                "anchor.normalized_content_hash does not match the recomputed hash of text"
            )
        return self

    @model_validator(mode="after")
    def _sizes_match_recomputed_content(self) -> DocumentChunk:
        if self.byte_size != len(self.text.encode("utf-8")):
            raise ValueError("byte_size does not match the recomputed UTF-8 byte length of text")
        if self.char_count != len(self.text):
            raise ValueError("char_count does not match the recomputed character length of text")
        return self


class ParseResult(CorpusModel):
    """Outcome of parsing one document. Identifies the document, the
    parser (when one was dispatched), success/failure, every chunk
    produced, warnings, and a typed failure when applicable."""

    document_id: str
    #: None only when no parser was ever dispatched (UNSUPPORTED_CAPABILITY
    #: or a pre-dispatch I/O failure) — a parser-level failure (bad
    #: encoding, a limit exceeded, a hash mismatch found by the parser
    #: itself) still identifies the parser that detected it.
    parser_name: str | None
    parser_version: str | None
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ParseStatus
    total_lines: int = Field(ge=0)
    #: Stable, validated order — see the validators below.
    chunks: tuple[DocumentChunk, ...] = ()
    warnings: tuple[str, ...] = ()
    failure: ParseFailure | None = None
    normalization_policy_version: str | None = None
    chunking_policy_version: str | None = None

    @model_validator(mode="after")
    def _status_matches_content(self) -> ParseResult:
        if self.status is ParseStatus.SUCCEEDED and self.failure is not None:
            raise ValueError("a succeeded result must not carry a failure")
        if self.status is ParseStatus.FAILED and self.failure is None:
            raise ValueError("a failed result must carry a failure")
        if self.status is ParseStatus.FAILED and self.chunks:
            raise ValueError("a failed result must not carry chunks")
        return self

    @model_validator(mode="after")
    def _chunks_are_ordered_in_range_and_non_overlapping(self) -> ParseResult:
        # This phase never permits overlap; there is no policy flag that
        # records or allows it, so any overlap or out-of-order pair is
        # rejected outright.
        for index, chunk in enumerate(self.chunks):
            if chunk.sequence_index != index:
                raise ValueError("chunks must be ordered: sequence_index must match position")
            if chunk.document_id != self.document_id:
                raise ValueError("chunk document_id must match the result's document_id")
            if chunk.anchor.start_line < 1 or chunk.anchor.end_line > self.total_lines:
                raise ValueError(
                    f"chunk anchor [{chunk.anchor.start_line}, {chunk.anchor.end_line}] "
                    f"cites a line outside the document's {self.total_lines} lines"
                )
        for previous, current in zip(self.chunks, self.chunks[1:], strict=False):
            if current.anchor.start_line <= previous.anchor.end_line:
                raise ValueError(
                    "chunks must not overlap or go out of order: "
                    f"chunk ending at line {previous.anchor.end_line} is followed by one "
                    f"starting at line {current.anchor.start_line}"
                )
        return self

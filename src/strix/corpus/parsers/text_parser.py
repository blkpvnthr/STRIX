"""The TXT/Markdown parser: deterministic UTF-8 decode -> normalize ->
paragraph-aware chunk. Markdown is treated purely as anchored text in
this phase -- no rendering, heading/link interpretation, or other
semantic rewriting."""

from __future__ import annotations

from typing import Protocol

from strix.canonical import sha256_hex
from strix.corpus.parsers.chunking import (
    CHUNKING_POLICY_VERSION,
    ChunkLimitExceededError,
    chunk_document,
)
from strix.corpus.parsers.models import (
    AnchorType,
    ParseFailure,
    ParseFailureCode,
    ParserCapability,
    ParseRequest,
    ParseResult,
    ParseStatus,
)
from strix.corpus.parsers.normalize import (
    NORMALIZATION_POLICY_VERSION,
    decode_utf8,
    normalize_text,
)


class Parser(Protocol):
    """The seam a document parser plugs into the registry through."""

    capability: ParserCapability

    def parse(self, request: ParseRequest, raw_bytes: bytes) -> ParseResult: ...


class TextParser:
    """Deterministic UTF-8 text parser for .txt/.md/.markdown."""

    PARSER_NAME = "text"
    PARSER_VERSION = "1.0.0"

    def __init__(self) -> None:
        self.capability = ParserCapability(
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            supported_extensions=(".txt", ".md", ".markdown"),
            anchor_type=AnchorType.LINE_RANGE,
        )

    def parse(self, request: ParseRequest, raw_bytes: bytes) -> ParseResult:
        actual_hash = sha256_hex(raw_bytes)
        if actual_hash != request.content_hash:
            return self._failure(
                request,
                actual_hash,
                ParseFailureCode.CONTENT_HASH_MISMATCH,
                f"preserved bytes hash {actual_hash!r} does not match the recorded "
                f"document hash {request.content_hash!r}",
            )

        try:
            text = decode_utf8(raw_bytes)
        except UnicodeDecodeError as exc:
            return self._failure(request, actual_hash, ParseFailureCode.INVALID_ENCODING, str(exc))

        if len(text) > request.limits.max_decoded_characters:
            return self._failure(
                request,
                actual_hash,
                ParseFailureCode.DECODED_CHARACTER_LIMIT_EXCEEDED,
                f"{len(text)} decoded characters exceeds the "
                f"{request.limits.max_decoded_characters}-character limit",
            )

        lines = normalize_text(text)
        if len(lines) > request.limits.max_lines:
            return self._failure(
                request,
                actual_hash,
                ParseFailureCode.LINE_LIMIT_EXCEEDED,
                f"{len(lines)} lines exceeds the {request.limits.max_lines}-line limit",
            )

        warnings: list[str] = []
        for index, line in enumerate(lines, start=1):
            if len(line) > request.limits.max_chunk_characters:
                warnings.append(
                    f"line {index} is {len(line)} characters, exceeding "
                    f"max_chunk_characters ({request.limits.max_chunk_characters}); "
                    "kept as a single oversized chunk since this phase never splits "
                    "within a line"
                )

        try:
            chunks = chunk_document(
                request.document_id,
                lines,
                max_chunk_characters=request.limits.max_chunk_characters,
                max_chunks=request.limits.max_chunks,
                parser_version=self.PARSER_VERSION,
            )
        except ChunkLimitExceededError:
            return self._failure(
                request,
                actual_hash,
                ParseFailureCode.CHUNK_LIMIT_EXCEEDED,
                f"document would produce more than {request.limits.max_chunks} chunks",
            )

        if lines and not chunks:
            warnings.append("document contains no non-blank lines to chunk")
        elif not lines:
            warnings.append("document is empty")

        return ParseResult(
            document_id=request.document_id,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            source_content_hash=actual_hash,
            status=ParseStatus.SUCCEEDED,
            total_lines=len(lines),
            chunks=chunks,
            warnings=tuple(warnings),
            normalization_policy_version=NORMALIZATION_POLICY_VERSION,
            chunking_policy_version=CHUNKING_POLICY_VERSION,
        )

    def _failure(
        self,
        request: ParseRequest,
        actual_hash: str,
        code: ParseFailureCode,
        message: str,
    ) -> ParseResult:
        return ParseResult(
            document_id=request.document_id,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            source_content_hash=actual_hash,
            status=ParseStatus.FAILED,
            total_lines=0,
            chunks=(),
            failure=ParseFailure(code=code, message=message),
            normalization_policy_version=NORMALIZATION_POLICY_VERSION,
            chunking_policy_version=CHUNKING_POLICY_VERSION,
        )

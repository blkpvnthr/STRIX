"""The parser registry: explicit extension -> parser capability lookup,
and parse_corpus(), which parses every document in a manifest through it.

The registry is the *only* source of truth for "is there a parser for
this extension" -- the scanner's broader DEFAULT_SUPPORTED_EXTENSIONS
allow-list from Phase 2 is a discovery-time classification only and is
never consulted here or treated as implying support.
"""

from __future__ import annotations

from pathlib import Path

from strix.corpus.models import CorpusManifest, DocumentArtifact
from strix.corpus.parsers.models import (
    ParseFailure,
    ParseFailureCode,
    ParseLimits,
    ParserCapability,
    ParseRequest,
    ParseResult,
    ParseStatus,
)
from strix.corpus.parsers.text_parser import Parser, TextParser
from strix.corpus.snapshot import CorpusStore


class ParserRegistry:
    """Explicit extension -> parser capability registration and lookup."""

    def __init__(self) -> None:
        self._parsers_by_extension: dict[str, Parser] = {}

    def register(self, parser: Parser) -> None:
        for extension in parser.capability.supported_extensions:
            self._parsers_by_extension[extension.lower()] = parser

    def capabilities(self) -> tuple[ParserCapability, ...]:
        """Every distinct registered capability, for explicit introspection."""
        seen: dict[str, ParserCapability] = {}
        for parser in self._parsers_by_extension.values():
            seen[parser.capability.parser_name] = parser.capability
        return tuple(seen.values())

    def capability_for(self, extension: str) -> ParserCapability | None:
        parser = self._parsers_by_extension.get(extension.lower())
        return parser.capability if parser is not None else None

    def parser_for(self, extension: str) -> Parser | None:
        return self._parsers_by_extension.get(extension.lower())


def default_registry() -> ParserRegistry:
    """A registry with this phase's one built-in parser registered."""
    registry = ParserRegistry()
    registry.register(TextParser())
    return registry


def parse_corpus(
    store: CorpusStore,
    manifest: CorpusManifest,
    registry: ParserRegistry,
    *,
    limits: ParseLimits | None = None,
) -> tuple[ParseResult, ...]:
    """Parse every document in *manifest*, in order, through *registry*.

    Reads each document's bytes from *store* -- the preserved snapshot,
    never the live evidence root. A failure parsing one document
    (unsupported extension, invalid encoding, a limit exceeded, a hash
    mismatch, an unreadable preserved copy) produces a FAILED ParseResult
    for that document only; it is never raised, and never stops the
    remaining documents in *manifest* from being parsed.
    """
    resolved_limits = limits if limits is not None else ParseLimits()
    return tuple(
        _parse_one(store, manifest.corpus_id, document, registry, resolved_limits)
        for document in manifest.documents
    )


def _parse_one(
    store: CorpusStore,
    corpus_id: str,
    document: DocumentArtifact,
    registry: ParserRegistry,
    limits: ParseLimits,
) -> ParseResult:
    extension = Path(document.relative_path).suffix.lower()
    parser = registry.parser_for(extension)
    if parser is None:
        return ParseResult(
            document_id=document.document_id,
            parser_name=None,
            parser_version=None,
            source_content_hash=document.content_hash,
            status=ParseStatus.FAILED,
            total_lines=0,
            failure=ParseFailure(
                code=ParseFailureCode.UNSUPPORTED_CAPABILITY,
                message=f"no parser is registered for extension {extension!r} "
                f"(document {document.relative_path!r})",
            ),
        )

    try:
        raw_bytes = store.read_document(corpus_id, document.relative_path)
    except OSError as exc:
        return ParseResult(
            document_id=document.document_id,
            parser_name=None,
            parser_version=None,
            source_content_hash=document.content_hash,
            status=ParseStatus.FAILED,
            total_lines=0,
            failure=ParseFailure(
                code=ParseFailureCode.SOURCE_UNREADABLE,
                message=f"could not read preserved document {document.relative_path!r}: {exc}",
            ),
        )

    request = ParseRequest(
        corpus_id=corpus_id,
        document_id=document.document_id,
        relative_path=document.relative_path,
        content_hash=document.content_hash,
        limits=limits,
    )
    return parser.parse(request, raw_bytes)

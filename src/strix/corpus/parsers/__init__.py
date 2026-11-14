"""Deterministic parsing of preserved corpus snapshots.

Phase 6 of the neuro-symbolic platform. Parsers read only bytes already
preserved by :mod:`strix.corpus.snapshot` — never the live evidence root —
and verify them against the recorded content hash before parsing anything.
Supported in this phase: ``.txt``, ``.md``, ``.markdown``, as anchored
plain text (no Markdown rendering or semantic rewriting). The scanner's
broader extension allow-list (``strix.corpus.models.
DEFAULT_SUPPORTED_EXTENSIONS``) is a discovery-time classification only —
it is never treated as a claim that a parser exists; :class:`~strix.
corpus.parsers.registry.ParserRegistry` is the sole source of truth for
that.

Nothing here reads the network, the wall clock, the environment, or calls
an LLM — decoding, normalization, and chunking are pure functions of the
preserved bytes and a versioned policy.
"""

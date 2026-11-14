"""Typed research requests and deterministic lexical retrieval.

Phase 8 of the neuro-symbolic platform: a sibling subsystem to
``strix.corpus``, not nested under it. A :class:`~strix.research.models.
ResearchRequest` is a fully preserved, replayable description of what a
request needs; :func:`~strix.research.retrieval.retrieve` turns it plus
an immutable corpus's :class:`~strix.corpus.parsers.models.ParseResult`
objects into a content-derived, replayable :class:`~strix.research.
models.RetrievalTrace`.

Retrieval here never reads the live evidence directory, never reparses a
document, never calls an embedding model, a language-model tokenizer, or
the network, and never claims that distinct selected documents
independently corroborate anything — that is verification's job, in a
later phase. Scoring is a simple, versioned, fully auditable lexical
baseline; a more sophisticated ranking method can be introduced later
behind the same :func:`retrieve` interface without changing its contract.
"""

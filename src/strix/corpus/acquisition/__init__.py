"""Scholarly-search and acquisition contracts.

Phase 4 of the neuro-symbolic platform: a provider-neutral
:class:`~strix.corpus.acquisition.connectors.base.SearchConnector` protocol,
strict :class:`~strix.corpus.acquisition.models.SearchPlan` and
:class:`~strix.corpus.acquisition.models.SearchResult` models, and one
deterministic, fixture-backed
:class:`~strix.corpus.acquisition.connectors.fake.FakeSearchConnector`.

A search result is a *lead*, never evidence: it is metadata about a
candidate document a provider reported, not content that has been
preserved, parsed, or anchored. Nothing in this package downloads
anything, calls a network client, or writes to the evidence root — that is
later phases (secure download, parsing) per
``architecture/development/neuro-symbolic-platform.md``.
"""

"""STRIX corpus subsystem: scholarly evidence acquisition and discovery.

Preserved source documents live under one evidence root
(``STRIX_EVIDENCE_ROOT``, default ``/Users/blkpvnthr/STRIX/docs``) in two
subtrees: ``acquired/`` (written only by the acquisition subsystem) and
``imported/`` (user-supplied). Nothing in this package ever mutates or
deletes a document under the evidence root.

Phase 2 (this phase) adds only recursive discovery (:mod:`strix.corpus.scanner`):
a stable, lexically ordered scan that records candidate evidence files and
rejects or flags unsupported types, unreadable files, symlinks, traversal
attempts, and configured limits — without parsing document content. Corpus
manifests, immutable snapshots, acquisition, parsing, retrieval, and LLM
proposals are later phases; see
``architecture/development/neuro-symbolic-platform.md`` for the full plan.
"""

#: Version of the corpus discovery contract. Recorded on every ScanResult so
#: later phases (manifest, snapshot) can detect contract drift.
CORPUS_DISCOVERY_VERSION = "1.0.0"

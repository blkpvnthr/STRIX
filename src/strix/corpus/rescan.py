"""The bounded rescan orchestrator: scan, snapshot, diff against a prior
corpus. No watcher, no background/automatic triggering, no retrieval or
finding-impact logic -- see :mod:`strix.corpus.diff` for why the latter
is a deliberate phase boundary, not an oversight.
"""

from __future__ import annotations

from pathlib import Path

from strix.corpus.diff import compute_diff
from strix.corpus.models import RescanResult, ScanLimits
from strix.corpus.scanner import scan_corpus
from strix.corpus.snapshot import CorpusStore


def rescan(
    *,
    evidence_root: Path,
    snapshot_root: Path,
    prior_corpus_id: str,
    scan_limits: ScanLimits | None = None,
) -> RescanResult:
    """Scan *evidence_root*, snapshot it, and diff against *prior_corpus_id*.

    1. Scans the live evidence root (``strix.corpus.scanner.scan_corpus``).
    2. Creates or reuses an immutable snapshot of the result
       (``CorpusStore.snapshot`` — if an identical snapshot already
       exists, it is verified, never blindly trusted, before being
       reused; nothing is ever overwritten).
    3. Loads and fully re-verifies the prior manifest named by
       *prior_corpus_id* from the same store — a tampered prior snapshot
       raises here rather than silently feeding corrupted data into the
       comparison.
    4. Compares the two manifests (``strix.corpus.diff.compute_diff``)
       and returns both the new manifest and the diff.

    Never mutates, overwrites, or deletes the prior manifest or snapshot
    — every write this performs is confined to the new snapshot's own
    (content-addressed, hence never colliding with the prior one unless
    truly identical) directory.
    """
    scan = scan_corpus(
        evidence_root, limits=scan_limits if scan_limits is not None else ScanLimits()
    )
    store = CorpusStore(snapshot_root)
    new_manifest, _directory = store.snapshot(scan)

    prior_manifest = store.verify_and_load(prior_corpus_id)

    diff = compute_diff(prior_manifest, new_manifest)
    return RescanResult(manifest=new_manifest, diff=diff)

"""STRIX durable audit ledger (GAP-002, R1 §19).

The authoritative, durable, append-only decision-to-outcome record for a
research run. This is deliberately *not* the C-engine ``decision_events.py``
in-memory sink: that sink is bounded and potentially lossy, so it can never be
the system of record. Every lifecycle event (R1 §19.1) — from
``research_requested`` through ``outcome_certified`` and ``research_terminated``
— is persisted here instead.

Design guarantees (all reused from the rest of STRIX):

- **Frozen, closed-schema contracts** built on :class:`strix.models.StrixModel`.
- **Content-derived identifiers and digests** via :mod:`strix.canonical`
  (``make_id``, ``canonical_hash``). An event id never hashes itself or any
  persistence wall-clock.
- **Crash-safe durable writes** via the same temp-file + ``fsync`` + atomic
  ``os.replace`` + directory-``fsync`` protocol as :mod:`strix.run_store`. An
  audit-critical write never fails silently: it raises
  :class:`strix.errors.AuditError`.
- **Hash chaining** links each event to its predecessor so any in-place
  tamper, reordering, or gap is detectable on read. Chaining alone cannot
  detect *tail truncation* (dropping the most recent events leaves a shorter
  but internally valid chain); a per-run manifest records the committed head
  and count as an external anchor that closes that gap.
"""

from __future__ import annotations

#: Audit contract version — recorded on every event and in every manifest so a
#: reader can detect structural drift independently of the release version.
AUDIT_SCHEMA_VERSION = "audit-v1"

__all__ = ["AUDIT_SCHEMA_VERSION"]

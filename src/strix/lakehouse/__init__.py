"""STRIX data lakehouse — a persistent, provenance-tracked evidence warehouse.

Layers (medallion):

- **Bronze** (DE-1): immutable, content-addressed raw source payloads plus
  append-only provenance manifests. Nothing here is ever mutated or overwritten.
- **Silver** (DE-3): normalized, partitioned, quality-gated datasets.
- **Gold** (DE-5): analytical marts and financial ratios.

The lakehouse reuses the rest of STRIX's discipline: frozen pydantic contracts,
Decimal-only values, :mod:`strix.canonical` content hashing and ``make_id``, and
atomic crash-safe writes. Raw bytes are preserved byte-exact and hash-verified,
so every downstream observation remains traceable to its original source
evidence — the same guarantee the research agent already relies on.
"""

from __future__ import annotations

#: Lakehouse contract version — recorded in every provenance manifest so a
#: reader can detect structural drift (independent of the release version).
LAKEHOUSE_VERSION = "0.1.0"

__all__ = ["LAKEHOUSE_VERSION"]

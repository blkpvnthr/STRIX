"""Silver layer (DE-3): deterministic normalization of immutable Bronze payloads
into typed, partitioned, quality-gated Parquet datasets.

Every normalized observation is Decimal-safe and carries lineage back to its
Bronze artifact id and source-record locator, so published rows remain fully
traceable and previously referenced research data stays reproducible. Raw Bronze
is never mutated; Silver is published atomically with versioned manifests.
"""

from __future__ import annotations

#: Silver contract version, recorded in every publication manifest.
SILVER_VERSION = "0.1.0"

__all__ = ["SILVER_VERSION"]

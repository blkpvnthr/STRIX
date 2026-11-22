"""Analytical warehouse (DE-4): DuckDB-first, optional Snowflake.

Loads validated Silver Parquet publications into a dimensional model
(facts + dimensions), with transactional incremental loading, load state,
source-to-warehouse reconciliation, point-in-time-aware temporal fields, and full
evidence lineage back to Bronze. The warehouse never confers verification — the
STRIX verifier still recomputes claims from preserved evidence.
"""

from __future__ import annotations

#: Warehouse contract version, recorded in load manifests.
WAREHOUSE_VERSION = "0.1.0"

__all__ = ["WAREHOUSE_VERSION"]

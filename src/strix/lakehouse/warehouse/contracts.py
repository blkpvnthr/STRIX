"""Typed contracts for warehouse loading, reconciliation, queries, and lineage."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field

from strix.lakehouse.warehouse import WAREHOUSE_VERSION
from strix.models import StrixModel


class WarehouseBackend(StrEnum):
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"


class LoadResult(StrixModel):
    """Outcome of loading one Silver dataset into the warehouse."""

    dataset: str
    fact_table: str
    silver_publication_id: str
    load_execution_id: str
    schema_version: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    silver_rows: int = 0
    skipped: bool = False
    reason: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    warehouse_version: str = WAREHOUSE_VERSION

    @property
    def ok(self) -> bool:
        return self.reason is None or self.skipped


class WarehouseReconciliation(StrixModel):
    """Silver-vs-warehouse reconciliation for one dataset."""

    dataset: str
    fact_table: str
    silver_rows: int
    warehouse_rows: int
    unique_natural_keys: int
    duplicate_keys: int
    null_value_rows: int
    min_observation_date: str | None
    max_observation_date: str | None
    lineage_complete: bool
    discrepancies: tuple[str, ...] = ()

    @property
    def balanced(self) -> bool:
        return not self.discrepancies


class QueryResult(StrixModel):
    """A typed, read-only analytical query result with provenance metadata."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str | None], ...]
    row_count: int
    units: dict[str, str] = Field(default_factory=dict)
    as_of: str | None = None
    dataset_versions: dict[str, str] = Field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class LineageRecord(StrixModel):
    """Warehouse row -> Silver -> Bronze artifact -> source-record locator."""

    natural_key: str
    fact_table: str
    silver_schema_version: str
    silver_publication_id: str
    bronze_artifact_id: str
    source_locator: str
    retrieved_at: str
    bronze_artifact_present: bool
    bronze_hash_ok: bool

    @property
    def complete(self) -> bool:
        return self.bronze_artifact_present and self.bronze_hash_ok

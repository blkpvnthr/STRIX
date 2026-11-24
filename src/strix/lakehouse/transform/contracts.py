"""Typed contracts for the dbt transformation layer: calculation contracts, dbt
run results, transform status, and independent cross-validation outcomes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from strix.models import StrixModel


class TransformBackend(StrEnum):
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"


class CalculationContract(StrixModel):
    """A versioned, immutable definition of one analytical calculation.

    Contracts are the single source of truth for how a mart number is defined.
    The language model cannot redefine them; the independent verifier consults
    them to recompute a claim from preserved evidence.
    """

    identifier: str
    formula: str
    methodology_version: str
    input_datasets: tuple[str, ...]
    required_observations: str
    output_unit: str
    precision_policy: str
    min_sample_size: int
    null_handling: str
    historical_availability: str
    evidence_lineage: str


class DbtNodeResult(StrixModel):
    """Outcome of a single dbt node (model/test/seed) from run_results.json."""

    unique_id: str
    name: str
    resource_type: str
    status: str
    execution_time_seconds: float = 0.0
    rows_affected: int | None = None
    message: str | None = None


class DbtRunResult(StrixModel):
    """Structured result of one controlled dbt invocation."""

    command: str
    backend: str
    dbt_subcommand: str
    argv: tuple[str, ...]
    returncode: int
    success: bool
    elapsed_seconds: float = 0.0
    selected: str | None = None
    full_refresh: bool = False
    nodes: tuple[DbtNodeResult, ...] = Field(default_factory=tuple)
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    skip_count: int = 0
    # Warehouse publication versions this transform ran against (dataset -> pub id).
    source_publications: dict[str, str] = Field(default_factory=dict)
    stdout_tail: str = ""
    stderr_tail: str = ""


class ModelInfo(StrixModel):
    """One model in the project inventory (from the dbt manifest)."""

    name: str
    layer: str  # staging | intermediate | marts | other
    materialization: str
    schema_name: str
    depends_on: tuple[str, ...] = Field(default_factory=tuple)


class CrossValidation(StrixModel):
    """Independent recomputation of one mart value from preserved evidence.

    ``sql_value`` is the warehouse/dbt mart number; ``python_value`` is recomputed
    by the Decimal calculators from the underlying Silver observations. ``agrees``
    is true only when they match within ``tolerance`` — this is the signal the
    verifier uses, never the mart's own assertion.
    """

    claim: str
    calculation_id: str
    methodology_version: str
    subject: str
    sql_value: str | None
    python_value: str | None
    tolerance: str
    difference: str | None
    sample_size: int
    agrees: bool
    status: str
    evidence_artifacts: tuple[str, ...] = Field(default_factory=tuple)
    note: str | None = None

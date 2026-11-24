"""Typed, evidence-compatible computation results (R1 §7.2).

Every analytical operation produces a :class:`ComputationResult`: an immutable,
content-addressed record carrying the result value (scalar / vector / matrix /
structured), the input digest, the numerical contract, the backend identity, and
the provenance/temporal/statistical metadata the evidence graph and independent
verifier need. Nondeterministic fields (execution duration) are excluded from the
content identifier, mirroring the existing ``RunManifest``/``VerificationResult``
convention. A backend never assigns a factual claim verdict — it only emits this
evidence (R1 §4, §7.2, §21).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Any

from strix.canonical import canonical_hash, make_id
from strix.models import DecimalValue, StrixModel
from strix.native.contracts import BackendValidation, NumericalContract


class ResultKind(StrEnum):
    """Shape of a computation result's value."""

    SCALAR = "scalar"
    VECTOR = "vector"
    MATRIX = "matrix"
    STRUCTURED = "structured"


class ComputationResult(StrixModel):
    """An immutable, content-addressed result of one native computation (R1 §7.2)."""

    # --- content-derived identity (deterministic) ---
    computation_id: str
    algorithm_id: str
    algorithm_version: str
    backend_id: str
    input_digest: str
    input_observation_ids: tuple[str, ...] = ()
    input_artifact_refs: tuple[str, ...] = ()

    # --- typed result (exactly one of the four is non-None) ---
    result_kind: ResultKind
    scalar: DecimalValue | None = None
    vector: tuple[DecimalValue, ...] | None = None
    matrix: tuple[tuple[DecimalValue, ...], ...] | None = None
    fields: tuple[tuple[str, DecimalValue], ...] | None = None

    # --- units / temporal / contract ---
    output_unit: str
    observation_interval: str | None = None
    knowledge_cutoff: date | None = None
    contract: NumericalContract

    # --- statistical metadata ---
    sample_size: int | None = None
    random_seed: int | None = None
    statistical_assumptions: tuple[str, ...] = ()
    missing_value_policy: str | None = None

    # --- software / validation ---
    software_version: str
    numerical_validation_status: BackendValidation

    # --- nondeterministic (EXCLUDED from computation_id) ---
    execution_duration_ms: int | None = None

    def _payload_for(self, kind: ResultKind) -> object | None:
        return {
            ResultKind.SCALAR: self.scalar,
            ResultKind.VECTOR: self.vector,
            ResultKind.MATRIX: self.matrix,
            ResultKind.STRUCTURED: self.fields,
        }[kind]

    def model_post_init(self, __context: object) -> None:
        present = [k for k in ResultKind if self._payload_for(k) is not None]
        if len(present) != 1:
            raise ValueError(
                f"exactly one result payload must be set, found {len(present)}"
            )
        if present[0] is not self.result_kind:
            raise ValueError(
                f"result_kind {self.result_kind} does not match the provided "
                f"{present[0]} payload"
            )


def _infer_kind(
    scalar: object | None,
    vector: object | None,
    matrix: object | None,
    fields: object | None,
) -> ResultKind:
    present = [
        kind
        for kind, value in (
            (ResultKind.SCALAR, scalar),
            (ResultKind.VECTOR, vector),
            (ResultKind.MATRIX, matrix),
            (ResultKind.STRUCTURED, fields),
        )
        if value is not None
    ]
    if len(present) != 1:
        raise ValueError(
            f"exactly one of scalar/vector/matrix/fields must be provided, got {len(present)}"
        )
    return present[0]


def make_computation_result(
    *,
    algorithm_id: str,
    algorithm_version: str,
    backend_id: str,
    inputs: object,
    contract: NumericalContract,
    output_unit: str,
    software_version: str,
    numerical_validation_status: BackendValidation,
    scalar: object | None = None,
    vector: Sequence[object] | None = None,
    matrix: Sequence[Sequence[object]] | None = None,
    fields: Sequence[tuple[str, object]] | None = None,
    input_observation_ids: Sequence[str] = (),
    input_artifact_refs: Sequence[str] = (),
    observation_interval: str | None = None,
    knowledge_cutoff: date | None = None,
    sample_size: int | None = None,
    random_seed: int | None = None,
    statistical_assumptions: Sequence[str] = (),
    missing_value_policy: str | None = None,
    execution_duration_ms: int | None = None,
) -> ComputationResult:
    """Assemble a content-addressed :class:`ComputationResult`.

    ``inputs`` is any canonically-serializable structure (e.g. the observation
    values and parameters); its SHA-256 becomes ``input_digest``. The
    ``computation_id`` is derived from the deterministic fields only.
    """
    kind = _infer_kind(scalar, vector, matrix, fields)
    input_digest = canonical_hash(inputs)

    # Construct a draft (pydantic validates types here — e.g. rejects float
    # payloads with a ValidationError) with a placeholder id, then derive the
    # real content id from the validated deterministic fields.
    draft = ComputationResult(
        computation_id="PENDING",
        algorithm_id=algorithm_id,
        algorithm_version=algorithm_version,
        backend_id=backend_id,
        input_digest=input_digest,
        input_observation_ids=tuple(input_observation_ids),
        input_artifact_refs=tuple(input_artifact_refs),
        result_kind=kind,
        scalar=scalar,
        vector=None if vector is None else tuple(vector),
        matrix=None if matrix is None else tuple(tuple(row) for row in matrix),
        fields=None if fields is None else tuple((str(k), v) for k, v in fields),
        output_unit=output_unit,
        observation_interval=observation_interval,
        knowledge_cutoff=knowledge_cutoff,
        contract=contract,
        sample_size=sample_size,
        random_seed=random_seed,
        statistical_assumptions=tuple(statistical_assumptions),
        missing_value_policy=missing_value_policy,
        software_version=software_version,
        numerical_validation_status=numerical_validation_status,
        execution_duration_ms=execution_duration_ms,
    )

    deterministic: Mapping[str, Any] = {
        "algorithm_id": draft.algorithm_id,
        "algorithm_version": draft.algorithm_version,
        "backend_id": draft.backend_id,
        "input_digest": draft.input_digest,
        "input_observation_ids": draft.input_observation_ids,
        "input_artifact_refs": draft.input_artifact_refs,
        "result_kind": draft.result_kind,
        "scalar": draft.scalar,
        "vector": draft.vector,
        "matrix": draft.matrix,
        "fields": draft.fields,
        "output_unit": draft.output_unit,
        "observation_interval": draft.observation_interval,
        "knowledge_cutoff": draft.knowledge_cutoff,
        "contract": draft.contract,
        "sample_size": draft.sample_size,
        "random_seed": draft.random_seed,
        "statistical_assumptions": draft.statistical_assumptions,
        "missing_value_policy": draft.missing_value_policy,
        "software_version": draft.software_version,
        "numerical_validation_status": draft.numerical_validation_status,
    }
    computation_id = make_id("COMP", deterministic)
    return draft.model_copy(update={"computation_id": computation_id})

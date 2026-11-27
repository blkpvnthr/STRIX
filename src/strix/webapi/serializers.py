"""JSON serialization for API responses.

Uses :func:`strix.canonical.to_jsonable` so Decimals serialize as exact strings
(never binary floats) and datetimes as UTC ISO — the same discipline the rest of
STRIX uses, so API numbers match persisted artifacts exactly.
"""

from __future__ import annotations

from typing import Any

from strix.agent.budget import BudgetSnapshot
from strix.agent.documentation import build_supporting_documentation
from strix.agent.models import AgentClaim, ResearchAnswer, ResearchResponse
from strix.canonical import to_jsonable


def serialize_answer(answer: ResearchAnswer) -> Any:
    return to_jsonable(answer.model_dump())


def serialize_response(response: ResearchResponse | None) -> Any:
    return to_jsonable(response.model_dump()) if response is not None else None


def serialize_documentation(response: ResearchResponse | None) -> Any:
    """Serialize the unified supporting-documentation + citation-mapping contract.

    Null when there is no response. This is the single §7/§15 contract the React
    frontend, CLI, and workers all render — derived deterministically from the
    verified response, never re-synthesized.
    """
    if response is None:
        return None
    return to_jsonable(build_supporting_documentation(response).model_dump())


def serialize_usage(usage: BudgetSnapshot) -> Any:
    return to_jsonable(usage.model_dump())


def serialize_claims(claims: tuple[AgentClaim, ...]) -> Any:
    return to_jsonable([c.model_dump() for c in claims])

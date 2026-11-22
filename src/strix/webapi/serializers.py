"""JSON serialization for API responses.

Uses :func:`strix.canonical.to_jsonable` so Decimals serialize as exact strings
(never binary floats) and datetimes as UTC ISO — the same discipline the rest of
STRIX uses, so API numbers match persisted artifacts exactly.
"""

from __future__ import annotations

from typing import Any

from strix.agent.budget import BudgetSnapshot
from strix.agent.models import AgentClaim, ResearchAnswer
from strix.canonical import to_jsonable


def serialize_answer(answer: ResearchAnswer) -> Any:
    return to_jsonable(answer.model_dump())


def serialize_usage(usage: BudgetSnapshot) -> Any:
    return to_jsonable(usage.model_dump())


def serialize_claims(claims: tuple[AgentClaim, ...]) -> Any:
    return to_jsonable([c.model_dump() for c in claims])

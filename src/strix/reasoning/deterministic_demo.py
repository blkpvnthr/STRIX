"""Deterministic demonstration reasoner.

This is NOT an LLM. It is fixed, auditable Python that assembles one
structured profitability claim from the evidence bundle. It exists to
exercise the reasoning boundary (:class:`strix.reasoning.base.Reasoner`)
until a schema-constrained LLM adapter is added behind the same protocol.

Constraints honored here:
- Input is only ``(spec, evidence)``.
- No file, environment, network, credential, or terminal access.
- No new authoritative financial values: every asserted number is copied
  verbatim from cited evidence; the only derivation is the structured
  direction, taken from the sign of the change evidence (and independently
  re-derived by the verifier).
"""

from __future__ import annotations

from strix.canonical import make_id
from strix.errors import ReasonerError
from strix.formatting import direction_from_change, render_statement
from strix.models import (
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    Metric,
    NumericAssertion,
    ResearchSpec,
)


class DeterministicDemoReasoner:
    """Builds the demo profitability claim from margin + change evidence."""

    def analyze(self, spec: ResearchSpec, evidence: list[Evidence]) -> list[Claim]:
        previous_period, current_period = spec.historical_periods
        previous = _find(evidence, Metric.OPERATING_MARGIN, previous_period)
        current = _find(evidence, Metric.OPERATING_MARGIN, current_period)
        change = _find(
            evidence,
            Metric.OPERATING_MARGIN_CHANGE_PP,
            f"{previous_period}..{current_period}",
        )

        direction = direction_from_change(change.value)
        statement = render_statement(direction, previous.value, current.value)
        # Role-ordered citations: previous, current, change.
        cited = (previous, current, change)
        assertions = tuple(
            NumericAssertion(
                metric=item.metric,
                asserted_value=item.value,
                unit=item.unit,
                evidence_id=item.evidence_id,
            )
            for item in cited
        )
        claim_id = make_id(
            "CL",
            {
                "subject_id": spec.company_id,
                "claim_type": ClaimType.PROFITABILITY_CHANGE,
                "direction": direction,
                "evidence_ids": [item.evidence_id for item in cited],
                "numeric_assertions": [
                    {
                        "metric": assertion.metric,
                        "asserted_value": assertion.asserted_value,
                        "unit": assertion.unit,
                        "evidence_id": assertion.evidence_id,
                    }
                    for assertion in assertions
                ],
            },
        )
        claim = Claim(
            claim_id=claim_id,
            subject_id=spec.company_id,
            statement=statement,
            claim_type=ClaimType.PROFITABILITY_CHANGE,
            direction=direction,
            evidence_ids=tuple(item.evidence_id for item in cited),
            numeric_assertions=assertions,
            status=ClaimStatus.PROPOSED,
        )
        return [claim]


def _find(evidence: list[Evidence], metric: Metric, observation_period: str) -> Evidence:
    matches = [
        item
        for item in evidence
        if item.metric is metric and item.observation_period == observation_period
    ]
    if len(matches) != 1:
        raise ReasonerError(
            f"expected exactly one {metric.value} evidence for period "
            f"{observation_period!r}, found {len(matches)}"
        )
    return matches[0]

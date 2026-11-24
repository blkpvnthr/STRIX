"""Sanity checks for anomalous financial observations (spec §4).

Independent recomputation proves a number was computed correctly from the
preserved series — it does not prove the *source* data is sound. A corporate
action, a stale price, an incomplete session, or an inverted date range can
yield an arithmetically-correct but economically-implausible figure (e.g. an
index proxy showing an ~18% weekly move).

These checks run after verification and never change a verdict. They emit
advisory :class:`SanityFlag` records that the orchestrator surfaces as
limitations and the synthesis layer must weigh before asserting a conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentVerificationStatus,
    CalculationMethod,
    ObservationSeries,
)

#: Trading days that count as a "short" window for magnitude plausibility.
SHORT_HORIZON_OBS = 7
#: A single-step (day-over-day) move beyond this is implausible for a broad proxy.
ANOMALOUS_STEP_RETURN = Decimal("0.25")
#: A short-horizon (<= ~1 week) cumulative move beyond this (a >3-sigma event for
#: a broad proxy) warrants a data-quality flag.
ANOMALOUS_SHORT_RETURN = Decimal("0.10")
#: Annualized realized volatility beyond this (200%) is implausible for equities.
ANOMALOUS_VOLATILITY = Decimal("2.0")

_RETURN_METHODS = frozenset(
    {CalculationMethod.PERIOD_RETURN, CalculationMethod.CUMULATIVE_RETURN}
)


@dataclass(frozen=True)
class SanityFlag:
    """One advisory data-quality concern about a verified observation."""

    code: str
    message: str
    claim_id: str | None = None


def check_claims(
    claims: tuple[AgentClaim, ...],
    collector: EvidenceCollector,
    *,
    as_of: date,
) -> tuple[SanityFlag, ...]:
    """Return advisory flags for anomalies among the verified claims."""
    flags: list[SanityFlag] = []
    for claim in claims:
        if claim.verification.status is not AgentVerificationStatus.VERIFIED:
            continue
        flags.extend(_check_claim(claim, collector, as_of))
    # Deduplicate on (code, claim_id) preserving order.
    seen: set[tuple[str, str | None]] = set()
    unique: list[SanityFlag] = []
    for flag in flags:
        key = (flag.code, flag.claim_id)
        if key not in seen:
            seen.add(key)
            unique.append(flag)
    return tuple(unique)


def _check_claim(
    claim: AgentClaim, collector: EvidenceCollector, as_of: date
) -> list[SanityFlag]:
    flags: list[SanityFlag] = []
    calc = claim.calculation
    if calc is None:
        return flags

    flags.extend(_check_date_params(claim, calc.parameters, as_of))

    series = [collector.series(sid) for sid in calc.input_series_ids]
    primary = series[0] if series else None
    if primary is not None:
        flags.extend(_check_series(claim, primary, as_of))

    value = claim.verification.computed_value
    if value is None:
        return flags

    n_obs = len(primary.observations) if primary is not None else None
    if (
        calc.method in _RETURN_METHODS
        and n_obs is not None
        and n_obs <= SHORT_HORIZON_OBS
        and abs(value) > ANOMALOUS_SHORT_RETURN
    ):
        flags.append(
            SanityFlag(
                code="anomalous_short_horizon_return",
                message=(
                    f"{claim.statement} implies a {_pct(value)} move over only "
                    f"{n_obs} observation(s) — unusually large for this horizon; "
                    "check for a corporate action, split, or price-adjustment issue."
                ),
                claim_id=claim.claim_id,
            )
        )
    if calc.method is CalculationMethod.REALIZED_VOLATILITY and value > ANOMALOUS_VOLATILITY:
        flags.append(
            SanityFlag(
                code="anomalous_volatility",
                message=(
                    f"Annualized realized volatility of {_pct(value)} is implausibly "
                    "high for an equity proxy; verify the underlying price series."
                ),
                claim_id=claim.claim_id,
            )
        )
    return flags


def _check_date_params(
    claim: AgentClaim, parameters: dict[str, str], as_of: date
) -> list[SanityFlag]:
    flags: list[SanityFlag] = []
    start = _parse_date(parameters.get("start"))
    end = _parse_date(parameters.get("end"))
    if start is not None and end is not None and start >= end:
        flags.append(
            SanityFlag(
                code="inverted_date_range",
                message=(
                    f"Calculation window start ({start.isoformat()}) is not before its "
                    f"end ({end.isoformat()})."
                ),
                claim_id=claim.claim_id,
            )
        )
    for label, value in (("start", start), ("end", end)):
        if value is not None and value > as_of:
            flags.append(
                SanityFlag(
                    code="future_dated_window",
                    message=(
                        f"Calculation window {label} ({value.isoformat()}) is after the "
                        f"as-of date ({as_of.isoformat()})."
                    ),
                    claim_id=claim.claim_id,
                )
            )
    return flags


def _check_series(
    claim: AgentClaim, series: ObservationSeries, as_of: date
) -> list[SanityFlag]:
    flags: list[SanityFlag] = []
    obs = series.observations
    dates = [_parse_date(o.at) for o in obs]
    concrete = [d for d in dates if d is not None]

    if any(o.value <= 0 for o in obs):
        flags.append(
            SanityFlag(
                code="nonpositive_price",
                message=f"{series.subject} series contains a non-positive value.",
                claim_id=claim.claim_id,
            )
        )
    if len(concrete) == len(dates) and concrete != sorted(concrete):
        flags.append(
            SanityFlag(
                code="unordered_series",
                message=f"{series.subject} observations are not in chronological order.",
                claim_id=claim.claim_id,
            )
        )
    if len(set(concrete)) != len(concrete):
        flags.append(
            SanityFlag(
                code="duplicate_observation_dates",
                message=f"{series.subject} series has duplicate observation dates.",
                claim_id=claim.claim_id,
            )
        )
    # Day-over-day step anomaly (adjacent closes).
    for prev, cur in pairwise(obs):
        if prev.value > 0:
            step = (cur.value - prev.value) / prev.value
            if abs(step) > ANOMALOUS_STEP_RETURN:
                flags.append(
                    SanityFlag(
                        code="anomalous_price_step",
                        message=(
                            f"{series.subject} moved {_pct(step)} between {prev.at} and "
                            f"{cur.at} — verify for a split or adjustment artifact."
                        ),
                        claim_id=claim.claim_id,
                    )
                )
                break
    # Incomplete / weekend session for the latest observation.
    if concrete:
        latest = concrete[-1]
        if latest == as_of:
            flags.append(
                SanityFlag(
                    code="possibly_incomplete_session",
                    message=(
                        f"The latest {series.subject} observation ({latest.isoformat()}) is "
                        "the as-of date; that session may be incomplete or provider-delayed."
                    ),
                    claim_id=claim.claim_id,
                )
            )
    if series.source_evidence_id and _is_weekend(as_of):
        flags.append(
            SanityFlag(
                code="weekend_as_of",
                message=(
                    f"The as-of date ({as_of.isoformat()}) is a weekend; the most recent "
                    "complete session predates it."
                ),
                claim_id=claim.claim_id,
            )
        )
    return flags


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5

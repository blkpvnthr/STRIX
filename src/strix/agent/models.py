"""Domain contracts for agent research: evidence, observations, claims, and
their independent verification.

These are broader than the core :mod:`strix.models` pipeline (which is bound to
operating-margin change) but follow the same discipline: frozen models, no
floats (Decimal only), content-derived identifiers via :mod:`strix.canonical`,
and a hard separation between *what the model proposes* (an :class:`AgentClaim`
with ``verification.status == PENDING``) and *what the independent verifier
decides* (every other status). The model can never set its own verified status.

Preserved numeric observations (:class:`ObservationSeries`) are the ground the
numerical verifier recomputes from — it never compares one model-produced number
against another.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, Field

from strix.canonical import make_id
from strix.models import DecimalValue, StrixModel

# --------------------------------------------------------------------------
# Bounded vocabularies
# --------------------------------------------------------------------------


class SourceKind(StrEnum):
    WEB_PAGE = "web_page"
    WEB_SEARCH_RESULT = "web_search_result"
    SEC_EDGAR = "sec_edgar"
    MARKET_DATA = "market_data"
    ECONOMIC_RELEASE = "economic_release"
    NEWS_ARTICLE = "news_article"
    CALCULATION = "calculation"
    DATASET = "dataset"


class FreshnessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class AgentClaimType(StrEnum):
    OBSERVATION = "observation"
    QUANTITATIVE = "quantitative"
    HISTORICAL_COMPARISON = "historical_comparison"
    ATTRIBUTED_STATEMENT = "attributed_statement"
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"
    FORECAST = "forecast"


class AgentVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNVERIFIABLE = "unverifiable"
    STALE = "stale"


class CalculationMethod(StrEnum):
    PERIOD_RETURN = "period_return"
    CUMULATIVE_RETURN = "cumulative_return"
    MAX_DRAWDOWN = "max_drawdown"
    REALIZED_VOLATILITY = "realized_volatility"
    MOVING_AVERAGE = "moving_average"
    RELATIVE_PERFORMANCE = "relative_performance"
    CORRELATION = "correlation"


#: Claim types whose truth the verifier can establish independently. Others
#: (interpretation, hypothesis, forecast) can at most be well-formed and cited;
#: they are never marked VERIFIED.
INDEPENDENTLY_VERIFIABLE_TYPES = frozenset(
    {
        AgentClaimType.OBSERVATION,
        AgentClaimType.QUANTITATIVE,
        AgentClaimType.HISTORICAL_COMPARISON,
        AgentClaimType.ATTRIBUTED_STATEMENT,
    }
)


# --------------------------------------------------------------------------
# Evidence and preserved observations
# --------------------------------------------------------------------------


class AgentEvidence(StrixModel):
    """A citable source record. A content hash proves artifact integrity, not
    that the source's assertions are true."""

    evidence_id: str
    source_type: SourceKind
    provider: str
    source_title: str
    source_url: str | None = None
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None
    observation_period: str | None = None
    #: SHA-256 of the preserved artifact bytes (integrity, not veracity).
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: Internal artifact reference (never exposed to unauthorized users).
    artifact_path: str | None = None
    source_anchor: str | None = None
    freshness_status: FreshnessStatus = FreshnessStatus.UNKNOWN
    #: Bounded excerpt actually retrieved from the source, when permitted.
    excerpt: str | None = None

    @staticmethod
    def make_id(content_hash: str, source_url: str | None, anchor: str | None) -> str:
        return make_id(
            "EV",
            {"content_hash": content_hash, "source_url": source_url or "", "anchor": anchor or ""},
        )


class Observation(StrixModel):
    """One preserved numeric datapoint (never a float)."""

    #: ISO date or period label the value is observed at.
    at: str = Field(min_length=1)
    value: DecimalValue


class ObservationSeries(StrixModel):
    """An ordered, preserved numeric series a calculation runs on.

    This is the data the numerical verifier independently recomputes from; it
    carries the evidence id it was extracted from so lineage is explicit.
    """

    series_id: str
    subject: str
    concept: str
    unit: str
    observations: tuple[Observation, ...]
    source_evidence_id: str

    @staticmethod
    def make_id(subject: str, concept: str, observations: tuple[Observation, ...]) -> str:
        return make_id(
            "SER",
            {
                "subject": subject,
                "concept": concept,
                "observations": [o.model_dump() for o in observations],
            },
        )

    @property
    def values(self) -> tuple[DecimalValue, ...]:
        return tuple(o.value for o in self.observations)


# --------------------------------------------------------------------------
# Claims and verification
# --------------------------------------------------------------------------


class AgentCalculation(StrixModel):
    """A deterministic calculation a quantitative claim rests on.

    ``claimed_value`` is what the model/claim asserts; the verifier recomputes
    it from the referenced series and compares within ``tolerance``.
    """

    method: CalculationMethod
    calculation_version: str
    #: Named parameters (e.g. window, periods_per_year) — JSON-safe scalars.
    parameters: dict[str, str] = Field(default_factory=dict)
    #: Series ids whose preserved observations feed the calculation (role-ordered).
    input_series_ids: tuple[str, ...]
    claimed_value: DecimalValue
    units: str


class ClaimVerification(StrixModel):
    """The independent verifier's verdict on a claim. Only the verifier writes
    anything other than ``PENDING`` here."""

    status: AgentVerificationStatus = AgentVerificationStatus.PENDING
    computed_value: DecimalValue | None = None
    method: str | None = None
    reason: str | None = None
    tolerance: DecimalValue | None = None
    verifier_version: str | None = None
    verified_at: AwareDatetime | None = None


class AgentClaim(StrixModel):
    """A structured statement whose numbers must cite preserved evidence."""

    claim_id: str
    claim_type: AgentClaimType
    statement: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    calculation: AgentCalculation | None = None
    #: For attributed statements: who is being quoted/attributed.
    attributed_to: str | None = None
    verification: ClaimVerification = ClaimVerification()

    @staticmethod
    def make_id(claim_type: AgentClaimType, statement: str, evidence_ids: tuple[str, ...]) -> str:
        return make_id(
            "CL",
            {"claim_type": claim_type, "statement": statement, "evidence_ids": list(evidence_ids)},
        )

    @property
    def is_verified(self) -> bool:
        return self.verification.status is AgentVerificationStatus.VERIFIED


# --------------------------------------------------------------------------
# Final research record
# --------------------------------------------------------------------------


class ResearchAnswer(StrixModel):
    """The validated, publishable answer to one research question."""

    run_id: str
    question: str
    data_as_of: AwareDatetime | None
    summary: str
    verified_claims: tuple[AgentClaim, ...]
    unresolved_claims: tuple[AgentClaim, ...]
    evidence: tuple[AgentEvidence, ...]
    limitations: tuple[str, ...]
    disclaimer: str

    @property
    def observed_dates(self) -> tuple[date, ...]:  # pragma: no cover - convenience
        return ()

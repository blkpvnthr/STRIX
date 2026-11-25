"""Read-only source-adapter contracts for federal spending data.

This module defines the *contract* a federal data source must satisfy and a
deterministic, offline, fixture-backed implementation that proves the
contract without any network access or credentials.

Why read-only
-------------
A federal spending connector is a **retrieval** adapter: it reads awards and
modifications from a public source of record. It never writes, submits,
mutates, or deletes anything upstream. The :class:`FederalConnector`
protocol therefore exposes only ``fetch_*`` methods, and implementations
must not add any write/submit surface.

Live endpoints (the LIVE_VALIDATED step — NOT implemented here)
---------------------------------------------------------------
A future live connector (a separate, network-enabled implementation of
:class:`FederalConnector`) would read from these public endpoints. This
module deliberately implements **none** of the HTTP below — it imports no
``requests``/``httpx``/``socket``/``urllib`` and reads no credentials:

* **USAspending.gov** — a public, **no-API-key** API.

  - Awards: ``POST https://api.usaspending.gov/api/v2/search/spending_by_award/``
    with a JSON body of ``filters`` (time period, agency, recipient, award
    type) and requested ``fields``.
  - Award detail / modifications (transaction history):
    ``GET https://api.usaspending.gov/api/v2/awards/<award_id>/`` and
    ``POST https://api.usaspending.gov/api/v2/transactions/`` for the
    modification (transaction) history of a given award.

* **Treasury Fiscal Data** — public, no key:
  ``GET https://api.fiscaldata.treasury.gov/services/api/fiscal_service/<dataset>``
  (query-string ``filter``/``fields``/``page`` parameters) for outlay and
  disbursement datasets.

* **SAM.gov** — entity (recipient) registration; requires a registered API
  key: ``GET https://api.sam.gov/entity-information/v3/entities``. (A live
  adapter supplies the key out-of-band; this module never reads one.)

* **GAO** — U.S. Government Accountability Office reports/decisions, consumed
  from published report listings (``https://www.gao.gov/reports-testimonies``).

A live adapter would additionally wrap each fetch in a :class:`SourceRecord`
(provenance) and validate payloads against ``strix.federal.models`` before
returning typed models. None of that network behavior lives here.

Honesty / safety
----------------
Everything in this module is fixture-backed and offline. Digests assert
content identity of the *preserved payload*, never that the underlying data
is factually complete or that any detected inconsistency is fraud.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime

from strix.canonical import canonical_hash
from strix.federal.models import AwardModification, FederalAward
from strix.models import StrixModel

__all__ = [
    "FederalConnector",
    "FixtureFederalConnector",
    "SourceRecord",
    "make_source_record",
]


class SourceRecord(StrixModel):
    """Provenance for one fetch from a federal source.

    Records *that* a payload was retrieved and *what* its content digest is,
    so a fetch can be reproduced and integrity-checked later. The
    ``source_digest`` is the canonical hash of the fetched payload and is
    independent of ``retrieved_at`` (the wall-clock time of retrieval is
    provenance, not content). The digest asserts content identity only — it
    makes no claim that the data is factually complete or correct.
    """

    #: Name of the source this payload came from (e.g. ``"usaspending"``).
    source_name: str
    #: Wall-clock time the payload was retrieved (timezone-aware).
    retrieved_at: AwareDatetime
    #: Number of records in the fetched payload.
    record_count: int
    #: SHA-256 hex of the canonical serialization of the payload.
    source_digest: str


def make_source_record(
    source_name: str,
    records: Sequence[StrixModel],
    retrieved_at: AwareDatetime,
) -> SourceRecord:
    """Build a :class:`SourceRecord` for a fetched payload.

    The digest is computed from ``records`` alone (via
    :func:`strix.canonical.canonical_hash`), so identical payloads always
    produce the identical digest regardless of ``retrieved_at``.
    """
    return SourceRecord(
        source_name=source_name,
        retrieved_at=retrieved_at,
        record_count=len(records),
        source_digest=canonical_hash(tuple(records)),
    )


@runtime_checkable
class FederalConnector(Protocol):
    """Read-only contract for a federal spending source adapter.

    An implementation retrieves awards and award modifications from a source
    of record. It is **read-only**: there is no write, submit, mutate, or
    delete method, and implementations must not add one.
    """

    #: Human-readable name of the underlying source.
    source_name: str

    def fetch_awards(self, query: dict[str, object]) -> tuple[FederalAward, ...]:
        """Return awards matching ``query`` (empty ``query`` returns all).

        A query key that is not a field of :class:`FederalAward` matches
        nothing — the result is an empty tuple, never an error.
        """
        ...

    def fetch_modifications(self, award_id: str) -> tuple[AwardModification, ...]:
        """Return modifications for ``award_id`` (empty if none)."""
        ...


def _award_matches(award: FederalAward, query: Mapping[str, object]) -> bool:
    """Return whether *award* satisfies every key/value in *query*.

    A key that is not a model field can never match, so an unknown query
    yields no matches rather than raising.
    """
    fields = type(award).model_fields
    for key, value in query.items():
        if key not in fields:
            return False
        if getattr(award, key) != value:
            return False
    return True


class FixtureFederalConnector:
    """Deterministic, offline :class:`FederalConnector` serving fixtures.

    Holds preserved tuples of awards and modifications and serves them with
    no network access, proving the adapter contract in isolation. Filtering
    is a pure, order-preserving scan over the preserved fixtures.
    """

    def __init__(
        self,
        source_name: str,
        awards: Sequence[FederalAward],
        modifications: Sequence[AwardModification],
    ) -> None:
        self.source_name = source_name
        self._awards: tuple[FederalAward, ...] = tuple(awards)
        self._modifications: tuple[AwardModification, ...] = tuple(modifications)

    def fetch_awards(self, query: dict[str, object]) -> tuple[FederalAward, ...]:
        """Return preserved awards matching ``query`` (all if ``query`` empty).

        An unknown query key matches nothing and yields an empty tuple.
        """
        return tuple(
            award for award in self._awards if _award_matches(award, query)
        )

    def fetch_modifications(self, award_id: str) -> tuple[AwardModification, ...]:
        """Return preserved modifications whose ``award_id`` matches.

        An unknown ``award_id`` yields an empty tuple.
        """
        return tuple(
            mod for mod in self._modifications if mod.award_id == award_id
        )

    def source_record(
        self,
        records: Sequence[StrixModel],
        retrieved_at: AwareDatetime,
    ) -> SourceRecord:
        """Build the provenance :class:`SourceRecord` for a fetched payload."""
        return make_source_record(self.source_name, records, retrieved_at)

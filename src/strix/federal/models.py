"""Federal procurement schemas with distinct money semantics.

These models adapt federal spending records onto STRIX's typed, frozen,
exact-:class:`~decimal.Decimal` modeling conventions. They reuse
:class:`strix.models.StrixModel` (frozen, ``extra="forbid"``) and
:data:`strix.models.DecimalValue` (money is ``Decimal``, never ``float``).

Money-kind discipline
---------------------
Federal spending distinguishes several monetary quantities that describe
different stages of the procurement lifecycle. :class:`MoneyKind` enumerates
them and they are **not interchangeable**:

* ``award_amount`` — the total potential value of an award (ceiling).
* ``obligation`` — funds the government is legally bound to pay.
* ``deobligation`` — a reduction of a prior obligation (released funds).
* ``outlay`` — funds actually paid out (disbursed from Treasury) against
  obligations.
* ``disbursement`` — a payment event to a recipient.
* ``modification_amount`` — the signed change to an award's obligated value
  carried by a contract modification.

Obligation is not outlay; an award may be fully obligated yet not outlayed.
Anomalies detected across these quantities are described as
"anomaly"/"inconsistency" and are **never** classified as confirmed fraud.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from strix.canonical import make_id
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "Agency",
    "AwardModification",
    "Contractor",
    "FederalAward",
    "FederalError",
    "MoneyKind",
    "make_award",
]


class FederalError(StrixError):
    """A federal procurement adapter failure (parsing, mapping, or validation)."""


class MoneyKind(StrEnum):
    """Distinct federal monetary quantities.

    These members are **semantically distinct and never interchangeable**:
    an obligation is not an outlay, a deobligation is not a disbursement, and
    an award ceiling (``award_amount``) is neither obligated nor outlayed by
    virtue of existing. Code that needs a monetary quantity must name exactly
    which kind it means.
    """

    AWARD_AMOUNT = "award_amount"
    OBLIGATION = "obligation"
    DEOBLIGATION = "deobligation"
    OUTLAY = "outlay"
    DISBURSEMENT = "disbursement"
    MODIFICATION_AMOUNT = "modification_amount"


class Agency(StrixModel):
    """A federal awarding (or funding) agency."""

    agency_id: str
    name: str
    #: Treasury Account Symbol top-tier code (e.g. ``"097"``); optional.
    toptier_code: str = ""


class Contractor(StrixModel):
    """A federal award recipient (prime contractor or grantee)."""

    contractor_id: str
    name: str
    #: Unique Entity Identifier (SAM.gov UEI); the current entity key.
    uei: str = ""
    #: Legacy DUNS number (retired 2022); retained for historical records.
    duns: str = ""
    #: UEI of the immediate parent entity, if this is a subsidiary.
    parent_uei: str | None = None


class FederalAward(StrixModel):
    """A federal contract or assistance award.

    ``award_amount``, ``obligated_amount``, and ``outlayed_amount`` are
    independent monetary fields describing distinct lifecycle stages
    (see :class:`MoneyKind`). An award may be fully obligated yet have a
    zero outlay; these fields must never be conflated.
    """

    #: PIID (contracts) or FAIN (assistance) award identifier.
    award_id: str
    #: UEI of the recipient (links to :class:`Contractor`).
    recipient_uei: str
    #: Awarding agency identifier (links to :class:`Agency`).
    agency_id: str
    #: Total potential value / ceiling of the award.
    award_amount: DecimalValue
    #: Funds the government is legally obligated to pay under the award.
    obligated_amount: DecimalValue
    #: Funds actually paid out (disbursed) against obligations.
    outlayed_amount: DecimalValue = Decimal(0)
    #: Latest action date for the award record.
    action_date: date
    period_of_performance_start: date | None = None
    #: North American Industry Classification System code.
    naics: str = ""
    description: str = ""


class AwardModification(StrixModel):
    """A contract modification carrying a signed change to obligated value.

    ``modification_amount`` is **signed**: a positive value is an obligation
    increase, a negative value is a deobligation. The sign is load-bearing
    and must be preserved exactly.
    """

    modification_id: str
    #: Identifier of the award this modification applies to.
    award_id: str
    #: Signed obligation change: positive = increase, negative = deobligation.
    modification_amount: DecimalValue
    action_date: date
    reason: str = ""


def make_award(
    *,
    award_id: str = "",
    recipient_uei: str,
    agency_id: str,
    award_amount: Decimal,
    obligated_amount: Decimal,
    outlayed_amount: Decimal = Decimal(0),
    action_date: date,
    period_of_performance_start: date | None = None,
    naics: str = "",
    description: str = "",
) -> FederalAward:
    """Build a :class:`FederalAward` with a deterministic content id (``AWD-``).

    The ``award_id`` is derived from the award's reproducible content so that
    identical awards always produce the identical identifier. The supplied
    ``award_id`` argument is the source PIID/FAIN and is folded into the
    content payload but does not become the model's ``award_id``.
    """
    payload = {
        "source_award_id": award_id,
        "recipient_uei": recipient_uei,
        "agency_id": agency_id,
        "award_amount": award_amount,
        "obligated_amount": obligated_amount,
        "outlayed_amount": outlayed_amount,
        "action_date": action_date,
        "period_of_performance_start": period_of_performance_start,
        "naics": naics,
        "description": description,
    }
    return FederalAward(
        award_id=make_id("AWD", payload),
        recipient_uei=recipient_uei,
        agency_id=agency_id,
        award_amount=award_amount,
        obligated_amount=obligated_amount,
        outlayed_amount=outlayed_amount,
        action_date=action_date,
        period_of_performance_start=period_of_performance_start,
        naics=naics,
        description=description,
    )

"""Single-sourced Decimal precision/rounding for the retrieval layer (§6.C).

Lives in its own low-level module so both ``index`` (which computes the average
document length) and ``bm25`` (which scores) pin the SAME precision without a
circular import. Every non-integer Decimal in retrieval is produced under this
context, so values are reproducible regardless of the caller's ambient context and
recomputable from the :class:`RetrievalContract`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN

#: Working precision for all retrieval Decimal arithmetic.
RETRIEVAL_PRECISION = 50
RETRIEVAL_ROUNDING = ROUND_HALF_EVEN

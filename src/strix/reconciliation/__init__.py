"""Heterogeneous evidence reconciliation and data integrity (R1 §12, GAP-003).

This package generalizes the C-engine data-integrity patterns into reusable,
deterministic checks over typed observations and aggregate reconciliation.

Two surfaces:

- :mod:`strix.reconciliation.integrity` screens a sequence of observations for
  duplicates, missing periods, temporal inconsistency, timestamp skew,
  coverage gaps, and measurement-unit mismatches.
- :mod:`strix.reconciliation.reconcile` reconstructs an observed aggregate from
  its components within exact Decimal tolerances and screens a numeric series
  for statistical anomalies.

Everything here produces **evidence** for the verifier (R1 §12.4): a
:class:`~strix.reconciliation.reconcile.ReconciliationResult` or an integrity
finding never assigns claim admission. Statistical anomalies trigger
*investigation*, never automatic rejection (R1 §12.3). All arithmetic is exact
:class:`~decimal.Decimal`; ``float`` is forbidden throughout.
"""

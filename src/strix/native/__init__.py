"""STRIX native quantitative computing layer (Milestone R1).

A portable, CPU-first numerical/statistical foundation callable directly by the
research agent. It extends STRIX's existing exact-Decimal discipline
(``strix.analytics.profitability``, ``strix.agent.calculations``) to the full
R1 §6/§7 surface: checked arithmetic, descriptive/time-series/multivariate/
inference statistics, numerical contracts, and typed evidence-compatible
computation results.

Design rules (R1 §5.1, §7):

- Exact :class:`decimal.Decimal` arithmetic inside a *local* context; the global
  decimal context is never mutated.
- Binary ``float`` is forbidden at every boundary; NaN/Inf are rejected.
- Authoritative monetary/financial quantities are never silently converted to
  binary floating point.
- Every operation declares a numerical contract (representation, precision,
  rounding, tolerance) so an independent backend can be certified for parity.
- No backend may assign an authoritative factual claim verdict; this layer only
  produces :class:`~strix.native.results.ComputationResult` evidence.
"""

from __future__ import annotations

__all__ = ["arithmetic"]

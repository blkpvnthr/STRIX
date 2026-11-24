"""Offline, decimal-exact personal-finance ledger engine.

This package is the deterministic double-entry accounting core: it never
touches the network and never aggregates live accounts (Plaid/Teller/
SnapTrade live connectors are a separate, credential-gated step). All
monetary amounts are exact :class:`~decimal.Decimal` values; binary
``float`` is rejected at the model boundary.
"""

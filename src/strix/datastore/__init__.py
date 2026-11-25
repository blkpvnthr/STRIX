"""Typed analytical datastore: Parquet + Apache Arrow + DuckDB (§7).

A domain-independent, Decimal-safe analytical layer: typed Arrow tables persisted as
content-addressed, atomically-replaced Parquet datasets with integrity-validatable
manifests, queried through a governed DuckDB interface that exposes only
parameterized aggregations over whitelisted columns (never arbitrary SQL). This is
the analytical complement to the PostgreSQL operational authority and the durable
outbox; it preserves exact Decimal money end to end.
"""

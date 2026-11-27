"""Versioned PyArrow schemas and dataset metadata for the Silver layer.

Each dataset declares its grain, natural key, partition keys, financial units,
timestamp semantics, decimal precision, revision handling, and the lineage
columns every row carries. Financial values use ``decimal128`` (never floats).
Timestamps are UTC microseconds; calendar dates (session/observation/reporting)
stay as ``date32`` so monthly economic data is never represented as daily.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pyarrow as pa

from strix.lakehouse.contracts import DataSource
from strix.lakehouse.silver import SILVER_VERSION

# Lineage columns present on EVERY Silver row (observation -> Bronze artifact).
LINEAGE_FIELDS: list[pa.Field[pa.DataType]] = [
    pa.field("natural_key", pa.string(), nullable=False),  # surrogate = hash(natural key)
    pa.field("source_feed", pa.string(), nullable=False),
    pa.field("bronze_artifact_id", pa.string(), nullable=False),
    pa.field("source_locator", pa.string(), nullable=False),
    pa.field("retrieved_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("schema_version", pa.string(), nullable=False),
]


@dataclass(frozen=True)
class DatasetSchema:
    """Everything needed to normalize, publish, validate, and reconcile a dataset."""

    name: str
    source: DataSource
    arrow_schema: pa.Schema
    grain: str
    natural_keys: tuple[str, ...]
    partition_keys: tuple[str, ...]
    unit_doc: str
    timestamp_doc: str
    revision_policy: str
    schema_version: str = SILVER_VERSION
    #: Fields that may legitimately be null (beyond arrow nullability).
    nullable_value_fields: tuple[str, ...] = field(default_factory=tuple)

    def with_lineage(self, fields: list[pa.Field[pa.DataType]]) -> pa.Schema:
        return pa.schema([*fields, *LINEAGE_FIELDS])


def _schema(core: list[pa.Field[pa.DataType]]) -> pa.Schema:
    return pa.schema([*core, *LINEAGE_FIELDS])


# --------------------------------------------------------------------------
# Alpaca daily equity bars
# --------------------------------------------------------------------------

_ALPACA_BARS = DatasetSchema(
    name="alpaca_equity_bars_daily",
    source=DataSource.ALPACA,
    arrow_schema=_schema(
        [
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("timeframe", pa.string(), nullable=False),
            pa.field("session_date", pa.date32(), nullable=False),
            pa.field("observation_ts", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("open", pa.decimal128(18, 6), nullable=False),
            pa.field("high", pa.decimal128(18, 6), nullable=False),
            pa.field("low", pa.decimal128(18, 6), nullable=False),
            pa.field("close", pa.decimal128(18, 6), nullable=False),
            pa.field("volume", pa.int64(), nullable=False),
            pa.field("trade_count", pa.int64(), nullable=True),
            pa.field("vwap", pa.decimal128(18, 6), nullable=True),
        ]
    ),
    grain="one adjusted daily bar per (symbol, timeframe, session_date)",
    natural_keys=("source_feed", "symbol", "timeframe", "session_date"),
    partition_keys=("symbol",),
    unit_doc="prices in USD (decimal128(18,6)); volume as integer shares",
    timestamp_doc="session_date is the UTC date of the daily bar (= US trading day); "
    "observation_ts is the bar's UTC timestamp",
    revision_policy="adjusted='all'; a re-fetch with different adjusted values replaces the "
    "prior row for the same natural key (latest retrieval wins), prior value quarantined",
    nullable_value_fields=("trade_count", "vwap"),
)

# --------------------------------------------------------------------------
# SEC EDGAR company facts (nested financial observations)
# --------------------------------------------------------------------------

_SEC_FACTS = DatasetSchema(
    name="sec_company_facts",
    source=DataSource.SEC_EDGAR,
    arrow_schema=_schema(
        [
            pa.field("cik", pa.string(), nullable=False),
            pa.field("taxonomy", pa.string(), nullable=False),
            pa.field("concept", pa.string(), nullable=False),
            pa.field("unit", pa.string(), nullable=False),
            pa.field("period_start", pa.date32(), nullable=True),
            pa.field("period_end", pa.date32(), nullable=False),
            pa.field("fiscal_year", pa.int32(), nullable=True),
            pa.field("fiscal_period", pa.string(), nullable=True),
            pa.field("form", pa.string(), nullable=True),
            pa.field("filed_date", pa.date32(), nullable=False),
            pa.field("accession", pa.string(), nullable=True),
            pa.field("frame", pa.string(), nullable=True),
            pa.field("value", pa.decimal128(28, 4), nullable=False),
        ]
    ),
    grain="one reported financial observation per (cik, taxonomy, concept, unit, "
    "period_start, period_end, accession)",
    natural_keys=(
        "cik", "taxonomy", "concept", "unit", "period_start", "period_end", "accession",
    ),
    partition_keys=("cik",),
    unit_doc="value in the stated XBRL unit (USD, USD/shares, shares); "
    "decimal128(28,4); negatives are valid (losses)",
    timestamp_doc="period_start/period_end are the reporting period; filed_date is the "
    "SEC filing date; distinct accessions for the same period are revisions/restatements",
    revision_policy="each filing (accession) is a distinct observation; restatements are "
    "retained as separate rows (same period, different accession)",
    nullable_value_fields=("period_start", "fiscal_year", "fiscal_period", "form", "frame",
                           "accession"),
)

# --------------------------------------------------------------------------
# US Treasury par yield curve
# --------------------------------------------------------------------------

_TREASURY = DatasetSchema(
    name="treasury_yield_curve",
    source=DataSource.US_TREASURY,
    arrow_schema=_schema(
        [
            pa.field("date", pa.date32(), nullable=False),
            pa.field("tenor", pa.string(), nullable=False),
            pa.field("yield_pct", pa.decimal128(9, 4), nullable=False),
        ]
    ),
    grain="one par yield per (date, tenor)",
    natural_keys=("source_feed", "date", "tenor"),
    partition_keys=("year",),
    unit_doc="yield_pct in percent (decimal128(9,4)); negatives permitted",
    timestamp_doc="date is the business date of the yield curve observation (UTC date)",
    revision_policy="Treasury revisions for a date replace the prior value (latest retrieval "
    "wins); prior differing value quarantined, never discarded",
)

# --------------------------------------------------------------------------
# BLS timeseries observations
# --------------------------------------------------------------------------

_BLS = DatasetSchema(
    name="bls_observations",
    source=DataSource.BLS,
    arrow_schema=_schema(
        [
            pa.field("series_id", pa.string(), nullable=False),
            pa.field("year", pa.int32(), nullable=False),
            pa.field("period", pa.string(), nullable=False),  # M01..M12, M13=annual
            pa.field("period_name", pa.string(), nullable=True),
            pa.field("frequency", pa.string(), nullable=False),  # monthly/annual
            pa.field("observation_date", pa.date32(), nullable=False),
            pa.field("value", pa.decimal128(28, 6), nullable=False),
            pa.field("footnotes", pa.string(), nullable=True),
        ]
    ),
    grain="one observation per (series_id, year, period)",
    natural_keys=("series_id", "year", "period"),
    partition_keys=("series_id",),
    unit_doc="value in the series' native unit (index, percent, thousands); decimal128(28,6)",
    timestamp_doc="monthly data keeps period=M01..M12 and observation_date=first-of-month; "
    "NEVER represented as daily. period=M13 is the annual average",
    revision_policy="identical observations across volatile response envelopes dedup to one "
    "canonical row; a changed value for the same period is a revision (latest retrieval wins), "
    "prior value quarantined",
    nullable_value_fields=("period_name", "footnotes"),
)

# --------------------------------------------------------------------------
# FRED series observations (carry vintage)
# --------------------------------------------------------------------------

_FRED = DatasetSchema(
    name="fred_observations",
    source=DataSource.FRED,
    arrow_schema=_schema(
        [
            pa.field("series_id", pa.string(), nullable=False),
            pa.field("observation_date", pa.date32(), nullable=False),
            pa.field("realtime_start", pa.date32(), nullable=False),
            pa.field("realtime_end", pa.date32(), nullable=False),
            pa.field("value", pa.decimal128(28, 10), nullable=True),  # "." -> null
        ]
    ),
    grain="one observation per (series_id, observation_date, realtime_start) [vintage]",
    natural_keys=("series_id", "observation_date", "realtime_start"),
    partition_keys=("series_id",),
    unit_doc="value in the series' native unit; decimal128(28,10); null when FRED reports '.'; "
    "negatives permitted (e.g. real rates)",
    timestamp_doc="observation_date is the data date; realtime_start/end are the FRED vintage "
    "window (revision vintages are distinct observations)",
    revision_policy="FRED vintages (realtime_start) are part of the natural key, so revisions "
    "are retained as distinct rows",
    nullable_value_fields=("value",),
)


SILVER_SCHEMAS: dict[str, DatasetSchema] = {
    s.name: s
    for s in (_ALPACA_BARS, _SEC_FACTS, _TREASURY, _BLS, _FRED)
}

#: Map a (source, bronze dataset) to its Silver dataset name.
BRONZE_TO_SILVER: dict[tuple[DataSource, str], str] = {
    (DataSource.ALPACA, "equity_bars_daily"): "alpaca_equity_bars_daily",
    (DataSource.SEC_EDGAR, "company_facts"): "sec_company_facts",
    (DataSource.US_TREASURY, "daily_treasury_yield_curve"): "treasury_yield_curve",
    (DataSource.BLS, "timeseries"): "bls_observations",
    (DataSource.FRED, "series_observations"): "fred_observations",
}

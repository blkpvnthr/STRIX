"""Shared helpers and sample payloads for Silver tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from strix.canonical import canonical_hash
from strix.lakehouse.contracts import (
    DataSource,
    ProvenanceManifest,
    RawArtifact,
)
from strix.lakehouse.silver.schemas import SILVER_SCHEMAS

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def mk_manifest(
    source: DataSource,
    dataset: str,
    *,
    entity: str | None = "X",
    retrieved_at: datetime = NOW,
    params: dict[str, str] | None = None,
    content_hash: str = "a" * 64,
) -> ProvenanceManifest:
    artifact = RawArtifact(
        artifact_id=f"RAW-{content_hash[:12]}",
        source=source,
        dataset=dataset,
        entity=entity,
        partition="full",
        content_hash=content_hash,
        byte_size=1,
        media_type="application/json",
        relative_path=f"bronze/{source.value}/{dataset}/x.json",
    )
    return ProvenanceManifest(
        ingestion_id=f"ING-{content_hash[:12]}",
        source=source,
        dataset=dataset,
        entity=entity,
        partition="full",
        endpoint="https://example/x",
        request_params=params or {},
        retrieved_at=retrieved_at,
        artifact=artifact,
        record_count=None,
        producer="test",
    )


def enrich(dataset: str, rows: list[dict[str, Any]], *, retrieved_at: datetime = NOW,
           bronze_artifact_id: str = "RAW-abc") -> list[dict[str, Any]]:
    """Attach lineage columns the engine would add (for dedup/unit tests)."""
    schema = SILVER_SCHEMAS[dataset]
    for row in rows:
        row["source_feed"] = schema.source.value
        row["bronze_artifact_id"] = bronze_artifact_id
        row["retrieved_at"] = retrieved_at
        row["schema_version"] = schema.schema_version
        row["natural_key"] = canonical_hash({k: row.get(k) for k in schema.natural_keys})
    return rows


# -- sample source payloads -------------------------------------------------

ALPACA_BARS = json.dumps(
    {
        "bars": [
            {"t": "2026-11-19T05:00:00Z", "o": 100.0, "h": 101.5, "l": 99.5, "c": 101.0,
             "v": 1000000, "n": 5000, "vw": 100.6},
            {"t": "2026-11-20T05:00:00Z", "o": 101.0, "h": 103.0, "l": 100.0, "c": 102.25,
             "v": 1200000, "n": 6000, "vw": 101.9},
        ],
        "next_page_token": None,
    }
).encode()

SEC_FACTS = json.dumps(
    {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2025-06-29", "end": "2025-09-27", "val": 102000000000,
                             "accn": "0000320193-25-000100", "fy": 2025, "fp": "Q4",
                             "form": "10-K", "filed": "2025-10-31"},
                        ]
                    }
                }
            }
        },
    }
).encode()

TREASURY_XML = (
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
    b'xmlns:d="x" xmlns:m="y"><entry><content><m:properties>'
    b"<d:NEW_DATE>2026-11-20T00:00:00</d:NEW_DATE>"
    b"<d:BC_2YEAR>4.12</d:BC_2YEAR><d:BC_10YEAR>4.45</d:BC_10YEAR>"
    b"<d:BC_30YEAR></d:BC_30YEAR>"
    b"</m:properties></content></entry></feed>"
)

BLS_PAYLOAD = json.dumps(
    {
        "Results": {
            "series": [
                {
                    "seriesID": "CUUR0000SA0",
                    "data": [
                        {"year": "2026", "period": "M10", "periodName": "October",
                         "value": "315.5", "footnotes": [{}]},
                        {"year": "2026", "period": "M09", "periodName": "September",
                         "value": "314.8", "footnotes": [{}]},
                    ],
                }
            ]
        }
    }
).encode()

FRED_PAYLOAD = json.dumps(
    {
        "observations": [
            {"date": "2026-11-19", "value": "4.45", "realtime_start": "2026-11-20",
             "realtime_end": "9999-12-31"},
            {"date": "2026-11-20", "value": ".", "realtime_start": "2026-11-20",
             "realtime_end": "9999-12-31"},
        ]
    }
).encode()

"""Tests for lakehouse typed contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from strix.lakehouse.contracts import (
    DatasetRef,
    DataSource,
    ProvenanceManifest,
    RawArtifact,
)

_HASH = "a" * 64


def test_dataset_ref_defaults_and_validation() -> None:
    ref = DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY")
    assert ref.partition == "full"
    assert ref.entity == "SPY"


def test_dataset_ref_rejects_bad_names() -> None:
    with pytest.raises(ValidationError):
        DatasetRef(source=DataSource.ALPACA, dataset="Equity Bars")  # space/uppercase
    with pytest.raises(ValidationError):
        DatasetRef(source=DataSource.FRED, dataset="cpi", entity="../evil")
    with pytest.raises(ValidationError):
        DatasetRef(source=DataSource.FRED, dataset="cpi", partition="2026/01")  # slash


def test_raw_artifact_id_deterministic_and_content_bound() -> None:
    a = RawArtifact.make_id(DataSource.ALPACA, "equity_bars_daily", _HASH)
    b = RawArtifact.make_id(DataSource.ALPACA, "equity_bars_daily", _HASH)
    c = RawArtifact.make_id(DataSource.ALPACA, "equity_bars_daily", "b" * 64)
    assert a == b and a != c and a.startswith("RAW-")


def test_manifest_id_differs_by_retrieval_time() -> None:
    base = (DataSource.FRED, "cpi", _HASH)
    id1 = ProvenanceManifest.make_id(*base, "2026-11-22T00:00:00+00:00", "u", {})
    id2 = ProvenanceManifest.make_id(*base, "2026-11-22T00:00:00+00:00", "u", {})
    id3 = ProvenanceManifest.make_id(*base, "2026-11-23T00:00:00+00:00", "u", {})
    assert id1 == id2  # same event -> same id (idempotent)
    assert id1 != id3  # later re-fetch -> new provenance entry
    assert id1.startswith("ING-")

"""Source-specific Bronze->Silver normalizers.

Each returns a list of row dicts holding the dataset's core schema fields plus a
``source_locator`` pinpointing the record inside the Bronze payload. The engine
adds the remaining lineage columns (natural_key, source_feed, bronze_artifact_id,
retrieved_at, schema_version). Numbers parse to exact ``Decimal`` (never float);
monthly data keeps month granularity (never daily).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# defusedxml hardens against XXE / billion-laughs; Treasury XML is external input.
from defusedxml import ElementTree as DefusedET
from defusedxml.ElementTree import ParseError as DefusedParseError

from strix.errors import LakehouseError
from strix.lakehouse.contracts import ProvenanceManifest

Row = dict[str, Any]
NormalizerFn = Callable[[bytes, ProvenanceManifest], list[Row]]


class NormalizationError(LakehouseError):
    """A Bronze payload could not be normalized (malformed/unexpected shape)."""


def _loads(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"payload is not valid JSON: {exc}") from exc


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    text = str(value).strip()
    if text in ("", ".", "NA", "null", "None"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Alpaca daily bars
# --------------------------------------------------------------------------


def normalize_alpaca_bars(raw: bytes, manifest: ProvenanceManifest) -> list[Row]:
    payload = _loads(raw)
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, list):
        return []
    symbol = (manifest.entity or "").upper()
    rows: list[Row] = []
    for i, bar in enumerate(bars):
        if not isinstance(bar, dict) or "t" not in bar:
            continue
        ts = _ts(bar["t"])
        close = _dec(bar.get("c"))
        if ts is None or close is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "timeframe": manifest.request_params.get("timeframe", "1Day"),
                "session_date": ts.date(),
                "observation_ts": ts,
                "open": _dec(bar.get("o")),
                "high": _dec(bar.get("h")),
                "low": _dec(bar.get("l")),
                "close": close,
                "volume": int(bar.get("v") or 0),
                "trade_count": (int(bar["n"]) if bar.get("n") is not None else None),
                "vwap": _dec(bar.get("vw")),
                "source_locator": f"/bars/{i}",
            }
        )
    return rows


def _ts(value: Any) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        from datetime import UTC

        return parsed.astimezone(UTC)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# SEC EDGAR company facts (nested observations)
# --------------------------------------------------------------------------

_SEC_TAXONOMIES = ("us-gaap", "dei", "ifrs-full", "srt", "invest")


def normalize_sec_company_facts(raw: bytes, manifest: ProvenanceManifest) -> list[Row]:
    payload = _loads(raw)
    if not isinstance(payload, dict):
        return []
    cik_num = payload.get("cik")
    cik = f"CIK{int(cik_num):010d}" if isinstance(cik_num, int) else (manifest.entity or "")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return []
    rows: list[Row] = []
    for taxonomy in _SEC_TAXONOMIES:
        concepts = facts.get(taxonomy)
        if not isinstance(concepts, dict):
            continue
        for concept, body in concepts.items():
            units = (body or {}).get("units") if isinstance(body, dict) else None
            if not isinstance(units, dict):
                continue
            for unit, entries in units.items():
                if not isinstance(entries, list):
                    continue
                for i, e in enumerate(entries):
                    row = _sec_entry(cik, taxonomy, concept, unit, e, i)
                    if row is not None:
                        rows.append(row)
    return rows


def _sec_entry(
    cik: str, taxonomy: str, concept: str, unit: str, e: Any, i: int
) -> Row | None:
    if not isinstance(e, dict):
        return None
    value = _dec(e.get("val"))
    period_end = _date(e.get("end"))
    filed = _date(e.get("filed"))
    if value is None or period_end is None or filed is None:
        return None
    return {
        "cik": cik,
        "taxonomy": taxonomy,
        "concept": str(concept),
        "unit": str(unit),
        "period_start": _date(e.get("start")),
        "period_end": period_end,
        "fiscal_year": (int(e["fy"]) if isinstance(e.get("fy"), int) else None),
        "fiscal_period": (str(e["fp"]) if e.get("fp") else None),
        "form": (str(e["form"]) if e.get("form") else None),
        "filed_date": filed,
        "accession": (str(e["accn"]) if e.get("accn") else None),
        "frame": (str(e["frame"]) if e.get("frame") else None),
        "value": value,
        "source_locator": f"/facts/{taxonomy}/{concept}/units/{unit}/{i}",
    }


# --------------------------------------------------------------------------
# US Treasury par yield curve (XML)
# --------------------------------------------------------------------------

_TENOR_MAP = {
    "BC_1MONTH": "1M", "BC_2MONTH": "2M", "BC_3MONTH": "3M", "BC_4MONTH": "4M",
    "BC_6MONTH": "6M", "BC_1YEAR": "1Y", "BC_2YEAR": "2Y", "BC_3YEAR": "3Y",
    "BC_5YEAR": "5Y", "BC_7YEAR": "7Y", "BC_10YEAR": "10Y", "BC_20YEAR": "20Y",
    "BC_30YEAR": "30Y",
}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_treasury_yields(raw: bytes, manifest: ProvenanceManifest) -> list[Row]:
    try:
        root = DefusedET.fromstring(raw)
    except (DefusedParseError, ValueError) as exc:
        raise NormalizationError(f"invalid Treasury XML: {exc}") from exc
    rows: list[Row] = []
    entries = [el for el in root.iter() if _localname(el.tag) == "entry"]
    for i, entry in enumerate(entries):
        props = {
            _localname(el.tag): (el.text or "").strip()
            for el in entry.iter()
            if _localname(el.tag) in _TENOR_MAP or _localname(el.tag) == "NEW_DATE"
        }
        obs_date = _date(props.get("NEW_DATE"))
        if obs_date is None:
            continue
        for field_name, tenor in _TENOR_MAP.items():
            y = _dec(props.get(field_name))
            if y is None:
                continue
            rows.append(
                {
                    "date": obs_date,
                    "tenor": tenor,
                    "yield_pct": y,
                    "source_locator": f"/entry[{i}]/{field_name}",
                }
            )
    return rows


# --------------------------------------------------------------------------
# BLS timeseries
# --------------------------------------------------------------------------


def normalize_bls(raw: bytes, manifest: ProvenanceManifest) -> list[Row]:
    payload = _loads(raw)
    series_list = (
        payload.get("Results", {}).get("series", []) if isinstance(payload, dict) else []
    )
    rows: list[Row] = []
    for s_idx, series in enumerate(series_list):
        if not isinstance(series, dict):
            continue
        series_id = str(series.get("seriesID") or manifest.entity or "")
        for d_idx, obs in enumerate(series.get("data", []) or []):
            if not isinstance(obs, dict):
                continue
            row = _bls_obs(series_id, obs, s_idx, d_idx)
            if row is not None:
                rows.append(row)
    return rows


def _bls_obs(series_id: str, obs: dict[str, Any], s_idx: int, d_idx: int) -> Row | None:
    value = _dec(obs.get("value"))
    period = str(obs.get("period") or "")
    year = obs.get("year")
    if value is None or not period or year is None:
        return None
    try:
        year_i = int(year)
    except (TypeError, ValueError):
        return None
    if period.startswith("M") and period != "M13":
        month = int(period[1:])
        obs_date, freq = date(year_i, month, 1), "monthly"
    elif period.startswith("Q"):
        quarter = int(period[1:])
        obs_date, freq = date(year_i, (quarter - 1) * 3 + 1, 1), "quarterly"
    else:  # M13 / A01 annual
        obs_date, freq = date(year_i, 1, 1), "annual"
    return {
        "series_id": series_id,
        "year": year_i,
        "period": period,
        "period_name": (str(obs["periodName"]) if obs.get("periodName") else None),
        "frequency": freq,
        "observation_date": obs_date,
        "value": value,
        "footnotes": _bls_footnotes(obs.get("footnotes")),
        "source_locator": f"/Results/series/{s_idx}/data/{d_idx}",
    }


def _bls_footnotes(raw: Any) -> str | None:
    if not isinstance(raw, list):
        return None
    texts = [str(f.get("text")) for f in raw if isinstance(f, dict) and f.get("text")]
    return "; ".join(texts) or None


# --------------------------------------------------------------------------
# FRED observations (carry vintage)
# --------------------------------------------------------------------------


def normalize_fred(raw: bytes, manifest: ProvenanceManifest) -> list[Row]:
    payload = _loads(raw)
    observations = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(observations, list):
        return []
    series_id = str(manifest.request_params.get("series_id") or manifest.entity or "")
    rows: list[Row] = []
    for i, obs in enumerate(observations):
        if not isinstance(obs, dict):
            continue
        obs_date = _date(obs.get("date"))
        rt_start = _date(obs.get("realtime_start"))
        rt_end = _date(obs.get("realtime_end"))
        if obs_date is None or rt_start is None or rt_end is None:
            continue
        rows.append(
            {
                "series_id": series_id,
                "observation_date": obs_date,
                "realtime_start": rt_start,
                "realtime_end": rt_end,
                "value": _dec(obs.get("value")),  # '.' -> None (valid missing)
                "source_locator": f"/observations/{i}",
            }
        )
    return rows


NORMALIZERS: dict[str, NormalizerFn] = {
    "alpaca_equity_bars_daily": normalize_alpaca_bars,
    "sec_company_facts": normalize_sec_company_facts,
    "treasury_yield_curve": normalize_treasury_yields,
    "bls_observations": normalize_bls,
    "fred_observations": normalize_fred,
}

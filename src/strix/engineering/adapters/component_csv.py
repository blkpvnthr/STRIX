"""Component/BOM CSV adapter -> component facts + numeric property facts.

Numeric columns produce Decimal values (float notation like exponents is
rejected) while preserving the original lexical spelling and unit exactly.
No unit conversion is performed.
"""

from __future__ import annotations

import re
from decimal import Decimal

from strix.engineering.adapters.base import (
    AdapterResult,
    build_artifact,
    decode_utf8,
    logical_lines,
    make_fact,
    split_strict_csv,
)
from strix.engineering.models import (
    AnchoredFact,
    ComponentFact,
    CsvAnchor,
    ManifestSource,
    NumericPropertyFact,
    SourceFormat,
)
from strix.errors import EngineeringSourceError

_HEADER = ("part_id", "name", "category", "revision", "mass_kg", "supply_voltage_v")

#: (column, property_name, normalized unit, original unit spelling)
_NUMERIC_COLUMNS = (
    ("mass_kg", "mass", "kg", "kg"),
    ("supply_voltage_v", "supply_voltage", "v", "v"),
)

_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")


def parse_decimal_cell(text: str, filename: str, line: int) -> Decimal:
    """Parse a plain decimal literal; float/exponent notation is rejected."""
    if not _DECIMAL_RE.fullmatch(text):
        raise EngineeringSourceError(
            f"{filename} line {line}: {text!r} is not a plain decimal literal "
            f"(exponent/float notation is rejected)"
        )
    return Decimal(text)


class ComponentCsvAdapter:
    format = SourceFormat.COMPONENT_CSV
    parser_version = "1.0.0"
    schema_version = "1.0.0"

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult:
        text = decode_utf8(raw, entry.file)
        rows = split_strict_csv(logical_lines(text), entry.file, _HEADER)
        artifact = build_artifact(entry, raw, media_type="text/csv")
        facts: list[AnchoredFact] = []
        for line, cells in rows:
            record = dict(zip(_HEADER, cells, strict=True))
            anchor = CsvAnchor(key=record["part_id"], row=line)
            facts.append(
                make_fact(
                    artifact,
                    anchor,
                    ComponentFact(
                        part_id=record["part_id"],
                        name=record["name"],
                        category=record["category"],
                        revision=record["revision"],
                    ),
                )
            )
            for column, property_name, unit, original_unit in _NUMERIC_COLUMNS:
                lexical = record[column]
                facts.append(
                    make_fact(
                        artifact,
                        anchor,
                        NumericPropertyFact(
                            subject_id=record["part_id"],
                            property_name=property_name,
                            value=parse_decimal_cell(lexical, entry.file, line),
                            unit=unit,
                            original_value=lexical,
                            original_unit=original_unit,
                        ),
                    )
                )
        return AdapterResult(artifact=artifact, facts=tuple(facts), diagnostics=())

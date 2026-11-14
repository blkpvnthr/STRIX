"""Engineering change notice CSV adapter -> revision/change facts."""

from __future__ import annotations

from datetime import date

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
    CsvAnchor,
    ManifestSource,
    RevisionChangeFact,
    SourceFormat,
)
from strix.errors import EngineeringSourceError

_HEADER = ("ecn_id", "part_id", "from_revision", "to_revision", "approved_date")


class ChangeNoticeCsvAdapter:
    format = SourceFormat.CHANGE_NOTICE_CSV
    parser_version = "1.0.0"
    schema_version = "1.0.0"

    def parse(self, entry: ManifestSource, raw: bytes) -> AdapterResult:
        text = decode_utf8(raw, entry.file)
        rows = split_strict_csv(logical_lines(text), entry.file, _HEADER)
        artifact = build_artifact(entry, raw, media_type="text/csv")
        facts: list[AnchoredFact] = []
        for line, cells in rows:
            record = dict(zip(_HEADER, cells, strict=True))
            try:
                approved = date.fromisoformat(record["approved_date"])
            except ValueError as exc:
                raise EngineeringSourceError(
                    f"{entry.file} line {line}: approved_date "
                    f"{record['approved_date']!r} is not an ISO date"
                ) from exc
            facts.append(
                make_fact(
                    artifact,
                    CsvAnchor(key=record["ecn_id"], row=line),
                    RevisionChangeFact(
                        ecn_id=record["ecn_id"],
                        part_id=record["part_id"],
                        from_revision=record["from_revision"],
                        to_revision=record["to_revision"],
                        approved_date=approved,
                    ),
                )
            )
        return AdapterResult(artifact=artifact, facts=tuple(facts), diagnostics=())

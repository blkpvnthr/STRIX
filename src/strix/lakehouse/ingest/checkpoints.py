"""Persistent, mutable ingestion checkpoints (incremental watermarks).

Checkpoints are deliberately *mutable* state (a watermark advances), so they live
outside the immutable object store, in ``_checkpoints/<source>/<dataset>/
<entity>.json`` under the lakehouse root, written atomically (temp + fsync +
replace). They make incremental runs resumable and reruns idempotent.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from strix.canonical import pretty_json_bytes
from strix.errors import IngestionError
from strix.lakehouse.contracts import DataSource
from strix.lakehouse.ingest.contracts import Checkpoint


class CheckpointStore:
    """Reads and atomically writes per-entity ingestion checkpoints."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root) / "_checkpoints"

    def _path(self, source: DataSource, dataset: str, entity: str | None) -> Path:
        return self._root / source.value / dataset / f"{entity or '_shared'}.json"

    def load(self, source: DataSource, dataset: str, entity: str | None) -> Checkpoint:
        path = self._path(source, dataset, entity)
        if not path.is_file():
            return Checkpoint(source=source, dataset=dataset, entity=entity)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint.model_validate(data)
        except (OSError, ValueError) as exc:
            raise IngestionError(f"corrupt checkpoint {path}: {exc}") from exc

    def save(self, checkpoint: Checkpoint) -> None:
        path = self._path(checkpoint.source, checkpoint.dataset, checkpoint.entity)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(pretty_json_bytes(checkpoint.model_dump()))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise IngestionError(f"could not write checkpoint {path}: {exc}") from exc

    def all_checkpoints(self) -> list[Checkpoint]:
        if not self._root.is_dir():
            return []
        out: list[Checkpoint] = []
        for path in sorted(self._root.rglob("*.json")):
            try:
                out.append(Checkpoint.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
        return out

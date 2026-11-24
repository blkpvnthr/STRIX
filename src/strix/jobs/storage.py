"""Durable object storage for research run artifacts (Supabase Storage).

A completed run directory (the atomic ``RUN-*`` bundle with its byte-exact
``raw/`` evidence and SHA-256 manifest) is zipped and uploaded to a private
bucket. This is what makes full byte-level, integrity-checked replay possible
after the serverless instance that produced it is gone. Structured artifacts
(answer, claims, evidence, manifest) are *also* mirrored into Postgres by the
executor, so evidence inspection never depends on a storage round-trip; storage
is for the raw bundle and replay.

Uploads use the service-role key server-side only and are best-effort: the
executor never discards a computed result because a storage call failed.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from strix.jobs.models import JobRecord


class SupabaseStorageSink:
    """Uploads/downloads run bundles via the Supabase Storage REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        service_key: str,
        bucket: str = "strix-evidence",
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = service_key
        self._bucket = bucket
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key,
        }

    def object_path(self, job: JobRecord, run_id: str) -> str:
        """Private, ownership-scoped storage key for a run bundle."""
        return f"{job.user_id}/{run_id}.zip"

    def upload_run(self, job: JobRecord, run_dir: Path) -> str | None:
        """Zip and upload the run directory. Returns the storage key or None."""
        run_id = run_dir.name
        archive = _zip_dir(run_dir)
        path = self.object_path(job, run_id)
        url = f"{self._base}/storage/v1/object/{self._bucket}/{path}"
        resp = httpx.post(
            url,
            content=archive,
            headers={
                **self._headers(),
                "Content-Type": "application/zip",
                "x-upsert": "true",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return f"{self._bucket}/{path}"

    def download_run(self, ref: str, dest_state_dir: Path) -> str:
        """Download a run bundle by ``bucket/path`` ref and unzip into
        ``dest_state_dir`` so that ``dest_state_dir/RUN-.../`` exists.

        Returns the restored run id. Raises on any failure.
        """
        url = f"{self._base}/storage/v1/object/{ref}"
        resp = httpx.get(url, headers=self._headers(), timeout=self._timeout)
        resp.raise_for_status()
        dest_state_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            _safe_extract(zf, dest_state_dir)
        run_id = Path(ref).name.removesuffix(".zip")
        return run_id


def _zip_dir(run_dir: Path) -> bytes:
    """Zip ``run_dir`` preserving its top-level directory name (RUN-...)."""
    buffer = io.BytesIO()
    root = run_dir.name
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                arcname = f"{root}/{path.relative_to(run_dir).as_posix()}"
                zf.write(path, arcname)
    return buffer.getvalue()


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract members, refusing any path that escapes ``dest`` (zip-slip)."""
    dest_resolved = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if not str(target).startswith(str(dest_resolved)):
            raise ValueError(f"unsafe archive member path: {member!r}")
    zf.extractall(dest)

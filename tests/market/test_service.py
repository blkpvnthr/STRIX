from __future__ import annotations

from datetime import date
from pathlib import Path

from strix.market.models import ResearchMandate
from strix.service import JobRegistry


def test_registry_enforces_tenant_and_user_ownership(tmp_path: Path) -> None:
    dataset = tmp_path / "unused.csv"
    registry = JobRegistry(tmp_path / "state", dataset)
    mandate = ResearchMandate(
        mandate_id="MANDATE-AUTH-001",
        universe=("AAA", "SPY"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
        benchmark="SPY",
    )
    job = registry.submit("tenant-a", "user-a", mandate)
    assert registry.get_for(job["job_id"], "tenant-b", "user-a") is None
    assert registry.get_for(job["job_id"], "tenant-a", "user-b") is None
    assert registry.get_for(job["job_id"], "tenant-a", "user-a") is not None

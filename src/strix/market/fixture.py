"""Generate the explicitly synthetic, offline daily-bar development fixture."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


def write_demo_daily_bars(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,symbol,open,high,low,close,adj_close,volume"]
    start = date(2024, 1, 2)
    symbols = (
        ("AAA", Decimal("0.002")),
        ("BBB", Decimal("-0.001")),
        ("SPY", Decimal("0.0005")),
    )
    for index in range(120):
        day = start + timedelta(days=index)
        for symbol, drift in symbols:
            price = (Decimal("100") * (Decimal(1) + drift) ** index).quantize(Decimal("0.000001"))
            lines.append(f"{day},{symbol},{price},{price + 1},{price - 1},{price},{price},1000000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    write_demo_daily_bars(Path("fixtures/daily-bars.csv"))


if __name__ == "__main__":
    main()

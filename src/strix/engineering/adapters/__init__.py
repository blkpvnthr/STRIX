"""Source adapters: declared-format dispatch onto typed anchored facts."""

from strix.engineering.adapters.base import (
    AdapterDiagnostic,
    AdapterResult,
    SourceAdapter,
    adapter_for,
    parser_versions,
    schema_versions,
)

__all__ = [
    "AdapterDiagnostic",
    "AdapterResult",
    "SourceAdapter",
    "adapter_for",
    "parser_versions",
    "schema_versions",
]

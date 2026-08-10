"""Typed exception hierarchy for STRIX.

The CLI surfaces only ``str(exc)`` for these errors (never a traceback);
tests and debugging retain the full typed exception.
"""


class StrixError(Exception):
    """Base class for all expected STRIX failures."""


class SourceError(StrixError):
    """A data source could not be fetched, resolved, or parsed."""


class FixtureError(SourceError):
    """The bundled or preserved fixture is missing, malformed, or invalid."""


class CalculationError(StrixError):
    """A deterministic calculation received invalid inputs."""


class ReasonerError(StrixError):
    """The reasoner could not construct a claim from the supplied evidence."""


class RunStoreError(StrixError):
    """Run persistence failed (staging, hashing, or commit)."""


class InvalidRunIdError(StrixError):
    """A run ID failed validation (format or path-containment)."""


class RunNotFoundError(StrixError):
    """No completed run exists for the requested run ID."""


class ReplayError(StrixError):
    """A preserved run could not be loaded for replay."""


class EngineeringSourceError(SourceError):
    """An engineering source (manifest or declared file) could not be
    trusted: missing/unreadable/malformed input, schema violation, policy
    refusal, or anything else preventing trustworthy interpretation."""


class ExportError(StrixError):
    """The export-completeness guard failed: an unverified or unresolvable
    item reached export build. Always an integrity failure."""


def error_code(exc: StrixError) -> str:
    """Machine-readable snake_case code for a typed error (CLI output)."""
    name = type(exc).__name__
    out = [name[0].lower()]
    for char in name[1:]:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)

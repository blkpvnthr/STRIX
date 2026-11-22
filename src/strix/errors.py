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


class CorpusError(StrixError):
    """Base class for all scholarly-corpus subsystem failures."""


class CorpusRootError(CorpusError):
    """The configured evidence root does not exist or is not a directory."""


class PathTraversalError(CorpusError):
    """A supplied relative path attempts to escape the evidence root."""


class CorpusSnapshotError(CorpusError):
    """Snapshot staging or commit failed. Always an integrity failure;
    staging is cleaned up and no partial snapshot is left visible."""


class SourceChangedError(CorpusSnapshotError):
    """A discovered source no longer matches what the scan recorded:
    it disappeared, changed size, became a symlink, or now escapes the
    evidence root. The whole snapshot attempt fails closed."""


class CorpusSnapshotIntegrityError(CorpusSnapshotError):
    """An existing on-disk snapshot failed re-verification (a preserved
    document's bytes no longer match its recorded hash). The snapshot is
    never silently repaired or overwritten."""


class AcquisitionError(CorpusError):
    """A scholarly search or acquisition operation could not be trusted or
    completed as requested (e.g. a plan executed against the wrong
    connector)."""


class UnsafeDestinationError(AcquisitionError):
    """A URL or resolved network address is not safe to connect to: a
    disallowed scheme/port, user info, a fragment, a malformed host, or a
    loopback/private/link-local/multicast/reserved/unspecified/metadata-
    service address. Raised before any byte of the response is read."""


class AcquisitionPolicyError(AcquisitionError):
    """An AcquisitionPolicy rule was violated: a disallowed domain, missing
    access/license authorization, a redirect, document-count, or
    total/per-document size limit, or (see the subclass) a timeout."""


class AcquisitionTimeoutError(AcquisitionPolicyError):
    """A bounded connect/read/write/pool timeout elapsed."""


class PdfValidationError(AcquisitionError):
    """The retrieved content did not pass PDF acceptance checks: an
    unapproved HTTP status, incompatible Content-Type, an HTML/JSON body
    masquerading as a document, or a missing ``%PDF-`` signature. Passing
    these checks is not a claim that the PDF is safe or structurally
    valid — only that it is plausibly a PDF response; full parsing and
    malware inspection are separate, later stages."""


class AcquiredDocumentIntegrityError(AcquisitionError):
    """A different file already exists at a content-addressed acquired-
    document path, or an existing file no longer matches its own name.
    Never silently repaired or overwritten."""


class ParseError(CorpusError):
    """Base class for parser-registry and parsing failures."""


class ParseIntegrityError(ParseError):
    """A chunk or anchor failed independent re-verification against its
    own declared source-line range or recomputed content hash — raised
    by a standalone check function, not a pydantic model validator (which
    raises plain ValueError, per every other model in this codebase)."""


class CorpusDiffError(CorpusError):
    """A corpus manifest comparison could not be trusted or completed."""


class IncompatibleSchemaVersionError(CorpusDiffError):
    """Two manifests declare different CorpusManifest schema_version
    values. Comparing their fields further could silently misinterpret a
    structural change, so this is raised before any comparison is
    attempted — unlike a scanner-version or scan-limit difference, which
    is recorded as a non-fatal compatibility warning instead."""


class ResearchError(StrixError):
    """Base class for strix.research (typed requests, retrieval) failures.

    A sibling of CorpusError, not a subclass of it — strix.research is a
    distinct subsystem built on top of strix.corpus, the same relationship
    strix.engineering and strix.market have to the rest of STRIX."""


class CorpusMismatchError(ResearchError):
    """A ResearchRequest's corpus_id does not match the CorpusManifest
    supplied to retrieval. Retrieval never silently retargets a request
    to a different corpus than the one it was built for."""


class RetrievalIntegrityError(ResearchError):
    """A supplied chunk or ParseResult failed independent re-verification
    (a tampered content hash, an inconsistent document_id, or invalid
    chunk ordering) before scoring could run. Always raised, never
    softened into a per-chunk exclusion reason — this is an integrity
    failure, not a normal retrieval outcome."""


class CandidatePoolTooLargeError(ResearchError):
    """The supplied candidate chunk inventory exceeds the request's
    budget.max_candidate_chunks. Retrieval never silently truncates the
    candidate pool itself — every suggested exclusion reason applies to
    one chunk already in the pool, not to the pool's own size."""


class EvidencePacketMismatchError(ResearchError):
    """A selected retrieval candidate has no corresponding chunk in the
    supplied parse results, or its text/anchor hash does not match what
    the evidence packet is about to record. prepare() never includes an
    evidence item it cannot independently verify."""


class ProviderFailureError(ResearchError):
    """An injected ProposalProvider raised while generating proposals.
    Wraps whatever the provider itself raised; propose() never lets a
    provider's own exception type leak through unlabeled."""


class PreparedProposalMismatchError(ResearchError):
    """A ProposalSet's prepared_id does not match the PreparedResearch
    passed to finalize(). finalize() never structurally validates a
    proposal set against a different prepared result than the one it
    declares it was built from."""


class MalformedProposalError(ResearchError):
    """A provider's response violated a propose()-level structural rule
    (e.g. more proposals than policy.max_proposals permits) that is not
    already enforced by a model's own field validators."""


class UnknownCitationError(ResearchError):
    """A proposal cites a chunk_id not present in the evidence packet, or
    cites a chunk_id together with a document_id that does not match the
    evidence item actually at that chunk_id. Either way, the citation
    does not resolve to real, supplied evidence."""


class VerificationStatusInjectionError(ResearchError):
    """A proposal's status is not PROPOSED. Provider output can never
    assign verification status — checked independently in finalize(),
    not only trusted to a model's own construction-time validator, since
    a proposal reaching finalize() could have been built via a route
    (e.g. model_copy) that bypasses it."""


class IncompleteCorpusPolicyError(ResearchError):
    """prepare() was asked to run against a truncated corpus snapshot and
    the supplied PreparationPolicy does not explicitly permit that
    (allow_incomplete_corpus=False, the default). Policy may instead
    permit it explicitly, in which case prepare() proceeds and records
    the incompleteness as a warning rather than refusing outright."""


class AgentError(StrixError):
    """Base class for the OpenAI research-agent subsystem (strix.agent).

    A sibling of ResearchError/CorpusError, not a subclass — strix.agent is a
    distinct subsystem layered on the rest of STRIX."""


class AgentConfigError(AgentError):
    """Agent configuration is missing or invalid: absent API key, unknown
    model, a non-positive limit, or an out-of-range reasoning effort. Raised
    before any network call so misconfiguration never silently degrades."""


class ModelUnavailableError(AgentConfigError):
    """The configured model is not available to this API key. The agent never
    silently falls back to a different (more expensive) model."""


class ProviderError(AgentError):
    """An OpenAI API call failed in a way the agent could not recover from
    within its retry budget: authentication, a persistent server error, a
    refusal, or an exhausted-retry rate limit/timeout."""


class ProviderTimeoutError(ProviderError):
    """A bounded provider request timed out after its allowed retries."""


class ProviderRateLimitError(ProviderError):
    """The provider rate-limited the request beyond the retry budget."""


class BudgetExceededError(AgentError):
    """A configured research budget was exhausted: model calls, tool calls,
    output tokens, wall-clock seconds, or estimated USD cost. The orchestrator
    stops and returns whatever verified findings it already has."""


class ToolError(AgentError):
    """A research tool could not be executed: unknown tool, invalid arguments,
    or a disabled/unpermitted tool. Tool *data* unavailability is reported as a
    structured unavailable-source result, not raised."""


class ResponseValidationError(AgentError):
    """The synthesized final answer failed fail-closed validation: an
    unresolved citation, a number that matches no accepted calculation, a
    rejected claim presented as fact, or an unsupported assertion. The answer
    is withheld rather than displayed as verified."""


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

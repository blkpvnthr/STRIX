# Milestone R1 — STRIX Repository Baseline Audit

**Audit branch:** `research/formal-evidence-verification`
**STRIX baseline (pinned):** `849018d` (branch `feat/milestone-0b`), audited from `research/formal-evidence-verification`
**C-engine baseline (pinned):** `3a23b13` (branch `feature/m9-runtime-microstructure-execution-learning`)
**Audit date:** 2026-11-24

## Audit scope

This audit establishes the Milestone R1 reuse-first baseline for STRIX at the pinned commits above. It inventories every subsystem that R1 (Resource-Bounded Typed Evidence Verification) must build on or extend, and records for each: what exists, what is reusable as-is, what is incomplete, known weaknesses, temporal/verification gaps, security posture, performance characteristics, tech debt, and what is missing for R1.

Subsystems covered:

1. Evidence & claim data models (`src/strix/models.py`, `canonical.py`, `formatting.py`)
2. Independent verification & deterministic replay (pipeline + agent stacks)
3. Research agent & orchestration (`src/strix/agent`, `research`, `reasoning`)
4. Analytics & calculators (`src/strix/analytics`, `pipeline.py`)
5. Lakehouse, warehouse & run persistence (`src/strix/lakehouse`, `run_store.py`)
6. Source connectors & acquisition (`sources`, `market`, `corpus`, `lakehouse/ingest`, `agent/connectors`)
7. CLI, Web API & service (`cli.py`, `webapi`, `service.py`)
8. Web frontend (`web/`)
9. Engineering traceability vertical (`src/strix/engineering`)
10. 0B requirements baseline, docs & eval infra

## Method (reuse-first)

The audit is reuse-first: every R1 target is first checked against existing STRIX capability before being classed as net-new. Each subsystem was inventoried structurally (typed node types, protocols, verification predicates, persistence primitives) rather than by feature wishlist. R1 areas are classified **present** (exists and directly reusable), **partial** (exists but incomplete or domain-locked), or **absent** (greenfield). The guiding bias is to **extend proven, deterministic, content-addressed primitives** (canonical hashing, frozen typed models, atomic persistence, independent recomputation) rather than rebuild them, and to treat the pervasive gaps — resource-bounded verification, cryptographic signing, decision→outcome entities, and the three fragmented evidence vocabularies — as the explicit R1 build surface.

---

## 1. Evidence & claim data models

**Existing capabilities.** Frozen, closed-schema `StrixModel` base (`ConfigDict(frozen=True, extra='forbid')`) gives tamper-evidence and schema-closure by construction. Full typed lineage chain `SourceArtifact → SourceFact → CalculationResult → Evidence → Claim` with role-ordered input-id tuples carrying provenance edges. Bounded `StrEnum` vocabularies including a 17-member `FailureCode` taxonomy. Decimal-only numeric discipline via `DecimalValue = Annotated[Decimal, BeforeValidator(_reject_float)]`, enforced again in `canonical.to_jsonable`. Canonical serialization (`to_jsonable` / `canonical_bytes`): sorted-key compact UTF-8 JSON, representation-normalized exact Decimal strings, UTC ISO datetimes, enums-by-value; float/bytes/naive-datetime rejected. Content digests (`canonical_hash`, `sha256_hex`) and content-derived ids (`make_id` → `PREFIX-sha256[:12]`). `VerificationResult`/`VerificationFailure`, `RunManifest` (per-stage integrity hashes), `NumericAssertion` (number↔evidence binding), and a pure deterministic display layer (`formatting.render_statement`) designed to be re-rendered verifier-side.

**Reusable as-is.** `canonical.py` in its entirety (dependency-light: hashlib/json/pydantic). `StrixModel` base. `DecimalValue` + `_reject_float`. The `make_id` content-addressing convention (`ID_HASH_LENGTH` a single tunable). The existing five node types map ~1:1 onto five of R1 §9's types and can be adopted/renamed. `FailureCode` + `VerificationFailure` as the certificate-rejection template. `render_statement` "re-render and compare" pattern for verifier-side determinism checks.

**Incomplete.** `CandidateClaim` is only implicit (single `Claim` + `ClaimStatus.PROPOSED`; agent `AgentClaim` is a separate non-canonical structure). Status mutation has no explicit state-machine guard (illegal transitions like `REJECTED→VERIFIED` unguarded). Vocabularies are hard-coded to the operating-margin demo (`Concept` has only REVENUE/OPERATING_INCOME, etc.). `RunManifest` stores integrity hashes but is unsigned (integrity without authenticity). Temporal fields exist (`known_at`, `as_of_date`, `FailureCode.EVIDENCE_AFTER_AS_OF`) but the admissibility check lives in the verifier, not the models.

**Weaknesses.** No certificate abstraction of any kind (zero occurrences of Computation/Claim/Authorization/Outcome certificates). No `SourceObservation` node (raw observation and validated fact collapsed into `SourceFact`). No resource-bound/cost accounting in evidence+claim models (`RetrievalBudget` exists only in `research/models.py`, unlinked). 48-bit truncated ids are a birthday-bound concern at R1 scale; length is global, not per-type. Unbounded `to_jsonable` recursion (DoS surface). Enum-by-value encoding means renaming a value silently changes downstream hashes; no schema-version tag in canonical payloads.

**Temporal / verification gaps.** No model-level validator enforces `known_at <= as_of`. `CalculationResult` has no `known_at` of its own (inferred from input facts in the pipeline). No valid-from/valid-until or bitemporal interval on any node (`observation_period` is a free string). `VerificationResult.checked_at` is wall-clock and hash-excluded (good for determinism, but a certificate would need a separate trusted-time attestation). No monotonic sequence/nonce to detect replay/reorder.

**Security.** Positive: `extra='forbid'` blocks field injection; two-layer float rejection; `source_name` pattern-validated (anti-path-traversal) in `SourceArtifact` and `RunManifest`; `content_hash` 64-hex validated; `make_id` payload excludes self-id/wall-clock/absolute paths. Gaps: integrity without authenticity (unsigned manifests/nodes — a privileged writer can recompute a self-consistent tampered manifest); 48-bit id collision surface; unbounded recursion DoS.

**Performance.** `canonical_bytes` re-serializes the whole graph per hash; pipeline hashes each stage separately (overlapping re-walks). No incremental/Merkle hashing. `to_jsonable` does `model_dump()` then re-walks the dict (double traversal). No hash memoization on frozen models.

**Tech debt.** Single-use-case enum stubs (any new metric touches enum + calculator + formatter + verifier). `display_value` conceptually lives twice. `ResearchResult` mixes a filesystem `Path` into the typed layer. `RunManifest` hash fields are plain `str` (no 64-hex pattern). Two parallel model ecosystems (`strix.models` vs `strix.research.models`/`lakehouse`). `calculation_id` payload shape duplicated per-metric.

**Missing for R1.** All four certificate node types (Computation/Claim/Authorization/Outcome). `SourceObservation`. A distinct first-class `CandidateClaim`. Cryptographic authenticity (keys/signatures/principal-capability model). Resource-bound accounting fields feeding a `ComputationCertificate`. Generic/extensible vocabulary registries. Model-level temporal invariants + bitemporal fields. Explicit status-transition state machines. A canonical schema-version/type-tag embedded in hashed payloads.

---

## 2. Independent verification & deterministic replay

Two parallel, non-unified stacks: **(A)** pipeline verifier `verification/claims.py` + `replay.py` over `strix.models`; **(B)** agent verifier `agent/verifier.py` + `agent/replay.py` over `AgentClaim`/`AgentEvidence`/`ObservationSeries`. Both recompute independently of any LLM; they share no code, vocabulary, or failure taxonomy.

**Existing capabilities.** Pipeline evidence-lineage verification (`_verify_evidence_lineage` walks Evidence→Calc→Fact→Artifact with per-edge FailureCodes). Pipeline claim verification (subject gate, date-granular temporal gate, VERIFIED gate, anti-smuggling: assertion must be cited, value+unit exact match). Comparison completeness + semantic checks (recompute direction sign, re-render prose). Fail-closed publication gate (no claims ⇒ NO_CLAIMS; failed verification publishes nothing). Deterministic replay with dual integrity + reproducibility per stage (recompute from preserved spec+raw via the same `compute()`). Canonical deterministic hashing. Atomic tamper-resistant run store (staging + fsync + atomic rename, raw re-hash, path containment). Agent independent verifier (recompute within `DEFAULT_TOLERANCE=1e-4`, epistemic typing of verdicts, freshness/STALE downgrade). Agent deterministic replay + response/certificate validation (response.json re-hash, citation integrity, classification integrity). Versioned verifiers.

**Reusable as-is.** `canonical.py` end-to-end. `run_store.py` atomic persistence + containment + raw re-hash. `replay.py` dual integrity+reproducibility stage pattern. `_verify_evidence_lineage` as the Provenance predicate kernel. Anti-smuggling pattern as the Support soundness guard. Agent recompute-within-tolerance as the Derivation predicate. `FailureCode` taxonomy. `ReplayStage`/`ClaimReplay`/`ResponseReplay` result shapes. Frozen `StrixModel` base for the Type component.

**Incomplete.** Derivation is only structural in the pipeline verifier (`evidence.value==calc.value`; arithmetic re-execution lives only in `replay.py` and the agent path — a wrong-but-consistent `CalculationResult` passes verify-time). Temporal checking is shallow (date-only as-of, no lineage monotonicity). Manifest/certificate is unsigned (self-referential integrity). Compositional invariants special-cased to one claim type. Two divergent stacks with no shared predicate interface. Agent replay `_created_at` falls back to `datetime.now(UTC)` — a determinism hole for the STALE verdict. No resource accounting anywhere.

**Weaknesses.** No single "admission predicate" abstraction — the five R1 predicates (Integrity/Type-Temporal/Provenance/Derivation/Support) are implicit and scattered, with no typed predicate objects or composition operator. Pipeline verifier "performs no new financial calculation" (independence only partial at verify time). Hardcoded single domain (operating-margin). Agent/pipeline duplication is a correctness risk (tolerance recompute exists only agent-side). Agent response-hash check assumes an unversioned dump form.

**Temporal / verification gaps.** As-of gate compares calendar date only. No lineage temporal monotonicity (`fact.known_at ≤ evidence.known_at ≤ as_of` unasserted). `SourceArtifact.known_at` never checked vs as_of. Agent STALE depends on a `now` that can fall back to wall clock (non-deterministic on replay). No knowledge-horizon/future-leakage check beyond the single as-of gate. `known_at` values are trusted input (not independently recomputed).

**Security.** Strong: path containment + strict name/id patterns defend replay against a tampered manifest; float forbidden everywhere; raw bytes re-hashed on persist and re-verified on replay. Gaps: unsigned manifest (consistent substitution of raw bytes + manifest still passes reproducibility — no external authenticity anchor); agent replay trusts untyped JSON manifest fields.

**Performance.** Verification is O(evidence+claims) with dict lookups (cheap). Replay re-runs the full `compute()` pipeline + re-hashes every artifact (no incremental re-verification — matters once R1 adds bounds). Agent replay loads all evidence into memory (unbounded by design). Arithmetic effectively done twice across the two paths.

**Tech debt.** Two parallel verification/replay implementations with no shared abstraction (primary debt). `verification/__init__.py` is an empty stub. Domain hardcoding to operating-margin. Unsigned `RunManifest` overloaded as integrity record + de-facto certificate. Agent replay untyped manifest access + `datetime.now` fallback. Hash-exclusion contracts documented only in prose.

**Missing for R1.** Resource-bounded verification (budget/cost/fuel/timeout, per-predicate accounting, bounded-work guarantee) — the central R1 primitive, entirely absent. Explicit typed admission-predicate layer (§10). Cryptographic certificate + certificate validation (§13 signing/keys/trust-anchor). General compositional-invariant engine (§11). Unified independent-by-construction Derivation check at verify time. A single shared verification core for both paths. Deterministic temporal predicate (timestamp-precise as-of, lineage monotonicity, replay `now` always derived from preserved data).

---

## 3. Research agent & orchestration

**Existing capabilities.** Bounded LLM tool-calling research loop (model plans/requests typed tools/proposes candidate claims; never sets a verdict). Comprehensive per-run resource accounting (`BudgetTracker`: model calls, tool calls, input/output tokens, wall-clock, USD from real token usage via versioned `PricingConfig`; checks before each call; fail-soft; immutable `BudgetSnapshot`). Typed tool registry (`ToolRegistry`/`ToolSpec`: JSON-schema validation pre-execution, structured errors, dispatch by name). Independent fail-closed verifier (recompute from preserved series, epistemic verdict typing). Deterministic Decimal calculators (`period_return`, `cumulative_return`, `max_drawdown`, `realized_volatility`, `moving_average`, `relative_performance`, `correlation`; single `recompute()` shared by tool and verifier). Deterministic question classification. Evidence preservation (content-addressed, dedup, freshness, alias resolution, replay reload). Synthesis (deterministic stance computed from verified claims + one guarded narrative call). Fail-closed answer validator. Validated config (SecretStr key, versioned pricing of only 4 permitted models). Bounded conversational memory. **Separate** deterministic corpus pipeline `research/` (`prepare→propose→finalize`): deterministic lexical retrieval with typed `RetrievalBudget` + replayable `RetrievalTrace`; provider-neutral `ProposalProvider` seam (no network/tool/credential handle); structural-only `finalize` with `VerificationStatusInjectionError`. `Reasoner` protocol + `DeterministicDemoReasoner`.

**Reusable as-is.** `BudgetTracker` + `BudgetSnapshot` as the R1 §16 substrate (missing only per-sub-goal sub-budget split). `ToolRegistry`/`ToolSpec` essentially as-is. `verifier.py` + `calculations.py` as §21 trust-boundary enforcement. `ProposalProvider`/`propose()`/`finalize()` as the cleanest §21 hybrid-intelligence boundary. `RetrievalBudget` + deterministic selection as a §15 acquisition primitive. `EvidenceCollector`. `ResearchQuestion` schema as the input contract for a real §14 decomposer. `validate_answer` fail-closed template.

**Incomplete.** `get_economic_series` is a hard-coded stub (no FRED key wired). The corpus pipeline stops at `finalize()` (semantic verification/persistence/replay are documented "Phase 11", not implemented — no verifier of its own). No production `ProposalProvider`. `reasoning/` is protocol + demo only. Two disconnected research stacks (agent live-LLM vs corpus deterministic) with no shared vocabulary. Question classification is a fixed English lexicon (~11-name ticker map). Synthesis numeric guard is regex-based.

**Weaknesses.** Acquisition **strategy** is entirely delegated to the LLM (`_run_loop` is a fixed range loop; no planner, no sub-goal prioritization, no value-of-information scoring, no coverage check, no adaptive stopping beyond budget/model-finished/cancel — the core §15 gap). No objective **decomposition** (flat single-shot classification; §14 only shallow). Textual claims verified by verbatim substring presence only. Every tool result truncated to 8000 chars (silent JSON corruption). Agent path trusts hosted `web_search` content (prompt-instruction only, not structurally sandboxed — injection surface). Synthesis budget reservation is a magic constant. The two paths duplicate the "proposer cannot set verdict" invariant in divergent vocabularies. No concurrency/parallel acquisition.

**Temporal / verification gaps.** As_of bounds fetch windows but there is no look-ahead guard matching claimed vs fetched window. Freshness is classified and STALE-downgrades, but there is **no freshness gating** (stale evidence still flows to the answer). Corpus `DateConstraint` dates are explicitly **not enforced** during retrieval. No point-in-time correctness for SEC fundamentals (restatements/amended filings). Verifier reproduces the number but does not re-verify the series' timestamps fall within the claim window. No monotonic-as_of check across conversation turns.

**Security.** Key as SecretStr, redacted before persistence. Web-search/tool content treated as untrusted by **system prompt only** (injection risk). Tool args validated (minimal hand-rolled schema check). `propose()` is a strong capability-restriction boundary. Evidence raw bytes content-hashed. Thread ids regex-validated. Truncation caps are size bounds, not security controls. Run manifests unsigned.

**Performance.** Strictly sequential loop (latency ceiling for multi-security questions). Decimal calculators at prec=50 (slow vs float but exact). `EvidenceCollector` keeps all raw bytes in memory. Token budgets enforced on cumulative usage (a single oversized call can overshoot before the next pre-call check). Synthesis narrative capped at ~1200 tokens.

**Tech debt.** THREE parallel non-integrated research architectures (agent / research / reasoning) with no shared vocabulary — the M1 spec's documented GAP-003 ("three duplicated evidence vocabularies and four independent reconcilers"). The `research/` pipeline is half-built (dead-ended Phase-10/11 scaffolding). Hard-coded domain lexicons. Magic `SYNTHESIS_RESERVED_CALLS=1`. Duplicated verdict/citation invariants. `get_economic_series` stub + `tool_cost_usd=0` placeholders. `estimate_token_count` is char/4. 8000-char JSON mid-slice.

**Missing for R1.** §14 real objective-decomposition component (typed dependent sub-goals, per-sub-goal evidence sufficiency, recombination). §15 explicit resource-constrained acquisition **strategy** layer (candidate-action generation, value-of-information prioritization, per-sub-goal sub-budgets, principled stopping). §15 coverage/gap tracker driving acquisition or abstention. §16 per-strategy/per-sub-goal budget partitioning + real tool-cost model. §21 unified trust boundary across live-tool and typed-evidence paths. §21 a running typed-evidence verifier for the proposer path. Integration: one orchestrator composing decomposition → strategy → typed registry → typed-evidence verification under one budget. First-class abstention at acquisition level.

---

## 4. Analytics & calculators

**Existing capabilities.** `operating_margin` (exact Decimal ratio, 6-dp quantum, ROUND_HALF_EVEN, `localcontext(prec=34)` never mutating global context). `operating_margin_change_pp` (two-period pp difference, 4-dp quantum). Strict typed input validation (concept-role, Unit.USD, shared subject, zero/negative revenue rejection → `CalculationError`). `InvalidOperation` caught and re-raised as `CalculationError`. Typed frozen `CalculationResult` (DecimalValue rejects float, role-ordered lineage tuples). Deterministic content-addressed ids via `make_id`. `CALCULATION_VERSION` stamped and recorded. Pipeline orchestration wiring two periods into previous/current/change. Canonical Decimal serialization + stage hashing.

**Reusable as-is.** The numerical-contract pattern (exact Decimal, float-forbidden `DecimalValue`, fixed prec + ROUND_HALF_EVEN, explicit quanta, `InvalidOperation→CalculationError`) as the R1 §7 template. `CalculationResult` as the typed evidence-carrying envelope. `make_id`/`canonical_hash` content-addressing. The calculator→evidence→claim→verify pipeline harness. The `test_profitability.py` test style. `display_value` dispatch.

**Incomplete.** Only one ratio + one two-period difference exist (a prototype pair, not a library). `CalculationResult.value` is a single scalar Decimal — no typed vector/matrix/CI/p-value/multi-field output. No uncertainty/error propagation. `operating_margin_change_pp` hard-limited to exactly two periods. No sample-size/degrees-of-freedom concept.

**Weaknesses.** Calculator wiring is hard-coded in `_build_calculations` (adding statistics requires editing the pipeline — no registry/dispatch). The verifier does **no** independent re-computation of the calculation itself (a calculator bug is hashed and "verified" as internally consistent). No output sanity invariants beyond revenue sign/overflow. Calculators do no as-of windowing themselves (deferred downstream). Quantum/precision policy is implicit module literals, not recorded on the result.

**Temporal / verification gaps.** Calculators don't validate `known_at ≤ as_of` (relies on downstream `EVIDENCE_AFTER_AS_OF`). No look-ahead protection in multi-period logic (trusts caller-supplied current/previous ordering; only rejects identical periods). No vintage/point-in-time snapshot for restated facts. `observation_period` is an opaque string (no chronological ordering).

**Security.** Pure arithmetic — no network/filesystem/eval. Inputs are already-validated typed models. DoS surface bounded by prec=34 + `InvalidOperation` catch, but no explicit input-magnitude or series-length bound (R1 resource-bounding must formalize).

**Performance.** O(1) scalar Decimal ops; `_build_calculations` linear fact scan per (concept,period). `localcontext()` entered per call (would add overhead in large-series loops — R1 should batch). Decimal materially slower than float. Hashing serializes full sorted dumps per stage.

**Tech debt.** `analytics/__init__.py` is an empty docstring module. Single shared `CALCULATION_VERSION` (needs per-calculator versioning). Precision/rounding policy duplicated inline. Role-ordering enforced by convention, not a typed role wrapper. `observation_period` stringly-typed. Committed `__pycache__` `.pyc` files.

**Missing for R1.** §6 descriptive statistics (mean/median/variance/std/quantiles/skew/kurtosis/count/sum) — none. §6 time-series statistics (returns/rolling/autocorrelation/stationarity/CAGR/volatility beyond the single two-point difference). §6 multivariate (correlation/covariance matrices/regression/beta/cointegration/PCA/ranking). §6 inference (hypothesis tests/t/z/F/p-values/CIs/bootstrap). §7 typed result variant for arrays/matrices/CIs/p-values/sample-size/standard-errors. §7 Decimal policy for sqrt/log/exp/aggregate ops. R1 resource-bounded independent re-computation / numerical-tolerance cross-check of calculator outputs. A calculator registry. NaN/inf/missing-data semantics for Decimal series. *(Note: `agent/calculations.py` does implement correlation/volatility/drawdown deterministically and is reusable raw material for several §6 time-series/multivariate targets, though it lives in the agent subsystem, not `analytics/`.)*

---

## 5. Lakehouse, warehouse & run persistence

**Existing capabilities.** Bronze: immutable content-addressed raw preservation with append-only `ProvenanceManifest`, dedup, read-back hash verification, deterministic path layout. `ObjectStore` seam (atomic temp+fsync+replace, immutability enforcement, path-traversal containment; S3 declared future). Ingestion orchestration (backfill + incremental, persistent watermark checkpoints, partial-failure recovery, coverage/gap, fetched-vs-written reconciliation). Read-only Bronze catalog + `verify_integrity()`. Silver: deterministic full recompute, row-level quality gates, natural-key dedup with quarantine + revision retention, reconciliation that **blocks** publication unless balanced; atomic staged partitioned Parquet (zstd, decimal128) with `PublicationManifest`. Versioned PyArrow schemas (5 datasets, 6 mandatory lineage columns per row). DuckDB warehouse (transactional incremental load, idempotent reload, row_signature accounting, Silver integrity gate, star schema, lineage resolver with hash re-verification, warehouse-side reconciliation). Snowflake adapter (offline SQL-gen). dbt mart layer + controlled `DbtRunner` (allow-listed subcommands, no shell). Independent cross-validation (`transform/verification.py` recomputes mart values via the same Decimal calculators). Run persistence (`run_store.py`: crash-safe atomic run dirs, `RunManifest` integrity, strict sanitization). Decimal-safe storage end to end.

**Reusable as-is.** Bronze immutable store + `ProvenanceManifest`. `ObjectStore` Protocol + `LocalObjectStore`. `make_id` identity pattern. Lineage columns + `lineage()` resolver. Silver reconciliation + quarantine (balanced-or-block) pattern. `transform/verification.py` cross-validation harness. `run_store` atomic commit protocol. `DecimalValue`/`StrixModel` + decimal128/NUMBER storage. `DbtRunner` controlled-subprocess pattern.

**Incomplete.** `fact_research_claims`/`fact_verification_results` are schema-only placeholders (research/verification results not persisted; `mart_research_quality` reports `integration_status='deferred_to_de7_no_warehouse_records'`). Snowflake is SQL-gen + offline only. Coverage detection is best-effort from partition names. Run manifests unsigned. No cross-run index/query over `run_store`. `_load_state` keeps only the current load (no history).

**Weaknesses.** No distinct **assurance** layer (R1 §23 4th medallion): assurance functions exist (Silver reconciliation, Bronze verify, warehouse reconcile, cross-validation) but produce **ephemeral, unpersisted** verdicts. `run_store` is per-execution dirs, not an append-only ordered decision ledger (no hash-chaining/sequence integrity — deletion/reordering not tamper-evident). `publish.py _swap` double-rename is weaker than the single-rename discipline elsewhere. Quarantine overwritten per transform (no history). DELETE+INSERT dimension rebuild (no SCD/history). Hash-derived surrogate keys (`hash(symbol)>>1`) are collision-possible.

**Temporal / verification gaps.** FRED vintages retained (true point-in-time), but BLS/Alpaca/Treasury use latest-wins (prior values quarantined, not bitemporal) — "what did we know as of T" is unreconstructable for those. No as-of/bitemporal warehouse query (no retained load history). Decision/verdict persistence lacks a temporal dimension entirely. Checkpoints are mutable single-value watermarks (no advancement history). Integrity/reconcile/cross-validation verdicts are never timestamped-and-stored.

**Security.** Strong, consistent path-traversal defenses. Immutability enforced by content comparison. `DbtRunner` strong command-injection defense. Secrets via env only (confirm `dbt/profiles.yml` is gitignored and not committed). Manifests unsigned (integrity, not authenticity). `_PROJECTIONS` f-string literals are a latent injection shape if ever fed external data (currently internal-only).

**Performance.** Silver is a full recompute from all Bronze per run (O(all-history); no incremental Bronze→Silver). `load_manifests()` re-parses every manifest per call; `lineage()` scans all manifests per lookup. Single-writer DuckDB. Full dimension rebuild per load. Cross-validation re-queries full series per metric call.

**Tech debt.** DE-7 placeholder debt (`fact_research_claims`/`fact_verification_results` + mart deferral). Two atomic-write implementations (`storage` + `run_store`). `publish._swap` double-rename. Untested live Snowflake. Heuristic coverage-window derivation. Hash-derived surrogate keys. Independent version constants with no compatibility checking.

**Missing for R1.** Durable **decision ledger** (R1 §19 GAP-002): append-only, ordered, tamper-evident (hash-chained/signed) store of ACCEPT/REJECT/QUARANTINE/NEED-MORE-DATA verdicts — entirely absent (`run_store` is not a ledger). Dedicated **assurance** layer (§23 4th medallion) persisting verification/reconciliation/integrity/resource-bound records as durable typed rows. Persistence of typed evidence-verification results. Cryptographic signing/attestation. Durable resource-bound accounting (cost/compute/time). Bitemporal/as-of persistence for point-in-time decision verification. A cross-run/cross-decision query & index surface.

---

## 6. Source connectors & acquisition

Three distinct, non-unified connector protocols: `SourceConnector` (`sources/base.py`), `SearchConnector` (`corpus/acquisition/connectors/base.py`), `SourceExtractor` (`lakehouse/ingest/contracts.py`).

**Existing capabilities.** SEC EDGAR connector (`sources/edgar.py`): ticker→CIK resolution, companyfacts fetch, raw-byte preservation, pure deterministic `parse_companyfacts(raw, ticker, as_of)` with strong point-in-time semantics (`filed ≤ as_of`, earliest-filed-wins, YoY end-date distance, Decimal-only, SEC fair-access User-Agent). Offline demo connector (refuses non-synthetic). Scholarly PDF acquisition (`corpus/acquisition/`): typed `SearchPlan`/`SearchResult`, `PdfDownloader` with layered defense (HTTPS-only, port allowlist, SSRF check per redirect hop, streamed size enforcement, `%PDF-` signature, license gating). SSRF module (`network_safety.py`: IDNA normalization, injectable resolver, rejects loopback/private/link-local/metadata for v4+v6, fails closed). Content-addressed acquired-doc store. Deterministic dedup + URL secret redaction. Lakehouse Bronze ingestion. Five live R1 §22 extractors (Alpaca bars, SEC company_facts, Treasury yield curve XML, BLS v1, FRED — FRED key never persisted). Ingestion orchestration. `HttpFetcher` (rate limiting + bounded backoff, injectable transport). Bronze catalog integrity check. Agent connectors (`sec.py`, `market_data.py` with structured `UnavailableSource`). Market research engine (offline CSV with `DatasetManifest` — **not** a network source).

**Reusable as-is.** EDGAR primitives (already reused by extractor + agent connector — reuse, don't rewrite). `SourceExtractor` + `BronzeIngestor` + `IngestionRunner` + `HttpFetcher` + `CheckpointStore` (extend via new extractor classes + `DataSource` members). `network_safety.py` (should be wired into the lakehouse `HttpFetcher`). Bronze content-addressing + provenance contracts. Typed `SearchPlan`/`SearchResult`/`AcquisitionRecord` (wall-clock-excluded ids). `redact_url` + FRED key-redaction. `AcquisitionPolicy` (resource-bound contract aligned with R1). `catalog.verify_integrity` + Bronze read-back verification.

**Incomplete.** No real `SearchConnector` provider (only `FakeSearchConnector`; Crossref/OpenAlex/arXiv/PubMed deferred). Corpus acquisition is PDF-only. Point-in-time correctness enforced only in `sources/edgar.py` + agent `sec.py`; the lakehouse EDGAR extractor preserves the **full** companyfacts snapshot with no as-of filter (deferred to Silver/DE-3). Coverage windows are heuristics; Treasury `record_count` is a byte-substring count. `RetractionStatus`/`PeerReviewStatus`/`AccessStatus` carried but never enforced. Market engine has no live acquisition (`survivorship_bias_controlled` hardcoded False). DNS-rebinding mitigation not implemented (documented residual).

**Weaknesses.** Duplicated EDGAR point-in-time parsing (`sources/edgar.py` vs agent `sec.py` re-implement earliest-filed-wins/quarter-duration/`filed ≤ as_of` independently — drift risk). Three unrelated connector abstractions with no shared base. Lakehouse `HttpFetcher` fetches arbitrary provider URLs via urllib with **no SSRF guard, no URL-shape validation, no redirect control** — live ingestion of EDGAR/Treasury/BLS/FRED/Alpaca is unprotected (the robust `network_safety.py` is wired only into the corpus PDF path). Bronze provenance identity includes `retrieved_at` wall clock (manifest set not reproducible across re-fetches). Market engine rebuilds indexed dicts per `_returns()` call.

**Temporal / verification gaps.** Bronze EDGAR preserves the full live snapshot with no as-of cut (an R1 verifier reading Bronze directly could leak post-as-of restatements). Alpaca requests `adjustment=all` — prices are retroactively corporate-action-adjusted, i.e. **NOT point-in-time** (no un-adjusted/as-reported path). No verification that preserved bytes cover the claimed observation window. `retrieved_at`/`discovered_at` are wall-clock audit-only (no attestable knowable-at timestamp). No cross-source temporal consistency check.

**Security.** Good: FRED key injected only into the live URL (excluded from provenance); Alpaca creds in headers, never persisted; `redact_url` masks secrets before URLs reach errors/records; corpus `PdfDownloader` defense-in-depth; path-traversal containment reused; symlinks never followed. Risk: lakehouse `HttpFetcher` has no SSRF guard / scheme/port restriction / redirect control (compromised endpoint/redirect could reach internal/metadata addresses). `compute_acquisition_id` does not redact URLs itself (relies on callers). Residual: DNS-rebinding window.

**Performance.** Ticker map cached per instance. `RateLimiter` default 0.35s min-interval. Bounded backoff. Bronze read-back doubles I/O (the integrity guarantee). Market engine recomputes dicts per `_returns` call. EDGAR parse is linear per tag.

**Tech debt.** Two parallel EDGAR point-in-time parsers. Three disjoint connector protocols. Triplicated atomic-write/staging helpers (deliberate but noted). SSRF guard not reused on the lakehouse path. Heuristic coverage derivation. Fragile Treasury `record_count`. Market subsystem mis-named as a "source connector" (it is an offline engine). Two distinct raw-preservation mechanisms for overlapping EDGAR data (`FetchedSource`/run_store vs Bronze).

**Missing for R1.** USAspending, SAM.gov, USGS connectors/extractors — all absent (no `DataSource` enum members). SSRF/URL-safety enforcement on the live ingestion path. A unified typed connector contract spanning search + acquisition with resource bounds attached. Point-in-time/as-reported preservation guarantee at Bronze for §22 sources. Cryptographically signed Bronze/provenance manifests. A real scholarly `SearchConnector` if R1 evidence includes papers.

---

## 7. CLI, Web API & service

**Existing capabilities.** CLI argparse surface: default interactive research, `ask` (→ agent orchestrator), `replay` (mode-dispatch: agent_research / engineering / v1), `engineer compile`, and four lakehouse pipelines (`ingest`/`normalize`/`warehouse`/`transform`). CLI is a pure presentation layer with injectable seams (input_fn/stdout/stderr/clock/reasoner/fixture_path/environ) and typed exit codes. FastAPI web API: `/api/health`, `/api/meta`, `POST /api/research`, `GET /api/research/{id}`, cancel, `/api/history`, `/api/runs/{id}`; static SPA mount. Background job runner (`ResearchService`: worker threads, progress events, cooperative cancel, thread memory, safe error redaction). Canonical JSON serialization for responses. Persisted-run history/detail filtered to `mode=='agent_research'`. Separate stdlib `service.py` gateway (`JobRegistry`: durable `jobs.json`, idempotency keys, bounded-concurrency semaphore, restart recovery, tenant/user/role auth via shared token + headers; campaign endpoints). Feature-flag gating.

**Reusable as-is.** Argparse subparser-builder + delegation convention (add `compute`/`graph`/`verify`/`audit`/`certificate`/`authorization`/`outcome`/`research benchmark`). `main()` dispatch table + injectable seams. `replay` mode-dispatch extension point (add a new run mode). `webapi/serializers.py` `to_jsonable` discipline. `ResearchService` job lifecycle scaffold. `JobRegistry` durable-job pattern (lift into FastAPI). `AgentConfig.load()` server-side key loading. `ResearchOutcome` dataclass as the structured result for an `outcome` command/endpoint.

**Incomplete.** Two parallel non-unified HTTP surfaces (FastAPI agent research, localhost CORS, no auth) vs stdlib `service.py` (campaigns, token+tenant auth, durable) — no shared router/auth/envelope. `webapi` jobs are in-memory only (restart loses queued/running jobs; history reconstructs from disk). No API versioning (`/api` unversioned, `service.py` uses `/v1`). `ask` has no JSON output mode (lakehouse commands do). Scheduler PATCH is a stub. No OpenAPI/schema export or contract test.

**Weaknesses.** Verification is implicit — **no standalone `verify` command** (runs only as a side effect of `ask`/`replay`). No resource budget enforced at the CLI/API boundary (budget is surfaced post-hoc; no pre-flight ceiling, no "resource exhausted" typed response). `replay` branches on a free-form `mode` string (no schema/enum). Manual `path.split('/')` routing in `service.py`. No `graph`/`audit`/`certificate`/`authorization`/`outcome`/`research benchmark` anywhere.

**Temporal / verification gaps.** As-of accepted by `ask`/web API (defaults to today) but no CLI/API validation that persisted evidence respects it (trusts the orchestrator). `replay` has no CLI-level assertion that replay as_of/window matches the original run. History/run_detail expose `created_at` but no as_of/observation-cutoff field. No endpoint/command returns the time-bound "knowable as of T" evidence set.

**Security.** FastAPI app has **no authentication** (localhost-only CORS regex). `service.py` auth uses plain `!=` token compare (timing side-channel) + fully trusted `X-STRIX-*` headers (role escalation if the gateway is bypassed). `service.py` sets good hygiene headers + 64KB body cap; `webapi` sets none. `STRIX_INTERNAL_TOKEN` required at startup (fail-closed). Keys never returned. Error redaction correct. Scheduler PATCH requires admin role but relies on a spoofable header.

**Performance.** `JobRegistry` bounds concurrency; `webapi` has **no** concurrency bound (unbounded thread spawn per POST). `JobRegistry` rewrites entire `jobs.json` per update (O(n)). `webapi` job events grow unbounded and are returned in full on every poll. Thread-per-connection stdlib server. `history()` scans+sorts the full state dir per request (no caching).

**Tech debt.** Two divergent service implementations with duplicated job/cancel/idempotency logic. Manual URL path parsing (no router). Stringly-typed `replay` mode + lazy per-branch imports. Contracts documented only in docstrings (no enforcing schema/test). Duplicated manifest-mode filtering. Four independent version notions (`AGENT_VERSION`/`PIPELINE_VERSION`/`__version__`/`/v1`).

**Missing for R1.** CLI commands entirely absent: `compute`, `graph`, `verify`, `audit`, `certificate`, `authorization`, `outcome`, `research benchmark` (only `ask`/`replay` of the §25 set exist). A typed-evidence certificate concept (issuance/validation command + API). An authorization/capability-grant command + resource-bound authorization model (webapi has no auth). Durable research jobs in the web API (port `JobRegistry`). A standardized typed §24 API response envelope (status, typed-evidence payload, verdict, resource-usage, certificate ref) unified across both surfaces. A `research benchmark` runner. An `outcome` command/endpoint. Resource-bound enforcement (pre-flight ceilings, typed resource-exhausted responses).

---

## 8. Web frontend

**Existing capabilities.** Answer-first conversational UI (`App.tsx`: Sidebar history + MetaBar + scrolling thread + Composer; `ConversationalResult` leads with `direct_answer`, then market assessment / analysis / scenarios / inferences / findings / sources / limitations / diagnostics — matching spec §11 ordering). Async lifecycle (POST `/api/research`, 700ms polling, live Progress, Cancel). Inline citations (`Cite` superscripts, `citeIndex` map → evidence inspector). Evidence inspector (slide-over: provider/source_type/url/dates/period/freshness/excerpt/SHA-256 with honest "hash proves artifact unchanged, not source correct" note/related claims). Epistemic/verification/stance badges. Market assessment block. Technical diagnostics drawer. Conversation threading. Run history + reload. Legacy fallback renderer. Full typed API contract in `types.ts`. Agent-config awareness (disables input when key unset).

**Reusable as-is.** Entire thread/composer/sidebar shell (answer-first + history + threading + polling) for §24.3. `api.ts` client + `pollResearch`. `Cite` + `citeIndex` inline-citation primitive. `EvidenceInspector` slide-over (template for graph/certificate inspectors). `ui.tsx` badges/formatters. Tailwind v4 design tokens + dark theme. `types.ts` typed payloads (extend for certificates/graph nodes).

**Incomplete.** All statement text rendered as plain React nodes — **no Markdown parsing** (raw markdown chars show). No deep-linking/URL routing (no router). No SSE/WebSocket streaming (700ms polling; events are untyped strings). **No test files anywhere** (no vitest/jest). Dual legacy/conversational rendering paths duplicate markup. "Related claims" may miss claims attached only via `supporting_facts`.

**Weaknesses.** The UI **trusts the server payload entirely** — `epistemic_class`, `verification.status`, `computed_value`, `content_hash` displayed verbatim with no client-side re-check or hash recomputation ("independently recomputed: {value}" is a server-asserted string). No certificate/proof object in the type model or UI (the core R1 artifact has zero frontend). Freshness shown only as a server string (no client staleness computation). `fmtTime`/`fmtDate` in viewer-local TZ with no label (ET-sensitive). No client routing/state persistence; no error boundary. Coarse error surfacing (swallowed meta/history failures).

**Temporal / verification gaps.** No client display/enforcement of per-claim resource budgets (only aggregate cost in MetaBar). `data_as_of` shown but never compared to now (a day-old answer looks live). No rendering of `verification tolerance`/`verifier_version`/`verified_at` per claim (present in the type but dropped). No certificate validity-window/expiry concept. `freshness_status` is free-form (no enum/threshold).

**Security.** No client-side sanitization (DOMPurify absent) — safe only because all content is plain-text React (auto-escaped); the moment R1 adds Markdown/HTML rendering this is an XSS surface. External links use `rel=noreferrer` but `source_url` is attacker-influenced and not scheme-validated (`javascript:`/`data:` injectable into href). No client auth. No CSP meta tag.

**Performance.** 700ms fixed polling (no backoff). No virtualization (long threads re-render all cards per tick). `citeIndex` rebuilt per render (not memoized). No code-splitting (will bloat once charts/graph libs added).

**Tech debt.** Dual rendering paths duplicate markup. Zero tests / no test tooling. Swallowed promise rejections. Synthetic error jobs mix fake ids with real. Long repeated inline Tailwind strings. Untyped `diagnostics` record. No eslint/prettier config.

**Missing for R1.** Markdown renderer (§24.3) — entirely absent. Table rendering / GFM. Charting library + chart component (time-series/price cannot be visualized). Graph inspector (evidence→claim→answer DAG). **Certificate inspector** (the central R1 deliverable has no frontend — no type, no panel for verifier/budget/proof/per-rule pass-fail). HTML sanitization (required once Markdown is added). Deep-linking/routing.

---

## 9. Engineering traceability vertical

**Existing capabilities.** Typed discriminated evidence relationships (edges): `CandidateRelationship` with `RelationshipType {CONNECTS, ALLOCATED_TO, SUPERSEDES}` + discriminated `RelationshipAttributes` union. Edge endpoints referenced by element `identity_key` (anchors ≠ identity). Every edge/node carries `evidence_ids` (min_length=1). Full lineage chain artifact→fact→evidence→candidate→verified model→export, each content-addressed. Independent verifier that re-derives every node/edge from cited evidence and rejects drift (`CANDIDATE_EVIDENCE_MISMATCH`). Edge/graph integrity checks (dangling/rejected endpoint, two-pass node-then-edge). Temporal knowability model (`known_at` = max(source availability, record constraint); as_of floor; `EVIDENCE_AFTER_AS_OF`). Configuration/version traceability (`SUPERSEDES` + `bridging_ecn_ids`, unique-path verification, `REVISION_CONFLICT`/`CONFIGURATION_AMBIGUITY`). First-class quarantine (`RejectedCandidate`). Anchor rendering to human-citable locations. Export-completeness guard + `evidence_index`. Traceability metrics (coverage/allocation/precision/recall). Deterministic replay with three-way comparison + anchor-drift detection. Run manifest separating analysis vs evaluation source hashes. Handling-marking propagation with `HANDLING_MISMATCH` check.

**Reusable as-is.** Discriminated typed-edge schema as the R1 §9 edge template (`{type, from_ref, to_ref, typed attributes, evidence_ids, handling, status}`). Endpoint-integrity verifier (dangling/rejected, two-pass). Evidence-citation discipline (re-derive from citations, reject drift). `anchors_for()` citation-chain resolver (click-through traceability). `known_at`/as_of gate. Export-completeness guard + `evidence_index`. `make_id` + `canonical_hash` + three-way replay. `RejectedCandidate` quarantine. Separation of schema capability vs execution policy.

**Incomplete.** Edge vocabulary is closed to 3 domain types (no generic edge, weight/confidence, or n-ary edges). No graph-level structure/queries (flat tuples; no adjacency/path/reachability; cycle detection only per-edge). Edges only intra-model (v2 "supports no external references"). Single global `as_of_date` (no per-edge validity interval/bitemporal beyond ECN approved_date). **No decision/action/outcome entities at all.** Metrics are coverage/precision/recall only (no topology metrics). Replay has no incremental/partial re-verification.

**Weaknesses.** Identity collision surface (`make_id` 48-bit; `DUPLICATE_IDENTITY` only catches same identity_key with conflicting name/revision, not hash collisions across distinct content). `elements_by_key` last-writer-wins if a component and requirement share an identity_key. No check that an edge endpoint was derived from the same evidence the edge cites. Builder trusts manifest/source order (determinism depends on stable sort keys assuming unique ids). Unsigned run manifest/export (self-certifying only). SUPERSEDES/ALLOCATED_TO to a pruned-duplicate node relies on name/revision-conflict detection rather than explicit edge ambiguity.

**Temporal / verification gaps.** Single global as_of cut-off (no per-edge/per-node validity window). `known_at` advances only for `RevisionChangeFact.approved_date` (other facts inherit source.known_at verbatim — no record-level effective date). No cross-edge causality/ordering (an allocation predating its component is not flagged). `checked_at` wall-clock excluded (correct for determinism, but no trusted verification timestamp). Replay uses a fixed `_REPLAY_CHECKED_AT`. No detection of retroactive source edits that keep content but change effective dates (except via content_hash drift, which changes identity entirely).

**Security.** XXE/entity-expansion hardening (`reject_doctype` before any XML parser). JSON float rejection in manifest loader. CSV adapter forbids quoting/embedded separators. Builder (propose) documented as a pure function (reasoner sandbox). Handling markings are propagation-only metadata with **no enforcement** (must NOT be treated as access control). Unsigned integrity (repudiable by anyone who can rewrite the whole run dir consistently). v2 execution policy refuses non-synthetic/non-PUBLIC data (R1 must consciously relax for real data).

**Performance.** `builder.propose` does repeated linear scans per component (O(components × numerics/descriptions)). `_interface_evidence_for` full scan per connection. `_verify_configuration` O(connections × endpoints × changes). `anchors_for` list-membership test (O(n²) on large citation sets). `_registry()` rebuilt per call. Whole-model in-memory recompute on replay (no incremental).

**Tech debt.** Pervasive `isinstance` narrowing with `# type: ignore[union-attr]` on the `FactPayload` union. Local import to avoid a cycle (layering coupling). Hand-maintained version constants with no bump-on-change enforcement. Non-authoritative `model-report.txt` excluded from hashing (report/export divergence unchecked). Enums + discriminated unions kept in lockstep manually across four modules. `elements_by_key` COMPONENT-then-REQUIREMENT update ordering is an undocumented precedence hazard.

**Missing for R1.** §9 generic graph-edge model (extensible relation kinds, optional weight/confidence, graph indices). §9 graph traversal/query layer (adjacency, path-finding, reachability, cycle/orphan detection). §19 decision entities (inputs, authorization context) — STRIX-009 ❌. §19 outcome entities + decision→outcome edges — STRIX-010/011 ❌. §19 closed-loop verification (outcome matches authorizing decision; retry/partial-failure outcome handling). Cross-run/cross-subsystem edges. Per-edge temporal validity intervals + causality/ordering. Signed/attestable provenance on edges.

---

## 10. 0B requirements baseline, docs & eval infra

**Existing capabilities.** Formal requirements baseline STRIX-001..015 as machine-readable YAML (per-req id/version/title/gap/rationale/preconditions/required_behavior/failure_behavior/acceptance_criteria/impl_references/verification_methods/status; status vocabulary implemented|partial|untested|missing|proposed; schema_version 0b.1). Human-readable traceability matrix (2 implemented / 7 partial / 6 missing; change-control policy; YAML declared source of truth). Authoritative gap definitions GAP-001/002/003. Engineering audit of 10 components. Gap-coverage matrix (component × gap; M1→M2→M3 sequencing). Remediation report (pre 828 → post 866 tests, 0 failed; deficiencies closed or preserved as xfail(strict)/skip; GO recommendation). Comparative-experiment design (falsification-first H1/H2/H3, 4 arms A/B/C/D, null/variables/falsification/ground-truth/controls/decision rule — **design only, zero results**). Three milestone specs (M1 evidence interoperability/GAP-003, M2 execution assurance/GAP-001, M3 outcome certification/GAP-002). v0.2.0 release docs incl. a manual research benchmark. mkdocs site. Domain-partitioned test layout + ground-truth-isolation fixtures + captured full-test baselines. Preserved-negative-result discipline (xfail(strict)/reasoned-skip cross-referenced to STRIX-NNN).

**Reusable as-is.** `requirements-baseline.yaml` schema + status vocabulary (extend with STRIX-016+). Traceability/gap-matrix markdown formats. Comparative-experiment-design structure as the R1 experiment template. Milestone-spec reuse-map pattern (ESTABLISHED FACTS vs DESIGN PROPOSAL). Ground-truth-isolation discipline. Test layout conventions (per-domain dirs, `FixedClock`, xfail(strict)/reasoned-skip). mkdocs nav wiring. `research_runs/*_fulltest.txt` baseline-capture convention.

**Incomplete.** §29 benchmark/eval infrastructure exists only as a **design** (no harness, arm runners, scorer, or seeded generators in src/ or tests/). The v0.2.0 benchmark is a hand-transcribed one-off, not an automated harness. 7/15 requirements partial, 6/15 missing. Coverage numbers unavailable (pytest-cov not installed). FALCON "docs" = a single untracked PDF. `research/` directory empty; `jobs.json` is `{}`. Reconciliation leaves view-backed-metric + content-hash integrity gaps open.

**Weaknesses.** Doc duplication: `docs/` and `architecture/` are byte-identical tracked trees (mkdocs uses `architecture/`; the declared single source of truth physically exists twice — drift hazard). Baseline audit_commit of record is `3dc70ea` (parent) while R1 pins `849018d` — impl_references were verified against the parent, not the R1 baseline (needs re-pin/re-verify). impl_references cite file:symbol but **not** line numbers; no linter verifies cited symbols/tests still exist. Status fields are point-in-time manual assertions with no CI gate. Verification is independent-by-construction but unsigned. No executable linkage between experiment design and codebase.

**Temporal / verification gaps.** No automated re-verification that baseline status/impl_references/verification_methods still hold against current source (manual, milestone-boundary only). audit_commit predates the R1 baseline (source changes between them unaudited). Coverage not measured over time (a test that stops asserting is undetected). Experiment reproducibility depends on seed/manifest capture no harness yet records. Evidence-freshness is a single hard-coded 45-day threshold with no execution-time gate.

**Security.** Manifests are unsigned SHA-256 hashes with no signature/trust-root/timestamp authority (integrity rests on recomputation/replay). Experiment design treats LLM output as hostile (no eval / bounded sizes / schema-validated / float rejection) — good inherited posture. `docs/FALCON/faq-dpa26bz04-dv-016.pdf` is an untracked unvetted binary (should not be mkdocs-published without review). Baseline correctly records LLM as proposer-only and verification path imports no LLM.

**Performance.** Full suite 862 passed / 2 skipped / 2 xfailed in ~25s at 866 tests (fast enough to gate R1 in CI). Reconciliation tests build a local DuckDB warehouse via dbt (heavyweight per-test setup the eval harness will inherit). No coverage instrumentation. Doc mirror doubles the built/tracked payload.

**Tech debt.** Two byte-identical doc trees (every edit must be made twice). Triple-duplicated evidence vocabularies (Claim/Evidence/VerificationStatus/FailureCode across `strix.models`, `agent.models`, `engineering.models`; two FORECAST enums) — audit §3 smell + M1 unification target. Four fragmented reconcilers with no shared interface. pytest-cov missing from dev extras. Untracked artifacts (FALCON PDF, empty `research/`, `assets/`). Committed `__pycache__` under tests/. The two-commit audit split (`3dc70ea` vs `849018d`).

**Missing for R1.** §29 benchmark/eval infrastructure as **code** (4-arm harness, arm-blind scorer, seeded synthetic generators, bootstrap-CI statistics, real-fixture adjudication). R1-specific requirement entries STRIX-016+ (Resource-Bounded Typed Evidence Verification targets) under the existing schema. Mapping of R1 targets into the gap/traceability matrices (R1 currently untraced). An automated baseline↔source consistency check (traceability linter). Re-pin of audit_commit to `849018d` with re-verification. Integrated FALCON documentation + non-empty `research/` workspace. pytest-cov in dev extras.

---

## Consolidated R1-coverage matrix

| R1 area | Status | Owning subsystem | Note |
|---|---|---|---|
| **§6** Descriptive statistics (mean/std/quantiles/etc.) | absent | Analytics | No descriptive-statistics functions exist anywhere. |
| **§6** Time-series statistics | partial | Analytics (+ agent/calculations) | Only a hard-coded two-period pp difference in `analytics/`; `agent/calculations.py` adds returns/volatility/drawdown/moving-average as reusable raw material. |
| **§6** Multivariate statistics (correlation/regression/etc.) | partial | Analytics (+ agent/calculations) | None in `analytics/`; `agent/calculations.py` has deterministic `correlation`/`relative_performance`; no covariance matrix/regression/PCA. |
| **§6** Inference statistics (tests/CIs/p-values) | absent | Analytics | No hypothesis tests, confidence intervals, p-values, or bootstrap. |
| **§7** Numerical contracts (exact Decimal, float-forbidden, rounding/overflow) | present | Analytics / Models | `DecimalValue` float-rejection, `localcontext` prec=34 ROUND_HALF_EVEN, explicit quanta, `InvalidOperation→CalculationError`; not yet applied to sqrt/log/aggregate ops. |
| **§7** Typed `CalculationResult` | present | Models / Analytics | Frozen closed-schema model with typed enums + role-ordered lineage; scalar-only (no array/CI/p-value/sample-size shape). |
| **§7** Typed result for non-scalar/statistical outputs | absent | Analytics | No typed variant carrying arrays/matrices/CIs/p-values/standard-errors. |
| **§9** SourceArtifact | present | Models | `models.py` — raw-bytes content_hash, content-derived id+version, byte_size, known_at. |
| **§9** SourceObservation | absent | Models | No observation node; `SourceFact` collapses observation and validated fact. |
| **§9** SourceFact | present | Models | Validated observation with concept/value/unit/period + source lineage + validation_status. |
| **§9** CalculationResult (node) | present | Models | Deterministic versioned calc with role-ordered input ids; lacks its own known_at. |
| **§9** Evidence | present | Models | Citable typed result carrying full source-fact lineage; display_value hash-excluded. |
| **§9** CandidateClaim | partial | Models | No distinct type; `Claim` + `ClaimStatus.PROPOSED` serves the role; agent `AgentClaim` is non-canonical. |
| **§9** VerificationResult (node) | present | Models | PASSED/FAILED verdict, verified/rejected ids, typed `VerificationFailure` (17 codes), verifier_version. |
| **§9** ComputationCertificate | absent | Models | No certificate type; no resource-bound/cost fields to certify bounded computation. |
| **§9** ClaimCertificate | absent | Models | No signed certificate binding a verified claim to evidence+verdict. |
| **§9** AuthorizationCertificate | absent | Models | No principals/capabilities/keys/signatures; entire authenticity layer must be built. |
| **§9** OutcomeCertificate | absent | Models / Engineering | No outcome/attestation node; `RunManifest`/`ResearchReport` are unsigned and not certificate-typed. |
| **§9** Content-derived identifiers | present | Models | `make_id → PREFIX-sha256[:12]`; 48-bit truncation + global length the only caveats. |
| **§9** Canonical serialization | present | Models | Sorted-key compact UTF-8, Decimal-as-exact-string, UTC ISO, float/bytes/naive rejected. |
| **§9** Typed graph edges (schema/endpoints/typed attributes) | present | Engineering | `CandidateRelationship` + discriminated `RelationshipAttributes` union — reusable edge template. |
| **§9** Graph edges — evidence-cited / provenance-bound | present | Engineering | Every edge cites ≥1 evidence id; verifier re-derives edge content and rejects drift. |
| **§9** Graph edges — endpoint/referential integrity | present | Engineering | Two-pass node-then-edge flags dangling/rejected endpoints. |
| **§9** Graph edges — generic/extensible kinds, weights, confidence | partial | Engineering | Closed 3-type domain enum; no generic relation kind, weight, or confidence. |
| **§9** Graph traversal/query (paths, reachability, cycles, orphans) | absent | Engineering | Flat tuples; no adjacency index or traversal layer. |
| **§9** Cross-run / external / n-ary edges | absent | Engineering | v2 supports no external references; edges strictly intra-model and binary. |
| **§10** Integrity predicate | partial | Verification | Replay checks stored artifacts + raw re-hash against the manifest, but the manifest is unsigned (self-referential). |
| **§10** Type-Temporal predicate | partial | Verification | Typed frozen/closed models give the Type half; temporal is a single date-granular as-of gate with no lineage monotonicity + a non-deterministic agent-replay `now`. |
| **§10** Provenance predicate | present | Verification | `_verify_evidence_lineage` fully walks Evidence→Calc→Fact→Artifact with per-edge codes; reusable as-is. |
| **§10** Derivation predicate | partial | Verification | Pipeline verifier only checks `value==calc.value`; independent recomputation at verify time exists only in the agent path. |
| **§10** Support predicate | present | Verification | Cited-evidence gates + assertion-must-be-cited + value/unit match + required-assertions; agent side mirrors via series→cited-evidence tracing. |
| **§11** Compositional invariants | partial | Verification | Direction-sign / prose==rendering + agent classification-integrity exist, but only for hardcoded schemas; no general evidence-graph invariant engine. |
| **§12** (not evidenced in audited inventories) | absent | — | No subsystem inventory entry maps to R1 §12; treat as greenfield pending the R1 spec. |
| **§13** Certificate validation | partial | Verification / Models | Hash-manifest + agent response re-hash/citation/classification checks exist, but there is no cryptographic signature/verification — only unsigned self-consistency. |
| **§13** Content digests | present | Models | `canonical_hash` (SHA-256 of canonical form) + `sha256_hex` (raw bytes); integrity only, no signing. |
| **§14** Research objective decomposition | partial | Agent | Deterministic single-shot classification (intent/entities/horizon/objectives/evidence_requirements); no decomposition into dependent sub-goals, per-sub-goal tracking, or recombination. |
| **§15** Resource-constrained acquisition loop | partial | Agent | `_run_loop` is a bounded, budget-checked tool-calling loop (present/reusable), but stopping is only budget-exhaustion/model-finished. |
| **§15** Acquisition strategies | absent | Agent / Sources | No candidate-action generation, value-of-information prioritization, coverage-gap driving, per-sub-goal sub-budgets, or principled stopping rules. |
| **§16** Resource accounting / budgets | present | Agent | `BudgetTracker` enforces calls/tokens/time/USD with versioned pricing, fail-soft, injectable clock, immutable snapshots; missing per-sub-goal attribution + real tool costs. |
| **§16** Durable resource-bound accounting | absent | Lakehouse | No persisted token/cost/time budget accounting; `mart_research_quality` explicitly defers cost/replay metrics. |
| **§17** (not evidenced in audited inventories) | absent | — | No subsystem inventory entry maps to R1 §17; treat as greenfield pending the R1 spec. |
| **§18** (not evidenced in audited inventories) | absent | — | No subsystem inventory entry maps to R1 §18; treat as greenfield pending the R1 spec. |
| **§19** GAP-002 durable decision ledger | partial | Lakehouse | `run_store` persists per-run artifacts + hash-based manifest + final_status replayably, but it is NOT an append-only ordered, chained, signed, cross-run decision ledger. |
| **§19** Decision entities & authorization context | absent | Engineering | No decision/authorization model (STRIX-009 ❌). |
| **§19** Outcome entities & decision→outcome edges | absent | Engineering | No execution-outcome records and no edges linking decisions to realized outcomes (STRIX-010/011 ❌). |
| **§19** Independent outcome verification / closed loop | absent | Engineering | The independent-verifier pattern is reusable, but there is no outcome-matches-decision check or retry/partial-failure handling. |
| **§19** Persisted typed evidence-verification results | absent | Lakehouse | `fact_research_claims`/`fact_verification_results` are schema-only placeholders (DE-7 deferred). |
| **§20** (not evidenced in audited inventories) | absent | — | No subsystem inventory entry maps to R1 §20; treat as greenfield pending the R1 spec. |
| **§22** EDGAR connector | present | Sources | Pure point-in-time parser + lakehouse extractor + agent connector; Bronze preserves full snapshot without as-of cut. |
| **§22** Alpaca connector | present | Sources | Agent connector + paginated lakehouse extractor; `adjustment=all` means bars are NOT point-in-time. |
| **§22** FRED connector | present | Sources | Lakehouse extractor, key-gated, API key redacted from provenance. |
| **§22** BLS connector | present | Sources | Lakehouse extractor on public v1; `record_count` heuristic parse. |
| **§22** Treasury connector | present | Sources | Lakehouse yield-curve XML extractor; `record_count` via fragile byte-count. |
| **§22** USAspending connector | absent | Sources | No code, no `DataSource` enum member. |
| **§22** SAM connector | absent | Sources | No code or reference anywhere in src. |
| **§22** USGS connector | absent | Sources | No code or reference anywhere in src. |
| **§22** Bronze artifact preservation | present | Sources / Lakehouse | Immutable content-addressed raw storage + append-only provenance + read-back hash verification; manifests unsigned. |
| **§22** Connector contracts | partial | Sources | Three typed protocols exist but are not unified; resource bounds attached only to the corpus PDF path, not lakehouse ingestion. |
| **§23** Bronze layer (immutable raw/provenance) | present | Lakehouse | Content-addressed immutable store + append-only `ProvenanceManifest` + read-back verification. |
| **§23** Silver layer (normalized, quality-gated, lineage-bearing) | present | Lakehouse | Full-recompute pipeline: quality gates, dedup/quarantine, reconciliation-blocks-publish, atomic decimal128 Parquet. |
| **§23** Analytical layer (marts/warehouse) | present | Lakehouse | DuckDB star schema + dbt staging/intermediate/marts + offline Snowflake adapter; transactional idempotent loads. |
| **§23** Assurance layer (durable, queryable assurance records) | absent | Lakehouse | No 4th medallion; reconcile/verify/cross-validation produce ephemeral unpersisted verdicts. |
| **§23** Lineage (claim → warehouse → silver → bronze) | present | Lakehouse | Mandatory lineage columns on every row; `lineage()` resolves and re-verifies the Bronze hash. |
| **§23** Decimal-safe storage | present | Lakehouse / Models | `DecimalValue` float-rejection, decimal128 Parquet, DECIMAL/NUMBER types, exact scale coercion. |
| **§23** Persistence (crash-safe, atomic, idempotent) | present | Lakehouse | Atomic temp+fsync+rename everywhere; single-rename commit; transactional/idempotent loads. |
| **§23** Bitemporal / point-in-time decision verification | partial | Lakehouse | FRED vintages retained; other sources latest-wins; no as-of warehouse query or retained load history. |
| **§23** Tamper-evidence / signing of records | absent | Lakehouse | Manifests hash-verified for corruption but UNSIGNED; no cryptographic attestation or hash-chaining. |
| **§24** API response contract | partial | CLI / WebAPI | Two ad-hoc JSON surfaces with canonical `to_jsonable` serialization but no unified, versioned, typed-evidence response envelope. |
| **§24.3** Answer-first web interface | present | Frontend | Leads with `direct_answer` in a polished ChatGPT-style thread with history + threading. |
| **§24.3** Markdown rendering | absent | Frontend | All text rendered as plain React nodes; no markdown parser/dependency. |
| **§24.3** Tables | absent | Frontend | No table component and no GFM table support. |
| **§24.3** Charts | absent | Frontend | No charting library and no chart component; time-series cannot be visualized. |
| **§24.3** Inline citations | present | Frontend | `Cite` + `citeIndex` produce clickable `[n]` superscripts that open the evidence inspector. |
| **§24.3** Evidence inspector | present | Frontend | Slide-over shows provenance, excerpt, SHA-256 hash, related claims; reusable as-is. |
| **§24.3** Graph inspector | absent | Frontend | No evidence/claim dependency-graph type or visualization component. |
| **§24.3** Certificate inspector | absent | Frontend | No certificate type and no UI panel; the resource-bounded typed-evidence certificate has zero frontend. |
| **§25** CLI: ask | present | CLI | `ask` → agent orchestrator; prints cited verified answer + usage. No `--json` mode. |
| **§25** CLI: compute | absent | CLI | No `compute` subcommand. |
| **§25** CLI: graph | absent | CLI | No `graph` subcommand; nearest is warehouse/transform lineage, not an evidence graph. |
| **§25** CLI: verify | absent | CLI | No standalone `verify`; verification runs only implicitly inside `ask`/`replay`. |
| **§25** CLI: audit | absent | CLI | No `audit` command. |
| **§25** CLI: certificate | absent | CLI | No certificate concept or command. |
| **§25** CLI: authorization | absent | CLI | No `authorization` command; only coarse token/tenant/role auth inside `service.py`. |
| **§25** CLI: outcome | absent | CLI | No `outcome` command, though `ResearchOutcome` exists and could back one. |
| **§25** CLI: replay | present | CLI | Mode-dispatched replay (v1/agent_research/engineering) verifying deterministic hashes; strong reuse base. |
| **§25** CLI: research benchmark | absent | CLI / Eval | No benchmark command; existing "benchmark" tokens are unrelated SPY market benchmarks. |

---

## Reusable vs. must-build summary

### Reuse as-is (proven, dependency-light, deterministic)
- **Canonical core** (`canonical.py`): `make_id`, `canonical_hash`, `canonical_bytes`, `to_jsonable`, `encode_decimal`, `sha256_hex` — the content-addressing + Decimal-exact serialization substrate for every R1 node and certificate.
- **Typed model base** (`StrixModel` frozen + `extra='forbid'`, `DecimalValue`) — immutability + schema-closure + float rejection for free.
- **Independent-verification kernels**: `_verify_evidence_lineage` (Provenance), anti-smuggling/support gates (Support), agent recompute-within-tolerance (Derivation).
- **Replay**: dual integrity+reproducibility stage pattern (`replay.py`) for the R1 Integrity+Derivation admission check.
- **Persistence**: `run_store` atomic single-rename commit; Bronze immutable content-addressed store + `ProvenanceManifest`; `ObjectStore` Protocol; medallion lineage columns + `lineage()` resolver.
- **Budgets**: `BudgetTracker` + `BudgetSnapshot` (calls/tokens/time/USD, versioned pricing, fail-soft) as the §16 substrate.
- **Boundaries**: `ToolRegistry`/`ToolSpec`; `ProposalProvider`/`propose()`/`finalize()` capability-restricted seam; `validate_answer` fail-closed template.
- **Connectors**: EDGAR point-in-time primitives; `SourceExtractor`/`BronzeIngestor`/`IngestionRunner`/`HttpFetcher`; `network_safety.py`; `AcquisitionPolicy`.
- **Edges**: engineering discriminated typed-edge schema + endpoint-integrity verifier + `anchors_for` resolver + three-way replay.
- **Front-end shell**: answer-first thread, `Cite`/`citeIndex`, `EvidenceInspector` slide-over.
- **Baseline infra**: `requirements-baseline.yaml` schema, traceability/gap-matrix formats, comparative-experiment-design template, test layout + ground-truth isolation.

### Extend (exists but domain-locked or incomplete)
- Vocabularies/enums → generic/extensible registries with a canonical schema-version tag.
- `CalculationResult` → typed non-scalar variant (arrays/matrices/CIs/p-values/sample-size); `agent/calculations.py` time-series/multivariate functions promoted into a real `analytics/` statistics library behind a calculator registry.
- Pipeline Derivation predicate → independent recomputation at verify time (adopt the agent pattern); unify the two verification stacks behind one predicate interface.
- `BudgetTracker` → per-sub-goal/per-strategy sub-budget partitioning + real per-tool cost model.
- `_run_loop` → explicit §15 acquisition-strategy layer (candidate generation, value-of-information, coverage-gap driving, stopping rules); `question.py` → real §14 decomposer.
- Engineering edges → generic edge kinds + weights/confidence + graph traversal/query + cross-run/n-ary edges.
- Lakehouse → 4th **assurance** medallion + durable **decision ledger** (ordering/hash-chaining/signing); bitemporal/as-of persistence.
- Lakehouse `HttpFetcher` → wire in `network_safety.py` SSRF guard on the live ingestion path; Bronze → point-in-time/as-reported preservation.
- CLI/web API → unified typed §24 response envelope; port `JobRegistry` durability into FastAPI; add the missing §25 commands.
- Front-end → Markdown/tables/charts (with DOMPurify) + graph & certificate inspectors + client-side verification cues.

### Net-new for R1
- **Resource-bounded verification** end to end (budget/cost/fuel/timeout + per-predicate accounting + bounded-work guarantee) — the central R1 primitive, absent everywhere.
- **Certificate layer**: Computation/Claim/Authorization/Outcome certificate node types + **cryptographic signing/verification** (keys, trust anchor, principal-capability model).
- **Typed admission-predicate layer** (§10) + general compositional-invariant engine (§11).
- **SourceObservation** node + first-class `CandidateClaim`; model-level temporal invariants + bitemporal fields.
- **Decision & outcome entities** + decision→outcome edges + closed-loop outcome verification (§19).
- **§22 connectors**: USAspending, SAM.gov, USGS (+ `DataSource` enum members).
- **§29 eval infrastructure as code**: 4-arm harness, arm-blind scorer, seeded generators, bootstrap-CI statistics.
- **STRIX-016+ requirement entries** for Resource-Bounded Typed Evidence Verification + an automated baseline↔source traceability linter.
- Unification of the three fragmented evidence vocabularies (GAP-003).

---

## Known 0B carry-over weaknesses

These were documented or preserved at the 0B baseline and remain open at `849018d`. Each is mapped to the R1 section that formalizes its remediation.

| 0B carry-over weakness | Evidence at baseline | Remediated by R1 section |
|---|---|---|
| **Untested reconciliation-discrepancy path** | 0B closed some reconciliation-discrepancy coverage but preserved view-backed-metric + content-hash integrity gaps as documented xfail(strict)/reasoned-skip; lakehouse reconciliation/cross-validation verdicts are produced but **never persisted or exercised as a durable gate**. | **§23 Assurance layer** — a durable, queryable 4th medallion that persists reconciliation/integrity/cross-validation verdicts as typed rows, making the discrepancy path a first-class, testable, retained check (with §19 decision-ledger recording the resulting verdict). |
| **Missing event ↔ outcome correlation** | No decision/action entities and no outcome entities or decision→outcome edges anywhere (engineering STRIX-009/010/011 ❌); `fact_research_claims`/`fact_verification_results` are schema-only placeholders. | **§19 decision-to-outcome** — decision + outcome entities, decision→outcome edges, and closed-loop independent outcome verification correlating each event to its realized outcome. |
| **Unsigned manifests** | `RunManifest`, Bronze `ProvenanceManifest`, Silver `PublicationManifest`, and engineering run manifests are hash-verified for corruption but carry no signature/MAC/trust anchor (integrity without authenticity). | **§13 certificate validation** — cryptographic signing/verification (keys, trust anchor) turning the unsigned hash manifest into an authenticated, tamper-evident certificate; pairs with the §9 AuthorizationCertificate principal-capability model. |
| **Doc drift (`llm-boundary.md` / `provenance.md`)** | 0B docs duplicated across byte-identical `docs/` and `architecture/` trees with no linter tying prose to source; the LLM-trust-boundary and provenance docs can diverge from the two divergent trust-boundary implementations (agent prompt-trusted vs corpus sandboxed) and the three fragmented evidence vocabularies. | `llm-boundary.md` → **§21 hybrid-intelligence trust boundary** (one unified, structurally-enforced boundary across live-tool and typed-evidence paths, re-establishing the doc as single truth). `provenance.md` → **§13 / §9 provenance & certificate layer** (signed, typed provenance on nodes/edges), backed by an automated baseline↔source traceability linter so the docs cannot silently drift. |

---

## Baseline test suite

Measured on branch `research/formal-evidence-verification` (at STRIX baseline `849018d`) with `python -m pytest -q` in `.venv` (Python 3.11.8, pytest 9.1.1):

**866 tests collected → 862 passed, 2 skipped, 2 xfailed, 0 failed, 0 errors. Exit code 0.**

Counts are derived from the per-test progress stream (862 `.` + 2 `s` + 2 `x` = 866); the condensed summary line was lost to carriage-return overwrite in the redirected log, but the outcome characters are unambiguous and were re-confirmed by character count.

This is the **regression gate** for all R1 work: every change must preserve **≥ 862 passed with 0 new failures/errors**. The 2 xfailed and 2 skipped are pre-existing and expected (see `tests/` — the xfails mark documented not-yet-implemented behaviours; the skips are optional-dependency guards).

# Adding reasoners

A **reasoner** turns a curated evidence bundle into structured, citable
claims. It is the narrow seam where judgment enters the pipeline — and it is
deliberately kept downstream of every authoritative number and upstream of the
verifier, so nothing it produces is trusted until verification passes.

!!! warning "No LLM is called anywhere in this version"
    The only reasoner today is `DeterministicDemoReasoner`, which is fixed,
    auditable Python — **not** an LLM. No LLM API is invoked anywhere in the
    codebase. The LLM adapter described at the end of this page is future work
    (see [Roadmap](roadmap.md)); it does not exist yet.

## The protocol

`reasoning/base.py` defines the entire contract:

```python
class Reasoner(Protocol):
    def analyze(self, spec: ResearchSpec, evidence: list[Evidence]) -> list[Claim]:
        ...
```

A reasoner receives **only** `(spec, evidence)`. It returns a list of `Claim`s.
That signature is the seam: `pipeline.compute` calls
`reasoner.analyze(spec, list(evidence))` and passes the result straight into
`verify`.

## Constraints every reasoner must honor

These are stated in `reasoning/base.py` and enforced by the surrounding
pipeline and tests:

- **Pure function of `(spec, evidence)`.** No files, environment variables,
  network, credentials, or terminal state. Its only inputs are the two
  arguments.
- **No new authoritative numbers.** Every number a claim asserts must be
  **copied verbatim** from a cited evidence record. A reasoner may derive
  structure (like a direction label) but not new financial values.
- **Cite everything.** Every `NumericAssertion` names the `evidence_id` that
  must support it, and every asserted evidence ID must also appear in the
  claim's `evidence_ids`. The verifier rejects an assertion that cites
  evidence the claim does not also cite (`ASSERTION_EVIDENCE_NOT_CITED`), which
  is what stops a claim from smuggling evidence past the subject / as-of /
  verified-status gates.

### The isolation test pattern

`tests/test_cli.py::TestReasonerIsolation` shows how to prove a reasoner does
no I/O: it monkeypatches `builtins.open` and `builtins.input` to raise, then
calls `analyze` and asserts a claim still comes back. Any new reasoner should
be covered the same way — if it can produce its claims with files and stdin
blocked, it is honoring the seam.

## How `DeterministicDemoReasoner` builds its claim

`reasoning/deterministic_demo.py` is the reference implementation. Given the
spec's `(previous_period, current_period)`, it:

1. **Locates its evidence** with `_find`, which requires exactly one match for
   each of the previous margin, the current margin, and the change (metric
   `operating_margin_change_pp`, period `"{previous}..{current}"`). Ambiguity
   or absence raises `ReasonerError`.
2. **Derives structure, not values.** `direction = direction_from_change(
   change.value)` — the one derivation it performs, and one the verifier
   independently re-derives.
3. **Renders prose** with `render_statement(direction, previous.value,
   current.value)`. This is a pure function of verified structured values; the
   verifier re-renders it and rejects any drift (`STATEMENT_MISMATCH`).
4. **Copies numbers verbatim** into role-ordered `NumericAssertion`s (previous,
   current, change), each carrying the source metric, value, unit, and
   `evidence_id`.
5. **Derives the `CL` identity** with `make_id("CL", {...})` over the subject,
   claim type, direction, cited evidence IDs, and the ordered numeric
   assertions — so the claim ID is a content hash, stable across recomputes,
   exactly like the upstream `FACT`/`CALC`/`EV` IDs.

The resulting `Claim` is returned with `status = ClaimStatus.PROPOSED`. The
reasoner never marks its own work verified — only the verifier does that.

## Why the verifier makes the reasoner safe to extend

The reasoner is the least-trusted component by design, so a more sophisticated
reasoner cannot weaken any guarantee:

- **The verifier does not change.** It re-checks lineage, confirms every cited
  evidence belongs to the subject and was knowable by the as-of date and is
  itself verified, matches every assertion's value and unit against its
  evidence, requires the complete comparison set, re-derives the direction
  sign, and re-renders the prose.
- **Failed verification blocks publication.** If any claim fails, the run's
  report publishes **no** claims — not even a concurrently-valid one — and its
  summary reads "No verified finding." (`test_verification.py` pins this via a
  two-claim reasoner.)
- **A claim is only as strong as its evidence.** Because numbers must be copied
  from cited, verified evidence, a reasoner cannot introduce a value that has
  no lineage.

## How a future LLM adapter would slot in

A schema-constrained LLM reasoner would implement the **same** `Reasoner`
protocol and sit behind the **same** verifier. The design intent (documented
in `reasoning/base.py`) is that it changes nothing about trust:

- It receives only `(spec, evidence)` — no tools, no network of its own, no
  file access.
- Its output is treated as **untrusted**: it must emit the same structured
  `Claim` shape (cited evidence IDs and verbatim numeric assertions), and it
  is fed straight into the unchanged verifier.
- Any claim it produces that cites uncited evidence, asserts a value that does
  not match its evidence, gets the direction wrong, or whose prose does not
  re-render exactly is **rejected**, and a failed verification still publishes
  nothing.

In other words, the seam is deliberately narrow so that swapping deterministic
Python for a constrained model does not move the trust boundary: the model
proposes, and the deterministic verifier disposes. Until that adapter is
written, `DeterministicDemoReasoner` is the only reasoner, and no model is in
the loop.

## Checklist for a new reasoner

1. Implement `analyze(self, spec, evidence) -> list[Claim]` with no I/O.
2. Locate evidence by metric and period; fail loudly on ambiguity.
3. Copy every asserted number verbatim from a cited evidence record.
4. Cite every evidence ID you assert against (and only verified evidence will
   survive the verifier).
5. Derive the `claim_id` with `make_id("CL", …)`; return claims as `PROPOSED`.
6. Add an isolation test that blocks `open`/`input` and still gets a claim.
7. If the claim is a new *type*, add its verifier rules first — see
   [Adding calculations](adding-calculations.md#calculations-are-not-claims-the-verifier-boundary).

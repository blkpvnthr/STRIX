# Security & Threat Model

STRIX runs untrusted-shaped inputs (external JSON, a user-supplied ticker, a
user-supplied run id) through a deterministic pipeline and writes signed-by-hash
artifacts to local disk. This page enumerates the threats that shape the design
and the concrete, code-grounded mitigations for each. Every claim below maps to
source in `src/strix/` and a test in `tests/`.

## Threat model at a glance

| Threat | Mitigation | Where |
| --- | --- | --- |
| Malicious data triggers code execution | No `eval`/`exec`/`pickle`/`subprocess`; strict schema parse | package-wide; `sources/demo.py` |
| Float sneaks into a monetary value | `float` rejected at three layers | `canonical.py`, `models.py`, source parsers |
| Path traversal via run id | ASCII regex + resolved-path containment | `run_store.py` |
| Tampered manifest steers reads outside the run | Artifact-name validation | `run_store.py`, `replay.py` |
| Crash leaves a half-written or forged run | Atomic staging + single rename | `run_store.py` |
| Stack traces leak internals to users | Typed errors → `Error: …`, exit 1 | `cli.py`, `errors.py` |
| Reasoner reaches for files/network/terminal | Protocol passes only `(spec, evidence)` | `reasoning/base.py` |
| Unexpected or excessive network egress | Exactly two SEC GETs, fair-access UA, 30 s timeout | `sources/edgar.py` |
| Credential leakage | No credentials exist anywhere | package-wide |
| Source contents leak into logs | Source bytes are never logged | package-wide |

## No dynamic code execution

STRIX contains no `eval`, `exec`, `pickle`, `marshal`, `subprocess`,
`os.system`, or `__import__` calls. External data is parsed with the standard
`json` module into strictly-typed Pydantic models — never deserialized into
live objects. A malformed or hostile source document can, at worst, be
*rejected*; it cannot cause code to run.

## Strict fixture and source validation

The demo fixture is parsed under a closed schema. `_FixtureModel` sets
`extra="forbid"`, so unknown keys are rejected; numeric fields are constrained
by regex (`value: str = Field(pattern=r"^-?\d+(\.\d+)?$")`); and JSON floats are
refused outright — `parse_demo_fixture` passes `parse_float=_forbid_float`,
which raises `FixtureError`. The parser additionally enforces
`synthetic == true`, `source_type == synthetic_fixture`, exactly two periods,
and exactly one revenue and one operating-income fact per period. STRIX refuses
to run a "demo" document that does not declare itself synthetic.

EDGAR parsing is equally defensive: `parse_companyfacts` decodes with
`parse_float=Decimal` so decimals never pass through binary floating point,
rejects non-object payloads, and skips any unit entry that is missing fields, is
the wrong duration, is filed after the as-of date, or whose value is a `bool` or
non-numeric. A regression test seeds the EDGAR sample with a JSON float (EPS
`1.23`) and asserts every extracted `value` is a `Decimal` and never a `float`.

!!! note "Float is forbidden in depth"
    `float` is rejected in three independent places: `canonical.to_jsonable`
    (serialization), the `DecimalValue` validator in `models.py` (domain
    models), and each source parser (`parse_float` hooks). No single missed
    check can let a lossy binary float reach a hashed value.

## Run-ID and artifact-name validation

Both the run id (from `strix replay RUN-ID`) and any artifact file name are
attacker-controllable and are validated before they touch the filesystem.

`sanitize_run_id` requires a full match of `^RUN-\d{8}-\d{3}$` compiled with
`re.ASCII`. The `re.ASCII` flag is load-bearing: without it, `\d` matches
Unicode decimal digits, and lookalike run ids would parse. A parametrized test
rejects, among others, `../evil`, `RUN-20260808-001/../..`, `/etc/passwd`, a
trailing newline, and the Unicode-digit forms `RUN-٢٠٢٦٠٨٠٨-٠٠١` and
`RUN-２０２６０８０８-００１`. `RunStore.run_dir` then resolves the candidate path and
raises `InvalidRunIdError` unless its parent is exactly the resolved state
directory — defense in depth against traversal.

`sanitize_artifact_name` validates every file name read from a run
(`^[A-Za-z0-9][A-Za-z0-9._\-]{0,254}$`, and an explicit `".." in name` check),
so a **tampered manifest cannot steer reads outside the run directory**. Two
independent tests cover this: names like `../manifest.json`, `/etc/passwd`,
`raw/../../x`, and `a/b.json` are rejected before any filesystem access; and a
manifest whose `source_name` is edited to `/etc/hosts` fails `RunManifest`
model validation, so `replay_run` raises `ReplayError` ("unreadable manifest")
rather than reading an absolute path. The `source_name` field itself is
pattern-constrained (`^[A-Za-z0-9][A-Za-z0-9._\-]*$`) on both `SourceArtifact`
and `RunManifest`.

## Atomic persistence resists forgery-by-crash

The run store commits a run with a single `os.rename` of a hidden staging
directory, and a completed run can never be overwritten (a rename onto an
existing name is caught and a fresh id is chosen). A crash leaves only an
ignorable `.staging-*` directory, never a partial or forged `RUN-*`. Details are
in [Storage](storage.md#atomic-write-protocol). Integrity of a committed run is
independently checkable with `strix replay`, which recomputes every stage hash
from preserved inputs and compares both stored and recomputed values to the
manifest.

## No tracebacks in normal CLI use

All expected failures are typed subclasses of `StrixError` (`errors.py`). The
CLI's top-level handler surfaces only the message:

```python
except StrixError as exc:
    err.write(f"Error: {exc}\n")
    return 1
```

Users see, for example, `Error: invalid run ID '../../etc'; …` and an exit code
of 1 — never a Python stack trace, file path, or internal frame. Tests assert
that a traversal run id and an unknown run id each produce `Error:` on stderr,
exit 1, and no leaked internals. `KeyboardInterrupt` exits 130; a declined
prompt exits 0 with no run created.

## No credentials anywhere

STRIX has no API keys, tokens, passwords, or secrets — none in code, none in
config, none required at runtime. The SEC EDGAR endpoints are public and
keyless. The only human-readable identifier sent anywhere is the fair-access
`User-Agent` (below), which is a contact string, not a secret.

## Network egress is minimal and explicit

Network access exists in exactly one module, `sources/edgar.py`, and only inside
`EdgarConnector.fetch` (the DEMO ticker is fully offline). A real-ticker run
makes **two** HTTP GETs and no more:

1. `https://www.sec.gov/files/company_tickers.json` — ticker → CIK.
2. `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — the
   company's XBRL facts.

Both carry the SEC-required fair-access `User-Agent` and a 30-second timeout:

```python
USER_AGENT = "STRIX/0.1 research prototype (contact@quantumquant.trade)"
_TIMEOUT_SECONDS = 30

request = urllib.request.Request(url, headers={"User-Agent": user_agent})
with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
    return bytes(response.read())
```

HTTP errors and connection failures are converted to `SourceError` (an unknown
ticker yields `not found in the SEC EDGAR ticker map`, exit 1) — never a raw
traceback. Once fetched, the bytes are preserved in the run directory, so
**replay never touches the network**.

!!! note "Tests block sockets suite-wide"
    An autouse `no_network` fixture in `tests/conftest.py` monkeypatches
    `socket.socket` and `socket.create_connection` to raise across the entire
    suite. Any code path that attempted a real connection would fail loudly, so
    the "network only in `EdgarConnector.fetch`" boundary is continuously
    enforced. EDGAR tests inject canned bytes through a fake `fetch_url` and
    assert the request carries a `STRIX` User-Agent.

## Reasoner isolation

The reasoning seam (`reasoning/base.py`) is a `Protocol` whose single method
receives only `(spec, evidence)` — no file handle, environment, network,
credential, or terminal. The current `DeterministicDemoReasoner` is fixed,
auditable Python (not an LLM; no LLM API is called anywhere in STRIX) and copies
every asserted number verbatim from cited evidence, inventing no authoritative
values. A test runs the reasoner with `builtins.open` and `builtins.input`
monkeypatched to raise, proving it needs neither files nor the terminal to
produce its claim. Whatever the reasoner emits is still subject to the full
deterministic verifier, so an isolated reasoner cannot smuggle an unsupported
claim into a report.

## Source contents are not logged

STRIX writes progress lines, findings, verification status, and typed error
messages — it does not log raw source bytes or fact values to any sink. Raw
source data lives in exactly one place: the preserved `raw/` copy inside the run
directory, written through the atomic store. Error messages reference ids,
tickers, and dates, not source payloads.

## Failure codes

A failed verification publishes **no** claims in the report and exits 1, so a
failed run can never read as approved. The verifier's complete
`FailureCode` vocabulary (`models.py`) is:

`unknown_evidence`, `subject_mismatch`, `evidence_after_as_of`,
`assertion_value_mismatch`, `assertion_unit_mismatch`,
`assertion_evidence_not_cited`, `missing_assertion`, `unsupported_unit`,
`missing_comparison_evidence`, `evidence_not_verified`, `unknown_calculation`,
`missing_source_fact`, `artifact_mismatch`, `evidence_calc_mismatch`,
`incomplete_lineage`, `direction_mismatch`, `statement_mismatch`, `no_claims`.

Their roles in the lineage and claim checks are documented in the
[Evidence model](evidence-model.md#claim-to-evidence-citation-rules).

!!! warning "Scope of these guarantees"
    These mitigations harden the *pipeline*: input handling, persistence, egress,
    and error surfaces. They are not a guarantee about the *truth* of source data.
    A hash confirms integrity, not veracity (see
    [Provenance](provenance.md#what-provenance-does-and-does-not-establish)).
    STRIX is a research and decision-support prototype: it has no user accounts,
    no database, produces no investment advice, and cannot place trades.

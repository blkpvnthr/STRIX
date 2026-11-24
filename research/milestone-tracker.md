# STRIX Milestone Tracker

Persistent tracker for the continuous-implementation directive. Status values:
DONE/TESTED · PARTIAL · NOT_STARTED · NOT_EVALUATED · BLOCKED(reason).

Branch: `research/formal-evidence-verification` (R1 baseline).

| ID | Milestone | Status | Acceptance / evidence | Blockers |
|---|---|---|---|---|
| R1 | Resource-bounded typed evidence verification | **DONE/TESTED** | 1430 passed, 0 regressions; ruff/mypy clean (31 mods); 11 adversarial defects fixed; e2e integration test | — |
| R1-commit | Commit/push/PR R1 | **IN PROGRESS** | scoped commits on branch | push/PR need remote auth (attempt) |
| R2-E | Ed25519 signed certificates | NOT_STARTED | — | needs `cryptography` (offline-OK) |
| R2-A | Live integration (governed `ask`, lifecycle) | NOT_STARTED | — | — |
| R2-B | Runtime behavior monitoring | NOT_STARTED | — | — |
| R2-C | Uncertainty assessment | NOT_STARTED | — | — |
| R2-D | Answer-first conversational intelligence | PARTIAL (deterministic path built in R1) | — | live-agent wiring |
| R2-F | Experimental benchmark + H1–H12 | NOT_EVALUATED | harness design in experimental-protocol.md | live LLM budget/credentials for 120/1200-q runs |
| R2-G | C++ / Metal native backends | NOT_STARTED | — | CMake toolchain; Metal needs macOS GPU |
| DE-1..9 | Financial data engineering platform | PARTIAL (Bronze/Silver/warehouse/dbt per prior memory) | existing lakehouse tests | Airflow orchestration; some connectors need keys |
| R3 | Personal financial intelligence app | NOT_STARTED | — | Plaid/Teller/SnapTrade credentials; REAL financial PII (defer live) |
| R4 | Adaptive assurance | NOT_STARTED | — | depends R2/R3 |
| R5 | FSIP cross-domain integration | NOT_STARTED | — | FSIP repo access; USAspending/SAM connectors |
| R6 | Hosted deployment (Vercel/OCI/Supabase) | NOT_STARTED | — | interactive cloud auth; branch protection; secrets |

## Protocol notes
- External-dependency items (bank connectors, cloud deploy, live-LLM benchmark, FSIP repo): per directive §12, isolate the dependency, build + test the offline alternative, document the blocker, continue unaffected work. Never fabricate success; never spend/deploy/disclose credentials without authorization.
- Full honest status per milestone lives in `milestone-r1-report.md` and this tracker (updated after each milestone).

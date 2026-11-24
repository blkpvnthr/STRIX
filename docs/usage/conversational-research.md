# Conversational research

STRIX answers a financial research question the way a professional research
assistant would — a direct, natural-language answer with supporting analysis —
while keeping every factual number under the same deterministic verification,
immutable evidence, and replay guarantees as the rest of the system.

The language model (GPT-6 Luna, `gpt-6-luna`) never assigns a verification
verdict and never invents a number or a probability. It writes prose; the
machine decides what is true.

## How a question becomes an answer

1. **Classify** (`strix.agent.question`, no model call) — intent, entities,
   asset classes, time horizon, objectives, and evidence requirements.
2. **Research loop** — the model calls typed tools to fetch real data, run
   deterministic calculations, and propose candidate claims. One model call is
   held back for synthesis.
3. **Resolve citations** (`strix.agent.citations`) — web-search handles are
   mapped to preserved evidence; unresolvable handles are stripped, never shown.
4. **Verify** (`strix.agent.verifier`) — every quantitative claim is recomputed
   from preserved observations. Verdicts: VERIFIED, CONTRADICTED,
   INSUFFICIENT_EVIDENCE, UNVERIFIABLE, STALE.
5. **Sanity-check** (`strix.agent.sanity`) — anomalous moves, bad date ranges,
   stale or incomplete sessions are flagged (advisory; verdicts are untouched).
6. **Synthesize** (`strix.agent.synthesis`) — a deterministic market assessment
   plus one GPT-6 Luna narrative call from a compact brief. Any number not
   traceable to a verified claim is stripped.
7. **Assemble, validate, persist, and record** the turn for conversational
   follow-ups.

## Two vocabularies, never merged

STRIX keeps *what the verifier decided about a fact* separate from *what kind of
statement the answer is making*:

| Verification verdict (facts) | Epistemic class (statements) |
| --- | --- |
| VERIFIED, CONTRADICTED, INSUFFICIENT_EVIDENCE, UNVERIFIABLE, STALE | VERIFIED_FACT, ATTRIBUTED_REPORT, ANALYTICAL_INFERENCE, CONDITIONAL_SCENARIO, FORECAST, UNRESOLVED |

An independently verified input can *support* an inference or a forecast, but the
inference itself is never presented as an independently verified fact.

## Market assessment

For market-outlook questions STRIX produces a structured assessment: a stance
(BULLISH / BEARISH / NEUTRAL / MIXED / INSUFFICIENT_EVIDENCE), the horizon,
supporting and contradictory indicators, missing indicators, an evidence-strength
grade, and invalidation conditions. The **stance is computed from the verified
indicators** — it is a reading of the weight of current evidence, explicitly
*not* a probability about the next session. When the evidence does not justify a
direction, the stance is INSUFFICIENT_EVIDENCE and the answer says so.

## Before and after

> **Q: "How can I expect the market to perform tomorrow?"**

**Before** (RUN-20261123-001):

```
Summary:
SPY's five-observation period return through November 20, 2026 was -0.082421 (ratio).
```

A trailing return — it does not address *tomorrow*.

**After:**

```
Answer:
No single session can be predicted from the available evidence. What the verified
data supports is a reading of current conditions — summarized below — not a
probability about the next session.

Market assessment: BEARISH (next session; evidence moderate)
  - SPY trailing return: -8.24% over the measured window
  missing: market breadth, index futures, economic calendar
```

> **Q: "Should I expect bearish or bullish conditions?"** — the AP sell-off
> report that previously surfaced as `cites unknown evidence: turn874423news19`
> is now either resolved to its preserved source or excluded and disclosed as an
> attributed, not independently verified, report. The ~11% weekly index move is
> flagged as an anomalous short-horizon return.

## Conversational memory

Follow-ups in the same thread retain the securities discussed, the last stance,
and the horizon — as context hints only. A previous answer's conclusions are
never reused as source evidence; freshness-sensitive facts are re-fetched and
re-verified each turn.

## Cost and budget

Synthesis reserves one model call from the existing per-run budget; the brief is
a compact structured summary, never the raw datasets, so the added cost is a
single small call. The configured maximum research cost (`$0.05`/run) and the
exclusive use of `gpt-6-luna` are unchanged — there is no escalation to a more
expensive model.

## Replay

`strix replay RUN-...` re-verifies every claim with no model call and, when a
run carries a `response.json`, independently re-validates the response: hash
integrity, that every citation resolves to preserved evidence, and that the
epistemic classification never collapsed into a verification verdict.

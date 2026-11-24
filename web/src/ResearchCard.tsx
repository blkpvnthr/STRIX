import { Fragment, type ReactNode } from "react";
import type {
  AnalyticalInference,
  ConditionalScenario,
  Evidence,
  MarketAssessment,
  MarketStance,
  MonitoringIndicator,
  ResearchJob,
  ResearchResponse,
  ResearchResult,
  SupportingFact,
} from "./types";
import { StatusBadge, fmtTime } from "./ui";

export function ResearchCard({
  job,
  onInspect,
  onCancel,
}: {
  job: ResearchJob;
  onInspect: (result: ResearchResult, evidenceId: string) => void;
  onCancel?: (id: string) => void;
}) {
  const running = job.status === "running" || job.status === "queued";
  return (
    <article className="rounded-2xl border border-[var(--strix-border)] bg-[var(--strix-panel)]/80 p-5 shadow-lg backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-[15px] font-semibold leading-snug text-slate-100">{job.question}</h2>
        {running && onCancel && (
          <button
            onClick={() => onCancel(job.research_id)}
            className="shrink-0 rounded-md border border-[var(--strix-border)] px-2.5 py-1 text-xs text-slate-400 hover:bg-white/5 hover:text-slate-200"
          >
            Cancel
          </button>
        )}
      </div>

      {running && <Progress events={job.events} />}

      {job.status === "failed" && (
        <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">
          {job.error ?? "Research failed."}
        </p>
      )}

      {job.result &&
        (job.result.response ? (
          <ConversationalResult
            result={job.result}
            response={job.result.response}
            onInspect={onInspect}
          />
        ) : (
          <LegacyResult result={job.result} onInspect={onInspect} />
        ))}
    </article>
  );
}

function Progress({ events }: { events: string[] }) {
  const latest = events[events.length - 1] ?? "Starting research…";
  return (
    <div className="mt-4 space-y-1.5">
      {events.slice(-6).map((e, i, arr) => (
        <div
          key={i}
          className={`flex items-center gap-2 text-sm ${
            i === arr.length - 1 ? "text-slate-200" : "text-slate-500"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              i === arr.length - 1 ? "bg-sky-400 strix-pulse" : "bg-slate-600"
            }`}
          />
          {e}
        </div>
      ))}
      {events.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400 strix-pulse" />
          {latest}
        </div>
      )}
    </div>
  );
}

// --- Conversational response (spec §11 section ordering) -------------------

function ConversationalResult({
  result,
  response,
  onInspect,
}: {
  result: ResearchResult;
  response: ResearchResponse;
  onInspect: (result: ResearchResult, evidenceId: string) => void;
}) {
  const { usage, answer } = result;
  const citeIndex = new Map(response.sources.map((e, i) => [e.evidence_id, i + 1]));

  return (
    <div className="mt-4 space-y-5">
      {/* 1. Direct conversational answer */}
      <div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
          <span>Data as of {fmtTime(answer.data_as_of)}</span>
          <span className="text-slate-700">·</span>
          <span className="mono">{response.run_id}</span>
          <span className="text-slate-700">·</span>
          <span className="uppercase tracking-wide">{response.question_intent}</span>
        </div>
        <p className="mt-2 text-[15px] font-medium leading-relaxed text-slate-100">
          {response.direct_answer}
        </p>
      </div>

      {/* 2. Market assessment */}
      {response.market_assessment && (
        <AssessmentBlock assessment={response.market_assessment} />
      )}

      {/* 3. Supporting analytical explanation */}
      {response.analysis && (
        <section>
          <SectionTitle>Analysis</SectionTitle>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{response.analysis}</p>
        </section>
      )}

      {/* 4. Conditional scenarios */}
      {response.conditional_scenarios.length > 0 && (
        <section>
          <SectionTitle>Conditional scenarios</SectionTitle>
          <ul className="mt-2 space-y-2">
            {response.conditional_scenarios.map((s: ConditionalScenario) => (
              <li
                key={s.scenario_id}
                className="rounded-xl border border-[var(--strix-border)] bg-black/20 p-3 text-sm text-slate-300"
              >
                <span className="text-slate-400">If </span>
                {s.condition}
                <span className="text-slate-400"> → </span>
                {s.outcome}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 5. Analytical inferences — interpretation, not independently verified */}
      {response.analytical_inferences.length > 0 && (
        <section>
          <SectionTitle>Interpretation (not independently verified)</SectionTitle>
          <ul className="mt-2 space-y-2">
            {response.analytical_inferences.map((inf: AnalyticalInference) => (
              <li
                key={inf.inference_id}
                className="rounded-xl border border-violet-500/20 bg-violet-500/[0.04] p-3.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm leading-relaxed text-slate-200">{inf.statement}</p>
                  <EpistemicBadge kind={inf.epistemic_class} />
                </div>
                {inf.uncertainty && (
                  <div className="mt-1.5 text-[11px] text-slate-500">{inf.uncertainty}</div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 6. Independently verified findings */}
      {response.supporting_facts.length > 0 && (
        <section>
          <SectionTitle>Independently verified findings</SectionTitle>
          <ul className="mt-2 space-y-2.5">
            {response.supporting_facts.map((f: SupportingFact) => (
              <li
                key={f.claim_id}
                className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-3.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm leading-relaxed text-slate-100">
                    {f.statement}{" "}
                    {f.evidence_ids.map((eid) => (
                      <Cite key={eid} n={citeIndex.get(eid)} onClick={() => onInspect(result, eid)} />
                    ))}
                  </p>
                  <EpistemicBadge kind={f.epistemic_class} />
                </div>
                {f.computed_value && (
                  <div className="mono mt-1.5 text-[11px] text-emerald-300/80">
                    independently recomputed: {f.computed_value}
                    {f.method ? ` · ${f.method}` : ""}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 7. Sources + inline citations */}
      {response.sources.length > 0 && <Sources sources={response.sources} result={result} onInspect={onInspect} />}

      {/* Contradictory + unresolved */}
      {response.contradictory_evidence.length > 0 && (
        <FactList title="Contradicted evidence" facts={response.contradictory_evidence} tone="rose" />
      )}
      {response.unresolved_findings.length > 0 && (
        <FactList
          title="Unresolved (not independently verified)"
          facts={response.unresolved_findings}
          tone="slate"
        />
      )}

      {/* What to monitor */}
      {response.monitoring_indicators.length > 0 && (
        <section>
          <SectionTitle>What to monitor</SectionTitle>
          <ul className="mt-2 space-y-1 text-[13px] text-slate-300">
            {response.monitoring_indicators.map((m: MonitoringIndicator, i) => (
              <li key={i}>
                <span className="text-slate-200">{m.label}</span>
                <span className="text-slate-500"> — {m.rationale}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 8. Limitations */}
      {response.limitations.length > 0 && (
        <section>
          <SectionTitle>Limitations</SectionTitle>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-slate-400">
            {response.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </section>
      )}

      {/* 9. Expandable technical diagnostics */}
      <Diagnostics usage={usage} diagnostics={response.diagnostics} />
      <p className="text-[11px] italic text-slate-600">{answer.disclaimer}</p>
    </div>
  );
}

function AssessmentBlock({ assessment }: { assessment: MarketAssessment }) {
  return (
    <section className="rounded-xl border border-[var(--strix-border)] bg-black/20 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <StanceBadge stance={assessment.stance} />
        <span className="text-[11px] text-slate-500">{assessment.horizon}</span>
        <span className="text-slate-700">·</span>
        <span className="text-[11px] text-slate-500">
          evidence: {assessment.evidence_strength}
        </span>
        {assessment.latest_session && (
          <>
            <span className="text-slate-700">·</span>
            <span className="text-[11px] text-slate-500">
              latest session {assessment.latest_session}
            </span>
          </>
        )}
      </div>
      {assessment.supporting_indicators.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-emerald-300/90">
          {assessment.supporting_indicators.map((ind, i) => (
            <li key={i}>
              + {ind.label}: <span className="text-slate-300">{ind.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {assessment.contradictory_indicators.length > 0 && (
        <ul className="mt-1.5 space-y-1 text-[13px] text-rose-300/90">
          {assessment.contradictory_indicators.map((ind, i) => (
            <li key={i}>
              − {ind.label}: <span className="text-slate-300">{ind.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {assessment.missing_indicators.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-500">
          Missing: {assessment.missing_indicators.join(", ")}
        </p>
      )}
      {assessment.invalidation_conditions.length > 0 && (
        <p className="mt-2 text-[12px] text-amber-300/80">
          Would be invalidated if: {assessment.invalidation_conditions.join("; ")}
        </p>
      )}
    </section>
  );
}

function Sources({
  sources,
  result,
  onInspect,
}: {
  sources: Evidence[];
  result: ResearchResult;
  onInspect: (result: ResearchResult, evidenceId: string) => void;
}) {
  return (
    <section>
      <SectionTitle>Sources</SectionTitle>
      <ol className="mt-2 space-y-1.5">
        {sources.map((e, i) => (
          <li key={e.evidence_id} className="flex items-start gap-2 text-[13px]">
            <button
              onClick={() => onInspect(result, e.evidence_id)}
              className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-sky-500/15 text-[11px] font-semibold text-sky-300 hover:bg-sky-500/25"
            >
              {i + 1}
            </button>
            <div className="min-w-0">
              <span className="text-slate-200">{e.source_title}</span>{" "}
              <span className="text-slate-500">— {e.provider}</span>
              {e.source_url && (
                <a
                  href={e.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 text-sky-400 hover:underline"
                >
                  ↗
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function FactList({
  title,
  facts,
  tone,
}: {
  title: string;
  facts: SupportingFact[];
  tone: "rose" | "slate";
}) {
  const border = tone === "rose" ? "border-rose-500/20" : "border-[var(--strix-border)]";
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      <ul className="mt-2 space-y-2">
        {facts.map((f) => (
          <li key={f.claim_id} className={`rounded-xl border ${border} bg-black/20 p-3.5`}>
            <p className="text-sm leading-relaxed text-slate-300">{f.statement}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Diagnostics({
  usage,
  diagnostics,
}: {
  usage: ResearchResult["usage"];
  diagnostics: Record<string, string>;
}) {
  return (
    <details className="rounded-lg border border-[var(--strix-border)] bg-black/20 px-3 py-2">
      <summary className="cursor-pointer text-[11px] uppercase tracking-wider text-slate-500">
        Technical diagnostics
      </summary>
      <div className="mono mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span>{usage.model_calls} model calls</span>
        <span>{usage.tool_calls} tool calls</span>
        <span>
          {usage.usage.input_tokens}in / {usage.usage.output_tokens}out
        </span>
        <span className="text-emerald-400/70">${usage.estimated_cost_usd}</span>
        <span>{usage.elapsed_seconds}s</span>
      </div>
      {Object.keys(diagnostics).length > 0 && (
        <dl className="mono mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
          {Object.entries(diagnostics).map(([k, v]) => (
            <Fragment key={k}>
              <dt className="text-slate-600">{k}</dt>
              <dd className="text-slate-400">{v}</dd>
            </Fragment>
          ))}
        </dl>
      )}
    </details>
  );
}

// --- Legacy (pre-synthesis) rendering, kept for runs without a response -----

function LegacyResult({
  result,
  onInspect,
}: {
  result: ResearchResult;
  onInspect: (result: ResearchResult, evidenceId: string) => void;
}) {
  const { answer, usage } = result;
  const citeIndex = new Map(answer.evidence.map((e, i) => [e.evidence_id, i + 1]));
  return (
    <div className="mt-4 space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
          <span>Data as of {fmtTime(answer.data_as_of)}</span>
          <span className="text-slate-700">·</span>
          <span className="mono">{answer.run_id}</span>
        </div>
        <p className="mt-2 text-[15px] leading-relaxed text-slate-200">{answer.summary}</p>
      </div>

      {answer.verified_claims.length > 0 && (
        <section>
          <SectionTitle>Verified findings</SectionTitle>
          <ul className="mt-2 space-y-2.5">
            {answer.verified_claims.map((c) => (
              <li
                key={c.claim_id}
                className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-3.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm leading-relaxed text-slate-100">
                    {c.statement}{" "}
                    {c.evidence_ids.map((eid) => (
                      <Cite key={eid} n={citeIndex.get(eid)} onClick={() => onInspect(result, eid)} />
                    ))}
                  </p>
                  <StatusBadge status={c.verification.status} />
                </div>
                {c.verification.computed_value && (
                  <div className="mono mt-1.5 text-[11px] text-emerald-300/80">
                    independently recomputed: {c.verification.computed_value}
                    {c.verification.method ? ` · ${c.verification.method}` : ""}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {answer.evidence.length > 0 && (
        <Sources sources={answer.evidence} result={result} onInspect={onInspect} />
      )}

      {answer.limitations.length > 0 && (
        <section>
          <SectionTitle>Limitations</SectionTitle>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-slate-400">
            {answer.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="mono flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--strix-border)] pt-3 text-[11px] text-slate-500">
        <span>{usage.model_calls} model calls</span>
        <span>{usage.tool_calls} tool calls</span>
        <span className="text-emerald-400/70">${usage.estimated_cost_usd}</span>
      </footer>
      <p className="text-[11px] italic text-slate-600">{answer.disclaimer}</p>
    </div>
  );
}

// --- Shared small components ------------------------------------------------

function Cite({ n, onClick }: { n: number | undefined; onClick: () => void }) {
  if (!n) return null;
  return (
    <button
      onClick={onClick}
      className="mx-0.5 inline-flex -translate-y-0.5 items-center rounded bg-sky-500/15 px-1 text-[10px] font-semibold text-sky-300 align-super hover:bg-sky-500/30"
    >
      {n}
    </button>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
      {children}
    </h3>
  );
}

const STANCE_STYLE: Record<MarketStance, string> = {
  bullish: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  bearish: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  neutral: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  mixed: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  insufficient_evidence: "bg-slate-500/10 text-slate-400 ring-slate-500/20",
};

function StanceBadge({ stance }: { stance: MarketStance }) {
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ${STANCE_STYLE[stance]}`}
    >
      {stance.replace(/_/g, " ")}
    </span>
  );
}

function EpistemicBadge({ kind }: { kind: SupportingFact["epistemic_class"] }) {
  const label = kind.replace(/_/g, " ");
  const style =
    kind === "verified_fact"
      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
      : kind === "forecast"
        ? "bg-violet-500/15 text-violet-300 ring-violet-500/30"
        : kind === "attributed_report"
          ? "bg-sky-500/15 text-sky-300 ring-sky-500/30"
          : "bg-slate-500/15 text-slate-300 ring-slate-500/30";
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${style}`}
    >
      {label}
    </span>
  );
}

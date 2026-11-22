import type { ReactNode } from "react";
import type { ResearchJob, ResearchResult } from "./types";
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

      {job.result && <Result result={job.result} onInspect={onInspect} />}
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

function Result({
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
                      <Cite
                        key={eid}
                        n={citeIndex.get(eid)}
                        onClick={() => onInspect(result, eid)}
                      />
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

      {answer.unresolved_claims.length > 0 && (
        <section>
          <SectionTitle>Not independently verified</SectionTitle>
          <ul className="mt-2 space-y-2">
            {answer.unresolved_claims.map((c) => (
              <li
                key={c.claim_id}
                className="rounded-xl border border-[var(--strix-border)] bg-black/20 p-3.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm leading-relaxed text-slate-300">
                    {c.statement}{" "}
                    {c.evidence_ids.map((eid) => (
                      <Cite
                        key={eid}
                        n={citeIndex.get(eid)}
                        onClick={() => onInspect(result, eid)}
                      />
                    ))}
                  </p>
                  <StatusBadge status={c.verification.status} />
                </div>
                {c.verification.reason && (
                  <div className="mt-1.5 text-[11px] text-slate-500">{c.verification.reason}</div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {answer.evidence.length > 0 && (
        <section>
          <SectionTitle>Sources</SectionTitle>
          <ol className="mt-2 space-y-1.5">
            {answer.evidence.map((e, i) => (
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
        <span>
          {usage.usage.input_tokens}in / {usage.usage.output_tokens}out
        </span>
        <span className="text-emerald-400/70">${usage.estimated_cost_usd}</span>
        <span>{usage.elapsed_seconds}s</span>
      </footer>
      <p className="text-[11px] italic text-slate-600">{answer.disclaimer}</p>
    </div>
  );
}

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

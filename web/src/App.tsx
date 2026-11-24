import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  TERMINAL,
  cancelResearch,
  getHistory,
  getMeta,
  getRun,
  pollResearch,
  retryResearch,
  submitResearch,
} from "./api";
import { authEnabled, getSession, onAuthChange, signOut } from "./auth";
import { Login } from "./Login";
import { EvidenceInspector } from "./EvidenceInspector";
import { ResearchCard } from "./ResearchCard";
import type { Evidence, HistoryItem, Meta, ResearchJob, ResearchResult } from "./types";

const EXAMPLES = [
  "What is the recent realized volatility of SPY?",
  "How has SPY performed versus QQQ over the last 3 months?",
  "What is the maximum drawdown of the Nasdaq-100 ETF this year?",
  "How has Apple's quarterly revenue changed year over year?",
];

// Authentication gate: when Supabase auth is configured, require a session
// before the research UI loads. When it isn't (offline dev), render directly.
export function App() {
  const [ready, setReady] = useState(!authEnabled);
  const [authed, setAuthed] = useState(!authEnabled);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled) return;
    getSession().then((s) => {
      setAuthed(Boolean(s));
      setEmail(s?.user?.email ?? null);
      setReady(true);
    });
    return onAuthChange((s) => {
      setAuthed(Boolean(s));
      setEmail(s?.user?.email ?? null);
    });
  }, []);

  if (!ready) return <div className="flex h-full items-center justify-center text-slate-500">…</div>;
  if (!authed) return <Login />;
  return <ResearchApp userEmail={email} onSignOut={() => void signOut()} />;
}

function ResearchApp({
  userEmail,
  onSignOut,
}: {
  userEmail: string | null;
  onSignOut: () => void;
}) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [inspect, setInspect] = useState<{ ev: Evidence; result: ResearchResult; n: number } | null>(
    null,
  );
  const threadRef = useRef<HTMLDivElement>(null);

  const refreshHistory = useCallback(() => {
    getHistory().then(setHistory).catch(() => undefined);
  }, []);

  useEffect(() => {
    getMeta().then(setMeta).catch(() => undefined);
    refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [jobs]);

  const upsert = useCallback((job: ResearchJob) => {
    setJobs((prev) => {
      const i = prev.findIndex((j) => j.research_id === job.research_id);
      if (i === -1) return [...prev, job];
      const copy = [...prev];
      copy[i] = job;
      return copy;
    });
  }, []);

  const ask = useCallback(
    async (q: string) => {
      const text = q.trim();
      if (!text || busy) return;
      setBusy(true);
      setQuestion("");
      try {
        const { research_id: id } = await submitResearch(text);
        upsert({
          research_id: id,
          question: text,
          status: "queued",
          events: [],
          result: null,
          error: null,
          created_at: new Date().toISOString(),
        });
        pollResearch(id, (job) => {
          upsert(job);
          if (TERMINAL.includes(job.status)) {
            setBusy(false);
            refreshHistory();
          }
        });
      } catch (e) {
        setBusy(false);
        upsert({
          research_id: `err-${Date.now()}`,
          question: text,
          status: "failed",
          events: [],
          result: null,
          error: String(e),
          created_at: new Date().toISOString(),
        });
      }
    },
    [busy, upsert, refreshHistory],
  );

  const openRun = useCallback(
    async (runId: string) => {
      try {
        const result = await getRun(runId);
        upsert({
          research_id: runId,
          question: result.answer.question,
          status: "completed",
          events: [],
          result,
          error: null,
          created_at: result.answer.data_as_of ?? new Date().toISOString(),
        });
      } catch {
        /* ignore */
      }
    },
    [upsert],
  );

  const retry = useCallback(
    async (id: string) => {
      try {
        const job = await retryResearch(id);
        setBusy(true);
        pollResearch(job.research_id, (j) => {
          upsert(j);
          if (TERMINAL.includes(j.status)) {
            setBusy(false);
            refreshHistory();
          }
        });
      } catch {
        /* surfaced via job error on next poll */
      }
    },
    [upsert, refreshHistory],
  );

  const onInspect = useCallback((result: ResearchResult, evidenceId: string) => {
    const idx = result.answer.evidence.findIndex((e) => e.evidence_id === evidenceId);
    if (idx >= 0) setInspect({ ev: result.answer.evidence[idx], result, n: idx + 1 });
  }, []);

  return (
    <div className="flex h-full">
      <Sidebar
        history={history}
        meta={meta}
        userEmail={userEmail}
        onSignOut={onSignOut}
        onPick={openRun}
        onNew={() => setJobs([])}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <MetaBar meta={meta} />

        <div ref={threadRef} className="strix-scroll flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-5">
            {jobs.length === 0 && <Empty onPick={ask} />}
            {jobs.map((job) => (
              <ResearchCard
                key={job.research_id}
                job={job}
                onInspect={onInspect}
                onCancel={(id) => void cancelResearch(id)}
                onRetry={(id) => void retry(id)}
              />
            ))}
          </div>
        </div>

        <Composer
          value={question}
          onChange={setQuestion}
          onSubmit={() => ask(question)}
          busy={busy}
          disabled={meta ? !meta.configured : false}
        />
      </main>

      {inspect && (
        <EvidenceInspector
          evidence={inspect.ev}
          claims={[
            ...inspect.result.answer.verified_claims,
            ...inspect.result.answer.unresolved_claims,
          ]}
          index={inspect.n}
          onClose={() => setInspect(null)}
        />
      )}
    </div>
  );
}

function Sidebar({
  history,
  meta,
  userEmail,
  onSignOut,
  onPick,
  onNew,
}: {
  history: HistoryItem[];
  meta: Meta | null;
  userEmail: string | null;
  onSignOut: () => void;
  onPick: (runId: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-[var(--strix-border)] bg-black/30 md:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <Logo />
        <div>
          <div className="text-sm font-semibold tracking-wide">STRIX</div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Verified research
          </div>
        </div>
      </div>
      <div className="px-4">
        <button
          onClick={onNew}
          className="w-full rounded-lg border border-[var(--strix-border)] bg-white/[0.03] px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]"
        >
          + New research
        </button>
      </div>
      <div className="mt-5 px-5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        History
      </div>
      <nav className="strix-scroll mt-1 flex-1 overflow-y-auto px-3 pb-4">
        {history.length === 0 && (
          <p className="px-2 py-3 text-xs text-slate-600">No research runs yet.</p>
        )}
        {history.map((h) => (
          <button
            key={h.research_id}
            onClick={() => h.run_id && onPick(h.run_id)}
            disabled={!h.run_id}
            className="mt-1 block w-full rounded-lg px-2.5 py-2 text-left hover:bg-white/[0.04] disabled:opacity-50"
          >
            <div className="truncate text-[13px] text-slate-300">
              {h.question || h.research_id}
            </div>
            <div className="mono mt-0.5 text-[10px] text-slate-600">
              {h.run_id ?? h.research_id} · {h.status}
            </div>
          </button>
        ))}
      </nav>
      <div className="border-t border-[var(--strix-border)] px-5 py-3">
        <div className="text-[10px] text-slate-600">
          {meta?.configured
            ? `model ${meta.model} · v${meta.agent_version}`
            : "agent not configured"}
        </div>
        {userEmail && (
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="truncate text-[11px] text-slate-500">{userEmail}</span>
            <button
              onClick={onSignOut}
              className="shrink-0 rounded-md border border-[var(--strix-border)] px-2 py-1 text-[10px] text-slate-400 hover:bg-white/[0.05]"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

function MetaBar({ meta }: { meta: Meta | null }) {
  return (
    <header className="flex items-center justify-between border-b border-[var(--strix-border)] px-6 py-3">
      <div className="text-[13px] text-slate-400">
        Evidence-grounded financial research ·{" "}
        <span className="text-slate-500">every number independently recomputed</span>
      </div>
      <div className="mono flex items-center gap-3 text-[11px] text-slate-500">
        {meta?.configured ? (
          <>
            <Pill ok>{meta.model}</Pill>
            <span>budget ${meta.max_cost_usd}/run</span>
            <span>{meta.web_search_enabled ? "web search on" : "web search off"}</span>
          </>
        ) : (
          <Pill>not configured</Pill>
        )}
      </div>
    </header>
  );
}

function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  disabled: boolean;
}) {
  return (
    <div className="border-t border-[var(--strix-border)] bg-black/20 px-6 py-4">
      <div className="mx-auto flex max-w-3xl items-end gap-3">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          disabled={disabled}
          placeholder={
            disabled
              ? "Set OPENAI_API_KEY in .env to enable research"
              : "Ask about markets, a security, or the economy…"
          }
          className="strix-scroll max-h-40 min-h-[48px] flex-1 resize-none rounded-xl border border-[var(--strix-border)] bg-[var(--strix-panel)] px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-sky-500/50"
        />
        <button
          onClick={onSubmit}
          disabled={busy || disabled || !value.trim()}
          className="h-12 shrink-0 rounded-xl bg-sky-500 px-5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-500"
        >
          {busy ? "Researching…" : "Research"}
        </button>
      </div>
    </div>
  );
}

function Empty({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mt-10 text-center">
      <div className="mx-auto mb-4 w-fit">
        <Logo size={40} />
      </div>
      <h1 className="text-xl font-semibold text-slate-100">Ask a research question</h1>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
        STRIX retrieves real data, recomputes every quantitative claim from preserved
        observations, and shows you exactly what it verified — and what it couldn't.
      </p>
      <div className="mx-auto mt-6 flex max-w-xl flex-wrap justify-center gap-2">
        {EXAMPLES.map((e) => (
          <button
            key={e}
            onClick={() => onPick(e)}
            className="rounded-full border border-[var(--strix-border)] bg-white/[0.03] px-3.5 py-1.5 text-[13px] text-slate-300 hover:bg-white/[0.07]"
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}

function Pill({ children, ok }: { children: ReactNode; ok?: boolean }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 ${
        ok ? "bg-emerald-500/10 text-emerald-300" : "bg-slate-500/10 text-slate-400"
      }`}
    >
      {children}
    </span>
  );
}

function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#0b1220" stroke="#1f2937" />
      <path d="M8 20c2.5 2.2 13.5 2.2 16 0" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" />
      <circle cx="12" cy="13" r="2.4" fill="#38bdf8" />
      <circle cx="20" cy="13" r="2.4" fill="#34d399" />
    </svg>
  );
}

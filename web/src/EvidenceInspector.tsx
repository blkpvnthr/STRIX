import type { Claim, Evidence } from "./types";
import { fmtDate } from "./ui";

export function EvidenceInspector({
  evidence,
  claims,
  index,
  onClose,
}: {
  evidence: Evidence;
  claims: Claim[];
  index: number;
  onClose: () => void;
}) {
  const related = claims.filter((c) => c.evidence_ids.includes(evidence.evidence_id));
  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[var(--strix-border)] bg-[var(--strix-panel)] shadow-2xl">
      <header className="flex items-center justify-between border-b border-[var(--strix-border)] px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-sky-500/15 text-xs font-semibold text-sky-300">
            {index}
          </span>
          <h3 className="text-sm font-semibold">Evidence inspector</h3>
        </div>
        <button
          onClick={onClose}
          className="rounded-md px-2 py-1 text-slate-400 hover:bg-white/5 hover:text-slate-200"
          aria-label="Close"
        >
          ✕
        </button>
      </header>

      <div className="strix-scroll flex-1 overflow-y-auto px-5 py-4 text-sm">
        <h4 className="text-base font-semibold leading-snug">{evidence.source_title}</h4>
        <Field label="Provider" value={evidence.provider} />
        <Field label="Source type" value={evidence.source_type.replace(/_/g, " ")} />
        {evidence.source_url && (
          <div className="mt-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">Source URL</div>
            <a
              href={evidence.source_url}
              target="_blank"
              rel="noreferrer"
              className="break-all text-sky-400 hover:underline"
            >
              {evidence.source_url}
            </a>
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label="Published" value={fmtDate(evidence.published_at)} />
          <Field label="Retrieved" value={fmtDate(evidence.retrieved_at)} />
          <Field label="Observation period" value={evidence.observation_period ?? "—"} />
          <Field label="Freshness" value={evidence.freshness_status} />
        </div>

        {evidence.excerpt && (
          <div className="mt-4">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">
              Preserved excerpt
            </div>
            <blockquote className="mt-1 border-l-2 border-slate-600 pl-3 text-slate-300">
              {evidence.excerpt}
            </blockquote>
          </div>
        )}

        <div className="mt-4">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">
            Artifact integrity (SHA-256)
          </div>
          <div className="mono mt-1 break-all text-xs text-slate-400">{evidence.content_hash}</div>
          <p className="mt-1 text-[11px] text-slate-500">
            A valid hash proves the artifact is unchanged — not that the source is correct.
          </p>
        </div>

        <div className="mt-5">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">
            Related claims ({related.length})
          </div>
          <ul className="mt-2 space-y-2">
            {related.map((c) => (
              <li
                key={c.claim_id}
                className="rounded-lg border border-[var(--strix-border)] bg-black/20 p-3"
              >
                <div className="text-[13px] leading-snug text-slate-200">{c.statement}</div>
                {c.verification.method && (
                  <div className="mono mt-1 text-[11px] text-slate-500">
                    method: {c.verification.method}
                    {c.verification.computed_value
                      ? ` · recomputed ${c.verification.computed_value}`
                      : ""}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </aside>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-slate-200">{value}</div>
    </div>
  );
}

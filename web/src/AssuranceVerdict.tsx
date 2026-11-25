import type { Assurance } from "./types";

// Visual treatment per gateway outcome (dark research-terminal aesthetic).
const OUTCOME_META: Record<string, { text: string; ring: string; dot: string }> = {
  authorized: { text: "text-emerald-300", ring: "ring-emerald-500/30", dot: "bg-emerald-400" },
  qualified: { text: "text-sky-300", ring: "ring-sky-500/30", dot: "bg-sky-400" },
  review_required: { text: "text-amber-300", ring: "ring-amber-500/30", dot: "bg-amber-400" },
  abstain: { text: "text-slate-300", ring: "ring-slate-500/30", dot: "bg-slate-400" },
  rejected: { text: "text-rose-300", ring: "ring-rose-500/30", dot: "bg-rose-400" },
};

/**
 * Renders the independent six-pillar assurance verdict the governed backend
 * attaches to a research result. The release flag — not the raw answer — is the
 * authoritative signal; a withheld answer carries an explicit caveat.
 */
export function AssuranceVerdict({ assurance }: { assurance: Assurance | null | undefined }) {
  if (!assurance) return null;
  const meta = OUTCOME_META[assurance.gateway_outcome] ?? OUTCOME_META.rejected;
  const released = assurance.answer_released;

  return (
    <section
      className={`rounded-lg ring-1 ${meta.ring} bg-white/[0.02] p-3 text-[12px]`}
      aria-label="Assurance verdict"
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
        <span className={`font-semibold uppercase tracking-wide ${meta.text}`}>
          {released ? "Released" : "Withheld"}
        </span>
        <span className="text-slate-400">
          gateway: <span className={meta.text}>{assurance.gateway_outcome}</span>
        </span>
        {assurance.uncertainty_level && (
          <span className="text-slate-400">· uncertainty: {assurance.uncertainty_level}</span>
        )}
      </div>

      {!released && (
        <p className="mt-2 text-amber-300/90">
          The independent gateway did not authorize release — this answer is NOT
          authorized; treat it as unverified/experimental.
        </p>
      )}

      {assurance.error && (
        <p className="mt-2 text-rose-300/90">Assurance error: {assurance.error}</p>
      )}

      {assurance.reason_codes && assurance.reason_codes.length > 0 && (
        <p className="mt-2 text-slate-400">reasons: {assurance.reason_codes.join(", ")}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        {assurance.certificate_id && <span>certificate: {assurance.certificate_id}</span>}
        <span>signed: {assurance.signed ? "yes" : "no"}</span>
        {assurance.audit_event_ids && (
          <span>audit events: {assurance.audit_event_ids.length}</span>
        )}
      </div>
    </section>
  );
}

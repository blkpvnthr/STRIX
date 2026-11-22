import type { VerificationStatus } from "./types";

export const STATUS_META: Record<
  VerificationStatus,
  { label: string; dot: string; text: string; ring: string }
> = {
  verified: {
    label: "Verified",
    dot: "bg-emerald-400",
    text: "text-emerald-300",
    ring: "ring-emerald-500/30",
  },
  contradicted: {
    label: "Contradicted",
    dot: "bg-rose-400",
    text: "text-rose-300",
    ring: "ring-rose-500/30",
  },
  stale: {
    label: "Stale",
    dot: "bg-amber-400",
    text: "text-amber-300",
    ring: "ring-amber-500/30",
  },
  insufficient_evidence: {
    label: "Insufficient evidence",
    dot: "bg-slate-400",
    text: "text-slate-300",
    ring: "ring-slate-500/30",
  },
  unverifiable: {
    label: "Unverifiable",
    dot: "bg-violet-400",
    text: "text-violet-300",
    ring: "ring-violet-500/30",
  },
  pending: {
    label: "Pending",
    dot: "bg-sky-400",
    text: "text-sky-300",
    ring: "ring-sky-500/30",
  },
};

export function StatusBadge({ status }: { status: VerificationStatus }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${m.ring} ${m.text} bg-white/[0.03]`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

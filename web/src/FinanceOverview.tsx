import { useEffect, useState } from "react";
import { getNetWorth, type NetWorth } from "./finance";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: NetWorth };

/**
 * Personal-finance overview: net worth plus the per-account balance breakdown,
 * loaded from the finance API. Money is rendered verbatim from the API's exact
 * Decimal strings (no client-side float formatting). Handles loading, empty,
 * and unavailable states explicitly.
 */
export function FinanceOverview() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    getNetWorth()
      .then((data) => {
        if (active) setState({ kind: "ready", data });
      })
      .catch((err: unknown) => {
        if (active) {
          const message = err instanceof Error ? err.message : "unknown error";
          setState({ kind: "error", message });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (state.kind === "loading") {
    return <p className="text-slate-400 text-sm">Loading finance overview…</p>;
  }
  if (state.kind === "error") {
    return (
      <p className="text-rose-300 text-sm" role="alert">
        Finance data unavailable: {state.message}
      </p>
    );
  }

  const { data } = state;
  return (
    <section className="space-y-4" aria-label="Finance overview">
      <div className="rounded-lg ring-1 ring-white/10 bg-white/[0.02] p-4">
        <div className="text-[11px] uppercase tracking-wide text-slate-500">Net worth</div>
        <div className="mt-1 text-2xl font-semibold text-emerald-300">${data.net_worth}</div>
        <div className="mt-2 flex gap-6 text-[12px] text-slate-400">
          <span>assets ${data.assets_total}</span>
          <span>liabilities ${data.liabilities_total}</span>
        </div>
      </div>

      {data.accounts.length === 0 ? (
        <p className="text-slate-400 text-sm">No accounts yet — add a manual account to begin.</p>
      ) : (
        <ul className="divide-y divide-white/5 rounded-lg ring-1 ring-white/10 bg-white/[0.02]">
          {data.accounts.map((a) => (
            <li key={a.account_id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span className="text-slate-200">
                {a.name}
                <span className="ml-2 text-[11px] text-slate-500">{a.account_type}</span>
              </span>
              <span
                className={
                  a.account_type === "liability" ? "text-rose-300" : "text-slate-200"
                }
              >
                ${a.balance}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

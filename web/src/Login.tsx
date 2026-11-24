import { useState } from "react";
import { signInWithPassword, signUpWithPassword } from "./auth";

// Authenticated-access gate for the private research application. STRIX is
// configured as private: no unauthenticated caller can submit research or read
// another user's history (enforced server-side; this is only the UI).
export function Login() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signin") {
        await signInWithPassword(email.trim(), password);
      } else {
        await signUpWithPassword(email.trim(), password);
        setNotice("Account created. Check your email to confirm, then sign in.");
        setMode("signin");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--strix-border)] bg-black/30 p-7">
        <div className="mb-5 flex items-center gap-2.5">
          <Logo />
          <div>
            <div className="text-sm font-semibold tracking-wide">STRIX</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Verified research · private access
            </div>
          </div>
        </div>

        <h1 className="text-lg font-semibold text-slate-100">
          {mode === "signin" ? "Sign in" : "Create account"}
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          Access is restricted to authorized researchers.
        </p>

        <div className="mt-5 flex flex-col gap-3">
          <input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="rounded-lg border border-[var(--strix-border)] bg-[var(--strix-panel)] px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500/50"
          />
          <input
            type="password"
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Password"
            className="rounded-lg border border-[var(--strix-border)] bg-[var(--strix-panel)] px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500/50"
          />
          {error && <p className="text-xs text-rose-400">{error}</p>}
          {notice && <p className="text-xs text-emerald-400">{notice}</p>}
          <button
            onClick={submit}
            disabled={busy || !email.trim() || !password}
            className="h-11 rounded-xl bg-sky-500 px-5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-500"
          >
            {busy ? "…" : mode === "signin" ? "Sign in" : "Sign up"}
          </button>
          <button
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setNotice(null);
            }}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            {mode === "signin"
              ? "Need an account? Sign up"
              : "Have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
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

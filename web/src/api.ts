import { getAccessToken } from "./auth";
import type {
  HistoryItem,
  Meta,
  ResearchJob,
  ResearchResult,
  SubmitResponse,
} from "./types";

const TERMINAL = ["completed", "partial", "failed", "cancelled", "timed_out"];

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

/** fetch with the Supabase bearer token attached (when authenticated). */
async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

export async function getMeta(): Promise<Meta> {
  return json<Meta>(await fetch("/api/meta"));
}

export async function getHistory(): Promise<HistoryItem[]> {
  const data = await json<{ runs: HistoryItem[] }>(await authedFetch("/api/history"));
  return data.runs;
}

export async function submitResearch(question: string, asOf?: string): Promise<SubmitResponse> {
  const resp = await authedFetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, as_of: asOf || null }),
  });
  return json<SubmitResponse>(resp);
}

export async function getResearch(id: string): Promise<ResearchJob> {
  return json<ResearchJob>(await authedFetch(`/api/research/${id}`));
}

export async function cancelResearch(id: string): Promise<boolean> {
  const data = await json<{ cancelled: boolean }>(
    await authedFetch(`/api/research/${id}/cancel`, { method: "POST" }),
  );
  return data.cancelled;
}

export async function retryResearch(id: string): Promise<ResearchJob> {
  return json<ResearchJob>(await authedFetch(`/api/research/${id}/retry`, { method: "POST" }));
}

export async function getRun(runId: string): Promise<ResearchResult> {
  return json<ResearchResult>(await authedFetch(`/api/runs/${runId}`));
}

export function pollResearch(
  id: string,
  onUpdate: (job: ResearchJob) => void,
  intervalMs = 1000,
): () => void {
  let active = true;
  const tick = async () => {
    if (!active) return;
    try {
      const job = await getResearch(id);
      if (!active) return;
      onUpdate(job);
      if (TERMINAL.includes(job.status)) return;
    } catch {
      /* transient; keep polling */
    }
    if (active) setTimeout(tick, intervalMs);
  };
  void tick();
  return () => {
    active = false;
  };
}

export { TERMINAL };

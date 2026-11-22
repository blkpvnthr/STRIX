import type { HistoryItem, Meta, ResearchJob, ResearchResult } from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

export async function getMeta(): Promise<Meta> {
  return json<Meta>(await fetch("/api/meta"));
}

export async function getHistory(): Promise<HistoryItem[]> {
  const data = await json<{ runs: HistoryItem[] }>(await fetch("/api/history"));
  return data.runs;
}

export async function submitResearch(question: string, asOf?: string): Promise<string> {
  const resp = await fetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, as_of: asOf || null }),
  });
  const data = await json<{ research_id: string }>(resp);
  return data.research_id;
}

export async function getResearch(id: string): Promise<ResearchJob> {
  return json<ResearchJob>(await fetch(`/api/research/${id}`));
}

export async function cancelResearch(id: string): Promise<boolean> {
  const data = await json<{ cancelled: boolean }>(
    await fetch(`/api/research/${id}/cancel`, { method: "POST" }),
  );
  return data.cancelled;
}

export async function getRun(runId: string): Promise<ResearchResult> {
  return json<ResearchResult>(await fetch(`/api/runs/${runId}`));
}

export function pollResearch(
  id: string,
  onUpdate: (job: ResearchJob) => void,
  intervalMs = 700,
): () => void {
  let active = true;
  const tick = async () => {
    if (!active) return;
    try {
      const job = await getResearch(id);
      if (!active) return;
      onUpdate(job);
      if (["completed", "failed", "cancelled"].includes(job.status)) return;
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

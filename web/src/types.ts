export type VerificationStatus =
  | "pending"
  | "verified"
  | "contradicted"
  | "insufficient_evidence"
  | "unverifiable"
  | "stale";

export interface ClaimVerification {
  status: VerificationStatus;
  computed_value: string | null;
  method: string | null;
  reason: string | null;
  tolerance: string | null;
  verifier_version: string | null;
  verified_at: string | null;
}

export interface Calculation {
  method: string;
  calculation_version: string;
  parameters: Record<string, string>;
  input_series_ids: string[];
  claimed_value: string;
  units: string;
}

export interface Claim {
  claim_id: string;
  claim_type: string;
  statement: string;
  evidence_ids: string[];
  calculation: Calculation | null;
  attributed_to: string | null;
  verification: ClaimVerification;
}

export interface Evidence {
  evidence_id: string;
  source_type: string;
  provider: string;
  source_title: string;
  source_url: string | null;
  retrieved_at: string;
  published_at: string | null;
  observation_period: string | null;
  content_hash: string;
  artifact_path: string | null;
  source_anchor: string | null;
  freshness_status: string;
  excerpt: string | null;
}

export interface Answer {
  run_id: string;
  question: string;
  data_as_of: string | null;
  summary: string;
  verified_claims: Claim[];
  unresolved_claims: Claim[];
  evidence: Evidence[];
  limitations: string[];
  disclaimer: string;
}

export interface Usage {
  model_calls: number;
  tool_calls: number;
  usage: {
    input_tokens: number;
    cached_input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    total_tokens: number;
  };
  estimated_cost_usd: string;
  tool_cost_usd: string;
  pricing_version: string;
  elapsed_seconds: string;
  exhausted: boolean;
  exhausted_reason: string | null;
}

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "timed_out";

export interface ResearchResult {
  run_id: string;
  answer: Answer;
  usage: Usage;
  claims?: Claim[];
  evidence?: Evidence[];
  manifest?: unknown;
  artifact_ref?: string | null;
}

export interface ResearchJob {
  research_id: string;
  question: string;
  status: JobStatus;
  events: string[];
  result: ResearchResult | null;
  run_id?: string | null;
  error: string | null;
  cost_usd?: string | null;
  attempt?: number;
  max_attempts?: number;
  created_at: string;
}

export interface SubmitResponse {
  research_id: string;
  status: JobStatus;
  created: boolean;
}

export interface HistoryItem {
  research_id: string;
  question: string;
  status: JobStatus;
  run_id: string | null;
  cost_usd: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Meta {
  configured: boolean;
  model?: string;
  pricing_version?: string;
  max_cost_usd?: string;
  web_search_enabled?: boolean;
  agent_version?: string;
  auth_required?: boolean;
  error?: string;
}

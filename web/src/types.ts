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

// --- Conversational response (spec §9) ------------------------------------

export type EpistemicClass =
  | "verified_fact"
  | "attributed_report"
  | "analytical_inference"
  | "conditional_scenario"
  | "forecast"
  | "unresolved";

export type MarketStance =
  | "bullish"
  | "bearish"
  | "neutral"
  | "mixed"
  | "insufficient_evidence";

export type EvidenceStrength = "strong" | "moderate" | "weak" | "insufficient";

export interface DirectionalIndicator {
  label: string;
  detail: string;
  claim_ids: string[];
}

export interface MarketAssessment {
  stance: MarketStance;
  horizon: string;
  analysis_timestamp: string;
  latest_session: string | null;
  supporting_indicators: DirectionalIndicator[];
  contradictory_indicators: DirectionalIndicator[];
  missing_indicators: string[];
  evidence_strength: EvidenceStrength;
  conditional_scenarios: string[];
  invalidation_conditions: string[];
}

export interface SupportingFact {
  claim_id: string;
  statement: string;
  epistemic_class: EpistemicClass;
  evidence_ids: string[];
  computed_value: string | null;
  method: string | null;
}

export interface AnalyticalInference {
  inference_id: string;
  epistemic_class: EpistemicClass;
  statement: string;
  supporting_claim_ids: string[];
  supporting_evidence_ids: string[];
  uncertainty: string | null;
}

export interface ConditionalScenario {
  scenario_id: string;
  condition: string;
  outcome: string;
  supporting_claim_ids: string[];
}

export interface MonitoringIndicator {
  label: string;
  rationale: string;
}

export interface ResearchResponse {
  run_id: string;
  question: string;
  question_intent: string;
  direct_answer: string;
  analysis: string;
  market_assessment: MarketAssessment | null;
  supporting_facts: SupportingFact[];
  analytical_inferences: AnalyticalInference[];
  conditional_scenarios: ConditionalScenario[];
  contradictory_evidence: SupportingFact[];
  unresolved_findings: SupportingFact[];
  monitoring_indicators: MonitoringIndicator[];
  sources: Evidence[];
  limitations: string[];
  diagnostics: Record<string, string>;
  verified_answer: Answer;
}

// Independent six-pillar assurance verdict attached by the governed backend
// (strix.agent.governed.govern_agent_outcome) to every research result.
export interface Assurance {
  gateway_outcome: string;
  answer_released: boolean;
  reason_codes?: string[];
  uncertainty_level?: string;
  certificate_id?: string;
  signed?: boolean;
  audit_event_ids?: string[];
  error?: string;
}

export interface ResearchResult {
  run_id: string;
  answer: Answer;
  response: ResearchResponse | null;
  usage: Usage;
  claims: Claim[];
  thread_id?: string | null;
  assurance?: Assurance | null;
}

export interface ResearchJob {
  research_id: string;
  question: string;
  thread_id?: string | null;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  events: string[];
  result: ResearchResult | null;
  error: string | null;
  created_at: string;
}

export interface HistoryItem {
  run_id: string;
  question: string;
  verified_count: number;
  created_at: string;
  model: string;
}

export interface Meta {
  configured: boolean;
  model?: string;
  pricing_version?: string;
  max_cost_usd?: string;
  web_search_enabled?: boolean;
  agent_version?: string;
  error?: string;
}

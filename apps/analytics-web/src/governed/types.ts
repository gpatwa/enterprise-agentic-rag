// Mirrors packages/platform_contracts/analytics_v2.py and analytics_v2_api.py (ADS-045).

export interface OutcomeBase {
  contract_version: 'v2';
  query_id: string;
  tenant_id: string;
  user_id: string;
  dataset: string;
  generated_at: string;
  assumptions: string[];
}

export interface Claim {
  text: string;
  cites: string[];
}

export interface ResultTable {
  columns: string[];
  rows: (string | number | boolean | null)[][];
  row_count: number;
}

export interface Visualization {
  kind: 'stat' | 'line' | 'bar' | 'table';
  x_column: number | null;
  y_columns: number[];
  semantic_ids: string[];
  row_limit: number;
}

export interface AnswerEvidence {
  semantic_contract_version: string | null;
  metric_ids: string[];
  dimension_ids: string[];
  result_fingerprint: string | null;
}

export interface AnswerOutcome extends OutcomeBase {
  outcome: 'answer';
  answer: string;
  explanation_status: 'grounded' | 'evidence_only' | null;
  claims: Claim[];
  result: ResultTable | null;
  visualization: Visualization | null;
  evidence: AnswerEvidence;
}

export interface ClarifyOutcome extends OutcomeBase {
  outcome: 'clarify';
  questions: { id: string; prompt: string; choices: { id: string; label: string }[]; free_text_allowed: boolean }[];
}

export interface ReviewOutcome extends OutcomeBase {
  outcome: 'review';
  review_id: string;
  plan_fingerprint: string | null;
  risk_reasons: string[];
  expires_at: string;
  allowed_actions: ('approve' | 'edit' | 'reject')[];
}

export interface RefuseOutcome extends OutcomeBase {
  outcome: 'refuse';
  reason_code: string;
  explanation: string;
  remediation: string | null;
}

export interface FailedOutcome extends OutcomeBase {
  outcome: 'failed';
  error_code: string;
  message: string;
  retryable: boolean;
}

export type Outcome = AnswerOutcome | ClarifyOutcome | ReviewOutcome | RefuseOutcome | FailedOutcome;

export type RunState = 'running' | 'waiting_clarification' | 'waiting_review' | 'terminal';

export interface RunResponse {
  run_id: string;
  state: RunState;
  outcome: Outcome | null;
}

export interface GovernedConfig {
  baseUrl: string;
  token: string;
  purpose: string;
  apiKey?: string;
}

export interface TraceEntry {
  at: string;
  label: string;
  runId?: string;
  detail?: string;
}

// Pure workflow logic for the governed analytics UI (ADS-047): API client, state mapping,
// client-side claim grounding, chart spec, trace, and replay verification. No React here.

import type {
  AnswerOutcome,
  Claim,
  GovernedConfig,
  Outcome,
  ResultTable,
  RunResponse,
  TraceEntry,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

const MESSAGES: Record<string, string> = {
  missing_bearer_token: 'Enter an access token to use governed analysis.',
  invalid_identity_token: 'The access token was rejected. Check it and try again.',
  purpose_not_authorized: 'This token is not authorized for the selected purpose.',
  governed_runtime_not_configured: 'Governed analysis is not enabled on this server.',
  idempotency_key_reused: 'That request key was already used for a different question.',
  invalid_idempotency_key: 'The request key is invalid.',
  run_not_found: 'No run with that ID is visible to this identity and purpose.',
  not_run_requester: 'Only the person who asked can answer a clarification.',
  run_not_awaiting_clarification: 'This run is no longer waiting for a clarification.',
  run_not_awaiting_review: 'This run is no longer waiting for a review.',
  review_not_permitted: 'You cannot decide this review. Someone other than the requester must.',
  review_stale: 'The plan changed or the review was already decided. Reload the run.',
  invalid_clarification: 'That choice is not valid for this question.',
  run_not_resumable: 'The run cannot be resumed right now.',
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return MESSAGES[error.code] ?? `The request failed (${error.status}).`;
  return error instanceof Error ? error.message : 'The request failed.';
}

const FAILURE_COPY: Record<string, string> = {
  query_timeout: 'The request ran out of time.',
  executor_unavailable: 'The data source could not run the query.',
  planner_unavailable: 'The request could not be planned.',
  internal_error: 'The run failed.',
};
export const failureCopy = (code: string) => FAILURE_COPY[code] ?? 'The run failed.';

// ---- API client ----

type Fetch = typeof fetch;

function headers(config: GovernedConfig, extra: Record<string, string> = {}): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${config.token}`,
    ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
    ...extra,
  };
}

async function parse(response: Response): Promise<RunResponse> {
  if (!response.ok) {
    let code = `http_${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') code = body.detail;
    } catch {
      /* non-JSON error body: keep the status code */
    }
    throw new ApiError(response.status, code);
  }
  return (await response.json()) as RunResponse;
}

const base = (config: GovernedConfig) => `${config.baseUrl}/api/v2/analytics`;

export const analyze = (config: GovernedConfig, requestText: string, key: string, doFetch: Fetch = fetch) =>
  doFetch(`${base(config)}/analyze`, {
    method: 'POST',
    headers: headers(config, { 'Idempotency-Key': key }),
    body: JSON.stringify({ request_text: requestText, purpose: config.purpose }),
  }).then(parse);

export const getRun = (config: GovernedConfig, runId: string, doFetch: Fetch = fetch) =>
  doFetch(`${base(config)}/runs/${encodeURIComponent(runId)}?purpose=${encodeURIComponent(config.purpose)}`, {
    headers: headers(config),
  }).then(parse);

export const clarify = (
  config: GovernedConfig,
  runId: string,
  ambiguityCode: string,
  selectedId: string,
  doFetch: Fetch = fetch,
) =>
  doFetch(`${base(config)}/runs/${encodeURIComponent(runId)}/clarify`, {
    method: 'POST',
    headers: headers(config),
    body: JSON.stringify({ purpose: config.purpose, ambiguity_code: ambiguityCode, selected_id: selectedId }),
  }).then(parse);

export const decideReview = (
  config: GovernedConfig,
  runId: string,
  decision: 'approved' | 'rejected',
  planFingerprint: string,
  doFetch: Fetch = fetch,
) =>
  doFetch(`${base(config)}/runs/${encodeURIComponent(runId)}/review`, {
    method: 'POST',
    headers: headers(config),
    body: JSON.stringify({ purpose: config.purpose, decision, plan_fingerprint: planFingerprint }),
  }).then(parse);

export const newIdempotencyKey = (): string => `web-${crypto.randomUUID()}`;

/** Poll a running run until it settles (or attempts run out, returning the last response). */
export async function pollUntilSettled(
  fetchRun: () => Promise<RunResponse>,
  { intervalMs = 1000, maxAttempts = 30, sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms)) } = {},
): Promise<RunResponse> {
  let latest = await fetchRun();
  for (let attempt = 1; latest.state === 'running' && attempt < maxAttempts; attempt += 1) {
    await sleep(intervalMs);
    latest = await fetchRun();
  }
  return latest;
}

// ---- view state ----

export type ViewKind = 'running' | 'answer' | 'clarify' | 'review' | 'refuse' | 'failed';

export function viewKind(response: RunResponse): ViewKind {
  if (response.state === 'running' || response.outcome === null) return 'running';
  return response.outcome.outcome;
}

export const isSettled = (response: RunResponse) => response.state !== 'running';

// ---- evidence: resolving and checking citations on the client ----

export interface ResolvedCite {
  cite: string;
  kind: 'cell' | 'semantic';
  label: string;
  value?: string;
}

const CELL = /^cell:r(\d+)c(\d+)$/;

/** Column index -> semantic ID, from the data-free visualization binding (x first, then y columns). */
export function columnLabels(answer: AnswerOutcome): Record<number, string> {
  const viz = answer.visualization;
  if (!viz) return {};
  const columns = [...(viz.x_column === null ? [] : [viz.x_column]), ...viz.y_columns];
  return Object.fromEntries(columns.flatMap((column, i) => (viz.semantic_ids[i] ? [[column, viz.semantic_ids[i]]] : [])));
}

export function resolveCite(
  result: ResultTable | null,
  cite: string,
  labels: Record<number, string> = {},
): ResolvedCite | null {
  const match = CELL.exec(cite);
  if (match) {
    if (!result) return null;
    const row = result.rows[Number(match[1])];
    const column = labels[Number(match[2])] ?? result.columns[Number(match[2])];
    if (!row || column === undefined) return null;
    const cell = row[Number(match[2])];
    return { cite, kind: 'cell', label: column, value: cell === null || cell === undefined ? '' : String(cell) };
  }
  if (/^(metric|dimension|contract):.+/.test(cite)) return { cite, kind: 'semantic', label: cite.split(':')[1] };
  return null;
}

const NUMBER = /\d[\d,]*(?:\.\d+)?/g;
const normalize = (token: string) => {
  let text = token.replaceAll(',', '');
  if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '');
  return text.replace(/^0+/, '') || '0';
};

export interface GroundedClaim {
  claim: Claim;
  cites: ResolvedCite[];
  grounded: boolean;
  problems: string[];
}

/** Re-check, in the browser, that a claim's citations resolve and its numbers come from cited cells. */
export function groundClaim(
  claim: Claim,
  result: ResultTable | null,
  labels: Record<number, string> = {},
): GroundedClaim {
  const resolved: ResolvedCite[] = [];
  const problems: string[] = [];
  for (const cite of claim.cites) {
    const item = resolveCite(result, cite, labels);
    if (item) resolved.push(item);
    else problems.push(`unknown citation ${cite}`);
  }
  const cells = resolved.filter((item) => item.kind === 'cell');
  if (cells.length === 0) problems.push('no result cell cited');
  const allowed = new Set(cells.flatMap((item) => (item.value ?? '').match(NUMBER) ?? []).map(normalize));
  for (const token of claim.text.match(NUMBER) ?? []) {
    if (!allowed.has(normalize(token))) problems.push(`number ${token} is not in a cited cell`);
  }
  return { claim, cites: resolved, grounded: problems.length === 0, problems };
}

// ---- chart ----

/** Vega-Lite spec for line/bar answers from the data-free visualization spec; null for stat/table. */
export function chartSpec(answer: AnswerOutcome): Record<string, unknown> | null {
  const { result, visualization: viz } = answer;
  if (!result || !viz || (viz.kind !== 'line' && viz.kind !== 'bar')) return null;
  if (viz.x_column === null || viz.y_columns.length === 0) return null;
  const x = result.columns[viz.x_column];
  const y = result.columns[viz.y_columns[0]];
  if (x === undefined || y === undefined) return null;
  const values = result.rows.slice(0, viz.row_limit).map((row) => ({
    [x]: row[viz.x_column as number],
    [y]: Number(row[viz.y_columns[0]]),
  }));
  return {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
    data: { values },
    mark: viz.kind === 'line' ? { type: 'line', point: true } : { type: 'bar' },
    encoding: {
      x: { field: x, type: viz.kind === 'line' ? 'temporal' : 'nominal', title: x },
      y: { field: y, type: 'quantitative', title: y },
    },
    height: 260,
  };
}

// ---- trace and replay ----

export const traceEntry = (label: string, runId?: string, detail?: string, now = () => new Date()): TraceEntry => ({
  at: now().toISOString(),
  label,
  runId,
  detail,
});

export function describeOutcome(outcome: Outcome | null): string {
  if (!outcome) return 'running';
  switch (outcome.outcome) {
    case 'answer':
      return `answer (${outcome.explanation_status ?? 'no narrative'})`;
    case 'clarify':
      return `clarification requested (${outcome.questions.map((q) => q.id).join(', ')})`;
    case 'review':
      return 'waiting for human review';
    case 'refuse':
      return `refused (${outcome.reason_code})`;
    case 'failed':
      return `failed (${outcome.error_code})`;
  }
}

export interface ReplayVerdict {
  verified: boolean;
  message: string;
}

/** Compare an original answer with a fresh read of the same run. */
export function verifyReplay(original: RunResponse, replay: RunResponse): ReplayVerdict {
  if (original.run_id !== replay.run_id) return { verified: false, message: 'Replay produced a different run.' };
  const a = original.outcome?.outcome === 'answer' ? original.outcome.evidence.result_fingerprint : null;
  const b = replay.outcome?.outcome === 'answer' ? replay.outcome.evidence.result_fingerprint : null;
  if (!a || !b) return { verified: false, message: 'Replay did not return an answer to compare.' };
  return a === b
    ? { verified: true, message: 'Replay verified: same run and identical result fingerprint.' }
    : { verified: false, message: 'Replay returned a different result fingerprint.' };
}

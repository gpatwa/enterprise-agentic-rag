import type { AnswerOutcome } from './types';

export const base = {
  contract_version: 'v2' as const, query_id: 'q', tenant_id: 't', user_id: 'u', dataset: 'orders',
  generated_at: '2026-10-03T00:00:00Z', assumptions: [],
};
export const answer = (overrides: Partial<AnswerOutcome> = {}): AnswerOutcome => ({
  ...base,
  outcome: 'answer',
  answer: 'Paid brought in 1,200.5.',
  explanation_status: 'grounded',
  claims: [{ text: 'Paid brought in 1,200.5.', cites: ['cell:r0c0', 'cell:r0c1', 'metric:revenue'] }],
  result: { columns: ['status', 'revenue'], rows: [['paid', '1200.5'], ['refunded', '300']], row_count: 2 },
  visualization: { kind: 'bar', x_column: 0, y_columns: [1], semantic_ids: ['orders.status', 'revenue'], row_limit: 50 },
  evidence: { semantic_contract_version: 'v1', metric_ids: ['revenue'], dimension_ids: ['orders.status'], result_fingerprint: 'f'.repeat(64) },
  ...overrides,
});

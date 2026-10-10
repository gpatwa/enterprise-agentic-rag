import assert from 'node:assert/strict';
import { test } from 'node:test';

import { answer, base } from './fixtures';
import type { GovernedConfig, RunResponse } from './types';
import {
  analyze,
  ApiError,
  chartSpec,
  columnLabels,
  clarify,
  decideReview,
  errorMessage,
  getRun,
  groundClaim,
  pollUntilSettled,
  resolveCite,
  verifyReplay,
  viewKind,
} from './workflow';

const config: GovernedConfig = { baseUrl: 'http://api', token: 'tok', purpose: 'analytics' };
const run = (outcome: RunResponse['outcome'], state: RunResponse['state'] = 'terminal'): RunResponse => ({ run_id: 'run-1', state, outcome });

test('citations resolve to result cells and semantic IDs; unknown ones do not', () => {
  const result = answer().result;
  assert.deepEqual(resolveCite(result, 'cell:r1c1'), { cite: 'cell:r1c1', kind: 'cell', label: 'revenue', value: '300' });
  assert.equal(resolveCite(result, 'cell:r9c0'), null);
  assert.equal(resolveCite(result, 'cell:r0c9'), null);
  assert.equal(resolveCite(null, 'cell:r0c0'), null);
  assert.equal(resolveCite(result, 'metric:revenue')?.kind, 'semantic');
  assert.equal(resolveCite(result, 'sql:DROP'), null);
});

test('claims are re-verified against the returned result in the browser', () => {
  const result = answer().result;
  assert.equal(groundClaim(answer().claims[0], result).grounded, true);
  const forged = groundClaim({ text: 'Paid brought in 9,999.', cites: ['cell:r0c1'] }, result);
  assert.equal(forged.grounded, false);
  assert.match(forged.problems[0], /9,999/);
  assert.equal(groundClaim({ text: 'Revenue is great.', cites: ['metric:revenue'] }, result).grounded, false);
  assert.equal(groundClaim({ text: 'Fine.', cites: ['cell:r5c5'] }, result).grounded, false);
  assert.equal(groundClaim({ text: 'Paid was 1200.50.', cites: ['cell:r0c1'] }, result).grounded, true);
});

test('chart specs are built only for bar/line answers from bound columns', () => {
  const spec = chartSpec(answer()) as { mark: { type: string }; data: { values: unknown[] }; encoding: { y: { field: string } } };
  assert.equal(spec.mark.type, 'bar');
  assert.equal(spec.data.values.length, 2);
  assert.equal(spec.encoding.y.field, 'revenue');
  assert.equal((chartSpec(answer({ visualization: { ...answer().visualization!, kind: 'line' } })) as { encoding: { x: { type: string } } }).encoding.x.type, 'temporal');
  assert.equal(chartSpec(answer({ visualization: { ...answer().visualization!, kind: 'stat' } })), null);
  assert.equal(chartSpec(answer({ visualization: { ...answer().visualization!, x_column: 7 } })), null);
  assert.equal(chartSpec(answer({ result: null })), null);
});

test('every run state maps to one view', () => {
  assert.equal(viewKind({ run_id: 'r', state: 'running', outcome: null }), 'running');
  assert.equal(viewKind(run(answer())), 'answer');
  assert.equal(viewKind(run({ ...base, outcome: 'clarify', questions: [] })), 'clarify');
  assert.equal(viewKind(run({ ...base, outcome: 'refuse', reason_code: 'policy_restricted', explanation: 'x', remediation: null })), 'refuse');
  assert.equal(viewKind(run({ ...base, outcome: 'failed', error_code: 'internal_error', message: 'm', retryable: false })), 'failed');
});

test('replay verification needs the same run and an identical fingerprint', () => {
  const original = run(answer());
  assert.equal(verifyReplay(original, run(answer())).verified, true);
  assert.equal(verifyReplay(original, run(answer({ evidence: { ...answer().evidence, result_fingerprint: 'e'.repeat(64) } }))).verified, false);
  assert.equal(verifyReplay(original, { ...run(answer()), run_id: 'other' }).verified, false);
  assert.equal(verifyReplay(original, { run_id: 'run-1', state: 'running', outcome: null }).verified, false);
});

test('polling stops when the run settles and is bounded otherwise', async () => {
  let calls = 0;
  const settled = await pollUntilSettled(
    async () => (++calls < 3 ? { run_id: 'r', state: 'running', outcome: null } : run(answer())),
    { sleep: async () => {} },
  );
  assert.equal(settled.state, 'terminal');
  assert.equal(calls, 3);
  let stuck = 0;
  const last = await pollUntilSettled(async () => (++stuck, { run_id: 'r', state: 'running' as const, outcome: null }), { maxAttempts: 4, sleep: async () => {} });
  assert.equal(last.state, 'running');
  assert.equal(stuck, 4);
});

const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

test('requests carry the bearer token, idempotency key, purpose, and strict bodies', async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const spy = (status: number, body: unknown): typeof fetch => async (url, init) => {
    seen.push({ url: String(url), init: init ?? {} });
    return reply(status, body)();
  };
  const ok = spy(200, run(answer()));
  await analyze(config, 'Show revenue', 'key-1', ok);
  await getRun(config, 'run 1', ok);
  await clarify(config, 'run-1', 'time', 'created_at', ok);
  await decideReview(config, 'run-1', 'approved', 'a'.repeat(64), ok);
  assert.equal(seen[0].url, 'http://api/api/v2/analytics/analyze');
  const h = seen[0].init.headers as Record<string, string>;
  assert.equal(h.Authorization, 'Bearer tok');
  assert.equal(h['Idempotency-Key'], 'key-1');
  assert.deepEqual(JSON.parse(seen[0].init.body as string), { request_text: 'Show revenue', purpose: 'analytics' });
  assert.equal(seen[1].url, 'http://api/api/v2/analytics/runs/run%201?purpose=analytics');
  assert.deepEqual(JSON.parse(seen[2].init.body as string), { purpose: 'analytics', ambiguity_code: 'time', selected_id: 'created_at' });
  assert.deepEqual(JSON.parse(seen[3].init.body as string), { purpose: 'analytics', decision: 'approved', plan_fingerprint: 'a'.repeat(64) });
  assert.ok(!JSON.stringify(seen).includes('sql'));
});

test('API errors surface stable codes as plain messages', async () => {
  const failing: typeof fetch = reply(409, { detail: 'review_stale' }) as typeof fetch;
  await assert.rejects(decideReview(config, 'r', 'approved', 'a'.repeat(64), failing), (error) => {
    assert.ok(error instanceof ApiError && error.status === 409 && error.code === 'review_stale');
    assert.match(errorMessage(error), /already decided/);
    return true;
  });
  const html: typeof fetch = async () => new Response('<html>', { status: 502 });
  await assert.rejects(getRun(config, 'r', html), (error) => error instanceof ApiError && error.code === 'http_502');
  assert.match(errorMessage(new ApiError(500, 'weird')), /500/);
});

test('cited cells are labelled with their semantic IDs when the visualization binds them', () => {
  assert.deepEqual(columnLabels(answer()), { 0: 'orders.status', 1: 'revenue' });
  assert.deepEqual(columnLabels(answer({ visualization: null })), {});
  const labelled = groundClaim(answer().claims[0], answer().result, columnLabels(answer()));
  assert.deepEqual(labelled.cites.filter((c) => c.kind === 'cell').map((c) => c.label), ['orders.status', 'revenue']);
});

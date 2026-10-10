import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderToStaticMarkup } from 'react-dom/server';

import type { RunResponse } from './types';
import { OutcomeView, type OutcomeActions, TracePanel } from './views';
import { answer } from './fixtures';
import { traceEntry } from './workflow';

const actions: OutcomeActions = { busy: false, replay: null, onClarify() {}, onDecide() {}, onRetry() {}, onReplay() {} };
const base = answer();
const shell = { contract_version: 'v2' as const, query_id: 'q', tenant_id: 't', user_id: 'u', dataset: 'd', generated_at: '2026-10-03T00:00:00Z', assumptions: [] };
const render = (response: RunResponse, overrides: Partial<OutcomeActions> = {}) =>
  renderToStaticMarkup(<OutcomeView response={response} actions={{ ...actions, ...overrides }} />);

test('answer shows narrative, verified claims with cited values, evidence, table, and replay', () => {
  const html = render({ run_id: 'run-1', state: 'terminal', outcome: base });
  assert.match(html, /data-view="answer"/);
  assert.match(html, /Paid brought in 1,200.5./);
  assert.match(html, /Verified in browser/);
  assert.match(html, /orders.status = paid/);
  assert.match(html, /revenue = 1200.5/);
  assert.match(html, /Result fingerprint/);
  assert.match(html, /Replay and verify/);
  assert.match(html, /<td>refunded<\/td>/);
  assert.doesNotMatch(html, /Not verified/);
  assert.doesNotMatch(html, /SELECT/i);
});

test('a claim the browser cannot verify is flagged instead of trusted', () => {
  const forged = { ...base, claims: [{ text: 'Revenue was 9,999.', cites: ['cell:r0c1'] }] };
  const html = render({ run_id: 'run-1', state: 'terminal', outcome: forged });
  assert.match(html, /Not verified/);
  assert.match(html, /9,999 is not in a cited cell/);
});

test('evidence-only answers say so and show no claims', () => {
  const html = render({ run_id: 'r', state: 'terminal', outcome: { ...base, explanation_status: 'evidence_only', claims: [], answer: 'The validated result is returned without narrative.' } });
  assert.match(html, /data-testid="evidence-only"/);
  assert.doesNotMatch(html, /Claims and their evidence/);
});

test('replay verdict is announced', () => {
  const html = render({ run_id: 'r', state: 'terminal', outcome: base }, { replay: { verified: true, message: 'Replay verified: same run.' } });
  assert.match(html, /role="status"[^>]*>Replay verified/);
});

test('clarify offers each certified choice as a button', () => {
  const html = render({ run_id: 'r', state: 'waiting_clarification', outcome: { ...shell, outcome: 'clarify', questions: [{ id: 'time', prompt: 'Select the intended certified time.', free_text_allowed: false, choices: [{ id: 'created_at', label: 'created_at' }, { id: 'status', label: 'status' }] }] } });
  assert.match(html, /data-view="clarify"/);
  assert.match(html, /Select the intended certified time/);
  assert.match(html, />created_at<\/button>/);
});

test('review shows the plan fingerprint and enables decisions only when it is present', () => {
  const review = { ...shell, outcome: 'review' as const, review_id: 'rev-1', plan_fingerprint: 'b'.repeat(64), risk_reasons: ['human_approval'], expires_at: '2026-10-04T00:00:00Z', allowed_actions: ['approve' as const, 'reject' as const] };
  const html = render({ run_id: 'r', state: 'waiting_review', outcome: review });
  assert.match(html, /data-view="review"/);
  assert.match(html, new RegExp('b'.repeat(64)));
  assert.doesNotMatch(html, /disabled/);
  const missing = render({ run_id: 'r', state: 'waiting_review', outcome: { ...review, plan_fingerprint: null } });
  assert.equal((missing.match(/disabled/g) ?? []).length, 2);
  const busy = render({ run_id: 'r', state: 'waiting_review', outcome: review }, { busy: true });
  assert.equal((busy.match(/disabled/g) ?? []).length, 2);
});

test('refusal and failure states explain without leaking internals; retry only when retryable', () => {
  const refuse = render({ run_id: 'r', state: 'terminal', outcome: { ...shell, outcome: 'refuse', reason_code: 'policy_restricted', explanation: 'The request was refused by policy or review.', remediation: null } });
  assert.match(refuse, /data-view="refuse"/);
  assert.match(refuse, /policy_restricted/);
  const failed = (retryable: boolean) => render({ run_id: 'r', state: 'terminal', outcome: { ...shell, outcome: 'failed', error_code: 'query_timeout', message: 'The request exceeded its time budget.', retryable } });
  assert.match(failed(true), /Try again/);
  assert.doesNotMatch(failed(false), /Try again/);
  assert.match(failed(true), /ran out of time/);
});

test('running state is announced politely', () => {
  assert.match(render({ run_id: 'r', state: 'running', outcome: null }), /role="status" aria-live="polite" data-view="running"/);
});

test('trace lists each step in order', () => {
  const entries = [traceEntry('Submitted: running', 'run-1'), traceEntry('Checked result: answer (grounded)', 'run-1', 'detail')];
  const html = renderToStaticMarkup(<TracePanel trace={entries} />);
  assert.ok(html.indexOf('Submitted') < html.indexOf('Checked result'));
  assert.match(renderToStaticMarkup(<TracePanel trace={[]} />), /Nothing has happened yet/);
});

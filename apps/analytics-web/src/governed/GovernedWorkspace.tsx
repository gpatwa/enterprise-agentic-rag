import { useRef, useState } from 'react';

import type { GovernedConfig, RunResponse, TraceEntry } from './types';
import { OutcomeView, TracePanel } from './views';
import {
  analyze,
  clarify,
  decideReview,
  describeOutcome,
  errorMessage,
  getRun,
  isSettled,
  newIdempotencyKey,
  pollUntilSettled,
  type ReplayVerdict,
  traceEntry,
  verifyReplay,
} from './workflow';

const BASE_URL = import.meta.env.VITE_ANALYTICS_API_URL ?? '';
const API_KEY = import.meta.env.VITE_ANALYTICS_API_KEY ?? '';
const DEFAULT_PURPOSE = import.meta.env.VITE_ANALYTICS_PURPOSE ?? 'analytics';

export function GovernedWorkspace() {
  const [token, setToken] = useState('');
  const [purpose, setPurpose] = useState(DEFAULT_PURPOSE);
  const [question, setQuestion] = useState('');
  const [runId, setRunId] = useState('');
  const [response, setResponse] = useState<RunResponse | null>(null);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [replay, setReplay] = useState<ReplayVerdict | null>(null);
  const request = useRef<{ text: string; key: string } | null>(null);

  const config = (): GovernedConfig => ({ baseUrl: BASE_URL, token, purpose, apiKey: API_KEY || undefined });
  const note = (label: string, id?: string, detail?: string) =>
    setTrace((current) => [...current, traceEntry(label, id, detail)]);

  async function run(label: string, call: () => Promise<RunResponse>) {
    setBusy(true);
    setError('');
    setReplay(null);
    try {
      let latest = await call();
      setResponse(latest);
      note(`${label}: ${describeOutcome(latest.outcome)}`, latest.run_id);
      if (!isSettled(latest)) {
        latest = await pollUntilSettled(() => getRun(config(), latest.run_id));
        setResponse(latest);
        note(`Checked result: ${describeOutcome(latest.outcome)}`, latest.run_id);
      }
    } catch (failure) {
      setError(errorMessage(failure));
      note(`${label} failed`, undefined, failure instanceof Error ? failure.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  function submit() {
    const text = question.trim();
    if (text.length < 3 || busy) return;
    request.current = { text, key: newIdempotencyKey() };
    setTrace([]);
    void run('Submitted', () => analyze(config(), text, request.current!.key));
  }

  const current = response?.run_id;
  const actions = {
    busy,
    replay,
    onClarify: (code: string, id: string) => current && void run(`Clarified ${code}`, () => clarify(config(), current, code, id)),
    onDecide: (decision: 'approved' | 'rejected', fingerprint: string) =>
      current && void run(`Review ${decision}`, () => decideReview(config(), current, decision, fingerprint)),
    onRetry: submit,
    onReplay: async () => {
      if (!response) return;
      setBusy(true);
      try {
        // Read-only: re-fetch the same run (never starts a new one, whoever is signed in).
        const again = await getRun(config(), response.run_id);
        const verdict = verifyReplay(response, again);
        setReplay(verdict);
        note(`Replay: ${verdict.verified ? 'verified' : 'mismatch'}`, again.run_id);
      } catch (failure) {
        setError(errorMessage(failure));
      } finally {
        setBusy(false);
      }
    },
  };

  return (
    <div className="gv">
      <section className="gv-card" aria-label="Connection">
        <h2>Governed analysis</h2>
        <p>Answers come with their evidence: the data used, the claims made, and a trace of each step.</p>
        <div className="gv-form">
          <label>Access token<input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} /></label>
          <label>Purpose<input value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label>
        </div>
        <label className="gv-ask">Question
          <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
        </label>
        <div className="gv-actions">
          <button onClick={submit} disabled={busy || !token || question.trim().length < 3}>Ask</button>
        </div>
        <div className="gv-form">
          <label>Open a run (reviewers)<input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="run ID" /></label>
          <button disabled={busy || !token || !runId.trim()} onClick={() => void run('Opened run', () => getRun(config(), runId.trim()))}>Open</button>
        </div>
      </section>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {response && <OutcomeView response={response} actions={actions} />}
      <TracePanel trace={trace} />
    </div>
  );
}

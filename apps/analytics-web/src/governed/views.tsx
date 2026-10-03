import { useEffect, useRef } from 'react';
import type { VisualizationSpec } from 'vega-embed';

import type { AnswerOutcome, ClarifyOutcome, FailedOutcome, RefuseOutcome, ReviewOutcome, RunResponse, TraceEntry } from './types';
import { chartSpec, columnLabels, failureCopy, groundClaim, type ReplayVerdict, viewKind } from './workflow';

export interface OutcomeActions {
  busy: boolean;
  onClarify: (ambiguityCode: string, selectedId: string) => void;
  onDecide: (decision: 'approved' | 'rejected', planFingerprint: string) => void;
  onRetry: () => void;
  onReplay: () => void;
  replay: ReplayVerdict | null;
}

export function OutcomeView({ response, actions }: { response: RunResponse; actions: OutcomeActions }) {
  const outcome = response.outcome;
  switch (viewKind(response)) {
    case 'running':
      return (
        <section className="gv-card" role="status" aria-live="polite" data-view="running">
          <h2>Working on it</h2>
          <p>The run is executing. This page checks for the result automatically.</p>
        </section>
      );
    case 'answer':
      return <AnswerView outcome={outcome as AnswerOutcome} runId={response.run_id} actions={actions} />;
    case 'clarify':
      return <ClarifyView outcome={outcome as ClarifyOutcome} actions={actions} />;
    case 'review':
      return <ReviewView outcome={outcome as ReviewOutcome} actions={actions} />;
    case 'refuse':
      return <RefuseView outcome={outcome as RefuseOutcome} />;
    default:
      return <FailedView outcome={outcome as FailedOutcome} actions={actions} />;
  }
}

function AnswerView({ outcome, runId, actions }: { outcome: AnswerOutcome; runId: string; actions: OutcomeActions }) {
  const spec = chartSpec(outcome);
  const grounded = outcome.claims.map((claim) => groundClaim(claim, outcome.result, columnLabels(outcome)));
  return (
    <section className="gv-card" data-view="answer" aria-live="polite">
      <h2>Answer</h2>
      <p className="gv-answer">{outcome.answer}</p>
      {outcome.explanation_status === 'evidence_only' && (
        <p className="gv-note" data-testid="evidence-only">
          No narrative could be verified against the result, so only the evidence is shown.
        </p>
      )}
      {grounded.length > 0 && (
        <ul className="gv-claims" aria-label="Claims and their evidence">
          {grounded.map(({ claim, cites, grounded: ok, problems }, index) => (
            <li key={index} data-grounded={ok}>
              <span>{claim.text}</span>
              <span className={ok ? 'gv-badge ok' : 'gv-badge bad'}>{ok ? 'Verified in browser' : 'Not verified'}</span>
              <span className="gv-cites">
                {cites.map((cite) => (
                  <code key={cite.cite} title={cite.cite}>
                    {cite.label}
                    {cite.value !== undefined ? ` = ${cite.value}` : ''}
                  </code>
                ))}
              </span>
              {problems.length > 0 && <small className="gv-problems">{problems.join('; ')}</small>}
            </li>
          ))}
        </ul>
      )}
      {spec && <Chart spec={spec} />}
      {outcome.result && <ResultTableView result={outcome.result} />}
      <dl className="gv-evidence" aria-label="Evidence">
        <dt>Run</dt><dd><code>{runId}</code></dd>
        <dt>Contract</dt><dd>{outcome.evidence.semantic_contract_version ?? 'unknown'}</dd>
        <dt>Metrics</dt><dd>{outcome.evidence.metric_ids.join(', ') || 'none'}</dd>
        <dt>Dimensions</dt><dd>{outcome.evidence.dimension_ids.join(', ') || 'none'}</dd>
        <dt>Result fingerprint</dt><dd><code>{outcome.evidence.result_fingerprint ?? 'none'}</code></dd>
      </dl>
      <div className="gv-actions">
        <button onClick={actions.onReplay} disabled={actions.busy}>Replay and verify</button>
        {actions.replay && (
          <span role="status" className={actions.replay.verified ? 'gv-badge ok' : 'gv-badge bad'}>{actions.replay.message}</span>
        )}
      </div>
    </section>
  );
}

function ClarifyView({ outcome, actions }: { outcome: ClarifyOutcome; actions: OutcomeActions }) {
  return (
    <section className="gv-card" data-view="clarify">
      <h2>One thing to confirm</h2>
      {outcome.questions.map((question) => (
        <div key={question.id} className="gv-question">
          <p>{question.prompt}</p>
          <div className="gv-actions">
            {question.choices.map((choice) => (
              <button key={choice.id} disabled={actions.busy} onClick={() => actions.onClarify(question.id, choice.id)}>
                {choice.label}
              </button>
            ))}
            {question.choices.length === 0 && <small>No options are available; rephrase your question.</small>}
          </div>
        </div>
      ))}
    </section>
  );
}

function ReviewView({ outcome, actions }: { outcome: ReviewOutcome; actions: OutcomeActions }) {
  const fingerprint = outcome.plan_fingerprint;
  return (
    <section className="gv-card" data-view="review">
      <h2>Waiting for review</h2>
      <p>A person other than the requester must approve this plan before it runs.</p>
      <dl className="gv-evidence">
        <dt>Review</dt><dd><code>{outcome.review_id}</code></dd>
        <dt>Reason</dt><dd>{outcome.risk_reasons.join(', ')}</dd>
        <dt>Expires</dt><dd>{new Date(outcome.expires_at).toLocaleString()}</dd>
        <dt>Plan fingerprint</dt><dd><code>{fingerprint ?? 'unavailable'}</code></dd>
      </dl>
      <div className="gv-actions">
        <button disabled={actions.busy || !fingerprint || !outcome.allowed_actions.includes('approve')}
          onClick={() => fingerprint && actions.onDecide('approved', fingerprint)}>Approve</button>
        <button disabled={actions.busy || !fingerprint || !outcome.allowed_actions.includes('reject')}
          onClick={() => fingerprint && actions.onDecide('rejected', fingerprint)}>Reject</button>
      </div>
    </section>
  );
}

function RefuseView({ outcome }: { outcome: RefuseOutcome }) {
  return (
    <section className="gv-card gv-refuse" data-view="refuse" role="alert">
      <h2>Not answered</h2>
      <p>{outcome.explanation}</p>
      <small>Reason: {outcome.reason_code}</small>
      {outcome.remediation && <p>{outcome.remediation}</p>}
    </section>
  );
}

function FailedView({ outcome, actions }: { outcome: FailedOutcome; actions: OutcomeActions }) {
  return (
    <section className="gv-card gv-failed" data-view="failed" role="alert">
      <h2>{failureCopy(outcome.error_code)}</h2>
      <p>{outcome.message}</p>
      <small>Code: {outcome.error_code}</small>
      {outcome.retryable && <div className="gv-actions"><button onClick={actions.onRetry} disabled={actions.busy}>Try again</button></div>}
    </section>
  );
}

function ResultTableView({ result }: { result: NonNullable<AnswerOutcome['result']> }) {
  return (
    <div className="table-scroll">
      <table>
        <thead><tr>{result.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {result.rows.slice(0, 50).map((row, rowIndex) => (
            <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell === null ? '—' : String(cell)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Chart({ spec }: { spec: Record<string, unknown> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let done = false;
    let view: { finalize: () => void } | undefined;
    import('vega-embed').then(({ default: embed }) => {
      if (!ref.current || done) return;
      const width = Math.max(280, ref.current.clientWidth - 36);
      void embed(ref.current, { ...spec, width } as VisualizationSpec, { actions: false, renderer: 'svg' }).then((r) => {
        view = r.view;
      });
    });
    return () => { done = true; view?.finalize(); };
  }, [spec]);
  return <div ref={ref} className="chart" role="img" aria-label="Result chart" />;
}

export function TracePanel({ trace }: { trace: TraceEntry[] }) {
  return (
    <section className="gv-card" aria-label="Run trace" data-view="trace">
      <h2>Trace</h2>
      {trace.length === 0 ? (
        <p>Nothing has happened yet.</p>
      ) : (
        <ol className="gv-trace">
          {trace.map((entry, index) => (
            <li key={index}>
              <time dateTime={entry.at}>{new Date(entry.at).toLocaleTimeString()}</time>
              <span>{entry.label}</span>
              {entry.detail && <small>{entry.detail}</small>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

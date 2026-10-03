import {
  ArrowUp,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Code2,
  Database,
  History,
  LayoutDashboard,
  LoaderCircle,
  PanelLeftClose,
  Search,
  Table2,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { VisualizationSpec } from 'vega-embed';

import { getHealth, runQuery } from './api';
import { GovernedWorkspace } from './governed/GovernedWorkspace';
import type { AnalyticsQueryResponse, HealthResponse } from './types';

const EXAMPLES = [
  'Revenue trend by month',
  'Top 10 product categories by sales',
  'Average delivery time by customer state',
];

export function App() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [result, setResult] = useState<AnalyticsQueryResponse | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState<'workspace' | 'governed'>('workspace');

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  async function submit(nextQuery = query) {
    const normalized = nextQuery.trim();
    if (normalized.length < 3 || loading) return;
    setQuery(normalized);
    setLoading(true);
    setError('');
    try {
      const response = await runQuery(normalized);
      setResult(response);
      setHistory((current) => [normalized, ...current.filter((item) => item !== normalized)].slice(0, 6));
      if (response.status === 'failed') setError(response.error);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Query failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><BarChart3 size={18} /></div>
          <div><strong>Compass</strong><span>Analytics</span></div>
        </div>
        <nav aria-label="Analytics navigation">
          <button className={view === 'workspace' ? 'nav-item active' : 'nav-item'} title="Workspace" onClick={() => setView('workspace')}><LayoutDashboard size={17} />Workspace</button>
          <button className={view === 'governed' ? 'nav-item active' : 'nav-item'} title="Governed analysis" onClick={() => setView('governed')}><CheckCircle2 size={17} />Governed</button>
          <button className="nav-item" title="Query history"><History size={17} />History</button>
          <button className="nav-item" title="Data sources"><Database size={17} />Data sources</button>
        </nav>
        <div className="sidebar-bottom">
          <div className="source-state">
            <span className={health?.status === 'ready' ? 'status-dot ready' : 'status-dot'} />
            <div><strong>Commerce demo</strong><span>{health?.status ?? 'Checking API'}</span></div>
          </div>
          <button className="icon-button" title="Collapse sidebar"><PanelLeftClose size={17} /></button>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div><span className="eyebrow">Workspace</span><h1>Commerce overview</h1></div>
          <button className="dataset-button"><Database size={15} />Olist commerce<ChevronDown size={14} /></button>
        </header>

        {view === 'governed' ? <GovernedWorkspace /> : (<>
        <section className="query-band" aria-label="Ask a data question">
          <div className="query-input">
            <Search size={19} />
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
              aria-label="Data question"
              rows={1}
            />
            <button className="run-button" onClick={() => void submit()} disabled={loading} title="Run query">
              {loading ? <LoaderCircle className="spin" size={17} /> : <ArrowUp size={17} />}
            </button>
          </div>
          <div className="example-row">
            {EXAMPLES.map((example) => (
              <button key={example} onClick={() => void submit(example)}>{example}</button>
            ))}
          </div>
        </section>

        {error && <div className="error-banner"><CircleAlert size={17} /><span>{error}</span></div>}

        {result ? (
          <ResultWorkspace result={result} />
        ) : (
          <section className="empty-workspace">
            <BarChart3 size={28} />
            <h2>Ask your first question</h2>
            <p>Results, query evidence, and execution details will appear here.</p>
          </section>
        )}

        {history.length > 0 && (
          <section className="history-strip">
            <div className="section-heading"><History size={16} /><h2>Recent queries</h2></div>
            <div className="history-list">
              {history.map((item) => <button key={item} onClick={() => void submit(item)}>{item}</button>)}
            </div>
          </section>
        )}
        </>)}
      </main>
    </div>
  );
}

function ResultWorkspace({ result }: { result: AnalyticsQueryResponse }) {
  const numeric = firstNumericValue(result);
  return (
    <section className="results" aria-live="polite">
      <div className="result-meta">
        <div><CheckCircle2 size={16} /><span>Completed</span></div>
        <div><Clock3 size={15} />{result.execution_time_ms} ms</div>
        <div><Table2 size={15} />{result.row_count.toLocaleString()} rows</div>
      </div>

      <div className="metric-grid">
        <div className="metric"><span>Rows returned</span><strong>{result.row_count.toLocaleString()}</strong><small>{result.truncated ? 'Result capped' : 'Complete result'}</small></div>
        <div className="metric accent"><span>Primary value</span><strong>{numeric ?? 'Multiple'}</strong><small>{result.columns[0] ?? 'No columns'}</small></div>
        <div className="metric"><span>Dataset</span><strong>{result.dataset}</strong><small>Contract {result.contract_version}</small></div>
      </div>

      <div className="result-grid">
        <section className="panel chart-panel">
          <div className="panel-heading"><div><BarChart3 size={17} /><h2>Result view</h2></div></div>
          {result.chart_spec ? <ResultChart spec={result.chart_spec} /> : <SingleValue result={result} />}
        </section>
        <section className="panel table-panel">
          <div className="panel-heading"><div><Table2 size={17} /><h2>Data</h2></div><span>{result.row_count} rows</span></div>
          <ResultTable result={result} />
        </section>
      </div>

      <details className="sql-panel">
        <summary><span><Code2 size={16} />Generated SQL</span><ChevronDown size={15} /></summary>
        <pre>{result.sql}</pre>
      </details>
    </section>
  );
}

function ResultChart({ spec }: { spec: Record<string, unknown> }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let finalized = false;
    let view: { finalize: () => void } | undefined;
    import('vega-embed').then(({ default: embed }) => {
      if (!chartRef.current || finalized) return;
      const width = Math.max(280, chartRef.current.clientWidth - 36);
      void embed(chartRef.current, { ...spec, width } as VisualizationSpec, { actions: false, renderer: 'svg' })
        .then((result) => { view = result.view; });
    });
    return () => { finalized = true; view?.finalize(); };
  }, [spec]);
  return <div ref={chartRef} className="chart" />;
}

function SingleValue({ result }: { result: AnalyticsQueryResponse }) {
  return <div className="single-value"><strong>{firstNumericValue(result) ?? result.row_count}</strong><span>{result.columns[0] ?? 'Result'}</span></div>;
}

function ResultTable({ result }: { result: AnalyticsQueryResponse }) {
  return (
    <div className="table-scroll">
      <table>
        <thead><tr>{result.columns.map((column) => <th key={column}>{formatLabel(column)}</th>)}</tr></thead>
        <tbody>
          {result.rows.slice(0, 50).map((row, rowIndex) => (
            <tr key={rowIndex}>{result.columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function firstNumericValue(result: AnalyticsQueryResponse): string | null {
  const row = result.rows[0];
  if (!row) return null;
  const value = Object.values(row).find((item) => typeof item === 'number');
  return typeof value === 'number' ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value) : null;
}

function formatLabel(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatCell(value: unknown) { return typeof value === 'number' ? value.toLocaleString() : String(value ?? '—'); }

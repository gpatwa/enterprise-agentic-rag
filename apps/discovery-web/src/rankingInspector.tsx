import { ChevronDown, Eye, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import './rankingInspector.css';

export type RankingMode = 'lexical' | 'vector' | 'hybrid' | 'pre-rank' | 'full-rank';

type RankingStage = {
  name: string;
  source: string;
  timing_bucket: '<5 ms' | '5-20 ms' | '20-50 ms';
  status: 'used' | 'fallback';
};

type RankingCandidate = {
  rank: number;
  title: string;
  source: string;
  reason: string;
  score_bucket: string;
  evidence: string[];
};

type RankingSnapshot = {
  mode: RankingMode;
  version: string;
  fallback: boolean;
  metrics: { recall: string; mrr: string; coverage: string; diversity: string };
  stages: RankingStage[];
  candidates: RankingCandidate[];
};

const modeLabels: Record<RankingMode, string> = {
  lexical: 'Lexical',
  vector: 'Vector',
  hybrid: 'Hybrid',
  'pre-rank': 'Pre-rank',
  'full-rank': 'Full-rank',
};

const snapshots: Record<RankingMode, RankingSnapshot> = {
  lexical: {
    mode: 'lexical', version: 'lexical-v1', fallback: false,
    metrics: { recall: '0.78', mrr: '0.71', coverage: '92%', diversity: '0.64' },
    stages: [{ name: 'Eligibility', source: 'policy', timing_bucket: '<5 ms', status: 'used' }, { name: 'BM25 retrieval', source: 'catalog', timing_bucket: '5-20 ms', status: 'used' }],
    candidates: [
      { rank: 1, title: 'Skybound Studio', source: 'catalog', reason: 'title match', score_bucket: 'high', evidence: ['title-match', 'tenant-scoped'] },
      { rank: 2, title: 'Tiny Town Builders', source: 'catalog', reason: 'genre match', score_bucket: 'medium', evidence: ['genre-match', 'policy-cleared'] },
    ],
  },
  vector: {
    mode: 'vector', version: 'vector-v1', fallback: false,
    metrics: { recall: '0.81', mrr: '0.74', coverage: '89%', diversity: '0.71' },
    stages: [{ name: 'Eligibility', source: 'policy', timing_bucket: '<5 ms', status: 'used' }, { name: 'ANN retrieval', source: 'catalog', timing_bucket: '20-50 ms', status: 'used' }],
    candidates: [
      { rank: 1, title: 'Tiny Town Builders', source: 'similarity', reason: 'semantic match', score_bucket: 'high', evidence: ['similarity-match', 'tenant-scoped'] },
      { rank: 2, title: 'Skybound Studio', source: 'similarity', reason: 'related theme', score_bucket: 'medium', evidence: ['theme-match', 'policy-cleared'] },
    ],
  },
  hybrid: {
    mode: 'hybrid', version: 'hybrid-v1', fallback: false,
    metrics: { recall: '0.86', mrr: '0.82', coverage: '95%', diversity: '0.76' },
    stages: [{ name: 'Eligibility', source: 'policy', timing_bucket: '<5 ms', status: 'used' }, { name: 'BM25 + ANN', source: 'catalog', timing_bucket: '20-50 ms', status: 'used' }, { name: 'RRF fusion', source: 'fusion', timing_bucket: '5-20 ms', status: 'used' }],
    candidates: [
      { rank: 1, title: 'Skybound Studio', source: 'hybrid', reason: 'fused lexical and semantic match', score_bucket: 'high', evidence: ['fused-signal', 'tenant-scoped'] },
      { rank: 2, title: 'Tiny Town Builders', source: 'hybrid', reason: 'fused genre and theme match', score_bucket: 'medium', evidence: ['fused-signal', 'policy-cleared'] },
    ],
  },
  'pre-rank': {
    mode: 'pre-rank', version: 'pre-rank-v1', fallback: false,
    metrics: { recall: '0.86', mrr: '0.84', coverage: '95%', diversity: '0.77' },
    stages: [{ name: 'Eligibility', source: 'policy', timing_bucket: '<5 ms', status: 'used' }, { name: 'Candidate fusion', source: 'fusion', timing_bucket: '5-20 ms', status: 'used' }, { name: 'Feature pre-rank', source: 'ranker', timing_bucket: '5-20 ms', status: 'used' }],
    candidates: [
      { rank: 1, title: 'Skybound Studio', source: 'personalized', reason: 'quality and preference signals', score_bucket: 'high', evidence: ['quality-signal', 'diversity-cap'] },
      { rank: 2, title: 'Reef Runners', source: 'trending', reason: 'freshness and quality signals', score_bucket: 'medium', evidence: ['freshness-signal', 'policy-cleared'] },
    ],
  },
  'full-rank': {
    mode: 'full-rank', version: 'full-rank-v1', fallback: true,
    metrics: { recall: '0.84', mrr: '0.80', coverage: '94%', diversity: '0.79' },
    stages: [{ name: 'Eligibility', source: 'policy', timing_bucket: '<5 ms', status: 'used' }, { name: 'Candidate fusion', source: 'fusion', timing_bucket: '5-20 ms', status: 'used' }, { name: 'Learned rank', source: 'ranker', timing_bucket: '20-50 ms', status: 'fallback' }],
    candidates: [
      { rank: 1, title: 'Skybound Studio', source: 'safe fallback', reason: 'ranker unavailable; safe ordering', score_bucket: 'high', evidence: ['fallback-order', 'policy-cleared'] },
      { rank: 2, title: 'Reef Runners', source: 'safe fallback', reason: 'ranker unavailable; safe ordering', score_bucket: 'medium', evidence: ['fallback-order', 'diversity-cap'] },
    ],
  },
};

export function RankingInspector() {
  const [mode, setMode] = useState<RankingMode>('hybrid');
  const snapshot = useMemo(() => snapshots[mode], [mode]);

  return <section className="ranking-inspector" aria-label="Ranking inspector">
    <div className="inspector-heading">
      <div><p className="eyebrow">OPERATOR VIEW</p><h2>Ranking inspector</h2><p>Compare governed stages using redacted local evidence.</p></div>
      <span className="home-status"><Eye size={15} aria-hidden="true" /> Redacted trace</span>
    </div>
    <div className="inspector-controls">
      <label htmlFor="ranking-mode">Ranking mode</label>
      <div className="select-wrap"><select id="ranking-mode" value={mode} onChange={(event) => setMode(event.target.value as RankingMode)}>{Object.entries(modeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={15} aria-hidden="true" /></div>
      <span className="inspector-version">{snapshot.version}</span>
      <span className={snapshot.fallback ? 'fallback-badge' : 'active-badge'}>{snapshot.fallback ? 'Fallback active' : 'Primary path'}</span>
    </div>
    <div className="metric-grid" aria-label="Evaluation metrics">{Object.entries(snapshot.metrics).map(([name, value]) => <div className="metric" key={name}><span>{name}</span><strong>{value}</strong></div>)}</div>
    <div className="inspector-grid">
      <div><h3>Stage trace</h3><div className="stage-list">{snapshot.stages.map((stage) => <div className="stage-row" key={stage.name}><span className={stage.status === 'fallback' ? 'stage-dot fallback' : 'stage-dot'} aria-hidden="true" /><strong>{stage.name}</strong><span>{stage.source}</span><span>{stage.timing_bucket}</span><span className={stage.status === 'fallback' ? 'stage-status fallback-text' : 'stage-status'}>{stage.status}</span></div>)}</div></div>
      <div><h3>Candidate evidence</h3><div className="candidate-list">{snapshot.candidates.map((candidate) => <div className="candidate-row" key={candidate.title}><span className="candidate-rank">{String(candidate.rank).padStart(2, '0')}</span><div><strong>{candidate.title}</strong><p>{candidate.reason}</p><div className="evidence-list">{candidate.evidence.map((item) => <span key={item}>{item}</span>)}</div></div><span className="score-bucket">{candidate.score_bucket}</span></div>)}</div></div>
    </div>
    <p className="inspector-note"><ShieldCheck size={15} aria-hidden="true" /> Private features, raw queries, vectors, identities, and provider payloads are withheld.</p>
  </section>;
}

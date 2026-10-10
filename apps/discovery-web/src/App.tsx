import { AlertCircle, ChevronLeft, ChevronRight, Compass, Search, SlidersHorizontal, Sparkles } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { createDiscoveryClient, type SearchRequest, type SearchResponse } from './api/client';
import { HomeDetailsExperience } from './homeDetails';
import './styles.css';

const PAGE_SIZE = 6;
const demoResponse: SearchResponse = {
  schema_version: 'imd-search-v1', request_id: 'local-demo', total_matches: 3, fallback: true, error: null,
  results: [
    { experience_id: 'skybound-studio', title: 'Skybound Studio', rank: 1, score: 0.96, reason_codes: ['lexical_match'], evidence: ['title'] },
    { experience_id: 'tiny-town', title: 'Tiny Town Builders', rank: 2, score: 0.82, reason_codes: ['lexical_match'], evidence: ['title', 'genre'] },
    { experience_id: 'reef-runners', title: 'Reef Runners', rank: 3, score: 0.67, reason_codes: ['safe_catalog_fallback'], evidence: ['genre'] },
  ],
};
const client = createDiscoveryClient(import.meta.env.VITE_DISCOVERY_API_URL ?? '');

function redactedReason(reasonCodes: string[]) { return reasonCodes.map((reason) => reason.replaceAll('_', ' ')).join(' · '); }

export default function App() {
  const [query, setQuery] = useState('cozy building games');
  const [locale, setLocale] = useState('en-US');
  const [device, setDevice] = useState('web');
  const [ageBand, setAgeBand] = useState('teen');
  const [page, setPage] = useState(1);
  const [response, setResponse] = useState<SearchResponse>(demoResponse);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pageCount = Math.max(1, Math.ceil(response.total_matches / PAGE_SIZE));
  const request = useMemo<SearchRequest>(() => ({
    query: query.trim(), context: { tenant_id: 'demo', principal_id: 'synthetic-user-1', request_id: crypto.randomUUID(), locale, device, age_band: ageBand, purpose: 'search' }, page, page_size: PAGE_SIZE,
  }), [ageBand, device, locale, page, query]);

  async function runSearch(nextPage = 1) {
    setLoading(true); setError(null);
    try { const next = await client.search({ ...request, page: nextPage }); setResponse(next); setPage(nextPage); }
    catch { setError('Search is unavailable right now. Try again in a moment.'); }
    finally { setLoading(false); }
  }
  function handleQueryKeyDown(event: KeyboardEvent<HTMLInputElement>) { if (event.key === 'Enter') void runSearch(); if (event.key === 'Escape') setQuery(''); }
  const canGoBack = page > 1 && !loading;
  const canGoForward = page < pageCount && !loading;

  return <main className="shell">
    <header className="topbar"><div className="brand"><Compass size={22} /><span>COMPASS / DISCOVERY</span></div><span className="status"><span className="dot" /> LOCAL DEMO</span></header>
    <section className="intro"><p className="eyebrow">IMMERSIVE DISCOVERY</p><h1>Find your next world.</h1><p className="lede">A governed search surface for experiences, creators, and communities.</p></section>
    <HomeDetailsExperience />
    <section className="search-panel" aria-label="Discovery search">
      <div className="search-row"><Search size={21} aria-hidden="true" /><label className="sr-only" htmlFor="experience-search">Search experiences</label><input id="experience-search" autoComplete="off" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleQueryKeyDown} placeholder="Search by name, genre, or feeling" /><button type="button" onClick={() => void runSearch()} disabled={loading}>{loading ? 'Searching' : 'Explore'}</button></div>
      <div className="filter-row" aria-label="Search filters"><div className="filter-label"><SlidersHorizontal size={15} aria-hidden="true" /><span>Filters</span></div><label>Locale<select aria-label="Locale" value={locale} onChange={(event) => { setLocale(event.target.value); setPage(1); }}><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="es-ES">Spanish</option></select></label><label>Device<select aria-label="Device" value={device} onChange={(event) => { setDevice(event.target.value); setPage(1); }}><option value="web">Web</option><option value="mobile">Mobile</option><option value="tablet">Tablet</option></select></label><label>Age<select aria-label="Age" value={ageBand} onChange={(event) => { setAgeBand(event.target.value); setPage(1); }}><option value="child">Child</option><option value="teen">Teen</option><option value="adult">Adult</option></select></label></div>
      <div className="chips"><span>Personalized when permitted</span><span>Policy-aware results</span><span>Evidence-backed ranking</span></div>
    </section>
    {error && <div className="notice error" role="alert"><AlertCircle size={17} aria-hidden="true" /><span>{error}</span><button type="button" onClick={() => void runSearch(page)}>Retry</button></div>}
    <section className="results" aria-live="polite" aria-busy={loading}>
      <div className="results-heading"><div><p className="eyebrow">{response.fallback ? 'SAFE CATALOG' : 'SEARCH RESULTS'}</p><h2>{loading ? 'Finding worlds...' : `${response.total_matches} ${response.total_matches === 1 ? 'world' : 'worlds'} to explore`}</h2></div><span className="trace"><Sparkles size={15} aria-hidden="true" /> {response.fallback ? 'Safe catalog fallback' : 'Ranked locally'}</span></div>
      {loading ? <div className="state-panel"><span className="loader" aria-hidden="true" /><p>Searching the local catalog</p></div> : response.results.length === 0 ? <div className="state-panel"><Search size={25} aria-hidden="true" /><p>No worlds matched that search.</p><small>Try a broader name, genre, or feeling.</small></div> : <div className="result-grid">{response.results.map((result) => <article className="result" key={result.experience_id}><div className="result-art"><span>{String(result.rank).padStart(2, '0')}</span></div><div className="result-copy"><h3>{result.title}</h3><p>{redactedReason(result.reason_codes)}</p><small>{Math.round(result.score * 100)}% relevance</small></div></article>)}</div>}
      <nav className="pagination" aria-label="Search result pages"><button type="button" aria-label="Previous page" onClick={() => void runSearch(page - 1)} disabled={!canGoBack}><ChevronLeft size={18} aria-hidden="true" /></button><span>Page {page} of {pageCount}</span><button type="button" aria-label="Next page" onClick={() => void runSearch(page + 1)} disabled={!canGoForward}><ChevronRight size={18} aria-hidden="true" /></button></nav>
    </section>
  </main>;
}

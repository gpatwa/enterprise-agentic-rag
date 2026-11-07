import { AlertCircle, ChevronLeft, ChevronRight, Package, Search } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { DiscoveryClient, ProductSearchResponse } from './api/client';

const PAGE_SIZE = 10;
const LOCALES = [['', 'All locales'], ['us', 'US'], ['es', 'Spain'], ['jp', 'Japan']] as const;

type Attempt = { text: string; page: number; locale: string };

/** Keyword product search over the ESCI subset. Nothing is fetched until the user searches. */
export function ProductSearch({ client }: { client: Pick<DiscoveryClient, 'searchProducts'> }) {
  const [query, setQuery] = useState('');
  const [locale, setLocale] = useState('');
  const [page, setPage] = useState(1);
  const [response, setResponse] = useState<ProductSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  // The search that was actually sent. Paging, a locale change and Retry repeat this one, not whatever has since been typed.
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const latest = useRef(0);
  const resultsRef = useRef<HTMLDivElement>(null);
  const focusResults = useRef(false);

  async function run(next: Attempt, { moveFocus = false } = {}) {
    // A slower, older request must not overwrite the answer to a newer one.
    const id = ++latest.current;
    focusResults.current = moveFocus;
    setAttempt(next); setLoading(true); setFailed(false);
    try {
      const body = await client.searchProducts({ query: next.text, page: next.page, page_size: PAGE_SIZE, ...(next.locale ? { locale: next.locale } : {}) });
      if (id !== latest.current) return;
      setResponse(body); setPage(next.page);
    } catch {
      if (id !== latest.current) return;
      focusResults.current = false; setFailed(true);
    } finally { if (id === latest.current) setLoading(false); }
  }
  // After paging, put keyboard focus on the new results; the pager button the user pressed may now be disabled.
  useEffect(() => {
    if (focusResults.current && response) { focusResults.current = false; resultsRef.current?.focus(); }
  }, [response]);

  function submit() { const text = query.trim(); if (text) void run({ text, page: 1, locale }); }
  function goToPage(nextPage: number) { if (attempt) void run({ ...attempt, page: nextPage }, { moveFocus: true }); }
  function changeLocale(next: string) {
    setLocale(next);
    if (response && attempt) void run({ text: attempt.text, page: 1, locale: next });
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) { if (event.key === 'Enter') submit(); if (event.key === 'Escape') setQuery(''); }

  const total = response?.total_matches ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const message = failed ? 'Product search is unavailable right now. Try again in a moment.' : response?.error?.message ?? null;
  const showResults = response !== null && !message;

  return <section className="product-search" aria-label="Product search">
    <p className="eyebrow">PRODUCT CATALOG</p>
    <h2>Search products</h2>
    <div className="search-panel">
      <div className="search-row"><Package size={21} aria-hidden="true" /><label className="sr-only" htmlFor="product-query">Search products</label><input id="product-query" autoComplete="off" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} placeholder="Try a product, brand, or color" /><button type="button" onClick={submit} disabled={loading || !query.trim()}>{loading ? 'Searching' : 'Search'}</button></div>
      <div className="filter-row"><label>Product locale<select aria-label="Product locale" value={locale} onChange={(event) => changeLocale(event.target.value)}>{LOCALES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
    </div>
    {message && <div className="notice error" role="alert"><AlertCircle size={17} aria-hidden="true" /><span>{message}</span><button type="button" onClick={() => attempt && void run(attempt)}>Retry</button></div>}
    {/* Always mounted, so a screen reader hears each change; it holds only the short summary, never the result list. */}
    <div className="product-status" role="status" aria-live="polite">
      {loading ? <p className="eyebrow">Searching products…</p> : showResults && <>
        <p className="eyebrow">{total.toLocaleString()} {total === 1 ? 'product' : 'products'}</p>
        {response.match === 'any' && total > 0 && <p className="product-meta">No product matched every word, so these match some of them.</p>}
      </>}
    </div>
    {showResults && <div ref={resultsRef} role="region" aria-label="Product results" aria-busy={loading} tabIndex={-1}>
      {response.results.length === 0 ? <div className="state-panel"><Search size={25} aria-hidden="true" /><p>No products matched that search.</p><small>Try fewer or different words.</small></div> : <ol className="product-list">{response.results.map((item) => <li className="product" key={item.product_id}><span className="product-rank" aria-hidden="true">{String(item.rank).padStart(2, '0')}</span><div><h3>{item.title}</h3>{(item.brand || item.color) && <p className="product-meta">{[item.brand, item.color].filter(Boolean).join(' · ')}</p>}{item.snippet && <p className="product-snippet">{item.snippet}</p>}</div></li>)}</ol>}
      <nav className="pagination" aria-label="Product result pages"><button type="button" aria-label="Previous products page" onClick={() => goToPage(page - 1)} disabled={page <= 1 || loading}><ChevronLeft size={18} aria-hidden="true" /></button><span>Page {page} of {pageCount}</span><button type="button" aria-label="Next products page" onClick={() => goToPage(page + 1)} disabled={page >= pageCount || loading}><ChevronRight size={18} aria-hidden="true" /></button></nav>
    </div>}
  </section>;
}

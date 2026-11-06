import { AlertCircle, ChevronLeft, ChevronRight, Package, Search } from 'lucide-react';
import { useState, type KeyboardEvent } from 'react';
import type { DiscoveryClient, ProductSearchResponse } from './api/client';

const PAGE_SIZE = 10;
const LOCALES = [['', 'All locales'], ['us', 'US'], ['es', 'Spain'], ['jp', 'Japan']] as const;

/** Keyword product search over the ESCI subset. Nothing is fetched until the user searches. */
export function ProductSearch({ client }: { client: Pick<DiscoveryClient, 'searchProducts'> }) {
  const [query, setQuery] = useState('');
  const [locale, setLocale] = useState('');
  const [page, setPage] = useState(1);
  const [response, setResponse] = useState<ProductSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function run(nextPage = 1, nextLocale = locale) {
    const text = query.trim();
    if (!text) return;
    setLoading(true); setFailed(false);
    try {
      const next = await client.searchProducts({ query: text, page: nextPage, page_size: PAGE_SIZE, ...(nextLocale ? { locale: nextLocale } : {}) });
      setResponse(next); setPage(nextPage);
    } catch { setFailed(true); }
    finally { setLoading(false); }
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) { if (event.key === 'Enter') void run(); if (event.key === 'Escape') setQuery(''); }

  const total = response?.total_matches ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const message = failed ? 'Product search is unavailable right now. Try again in a moment.' : response?.error?.message ?? null;

  return <section className="product-search" aria-label="Product search">
    <p className="eyebrow">PRODUCT CATALOG</p>
    <h2>Search products</h2>
    <div className="search-panel">
      <div className="search-row"><Package size={21} aria-hidden="true" /><label className="sr-only" htmlFor="product-query">Search products</label><input id="product-query" autoComplete="off" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} placeholder="Try a product, brand, or color" /><button type="button" onClick={() => void run()} disabled={loading || !query.trim()}>{loading ? 'Searching' : 'Search'}</button></div>
      <div className="filter-row"><label>Product locale<select aria-label="Product locale" value={locale} onChange={(event) => { setLocale(event.target.value); if (response) void run(1, event.target.value); }}>{LOCALES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
    </div>
    {message && <div className="notice error" role="alert"><AlertCircle size={17} aria-hidden="true" /><span>{message}</span><button type="button" onClick={() => void run(page)}>Retry</button></div>}
    {response && !message && <div aria-live="polite" aria-busy={loading}>
      <p className="eyebrow">{total.toLocaleString()} {total === 1 ? 'product' : 'products'}</p>
      {response.results.length === 0 ? <div className="state-panel"><Search size={25} aria-hidden="true" /><p>No products matched that search.</p><small>Try fewer or different words.</small></div> : <ol className="product-list">{response.results.map((item) => <li className="product" key={item.product_id}><span className="product-rank" aria-hidden="true">{String(item.rank).padStart(2, '0')}</span><div><h3>{item.title}</h3>{(item.brand || item.color) && <p className="product-meta">{[item.brand, item.color].filter(Boolean).join(' · ')}</p>}{item.snippet && <p className="product-snippet">{item.snippet}</p>}</div></li>)}</ol>}
      <nav className="pagination" aria-label="Product result pages"><button type="button" aria-label="Previous products page" onClick={() => void run(page - 1)} disabled={page <= 1 || loading}><ChevronLeft size={18} aria-hidden="true" /></button><span>Page {page} of {pageCount}</span><button type="button" aria-label="Next products page" onClick={() => void run(page + 1)} disabled={page >= pageCount || loading}><ChevronRight size={18} aria-hidden="true" /></button></nav>
    </div>}
  </section>;
}

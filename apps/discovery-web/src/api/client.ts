import type { TokenSource } from './auth';
import { DiscoveryApiError } from './errors';

export type DiscoveryContext = {
  tenant_id: string;
  principal_id: string;
  request_id: string;
  locale: string;
  device: string;
  age: number;
  purpose: 'search';
};

export type SearchRequest = {
  query: string;
  context: DiscoveryContext;
  page?: number;
  page_size?: number;
  blocked_ids?: string[];
};

export type SearchResult = {
  experience_id: string;
  title: string;
  rank: number;
  score: number;
  reason_codes: string[];
  evidence: string[];
};

export type SearchResponse = {
  schema_version: string;
  request_id: string;
  results: SearchResult[];
  total_matches: number;
  fallback: boolean;
  error: { code: string; message: string } | null;
};

export type ProductSearchRequest = { query: string; locale?: string; page?: number; page_size?: number };

export type ProductResult = { product_id: string; title: string; brand: string; color: string; snippet: string; rank: number; score: number };

export type ProductSearchResponse = {
  schema_version: string;
  results: ProductResult[];
  total_matches: number;
  page: number;
  page_size: number;
  match: 'all' | 'any';
  error: { code: string; message: string } | null;
};

export type DiscoveryClient = {
  search(request: SearchRequest): Promise<SearchResponse>;
  searchProducts(request: ProductSearchRequest): Promise<ProductSearchResponse>;
};

export function createDiscoveryClient(baseUrl = '', getToken?: TokenSource): DiscoveryClient {
  const base = { 'content-type': 'application/json' };
  // Without a token source nothing is awaited, so fetch is still called synchronously.
  function headers(forceRefresh = false): Record<string, string> | Promise<Record<string, string>> {
    if (!getToken) return base;
    return getToken(forceRefresh ? { forceRefresh: true } : undefined).then((token) => (token ? { ...base, authorization: `Bearer ${token}` } : base));
  }
  const send = (path: string, body: unknown, resolved: Record<string, string>) =>
    fetch(`${baseUrl}${path}`, { method: 'POST', headers: resolved, body: JSON.stringify(body) });

  /** POST; on a 401 take one silent token refresh and retry the request once. A 403 is never retried. */
  async function post<T>(path: string, body: unknown, label: string): Promise<T> {
    const pending = headers();
    let response = await send(path, body, pending instanceof Promise ? await pending : pending);
    if (response.status === 401 && getToken) response = await send(path, body, await headers(true));
    if (!response.ok) throw new DiscoveryApiError(`${label} failed with status ${response.status}`, response.status);
    return (await response.json()) as T;
  }
  return {
    search: (request) => post<SearchResponse>('/api/discovery/v1/search', request, 'Discovery search'),
    searchProducts: (request) => post<ProductSearchResponse>('/api/discovery/v1/products/search', request, 'Product search'),
  };
}

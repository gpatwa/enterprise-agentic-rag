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

export function createDiscoveryClient(baseUrl = ''): DiscoveryClient {
  return {
    async search(request) {
      const response = await fetch(`${baseUrl}/api/discovery/v1/search`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        throw new Error(`Discovery search failed with status ${response.status}`);
      }
      return (await response.json()) as SearchResponse;
    },
    async searchProducts(request) {
      const response = await fetch(`${baseUrl}/api/discovery/v1/products/search`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        throw new Error(`Product search failed with status ${response.status}`);
      }
      return (await response.json()) as ProductSearchResponse;
    },
  };
}

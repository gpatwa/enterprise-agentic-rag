export type DiscoveryContext = {
  tenant_id: string;
  principal_id: string;
  request_id: string;
  locale: string;
  device: string;
  age_band: string;
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

export type DiscoveryClient = {
  search(request: SearchRequest): Promise<SearchResponse>;
};

export function createDiscoveryClient(baseUrl = ''): DiscoveryClient {
  return {
    async search(request) {
      const response = await fetch(`${baseUrl}/api/discovery/search`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        throw new Error(`Discovery search failed with status ${response.status}`);
      }
      return (await response.json()) as SearchResponse;
    },
  };
}

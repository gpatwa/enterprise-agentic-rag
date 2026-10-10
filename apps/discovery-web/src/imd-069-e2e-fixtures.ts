import type { SearchResponse } from './api/client';
import { demoHomeResponse, noHistoryHomeResponse, type HomeResponse } from './homeDetails';

export const journeySearchResponses: Record<string, SearchResponse> = {
  exact: {
    schema_version: 'imd-search-v1', request_id: 'imd-069-exact', total_matches: 1, fallback: false, error: null,
    results: [{ experience_id: 'skybound-studio', title: 'Skybound Studio', rank: 1, score: 0.96, reason_codes: ['exact_id_match'], evidence: ['exact-title', 'tenant-scoped'] }],
  },
  natural: {
    schema_version: 'imd-search-v1', request_id: 'imd-069-natural', total_matches: 2, fallback: false, error: null,
    results: [
      { experience_id: 'skybound-studio', title: 'Skybound Studio', rank: 1, score: 0.96, reason_codes: ['lexical_match', 'genre_match'], evidence: ['title', 'genre'] },
      { experience_id: 'tiny-town', title: 'Tiny Town Builders', rank: 2, score: 0.82, reason_codes: ['semantic_match'], evidence: ['theme'] },
    ],
  },
  noResult: { schema_version: 'imd-search-v1', request_id: 'imd-069-empty', total_matches: 0, fallback: false, error: null, results: [] },
  safeFallback: {
    schema_version: 'imd-search-v1', request_id: 'imd-069-fallback', total_matches: 1, fallback: true, error: null,
    results: [{ experience_id: 'reef-runners', title: 'Reef Runners', rank: 1, score: 0.67, reason_codes: ['safe_catalog_fallback'], evidence: ['policy-cleared'] }],
  },
};

export const safeHomeResponse: HomeResponse = noHistoryHomeResponse;
export const personalizedHomeResponse: HomeResponse = demoHomeResponse;

export const forbiddenResultTitles = ['Private Studio', 'Unsafe Combat Test', 'Other Tenant World'];


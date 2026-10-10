import { describe, expect, it, vi } from 'vitest';
import { createDiscoveryClient, type SearchRequest } from './client';

const request: SearchRequest = {
  query: 'cozy building games',
  context: {
    tenant_id: 'demo',
    principal_id: 'synthetic-user-1',
    request_id: 'request-1',
    locale: 'en-US',
    device: 'web',
    age_band: 'teen',
    purpose: 'search',
  },
};

describe('discovery client', () => {
  it('sends the typed local search request', async () => {
    const response = { schema_version: 'imd-search-v1', request_id: 'request-1', results: [], total_matches: 0, fallback: false, error: null };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await createDiscoveryClient('http://localhost:8000').search(request);

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/api/discovery/search', expect.objectContaining({ method: 'POST', body: JSON.stringify(request) }));
  });

  it('raises a typed boundary error for non-success responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));

    await expect(createDiscoveryClient().search(request)).rejects.toThrow('status 503');
  });
});

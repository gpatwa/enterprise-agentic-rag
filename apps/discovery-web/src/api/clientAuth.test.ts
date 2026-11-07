import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDiscoveryClient, type SearchRequest } from './client';
import { AuthRequiredError, authFailureOf, DiscoveryApiError } from './errors';

const search: SearchRequest = { query: 'a', context: { tenant_id: 't', principal_id: 'p', request_id: 'r', locale: 'en-US', device: 'web', age: 16, purpose: 'search' } };
const okBody = JSON.stringify({ results: [] });
const respond = (...statuses: number[]) => {
  const queue = [...statuses];
  return vi.fn().mockImplementation(async () => new Response(queue.length > 1 ? '' : queue[0] === 200 ? okBody : '', { status: queue.shift() }));
};
const calls: Array<[string, (client: ReturnType<typeof createDiscoveryClient>) => Promise<unknown>]> = [
  ['experience search', (client) => client.search(search)],
  ['product search', (client) => client.searchProducts({ query: 'a' })],
];

afterEach(() => vi.unstubAllGlobals());

describe.each(calls)('%s: auth failures', (_name, call) => {
  it('on a 401 takes exactly one forced silent refresh and retries once with the new token', async () => {
    const fetchMock = respond(401, 200);
    vi.stubGlobal('fetch', fetchMock);
    const getToken = vi.fn().mockResolvedValueOnce('old-token').mockResolvedValueOnce('new-token');
    await call(createDiscoveryClient('', getToken));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getToken).toHaveBeenNthCalledWith(1, undefined);
    expect(getToken).toHaveBeenNthCalledWith(2, { forceRefresh: true });
    expect(fetchMock.mock.calls[0][1].headers.authorization).toBe('Bearer old-token');
    expect(fetchMock.mock.calls[1][1].headers.authorization).toBe('Bearer new-token');
  });

  it('gives up after one retry and raises a typed 401', async () => {
    const fetchMock = respond(401, 401, 401);
    vi.stubGlobal('fetch', fetchMock);
    const getToken = vi.fn().mockResolvedValue('t');
    const error = await call(createDiscoveryClient('', getToken)).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(DiscoveryApiError);
    expect(error).toMatchObject({ status: 401 });
    expect(authFailureOf(error)).toBe('expired');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getToken).toHaveBeenCalledTimes(2);
  });

  it('stops without a retry when the silent refresh itself needs the person', async () => {
    const fetchMock = respond(401, 200);
    vi.stubGlobal('fetch', fetchMock);
    const getToken = vi.fn().mockResolvedValueOnce('t').mockRejectedValueOnce(new AuthRequiredError('signin_required'));
    const error = await call(createDiscoveryClient('', getToken)).catch((caught: unknown) => caught);
    expect(authFailureOf(error)).toBe('expired');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('on a 403 goes straight to no-access: no refresh, no retry', async () => {
    const fetchMock = respond(403, 200);
    vi.stubGlobal('fetch', fetchMock);
    const getToken = vi.fn().mockResolvedValue('t');
    const error = await call(createDiscoveryClient('', getToken)).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 403 });
    expect(authFailureOf(error)).toBe('no-access');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getToken).toHaveBeenCalledTimes(1);
  });

  it('does not treat other failures as auth failures and does not retry them', async () => {
    const fetchMock = respond(503, 200);
    vi.stubGlobal('fetch', fetchMock);
    const error = await call(createDiscoveryClient('', vi.fn().mockResolvedValue('t'))).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 503 });
    expect(authFailureOf(error)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('with no token source calls fetch synchronously, never retries a 401 and makes no extra calls', async () => {
    const fetchMock = respond(401, 200);
    vi.stubGlobal('fetch', fetchMock);
    const pending = call(createDiscoveryClient(''));
    expect(fetchMock).toHaveBeenCalledTimes(1); // before any await: the unauthenticated path is unchanged
    const error = await pending.catch((caught: unknown) => caught);
    expect(authFailureOf(error)).toBe('expired');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('authFailureOf', () => {
  it('maps only auth errors', () => {
    expect(authFailureOf(new AuthRequiredError('no_access'))).toBe('no-access');
    for (const reason of ['signin_required', 'redirect_error', 'interaction_in_progress'] as const) expect(authFailureOf(new AuthRequiredError(reason))).toBe('expired');
    expect(authFailureOf(new Error('Discovery search failed with status 401'))).toBeNull();
    expect(authFailureOf(new TypeError('offline'))).toBeNull();
  });
});

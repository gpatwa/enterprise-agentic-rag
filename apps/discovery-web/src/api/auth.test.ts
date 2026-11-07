import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { authConfigFromEnv, redirectUriFor } from './auth';
import { createDiscoveryClient } from './client';

describe('auth config', () => {
  it('is off unless all three settings are present', () => {
    expect(authConfigFromEnv({})).toBeNull();
    expect(authConfigFromEnv({ VITE_ENTRA_CLIENT_ID: 'c', VITE_ENTRA_TENANT_ID: 't' })).toBeNull();
    expect(authConfigFromEnv({ VITE_ENTRA_CLIENT_ID: ' c ', VITE_ENTRA_TENANT_ID: 't', VITE_ENTRA_API_SCOPE: 'api://x/user' })).toEqual({ clientId: 'c', tenantId: 't', scope: 'api://x/user' });
  });
});

describe('client token header', () => {
  const ok = () => vi.fn().mockImplementation(async () => new Response(JSON.stringify({ results: [] }), { status: 200 }));

  it('sends a bearer token on both routes when a token source is given', async () => {
    const fetchMock = ok();
    vi.stubGlobal('fetch', fetchMock);
    const client = createDiscoveryClient('', async () => 'tok-1');
    await client.searchProducts({ query: 'a' });
    await client.search({ query: 'a', context: { tenant_id: 't', principal_id: 'p', request_id: 'r', locale: 'en-US', device: 'web', age: 16, purpose: 'search' } });
    for (const call of fetchMock.mock.calls) expect(call[1].headers).toEqual({ 'content-type': 'application/json', authorization: 'Bearer tok-1' });
  });

  it('sends no authorization header without a token', async () => {
    const fetchMock = ok();
    vi.stubGlobal('fetch', fetchMock);
    await createDiscoveryClient('').searchProducts({ query: 'a' });
    await createDiscoveryClient('', async () => null).searchProducts({ query: 'a' });
    for (const call of fetchMock.mock.calls) expect(call[1].headers).toEqual({ 'content-type': 'application/json' });
  });

  it('asks for a fresh token on every request', async () => {
    vi.stubGlobal('fetch', ok());
    const source = vi.fn().mockResolvedValue('t');
    const client = createDiscoveryClient('', source);
    await client.searchProducts({ query: 'a' });
    await client.searchProducts({ query: 'b' });
    expect(source).toHaveBeenCalledTimes(2);
  });
});

describe('redirect URI contract with Terraform', () => {
  it('sends the origin with a trailing slash', () => {
    expect(redirectUriFor('https://web.example.test')).toBe('https://web.example.test/');
  });

  it('matches the SPA redirect registered in Terraform, which also ends in a slash', () => {
    const terraform = readFileSync(resolve(process.cwd(), '../../infra/terraform/azure-discovery-pilot/resources.tf'), 'utf8');
    const registered = terraform.match(/single_page_application\s*\{\s*redirect_uris\s*=\s*\["https:\/\/\$\{local\.web_fqdn\}([^"]*)"\]/);
    expect(registered).not.toBeNull();
    expect(registered![1]).toBe('/');
    expect(redirectUriFor('https://x.test')).toBe(`https://x.test${registered![1]}`);
  });
});

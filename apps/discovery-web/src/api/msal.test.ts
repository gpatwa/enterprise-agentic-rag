import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMsalAuth, isMsalSilentFrame, REDIRECT_FLAG, sessionLoginHint, type AuthConfig, type MsalApp } from './auth';
import { AuthRequiredError } from './errors';

const config: AuthConfig = { clientId: 'client-id', tenantId: 'tenant-id', scope: 'api://client-id/access_as_user' };
const TOKEN = 'eyJ.secret-token-value.sig';
const account = { homeAccountId: 'h', environment: 'e', tenantId: 't', username: 'ada@contoso.example', localAccountId: 'l', name: 'Ada' };
const msalError = (errorCode: string) => Object.assign(new Error(`AADSTS-secret-text ${errorCode}`), { errorCode });

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => void data.set(key, value), removeItem: (key: string) => void data.delete(key) };
}

function fakeApp(overrides: Record<string, unknown> = {}) {
  const app = {
    initialize: vi.fn().mockResolvedValue(undefined),
    handleRedirectPromise: vi.fn().mockResolvedValue(null),
    getActiveAccount: vi.fn(() => null),
    getAllAccounts: vi.fn(() => []),
    setActiveAccount: vi.fn(),
    acquireTokenSilent: vi.fn(),
    ssoSilent: vi.fn().mockRejectedValue(msalError('login_required')),
    loginRedirect: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return app as typeof app & MsalApp;
}

function setup(app: ReturnType<typeof fakeApp>, storage = memoryStorage(), fetchHint: () => Promise<string | undefined> = async () => undefined) {
  const reload = vi.fn();
  const auth = createMsalAuth(config, { loadApp: async () => app, storage, fetchHint, reload, now: () => 1_000_000 });
  return { auth, storage, reload };
}

afterEach(() => vi.restoreAllMocks());

describe('silent pick-up of the existing session', () => {
  it('uses ssoSilent with the hint from the edge session and never redirects when it works', async () => {
    const app = fakeApp({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    const { auth, storage } = setup(app, memoryStorage(), async () => 'ada@contoso.example');
    await expect(auth.getToken()).resolves.toBe(TOKEN);
    expect(app.ssoSilent).toHaveBeenCalledWith({ scopes: [config.scope], loginHint: 'ada@contoso.example' });
    expect(app.loginRedirect).not.toHaveBeenCalled();
    expect(app.setActiveAccount).toHaveBeenCalledWith(account);
    expect(storage.data.size).toBe(0); // the redirect flag is not left behind, and no token is stored by us
  });

  it('works without a hint (local dev has no /.auth/me)', async () => {
    const app = fakeApp({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    await setup(app).auth.getToken();
    expect(app.ssoSilent).toHaveBeenCalledWith({ scopes: [config.scope] });
  });

  it('uses a cached account first and only falls back to ssoSilent with that account as the hint', async () => {
    const cached = fakeApp({ getAllAccounts: vi.fn(() => [account]), acquireTokenSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    await expect(setup(cached).auth.getToken()).resolves.toBe(TOKEN);
    expect(cached.ssoSilent).not.toHaveBeenCalled();
    expect(cached.acquireTokenSilent).toHaveBeenCalledWith(expect.objectContaining({ scopes: [config.scope], account }));

    const stale = fakeApp({ getAllAccounts: vi.fn(() => [account]), acquireTokenSilent: vi.fn().mockRejectedValue(msalError('interaction_required')), ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    await expect(setup(stale).auth.getToken()).resolves.toBe(TOKEN);
    expect(stale.ssoSilent).toHaveBeenCalledWith({ scopes: [config.scope], loginHint: account.username });
    expect(stale.loginRedirect).not.toHaveBeenCalled();
  });

  it('never logs a token', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => undefined));
    const app = fakeApp({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    await setup(app).auth.getToken();
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain(TOKEN);
  });
});

describe('at most one automatic redirect', () => {
  it('redirects once when the silent attempt fails, with the hint, and records it in sessionStorage', async () => {
    const app = fakeApp();
    const { auth, storage } = setup(app, memoryStorage(), async () => 'ada@contoso.example');
    let settled = false;
    void auth.getToken().then(() => { settled = true; }, () => { settled = true; });
    await vi.waitFor(() => expect(app.loginRedirect).toHaveBeenCalledTimes(1));
    expect(app.loginRedirect).toHaveBeenCalledWith({ scopes: [config.scope], loginHint: 'ada@contoso.example' });
    expect(storage.data.has(REDIRECT_FLAG)).toBe(true);
    await Promise.resolve();
    expect(settled).toBe(false); // the page is leaving; the promise never settles
  });

  it('does not redirect a second time after returning from one, so there is no loop', async () => {
    const storage = memoryStorage();
    const first = fakeApp();
    void setup(first, storage).auth.getToken();
    await vi.waitFor(() => expect(first.loginRedirect).toHaveBeenCalledTimes(1));

    // Next page load in the same tab: the redirect came back, but silent sign-in still cannot produce a token.
    const second = fakeApp();
    const reloaded = setup(second, storage).auth;
    await expect(reloaded.getToken()).rejects.toMatchObject({ reason: 'signin_required' });
    await expect(reloaded.getToken()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(second.loginRedirect).not.toHaveBeenCalled();
  });

  it('shares one attempt between concurrent callers, so two requests cannot start two redirects', async () => {
    const app = fakeApp();
    const { auth } = setup(app);
    void auth.getToken(); void auth.getToken(); void auth.getToken();
    await vi.waitFor(() => expect(app.loginRedirect).toHaveBeenCalled());
    expect(app.loginRedirect).toHaveBeenCalledTimes(1);
    expect(app.ssoSilent).toHaveBeenCalledTimes(1);
  });

  it('allows another automatic attempt once a token was obtained (the flag is cleared by success)', async () => {
    const storage = memoryStorage({ [REDIRECT_FLAG]: String(1_000_000) });
    const app = fakeApp({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) });
    await setup(app, storage).auth.getToken();
    expect(storage.data.has(REDIRECT_FLAG)).toBe(false);
  });

  it('ignores a flag older than five minutes', async () => {
    const storage = memoryStorage({ [REDIRECT_FLAG]: String(1_000_000 - 6 * 60_000) });
    const app = fakeApp();
    void setup(app, storage).auth.getToken();
    await vi.waitFor(() => expect(app.loginRedirect).toHaveBeenCalledTimes(1));
  });

  it('does not redirect on its own when the flag cannot be stored (a loop could not be ruled out)', async () => {
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }, removeItem: () => { throw new Error('blocked'); } };
    const app = fakeApp();
    const auth = createMsalAuth(config, { loadApp: async () => app, storage: broken, fetchHint: async () => undefined });
    await expect(auth.getToken()).rejects.toMatchObject({ reason: 'signin_required' });
    expect(app.loginRedirect).not.toHaveBeenCalled();
  });

  it('never redirects during a forced silent refresh', async () => {
    const app = fakeApp({ getAllAccounts: vi.fn(() => [account]), acquireTokenSilent: vi.fn().mockRejectedValue(msalError('interaction_required')) });
    await expect(setup(app).auth.getToken({ forceRefresh: true })).rejects.toMatchObject({ reason: 'signin_required' });
    expect(app.acquireTokenSilent).toHaveBeenCalledWith(expect.objectContaining({ forceRefresh: true }));
    expect(app.loginRedirect).not.toHaveBeenCalled();
  });
});

describe('redirect errors and interaction_in_progress', () => {
  it('does not redirect again when the redirect returned with an error', async () => {
    const app = fakeApp({ handleRedirectPromise: vi.fn().mockRejectedValue(msalError('server_error')) });
    const { auth } = setup(app);
    await expect(auth.getToken()).rejects.toMatchObject({ reason: 'redirect_error' });
    expect(app.ssoSilent).not.toHaveBeenCalled();
    expect(app.loginRedirect).not.toHaveBeenCalled();
  });

  it('treats an access_denied return as no access', async () => {
    const app = fakeApp({ handleRedirectPromise: vi.fn().mockRejectedValue(msalError('access_denied')) });
    await expect(setup(app).auth.getToken()).rejects.toMatchObject({ reason: 'no_access' });
  });

  it('does not put provider error text in the error it raises', async () => {
    const app = fakeApp({ handleRedirectPromise: vi.fn().mockRejectedValue(msalError('server_error')) });
    const error = await setup(app).auth.getToken().catch((caught: Error) => caught);
    expect((error as Error).message).not.toContain('AADSTS');
  });

  it('does not start a second interaction when one is already in progress', async () => {
    const silent = fakeApp({ ssoSilent: vi.fn().mockRejectedValue(msalError('interaction_in_progress')) });
    await expect(setup(silent).auth.getToken()).rejects.toMatchObject({ reason: 'interaction_in_progress' });
    expect(silent.loginRedirect).not.toHaveBeenCalled();

    const redirect = fakeApp({ loginRedirect: vi.fn().mockRejectedValue(msalError('interaction_in_progress')) });
    await expect(setup(redirect).auth.getToken()).rejects.toMatchObject({ reason: 'interaction_in_progress' });
    expect(redirect.loginRedirect).toHaveBeenCalledTimes(1);
  });

  it('retries initialization on a later call if MSAL failed to load', async () => {
    const loadApp = vi.fn().mockRejectedValueOnce(new Error('chunk failed')).mockResolvedValue(fakeApp({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account }) }));
    const auth = createMsalAuth(config, { loadApp, storage: memoryStorage(), fetchHint: async () => undefined });
    await expect(auth.getToken()).rejects.not.toBeInstanceOf(AuthRequiredError);
    await expect(auth.getToken()).resolves.toBe(TOKEN);
  });
});

describe('explicit sign-in (the button)', () => {
  it('redirects even though the automatic redirect was already used, and clears an earlier error', async () => {
    const storage = memoryStorage({ [REDIRECT_FLAG]: String(1_000_000) });
    const app = fakeApp({ handleRedirectPromise: vi.fn().mockRejectedValue(msalError('server_error')) });
    const { auth } = setup(app, storage, async () => 'ada@contoso.example');
    await expect(auth.getToken()).rejects.toMatchObject({ reason: 'redirect_error' });
    await auth.signIn();
    expect(app.loginRedirect).toHaveBeenCalledTimes(1);
    expect(app.loginRedirect).toHaveBeenCalledWith({ scopes: [config.scope], loginHint: 'ada@contoso.example' });
    expect(storage.data.has(REDIRECT_FLAG)).toBe(true); // so a failed return is still not followed by a second automatic redirect
  });

  it('reloads the page to clear a stale interaction marker', async () => {
    const app = fakeApp({ loginRedirect: vi.fn().mockRejectedValue(msalError('interaction_in_progress')) });
    const { auth, reload } = setup(app);
    await auth.signIn();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe('login hint from the edge session', () => {
  const answer = (body: string, status = 200) => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status })));

  it('reads only an email-shaped identity claim and ignores tokens in the response', async () => {
    answer(JSON.stringify([{ provider_name: 'aad', id_token: TOKEN, access_token: TOKEN, user_id: 'ada@contoso.example', user_claims: [{ typ: 'name', val: 'Ada' }, { typ: 'preferred_username', val: 'ada@contoso.example' }] }]));
    await expect(sessionLoginHint()).resolves.toBe('ada@contoso.example');
    expect(fetch).toHaveBeenCalledWith('/.auth/me', expect.objectContaining({ credentials: 'same-origin' }));
  });

  it('treats 404, the SPA index.html, bad JSON, non-email values and network errors as no hint', async () => {
    answer('', 404);
    await expect(sessionLoginHint()).resolves.toBeUndefined();
    answer('<!doctype html><html></html>');
    await expect(sessionLoginHint()).resolves.toBeUndefined();
    answer(JSON.stringify([{ user_id: 'not-an-email', user_claims: [{ typ: 'preferred_username', val: TOKEN }] }]));
    await expect(sessionLoginHint()).resolves.toBeUndefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(sessionLoginHint()).resolves.toBeUndefined();
  });
});

describe('silent sign-in frame', () => {
  it('is only a frame when embedded and carrying a sign-in response', () => {
    const top = {} as Window;
    expect(isMsalSilentFrame({ self: {} as Window, top, location: { hash: '#code=abc&state=x' } as Location })).toBe(true);
    expect(isMsalSilentFrame({ self: {} as Window, top, location: { hash: '#error=login_required' } as Location })).toBe(true);
    expect(isMsalSilentFrame({ self: {} as Window, top, location: { hash: '' } as Location })).toBe(false);
    expect(isMsalSilentFrame({ self: top, top, location: { hash: '#code=abc' } as Location })).toBe(false);
  });
});

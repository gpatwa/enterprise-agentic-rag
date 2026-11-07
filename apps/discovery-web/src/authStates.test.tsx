import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { createMsalAuth, REDIRECT_FLAG, type MsalApp, type MsalAuth } from './api/auth';
import { AuthRequiredError } from './api/errors';
import { createSession } from './api/session';

const TOKEN = 'eyJ.secret-token-value.sig';
const searchBody = { schema_version: 'imd-search-v1', request_id: 'r', total_matches: 0, fallback: false, error: null, results: [] };
const productBody = { schema_version: 'p', results: [], total_matches: 0, page: 1, page_size: 10, match: 'all', error: null };
const reply = (status: number, body: unknown = {}) => new Response(status === 200 ? JSON.stringify(body) : '', { status });

/** A token source that always has a token, so only the API's answer decides the state. */
function steadyAuth(overrides: Partial<MsalAuth> = {}) {
  return { getToken: vi.fn().mockResolvedValue(TOKEN), signIn: vi.fn().mockResolvedValue(undefined), ...overrides } satisfies MsalAuth;
}
/** Stubs fetch; the handler gets the request path, so a test could answer the two searches differently. */
function stubApi(handler: (path: string) => Response | Promise<Response>) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => handler(url));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const exploreSearch = () => fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
function searchProducts(text = 'shoes') {
  fireEvent.change(screen.getByLabelText('Search products'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

describe('auth states', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', { randomUUID: () => 'request-1' });
  });
  afterEach(() => vi.unstubAllGlobals());

  describe('session ended (401)', () => {
    it('shows the designed state, announces it, moves focus to the one button, and shows no generic error or code', async () => {
      stubApi(() => reply(401));
      const auth = steadyAuth();
      render(<App session={createSession({}, { auth })} />);
      exploreSearch();

      const alert = await screen.findByRole('alert');
      expect(within(alert).getByRole('heading', { name: 'Your session ended.' })).toBeInTheDocument();
      expect(alert).toHaveTextContent('Sign in again.');
      expect(within(alert).getAllByRole('button')).toHaveLength(1); // a single primary action
      const button = within(alert).getByRole('button', { name: 'Sign in again' });
      expect(button.tagName).toBe('BUTTON'); // natively keyboard operable
      expect(button.tabIndex).toBe(0);
      await waitFor(() => expect(button).toHaveFocus());
      expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/401|AADSTS|eyJ/);
      expect(document.body.textContent).not.toContain(TOKEN);
      expect(screen.getAllByRole('alert')).toHaveLength(1);
    });

    it('takes one silent refresh and one retry first, then shows the state', async () => {
      const fetchMock = stubApi(() => reply(401));
      const auth = steadyAuth();
      render(<App session={createSession({}, { auth })} />);
      exploreSearch();
      await screen.findByRole('heading', { name: 'Your session ended.' });
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(auth.getToken).toHaveBeenLastCalledWith({ forceRefresh: true });
    });

    it('recovers silently when the one retry succeeds, without ever showing the state', async () => {
      let attempts = 0;
      stubApi(() => (attempts++ === 0 ? reply(401) : reply(200, searchBody)));
      render(<App session={createSession({}, { auth: steadyAuth() })} />);
      exploreSearch();
      await screen.findByText('No worlds matched that search.');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('signs in again from the button, and goes away after the next good answer', async () => {
      let signedIn = false;
      stubApi(() => (signedIn ? reply(200, searchBody) : reply(401)));
      const auth = steadyAuth();
      render(<App session={createSession({}, { auth })} />);
      exploreSearch();
      const button = await screen.findByRole('button', { name: 'Sign in again' });
      fireEvent.click(button);
      expect(auth.signIn).toHaveBeenCalledTimes(1);
      await screen.findByText('Signing you in...');
      expect(screen.queryByRole('button', { name: 'Sign in again' })).not.toBeInTheDocument();

      signedIn = true; // as after a successful return from the redirect
      exploreSearch();
      await screen.findByText('No worlds matched that search.');
      await waitFor(() => expect(screen.queryByText('Signing you in...')).not.toBeInTheDocument());
    });

    it('falls back to the session ended state if starting the sign-in itself fails', async () => {
      stubApi(() => reply(401));
      render(<App session={createSession({}, { auth: steadyAuth({ signIn: vi.fn().mockRejectedValue(new Error('x')) }) })} />);
      exploreSearch();
      fireEvent.click(await screen.findByRole('button', { name: 'Sign in again' }));
      await screen.findByRole('heading', { name: 'Your session ended.' });
    });

    it('reloads the page (and so the edge sign-in) when no Entra settings are configured', async () => {
      stubApi(() => reply(401));
      const reload = vi.fn();
      render(<App session={createSession({}, { reload })} />);
      exploreSearch();
      fireEvent.click(await screen.findByRole('button', { name: 'Sign in again' }));
      expect(reload).toHaveBeenCalledTimes(1);
    });

    it('is shared with product search', async () => {
      stubApi(() => reply(401));
      render(<App session={createSession({}, { auth: steadyAuth() })} />);
      searchProducts();
      await screen.findByRole('heading', { name: 'Your session ended.' });
      expect(screen.queryByText(/Product search is unavailable/)).not.toBeInTheDocument();
      expect(screen.getAllByRole('alert')).toHaveLength(1);
    });
  });

  describe('no access (403)', () => {
    it('shows the designed state with no retry, announces it and takes focus', async () => {
      const fetchMock = stubApi(() => reply(403));
      const auth = steadyAuth();
      render(<App session={createSession({}, { auth })} />);
      exploreSearch();

      const alert = await screen.findByRole('alert');
      expect(within(alert).getByRole('heading', { name: "You don't have access to this demo." })).toBeInTheDocument();
      expect(alert).toHaveTextContent('Ask the owner to add you.');
      expect(within(alert).queryByRole('button')).not.toBeInTheDocument();
      await waitFor(() => expect(alert).toHaveFocus());
      expect(alert.tabIndex).toBe(-1); // focusable by script, not an extra tab stop
      expect(fetchMock).toHaveBeenCalledTimes(1); // no refresh, no retry
      expect(auth.getToken).not.toHaveBeenCalledWith({ forceRefresh: true });
      expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/403|AADSTS/);
    });

    it('is shared with product search', async () => {
      stubApi(() => reply(403));
      render(<App session={createSession({}, { auth: steadyAuth() })} />);
      searchProducts();
      await screen.findByRole('heading', { name: "You don't have access to this demo." });
      expect(screen.queryByText(/Product search is unavailable/)).not.toBeInTheDocument();
    });

    it('is reached when the redirect returns access_denied', async () => {
      const app = fakeMsal({ handleRedirectPromise: vi.fn().mockRejectedValue(Object.assign(new Error('AADSTS50105'), { errorCode: 'access_denied' })) });
      stubApi(() => reply(200, searchBody));
      const msal = createMsalAuth(config, { loadApp: async () => app, storage: memoryStorage(), fetchHint: async () => undefined });
      render(<App session={createSession({}, { auth: msal })} />);
      await screen.findByRole('heading', { name: "You don't have access to this demo." });
      expect(document.body.textContent).not.toContain('AADSTS');
    });
  });

  describe('signing in', () => {
    it('appears only after a moment, inside a polite live region, and clears when sign-in finishes', async () => {
      let finish: (token: string) => void = () => undefined;
      const auth = steadyAuth({ getToken: vi.fn().mockReturnValue(new Promise<string>((resolve) => { finish = resolve; })) });
      const { container } = render(<App session={createSession({}, { auth, delayMs: 60 })} />);
      const live = container.querySelector('[aria-live="polite"].auth-live') as HTMLElement;
      expect(live).toBeInTheDocument(); // mounted from the start, so the change is announced
      expect(screen.queryByText('Signing you in...')).not.toBeInTheDocument(); // not for a quick sign-in
      await waitFor(() => expect(within(live).getByText('Signing you in...')).toBeInTheDocument());
      expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // progress is not an alarm
      await act(async () => finish(TOKEN));
      await waitFor(() => expect(screen.queryByText('Signing you in...')).not.toBeInTheDocument());
    });

    it('never shows when sign-in is quick', async () => {
      render(<App session={createSession({}, { auth: steadyAuth(), delayMs: 60 })} />);
      await new Promise((resolve) => setTimeout(resolve, 120));
      expect(screen.queryByText('Signing you in...')).not.toBeInTheDocument();
    });

    it('stays while a redirect is under way', async () => {
      const auth = steadyAuth({ getToken: vi.fn().mockReturnValue(new Promise<string>(() => undefined)) });
      render(<App session={createSession({}, { auth, delayMs: 10 })} />);
      await screen.findByText('Signing you in...');
    });
  });

  describe('API unavailable', () => {
    it('keeps the existing retry messages and no sign-in state for non-auth failures', async () => {
      stubApi(() => reply(503));
      render(<App session={createSession({}, { auth: steadyAuth() })} />);
      exploreSearch();
      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Search is unavailable right now. Try again in a moment.'));
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Your session ended.' })).not.toBeInTheDocument();
      searchProducts();
      await waitFor(() => expect(screen.getByText('Product search is unavailable right now. Try again in a moment.')).toBeInTheDocument());
    });
  });

  describe('page load', () => {
    it('begins sign-in once at load (also under StrictMode) and shows the state if the person has to act', async () => {
      const getToken = vi.fn().mockRejectedValue(new AuthRequiredError('signin_required'));
      const fetchMock = stubApi(() => reply(200, searchBody));
      render(<StrictMode><App session={createSession({}, { auth: steadyAuth({ getToken }) })} /></StrictMode>);
      await screen.findByRole('heading', { name: 'Your session ended.' });
      expect(getToken).toHaveBeenCalledTimes(1);
      expect(fetchMock).not.toHaveBeenCalled(); // nothing is fetched on load
    });

    it('does nothing at load when the Entra settings are unset: no token source, no calls', async () => {
      const fetchMock = stubApi(() => reply(200, searchBody));
      const session = createSession({});
      render(<App session={session} />);
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(fetchMock).not.toHaveBeenCalled();
      expect(session.status.get()).toBe('ok');
      exploreSearch();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      expect(fetchMock.mock.calls[0][1].headers.authorization).toBeUndefined();
    });
  });

  describe('no redirect loop, end to end with a fake MSAL', () => {
    it('redirects once for the first page load and not again when the return still has no token', async () => {
      const storage = memoryStorage();
      stubApi(() => reply(200, searchBody));
      const first = fakeMsal();
      render(<App session={createSession({}, { auth: createMsalAuth(config, { loadApp: async () => first, storage, fetchHint: async () => 'ada@contoso.example' }) })} />);
      await waitFor(() => expect(first.loginRedirect).toHaveBeenCalledTimes(1));
      expect(storage.data.has(REDIRECT_FLAG)).toBe(true);
      cleanup();

      // The same tab comes back from sign-in; silent sign-in still fails. A second automatic redirect would be a loop.
      const second = fakeMsal();
      render(<App session={createSession({}, { auth: createMsalAuth(config, { loadApp: async () => second, storage, fetchHint: async () => 'ada@contoso.example' }) })} />);
      await screen.findByRole('heading', { name: 'Your session ended.' });
      expect(second.loginRedirect).not.toHaveBeenCalled();
      expect(first.loginRedirect).toHaveBeenCalledTimes(1);
    });

    it('is quiet when the existing session is picked up silently', async () => {
      stubApi(() => reply(200, productBody));
      const app = fakeMsal({ ssoSilent: vi.fn().mockResolvedValue({ accessToken: TOKEN, account: { username: 'ada@contoso.example' } }) });
      const storage = memoryStorage();
      const session = createSession({}, { auth: createMsalAuth(config, { loadApp: async () => app, storage, fetchHint: async () => 'ada@contoso.example' }), delayMs: 5 });
      render(<App session={session} />);
      await waitFor(() => expect(app.ssoSilent).toHaveBeenCalledTimes(1));
      searchProducts();
      await screen.findByText('No products matched that search.');
      expect(app.loginRedirect).not.toHaveBeenCalled();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText('Signing you in...')).not.toBeInTheDocument();
    });
  });
});

const config = { clientId: 'client-id', tenantId: 'tenant-id', scope: 'api://client-id/access_as_user' };
function memoryStorage() {
  const data = new Map<string, string>();
  return { data, getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => void data.set(key, value), removeItem: (key: string) => void data.delete(key) };
}
function fakeMsal(overrides: Record<string, unknown> = {}) {
  const app = {
    initialize: vi.fn().mockResolvedValue(undefined),
    handleRedirectPromise: vi.fn().mockResolvedValue(null),
    getActiveAccount: vi.fn(() => null),
    getAllAccounts: vi.fn(() => []),
    setActiveAccount: vi.fn(),
    acquireTokenSilent: vi.fn(),
    ssoSilent: vi.fn().mockRejectedValue(Object.assign(new Error('x'), { errorCode: 'login_required' })),
    loginRedirect: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return app as typeof app & MsalApp;
}

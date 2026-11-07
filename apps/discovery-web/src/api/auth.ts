import type { AccountInfo, AuthenticationResult, PublicClientApplication } from '@azure/msal-browser';
import { AuthRequiredError } from './errors';

/** Optional Entra sign-in. With no VITE_ENTRA_* settings the app sends no token, which is today's behaviour. */
export type AuthConfig = { clientId: string; tenantId: string; scope: string };
export type TokenOptions = { forceRefresh?: boolean };
export type TokenSource = (options?: TokenOptions) => Promise<string | null>;

export function authConfigFromEnv(env: Record<string, string | undefined>): AuthConfig | null {
  const clientId = env.VITE_ENTRA_CLIENT_ID?.trim();
  const tenantId = env.VITE_ENTRA_TENANT_ID?.trim();
  const scope = env.VITE_ENTRA_API_SCOPE?.trim();
  return clientId && tenantId && scope ? { clientId, tenantId, scope } : null;
}

/** The slice of MSAL this app uses; the real PublicClientApplication satisfies it, tests supply a fake. */
export type MsalApp = Pick<PublicClientApplication, 'initialize' | 'handleRedirectPromise' | 'getActiveAccount' | 'getAllAccounts' | 'setActiveAccount' | 'acquireTokenSilent' | 'ssoSilent' | 'loginRedirect'>;

export type MsalAuthDeps = {
  loadApp?: (config: AuthConfig) => Promise<MsalApp>;
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
  /** The signed-in user's address from the existing edge session, or undefined. Must never reject. */
  fetchHint?: () => Promise<string | undefined>;
  now?: () => number;
  reload?: () => void;
};

export type MsalAuth = {
  getToken: TokenSource;
  /** Explicit, user-initiated sign-in (the button). Allowed even after the one automatic redirect was used. */
  signIn(): Promise<void>;
};

/** At most one automatic redirect per page load: this key is claimed before redirecting and cleared only by a good token or a click. */
export const REDIRECT_FLAG = 'discovery.auth.redirect-attempt';
/** A flag older than this is ignored, so a fresh visit in a long-lived tab may try once more. A redirect loop cycles in seconds. */
const FLAG_FRESH_MS = 5 * 60_000;
const HINT_TIMEOUT_MS = 2_000;
const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,255}$/;
const HINT_CLAIMS = ['preferred_username', 'upn', 'email', 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn', 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress'];

function errorCode(error: unknown): string | undefined {
  const code = (error as { errorCode?: unknown } | null)?.errorCode;
  return typeof code === 'string' ? code : undefined;
}

/** A silent iframe that MSAL opened to our own origin carries the response in its hash; it must not run the app (and consume the hash). */
export function isMsalSilentFrame(win: { self: unknown; top: unknown; location: Pick<Location, 'hash'> } = window): boolean {
  return win.self !== win.top && /[#&](code|error)=/.test(win.location.hash);
}

/**
 * Reads the signed-in user's address from the platform sign-in session (Container Apps easy-auth `/.auth/me`) to use as a
 * login hint. Absent in local dev (404, or the SPA's index.html), in which case there is simply no hint. Only an email-shaped
 * identity claim is read; any token in that response is ignored and nothing from it is logged or stored.
 */
export async function sessionLoginHint(): Promise<string | undefined> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HINT_TIMEOUT_MS);
  try {
    const response = await fetch('/.auth/me', { credentials: 'same-origin', signal: controller.signal });
    if (!response.ok) return undefined;
    const data: unknown = JSON.parse(await response.text());
    const entry = (Array.isArray(data) ? data[0] : data) as { user_id?: unknown; user_claims?: unknown } | null | undefined;
    const claims = Array.isArray(entry?.user_claims) ? (entry.user_claims as { typ?: unknown; val?: unknown }[]) : [];
    const candidates = [
      ...HINT_CLAIMS.map((type) => claims.find((claim) => claim?.typ === type)?.val),
      entry?.user_id,
    ];
    return candidates.find((value): value is string => typeof value === 'string' && value.length <= 320 && EMAIL.test(value));
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

/** Must equal the SPA redirect URI registered in Terraform exactly, including the trailing slash. */
export function redirectUriFor(origin: string): string {
  return `${origin}/`;
}

async function loadRealApp(config: AuthConfig): Promise<MsalApp> {
  const { PublicClientApplication } = await import('@azure/msal-browser');
  return new PublicClientApplication({
    auth: { clientId: config.clientId, authority: `https://login.microsoftonline.com/${config.tenantId}`, redirectUri: redirectUriFor(window.location.origin) },
    cache: { cacheLocation: 'sessionStorage' },
  });
}

/**
 * Token source backed by MSAL (loaded on first use). Order of attempts, each silent until the last:
 * cached token, then `ssoSilent` against the existing Entra session (with a login hint when one is known), then at most one
 * automatic redirect per page load. A forced refresh (after a 401) never redirects. Tokens are never logged, put in a URL or
 * stored by this code; MSAL keeps its cache in sessionStorage only.
 */
export function createMsalAuth(config: AuthConfig, deps: MsalAuthDeps = {}): MsalAuth {
  const loadApp = deps.loadApp ?? loadRealApp;
  const fetchHint = deps.fetchHint ?? sessionLoginHint;
  const now = deps.now ?? Date.now;
  const reload = deps.reload ?? (() => window.location.reload());
  const store = (): MsalAuthDeps['storage'] | undefined => {
    try { return deps.storage ?? window.sessionStorage; } catch { return undefined; }
  };

  const flagFresh = (): boolean => {
    const raw = store()?.getItem(REDIRECT_FLAG);
    return raw != null && now() - Number(raw) < FLAG_FRESH_MS;
  };
  /** True when this call may redirect. If the flag cannot be stored we cannot rule out a loop, so we do not redirect. */
  const claimRedirect = (): boolean => {
    try {
      const storage = store();
      if (!storage || flagFresh()) return false;
      storage.setItem(REDIRECT_FLAG, String(now()));
      return flagFresh();
    } catch { return false; }
  };
  const clearFlag = () => { try { store()?.removeItem(REDIRECT_FLAG); } catch { /* storage unavailable */ } };

  let redirectError: string | null = null;
  let ready: Promise<MsalApp> | null = null;
  const start = () => {
    ready ??= (async () => {
      const app = await loadApp(config);
      await app.initialize();
      try {
        const result = await app.handleRedirectPromise();
        if (result?.account) app.setActiveAccount(result.account);
      } catch (error) {
        // The redirect came back with an error. Remember only its code (never shown) and do not redirect again on our own.
        redirectError = errorCode(error) ?? 'unknown';
      }
      return app;
    })().catch((error) => { ready = null; throw error; });
    return ready;
  };

  const rejectIfBusy = (error: unknown) => {
    if (errorCode(error) === 'interaction_in_progress') throw new AuthRequiredError('interaction_in_progress');
  };
  const accepted = (app: MsalApp, result: AuthenticationResult): string => {
    if (result.account) app.setActiveAccount(result.account);
    clearFlag();
    return result.accessToken;
  };
  const request = { scopes: [config.scope] };

  async function acquire(forceRefresh: boolean): Promise<string> {
    const app = await start();
    if (redirectError) throw new AuthRequiredError(redirectError === 'access_denied' ? 'no_access' : 'redirect_error');
    const account: AccountInfo | undefined = app.getActiveAccount() ?? app.getAllAccounts()[0];
    let hint: string | undefined;
    if (account) {
      app.setActiveAccount(account);
      try { return accepted(app, await app.acquireTokenSilent({ ...request, account, forceRefresh })); } catch (error) { rejectIfBusy(error); }
      hint = account.username || undefined;
    }
    hint ??= await fetchHint();
    try { return accepted(app, await app.ssoSilent({ ...request, ...(hint ? { loginHint: hint } : {}) })); } catch (error) { rejectIfBusy(error); }
    if (forceRefresh || !claimRedirect()) throw new AuthRequiredError('signin_required');
    try {
      await app.loginRedirect({ ...request, ...(hint ? { loginHint: hint } : {}) });
    } catch (error) {
      rejectIfBusy(error);
      throw new AuthRequiredError('signin_required');
    }
    // The page is leaving for the sign-in redirect, so this promise intentionally never settles.
    return new Promise<string>(() => undefined);
  }

  let shared: Promise<string | null> | null = null;
  const getToken: TokenSource = (options) => {
    if (options?.forceRefresh) return acquire(true);
    // Concurrent callers (React StrictMode, two searches at once) share one attempt and so cannot start two redirects.
    shared ??= acquire(false).finally(() => { shared = null; });
    return shared;
  };

  async function signIn(): Promise<void> {
    const app = await start();
    redirectError = null;
    clearFlag();
    const account = app.getActiveAccount() ?? app.getAllAccounts()[0];
    const hint = account?.username || (await fetchHint());
    claimRedirect();
    try {
      await app.loginRedirect({ ...request, ...(hint ? { loginHint: hint } : {}) });
    } catch (error) {
      // A stale interaction marker left by an abandoned redirect; a reload clears it (MSAL does this on load).
      if (errorCode(error) === 'interaction_in_progress') reload();
      else throw error;
    }
  }

  return { getToken, signIn };
}

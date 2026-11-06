/** Optional Entra sign-in. With no VITE_ENTRA_* settings the app sends no token, which is today's behaviour. */
export type AuthConfig = { clientId: string; tenantId: string; scope: string };
export type TokenSource = () => Promise<string | null>;

export function authConfigFromEnv(env: Record<string, string | undefined>): AuthConfig | null {
  const clientId = env.VITE_ENTRA_CLIENT_ID?.trim();
  const tenantId = env.VITE_ENTRA_TENANT_ID?.trim();
  const scope = env.VITE_ENTRA_API_SCOPE?.trim();
  return clientId && tenantId && scope ? { clientId, tenantId, scope } : null;
}

/**
 * Returns a token source backed by MSAL (loaded on first use). It tries a silent token first and falls back to a
 * redirect sign-in; the redirect leaves the page, so the promise then never settles. Tokens are never logged or stored by us.
 */
export function createMsalTokenSource(config: AuthConfig): TokenSource {
  let ready: Promise<import('@azure/msal-browser').PublicClientApplication> | null = null;
  const start = () => {
    ready ??= import('@azure/msal-browser').then(async ({ PublicClientApplication }) => {
      const app = new PublicClientApplication({
        auth: { clientId: config.clientId, authority: `https://login.microsoftonline.com/${config.tenantId}`, redirectUri: window.location.origin },
        cache: { cacheLocation: 'sessionStorage' },
      });
      await app.initialize();
      await app.handleRedirectPromise();
      return app;
    });
    return ready;
  };
  return async () => {
    const app = await start();
    const account = app.getActiveAccount() ?? app.getAllAccounts()[0];
    if (!account) {
      await app.loginRedirect({ scopes: [config.scope] });
      return new Promise<string | null>(() => undefined);
    }
    app.setActiveAccount(account);
    try {
      return (await app.acquireTokenSilent({ scopes: [config.scope], account })).accessToken;
    } catch {
      await app.acquireTokenRedirect({ scopes: [config.scope], account });
      return new Promise<string | null>(() => undefined);
    }
  };
}

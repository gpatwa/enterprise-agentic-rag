import { authConfigFromEnv, createMsalAuth, type MsalAuth, type MsalAuthDeps } from './auth';
import { createAuthStatus, type AuthStatus } from './authStatus';
import { createDiscoveryClient, type DiscoveryClient } from './client';
import { authFailureOf } from './errors';

/** The API client plus the sign-in state the page shows. One per page; search and product search share it. */
export type Session = {
  client: DiscoveryClient;
  status: AuthStatus;
  /** Begins silent sign-in at page load, so the first search does not wait for it. A no-op without Entra settings. */
  start(): void;
  /** The "Sign in again" button. */
  signIn(): void;
};

export type SessionOptions = { baseUrl?: string; auth?: MsalAuth | null; delayMs?: number; reload?: () => void };

export function createSession(env: Record<string, string | undefined>, options: SessionOptions & { msal?: MsalAuthDeps } = {}): Session {
  const config = authConfigFromEnv(env);
  const auth = options.auth !== undefined ? options.auth : config ? createMsalAuth(config, options.msal) : null;
  const status = createAuthStatus(options.delayMs);
  const reload = options.reload ?? (() => window.location.reload());
  const raw = createDiscoveryClient(options.baseUrl ?? env.VITE_DISCOVERY_API_URL ?? '', auth ? (tokenOptions) => status.track(auth.getToken(tokenOptions)) : undefined);

  /** Records an auth failure as a page state and rethrows, so each caller still sees a failed call. */
  const guarded = <A, R>(call: (argument: A) => Promise<R>) => async (argument: A): Promise<R> => {
    try {
      const result = await call(argument);
      status.succeed();
      return result;
    } catch (error) {
      const failure = authFailureOf(error);
      if (failure) status.set(failure);
      throw error;
    }
  };
  const client: DiscoveryClient = { search: guarded((request) => raw.search(request)), searchProducts: guarded((request) => raw.searchProducts(request)) };

  let started = false;
  return {
    client,
    status,
    start() {
      if (!auth || started) return;
      started = true;
      status.track(auth.getToken()).catch((error) => {
        const failure = authFailureOf(error);
        if (failure) status.set(failure);
        // Anything else (the MSAL bundle failed to load) is left for the first search to report as "unavailable", with Retry.
        else started = false;
      });
    },
    signIn() {
      if (!auth) { reload(); return; }
      status.set('signing-in');
      auth.signIn().catch(() => status.set('expired'));
    },
  };
}

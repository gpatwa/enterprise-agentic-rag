import type { AuthFailure } from './errors';

/** What the page should show about sign-in. 'ok' shows nothing. */
export type AuthPhase = 'ok' | 'signing-in' | AuthFailure;

export type AuthStatus = {
  get(): AuthPhase;
  subscribe(listener: () => void): () => void;
  set(phase: AuthPhase): void;
  /** Marks a good API answer: a stale "session ended" or "no access" notice goes away. */
  succeed(): void;
  /** Wraps a token acquisition: "signing in" appears only if it is still pending after `delayMs`, and clears when it settles. */
  track<T>(work: Promise<T>): Promise<T>;
};

export function createAuthStatus(delayMs = 400): AuthStatus {
  let phase: AuthPhase = 'ok';
  let pending = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();
  const set = (next: AuthPhase) => {
    if (next === phase) return;
    phase = next;
    listeners.forEach((listener) => listener());
  };
  const settle = () => {
    pending -= 1;
    if (pending > 0) return;
    clearTimeout(timer);
    if (phase === 'signing-in') set('ok');
  };
  return {
    get: () => phase,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    set,
    succeed() { if (phase === 'expired' || phase === 'no-access') set('ok'); },
    track(work) {
      pending += 1;
      if (pending === 1) timer = setTimeout(() => { if (pending > 0 && phase === 'ok') set('signing-in'); }, delayMs);
      return work.finally(settle);
    },
  };
}

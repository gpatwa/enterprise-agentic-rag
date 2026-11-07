import { LockKeyhole, LogIn } from 'lucide-react';
import { useEffect, useRef, useSyncExternalStore } from 'react';
import type { AuthPhase, AuthStatus } from './api/authStatus';

export function useAuthPhase(status: AuthStatus): AuthPhase {
  return useSyncExternalStore(status.subscribe, status.get, status.get);
}

/**
 * The page's sign-in states. Plain copy only: no codes, no provider text, nothing from a token.
 * "Signing you in..." sits in an always-mounted polite live region so a screen reader hears it appear.
 * The two blocking states are role="alert" and take keyboard focus, so a keyboard user lands on the one thing they can do.
 */
export function AuthPanel({ phase, onSignIn }: { phase: AuthPhase; onSignIn: () => void }) {
  const signInButton = useRef<HTMLButtonElement>(null);
  const noAccessNotice = useRef<HTMLElement>(null);
  useEffect(() => {
    if (phase === 'expired') signInButton.current?.focus();
    if (phase === 'no-access') noAccessNotice.current?.focus();
  }, [phase]);

  return <div className="auth-region">
    <div className="auth-live" aria-live="polite" aria-atomic="true">
      {phase === 'signing-in' && <div className="auth-state"><span className="loader" aria-hidden="true" /><p>Signing you in...</p></div>}
    </div>
    {phase === 'expired' && <section className="auth-state auth-blocking" role="alert" aria-labelledby="auth-title">
      <LogIn size={20} aria-hidden="true" />
      <div className="auth-copy"><h2 id="auth-title">Your session ended.</h2><p>Sign in again.</p></div>
      <button ref={signInButton} type="button" onClick={onSignIn}>Sign in again</button>
    </section>}
    {phase === 'no-access' && <section ref={noAccessNotice} className="auth-state auth-blocking" role="alert" aria-labelledby="auth-title" tabIndex={-1}>
      <LockKeyhole size={20} aria-hidden="true" />
      <div className="auth-copy"><h2 id="auth-title">You don't have access to this demo.</h2><p>Ask the owner to add you.</p></div>
    </section>}
  </div>;
}

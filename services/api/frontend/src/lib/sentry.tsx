/**
 * Sentry initialization for the frontend.
 *
 * Opt-in: only initialises when VITE_SENTRY_DSN is set at build time.
 * In dev / when DSN is unset this module is a no-op — `init()` returns
 * silently and `ErrorBoundary` becomes a pass-through.
 *
 * Why a wrapper file rather than calling Sentry directly in main.tsx?
 *   - Centralises the one place that touches Sentry's import-time side
 *     effects (which fire on `import * as Sentry`)
 *   - Lets us expose a `safeCaptureException` helper that no-ops when
 *     Sentry isn't initialised, so call sites don't have to gate
 *   - Reduces coupling: if we swap providers (Bugsnag, Honeybadger, …)
 *     the change is local
 */
import * as Sentry from '@sentry/react';
import type { ReactNode } from 'react';

const DEV =
  (import.meta as unknown as { env?: { DEV?: boolean } }).env?.DEV === true;

const DSN = (
  import.meta as unknown as { env?: { VITE_SENTRY_DSN?: string } }
).env?.VITE_SENTRY_DSN;

const ENVIRONMENT =
  (import.meta as unknown as { env?: { VITE_SENTRY_ENVIRONMENT?: string } }).env
    ?.VITE_SENTRY_ENVIRONMENT ?? (DEV ? 'development' : 'alpha');

const RELEASE = (
  import.meta as unknown as { env?: { VITE_SENTRY_RELEASE?: string } }
).env?.VITE_SENTRY_RELEASE;

let initialised = false;

export function initSentry() {
  // Refuse to enable in dev unless explicitly opted in — local stack traces
  // are more useful than half-tagged Sentry events.
  if (!DSN || initialised) return;
  if (DEV && ENVIRONMENT !== 'development-explicit') return;

  Sentry.init({
    dsn: DSN,
    environment: ENVIRONMENT,
    release: RELEASE,
    // Conservative defaults — alpha doesn't need full session replay.
    tracesSampleRate: 0.0,
    // Don't capture URL params or POST bodies that might contain PII.
    sendDefaultPii: false,
    // Filter out a few known-noisy events seen in our suite.
    ignoreErrors: [
      // ResizeObserver loop warnings are harmless — Chrome quirk.
      'ResizeObserver loop limit exceeded',
      'ResizeObserver loop completed with undelivered notifications',
      // Browser extensions hooking fetch sometimes throw here.
      'Non-Error promise rejection captured',
    ],
    beforeSend(event) {
      // One last cleanup: drop request data we don't need; Sentry's
      // sendDefaultPii=false already hides cookies/headers, but the
      // request URL can leak query strings. Replace the search portion
      // with a redaction marker.
      if (event.request?.url) {
        try {
          const u = new URL(event.request.url);
          if (u.search) {
            event.request.url = `${u.origin}${u.pathname}?[redacted]`;
          }
        } catch {
          /* malformed URL — leave untouched */
        }
      }
      return event;
    },
  });
  initialised = true;
}

/**
 * Capture an exception. No-ops when Sentry isn't initialised so call
 * sites don't need to check.
 */
export function safeCaptureException(err: unknown, context?: Record<string, unknown>) {
  if (!initialised) return;
  if (context) {
    Sentry.withScope((scope) => {
      Object.entries(context).forEach(([k, v]) => scope.setExtra(k, v));
      Sentry.captureException(err);
    });
  } else {
    Sentry.captureException(err);
  }
}

/**
 * ErrorBoundary that wraps the React app. When Sentry is initialised
 * this surfaces caught render errors there; either way it shows a
 * minimal "Something went wrong" UI rather than a blank page.
 */
export function SentryErrorBoundary({ children }: { children: ReactNode }) {
  return (
    <Sentry.ErrorBoundary fallback={ErrorFallback} showDialog={false}>
      {children}
    </Sentry.ErrorBoundary>
  );
}

function ErrorFallback({ error, resetError }: { error: unknown; resetError: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg p-6">
      <div className="max-w-md text-center">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">
          Compass
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">
          Something went wrong
        </h1>
        <p className="text-fg-secondary mt-3 text-sm leading-relaxed">
          The page hit an unexpected error. We&apos;ve been notified and the team
          will look into it.
        </p>
        <div className="mt-6 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={resetError}
            className="px-4 py-2 rounded-md bg-accent text-accent-fg text-sm font-medium hover:bg-accent/90"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-md bg-surface-muted border border-border text-fg text-sm font-medium hover:border-border-strong"
          >
            Reload page
          </button>
        </div>
        {DEV && error instanceof Error && (
          <pre className="text-xs text-fg-muted bg-surface-muted rounded-md p-3 mt-6 text-left overflow-auto max-h-48">
            {error.message}
            {error.stack ? `\n\n${error.stack}` : ''}
          </pre>
        )}
      </div>
    </div>
  );
}

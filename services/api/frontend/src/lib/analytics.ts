/**
 * Analytics instrumentation hook.
 *
 * Provider-agnostic shim. Today: console.debug + sendBeacon to
 * /api/v1/system/events (server logs them). Swap in PostHog / Segment /
 * Amplitude by replacing `dispatch` below — call sites don't change.
 *
 * Privacy: no PII in event names or props. Use stable ids only.
 * Properties pass through `[Source: …]`-style stripping if you must
 * include question text — see `redactForAnalytics`.
 */

export type EventName =
  | 'app.loaded'
  | 'home.viewed'
  | 'question.asked'
  | 'answer.first_token'
  | 'answer.received'
  | 'answer.errored'
  | 'answer.saved'
  | 'thread.opened'
  | 'thread.pinned'
  | 'sources.refreshed'
  | 'palette.opened'
  | 'theme.changed'
  | 'skill.installed';

interface EventProps {
  [k: string]: string | number | boolean | null | undefined;
}

const QUEUE_KEY = '__compass_event_queue__';
const FLUSH_INTERVAL_MS = 5_000;

interface QueuedEvent {
  name: EventName;
  props: EventProps;
  ts: number;
}

let inFlight = false;

function getQueue(): QueuedEvent[] {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  if (!w[QUEUE_KEY]) w[QUEUE_KEY] = [];
  return w[QUEUE_KEY];
}

async function flush() {
  if (inFlight) return;
  const q = getQueue();
  if (q.length === 0) return;
  inFlight = true;
  const batch = q.splice(0, q.length);
  try {
    // navigator.sendBeacon is best-effort and survives page unload.
    const ok =
      typeof navigator.sendBeacon === 'function' &&
      navigator.sendBeacon(
        '/api/v1/system/events',
        new Blob([JSON.stringify({ events: batch })], { type: 'application/json' })
      );
    if (!ok) {
      // Fall back to keepalive fetch
      await fetch('/api/v1/system/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: batch }),
        keepalive: true,
      });
    }
  } catch {
    // Re-queue on failure (capped to avoid runaway growth)
    if (q.length < 1000) q.unshift(...batch);
  } finally {
    inFlight = false;
  }
}

if (typeof window !== 'undefined') {
  setInterval(() => void flush(), FLUSH_INTERVAL_MS);
  window.addEventListener('beforeunload', () => void flush());
}

/** Strip PII-ish content from event properties (best-effort client-side). */
export function redactForAnalytics(s: string, max = 80): string {
  return s
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '[email]')
    .replace(/\b\d{3}-\d{2}-\d{4}\b/g, '[ssn]')
    .replace(/\b(?:\d[ -]*?){13,19}\b/g, '[cc]')
    .slice(0, max);
}

export function track(name: EventName, props: EventProps = {}): void {
  if (typeof window === 'undefined') return;
  const enriched: EventProps = {
    ...props,
    path: window.location.pathname,
    ts: Date.now(),
  };
  // Vite injects import.meta.env at build time. Cast keeps TS happy without
  // adding a `vite/client` triple-slash reference (we don't want global types).
  const dev = (import.meta as unknown as { env?: { DEV?: boolean } }).env?.DEV;
  if (dev) {
    // eslint-disable-next-line no-console
    console.debug('[analytics]', name, enriched);
  }
  getQueue().push({ name, props: enriched, ts: Date.now() });
}

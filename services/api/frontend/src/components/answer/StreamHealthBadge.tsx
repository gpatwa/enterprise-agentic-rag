import { useEffect, useState } from 'react';
import { CircleDot, WifiOff } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  streaming: boolean;
  /** Last update timestamp (ms epoch) — used to detect a stalled stream. */
  lastUpdate: number;
  /** Turn start timestamp (ms epoch), used to show live TTFT while waiting. */
  startedAt?: number;
  /** Client-observed time to first token/delta. */
  firstTokenMs?: number | null;
  /** Server-observed TTFT when available. */
  serverFirstTokenMs?: number | null;
  /** ms without an event before we flag the stream as stalled. */
  stallMs?: number;
}

/**
 * Tiny badge that shows live/stalled status during a chat stream.
 * Watches `lastUpdate` and flips to "stalled" once the gap exceeds `stallMs`.
 */
export function StreamHealthBadge({
  streaming,
  lastUpdate,
  startedAt,
  firstTokenMs,
  serverFirstTokenMs,
  stallMs = 8_000,
}: Props) {
  const [stalled, setStalled] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!streaming) {
      setStalled(false);
      return;
    }
    setStalled(false);
    const id = window.setInterval(() => {
      setStalled(Date.now() - lastUpdate > stallMs);
    }, 1_000);
    return () => clearInterval(id);
  }, [streaming, lastUpdate, stallMs]);

  useEffect(() => {
    if (!streaming || firstTokenMs != null) return;
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [streaming, firstTokenMs]);

  if (!streaming && firstTokenMs == null) return null;

  const liveTtftMs = startedAt ? Math.max(now - startedAt, 0) : null;
  const ttftLabel =
    firstTokenMs != null
      ? `TTFT ${formatLatency(firstTokenMs)}`
      : liveTtftMs != null
        ? `TTFT ${formatLatency(liveTtftMs)} waiting`
        : 'Waiting for first token';
  const serverLabel =
    serverFirstTokenMs != null && serverFirstTokenMs !== firstTokenMs
      ? ` · server ${formatLatency(serverFirstTokenMs)}`
      : '';

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full border',
        stalled
          ? 'bg-governance/15 text-governance border-governance/25'
          : 'bg-knowledge/10 text-knowledge border-knowledge/25'
      )}
    >
      {stalled ? (
        <>
          <WifiOff className="w-3 h-3" />
          <span>{ttftLabel} · stalled{serverLabel}</span>
        </>
      ) : (
        <>
          <CircleDot className="w-3 h-3 animate-pulse" />
          <span>{firstTokenMs == null ? ttftLabel : `${ttftLabel} · Streaming`}{serverLabel}</span>
        </>
      )}
    </div>
  );
}

function formatLatency(ms: number) {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

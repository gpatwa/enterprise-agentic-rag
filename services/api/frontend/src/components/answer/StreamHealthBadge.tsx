import { useEffect, useState } from 'react';
import { CircleDot, WifiOff } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  streaming: boolean;
  /** Last update timestamp (ms epoch) — used to detect a stalled stream. */
  lastUpdate: number;
  /** ms without an event before we flag the stream as stalled. */
  stallMs?: number;
}

/**
 * Tiny badge that shows live/stalled status during a chat stream.
 * Watches `lastUpdate` and flips to "stalled" once the gap exceeds `stallMs`.
 */
export function StreamHealthBadge({ streaming, lastUpdate, stallMs = 8_000 }: Props) {
  const [stalled, setStalled] = useState(false);

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

  if (!streaming) return null;

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
          <span>Connection stalled — still waiting…</span>
        </>
      ) : (
        <>
          <CircleDot className="w-3 h-3 animate-pulse" />
          <span>Streaming</span>
        </>
      )}
    </div>
  );
}

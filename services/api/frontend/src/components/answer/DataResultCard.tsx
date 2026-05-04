import { useEffect, useRef, useState } from 'react';
import type { DataResultEvent } from '@/types/chat';
import { cn } from '@/lib/utils';

interface Props {
  result: DataResultEvent;
}

const PREVIEW_ROWS = 20;

export function DataResultCard({ result }: Props) {
  const { columns, rows, row_count, chart_spec } = result;
  const [showAll, setShowAll] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  // Lazy-load vega-embed only when a chart is actually present.
  // Saves ~1MB of JS from the initial bundle.
  useEffect(() => {
    if (!chart_spec || !chartRef.current) return;
    let cancelled = false;
    let viewHandle: { finalize?: () => void } | null = null;

    import('vega-embed')
      .then(({ default: vegaEmbed }) => {
        if (cancelled || !chartRef.current) return null;
        return vegaEmbed(chartRef.current, chart_spec, {
          actions: false,
          theme: 'dark',
          config: {
            background: 'transparent',
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            axis: { labelColor: '#9aa0b6', titleColor: '#e1e2e8', gridColor: '#252a3a' } as any,
            legend: { labelColor: '#9aa0b6', titleColor: '#e1e2e8' },
            title: { color: '#e1e2e8' },
          },
        });
      })
      .then((result) => {
        viewHandle = result?.view ?? null;
        if (cancelled) viewHandle?.finalize?.();
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn('vega-embed failed:', err);
      });

    return () => {
      cancelled = true;
      viewHandle?.finalize?.();
    };
  }, [chart_spec]);

  const visibleRows = showAll ? rows : rows.slice(0, PREVIEW_ROWS);

  return (
    <div className="space-y-4">
      {chart_spec && (
        <div className="glass rounded-lg p-3">
          <div ref={chartRef} className="w-full overflow-auto" />
        </div>
      )}

      <div className="glass rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/40 bg-surface-muted/30">
                {columns.map((col) => (
                  <th
                    key={col}
                    className="text-left px-4 py-2.5 font-medium text-fg-secondary text-xs uppercase tracking-wider"
                  >
                    {humanize(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {visibleRows.map((row, i) => (
                <tr key={i} className="hover:bg-white/[0.02] transition">
                  {columns.map((col) => (
                    <td
                      key={col}
                      className={cn(
                        'px-4 py-2',
                        typeof row[col] === 'number' && 'font-mono text-fg'
                      )}
                    >
                      {formatCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {row_count > PREVIEW_ROWS && (
          <button
            onClick={() => setShowAll(!showAll)}
            className="w-full text-xs text-fg-muted hover:text-fg py-2 border-t border-border/40 transition"
          >
            {showAll
              ? `Showing all ${row_count} rows · click to collapse`
              : `Showing ${PREVIEW_ROWS} of ${row_count} rows · click to expand`}
          </button>
        )}
      </div>
    </div>
  );
}

function humanize(col: string): string {
  return col
    .split(/[_\s]/)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

function formatCell(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (!Number.isInteger(v)) return v.toFixed(2);
    return String(v);
  }
  return String(v);
}

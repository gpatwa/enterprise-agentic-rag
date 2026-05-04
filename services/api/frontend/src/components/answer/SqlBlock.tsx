import { useState } from 'react';
import { ChevronDown, ChevronRight, Check, Copy } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  sql: string;
  timeMs: number;
}

export function SqlBlock({ sql, timeMs }: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore
    }
  };

  return (
    <div className="glass rounded-lg overflow-hidden text-sm">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-white/[0.03] transition text-left"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />
        )}
        <span className="font-medium text-fg flex-1">View SQL</span>
        {timeMs > 0 && (
          <span className="text-xs text-knowledge bg-knowledge/10 border border-knowledge/20 px-1.5 py-0.5 rounded font-mono">
            {timeMs}ms
          </span>
        )}
      </button>
      <div
        className={cn(
          'border-t border-border/40 overflow-hidden transition-all',
          open ? 'max-h-[420px]' : 'max-h-0'
        )}
      >
        <div className="relative">
          <button
            onClick={copy}
            className="absolute top-3 right-3 z-10 inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-surface-muted text-fg-muted hover:text-fg hover:bg-surface-elevated transition"
            aria-label="Copy SQL"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <pre className="font-mono text-xs leading-6 px-4 py-3 overflow-auto text-knowledge">
            {sql}
          </pre>
        </div>
      </div>
    </div>
  );
}

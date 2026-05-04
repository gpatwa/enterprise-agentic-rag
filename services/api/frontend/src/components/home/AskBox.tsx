import { useState } from 'react';
import { Sparkles, Mic, BarChart3, FileText, Code2, Globe } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { Scope } from '@/types';

const scopes: { id: Scope; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'auto', label: 'Auto', icon: Sparkles },
  { id: 'data', label: 'Data', icon: BarChart3 },
  { id: 'docs', label: 'Docs', icon: FileText },
  { id: 'code', label: 'Code', icon: Code2 },
  { id: 'web', label: 'Web', icon: Globe },
];

interface Props {
  onSubmit?: (query: string, scope: Scope) => void;
}

export function AskBox({ onSubmit }: Props) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<Scope>('auto');
  const [focused, setFocused] = useState(false);

  function submit() {
    const q = query.trim();
    if (!q) return;
    onSubmit?.(q, scope);
  }

  return (
    <div
      className={cn(
        'rounded-xl glass-strong overflow-hidden transition-shadow duration-200',
        focused && 'shadow-[0_0_0_1px_hsl(var(--accent)/0.3),0_8px_32px_-8px_hsl(var(--accent-from)/0.30)]'
      )}
    >
      <div className="px-5 pt-4 pb-2 flex items-start gap-3">
        <Sparkles className="w-5 h-5 text-accent mt-0.5 flex-shrink-0" />
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit();
          }}
          placeholder="Ask anything…"
          rows={1}
          className="flex-1 bg-transparent border-0 outline-none resize-none text-fg placeholder:text-fg-muted text-base leading-6 max-h-32"
        />
        <button
          aria-label="Voice input"
          className="text-fg-muted hover:text-fg transition flex-shrink-0"
        >
          <Mic className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 pb-3 flex items-center gap-1.5 border-t pt-2.5">
        {scopes.map((s) => {
          const active = scope === s.id;
          const Icon = s.icon;
          return (
            <button
              key={s.id}
              onClick={() => setScope(s.id)}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs flex items-center gap-1.5 transition border',
                active
                  ? 'bg-accent/15 text-accent border-accent/30 font-medium'
                  : 'border-transparent text-fg-secondary hover:bg-white/5'
              )}
            >
              <Icon className="w-3 h-3" />
              {s.label}
            </button>
          );
        })}
        <div className="flex-1" />
        <button
          onClick={submit}
          disabled={!query.trim()}
          className="px-3 py-1 rounded-md bg-accent-grad text-white text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 shadow-lg shadow-accent/20"
        >
          Send <span className="font-mono opacity-80">⌘↵</span>
        </button>
      </div>
    </div>
  );
}

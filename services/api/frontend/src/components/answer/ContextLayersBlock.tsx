import { useState } from 'react';
import { BookOpen, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  content: string;
}

/**
 * Renders the context-layers block (glossary terms, business rules, etc.)
 * that the agent applied before answering.
 */
export function ContextLayersBlock({ content }: Props) {
  const [open, setOpen] = useState(false);

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
        <BookOpen className="w-3.5 h-3.5 text-knowledge" />
        <span className="font-medium text-fg flex-1">Context applied</span>
      </button>
      <div
        className={cn(
          'border-t border-border/40 overflow-hidden transition-all',
          open ? 'max-h-[420px]' : 'max-h-0'
        )}
      >
        <pre className="font-mono text-xs leading-6 px-4 py-3 text-fg-secondary whitespace-pre-wrap">
          {content}
        </pre>
      </div>
    </div>
  );
}

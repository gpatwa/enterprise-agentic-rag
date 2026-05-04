import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { FileText } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  content: string;
  streaming?: boolean;
}

/**
 * Renders the synthesized answer with markdown + GFM (tables, strikethrough).
 * Pulls [Source: filename] tokens out and renders them as inline badges.
 */
export function AnswerText({ content, streaming }: Props) {
  const sourceRegex = /\[Source:\s*([^\]]+)\]/g;
  const sources = Array.from(content.matchAll(sourceRegex)).map((m) => m[1].trim());
  const cleaned = content.replace(sourceRegex, '').trim();

  return (
    <div className="space-y-3">
      <div
        className={cn(
          'prose prose-sm prose-invert max-w-none',
          'prose-headings:tracking-tight prose-headings:font-semibold',
          'prose-p:text-fg prose-p:leading-relaxed',
          'prose-strong:text-fg prose-strong:font-semibold',
          'prose-li:text-fg prose-ul:my-2 prose-ol:my-2',
          'prose-code:text-knowledge prose-code:bg-surface-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-code:text-xs',
          'prose-table:text-sm prose-th:text-fg-secondary prose-th:border-border prose-td:border-border'
        )}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleaned}</ReactMarkdown>
        {streaming && (
          <span className="inline-block w-1.5 h-4 ml-0.5 bg-accent rounded-sm align-middle animate-pulse" />
        )}
      </div>

      {sources.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {sources.map((s, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-knowledge/10 text-knowledge border border-knowledge/20"
            >
              <FileText className="w-3 h-3" />
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

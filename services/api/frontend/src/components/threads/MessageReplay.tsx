import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles, User } from 'lucide-react';
import type { ThreadMessage } from '@/types';
import { cn } from '@/lib/utils';

interface Props {
  messages: ThreadMessage[];
  isLoading?: boolean;
}

export function MessageReplay({ messages, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1].map((i) => (
          <div key={i} className="glass rounded-lg h-20 animate-pulse" />
        ))}
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="glass rounded-lg p-5 text-sm text-fg-secondary">
        <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">Conversation</div>
        <p>
          No messages yet. Ask a question below to start the thread.
        </p>
      </div>
    );
  }

  return (
    <ol className="space-y-3" aria-label="Message history">
      {messages.map((m) => (
        <Message key={m.id} message={m} />
      ))}
    </ol>
  );
}

function Message({ message }: { message: ThreadMessage }) {
  const isUser = message.role === 'user';
  return (
    <li
      className={cn(
        'flex items-start gap-3 px-4 py-3 rounded-lg',
        isUser ? 'glass' : 'glass-strong border border-border/60'
      )}
    >
      <div
        className={cn(
          'w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5',
          isUser ? 'bg-surface-muted text-fg-secondary' : 'bg-accent/15 text-accent'
        )}
      >
        {isUser ? <User className="w-3.5 h-3.5" /> : <Sparkles className="w-3.5 h-3.5" />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted mb-1.5">
          {isUser ? 'You' : 'Compass'} ·{' '}
          <time dateTime={message.created_at}>
            {new Date(message.created_at).toLocaleString(undefined, {
              dateStyle: 'medium',
              timeStyle: 'short',
            })}
          </time>
        </div>
        <div
          className={cn(
            'prose prose-sm prose-invert max-w-none',
            'prose-p:text-fg prose-p:leading-relaxed prose-p:my-1.5',
            'prose-strong:text-fg prose-strong:font-semibold',
            'prose-li:text-fg prose-ul:my-2 prose-ol:my-2',
            'prose-code:text-knowledge prose-code:bg-surface-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-code:text-xs'
          )}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {stripSourceTokens(message.content)}
          </ReactMarkdown>
        </div>
      </div>
    </li>
  );
}

function stripSourceTokens(s: string): string {
  return s.replace(/\[Source:\s*[^\]]+\]/g, '').trim();
}

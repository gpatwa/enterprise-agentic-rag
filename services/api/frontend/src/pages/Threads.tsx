import { Link } from 'react-router-dom';
import { MessageSquare, Pin, PinOff } from 'lucide-react';
import { usePinThread, useThreads } from '@/lib/queries';
import { useToast } from '@/components/ui/use-toast';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { Thread } from '@/types';
import { formatRelative } from '@/lib/format';

export function ThreadsPage() {
  const { data, isLoading, error } = useThreads({ limit: 50 });
  const threads = data?.threads ?? [];

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-8 py-12">
        <header className="mb-8">
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">Threads</div>
          <h1 className="text-2xl font-semibold tracking-tight">Your conversations</h1>
          <p className="text-fg-secondary mt-2 text-base">
            Persistent threads with full context, evidence, and audit trail.
          </p>
        </header>

        {isLoading && (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="glass rounded-md h-16 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="glass rounded-md p-4 text-sm text-fg-secondary">
            Couldn't load threads. Make sure the backend is reachable on{' '}
            <code className="font-mono">/api/v1/threads</code>.
          </div>
        )}

        {!isLoading && !error && threads.length === 0 && (
          <div className="glass rounded-xl px-8 py-16 text-center">
            <MessageSquare className="w-8 h-8 text-fg-muted mx-auto mb-4" />
            <h3 className="font-semibold text-base mb-2">No threads yet</h3>
            <p className="text-sm text-fg-secondary mb-6 max-w-sm mx-auto">
              Ask a question on the Home page. Threads persist across sessions and capture every step.
            </p>
            <Button asChild>
              <Link to="/">Go to Home</Link>
            </Button>
          </div>
        )}

        {!isLoading && !error && threads.length > 0 && (
          <TooltipProvider delayDuration={250}>
            <ul className="glass rounded-xl divide-y divide-border/40">
              {threads.map((t) => (
                <ThreadRow key={t.id} thread={t} />
              ))}
            </ul>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}

function ThreadRow({ thread }: { thread: Thread }) {
  const pin = usePinThread();
  const { toast } = useToast();

  const togglePin = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !thread.pinned;
    pin.mutate(
      { id: thread.id, pinned: next },
      {
        onSuccess: () =>
          toast({
            title: next ? 'Pinned thread' : 'Unpinned thread',
            description: thread.title,
          }),
        onError: () =>
          toast({
            title: 'Pin failed',
            description: 'Could not update pin state.',
            variant: 'destructive',
          }),
      }
    );
  };

  return (
    <li className="group">
      <Link
        to={`/threads/${thread.id}`}
        className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition"
      >
        <MessageSquare className="w-4 h-4 text-fg-muted flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">{thread.title}</div>
          <div className="text-xs text-fg-muted mt-0.5">
            {thread.message_count} messages · {formatRelative(thread.updated_at)}
          </div>
        </div>
        {thread.active && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/25">
            Active
          </span>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={togglePin}
              className="text-fg-muted hover:text-fg p-1.5 rounded-md hover:bg-white/5 transition opacity-0 group-hover:opacity-100"
              aria-label={thread.pinned ? 'Unpin thread' : 'Pin thread'}
            >
              {thread.pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
            </button>
          </TooltipTrigger>
          <TooltipContent>{thread.pinned ? 'Unpin' : 'Pin'}</TooltipContent>
        </Tooltip>
      </Link>
    </li>
  );
}

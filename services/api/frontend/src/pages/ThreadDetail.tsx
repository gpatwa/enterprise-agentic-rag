import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AskBox } from '@/components/home/AskBox';
import { AnswerCard } from '@/components/answer/AnswerCard';
import { SavedQuestionDialog } from '@/components/saved/SavedQuestionDialog';
import { useAsk } from '@/lib/useAsk';
import { useToast } from '@/components/ui/use-toast';
import { formatRelative } from '@/lib/format';
import type { Thread } from '@/types';

interface ThreadDetailResponse extends Thread {
  pinned?: boolean;
}

export function ThreadDetailPage() {
  const { threadId = '' } = useParams<{ threadId: string }>();
  const { turn, ask } = useAsk();
  const { toast } = useToast();
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [pendingSaveQuestion, setPendingSaveQuestion] = useState('');

  const {
    data: thread,
    isLoading,
    error,
  } = useQuery<ThreadDetailResponse>({
    queryKey: ['threads', threadId],
    queryFn: async () => {
      const { api } = await import('@/lib/api');
      // No specific GET helper yet — call the endpoint directly.
      const res = await fetch(`/api/v1/threads/${threadId}`, {
        headers: {
          Authorization: `Bearer ${await (await import('@/lib/api')).getToken()}`,
        },
      });
      if (!res.ok) throw new Error(`thread fetch failed: ${res.status}`);
      void api;
      return res.json();
    },
    enabled: Boolean(threadId),
  });

  const handleAsk = (q: string) => ask(q, { sessionId: threadId });

  const handleSaveTurn = (q: string) => {
    setPendingSaveQuestion(q);
    setSaveDialogOpen(true);
  };

  if (error) {
    return (
      <div className="flex-1 overflow-auto">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
          <Button asChild variant="ghost" size="sm">
            <Link to="/threads">
              <ArrowLeft className="w-4 h-4" />
              All threads
            </Link>
          </Button>
          <div className="glass rounded-md p-4 text-sm text-fg-secondary mt-6">
            Couldn't load this thread. It may have been deleted, or the backend isn't reachable.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        {/* Breadcrumb */}
        <Button asChild variant="ghost" size="sm" className="mb-6 -ml-2">
          <Link to="/threads">
            <ArrowLeft className="w-4 h-4" />
            All threads
          </Link>
        </Button>

        {/* Header */}
        {isLoading ? (
          <div className="space-y-3 mb-8">
            <div className="h-7 w-2/3 bg-surface-muted rounded animate-pulse" />
            <div className="h-4 w-1/3 bg-surface-muted rounded animate-pulse" />
          </div>
        ) : (
          thread && (
            <header className="mb-8">
              <div className="flex items-center gap-2 text-xs text-fg-muted mb-2">
                <MessageSquare className="w-3.5 h-3.5" />
                <span>Thread</span>
                {thread.pinned && (
                  <span className="ml-1 px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/25">
                    Pinned
                  </span>
                )}
              </div>
              <h1 className="text-2xl font-semibold tracking-tight leading-tight text-fg">
                {thread.title}
              </h1>
              <div className="text-sm text-fg-muted mt-2">
                {thread.message_count} messages · last activity {formatRelative(thread.updated_at)}
              </div>
            </header>
          )
        )}

        {/* History placeholder (W2 will render full message replay) */}
        <div className="glass rounded-lg p-5 text-sm text-fg-secondary mb-6">
          <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">Conversation</div>
          <p>
            Compass loads prior context from this thread automatically when you continue.
            <span className="text-fg-muted"> Full message replay ships in W2.</span>
          </p>
        </div>

        {/* Active turn */}
        {turn && (
          <div className="mb-6">
            <AnswerCard turn={turn} onSave={handleSaveTurn} />
          </div>
        )}

        {/* Continue */}
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-wider text-fg-muted">Continue the conversation</div>
          <AskBox
            onSubmit={(q) => {
              if (!q.trim()) {
                toast({ title: 'Empty question', variant: 'destructive' });
                return;
              }
              handleAsk(q);
            }}
          />
        </div>

        <div className="h-12" />
      </div>

      <SavedQuestionDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        initialQuestion={pendingSaveQuestion}
        initialTitle={pendingSaveQuestion.slice(0, 60)}
      />
    </div>
  );
}

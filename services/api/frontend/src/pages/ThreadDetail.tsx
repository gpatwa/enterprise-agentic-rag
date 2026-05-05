import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AskBox } from '@/components/home/AskBox';
import { AnswerCard } from '@/components/answer/AnswerCard';
import { SourcesReasoningRail } from '@/components/answer/SourcesReasoningRail';
import { SavedQuestionDialog } from '@/components/saved/SavedQuestionDialog';
import { MessageReplay } from '@/components/threads/MessageReplay';
import { useAsk } from '@/lib/useAsk';
import { useThread, useThreadMessages } from '@/lib/queries';
import { useToast } from '@/components/ui/use-toast';
import { formatRelative } from '@/lib/format';

export function ThreadDetailPage() {
  const { threadId = '' } = useParams<{ threadId: string }>();
  const { turn, ask, lastUpdate } = useAsk();
  const { toast } = useToast();
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [pendingSaveQuestion, setPendingSaveQuestion] = useState('');

  const { data: thread, isLoading: threadLoading, error: threadError } = useThread(threadId);
  const { data: msgs, isLoading: msgsLoading } = useThreadMessages(threadId);
  const messages = msgs?.messages ?? [];

  const handleAsk = (q: string) => ask(q, { sessionId: threadId });
  const handleSaveTurn = (q: string) => {
    setPendingSaveQuestion(q);
    setSaveDialogOpen(true);
  };

  if (threadError) {
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
    <>
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
        {threadLoading ? (
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

        {/* Message replay */}
        <div className="mb-6">
          <MessageReplay messages={messages} isLoading={msgsLoading} />
        </div>

        {/* Active turn */}
        {turn && (
          <div className="mb-6">
            <AnswerCard
              turn={turn}
              onSave={handleSaveTurn}
              onFollowUp={(q) => ask(q, { sessionId: threadId })}
              lastUpdate={lastUpdate}
            />
          </div>
        )}

        {/* Continue */}
        <div className="space-y-2 sticky bottom-0 pt-4 pb-4 bg-bg/80 backdrop-blur-sm">
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
      </div>

      <SavedQuestionDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        initialQuestion={pendingSaveQuestion}
        initialTitle={pendingSaveQuestion.slice(0, 60)}
      />
      </div>

      {/* Right-rail trace when a turn is active */}
      {turn && <SourcesReasoningRail turn={turn} />}
    </>
  );
}

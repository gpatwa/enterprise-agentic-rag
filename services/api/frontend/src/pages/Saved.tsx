import { Bookmark, BookmarkX, Plus, Play, Trash2 } from 'lucide-react';
import {
  useDeleteSavedQuestion,
  useSavedQuestions,
  useUpdateSavedQuestion,
} from '@/lib/queries';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { SavedQuestionDialog } from '@/components/saved/SavedQuestionDialog';
import type { SavedQuestionDetail } from '@/types';
import { formatRelative } from '@/lib/format';

export function SavedPage() {
  const { data, isLoading, error } = useSavedQuestions();
  const items = data?.saved_questions ?? [];

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-8 flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">Saved</div>
            <h1 className="text-2xl font-semibold tracking-tight">Saved questions</h1>
            <p className="text-fg-secondary mt-2 text-base max-w-2xl">
              Bookmarked questions you can re-run on demand. Each saved question caches its last
              result preview.
            </p>
          </div>
          <SavedQuestionDialog />
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
            Couldn't load saved questions. Make sure the backend is reachable on{' '}
            <code className="font-mono">/api/v1/saved-questions</code>.
          </div>
        )}

        {!isLoading && !error && items.length === 0 && (
          <div className="glass rounded-xl px-8 py-16 text-center">
            <Bookmark className="w-8 h-8 text-fg-muted mx-auto mb-4" />
            <h3 className="font-semibold text-base mb-2">No saved questions yet</h3>
            <p className="text-sm text-fg-secondary mb-6 max-w-sm mx-auto">
              Save a question to re-run it later. Saved questions can be pinned to your Home page.
            </p>
            <SavedQuestionDialog
              trigger={
                <Button>
                  <Plus className="w-4 h-4" />
                  Save your first question
                </Button>
              }
            />
          </div>
        )}

        {!isLoading && !error && items.length > 0 && (
          <TooltipProvider delayDuration={250}>
            <ul className="glass rounded-xl divide-y divide-border/40">
              {items.map((q) => (
                <SavedRow key={q.id} q={q} />
              ))}
            </ul>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}

function SavedRow({ q }: { q: SavedQuestionDetail }) {
  const update = useUpdateSavedQuestion();
  const del = useDeleteSavedQuestion();
  const { toast } = useToast();

  const togglePin = () => {
    update.mutate(
      { id: q.id, patch: { pinned: !q.pinned } },
      {
        onSuccess: () =>
          toast({
            title: q.pinned ? 'Unpinned' : 'Pinned to Home',
            description: q.title,
          }),
      }
    );
  };

  const remove = () => {
    if (!confirm(`Delete "${q.title}"?`)) return;
    del.mutate(q.id, {
      onSuccess: () => toast({ title: 'Deleted', description: q.title }),
    });
  };

  return (
    <li className="group flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition">
      <Bookmark
        className={`w-4 h-4 flex-shrink-0 ${q.pinned ? 'text-accent fill-accent' : 'text-fg-muted'}`}
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg truncate">{q.title}</div>
        <div className="text-xs text-fg-muted mt-0.5 truncate">
          {q.last_run_at ? `Last run ${formatRelative(q.last_run_at)} · ` : 'Never run · '}
          <span className="font-mono">{q.scope}</span>
        </div>
      </div>

      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              className="text-fg-muted hover:text-fg p-1.5 rounded-md hover:bg-white/5 transition"
              aria-label="Re-run"
            >
              <Play className="w-3.5 h-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Re-run</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={togglePin}
              className="text-fg-muted hover:text-fg p-1.5 rounded-md hover:bg-white/5 transition"
              aria-label={q.pinned ? 'Unpin' : 'Pin to home'}
            >
              {q.pinned ? (
                <BookmarkX className="w-3.5 h-3.5" />
              ) : (
                <Bookmark className="w-3.5 h-3.5" />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent>{q.pinned ? 'Unpin' : 'Pin to home'}</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={remove}
              className="text-fg-muted hover:text-destructive p-1.5 rounded-md hover:bg-white/5 transition"
              aria-label="Delete"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Delete</TooltipContent>
        </Tooltip>
      </div>
    </li>
  );
}

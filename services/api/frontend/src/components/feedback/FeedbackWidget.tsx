import { useState } from 'react';
import { Bug, Lightbulb, Loader2, MessageCircle, MessageSquarePlus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/components/ui/use-toast';
import { useSubmitFeedback } from '@/lib/queries';
import { cn } from '@/lib/utils';

type Category = 'bug' | 'idea' | 'comment';

const CATEGORIES: {
  id: Category;
  label: string;
  icon: typeof Bug;
  hint: string;
}[] = [
  { id: 'bug', label: 'Bug', icon: Bug, hint: 'Something is broken or wrong.' },
  {
    id: 'idea',
    label: 'Idea',
    icon: Lightbulb,
    hint: 'Suggestion or feature request.',
  },
  {
    id: 'comment',
    label: 'Comment',
    icon: MessageCircle,
    hint: 'General thought or reaction.',
  },
];

const MIN_MESSAGE_LENGTH = 4;
const MAX_MESSAGE_LENGTH = 4000;

/**
 * Always-visible "Send feedback" button + modal. Mounts once at the AppShell
 * level so it's reachable from every in-app surface. Submissions go to
 * `POST /api/v1/feedback` — which audit-logs and (best-effort) relays to
 * the team's Slack channel via an incoming webhook.
 *
 * Hidden when `VITE_FEEDBACK_DISABLED=1` so the marketing /welcome page
 * (which mounts a different layout) doesn't pick it up; we don't want
 * anonymous visitors using the in-app feedback path.
 */
export function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const env = (
    import.meta as unknown as { env?: { VITE_FEEDBACK_DISABLED?: string } }
  ).env;
  if (env?.VITE_FEEDBACK_DISABLED === '1') {
    return null;
  }

  return (
    <>
      <button
        type="button"
        aria-label="Send feedback"
        onClick={() => setOpen(true)}
        className={cn(
          'fixed bottom-4 right-4 z-30',
          'inline-flex items-center gap-2 px-4 py-2.5 rounded-full',
          'bg-accent text-accent-fg shadow-lg shadow-accent/20 ring-1 ring-accent/40',
          'hover:bg-accent/90 active:scale-[0.98] transition',
          'text-sm font-medium',
          // Mobile-first: always visible bottom-right; bottom tab bar
          // (h-14 ≈ 56px) sits above 0px, so we pull above it on small screens.
          'mb-14 md:mb-0'
        )}
      >
        <MessageSquarePlus className="w-4 h-4" aria-hidden="true" />
        <span className="hidden sm:inline">Feedback</span>
      </button>
      <FeedbackDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

function FeedbackDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  const { toast } = useToast();
  const [category, setCategory] = useState<Category>('comment');
  const [message, setMessage] = useState('');
  const submitMut = useSubmitFeedback();

  const reset = () => {
    setCategory('comment');
    setMessage('');
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = message.trim();
    if (trimmed.length < MIN_MESSAGE_LENGTH) {
      toast({
        title: 'Tell us a bit more',
        description: `Need at least ${MIN_MESSAGE_LENGTH} characters.`,
        variant: 'destructive',
      });
      return;
    }
    submitMut.mutate(
      {
        message: trimmed,
        category,
        current_url: typeof window !== 'undefined' ? window.location.href : undefined,
        user_agent:
          typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
      },
      {
        onSuccess: (res) => {
          if (res.relayed_to_slack) {
            toast({ title: 'Thanks — feedback sent to the team' });
          } else {
            // Slack down or webhook unconfigured. Audit log captured it,
            // so we still tell the user it's recorded.
            toast({
              title: 'Thanks — feedback recorded',
              description: 'We saved it locally; Slack relay is offline.',
            });
          }
          reset();
          onOpenChange(false);
        },
        onError: (err: Error) => {
          toast({
            title: 'Could not send feedback',
            description: err.message,
            variant: 'destructive',
          });
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Send feedback</DialogTitle>
          <DialogDescription>
            Anything broken, confusing, or missing? Tell us — it goes
            straight to the team channel.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div role="radiogroup" aria-label="Category" className="grid grid-cols-3 gap-2">
            {CATEGORIES.map((c) => {
              const selected = category === c.id;
              return (
                <button
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  key={c.id}
                  onClick={() => setCategory(c.id)}
                  className={cn(
                    'flex flex-col items-center gap-1 px-3 py-3 rounded-lg border text-xs font-medium transition',
                    selected
                      ? 'bg-accent/10 border-accent text-accent ring-1 ring-accent/40'
                      : 'bg-surface-muted border-border text-fg-secondary hover:text-fg hover:border-border-strong'
                  )}
                >
                  <c.icon className="w-4 h-4" aria-hidden="true" />
                  <span>{c.label}</span>
                </button>
              );
            })}
          </div>
          <p className="text-xs text-fg-muted -mt-2">
            {CATEGORIES.find((c) => c.id === category)?.hint}
          </p>

          <div className="space-y-1.5">
            <label
              htmlFor="feedback-message"
              className="text-xs uppercase tracking-widest text-fg-muted font-medium"
            >
              What happened?
            </label>
            <textarea
              id="feedback-message"
              required
              minLength={MIN_MESSAGE_LENGTH}
              maxLength={MAX_MESSAGE_LENGTH}
              rows={5}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={
                category === 'bug'
                  ? 'Describe what you expected vs what happened. Include the steps if you can.'
                  : category === 'idea'
                    ? 'What would you want it to do?'
                    : 'Anything on your mind…'
              }
              className="w-full rounded-md bg-surface-muted border border-border px-3 py-2 text-sm text-fg placeholder:text-fg-muted focus:outline-none focus:border-accent resize-none"
            />
            <div className="text-[11px] text-fg-muted text-right tabular-nums">
              {message.length} / {MAX_MESSAGE_LENGTH}
            </div>
          </div>

          <DialogFooter className="flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
            <span className="text-[11px] text-fg-muted">
              We attach the page URL + your user id automatically.
            </span>
            <div className="flex items-center gap-2 self-end sm:self-auto">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                <X className="w-3.5 h-3.5" />
                Cancel
              </Button>
              <Button type="submit" disabled={submitMut.isPending}>
                {submitMut.isPending && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                )}
                Send
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

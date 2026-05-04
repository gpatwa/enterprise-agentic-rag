import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useToast } from '@/components/ui/use-toast';
import { useCreateSavedQuestion } from '@/lib/queries';

interface Props {
  /** Optional custom trigger; falls back to a "New saved question" button. */
  trigger?: React.ReactNode;
  /** Open state — controlled mode. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Pre-fill the form (used by the answer card "Save" action). */
  initialQuestion?: string;
  initialTitle?: string;
}

export function SavedQuestionDialog({
  trigger,
  open: controlledOpen,
  onOpenChange,
  initialQuestion = '',
  initialTitle = '',
}: Props) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;

  const [title, setTitle] = useState(initialTitle);
  const [questionText, setQuestionText] = useState(initialQuestion);
  const [pinToHome, setPinToHome] = useState(false);
  const create = useCreateSavedQuestion();
  const { toast } = useToast();

  // Sync prefill when the dialog opens with new defaults
  useEffect(() => {
    if (open) {
      setTitle(initialTitle || initialQuestion.slice(0, 60));
      setQuestionText(initialQuestion);
      setPinToHome(false);
    }
  }, [open, initialQuestion, initialTitle]);

  const submit = () => {
    if (!title.trim() || !questionText.trim()) return;
    create.mutate(
      {
        title: title.trim(),
        question_text: questionText.trim(),
        pinned: pinToHome,
      },
      {
        onSuccess: () => {
          toast({ title: 'Saved', description: title });
          setOpen(false);
        },
        onError: () =>
          toast({
            title: 'Save failed',
            description: 'Could not save question. Try again.',
            variant: 'destructive',
          }),
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger !== undefined && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      {trigger === undefined && controlledOpen === undefined && (
        <DialogTrigger asChild>
          <Button>
            <Plus className="w-4 h-4" />
            New saved question
          </Button>
        </DialogTrigger>
      )}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save a question</DialogTitle>
          <DialogDescription>
            Bookmark to re-run later. Pinned questions show on your Home page.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label htmlFor="sq-title" className="text-xs text-fg-muted block mb-1">
              Title
            </label>
            <Input
              id="sq-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Revenue by month last year"
              className="glass border"
            />
          </div>
          <div>
            <label htmlFor="sq-question" className="text-xs text-fg-muted block mb-1">
              Question
            </label>
            <textarea
              id="sq-question"
              value={questionText}
              onChange={(e) => setQuestionText(e.target.value)}
              placeholder="The full question Compass will run"
              rows={3}
              className="glass border w-full rounded-md px-3 py-2 text-sm resize-none"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-fg-secondary cursor-pointer select-none">
            <input
              type="checkbox"
              checked={pinToHome}
              onChange={(e) => setPinToHome(e.target.checked)}
              className="accent-accent"
            />
            Pin to Home page
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={!title.trim() || !questionText.trim() || create.isPending}
          >
            {create.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

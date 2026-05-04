import { Bookmark } from 'lucide-react';
import type { PinnedQuestion } from '@/types';

interface Props {
  questions: PinnedQuestion[];
  onRerun?: (id: string) => void;
}

export function Pinned({ questions, onRerun }: Props) {
  if (questions.length === 0) return null;
  return (
    <section className="mt-10">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-xs uppercase tracking-wider text-fg-muted font-medium">
          Pinned · {questions.length}
        </h2>
        <div className="flex-1 h-px bg-white/5" />
      </div>
      <div className="glass rounded-xl overflow-hidden divide-y divide-border/40">
        {questions.map((q) => (
          <a
            key={q.id}
            href={`#thread/${q.id}`}
            className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition group"
          >
            <Bookmark className="w-4 h-4 text-accent flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-fg">{q.title}</div>
              {q.last_run_at && (
                <div className="text-xs text-fg-muted mt-0.5">
                  {q.last_result_preview || `Last run ${formatRelative(q.last_run_at)}`}
                </div>
              )}
            </div>
            <button
              onClick={(e) => {
                e.preventDefault();
                onRerun?.(q.id);
              }}
              className="text-xs text-fg-muted hover:text-fg opacity-0 group-hover:opacity-100 transition"
            >
              Re-run
            </button>
          </a>
        ))}
      </div>
    </section>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const min = Math.round(diffMs / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

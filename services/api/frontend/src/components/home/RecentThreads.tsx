import { MessageSquare } from 'lucide-react';
import type { Thread } from '@/types';
import { formatRelative } from '@/lib/format';

interface Props {
  threads: Thread[];
}

export function RecentThreads({ threads }: Props) {
  if (threads.length === 0) return null;
  return (
    <section className="mt-10">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-xs uppercase tracking-wider text-fg-muted font-medium">
          Recent threads
        </h2>
        <div className="flex-1 h-px bg-white/5" />
        <a className="text-xs text-fg-muted hover:text-fg transition" href="/threads">
          View all →
        </a>
      </div>
      <div className="space-y-1">
        {threads.map((t) => (
          <a
            key={t.id}
            href={`/threads/${t.id}`}
            className="flex items-center gap-3 px-3 py-2.5 rounded-md hover:bg-white/[0.03] transition"
          >
            <MessageSquare className="w-4 h-4 text-fg-muted flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-fg truncate">{t.title}</div>
              <div className="text-xs text-fg-muted mt-0.5">
                {t.message_count} messages · {formatRelative(t.updated_at)}
              </div>
            </div>
            {t.active && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/25">
                Active
              </span>
            )}
          </a>
        ))}
      </div>
    </section>
  );
}


import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bookmark,
  LayoutDashboard,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useSavedQuestions } from '@/lib/queries';
import { useAsk } from '@/lib/useAsk';
import { AnswerCard } from '@/components/answer/AnswerCard';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { formatRelative } from '@/lib/format';
import type { SavedQuestionDetail } from '@/types';

/**
 * /dashboards
 *
 * MVP composer: every saved question with `pinned=true` becomes a tile.
 * Click "Re-run" on a tile to execute that question and render the live
 * AnswerCard inline. The dashboard is a Spotter-style "view multiple
 * questions in one place" surface.
 *
 * Future (W3+): explicit Dashboard records (title, owner, layout, refresh
 * schedule), drag-to-reorder, saved chart views.
 */
export function DashboardsPage() {
  const { data, isLoading, error } = useSavedQuestions({ pinnedOnly: true });
  const tiles = data?.saved_questions ?? [];

  // One ask hook for the active "running" tile. Single-active to keep it simple.
  const { turn, ask, reset, lastUpdate } = useAsk();
  const [runningId, setRunningId] = useState<string | null>(null);

  const runTile = (q: SavedQuestionDetail) => {
    setRunningId(q.id);
    ask(q.question_text);
  };

  const closeActive = () => {
    setRunningId(null);
    reset();
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-8 flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">
              Dashboards
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">Your dashboard</h1>
            <p className="text-fg-secondary mt-2 text-base max-w-2xl">
              Pinned saved questions, ready to re-run. Click any tile to refresh its answer
              against your latest data.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link to="/saved">
              <Bookmark className="w-4 h-4" />
              Manage saved questions
            </Link>
          </Button>
        </header>

        {isLoading && (
          <div className="grid sm:grid-cols-2 gap-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="glass rounded-xl h-36 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="glass rounded-md p-4 text-sm text-fg-secondary">
            Couldn't load dashboards. Make sure the backend is reachable.
          </div>
        )}

        {!isLoading && !error && tiles.length === 0 && <EmptyState />}

        {!isLoading && !error && tiles.length > 0 && (
          <TooltipProvider delayDuration={250}>
            {/* Active turn appears above the grid */}
            {turn && runningId && (
              <div className="mb-6">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs uppercase tracking-widest text-fg-muted">
                    Running
                  </div>
                  <button
                    onClick={closeActive}
                    className="text-xs text-fg-muted hover:text-fg transition"
                  >
                    Close
                  </button>
                </div>
                <AnswerCard turn={turn} lastUpdate={lastUpdate} />
              </div>
            )}

            {/* Tile grid */}
            <div className="grid sm:grid-cols-2 gap-3">
              {tiles.map((q) => (
                <Tile
                  key={q.id}
                  q={q}
                  isRunning={runningId === q.id && turn?.streaming === true}
                  onRun={() => runTile(q)}
                />
              ))}
            </div>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}

function Tile({
  q,
  isRunning,
  onRun,
}: {
  q: SavedQuestionDetail;
  isRunning: boolean;
  onRun: () => void;
}) {
  return (
    <article className="glass rounded-xl p-5 hover:border-border-strong transition group">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-8 h-8 rounded-md bg-accent/15 text-accent flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-base text-fg truncate">{q.title}</h3>
          <div className="text-xs text-fg-muted mt-0.5">
            {q.last_run_at ? `Last run ${formatRelative(q.last_run_at)}` : 'Never run'}
            {' · '}
            <span className="font-mono">{q.scope}</span>
          </div>
        </div>
      </div>

      {q.last_result_preview && (
        <p className="text-sm text-fg-secondary leading-relaxed mb-4 line-clamp-3">
          {q.last_result_preview}
        </p>
      )}

      <div className="flex items-center justify-between">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="sm" onClick={onRun} disabled={isRunning}>
              {isRunning ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Running…
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  Re-run
                </>
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Run this question against your latest data</TooltipContent>
        </Tooltip>
        <span
          className="text-xs text-fg-muted truncate max-w-[60%]"
          title={q.question_text}
        >
          {q.question_text}
        </span>
      </div>
    </article>
  );
}

function EmptyState() {
  return (
    <div className="glass rounded-xl px-8 py-16 text-center">
      <LayoutDashboard className="w-8 h-8 text-fg-muted mx-auto mb-4" />
      <h3 className="font-semibold text-base mb-2">Your dashboard is empty</h3>
      <p className="text-sm text-fg-secondary mb-6 max-w-md mx-auto leading-relaxed">
        Pin a saved question to add it here. Tiles re-run on demand against your latest data,
        so your answers stay fresh.
      </p>
      <Button asChild>
        <Link to="/saved">
          <Plus className="w-4 h-4" />
          Browse saved questions
        </Link>
      </Button>
    </div>
  );
}

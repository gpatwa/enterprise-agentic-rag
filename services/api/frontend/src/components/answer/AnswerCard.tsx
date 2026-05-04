import {
  AlertCircle,
  Bookmark,
  ExternalLink,
  Sparkles,
  Star,
  type LucideIcon,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { AskTurn } from '@/types/chat';
import { PipelineStatus } from './PipelineStatus';
import { SqlBlock } from './SqlBlock';
import { DataResultCard } from './DataResultCard';
import { AnswerText } from './AnswerText';
import { ContextLayersBlock } from './ContextLayersBlock';

interface Props {
  turn: AskTurn;
  onSave?: (q: string) => void;
}

export function AnswerCard({ turn, onSave }: Props) {
  return (
    <article className="glass-strong rounded-xl border border-border/60 p-5 space-y-4">
      {/* Header — user question + pipeline */}
      <header className="flex items-start gap-3">
        <div className="w-7 h-7 rounded-full bg-accent/15 text-accent flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-3.5 h-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-fg font-medium text-base leading-snug">{turn.question}</h3>
          <div className="mt-2">
            <PipelineStatus steps={turn.steps} streaming={turn.streaming} />
          </div>
        </div>
      </header>

      {/* Data analytics: SQL + result table/chart */}
      {turn.sql && <SqlBlock sql={turn.sql.sql} timeMs={turn.sql.timeMs} />}
      {turn.dataResult && <DataResultCard result={turn.dataResult} />}
      {turn.dataError && (
        <div className="glass rounded-lg p-3 flex items-start gap-2 text-sm border border-destructive/30">
          <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="font-medium text-destructive mb-0.5">Query error</div>
            <div className="text-fg-secondary">{turn.dataError}</div>
          </div>
        </div>
      )}

      {/* Context layers (collapsible) */}
      {turn.contextLayers && <ContextLayersBlock content={turn.contextLayers} />}

      {/* Tool results (web search, calculator, etc.) */}
      {turn.toolResults.map((tr, i) => (
        <div key={i} className="glass rounded-lg p-3 text-sm">
          <div className="text-xs text-fg-muted mb-1 font-medium uppercase tracking-wider">
            {tr.tool}
          </div>
          <pre className="text-fg-secondary whitespace-pre-wrap font-mono text-xs leading-relaxed">
            {tr.content}
          </pre>
        </div>
      ))}

      {/* Multimodal images */}
      {turn.images.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {turn.images.map((img, i) => (
            <a
              key={i}
              href={img.url}
              target="_blank"
              rel="noreferrer"
              className="block glass rounded-md overflow-hidden hover:border-border-strong transition"
            >
              <img
                src={img.url}
                alt={img.caption ?? img.filename ?? 'Retrieved image'}
                className="w-full aspect-square object-cover"
                loading="lazy"
              />
              {(img.caption || img.filename) && (
                <div className="text-xs text-fg-muted px-2 py-1 truncate">
                  {img.caption ?? img.filename}
                </div>
              )}
            </a>
          ))}
        </div>
      )}

      {/* Final answer */}
      {turn.answer && <AnswerText content={turn.answer} streaming={turn.streaming} />}

      {/* Stream error */}
      {turn.error && (
        <div className="glass rounded-lg p-3 flex items-start gap-2 text-sm border border-destructive/30">
          <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
          <span className="text-fg-secondary">{turn.error}</span>
        </div>
      )}

      {/* Footer — actions */}
      {(turn.answer || turn.dataResult) && !turn.streaming && (
        <footer className="flex items-center gap-2 pt-3 border-t border-border/40">
          {turn.evalScore !== null && turn.evalScore > 0 && (
            <span
              className="inline-flex items-center gap-1 text-xs text-fg-muted"
              title={turn.evalReason ?? ''}
            >
              <Star className="w-3 h-3 text-governance" />
              <span>{turn.evalScore.toFixed(1)} / 5</span>
            </span>
          )}
          <div className="flex-1" />
          <TooltipProvider delayDuration={300}>
            {onSave && (
              <ActionButton
                icon={Bookmark}
                label="Save"
                onClick={() => onSave(turn.question)}
              />
            )}
            {turn.sessionId && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button asChild variant="ghost" size="sm">
                    <Link to={`/threads/${turn.sessionId}`}>
                      <ExternalLink className="w-3.5 h-3.5" />
                      Open in thread
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Open the full thread view</TooltipContent>
              </Tooltip>
            )}
          </TooltipProvider>
        </footer>
      )}
    </article>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="sm" onClick={onClick}>
          <Icon className="w-3.5 h-3.5" />
          {label}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label} this question</TooltipContent>
    </Tooltip>
  );
}

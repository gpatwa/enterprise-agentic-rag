import {
  Brain,
  Search,
  Sparkles,
  Wrench,
  FileSearch,
  RotateCw,
  ArrowRight,
  BookOpen,
  BarChart3,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const ICONS: Record<string, LucideIcon> = {
  planner: Brain,
  retriever: Search,
  responder: Sparkles,
  tool_node: Wrench,
  evaluator: FileSearch,
  retry: RotateCw,
  step_advance: ArrowRight,
  context_enricher: BookOpen,
  data_analytics: BarChart3,
};

const LABELS: Record<string, string> = {
  planner: 'Plan',
  retriever: 'Retrieve',
  responder: 'Synthesize',
  tool_node: 'Tool',
  evaluator: 'Evaluate',
  retry: 'Retry',
  step_advance: 'Step',
  context_enricher: 'Apply context',
  data_analytics: 'Query data',
};

interface Props {
  steps: { node: string; at: number }[];
  streaming: boolean;
}

export function PipelineStatus({ steps, streaming }: Props) {
  if (steps.length === 0) {
    return streaming ? (
      <div className="text-xs text-fg-muted animate-pulse">Routing question…</div>
    ) : null;
  }

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {steps.map((s, i) => {
        const isLast = i === steps.length - 1;
        const Icon = ICONS[s.node] ?? Brain;
        const isRetry = s.node === 'retry';
        const active = isLast && streaming;
        return (
          <span
            key={`${s.node}-${i}`}
            className={cn(
              'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border',
              isRetry
                ? 'bg-destructive/10 text-destructive border-destructive/20'
                : active
                  ? 'bg-accent/15 text-accent border-accent/30'
                  : 'bg-knowledge/10 text-knowledge border-knowledge/20'
            )}
            title={LABELS[s.node] ?? s.node}
          >
            <Icon className={cn('w-3 h-3', active && 'animate-pulse')} />
            <span>{LABELS[s.node] ?? s.node}</span>
          </span>
        );
      })}
    </div>
  );
}

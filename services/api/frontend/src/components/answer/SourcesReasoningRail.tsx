import {
  Activity,
  AlertCircle,
  BarChart3,
  BookOpen,
  Brain,
  Check,
  CheckCircle2,
  Database,
  FileText,
  Search,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import type { AskTurn } from '@/types/chat';

const NODE_ICONS: Record<string, LucideIcon> = {
  planner: Brain,
  retriever: Search,
  responder: Sparkles,
  tool_node: Wrench,
  evaluator: CheckCircle2,
  context_enricher: BookOpen,
  data_analytics: BarChart3,
};

const NODE_LABELS: Record<string, string> = {
  planner: 'Plan',
  retriever: 'Retrieve',
  responder: 'Synthesize',
  tool_node: 'Tool',
  evaluator: 'Evaluate',
  context_enricher: 'Apply context',
  data_analytics: 'Query data',
  retry: 'Retry',
  step_advance: 'Step',
};

interface Props {
  turn: AskTurn;
}

/**
 * Right-rail panel that surfaces the trace, sources, and governance signals
 * for the active turn. Replaces the global RightRail when an answer is in flight.
 */
export function SourcesReasoningRail({ turn }: Props) {
  const sourceCount = countSources(turn);

  return (
    <aside className="hidden lg:block w-[300px] glass border-l overflow-auto">
      <div className="px-5 py-5 space-y-6">
        {/* Header */}
        <div>
          <div className="text-xs uppercase tracking-widest text-fg-muted font-medium mb-2">
            Sources &amp; Reasoning
          </div>
          <p className="text-xs text-fg-secondary leading-relaxed">
            Every answer ships with the path it took, the data it used, and the policy applied.
          </p>
        </div>

        {/* Plan trace */}
        <Section
          icon={Activity}
          label={`Plan ${turn.streaming ? '· running' : '· complete'}`}
        >
          {turn.steps.length === 0 ? (
            <div className="text-xs text-fg-muted">Routing question…</div>
          ) : (
            <ol className="space-y-1.5">
              {turn.steps.map((s, i) => {
                const Icon = NODE_ICONS[s.node] ?? Brain;
                const isLast = i === turn.steps.length - 1;
                const active = isLast && turn.streaming;
                return (
                  <li
                    key={`${s.node}-${i}`}
                    className="flex items-center gap-2 text-xs"
                  >
                    <span className="font-mono text-fg-muted text-[10px] w-3 text-right">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <Icon
                      className={
                        'w-3.5 h-3.5 ' + (active ? 'text-accent animate-pulse' : 'text-knowledge')
                      }
                    />
                    <span className="text-fg flex-1">{NODE_LABELS[s.node] ?? s.node}</span>
                    {!active && i < turn.steps.length - 1 && (
                      <Check className="w-3 h-3 text-knowledge" />
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Section>

        {/* Data sources */}
        {(turn.sql || turn.dataResult) && (
          <Section icon={Database} label="Data">
            {turn.sql && (
              <div className="text-xs text-fg-secondary mb-2">
                <div className="font-mono text-[11px] text-fg-muted truncate" title={turn.sql.sql}>
                  {extractTables(turn.sql.sql).join(' · ') || 'SQL query'}
                </div>
                <div className="mt-1 text-[11px]">
                  Query time:{' '}
                  <span className="font-mono text-knowledge">{turn.sql.timeMs}ms</span>
                </div>
              </div>
            )}
            {turn.dataResult && (
              <div className="text-xs text-fg-secondary">
                Rows returned:{' '}
                <span className="font-mono text-fg">{turn.dataResult.row_count}</span>
              </div>
            )}
          </Section>
        )}

        {/* Sources from answer text */}
        {turn.answer && sourceCount > 0 && (
          <Section icon={FileText} label={`Citations · ${sourceCount}`}>
            <ul className="space-y-1">
              {extractSources(turn.answer).map((s, i) => (
                <li
                  key={i}
                  className="text-xs text-fg-secondary truncate"
                  title={s}
                >
                  <span className="font-mono text-[10px] text-fg-muted mr-1.5">
                    [{i + 1}]
                  </span>
                  {s}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Context applied */}
        {turn.contextLayers && (
          <Section icon={BookOpen} label="Context applied">
            <pre className="text-[11px] leading-relaxed text-fg-secondary whitespace-pre-wrap font-mono max-h-40 overflow-auto">
              {turn.contextLayers}
            </pre>
          </Section>
        )}

        {/* Tool results */}
        {turn.toolResults.length > 0 && (
          <Section icon={Wrench} label={`Tools · ${turn.toolResults.length}`}>
            <ul className="space-y-2">
              {turn.toolResults.map((tr, i) => (
                <li key={i} className="text-xs">
                  <div className="font-medium text-fg mb-0.5">{tr.tool}</div>
                  <div className="text-[11px] text-fg-secondary line-clamp-3">{tr.content}</div>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Evaluator */}
        {turn.evalScore !== null && turn.evalScore > 0 && (
          <Section icon={CheckCircle2} label="Evaluation">
            <div className="text-xs">
              <div className="text-fg">
                Score:{' '}
                <span
                  className={
                    'font-mono ' +
                    (turn.evalScore >= 4
                      ? 'text-knowledge'
                      : turn.evalScore >= 3
                        ? 'text-governance'
                        : 'text-destructive')
                  }
                >
                  {turn.evalScore.toFixed(1)} / 5
                </span>
              </div>
              {turn.evalReason && (
                <p className="text-fg-secondary mt-1.5 leading-relaxed">{turn.evalReason}</p>
              )}
            </div>
          </Section>
        )}

        {/* Errors */}
        {(turn.error || turn.dataError) && (
          <Section icon={AlertCircle} label="Errors" tone="destructive">
            <div className="text-xs text-destructive">{turn.error || turn.dataError}</div>
          </Section>
        )}
      </div>
    </aside>
  );
}

function Section({
  icon: Icon,
  label,
  tone,
  children,
}: {
  icon: LucideIcon;
  label: string;
  tone?: 'destructive';
  children: React.ReactNode;
}) {
  return (
    <section>
      <div
        className={
          'flex items-center gap-1.5 mb-2.5 text-xs uppercase tracking-wider font-medium ' +
          (tone === 'destructive' ? 'text-destructive' : 'text-fg-muted')
        }
      >
        <Icon className="w-3 h-3" />
        {label}
      </div>
      {children}
    </section>
  );
}

function countSources(turn: AskTurn): number {
  if (!turn.answer) return 0;
  return extractSources(turn.answer).length;
}

function extractSources(content: string): string[] {
  return Array.from(content.matchAll(/\[Source:\s*([^\]]+)\]/g)).map((m) => m[1].trim());
}

function extractTables(sql: string): string[] {
  const matches = Array.from(sql.matchAll(/\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)/gi));
  return Array.from(new Set(matches.map((m) => m[1])));
}

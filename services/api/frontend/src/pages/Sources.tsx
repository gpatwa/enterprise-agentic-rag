import { useState } from 'react';
import {
  Database,
  FileSearch,
  GitBranch,
  Plus,
  RefreshCw,
  Slack,
  Github,
  HardDrive,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useSourcesHealth } from '@/lib/queries';
import { useToast } from '@/components/ui/use-toast';
import { useQueryClient } from '@tanstack/react-query';
import { formatCount, formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { SourceHealth, SourceType } from '@/types';

const SOURCE_ICONS: Record<SourceType, LucideIcon> = {
  postgres: Database,
  qdrant: FileSearch,
  neo4j: GitBranch,
  s3: HardDrive,
  slack: Slack,
  notion: HardDrive,
  github: Github,
};

const STATUS_TONE = {
  fresh: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  stale: 'text-governance bg-governance/10 border-governance/20',
  error: 'text-destructive bg-destructive/10 border-destructive/20',
  not_connected: 'text-fg-muted bg-surface-muted border-border',
} as const;

const STATUS_LABEL = {
  fresh: 'Fresh',
  stale: 'Stale',
  error: 'Error',
  not_connected: 'Not connected',
} as const;

const CONNECTABLE: { id: string; label: string; icon: LucideIcon; description: string; ship?: string }[] = [
  { id: 'snowflake', label: 'Snowflake', icon: Database, description: 'Connect a Snowflake warehouse', ship: 'W3' },
  { id: 'bigquery', label: 'BigQuery', icon: Database, description: 'Connect a BigQuery dataset', ship: 'W3' },
  { id: 'salesforce', label: 'Salesforce', icon: HardDrive, description: 'Pull objects from your Salesforce org', ship: 'W3' },
  { id: 'notion', label: 'Notion', icon: HardDrive, description: 'Index a Notion workspace', ship: 'W3' },
  { id: 'slack', label: 'Slack', icon: Slack, description: 'Index Slack channel exports', ship: 'W3' },
  { id: 'github', label: 'GitHub', icon: Github, description: 'Index repos and READMEs', ship: 'W3' },
];

export function SourcesPage() {
  const { data, isLoading, error, refetch, isFetching } = useSourcesHealth();
  const sources = data?.sources ?? [];
  const probedAt = data?.probed_at;
  const { toast } = useToast();
  const qc = useQueryClient();

  const refresh = () => {
    refetch();
    toast({ title: 'Re-probing sources…' });
    qc.invalidateQueries({ queryKey: ['home', 'landing'] });
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-8 flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">Sources</div>
            <h1 className="text-2xl font-semibold tracking-tight">Connected data &amp; documents</h1>
            <p className="text-fg-secondary mt-2 text-base max-w-2xl">
              The systems Compass reads from. Health is probed live; freshness shows when each source was last reachable.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={refresh} disabled={isFetching}>
              <RefreshCw className={cn('w-4 h-4', isFetching && 'animate-spin')} />
              {isFetching ? 'Probing…' : 'Refresh'}
            </Button>
            <ConnectSourceDialog />
          </div>
        </header>

        {/* Status footer */}
        {probedAt && (
          <div className="text-xs text-fg-muted mb-4">
            Last probed {formatRelative(probedAt)}
          </div>
        )}

        {/* List */}
        {isLoading && (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="glass rounded-lg h-20 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="glass rounded-md p-4 text-sm text-fg-secondary">
            Couldn't probe sources. Make sure the backend is reachable on{' '}
            <code className="font-mono">/api/v1/sources/health</code>.
          </div>
        )}

        {!isLoading && !error && sources.length > 0 && (
          <ul className="glass rounded-xl divide-y divide-border/40">
            {sources.map((s) => (
              <SourceRow key={`${s.type}-${s.name}`} source={s} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function SourceRow({ source }: { source: SourceHealth }) {
  const Icon = SOURCE_ICONS[source.type] ?? Database;
  const tone = STATUS_TONE[source.status];
  const label = STATUS_LABEL[source.status];

  const count =
    source.row_count != null
      ? `${formatCount(source.row_count)} rows`
      : source.chunk_count != null
        ? `${source.chunk_count.toLocaleString()} chunks`
        : source.node_count != null
          ? `${source.node_count.toLocaleString()} nodes`
          : null;

  return (
    <li className="flex items-center gap-3 px-4 py-3.5 hover:bg-white/[0.03] transition">
      <div className="w-9 h-9 rounded-md bg-surface-muted flex items-center justify-center flex-shrink-0">
        <Icon className="w-4 h-4 text-fg-secondary" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg">{source.name}</div>
        <div className="text-xs text-fg-muted mt-0.5 flex flex-wrap gap-x-2">
          <span className="font-mono uppercase">{source.type}</span>
          {count && <span>· {count}</span>}
          {source.last_synced_at && <span>· Last sync {formatRelative(source.last_synced_at)}</span>}
        </div>
      </div>
      <span className={cn('text-xs px-2 py-0.5 rounded border whitespace-nowrap', tone)}>
        {label}
      </span>
    </li>
  );
}

function ConnectSourceDialog() {
  const [open, setOpen] = useState(false);
  const { toast } = useToast();

  const onConnect = (id: string) => {
    toast({
      title: `${id} connector coming in W3`,
      description: 'Configurable connectors are part of the next milestone.',
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4" />
          Add source
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Connect a source</DialogTitle>
          <DialogDescription>
            Pick a system to index. Configurable connectors ship in W3 — this preview shows the
            catalog.
          </DialogDescription>
        </DialogHeader>

        <div className="grid sm:grid-cols-2 gap-2 max-h-[420px] overflow-auto">
          {CONNECTABLE.map((c) => (
            <button
              key={c.id}
              onClick={() => onConnect(c.label)}
              className="text-left glass rounded-lg p-4 hover:border-border-strong transition group"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-md bg-surface-muted flex items-center justify-center flex-shrink-0">
                  <c.icon className="w-4 h-4 text-fg-secondary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm flex items-center gap-2">
                    {c.label}
                    {c.ship && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-governance/15 text-governance border border-governance/25">
                        {c.ship}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-fg-muted mt-0.5">{c.description}</div>
                </div>
              </div>
            </button>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

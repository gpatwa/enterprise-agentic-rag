import { useState, type FormEvent } from 'react';
import {
  Database,
  FileSearch,
  GitBranch,
  CheckCircle2,
  LifeBuoy,
  Loader2,
  MessageCircle,
  Plus,
  RefreshCw,
  Slack,
  Github,
  HardDrive,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
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
import {
  useRemoveSupportConnection,
  useSourcesHealth,
  useSupportCatalog,
  useSupportConnections,
  useTestSupportConnection,
  useUpsertSupportConnection,
} from '@/lib/queries';
import { useToast } from '@/components/ui/use-toast';
import { useQueryClient } from '@tanstack/react-query';
import { formatCount, formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import { McpConnectorsSection } from '@/components/sources/McpConnectorsSection';
import type { SourceHealth, SourceType, SupportAuthMode, SupportCatalogEntry } from '@/types';

const SOURCE_ICONS: Record<SourceType, LucideIcon> = {
  postgres: Database,
  qdrant: FileSearch,
  neo4j: GitBranch,
  s3: HardDrive,
  slack: Slack,
  notion: HardDrive,
  github: Github,
  zendesk: LifeBuoy,
  intercom: MessageCircle,
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

        <SupportIntegrationsPanel />

        {/* MCP / SaaS connectors — hidden when the backend reports MCP off */}
        <McpConnectorsSection />
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
          : source.ticket_count != null
            ? `${source.ticket_count.toLocaleString()} tickets`
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
  const [selected, setSelected] = useState<SupportCatalogEntry | null>(null);
  const [authMode, setAuthMode] = useState<SupportAuthMode>('nango');
  const [connectionId, setConnectionId] = useState('');
  const [providerConfigKey, setProviderConfigKey] = useState('');
  const catalogQuery = useSupportCatalog();
  const upsertMut = useUpsertSupportConnection();
  const { toast } = useToast();

  const catalog = catalogQuery.data?.catalog ?? [];

  const selectConnector = (entry: SupportCatalogEntry) => {
    setSelected(entry);
    setAuthMode('nango');
    setProviderConfigKey(entry.nango_provider_config_key);
    setConnectionId('');
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    if (authMode === 'nango' && !connectionId.trim()) {
      toast({
        title: 'Nango connection ID required',
        description: 'Create the OAuth connection in Nango, then paste its connection ID here.',
        variant: 'destructive',
      });
      return;
    }

    upsertMut.mutate(
      {
        provider: selected.provider,
        auth_mode: authMode,
        nango_connection_id: authMode === 'nango' ? connectionId.trim() : null,
        provider_config_key: authMode === 'nango' ? providerConfigKey.trim() : selected.nango_provider_config_key,
      },
      {
        onSuccess: () => {
          toast({ title: `${selected.display_name} connection saved` });
          setOpen(false);
          setSelected(null);
        },
        onError: (err) => {
          toast({
            title: 'Connection failed',
            description: err instanceof Error ? err.message : 'Could not save connector.',
            variant: 'destructive',
          });
        },
      }
    );
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
          <DialogTitle>Connect support source</DialogTitle>
          <DialogDescription>
            Start with first-class ticketing systems. Nango handles customer OAuth; direct env mode
            uses server-side credentials for local or private deployments.
          </DialogDescription>
        </DialogHeader>

        {!selected ? (
          <div className="grid sm:grid-cols-2 gap-2 max-h-[420px] overflow-auto">
            {catalogQuery.isLoading && (
              <div className="glass rounded-lg p-4 text-sm text-fg-secondary">
                Loading connector catalog…
              </div>
            )}
            {catalog.map((entry) => {
              const Icon = SOURCE_ICONS[entry.provider] ?? LifeBuoy;
              return (
                <button
                  key={entry.provider}
                  onClick={() => selectConnector(entry)}
                  className="text-left glass rounded-lg p-4 hover:border-border-strong transition group"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-9 h-9 rounded-md bg-surface-muted flex items-center justify-center flex-shrink-0">
                      <Icon className="w-4 h-4 text-fg-secondary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm">{entry.display_name}</div>
                      <div className="text-xs text-fg-muted mt-0.5">{entry.description}</div>
                      <div className="text-[10px] uppercase tracking-wider text-fg-muted mt-2">
                        {entry.objects.join(' · ')}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="glass rounded-lg p-4">
              <div className="text-sm font-medium">{selected.display_name}</div>
              <div className="text-xs text-fg-muted mt-1">{selected.description}</div>
            </div>

            <div className="grid sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setAuthMode('nango')}
                className={cn(
                  'text-left rounded-lg border p-3 transition',
                  authMode === 'nango'
                    ? 'border-accent bg-accent/10'
                    : 'border-border bg-surface-muted hover:border-border-strong'
                )}
              >
                <div className="text-sm font-medium">Nango OAuth</div>
                <div className="text-xs text-fg-muted mt-1">Customer-managed OAuth connection.</div>
              </button>
              <button
                type="button"
                onClick={() => setAuthMode('direct_env')}
                className={cn(
                  'text-left rounded-lg border p-3 transition',
                  authMode === 'direct_env'
                    ? 'border-accent bg-accent/10'
                    : 'border-border bg-surface-muted hover:border-border-strong'
                )}
              >
                <div className="text-sm font-medium">Direct env</div>
                <div className="text-xs text-fg-muted mt-1">
                  Uses {selected.direct_env_vars.join(', ')} on the API server.
                </div>
              </button>
            </div>

            {authMode === 'nango' && (
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="space-y-1.5">
                  <span className="text-xs uppercase tracking-widest text-fg-muted">Connection ID</span>
                  <Input
                    value={connectionId}
                    onChange={(e) => setConnectionId(e.target.value)}
                    placeholder="tenant-zendesk-prod"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs uppercase tracking-widest text-fg-muted">Provider config</span>
                  <Input
                    value={providerConfigKey}
                    onChange={(e) => setProviderConfigKey(e.target.value)}
                    placeholder={selected.nango_provider_config_key}
                  />
                </label>
              </div>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setSelected(null)}>
                Back
              </Button>
              <Button type="submit" disabled={upsertMut.isPending}>
                {upsertMut.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                Save connection
              </Button>
            </DialogFooter>
          </form>
        )}

        {!selected && (
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

function SupportIntegrationsPanel() {
  const catalogQuery = useSupportCatalog();
  const connectionsQuery = useSupportConnections();
  const testMut = useTestSupportConnection();
  const removeMut = useRemoveSupportConnection();
  const { toast } = useToast();

  const connections = connectionsQuery.data?.connections ?? [];
  if (catalogQuery.data?.support_integrations_enabled === false) return null;

  return (
    <section className="mt-8" aria-labelledby="support-integrations-heading">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h2 id="support-integrations-heading" className="text-lg font-semibold tracking-tight">
            Support integrations
          </h2>
          <p className="text-sm text-fg-secondary mt-1">
            Ticketing systems feeding resolution intelligence and repeat-issue analysis.
          </p>
        </div>
      </div>

      {connections.length === 0 ? (
        <div className="glass rounded-lg p-4 text-sm text-fg-secondary">
          Zendesk and Intercom are ready to connect.
        </div>
      ) : (
        <ul className="glass rounded-xl divide-y divide-border/40">
          {connections.map((connection) => {
            const entry = catalogQuery.data?.catalog.find((c) => c.provider === connection.provider);
            const Icon = SOURCE_ICONS[connection.provider] ?? LifeBuoy;
            const isConnected = connection.status === 'connected';
            return (
              <li key={connection.provider} className="px-4 py-3.5 flex items-center gap-3">
                <div className="w-9 h-9 rounded-md bg-surface-muted flex items-center justify-center flex-shrink-0">
                  <Icon className="w-4 h-4 text-fg-secondary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium flex items-center gap-2">
                    {entry?.display_name ?? connection.provider}
                    {isConnected && <CheckCircle2 className="w-4 h-4 text-knowledge" />}
                  </div>
                  <div className="text-xs text-fg-muted mt-0.5">
                    {connection.auth_mode === 'nango' ? 'Nango OAuth' : 'Direct env'} · {connection.status}
                    {connection.last_health_check && ` · Last checked ${formatRelative(connection.last_health_check)}`}
                  </div>
                  {connection.error_message && (
                    <div className="text-xs text-destructive mt-1">{connection.error_message}</div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={testMut.isPending}
                    onClick={() =>
                      testMut.mutate(connection.provider, {
                        onSuccess: (res) => {
                          toast({
                            title: res.ok ? 'Connection healthy' : 'Connection needs attention',
                            description: res.error_message ?? undefined,
                            variant: res.ok ? 'default' : 'destructive',
                          });
                        },
                      })
                    }
                  >
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${entry?.display_name ?? connection.provider}`}
                    disabled={removeMut.isPending}
                    onClick={() => removeMut.mutate(connection.provider)}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

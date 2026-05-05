import { useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  ExternalLink,
  Github,
  HardDrive,
  Loader2,
  Plug,
  Slack,
  Trash2,
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
} from '@/components/ui/dialog';
import {
  useDisableMcp,
  useEnableMcp,
  useMcpCatalog,
  useMcpConnections,
  useRemoveMcp,
  useTestMcp,
} from '@/lib/queries';
import { useToast } from '@/components/ui/use-toast';
import { formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { MCPCatalogEntry, MCPConnection, MCPConnectionStatus } from '@/types';

const SERVER_ICONS: Record<string, LucideIcon> = {
  slack: Slack,
  github: Github,
  notion: HardDrive,
  gdrive: HardDrive,
};

const STATUS_TONE: Record<MCPConnectionStatus | 'not_connected', string> = {
  enabled: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  pending: 'text-governance bg-governance/10 border-governance/20',
  disabled: 'text-fg-muted bg-surface-muted border-border',
  error: 'text-destructive bg-destructive/10 border-destructive/20',
  not_connected: 'text-fg-muted bg-surface-muted border-border',
};

const STATUS_LABEL: Record<MCPConnectionStatus | 'not_connected', string> = {
  enabled: 'Connected',
  pending: 'Pending',
  disabled: 'Disabled',
  error: 'Error',
  not_connected: 'Not connected',
};

/**
 * App connectors section — drives the live MCP catalog + per-tenant
 * connection state. Renders one tile per known server and wires up
 * the enable / test / disable / remove actions.
 */
export function McpConnectorsSection() {
  const catalogQuery = useMcpCatalog();
  const connectionsQuery = useMcpConnections();

  const tiles = useMemo(() => {
    const cat = catalogQuery.data?.catalog ?? [];
    const conn = connectionsQuery.data?.connections ?? [];
    const byServer = new Map<string, MCPConnection>();
    for (const c of conn) byServer.set(c.server_name, c);
    return cat.map((entry) => ({
      entry,
      connection: byServer.get(entry.server_name) ?? null,
    }));
  }, [catalogQuery.data, connectionsQuery.data]);

  // Hide the section entirely when the backend reports MCP off — keeps
  // /sources clean for deployments that haven't wired the feature.
  const mcpDisabled =
    catalogQuery.data?.mcp_enabled === false &&
    connectionsQuery.data?.mcp_enabled === false;
  if (mcpDisabled) return null;

  const isLoading = catalogQuery.isLoading || connectionsQuery.isLoading;
  const error = catalogQuery.error || connectionsQuery.error;

  return (
    <section className="mt-12" aria-labelledby="mcp-connectors-heading">
      <header className="flex items-end justify-between mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-1.5">
            App connectors
          </div>
          <h2 id="mcp-connectors-heading" className="text-lg font-semibold tracking-tight">
            SaaS tools your agent can read
          </h2>
        </div>
      </header>

      {isLoading && (
        <div className="grid sm:grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass rounded-xl h-28 animate-pulse" />
          ))}
        </div>
      )}

      {!!error && !isLoading && (
        <div className="glass rounded-md p-4 text-sm text-fg-secondary">
          Couldn't load MCP catalog. Make sure the backend is reachable on{' '}
          <code className="font-mono">/api/v1/mcp/catalog</code>.
        </div>
      )}

      {!isLoading && !error && tiles.length > 0 && (
        <ul className="grid sm:grid-cols-2 gap-3">
          {tiles.map((t) => (
            <li key={t.entry.server_name}>
              <ConnectorTile entry={t.entry} connection={t.connection} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ConnectorTile({
  entry,
  connection,
}: {
  entry: MCPCatalogEntry;
  connection: MCPConnection | null;
}) {
  const [enableOpen, setEnableOpen] = useState(false);
  const Icon = SERVER_ICONS[entry.server_name] ?? Plug;
  const statusKey: MCPConnectionStatus | 'not_connected' =
    connection?.status ?? 'not_connected';
  const tone = STATUS_TONE[statusKey];
  const label = STATUS_LABEL[statusKey];

  return (
    <div className="glass rounded-xl p-4 flex flex-col h-full">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-md bg-surface-muted flex items-center justify-center flex-shrink-0">
          <Icon className="w-4 h-4 text-fg-secondary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="font-medium text-sm">{entry.display_name}</div>
            <span
              className={cn(
                'text-xs px-2 py-0.5 rounded border whitespace-nowrap flex-shrink-0',
                tone
              )}
            >
              {label}
            </span>
          </div>
          <p className="text-xs text-fg-muted mt-1 leading-relaxed line-clamp-2">
            {entry.description}
          </p>
        </div>
      </div>

      {connection?.error_message && statusKey === 'error' && (
        <div className="mt-3 flex items-start gap-2 text-xs text-destructive bg-destructive/5 border border-destructive/20 rounded-md px-2.5 py-1.5">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span className="leading-snug">{connection.error_message}</span>
        </div>
      )}

      {connection?.last_health_check && (
        <div className="text-xs text-fg-muted mt-2">
          Last checked {formatRelative(connection.last_health_check)}
        </div>
      )}

      <div className="flex-1" />

      <ConnectorActions
        entry={entry}
        connection={connection}
        onConnect={() => setEnableOpen(true)}
      />

      <EnableMcpDialog
        entry={entry}
        open={enableOpen}
        onOpenChange={setEnableOpen}
      />
    </div>
  );
}

function ConnectorActions({
  entry,
  connection,
  onConnect,
}: {
  entry: MCPCatalogEntry;
  connection: MCPConnection | null;
  onConnect: () => void;
}) {
  const { toast } = useToast();
  const testMut = useTestMcp();
  const disableMut = useDisableMcp();
  const removeMut = useRemoveMcp();

  if (!connection) {
    return (
      <div className="flex items-center gap-2 mt-4">
        <Button size="sm" onClick={onConnect}>
          <Plug className="w-3.5 h-3.5" />
          Connect
        </Button>
        {entry.docs_url && (
          <Button asChild size="sm" variant="ghost">
            <a href={entry.docs_url} target="_blank" rel="noreferrer">
              Docs
              <ExternalLink className="w-3 h-3" />
            </a>
          </Button>
        )}
      </div>
    );
  }

  const isBusy = testMut.isPending || disableMut.isPending || removeMut.isPending;

  const onTest = () => {
    testMut.mutate(entry.server_name, {
      onSuccess: (res) => {
        toast({
          title: res.ok ? 'Connection healthy' : 'Health check failed',
          description: res.ok ? entry.display_name : res.error_message ?? undefined,
          variant: res.ok ? 'default' : 'destructive',
        });
      },
      onError: (err) => {
        toast({
          title: 'Test failed',
          description: err.message,
          variant: 'destructive',
        });
      },
    });
  };

  const onDisable = () => {
    disableMut.mutate(entry.server_name, {
      onSuccess: () =>
        toast({ title: `${entry.display_name} paused` }),
      onError: (err) =>
        toast({
          title: 'Disable failed',
          description: err.message,
          variant: 'destructive',
        }),
    });
  };

  const onRemove = () => {
    if (!window.confirm(`Remove ${entry.display_name}? Credentials will be deleted.`)) {
      return;
    }
    removeMut.mutate(entry.server_name, {
      onSuccess: () =>
        toast({ title: `${entry.display_name} removed` }),
      onError: (err) =>
        toast({
          title: 'Remove failed',
          description: err.message,
          variant: 'destructive',
        }),
    });
  };

  return (
    <div className="flex items-center gap-1.5 mt-4 flex-wrap">
      <Button size="sm" variant="ghost" onClick={onTest} disabled={isBusy}>
        {testMut.isPending ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Check className="w-3.5 h-3.5" />
        )}
        Test
      </Button>
      {connection.status === 'enabled' && (
        <Button size="sm" variant="ghost" onClick={onDisable} disabled={isBusy}>
          Pause
        </Button>
      )}
      {connection.status === 'disabled' && (
        <Button size="sm" variant="ghost" onClick={onConnect}>
          <Plug className="w-3.5 h-3.5" />
          Re-enable
        </Button>
      )}
      {connection.status === 'error' && (
        <Button size="sm" variant="ghost" onClick={onConnect}>
          Update creds
        </Button>
      )}
      <div className="flex-1" />
      <Button
        size="sm"
        variant="ghost"
        onClick={onRemove}
        disabled={isBusy}
        className="text-fg-muted hover:text-destructive"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </Button>
    </div>
  );
}

/**
 * Modal for entering credentials. Form fields are generated from the
 * catalog entry's `required_credentials` so adding a new MCP server
 * never requires a frontend change.
 */
function EnableMcpDialog({
  entry,
  open,
  onOpenChange,
}: {
  entry: MCPCatalogEntry;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  const { toast } = useToast();
  const enableMut = useEnableMcp();
  const [values, setValues] = useState<Record<string, string>>({});

  // OAuth-flow servers (Drive) need the browser-redirect flow rather than
  // a static-token form. Phase 4 will wire that up; for now we surface a
  // clear "coming soon" so the form doesn't pretend to work.
  const isOAuthServer = entry.oauth_flow === 'oauth2';

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isOAuthServer) return;
    const missing = entry.required_credentials.filter((k) => !values[k]?.trim());
    if (missing.length > 0) {
      toast({
        title: 'Missing credentials',
        description: `Required: ${missing.join(', ')}`,
        variant: 'destructive',
      });
      return;
    }
    enableMut.mutate(
      { server_name: entry.server_name, credentials: values },
      {
        onSuccess: (res) => {
          const status = res.connection?.status ?? 'pending';
          if (status === 'enabled') {
            toast({ title: `${entry.display_name} connected` });
            onOpenChange(false);
            setValues({});
          } else {
            toast({
              title: `${entry.display_name} saved with status: ${status}`,
              description: res.connection?.error_message ?? undefined,
              variant: status === 'error' ? 'destructive' : 'default',
            });
          }
        },
        onError: (err: Error & { detail?: { message?: string } }) => {
          toast({
            title: 'Connect failed',
            description: err.detail?.message ?? err.message,
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
          <DialogTitle>Connect {entry.display_name}</DialogTitle>
          <DialogDescription>{entry.description}</DialogDescription>
        </DialogHeader>

        {isOAuthServer ? (
          <div className="text-sm text-fg-secondary glass rounded-lg p-4">
            {entry.display_name} uses OAuth2. The connect-with-Google flow
            ships in Phase 4 — for now this connector is a placeholder.
          </div>
        ) : (
          <form className="space-y-3" onSubmit={onSubmit}>
            {entry.required_credentials.map((key) => (
              <div key={key} className="space-y-1.5">
                <label
                  htmlFor={`mcp-${entry.server_name}-${key}`}
                  className="text-xs uppercase tracking-widest text-fg-muted font-medium"
                >
                  {key}
                </label>
                <input
                  id={`mcp-${entry.server_name}-${key}`}
                  type="password"
                  autoComplete="off"
                  value={values[key] ?? ''}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [key]: e.target.value }))
                  }
                  className="w-full rounded-md bg-surface-muted border border-border px-3 py-2 text-sm font-mono text-fg placeholder:text-fg-muted focus:outline-none focus:border-accent"
                  placeholder={`Paste ${key}`}
                />
              </div>
            ))}
            {entry.docs_url && (
              <div className="text-xs text-fg-muted">
                Need a token?{' '}
                <a
                  href={entry.docs_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline inline-flex items-center gap-1"
                >
                  See {entry.display_name} docs <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={enableMut.isPending}>
                {enableMut.isPending && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                )}
                Connect
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

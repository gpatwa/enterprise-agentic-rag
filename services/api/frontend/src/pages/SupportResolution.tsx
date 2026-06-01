import { useMemo, useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  ClipboardCheck,
  CheckCircle2,
  ExternalLink,
  LifeBuoy,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Ticket,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';
import {
  useIndexSupportTickets,
  useResolveSupportIssue,
  useSearchSupportIndex,
  useSupportTickets,
} from '@/lib/queries';
import { formatCount, formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { SupportResolution, SupportSearchResult, SupportTicket } from '@/types';

type ProviderFilter = 'all' | 'zendesk' | 'intercom';

const STATUS_TONE: Record<string, string> = {
  open: 'text-governance bg-governance/10 border-governance/20',
  pending: 'text-accent bg-accent/10 border-accent/20',
  solved: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  closed: 'text-fg-muted bg-surface-muted border-border',
};

const PIPELINE = [
  { label: 'Connect', body: 'Zendesk and Intercom connectors' },
  { label: 'Normalize', body: 'Canonical ticket model' },
  { label: 'Index', body: 'Tenant-scoped vector memory' },
  { label: 'Resolve', body: 'Answer from prior resolutions' },
] as const;

export function SupportResolutionPage() {
  const [provider, setProvider] = useState<ProviderFilter>('all');
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('How have we resolved export timeout issues?');
  const providerParam = provider === 'all' ? undefined : provider;
  const statusParam = status.trim() || undefined;
  const ticketsQuery = useSupportTickets({ provider: providerParam, status: statusParam, limit: 25 });
  const indexMutation = useIndexSupportTickets();
  const searchMutation = useSearchSupportIndex();
  const resolveMutation = useResolveSupportIssue();
  const { toast } = useToast();

  const tickets = ticketsQuery.data?.tickets ?? [];
  const indexSummary = indexMutation.data?.index;
  const resultCount = searchMutation.data?.results.length ?? 0;

  const runIndex = () => {
    indexMutation.mutate(
      { provider: providerParam, limit: 100 },
      {
        onSuccess: (data) =>
          toast({
            title: 'Support index updated',
            description: `${data.index.indexed} indexed, ${data.index.skipped} unchanged, ${data.index.chunks} chunks.`,
          }),
        onError: (err) =>
          toast({
            title: 'Indexing failed',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    searchMutation.mutate(
      { q, provider: providerParam, status: statusParam, limit: 8 },
      {
        onError: (err) =>
          toast({
            title: 'Search unavailable',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  const runResolve = () => {
    const q = query.trim();
    if (q.length < 2) return;
    resolveMutation.mutate(
      { question: q, provider: providerParam, status: statusParam, limit: 6 },
      {
        onError: (err) =>
          toast({
            title: 'Resolution unavailable',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-8 flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">
              Resolution Intelligence
            </div>
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">
              Deflect repeat support tickets
            </h1>
            <p className="text-fg-secondary mt-2 text-base max-w-2xl leading-relaxed">
              Turn historical support tickets into searchable resolution memory. The first wave is
              built for customer support teams that need faster answers before adding automation.
            </p>
          </div>
          <Button onClick={runIndex} disabled={indexMutation.isPending}>
            {indexMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {indexMutation.isPending ? 'Indexing…' : 'Index tickets'}
          </Button>
        </header>

        <div className="grid md:grid-cols-3 gap-3 mb-6">
          <MetricCard
            icon={Ticket}
            label="Normalized tickets"
            value={formatCount(ticketsQuery.data?.total ?? 0)}
            detail="Synced into the support data plane"
          />
          <MetricCard
            icon={Sparkles}
            label="Indexed chunks"
            value={formatCount(indexSummary?.chunks ?? 0)}
            detail={indexSummary ? `${indexSummary.indexed} tickets refreshed` : 'Run indexing after sync'}
          />
          <MetricCard
            icon={ShieldCheck}
            label="Search isolation"
            value="Tenant"
            detail="Every vector query is tenant-filtered"
          />
        </div>

        <section className="glass rounded-2xl p-4 md:p-5 mb-6">
          <div className="grid md:grid-cols-4 gap-3">
            {PIPELINE.map((step, idx) => (
              <div key={step.label} className="relative rounded-xl border border-border/60 bg-surface-muted/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-6 h-6 rounded-full bg-accent/15 text-accent text-xs font-mono flex items-center justify-center">
                    {idx + 1}
                  </span>
                  <div className="text-sm font-medium">{step.label}</div>
                </div>
                <p className="text-xs text-fg-muted leading-relaxed">{step.body}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-6 items-start">
          <section className="glass rounded-2xl p-4 md:p-5">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Ask prior resolutions</h2>
                <p className="text-sm text-fg-secondary mt-1">
                  Search the support memory before a new agent or customer opens another ticket.
                </p>
              </div>
              {searchMutation.isError && (
                <span className="text-xs px-2 py-1 rounded border text-destructive bg-destructive/10 border-destructive/20">
                  Index unavailable
                </span>
              )}
            </div>

            <FilterBar
              provider={provider}
              status={status}
              onProviderChange={setProvider}
              onStatusChange={setStatus}
            />

            <form onSubmit={submitSearch} className="mt-4 flex flex-col sm:flex-row gap-2">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask about a recurring issue…"
                className="glass border"
              />
              <div className="flex gap-2">
                <Button type="button" onClick={runResolve} disabled={resolveMutation.isPending || query.trim().length < 2}>
                  {resolveMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <ClipboardCheck className="w-4 h-4" />
                  )}
                  Resolve
                </Button>
                <Button type="submit" variant="outline" disabled={searchMutation.isPending || query.trim().length < 2}>
                  {searchMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Search className="w-4 h-4" />
                  )}
                  Search
                </Button>
              </div>
            </form>

            <div className="mt-5">
              {resolveMutation.isSuccess && <ResolutionCard resolution={resolveMutation.data.resolution} />}
              {resolveMutation.isPending && <LoadingRows />}
              {resolveMutation.isError && <ResolveError />}
              {searchMutation.isIdle && !resolveMutation.isSuccess && !resolveMutation.isPending && <SearchEmptyState />}
              {searchMutation.isPending && <LoadingRows />}
              {searchMutation.isError && <SearchError />}
              {searchMutation.isSuccess && (
                <SearchResults results={searchMutation.data.results} resultCount={resultCount} />
              )}
            </div>
          </section>

          <section className="glass rounded-2xl p-4 md:p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Recent normalized tickets</h2>
                <p className="text-sm text-fg-secondary mt-1">
                  These are the records that feed the resolution index.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => ticketsQuery.refetch()} disabled={ticketsQuery.isFetching}>
                <RefreshCw className={cn('w-3.5 h-3.5', ticketsQuery.isFetching && 'animate-spin')} />
                Refresh
              </Button>
            </div>

            {ticketsQuery.isLoading && <LoadingRows />}
            {ticketsQuery.error && (
              <div className="rounded-lg border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
                Could not load support tickets.
              </div>
            )}
            {!ticketsQuery.isLoading && !ticketsQuery.error && tickets.length === 0 && <TicketsEmptyState />}
            {tickets.length > 0 && <TicketList tickets={tickets} />}
          </section>
        </div>
      </div>
    </div>
  );
}

function ResolutionCard({ resolution }: { resolution: SupportResolution }) {
  const confidenceTone =
    resolution.confidence === 'high'
      ? 'text-knowledge bg-knowledge/10 border-knowledge/20'
      : resolution.confidence === 'medium'
        ? 'text-accent bg-accent/10 border-accent/20'
        : 'text-governance bg-governance/10 border-governance/20';
  return (
    <article className="rounded-2xl border border-accent/25 bg-accent/5 p-4 mb-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-fg-muted">Suggested resolution</div>
          <h3 className="text-base font-semibold mt-1">Agent-ready answer</h3>
        </div>
        <span className={cn('text-xs px-2 py-1 rounded border capitalize', confidenceTone)}>
          {resolution.confidence} confidence
        </span>
      </div>
      <div className="whitespace-pre-wrap text-sm text-fg-secondary leading-relaxed">{resolution.answer}</div>
      <div className="mt-4 flex flex-wrap gap-2">
        <span className="text-[11px] px-2 py-1 rounded border border-border bg-surface-muted text-fg-muted">
          Next: {resolution.next_action.replace(/_/g, ' ')}
        </span>
        {resolution.citations.map((citation) => (
          <a
            key={`${citation.label}-${citation.source_id}`}
            href={citation.source_url || undefined}
            target="_blank"
            rel="noreferrer"
            className={cn(
              'text-[11px] px-2 py-1 rounded border border-border bg-surface-muted text-fg-muted',
              citation.source_url && 'hover:text-fg hover:border-border-strong'
            )}
          >
            {citation.label} {citation.title || citation.source_id || citation.source_type}
          </a>
        ))}
      </div>
    </article>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Ticket;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="glass rounded-xl p-4">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-surface-muted flex items-center justify-center">
          <Icon className="w-4 h-4 text-accent" />
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-fg-muted">{label}</div>
          <div className="text-xl font-semibold mt-0.5">{value}</div>
        </div>
      </div>
      <p className="text-xs text-fg-secondary mt-3">{detail}</p>
    </article>
  );
}

function FilterBar({
  provider,
  status,
  onProviderChange,
  onStatusChange,
}: {
  provider: ProviderFilter;
  status: string;
  onProviderChange: (value: ProviderFilter) => void;
  onStatusChange: (value: string) => void;
}) {
  return (
    <div className="grid sm:grid-cols-2 gap-2">
      <label className="text-xs text-fg-muted">
        Provider
        <select
          value={provider}
          onChange={(e) => onProviderChange(e.target.value as ProviderFilter)}
          className="mt-1 glass border w-full rounded-md px-3 py-2 text-sm text-fg bg-bg"
        >
          <option value="all">All providers</option>
          <option value="zendesk">Zendesk</option>
          <option value="intercom">Intercom</option>
        </select>
      </label>
      <label className="text-xs text-fg-muted">
        Status
        <Input
          value={status}
          onChange={(e) => onStatusChange(e.target.value)}
          placeholder="open, solved, pending…"
          className="mt-1 glass border"
        />
      </label>
    </div>
  );
}

function SearchResults({ results, resultCount }: { results: SupportSearchResult[]; resultCount: number }) {
  if (results.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface-muted/40 p-6 text-center">
        <Search className="w-6 h-6 text-fg-muted mx-auto mb-3" />
        <div className="font-medium">No matching resolutions yet</div>
        <p className="text-sm text-fg-secondary mt-1">
          Sync support tickets, run indexing, then try the search again.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-fg-muted">
        {resultCount} resolution {resultCount === 1 ? 'match' : 'matches'}
      </div>
      {results.map((result) => (
        <article key={result.id} className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-sm truncate">{result.title || result.source_id || 'Support ticket'}</div>
              <div className="flex flex-wrap items-center gap-2 mt-1 text-[11px] text-fg-muted">
                {result.provider && <span className="font-mono uppercase">{result.provider}</span>}
                {result.status && <StatusPill status={result.status} />}
                {typeof result.score === 'number' && <span>Score {result.score.toFixed(2)}</span>}
              </div>
            </div>
            {result.source_url && (
              <a
                href={result.source_url}
                target="_blank"
                rel="noreferrer"
                className="text-fg-muted hover:text-fg transition"
                aria-label="Open source ticket"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
          </div>
          <p className="text-sm text-fg-secondary leading-relaxed mt-3 line-clamp-4">{result.text}</p>
          {result.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {result.tags.slice(0, 5).map((tag) => (
                <span key={tag} className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-fg-muted border border-border/50">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function TicketList({ tickets }: { tickets: SupportTicket[] }) {
  const grouped = useMemo(() => tickets.slice(0, 25), [tickets]);
  return (
    <ul className="space-y-2">
      {grouped.map((ticket) => (
        <li key={`${ticket.provider}-${ticket.external_id}`} className="rounded-xl border border-border/70 bg-surface-muted/30 p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{ticket.subject}</div>
              <div className="flex flex-wrap items-center gap-2 mt-1 text-[11px] text-fg-muted">
                <span className="font-mono uppercase">{ticket.provider}</span>
                {ticket.status && <StatusPill status={ticket.status} />}
                {ticket.priority && <span>{ticket.priority} priority</span>}
                {ticket.last_synced_at && <span>Synced {formatRelative(ticket.last_synced_at)}</span>}
              </div>
            </div>
            {ticket.source_url && (
              <a href={ticket.source_url} target="_blank" rel="noreferrer" className="text-fg-muted hover:text-fg transition">
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
          </div>
          {ticket.description && (
            <p className="text-xs text-fg-secondary leading-relaxed mt-2 line-clamp-2">{ticket.description}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={cn('px-1.5 py-0.5 rounded border text-[11px]', STATUS_TONE[status] ?? 'text-fg-muted bg-surface-muted border-border')}>
      {status}
    </span>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-20 rounded-xl bg-surface-muted animate-pulse" />
      ))}
    </div>
  );
}

function SearchEmptyState() {
  return (
    <div className="rounded-xl border border-border bg-surface-muted/40 p-6 text-center">
      <LifeBuoy className="w-7 h-7 text-accent mx-auto mb-3" />
      <div className="font-medium">Search the support memory</div>
      <p className="text-sm text-fg-secondary mt-1">
        Start with a recurring issue. The engine searches historical ticket context, scoped to this tenant.
      </p>
    </div>
  );
}

function SearchError() {
  return (
    <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 flex items-start gap-3">
      <AlertTriangle className="w-4 h-4 text-destructive mt-0.5" />
      <div>
        <div className="text-sm font-medium text-destructive">Support index is not ready</div>
        <p className="text-xs text-fg-secondary mt-1">
          Sync tickets and run indexing first. In dev, also make sure the embedding and vector services are running.
        </p>
      </div>
    </div>
  );
}

function ResolveError() {
  return (
    <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 flex items-start gap-3 mb-4">
      <AlertTriangle className="w-4 h-4 text-destructive mt-0.5" />
      <div>
        <div className="text-sm font-medium text-destructive">Could not generate a resolution</div>
        <p className="text-xs text-fg-secondary mt-1">
          The support index is probably empty or unavailable. Sync tickets, index them, then retry.
        </p>
      </div>
    </div>
  );
}

function TicketsEmptyState() {
  return (
    <div className="rounded-xl border border-border bg-surface-muted/40 p-6 text-center">
      <CheckCircle2 className="w-7 h-7 text-fg-muted mx-auto mb-3" />
      <div className="font-medium">No support tickets synced yet</div>
      <p className="text-sm text-fg-secondary mt-1">
        Connect Zendesk or Intercom from Sources, sync tickets, then return here to index and search resolutions.
      </p>
    </div>
  );
}

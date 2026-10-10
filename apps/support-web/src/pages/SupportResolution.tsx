import { useMemo, useState, type FormEvent } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Bot,
  ClipboardCheck,
  CheckCircle2,
  Clock,
  Copy,
  Database,
  ExternalLink,
  FileText,
  LifeBuoy,
  Loader2,
  PackageCheck,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Ticket,
  TrendingDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { useToast } from '@/components/ui/use-toast';
import {
  useIndexSupportTickets,
  useBuildSupportResolutionWorkflow,
  useCreateSupportAction,
  useExecuteSupportAction,
  useResetSupportActions,
  useResolveSupportIssue,
  useSearchSupportIndex,
  useSeedSupportDemo,
  useSupportActions,
  useStartSupportSyncIndexJob,
  useSupportRepeatInsights,
  useSupportJobs,
  useSupportTickets,
  useUpdateSupportActionStatus,
} from '@/lib/queries';
import { formatCount, formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';
import type {
  SupportAction,
  SupportActionStatus,
  SupportJob,
  SupportRepeatTicketInsight,
  SupportResolution,
  SupportResolutionWorkflow,
  SupportSearchResult,
  SupportTicket,
} from '@/types';

type ProviderFilter = 'all' | 'zendesk' | 'intercom';

const STATUS_TONE: Record<string, string> = {
  open: 'text-governance bg-governance/10 border-governance/20',
  pending: 'text-accent bg-accent/10 border-accent/20',
  solved: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  closed: 'text-fg-muted bg-surface-muted border-border',
};

const JOB_STATUS_TONE: Record<string, string> = {
  queued: 'text-fg-muted bg-surface-muted border-border',
  running: 'text-accent bg-accent/10 border-accent/20',
  succeeded: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  failed: 'text-destructive bg-destructive/10 border-destructive/20',
  canceled: 'text-fg-muted bg-surface-muted border-border',
};

const ACTION_STATUS_TONE: Record<string, string> = {
  generated: 'text-fg-muted bg-surface-muted border-border',
  needs_review: 'text-accent bg-accent/10 border-accent/20',
  approved: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  ready_to_execute: 'text-governance bg-governance/10 border-governance/20',
  executed: 'text-knowledge bg-knowledge/10 border-knowledge/20',
  rejected: 'text-destructive bg-destructive/10 border-destructive/20',
};

const PIPELINE = [
  { label: 'Ask', body: 'Describe the recurring support issue' },
  { label: 'Match', body: 'Find repeat clusters and solved cases' },
  { label: 'Build', body: 'Generate a cited resolution workflow' },
  { label: 'Command', body: 'Create an agent-ready execution prompt' },
] as const;

const ASK_SUGGESTIONS = [
  'Why do export timeout tickets keep happening?',
  'How have we resolved Slack integration failures?',
  'Which billing preview issues could be deflected?',
] as const;

const EMPTY_SUPPORT_ACTIONS: SupportAction[] = [];
const EMPTY_REPEAT_INSIGHTS: SupportRepeatTicketInsight[] = [];
const DEMO_QUESTION = 'How have we resolved export timeout issues?';
const DEMO_STEPS = [
  { id: 'reset', label: 'Reset' },
  { id: 'seed', label: 'Seed' },
  { id: 'ask', label: 'Ask' },
  { id: 'build', label: 'Build' },
  { id: 'queue', label: 'Queue' },
  { id: 'review', label: 'Review' },
  { id: 'approve', label: 'Approve' },
  { id: 'ready', label: 'Ready' },
  { id: 'execute', label: 'Execute' },
] as const;

type DemoStepId = (typeof DEMO_STEPS)[number]['id'];
type DemoRunState = {
  active: boolean;
  step: DemoStepId | 'idle' | 'complete' | 'error';
  error?: string;
};
type BuyerOutcome = {
  headline: string;
  summary: string;
  deflectableTickets: number;
  artifactCount: number;
  macroDrafted: boolean;
  kbDrafted: boolean;
  followUpPrepared: boolean;
};
type RepeatSummary = {
  tickets_analyzed: number;
  total_tickets: number;
  repeat_clusters: number;
  repeat_ticket_count: number;
  potential_deflection_count: number;
};

export function SupportResolutionPage() {
  const [provider, setProvider] = useState<ProviderFilter>('all');
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState(DEMO_QUESTION);
  const [demoRun, setDemoRun] = useState<DemoRunState>({ active: false, step: 'idle' });
  const [caseStudyOpen, setCaseStudyOpen] = useState(false);
  const providerParam = provider === 'all' ? undefined : provider;
  const statusParam = status.trim() || undefined;
  const ticketsQuery = useSupportTickets({ provider: providerParam, status: statusParam, limit: 25 });
  const repeatInsightsQuery = useSupportRepeatInsights({
    provider: providerParam,
    status: statusParam,
    limit: 200,
    min_count: 2,
  });
  const jobsQuery = useSupportJobs();
  const actionsQuery = useSupportActions();
  const indexMutation = useIndexSupportTickets();
  const searchMutation = useSearchSupportIndex();
  const resolveMutation = useResolveSupportIssue();
  const workflowMutation = useBuildSupportResolutionWorkflow();
  const createActionMutation = useCreateSupportAction();
  const resetActionsMutation = useResetSupportActions();
  const updateActionStatusMutation = useUpdateSupportActionStatus();
  const executeActionMutation = useExecuteSupportAction();
  const seedMutation = useSeedSupportDemo();
  const startJobMutation = useStartSupportSyncIndexJob();
  const { toast } = useToast();

  const tickets = ticketsQuery.data?.tickets ?? [];
  const jobs = jobsQuery.data?.jobs ?? [];
  const actions = actionsQuery.data?.actions ?? EMPTY_SUPPORT_ACTIONS;
  const repeatInsights = repeatInsightsQuery.data?.insights ?? EMPTY_REPEAT_INSIGHTS;
  const repeatSummary = repeatInsightsQuery.data?.summary;
  const activeJob = jobs.find((job) => job.status === 'queued' || job.status === 'running');
  const indexSummary = indexMutation.data?.index ?? seedMutation.data?.index ?? undefined;
  const resultCount = searchMutation.data?.results.length ?? 0;
  const syncProviders: Array<'zendesk' | 'intercom'> = providerParam ? [providerParam] : ['zendesk', 'intercom'];
  const matchedInsight = useMemo(
    () => findBestRepeatInsight(query, repeatInsights),
    [query, repeatInsights]
  );
  const latestExecutedAction = useMemo(
    () => actions.find((action) => action.status === 'executed') ?? actions[0],
    [actions]
  );
  const buyerOutcome = useMemo(
    () => buildBuyerOutcome(latestExecutedAction, repeatSummary),
    [latestExecutedAction, repeatSummary]
  );

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

  const loadDemoData = () => {
    seedMutation.mutate(undefined, {
      onSuccess: (data) => {
        void ticketsQuery.refetch();
        void jobsQuery.refetch();
        toast({
          title: data.index_status === 'succeeded' ? 'Demo data loaded and indexed' : 'Demo data loaded',
          description:
            data.index_status === 'succeeded'
              ? `${data.seed.tickets_seen} tickets, ${data.seed.comments_seen} comments, and ${data.seed.articles_seen} articles are ready.`
              : `${data.seed.tickets_seen} tickets loaded. Indexing still needs vector/embedding services.`,
        });
      },
      onError: (err) =>
        toast({
          title: 'Demo load failed',
          description: err.message,
          variant: 'destructive',
        }),
    });
  };

  const startSyncIndex = () => {
    startJobMutation.mutate(
      { providers: syncProviders, limit: 100 },
      {
        onSuccess: (data) => {
          void jobsQuery.refetch();
          toast({
            title: 'Sync + index job started',
            description: `${data.job.providers.join(', ')} pipeline is running in the background.`,
          });
        },
        onError: (err) =>
          toast({
            title: 'Could not start pipeline',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  const searchResolutionMemory = (q: string) => {
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

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    searchResolutionMemory(query.trim());
  };

  const searchRepeatInsight = (q: string) => {
    setQuery(q);
    searchResolutionMemory(q);
  };

  const buildWorkflow = (insight: SupportRepeatTicketInsight) => {
    setQuery(insight.related_query);
    workflowMutation.mutate(
      {
        cluster_id: insight.id,
        provider: providerParam,
        status: statusParam,
        limit: 200,
        min_count: 2,
      },
      {
        onSuccess: (data) =>
          toast({
            title: 'Resolution workflow built',
            description: `${data.workflow.cluster.title}: ${data.workflow.deflection_estimate.potential_ticket_count} potential repeat tickets.`,
          }),
        onError: (err) =>
          toast({
            title: 'Could not build workflow',
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

  const runGuidedAsk = () => {
    const q = query.trim();
    if (q.length < 2) return;
    searchResolutionMemory(q);
    runResolve();
    if (matchedInsight) {
      buildWorkflow(matchedInsight);
    } else {
      toast({
        title: 'No repeat cluster matched yet',
        description: 'Load demo data or refresh repeat insights, then build the workflow from a cluster.',
      });
    }
  };

  const resetActionQueue = () => {
    resetActionsMutation.mutate(undefined, {
      onSuccess: (data) => {
        setDemoRun({ active: false, step: 'idle' });
        void actionsQuery.refetch();
        toast({
          title: 'Demo actions reset',
          description: `${data.deleted_count} queued action${data.deleted_count === 1 ? '' : 's'} cleared. Ticket memory is unchanged.`,
        });
      },
      onError: (err) =>
        toast({
          title: 'Could not reset demo actions',
          description: err.message,
          variant: 'destructive',
        }),
    });
  };

  const startGuidedDemo = async () => {
    if (demoRun.active) return;

    const setStep = (step: DemoStepId) => setDemoRun({ active: true, step });
    setProvider('all');
    setStatus('');
    setQuery(DEMO_QUESTION);

    try {
      setStep('reset');
      await resetActionsMutation.mutateAsync();

      setStep('seed');
      await seedMutation.mutateAsync();
      await Promise.all([ticketsQuery.refetch(), jobsQuery.refetch()]);
      const refreshedInsights = await repeatInsightsQuery.refetch();
      const insights = refreshedInsights.data?.insights ?? repeatInsights;
      const insight = findBestRepeatInsight(DEMO_QUESTION, insights);
      if (!insight) {
        throw new Error('Export timeout repeat cluster was not available after loading demo data.');
      }

      setStep('ask');
      await Promise.all([
        searchMutation.mutateAsync({ q: DEMO_QUESTION, limit: 8 }),
        resolveMutation.mutateAsync({ question: DEMO_QUESTION, limit: 6 }),
      ]);

      setStep('build');
      const workflowResponse = await workflowMutation.mutateAsync({
        cluster_id: insight.id,
        limit: 200,
        min_count: 2,
      });
      const commandText = buildAgentCommand(workflowResponse.workflow);

      setStep('queue');
      const created = await createActionMutation.mutateAsync({
        cluster_id: workflowResponse.workflow.cluster.id,
        cluster_title: workflowResponse.workflow.cluster.title,
        command_text: commandText,
        workflow: JSON.parse(JSON.stringify(workflowResponse.workflow)) as Record<string, unknown>,
      });
      const actionId = created.action.id;

      setStep('review');
      await updateActionStatusMutation.mutateAsync({
        actionId,
        status: 'needs_review',
        review_notes: 'Guided demo review: evidence and guardrails checked.',
      });

      setStep('approve');
      await updateActionStatusMutation.mutateAsync({ actionId, status: 'approved' });

      setStep('ready');
      await updateActionStatusMutation.mutateAsync({ actionId, status: 'ready_to_execute' });

      setStep('execute');
      await executeActionMutation.mutateAsync({
        actionId,
        execution_notes: 'Guided local demo execution. No external system was changed.',
      });
      await actionsQuery.refetch();

      setDemoRun({ active: false, step: 'complete' });
      toast({
        title: 'Guided demo complete',
        description: 'The support action moved from historical memory to reviewed local execution.',
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Guided demo failed.';
      setDemoRun({ active: false, step: 'error', error: message });
      toast({
        title: 'Guided demo stopped',
        description: message,
        variant: 'destructive',
      });
    }
  };

  const saveWorkflowAction = (workflow: SupportResolutionWorkflow, commandText: string) => {
    createActionMutation.mutate(
      {
        cluster_id: workflow.cluster.id,
        cluster_title: workflow.cluster.title,
        command_text: commandText,
        workflow: JSON.parse(JSON.stringify(workflow)) as Record<string, unknown>,
      },
      {
        onSuccess: (data) =>
          toast({
            title: 'Action added to approval queue',
            description: `${data.action.cluster_title} is ready for support ops review.`,
          }),
        onError: (err) =>
          toast({
            title: 'Could not save action',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  const updateActionStatus = (actionId: string, status: SupportActionStatus) => {
    updateActionStatusMutation.mutate(
      { actionId, status },
      {
        onSuccess: (data) =>
          toast({
            title: 'Action status updated',
            description: `${data.action.cluster_title} is now ${formatLabel(data.action.status)}.`,
          }),
        onError: (err) =>
          toast({
            title: 'Could not update action',
            description: err.message,
            variant: 'destructive',
          }),
      }
    );
  };

  const executeAction = (actionId: string) => {
    executeActionMutation.mutate(
      {
        actionId,
        execution_notes: 'Local demo execution. No external system was changed.',
      },
      {
        onSuccess: (data) =>
          toast({
            title: 'Local action executed',
            description: `${data.action.cluster_title} produced reviewable local artifacts.`,
          }),
        onError: (err) =>
          toast({
            title: 'Could not execute action',
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
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={loadDemoData} disabled={seedMutation.isPending}>
              {seedMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Database className="w-4 h-4" />
              )}
              {seedMutation.isPending ? 'Loading…' : 'Load demo data'}
            </Button>
            <Button onClick={startSyncIndex} disabled={startJobMutation.isPending || Boolean(activeJob)}>
              {startJobMutation.isPending || activeJob ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <PlayCircle className="w-4 h-4" />
              )}
              {activeJob ? 'Pipeline running…' : 'Sync + index'}
            </Button>
            <Button variant="ghost" onClick={runIndex} disabled={indexMutation.isPending}>
              {indexMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              {indexMutation.isPending ? 'Indexing…' : 'Index only'}
            </Button>
          </div>
        </header>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
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
            detail={indexSummary ? `${indexSummary.indexed} records refreshed` : 'Run indexing after sync'}
          />
          <MetricCard
            icon={TrendingDown}
            label="Repeat clusters"
            value={formatCount(repeatSummary?.repeat_clusters ?? 0)}
            detail={`${formatCount(repeatSummary?.potential_deflection_count ?? 0)} tickets could be deflected`}
          />
          <MetricCard
            icon={ShieldCheck}
            label="Search isolation"
            value="Tenant"
            detail="Every vector query is tenant-filtered"
          />
        </div>

        <DemoRunbookPanel
          actionsCount={actions.length}
          state={demoRun}
          isStarting={demoRun.active}
          isResetting={resetActionsMutation.isPending}
          onStart={() => void startGuidedDemo()}
          onReset={resetActionQueue}
        />

        <BuyerOutcomePanel
          outcome={buyerOutcome}
          hasExecutedAction={latestExecutedAction?.status === 'executed'}
          onOpenCaseStudy={() => setCaseStudyOpen(true)}
        />

        <AskToResolutionPanel
          query={query}
          suggestions={ASK_SUGGESTIONS}
          matchedInsight={matchedInsight}
          isResolving={resolveMutation.isPending}
          isSearching={searchMutation.isPending}
          isBuildingWorkflow={workflowMutation.isPending}
          onQueryChange={setQuery}
          onSubmitSearch={submitSearch}
          onGuidedAsk={runGuidedAsk}
          onResolve={runResolve}
          onSuggestion={(suggestion) => {
            setQuery(suggestion);
            searchResolutionMemory(suggestion);
          }}
        />

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

        <JobStatusPanel
          jobs={jobs}
          isLoading={jobsQuery.isLoading}
          isRefreshing={jobsQuery.isFetching}
          onRefresh={() => void jobsQuery.refetch()}
        />

        <RepeatInsightsPanel
          insights={repeatInsights}
          summary={repeatSummary}
          isLoading={repeatInsightsQuery.isLoading}
          isError={repeatInsightsQuery.isError}
          isRefreshing={repeatInsightsQuery.isFetching}
          onRefresh={() => void repeatInsightsQuery.refetch()}
          onSearchQuery={searchRepeatInsight}
          onBuildWorkflow={buildWorkflow}
        />

        <WorkflowPanel
          workflow={workflowMutation.data?.workflow}
          isLoading={workflowMutation.isPending}
          isError={workflowMutation.isError}
          errorMessage={workflowMutation.error?.message}
          isSavingAction={createActionMutation.isPending}
          onSaveAction={saveWorkflowAction}
        />

        <GroundedResolutionState
          resolution={resolveMutation.data?.resolution}
          workflow={workflowMutation.data?.workflow}
          action={latestExecutedAction}
        />

        <ActionQueuePanel
          actions={actions}
          isLoading={actionsQuery.isLoading}
          isRefreshing={actionsQuery.isFetching}
          updatingActionId={
            updateActionStatusMutation.isPending
              ? updateActionStatusMutation.variables?.actionId
              : undefined
          }
          executingActionId={
            executeActionMutation.isPending
              ? executeActionMutation.variables?.actionId
              : undefined
          }
          onRefresh={() => void actionsQuery.refetch()}
          onUpdateStatus={updateActionStatus}
          onExecute={executeAction}
        />

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
      <CaseStudySheet
        open={caseStudyOpen}
        onOpenChange={setCaseStudyOpen}
        outcome={buyerOutcome}
      />
    </div>
  );
}

function DemoRunbookPanel({
  actionsCount,
  state,
  isStarting,
  isResetting,
  onStart,
  onReset,
}: {
  actionsCount: number;
  state: DemoRunState;
  isStarting: boolean;
  isResetting: boolean;
  onStart: () => void;
  onReset: () => void;
}) {
  const currentIndex = DEMO_STEPS.findIndex((step) => step.id === state.step);
  const complete = state.step === 'complete';
  const hasError = state.step === 'error';

  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <PlayCircle className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Demo runbook</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            Historical tickets to reviewed local execution for the export-timeout scenario.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onStart} disabled={isStarting || isResetting}>
            {isStarting ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
            {isStarting ? 'Running…' : 'Start demo'}
          </Button>
          <Button variant="outline" onClick={onReset} disabled={isStarting || isResetting || actionsCount === 0}>
            {isResetting ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Reset actions
          </Button>
        </div>
      </div>

      <div className="mt-4 grid sm:grid-cols-3 lg:grid-cols-9 gap-2">
        {DEMO_STEPS.map((step, idx) => {
          const active = state.step === step.id;
          const done = complete || currentIndex > idx;
          return (
            <div
              key={step.id}
              className={cn(
                'rounded-lg border px-3 py-2 min-w-0',
                active && 'border-accent/40 bg-accent/10',
                done && 'border-knowledge/30 bg-knowledge/10',
                !active && !done && 'border-border bg-surface-muted/30'
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    'w-2 h-2 rounded-full shrink-0',
                    active && 'bg-accent',
                    done && 'bg-knowledge',
                    !active && !done && 'bg-border-strong'
                  )}
                />
                <span className="text-xs font-medium truncate">{step.label}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div
        className={cn(
          'mt-3 rounded-lg border px-3 py-2 text-xs',
          hasError
            ? 'border-destructive/25 bg-destructive/10 text-destructive'
            : complete
              ? 'border-knowledge/20 bg-knowledge/10 text-fg-secondary'
              : 'border-border bg-surface-muted/30 text-fg-secondary'
        )}
      >
        {hasError
          ? state.error
          : complete
            ? 'Ready for replay. The latest action is executed locally with audit evidence.'
            : isStarting
              ? `${formatLabel(String(state.step))} in progress.`
              : `${formatCount(actionsCount)} queued action${actionsCount === 1 ? '' : 's'} in the local demo queue.`}
      </div>
    </section>
  );
}

function BuyerOutcomePanel({
  outcome,
  hasExecutedAction,
  onOpenCaseStudy,
}: {
  outcome: BuyerOutcome;
  hasExecutedAction: boolean;
  onOpenCaseStudy: () => void;
}) {
  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Buyer outcome</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            The demo result translated into support-ops value and trust signals.
          </p>
        </div>
        <Button variant="outline" onClick={onOpenCaseStudy}>
          <FileText className="w-4 h-4" />
          Case study
        </Button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <OutcomeTile
          icon={TrendingDown}
          label="Deflection opportunity"
          value={formatCount(outcome.deflectableTickets)}
          detail="repeat tickets in this local sample"
        />
        <OutcomeTile
          icon={PackageCheck}
          label="Macro draft"
          value={outcome.macroDrafted ? 'Ready' : 'Pending'}
          detail="agent response prepared for review"
        />
        <OutcomeTile
          icon={FileText}
          label="KB update"
          value={outcome.kbDrafted ? 'Ready' : 'Pending'}
          detail="article gap packaged from evidence"
        />
        <OutcomeTile
          icon={Bot}
          label="Product follow-up"
          value={outcome.followUpPrepared ? 'Ready' : 'Pending'}
          detail="repeat evidence prepared for triage"
        />
        <OutcomeTile
          icon={ShieldCheck}
          label="External changes"
          value="0"
          detail={hasExecutedAction ? 'local execution only' : 'waiting for local execution'}
        />
      </div>

      <div className="mt-4 rounded-xl border border-knowledge/20 bg-knowledge/10 p-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <div className="text-sm font-medium">{outcome.headline}</div>
            <p className="text-xs text-fg-secondary mt-1 leading-relaxed">
              {outcome.summary}
            </p>
          </div>
          <StatusBadge status={hasExecutedAction ? 'executed' : 'needs_review'} />
        </div>
      </div>
    </section>
  );
}

function OutcomeTile({
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
    <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4 min-w-0">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-bg/40 flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4 text-accent" />
        </div>
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-fg-muted truncate">{label}</div>
          <div className="text-lg font-semibold mt-0.5 truncate">{value}</div>
        </div>
      </div>
      <p className="text-xs text-fg-secondary mt-3 leading-relaxed">{detail}</p>
    </article>
  );
}

function CaseStudySheet({
  open,
  onOpenChange,
  outcome,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  outcome: BuyerOutcome;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto p-0">
        <SheetHeader>
          <SheetTitle>Case study: repeat support tickets</SheetTitle>
          <SheetDescription>
            A buyer-ready story for support teams evaluating resolution memory before automation.
          </SheetDescription>
        </SheetHeader>

        <div className="px-6 pb-6 space-y-5">
          <section className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
            <div className="text-xs uppercase tracking-wider text-fg-muted">Prospect profile</div>
            <h3 className="font-semibold mt-1">B2B SaaS support team with repeat export failures</h3>
            <p className="text-sm text-fg-secondary mt-2 leading-relaxed">
              The team already solved similar export-timeout tickets, but the answers are buried across
              historical cases, comments, and knowledge articles.
            </p>
          </section>

          <div className="grid sm:grid-cols-2 gap-3">
            <CaseStudyBlock
              label="Before Compass"
              items={[
                'Agents search solved tickets manually.',
                'KB gaps are found after volume has already accumulated.',
                'Product follow-up lacks clean repeated-issue evidence.',
              ]}
            />
            <CaseStudyBlock
              label="After Compass"
              items={[
                'Repeat clusters surface from historical tickets.',
                'Prior resolutions become cited playbooks.',
                'Human-reviewed commands create macro, KB, and follow-up artifacts.',
              ]}
            />
          </div>

          <section className="rounded-xl border border-accent/20 bg-accent/5 p-4">
            <div className="text-xs uppercase tracking-wider text-fg-muted">Live demo proof</div>
            <div className="mt-3 grid sm:grid-cols-3 gap-2">
              <MiniStat label="Deflectable tickets" value={formatCount(outcome.deflectableTickets)} />
              <MiniStat label="Local artifacts" value={formatCount(outcome.artifactCount)} />
              <MiniStat label="External changes" value="0" />
            </div>
            <p className="text-sm text-fg-secondary mt-3 leading-relaxed">
              {outcome.summary}
            </p>
          </section>

          <section className="rounded-xl border border-governance/20 bg-governance/10 p-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-governance" />
              <h3 className="font-semibold">Trust layer</h3>
            </div>
            <ul className="mt-3 space-y-2">
              {[
                'Tenant-scoped search and action queues keep customer data isolated.',
                'Every answer and command keeps evidence visible before action.',
                'Approval, readiness, and local execution are recorded in the action timeline.',
                'The demo creates local artifacts only; no helpdesk, KB, or product system is changed.',
              ].map((item) => (
                <li key={item} className="flex gap-2 text-sm text-fg-secondary">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-governance shrink-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
            <div className="text-xs uppercase tracking-wider text-fg-muted">Close</div>
            <p className="text-sm text-fg-secondary mt-2 leading-relaxed">
              Compass is positioned as a support resolution operating layer: it turns messy ticket
              history into searchable memory, prepares reviewable work, and creates the audit trail
              needed before deeper automation.
            </p>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function CaseStudyBlock({ label, items }: { label: string; items: string[] }) {
  return (
    <section className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
      <h3 className="font-semibold">{label}</h3>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-sm text-fg-secondary">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AskToResolutionPanel({
  query,
  suggestions,
  matchedInsight,
  isResolving,
  isSearching,
  isBuildingWorkflow,
  onQueryChange,
  onSubmitSearch,
  onGuidedAsk,
  onResolve,
  onSuggestion,
}: {
  query: string;
  suggestions: readonly string[];
  matchedInsight: SupportRepeatTicketInsight | undefined;
  isResolving: boolean;
  isSearching: boolean;
  isBuildingWorkflow: boolean;
  onQueryChange: (value: string) => void;
  onSubmitSearch: (event: FormEvent) => void;
  onGuidedAsk: () => void;
  onResolve: () => void;
  onSuggestion: (suggestion: string) => void;
}) {
  const busy = isResolving || isSearching || isBuildingWorkflow;

  return (
    <section className="glass-strong rounded-2xl p-4 md:p-6 mb-6 border border-accent/20">
      <div className="grid lg:grid-cols-[1.3fr_0.7fr] gap-5 items-start">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-accent mb-3">
            <Sparkles className="w-4 h-4" />
            Ask Compass
          </div>
          <h2 className="text-xl md:text-2xl font-semibold tracking-tight">
            Tell Compass the support issue. It builds the resolution path.
          </h2>
          <p className="text-sm text-fg-secondary mt-2 max-w-2xl leading-relaxed">
            Start with the customer pain, then move from repeat cluster to solved cases, playbook,
            KB gap, and deflection estimate in one guided pass.
          </p>

          <form onSubmit={onSubmitSearch} className="mt-5">
            <div className="flex flex-col sm:flex-row gap-2">
              <Input
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                placeholder="Ask about a recurring support issue..."
                className="glass border h-11 text-base"
              />
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="lg"
                  onClick={onGuidedAsk}
                  disabled={busy || query.trim().length < 2}
                  className="shrink-0"
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
                  Build path
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={onResolve}
                  disabled={isResolving || query.trim().length < 2}
                  className="shrink-0"
                >
                  {isResolving ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardCheck className="w-4 h-4" />}
                  Answer
                </Button>
              </div>
            </div>
          </form>

          <div className="mt-4 flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onSuggestion(suggestion)}
                className="text-left text-xs px-3 py-2 rounded-md border border-border bg-surface-muted/50 text-fg-secondary hover:text-fg hover:border-border-strong transition"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
          <div className="text-xs uppercase tracking-wider text-fg-muted">Matched repeat cluster</div>
          {matchedInsight ? (
            <div className="mt-3">
              <h3 className="font-semibold">{matchedInsight.title}</h3>
              <p className="text-sm text-fg-secondary mt-2 leading-relaxed">
                {matchedInsight.count} related tickets, with {matchedInsight.potential_deflection_count} likely
                deflection candidates in this sample.
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {matchedInsight.tags.slice(0, 4).map((tag) => (
                  <span key={tag} className="text-[11px] px-1.5 py-0.5 rounded bg-bg/40 text-fg-muted border border-border/50">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-fg-secondary mt-3 leading-relaxed">
              Load demo data or refresh repeat insights to auto-match the ask to a support cluster.
            </p>
          )}
          <div className="mt-4 rounded-lg border border-knowledge/20 bg-knowledge/10 p-3 text-xs text-fg-secondary">
            Review required. Compass prepares an agent command and keeps citations visible before any customer-facing action.
          </div>
        </div>
      </div>
    </section>
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

function GroundedResolutionState({
  resolution,
  workflow,
  action,
}: {
  resolution: SupportResolution | undefined;
  workflow: SupportResolutionWorkflow | undefined;
  action: SupportAction | undefined;
}) {
  const citations = resolution?.citations ?? workflow?.playbook.citations ?? [];
  const confidence = resolution?.confidence ?? workflow?.playbook.confidence;
  const abstained = confidence === 'low' || citations.length === 0;
  const command = workflow ? buildAgentCommand(workflow) : undefined;
  const approval = action ? formatLabel(action.status) : 'Not queued';

  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6" aria-labelledby="grounded-state-heading">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-accent">
            <ShieldCheck className="w-4 h-4" />
            Local demo trust state
          </div>
          <h2 id="grounded-state-heading" className="text-lg font-semibold tracking-tight mt-1">
            Grounded resolution state
          </h2>
          <p className="text-sm text-fg-secondary mt-1">
            Why the answer is usable, what remains reviewable, and what can happen next.
          </p>
        </div>
        <span className="text-[11px] px-2 py-1 rounded border border-governance/20 bg-governance/10 text-governance whitespace-nowrap">
          Local only
        </span>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-2">
        <TrustPill label="Why" value={resolution ? 'Cited answer' : 'Awaiting resolution'} tone="accent" />
        <TrustPill label="Evidence" value={`${citations.length} citation${citations.length === 1 ? '' : 's'}`} tone="knowledge" />
        <TrustPill label="Confidence" value={confidence ? formatLabel(confidence) : 'Pending'} tone="accent" />
        <TrustPill label="Abstention" value={abstained ? 'Review required' : 'Not triggered'} tone={abstained ? 'governance' : 'knowledge'} />
        <TrustPill label="Approval" value={approval} tone="governance" />
      </div>

      <div className="grid lg:grid-cols-[1fr_1fr] gap-3 mt-3">
        <div className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
          <div className="text-xs uppercase tracking-wider text-fg-muted">Next action and risk</div>
          <p className="text-sm text-fg-secondary mt-2">
            {resolution?.next_action ? formatLabel(resolution.next_action) : workflow?.playbook.next_action ? formatLabel(workflow.playbook.next_action) : 'Build or review the resolution first.'}
          </p>
          <p className="text-xs text-fg-muted mt-2">
            Risk: {abstained ? 'Do not act until evidence is reviewed.' : 'Low risk; approval remains mandatory before execution.'}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {citations.slice(0, 5).map((citation) => (
              <span key={`${citation.label}-${citation.source_id}`} className="text-[11px] px-2 py-1 rounded border border-border bg-bg/40 text-fg-muted">
                {citation.label} {citation.title || citation.source_id || citation.source_type}
              </span>
            ))}
            {citations.length === 0 && <span className="text-xs text-fg-muted">No evidence attached.</span>}
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-bg/30 overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-[11px] uppercase tracking-wider text-fg-muted">
            <Terminal className="w-3.5 h-3.5" />
            Typed command
          </div>
          <pre className="max-h-36 overflow-auto p-3 text-xs leading-relaxed text-fg-secondary whitespace-pre-wrap break-words">
            {command || 'No command proposed until a grounded workflow is built.'}
          </pre>
          <div className="border-t border-border/60 px-3 py-2 text-[11px] text-fg-muted">
            {action?.execution_result ? 'Local execution outcome recorded; no external system changed.' : 'Proposal only; human approval is required.'}
          </div>
        </div>
      </div>
    </section>
  );
}

function WorkflowPanel({
  workflow,
  isLoading,
  isError,
  errorMessage,
  isSavingAction,
  onSaveAction,
}: {
  workflow: SupportResolutionWorkflow | undefined;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  isSavingAction: boolean;
  onSaveAction: (workflow: SupportResolutionWorkflow, commandText: string) => void;
}) {
  if (!workflow && !isLoading && !isError) return null;

  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <ClipboardCheck className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Resolution workflow</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            Repeat issue cluster to evidence-backed playbook, KB gap, and deflection estimate.
          </p>
        </div>
      </div>

      {isLoading && <div className="h-56 rounded-xl bg-surface-muted animate-pulse" />}
      {!isLoading && isError && (
        <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-destructive mt-0.5" />
          <div>
            <div className="text-sm font-medium text-destructive">Could not build workflow</div>
            <p className="text-xs text-fg-secondary mt-1">
              {errorMessage || 'Load demo data, index support records, then try again.'}
            </p>
          </div>
        </div>
      )}

      {!isLoading && workflow && (
        <div className="space-y-4">
          <div className="grid md:grid-cols-4 gap-3">
            <WorkflowStep
              label="1. Issue cluster"
              title={workflow.cluster.title}
              body={`${formatCount(workflow.cluster.count)} tickets, ${Math.round(workflow.cluster.share * 100)}% of analyzed volume.`}
            />
            <WorkflowStep
              label="2. Playbook"
              title={formatLabel(workflow.playbook.status)}
              body={`${workflow.playbook.confidence} confidence with ${formatCount(workflow.playbook.evidence_count)} evidence source(s).`}
            />
            <WorkflowStep
              label="3. KB gap"
              title={formatLabel(workflow.knowledge_gap.status)}
              body={`${workflow.knowledge_gap.severity} severity: ${workflow.knowledge_gap.article_title}`}
            />
            <WorkflowStep
              label="4. Deflection"
              title={`${formatCount(workflow.deflection_estimate.potential_ticket_count)} tickets`}
              body={`${workflow.deflection_estimate.confidence} confidence, about ${workflow.deflection_estimate.estimated_agent_hours_saved} agent hours in-sample.`}
            />
          </div>

          <div className="grid lg:grid-cols-[1.2fr_0.8fr] gap-3">
            <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
              <div className="text-xs uppercase tracking-wider text-fg-muted">Evidence-backed playbook</div>
              <h3 className="font-semibold mt-1">{workflow.playbook.title}</h3>
              <div className="mt-3 rounded-lg border border-accent/20 bg-accent/5 p-3 text-sm text-fg-secondary whitespace-pre-wrap leading-relaxed">
                {workflow.playbook.recommended_resolution}
              </div>
              <ol className="mt-4 space-y-2">
                {workflow.playbook.resolution_steps.map((step) => (
                  <li key={step} className="flex gap-2 text-sm text-fg-secondary">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-4">
                <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">Customer response draft</div>
                <p className="text-sm text-fg-secondary leading-relaxed rounded-lg border border-border/70 bg-bg/30 p-3">
                  {workflow.playbook.customer_response_draft}
                </p>
              </div>
            </article>

            <div className="space-y-3">
              <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
                <div className="text-xs uppercase tracking-wider text-fg-muted">Knowledge gap</div>
                <h3 className="font-semibold mt-1">{formatLabel(workflow.knowledge_gap.status)}</h3>
                <p className="text-sm text-fg-secondary mt-2 leading-relaxed">
                  {workflow.knowledge_gap.recommendation}
                </p>
                <p className="text-xs text-fg-muted mt-2">{workflow.knowledge_gap.rationale}</p>
              </article>

              <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
                <div className="text-xs uppercase tracking-wider text-fg-muted">Deflection estimate</div>
                <h3 className="font-semibold mt-1">{workflow.deflection_estimate.rationale}</h3>
                <p className="text-xs text-fg-muted mt-2">{workflow.deflection_estimate.basis}</p>
                <ul className="mt-3 space-y-1.5">
                  {workflow.deflection_estimate.assumptions.map((assumption) => (
                    <li key={assumption} className="text-xs text-fg-secondary">
                      {assumption}
                    </li>
                  ))}
                </ul>
              </article>

              <AgentCommandAction
                workflow={workflow}
                isSavingAction={isSavingAction}
                onSaveAction={onSaveAction}
              />

              <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
                <div className="text-xs uppercase tracking-wider text-fg-muted">Evidence and guardrails</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {workflow.playbook.citations.map((citation) => (
                    <a
                      key={`${citation.label}-${citation.source_id}`}
                      href={citation.source_url || undefined}
                      target="_blank"
                      rel="noreferrer"
                      className={cn(
                        'text-[11px] px-2 py-1 rounded border border-border bg-bg/40 text-fg-muted',
                        citation.source_url && 'hover:text-fg hover:border-border-strong'
                      )}
                    >
                      {citation.label} {citation.title || citation.source_id || citation.source_type}
                    </a>
                  ))}
                  {workflow.playbook.citations.length === 0 && (
                    <span className="text-xs text-fg-muted">No citations yet. Keep this in human review.</span>
                  )}
                </div>
                <ul className="mt-3 space-y-1.5">
                  {workflow.playbook.guardrails.map((guardrail) => (
                    <li key={guardrail} className="text-xs text-fg-secondary">
                      {guardrail}
                    </li>
                  ))}
                </ul>
              </article>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function AgentCommandAction({
  workflow,
  isSavingAction,
  onSaveAction,
}: {
  workflow: SupportResolutionWorkflow;
  isSavingAction: boolean;
  onSaveAction: (workflow: SupportResolutionWorkflow, commandText: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const command = buildAgentCommand(workflow);

  const copyCommand = () => {
    void copyText(command).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    });
  };

  return (
    <article className="rounded-xl border border-accent/25 bg-accent/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-fg-muted">
            <Bot className="w-3.5 h-3.5 text-accent" />
            Agent execution command
          </div>
          <h3 className="font-semibold mt-2">Prepare follow-up work for an agent</h3>
          <p className="text-xs text-fg-secondary mt-2 leading-relaxed">
            Copy this command for manual execution today; future integrations can route the same
            intent to Zendesk, Jira, or a KB writer.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 justify-end">
          <Button type="button" variant="outline" size="sm" onClick={copyCommand}>
            {copied ? <CheckCircle2 className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => onSaveAction(workflow, command)}
            disabled={isSavingAction}
          >
            {isSavingAction ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Clock className="w-3.5 h-3.5" />}
            Queue
          </Button>
        </div>
      </div>
      <div className="mt-3 rounded-lg border border-border/70 bg-bg/40 overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-[11px] uppercase tracking-wider text-fg-muted">
          <Terminal className="w-3.5 h-3.5" />
          support.agent.execute
        </div>
        <pre className="max-h-72 overflow-auto p-3 text-xs leading-relaxed text-fg-secondary whitespace-pre-wrap break-words">
          {command}
        </pre>
      </div>
    </article>
  );
}

function buildAgentCommand(workflow: SupportResolutionWorkflow) {
  const citations = workflow.playbook.citations
    .slice(0, 5)
    .map((citation) => `- ${citation.label}: ${citation.title || citation.source_id || citation.source_type}`)
    .join('\n');
  const guardrails = workflow.playbook.guardrails.map((guardrail) => `- ${guardrail}`).join('\n');
  const steps = workflow.playbook.resolution_steps.map((step, idx) => `${idx + 1}. ${step}`).join('\n');

  return [
    '/support.agent.execute',
    `cluster: ${workflow.cluster.title}`,
    `objective: Reduce repeat tickets by preparing reviewed support follow-up for ${workflow.cluster.count} related ticket(s).`,
    `confidence: ${workflow.playbook.confidence}`,
    '',
    'tasks:',
    '- Validate the cited solved cases and article evidence.',
    '- Draft or update a support macro using the customer response draft.',
    `- Draft or update KB article: ${workflow.knowledge_gap.article_title}.`,
    '- Create a product follow-up if evidence points to a product defect or stale behavior.',
    '- Return a review checklist before anything is published or sent.',
    '',
    'recommended_resolution:',
    workflow.playbook.recommended_resolution,
    '',
    'resolution_steps:',
    steps,
    '',
    'customer_response_draft:',
    workflow.playbook.customer_response_draft,
    '',
    'knowledge_gap:',
    workflow.knowledge_gap.recommendation,
    '',
    'deflection_estimate:',
    `${workflow.deflection_estimate.potential_ticket_count} ticket(s); ${workflow.deflection_estimate.rationale}`,
    '',
    'evidence:',
    citations || '- No citations available; keep this in human review.',
    '',
    'guardrails:',
    guardrails || '- Human review required before any customer-facing action.',
  ].join('\n');
}

function ActionQueuePanel({
  actions,
  isLoading,
  isRefreshing,
  updatingActionId,
  executingActionId,
  onRefresh,
  onUpdateStatus,
  onExecute,
}: {
  actions: SupportAction[];
  isLoading: boolean;
  isRefreshing: boolean;
  updatingActionId: string | undefined;
  executingActionId: string | undefined;
  onRefresh: () => void;
  onUpdateStatus: (actionId: string, status: SupportActionStatus) => void;
  onExecute: (actionId: string) => void;
}) {
  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Approval action queue</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            Local-only command actions move through review before any future integration can execute them.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn('w-3.5 h-3.5', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {isLoading && <div className="h-24 rounded-xl bg-surface-muted animate-pulse" />}
      {!isLoading && actions.length === 0 && (
        <div className="rounded-xl border border-border bg-surface-muted/40 p-4 text-sm text-fg-secondary">
          No queued actions yet. Build a resolution workflow, then queue the generated agent command for review.
        </div>
      )}
      {!isLoading && actions.length > 0 && (
        <div className="grid lg:grid-cols-2 gap-3">
          {actions.slice(0, 4).map((action) => (
            <ActionQueueCard
              key={action.id}
              action={action}
              isUpdating={updatingActionId === action.id}
              isExecuting={executingActionId === action.id}
              onUpdateStatus={onUpdateStatus}
              onExecute={onExecute}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ActionQueueCard({
  action,
  isUpdating,
  isExecuting,
  onUpdateStatus,
  onExecute,
}: {
  action: SupportAction;
  isUpdating: boolean;
  isExecuting: boolean;
  onUpdateStatus: (actionId: string, status: SupportActionStatus) => void;
  onExecute: (actionId: string) => void;
}) {
  const nextStatus = nextActionStatus(action.status);
  const trust = actionTrustSummary(action);
  const result = executionResultSummary(action.execution_result);

  return (
    <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wider text-fg-muted">Agent command</div>
          <h3 className="font-semibold mt-1 truncate">{action.cluster_title}</h3>
          <p className="text-xs text-fg-muted mt-1 font-mono truncate">{action.id}</p>
        </div>
        <StatusBadge status={action.status} />
      </div>
      <p className="text-sm text-fg-secondary mt-3 leading-relaxed line-clamp-3">
        {firstCommandTask(action.command_text)}
      </p>

      <div className="mt-4 grid sm:grid-cols-3 gap-2">
        <TrustPill label="Permission" value={trust.permission} tone="accent" />
        <TrustPill label="Evidence" value={trust.evidence} tone="knowledge" />
        <TrustPill label="Boundary" value="Local mock only" tone="governance" />
      </div>

      <div className="mt-4 rounded-lg border border-border/70 bg-bg/30 p-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-fg-muted mb-2">
          <ShieldCheck className="w-3.5 h-3.5 text-governance" />
          Audit timeline
        </div>
        <div className="space-y-2">
          {actionTimeline(action).map((item) => (
            <div key={item.label} className="flex items-start gap-2 text-xs">
              <span className={cn('mt-1.5 w-1.5 h-1.5 rounded-full shrink-0', item.done ? 'bg-knowledge' : 'bg-border-strong')} />
              <div className="min-w-0">
                <div className={item.done ? 'text-fg-secondary' : 'text-fg-muted'}>{item.label}</div>
                {item.detail && <div className="text-fg-muted truncate">{item.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {result && (
        <div className="mt-3 rounded-lg border border-knowledge/20 bg-knowledge/10 p-3">
          <div className="text-xs uppercase tracking-wider text-fg-muted">Execution result</div>
          <div className="text-sm font-medium mt-1">{result.summary}</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {result.artifacts.map((artifact) => (
              <span key={artifact} className="text-[11px] px-2 py-1 rounded border border-knowledge/20 bg-bg/40 text-fg-secondary">
                {artifact}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {nextStatus && (
          <Button
            size="sm"
            onClick={() => onUpdateStatus(action.id, nextStatus.status)}
            disabled={isUpdating}
          >
            {isUpdating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            {nextStatus.label}
          </Button>
        )}
        {action.status === 'ready_to_execute' && (
          <Button
            size="sm"
            onClick={() => onExecute(action.id)}
            disabled={isUpdating || isExecuting}
          >
            {isExecuting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
            Execute local
          </Button>
        )}
        {action.status !== 'rejected' && action.status !== 'ready_to_execute' && action.status !== 'executed' && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onUpdateStatus(action.id, 'rejected')}
            disabled={isUpdating}
          >
            Reject
          </Button>
        )}
      </div>
    </article>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('text-[11px] px-2 py-1 rounded border capitalize whitespace-nowrap', ACTION_STATUS_TONE[status] ?? ACTION_STATUS_TONE.generated)}>
      {formatLabel(status)}
    </span>
  );
}

function TrustPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'accent' | 'knowledge' | 'governance';
}) {
  const toneClass = {
    accent: 'border-accent/20 bg-accent/10',
    knowledge: 'border-knowledge/20 bg-knowledge/10',
    governance: 'border-governance/20 bg-governance/10',
  }[tone];

  return (
    <div className={cn('rounded-lg border p-2 min-w-0', toneClass)}>
      <div className="text-[10px] uppercase tracking-wider text-fg-muted">{label}</div>
      <div className="text-xs text-fg-secondary mt-1 truncate">{value}</div>
    </div>
  );
}

function actionTrustSummary(action: SupportAction) {
  const citations = workflowArray(action.workflow, 'citations');
  const evidence = citations.length > 0 ? `${citations.length} source${citations.length === 1 ? '' : 's'}` : 'Needs evidence';
  const permission = action.approved_by
    ? `Approved by ${action.approved_by}`
    : action.status === 'generated'
      ? 'Draft only'
      : 'Review pending';
  return { evidence, permission };
}

function actionTimeline(action: SupportAction) {
  const executed = action.status === 'executed';
  const rejected = action.status === 'rejected';
  return [
    {
      label: 'Generated',
      done: true,
      detail: `${action.created_by} ${formatRelative(action.created_at)}`,
    },
    {
      label: 'Submitted for review',
      done: ['needs_review', 'approved', 'ready_to_execute', 'executed'].includes(action.status),
      detail: action.review_notes || undefined,
    },
    {
      label: 'Approved',
      done: Boolean(action.approved_at),
      detail: action.approved_by ? `${action.approved_by} ${formatRelative(action.approved_at)}` : undefined,
    },
    {
      label: 'Ready to execute',
      done: Boolean(action.ready_at),
      detail: action.ready_at ? formatRelative(action.ready_at) : undefined,
    },
    {
      label: rejected ? 'Rejected' : 'Executed locally',
      done: executed || rejected,
      detail: rejected
        ? formatRelative(action.rejected_at)
        : action.executed_by
          ? `${action.executed_by} ${formatRelative(action.executed_at)}`
          : undefined,
    },
  ];
}

function executionResultSummary(result: Record<string, unknown> | null) {
  if (!isRecord(result)) return null;
  const rawArtifacts = Array.isArray(result.artifacts) ? result.artifacts : [];
  const artifacts = rawArtifacts
    .map((artifact) => {
      if (!isRecord(artifact)) return null;
      const title = typeof artifact.title === 'string' ? artifact.title : undefined;
      const type = typeof artifact.type === 'string' ? formatLabel(artifact.type) : undefined;
      return title || type || null;
    })
    .filter((artifact): artifact is string => Boolean(artifact))
    .slice(0, 3);
  const impact = isRecord(result.impact) && typeof result.impact.summary === 'string'
    ? result.impact.summary
    : undefined;
  return {
    summary: impact || `${artifacts.length} local artifact${artifacts.length === 1 ? '' : 's'} created.`,
    artifacts: artifacts.length > 0 ? artifacts : ['Local artifact log'],
  };
}

function buildBuyerOutcome(
  action: SupportAction | undefined,
  summary: RepeatSummary | undefined
): BuyerOutcome {
  const workflow = isRecord(action?.workflow) ? action.workflow : {};
  const deflection = isRecord(workflow.deflection_estimate) ? workflow.deflection_estimate : {};
  const execution = isRecord(action?.execution_result) ? action.execution_result : {};
  const rawArtifacts = Array.isArray(execution.artifacts) ? execution.artifacts : [];
  const artifactTypes = rawArtifacts
    .map((artifact) => (isRecord(artifact) && typeof artifact.type === 'string' ? artifact.type : null))
    .filter((type): type is string => Boolean(type));
  const deflectableTickets = numberFromUnknown(deflection.potential_ticket_count)
    ?? summary?.potential_deflection_count
    ?? 0;
  const executed = action?.status === 'executed';

  return {
    headline: executed
      ? 'Reviewed support work is ready without touching external systems.'
      : 'Run the demo to produce the buyer-facing outcome proof.',
    summary: executed
      ? `${formatCount(deflectableTickets)} repeat ticket${deflectableTickets === 1 ? '' : 's'} can be targeted with a reviewed macro, KB update, and product follow-up while keeping execution local.`
      : 'The next completed run will show deflection opportunity, prepared artifacts, and the human-trust boundary for a prospect conversation.',
    deflectableTickets,
    artifactCount: artifactTypes.length,
    macroDrafted: artifactTypes.includes('support_macro'),
    kbDrafted: artifactTypes.includes('kb_update'),
    followUpPrepared: artifactTypes.includes('product_follow_up'),
  };
}

function workflowArray(workflow: Record<string, unknown>, key: 'citations') {
  const playbook = isRecord(workflow.playbook) ? workflow.playbook : {};
  const value = playbook[key];
  return Array.isArray(value) ? value : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function numberFromUnknown(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function nextActionStatus(status: SupportActionStatus) {
  if (status === 'generated') return { status: 'needs_review', label: 'Submit review' };
  if (status === 'needs_review') return { status: 'approved', label: 'Approve' };
  if (status === 'approved') return { status: 'ready_to_execute', label: 'Mark ready' };
  return null;
}

function firstCommandTask(commandText: string) {
  const task = commandText
    .split('\n')
    .find((line) => line.startsWith('- ') && !line.includes('Validate the cited'));
  return task?.replace(/^- /, '') || commandText.split('\n')[0] || 'Agent command queued for review.';
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall back to a temporary textarea when browser permissions block clipboard access.
    }
  }

  const textArea = document.createElement('textarea');
  textArea.value = value;
  textArea.setAttribute('readonly', 'true');
  textArea.style.position = 'fixed';
  textArea.style.left = '-9999px';
  textArea.style.top = '0';
  document.body.appendChild(textArea);
  textArea.select();
  document.execCommand('copy');
  document.body.removeChild(textArea);
}

function WorkflowStep({ label, title, body }: { label: string; title: string; body: string }) {
  return (
    <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
      <div className="text-[11px] uppercase tracking-wider text-fg-muted">{label}</div>
      <div className="font-semibold mt-1">{title}</div>
      <p className="text-xs text-fg-secondary mt-2 leading-relaxed">{body}</p>
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

function JobStatusPanel({
  jobs,
  isLoading,
  isRefreshing,
  onRefresh,
}: {
  jobs: SupportJob[];
  isLoading: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const latest = jobs[0];
  const active = jobs.find((job) => job.status === 'queued' || job.status === 'running');
  const visibleJobs = jobs.slice(0, 3);

  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Sync and indexing jobs</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            Production runs this through a dedicated durable support-worker deployment; local dev may use an embedded runner.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn('w-3.5 h-3.5', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {isLoading && <div className="h-16 rounded-xl bg-surface-muted animate-pulse" />}
      {!isLoading && !latest && (
        <div className="rounded-xl border border-border bg-surface-muted/40 p-4 text-sm text-fg-secondary">
          No background jobs yet. Use <span className="text-fg">Sync + index</span> when connectors are configured,
          or load demo data for a local customer-support walkthrough.
        </div>
      )}
      {!isLoading && latest && (
        <div className="grid lg:grid-cols-[1fr_1.2fr] gap-3">
          <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-wider text-fg-muted">
                  {active ? 'Active pipeline' : 'Latest pipeline'}
                </div>
                <div className="font-medium mt-1">{formatJobStep((active ?? latest).current_step)}</div>
              </div>
              <JobStatusBadge status={(active ?? latest).status} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-fg-muted">
              {(active ?? latest).providers.map((provider) => (
                <span key={provider} className="px-2 py-1 rounded border border-border bg-bg/40 font-mono uppercase">
                  {provider}
                </span>
              ))}
              <span className="px-2 py-1 rounded border border-border bg-bg/40">
                Limit {(active ?? latest).limit}
              </span>
              {(active ?? latest).seed_demo && (
                <span className="px-2 py-1 rounded border border-border bg-bg/40">Includes demo seed</span>
              )}
            </div>
            {(active ?? latest).error_message && (
              <p className="text-xs text-destructive mt-3 line-clamp-2">{(active ?? latest).error_message}</p>
            )}
          </article>

          <div className="space-y-2">
            {visibleJobs.map((job) => (
              <article key={job.id} className="rounded-xl border border-border/70 bg-surface-muted/25 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-fg truncate">{job.id}</div>
                    <div className="text-[11px] text-fg-muted mt-1">
                      {formatJobStep(job.current_step)} · {formatJobTime(job)}
                    </div>
                  </div>
                  <JobStatusBadge status={job.status} />
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function RepeatInsightsPanel({
  insights,
  summary,
  isLoading,
  isError,
  isRefreshing,
  onRefresh,
  onSearchQuery,
  onBuildWorkflow,
}: {
  insights: SupportRepeatTicketInsight[];
  summary:
    | {
        tickets_analyzed: number;
        total_tickets: number;
        repeat_clusters: number;
        repeat_ticket_count: number;
        potential_deflection_count: number;
      }
    | undefined;
  isLoading: boolean;
  isError: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
  onSearchQuery: (query: string) => void;
  onBuildWorkflow: (insight: SupportRepeatTicketInsight) => void;
}) {
  return (
    <section className="glass rounded-2xl p-4 md:p-5 mb-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <TrendingDown className="w-4 h-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">Repeat-ticket insights</h2>
          </div>
          <p className="text-sm text-fg-secondary mt-1">
            Spot issue clusters that should become macros, help articles, or automated deflection.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn('w-3.5 h-3.5', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {isLoading && <div className="h-36 rounded-xl bg-surface-muted animate-pulse" />}
      {!isLoading && isError && (
        <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-destructive mt-0.5" />
          <div>
            <div className="text-sm font-medium text-destructive">Could not load repeat insights</div>
            <p className="text-xs text-fg-secondary mt-1">
              The local database may be unavailable. Load demo data and refresh this panel.
            </p>
          </div>
        </div>
      )}
      {!isLoading && !isError && insights.length === 0 && (
        <div className="rounded-xl border border-border bg-surface-muted/40 p-5 text-sm text-fg-secondary">
          No repeat clusters yet. Load demo data to see local patterns, or sync more support tickets
          before relying on ticket deflection recommendations.
        </div>
      )}
      {!isLoading && !isError && insights.length > 0 && (
        <>
          <div className="grid sm:grid-cols-3 gap-2 mb-4">
            <MiniStat label="Tickets analyzed" value={formatCount(summary?.tickets_analyzed ?? 0)} />
            <MiniStat label="Repeat tickets" value={formatCount(summary?.repeat_ticket_count ?? 0)} />
            <MiniStat
              label="Deflection potential"
              value={formatCount(summary?.potential_deflection_count ?? 0)}
            />
          </div>
          <div className="grid lg:grid-cols-3 gap-3">
            {insights.slice(0, 3).map((insight) => (
              <RepeatInsightCard
                key={insight.id}
                insight={insight}
                onSearchQuery={onSearchQuery}
                onBuildWorkflow={onBuildWorkflow}
              />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-surface-muted/30 p-3">
      <div className="text-[11px] uppercase tracking-wider text-fg-muted">{label}</div>
      <div className="text-lg font-semibold mt-1">{value}</div>
    </div>
  );
}

function RepeatInsightCard({
  insight,
  onSearchQuery,
  onBuildWorkflow,
}: {
  insight: SupportRepeatTicketInsight;
  onSearchQuery: (query: string) => void;
  onBuildWorkflow: (insight: SupportRepeatTicketInsight) => void;
}) {
  const share = Math.round(insight.share * 100);
  const statusText = Object.entries(insight.statuses)
    .map(([status, count]) => `${count} ${status}`)
    .join(', ');

  return (
    <article className="rounded-xl border border-border/70 bg-surface-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-fg-muted">Repeat cluster</div>
          <h3 className="font-semibold mt-1">{insight.title}</h3>
        </div>
        <span className="text-xs px-2 py-1 rounded border border-accent/25 bg-accent/10 text-accent whitespace-nowrap">
          {insight.count} tickets
        </span>
      </div>
      <p className="text-xs text-fg-secondary mt-3 leading-relaxed">
        {share}% of analyzed tickets. {insight.recommended_action}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {insight.tags.slice(0, 4).map((tag) => (
          <span key={tag} className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-fg-muted border border-border/50">
            {tag}
          </span>
        ))}
      </div>
      <div className="text-[11px] text-fg-muted mt-3">
        {statusText}
        {insight.latest_updated_at ? ` · Latest ${formatRelative(insight.latest_updated_at)}` : ''}
      </div>
      <ul className="mt-3 space-y-1.5">
        {insight.sample_tickets.slice(0, 2).map((ticket) => (
          <li key={`${ticket.provider}-${ticket.external_id}`} className="text-xs text-fg-secondary line-clamp-1">
            {ticket.subject}
          </li>
        ))}
      </ul>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button size="sm" onClick={() => onBuildWorkflow(insight)}>
          <ClipboardCheck className="w-3.5 h-3.5" />
          Playbook
        </Button>
        <Button variant="outline" size="sm" onClick={() => onSearchQuery(insight.related_query)}>
          <Search className="w-3.5 h-3.5" />
          Cases
        </Button>
      </div>
    </article>
  );
}

function JobStatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('text-[11px] px-2 py-1 rounded border capitalize', JOB_STATUS_TONE[status] ?? JOB_STATUS_TONE.queued)}>
      {status}
    </span>
  );
}

function formatLabel(value: string) {
  return value.replace(/_/g, ' ');
}

function formatJobStep(step: string | null) {
  if (!step) return 'Waiting to start';
  return formatLabel(step);
}

function formatJobTime(job: SupportJob) {
  if (job.finished_at) return `Finished ${formatRelative(job.finished_at)}`;
  if (job.started_at) return `Started ${formatRelative(job.started_at)}`;
  return `Queued ${formatRelative(job.created_at)}`;
}

function findBestRepeatInsight(query: string, insights: SupportRepeatTicketInsight[]) {
  const queryTerms = meaningfulTerms(query);
  if (queryTerms.length === 0) return insights[0];

  let best: { insight: SupportRepeatTicketInsight; score: number } | undefined;
  for (const insight of insights) {
    const haystack = [
      insight.title,
      insight.related_query,
      insight.recommended_action,
      ...insight.tags,
      ...insight.signals,
      ...insight.sample_tickets.map((ticket) => ticket.subject),
    ]
      .join(' ')
      .toLowerCase();
    const score = queryTerms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0);
    if (!best || score > best.score) {
      best = { insight, score };
    }
  }

  return best && best.score > 0 ? best.insight : insights[0];
}

function meaningfulTerms(value: string) {
  const stopWords = new Set([
    'about',
    'again',
    'could',
    'does',
    'have',
    'happen',
    'happening',
    'resolved',
    'support',
    'ticket',
    'tickets',
    'which',
    'why',
  ]);
  return value
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((term) => term.length > 2 && !stopWords.has(term));
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
                {result.retrieval_source && <RetrievalPill source={result.retrieval_source} />}
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

function RetrievalPill({ source }: { source: string }) {
  const tone =
    source === 'hybrid'
      ? 'text-knowledge bg-knowledge/10 border-knowledge/20'
      : source === 'lexical'
        ? 'text-accent bg-accent/10 border-accent/20'
        : 'text-fg-muted bg-surface-muted border-border';
  return <span className={cn('px-1.5 py-0.5 rounded border text-[11px]', tone)}>{source}</span>;
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

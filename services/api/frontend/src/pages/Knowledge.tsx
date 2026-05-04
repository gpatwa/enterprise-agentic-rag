import { useState } from 'react';
import { BookOpen, ClipboardList, Code2, Plus, Trash2, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useToast } from '@/components/ui/use-toast';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  useBusinessRules,
  useCodeContext,
  useCreateBusinessRule,
  useCreateCodeContext,
  useCreateGlossaryTerm,
  useDeleteAnnotation,
  useDeleteBusinessRule,
  useDeleteCodeContext,
  useGlossary,
} from '@/lib/queries';
import { formatRelative } from '@/lib/format';

export function KnowledgePage() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-8">
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">Knowledge</div>
          <h1 className="text-2xl font-semibold tracking-tight">Knowledge layers</h1>
          <p className="text-fg-secondary mt-2 text-base max-w-2xl">
            Definitions, business rules, and code lineage applied to every Compass answer.
            Token-budgeted, role-scoped, and version-controlled.
          </p>
        </header>

        <Tabs defaultValue="glossary">
          <TabsList>
            <TabsTrigger value="glossary">Glossary</TabsTrigger>
            <TabsTrigger value="rules">Business rules</TabsTrigger>
            <TabsTrigger value="code">Code &amp; lineage</TabsTrigger>
          </TabsList>

          <TabsContent value="glossary">
            <GlossaryTab />
          </TabsContent>
          <TabsContent value="rules">
            <BusinessRulesTab />
          </TabsContent>
          <TabsContent value="code">
            <CodeContextTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// ── Glossary ────────────────────────────────────────────────────────

function GlossaryTab() {
  const { data, isLoading, error } = useGlossary();
  const items = data ?? [];

  return (
    <SectionShell
      icon={BookOpen}
      title="Glossary terms"
      description='Define what "revenue", "active customer", "MRR" mean at your company. Compass injects matching definitions into the answer.'
      empty={{
        title: 'No glossary terms yet',
        body: 'Add a term to see it applied automatically the next time someone asks a related question.',
      }}
      addAction={<NewGlossaryDialog />}
      isLoading={isLoading}
      error={error}
      isEmpty={items.length === 0}
    >
      <ul className="glass rounded-xl divide-y divide-border/40">
        {items.map((a) => (
          <GlossaryRow key={a.id} id={a.id} term={a.key} definition={a.value} created_at={a.created_at} />
        ))}
      </ul>
    </SectionShell>
  );
}

function GlossaryRow({
  id,
  term,
  definition,
  created_at,
}: {
  id: number;
  term: string;
  definition: string;
  created_at: string;
}) {
  const del = useDeleteAnnotation();
  const { toast } = useToast();
  const remove = () => {
    if (!confirm(`Delete "${term}"?`)) return;
    del.mutate(id, { onSuccess: () => toast({ title: 'Deleted', description: term }) });
  };
  return (
    <li className="group flex items-start gap-3 px-4 py-3 hover:bg-white/[0.03] transition">
      <BookOpen className="w-4 h-4 text-knowledge flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg">{term}</div>
        <div className="text-xs text-fg-secondary mt-0.5">{definition}</div>
        <div className="text-[10px] text-fg-muted mt-1">Added {formatRelative(created_at)}</div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={remove}
            className="text-fg-muted hover:text-destructive p-1.5 rounded-md hover:bg-white/5 transition opacity-0 group-hover:opacity-100"
            aria-label="Delete"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Delete</TooltipContent>
      </Tooltip>
    </li>
  );
}

function NewGlossaryDialog() {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState('');
  const [def, setDef] = useState('');
  const create = useCreateGlossaryTerm();
  const { toast } = useToast();

  const submit = () => {
    if (!term.trim() || !def.trim()) return;
    create.mutate(
      { key: term.trim(), value: def.trim() },
      {
        onSuccess: () => {
          toast({ title: 'Term added', description: term });
          setTerm('');
          setDef('');
          setOpen(false);
        },
        onError: () =>
          toast({
            title: 'Failed to add term',
            description: 'Check the backend connection and try again.',
            variant: 'destructive',
          }),
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4" />
          New term
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New glossary term</DialogTitle>
          <DialogDescription>
            Compass injects matching definitions into every relevant answer.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Term" id="term">
            <Input id="term" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="e.g. Active Customer" className="glass border" />
          </Field>
          <Field label="Definition" id="def">
            <textarea
              id="def"
              value={def}
              onChange={(e) => setDef(e.target.value)}
              placeholder="A customer with at least one paid order in the last 90 days."
              rows={3}
              className="glass border w-full rounded-md px-3 py-2 text-sm resize-none"
            />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!term.trim() || !def.trim() || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add term'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Business rules ──────────────────────────────────────────────────

function BusinessRulesTab() {
  const { data, isLoading, error } = useBusinessRules();
  const items = data ?? [];

  return (
    <SectionShell
      icon={ClipboardList}
      title="Business rules"
      description="Recognition policies, exclusion rules, and policy guardrails Compass applies before generating an answer."
      empty={{
        title: 'No rules yet',
        body: 'Add a rule (e.g. "exclude returns from revenue") to enforce business policy on every answer.',
      }}
      addAction={<NewBusinessRuleDialog />}
      isLoading={isLoading}
      error={error}
      isEmpty={items.length === 0}
    >
      <ul className="glass rounded-xl divide-y divide-border/40">
        {items.map((r) => (
          <RuleRow
            key={r.id}
            id={r.id}
            title={r.key}
            description={r.value}
            roles={r.applies_to_roles}
            priority={r.priority}
            created_at={r.created_at}
          />
        ))}
      </ul>
    </SectionShell>
  );
}

function RuleRow({
  id,
  title,
  description,
  roles,
  priority,
  created_at,
}: {
  id: number;
  title: string;
  description: string;
  roles?: string[];
  priority?: number;
  created_at: string;
}) {
  const del = useDeleteBusinessRule();
  const { toast } = useToast();
  const remove = () => {
    if (!confirm(`Delete "${title}"?`)) return;
    del.mutate(id, { onSuccess: () => toast({ title: 'Deleted', description: title }) });
  };
  return (
    <li className="group flex items-start gap-3 px-4 py-3 hover:bg-white/[0.03] transition">
      <ClipboardList className="w-4 h-4 text-data flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg flex items-center gap-2">
          {title}
          {priority != null && priority > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-governance/15 text-governance border border-governance/25">
              P{priority}
            </span>
          )}
        </div>
        <div className="text-xs text-fg-secondary mt-0.5">{description}</div>
        <div className="text-[10px] text-fg-muted mt-1 flex flex-wrap gap-x-2">
          {roles && roles.length > 0 && <span>Roles: {roles.join(', ')}</span>}
          <span>Added {formatRelative(created_at)}</span>
        </div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={remove}
            className="text-fg-muted hover:text-destructive p-1.5 rounded-md hover:bg-white/5 transition opacity-0 group-hover:opacity-100"
            aria-label="Delete"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Delete</TooltipContent>
      </Tooltip>
    </li>
  );
}

function NewBusinessRuleDialog() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [contextType, setContextType] = useState('business_rule');
  const [priority, setPriority] = useState(1);
  const create = useCreateBusinessRule();
  const { toast } = useToast();

  const submit = () => {
    if (!title.trim() || !body.trim()) return;
    create.mutate(
      { context_type: contextType, key: title.trim(), value: body.trim(), priority },
      {
        onSuccess: () => {
          toast({ title: 'Rule added', description: title });
          setTitle('');
          setBody('');
          setOpen(false);
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4" />
          New rule
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New business rule</DialogTitle>
          <DialogDescription>
            Compass applies this rule to every relevant query before generating an answer.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Name" id="rule-title">
            <Input id="rule-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Recognition policy" className="glass border" />
          </Field>
          <Field label="Description" id="rule-body">
            <textarea
              id="rule-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Revenue is recognized at delivery, not at purchase. Returns are excluded."
              rows={3}
              className="glass border w-full rounded-md px-3 py-2 text-sm resize-none"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type" id="rule-type">
              <Input id="rule-type" value={contextType} onChange={(e) => setContextType(e.target.value)} className="glass border" />
            </Field>
            <Field label="Priority (higher = more important)" id="rule-priority">
              <Input
                id="rule-priority"
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value) || 0)}
                className="glass border"
              />
            </Field>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!title.trim() || !body.trim() || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add rule'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Code context ────────────────────────────────────────────────────

function CodeContextTab() {
  const { data, isLoading, error } = useCodeContext();
  const items = data ?? [];

  return (
    <SectionShell
      icon={Code2}
      title="Code &amp; lineage"
      description="Pipeline names, table lineage, code ownership. Compass uses these when answering engineering questions."
      empty={{
        title: 'No code context yet',
        body: 'Add an entry to teach Compass about your data pipelines, services, or models.',
      }}
      addAction={<NewCodeContextDialog />}
      isLoading={isLoading}
      error={error}
      isEmpty={items.length === 0}
    >
      <ul className="glass rounded-xl divide-y divide-border/40">
        {items.map((c) => (
          <CodeRow
            key={c.id}
            id={c.id}
            name={c.name}
            description={c.description}
            type={c.context_type}
            created_at={c.created_at}
          />
        ))}
      </ul>
    </SectionShell>
  );
}

function CodeRow({
  id,
  name,
  description,
  type,
  created_at,
}: {
  id: number;
  name: string;
  description: string;
  type: string;
  created_at: string;
}) {
  const del = useDeleteCodeContext();
  const { toast } = useToast();
  const remove = () => {
    if (!confirm(`Delete "${name}"?`)) return;
    del.mutate(id, { onSuccess: () => toast({ title: 'Deleted', description: name }) });
  };
  return (
    <li className="group flex items-start gap-3 px-4 py-3 hover:bg-white/[0.03] transition">
      <Code2 className="w-4 h-4 text-accent flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg flex items-center gap-2">
          {name}
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-muted text-fg-secondary font-mono">
            {type}
          </span>
        </div>
        <div className="text-xs text-fg-secondary mt-0.5">{description}</div>
        <div className="text-[10px] text-fg-muted mt-1">Added {formatRelative(created_at)}</div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={remove}
            className="text-fg-muted hover:text-destructive p-1.5 rounded-md hover:bg-white/5 transition opacity-0 group-hover:opacity-100"
            aria-label="Delete"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Delete</TooltipContent>
      </Tooltip>
    </li>
  );
}

function NewCodeContextDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [contextType, setContextType] = useState('etl_pipeline');
  const create = useCreateCodeContext();
  const { toast } = useToast();

  const submit = () => {
    if (!name.trim() || !description.trim()) return;
    create.mutate(
      { context_type: contextType, name: name.trim(), description: description.trim() },
      {
        onSuccess: () => {
          toast({ title: 'Code context added', description: name });
          setName('');
          setDescription('');
          setOpen(false);
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4" />
          New entry
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New code context</DialogTitle>
          <DialogDescription>
            Pipeline, model, or service Compass should know about.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Name" id="cc-name">
            <Input
              id="cc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. orders_dbt_model"
              className="glass border"
            />
          </Field>
          <Field label="Description" id="cc-desc">
            <textarea
              id="cc-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Salesforce → Fivetran → dbt → Postgres. Refreshes every 1h."
              rows={3}
              className="glass border w-full rounded-md px-3 py-2 text-sm resize-none"
            />
          </Field>
          <Field label="Type" id="cc-type">
            <Input
              id="cc-type"
              value={contextType}
              onChange={(e) => setContextType(e.target.value)}
              placeholder="etl_pipeline, sql_query, api_endpoint, data_lineage…"
              className="glass border"
            />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!name.trim() || !description.trim() || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add entry'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Shared section shell ────────────────────────────────────────────

function SectionShell({
  icon: Icon,
  title,
  description,
  empty,
  addAction,
  isLoading,
  error,
  isEmpty,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  empty: { title: string; body: string };
  addAction: React.ReactNode;
  isLoading: boolean;
  error: unknown;
  isEmpty: boolean;
  children: React.ReactNode;
}) {
  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <p className="text-sm text-fg-secondary mt-1 max-w-2xl">{description}</p>
        </div>
        {addAction}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[0, 1].map((i) => (
            <div key={i} className="glass rounded-md h-16 animate-pulse" />
          ))}
        </div>
      )}

      {error != null && (
        <div className="glass rounded-md p-4 text-sm text-fg-secondary">
          Couldn't load. Make sure the backend is reachable and{' '}
          <code className="font-mono">CONTEXT_LAYERS_ENABLED=true</code>.
        </div>
      )}

      {!isLoading && error == null && isEmpty && (
        <div className="glass rounded-xl px-8 py-12 text-center">
          <Icon className="w-7 h-7 text-fg-muted mx-auto mb-3" />
          <h3 className="font-semibold text-base mb-1">{empty.title}</h3>
          <p className="text-sm text-fg-secondary max-w-sm mx-auto">{empty.body}</p>
        </div>
      )}

      {!isLoading && error == null && !isEmpty && children}
    </TooltipProvider>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-xs text-fg-muted block mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}

import { useState } from 'react';
import {
  Bot,
  BookOpen,
  Code2,
  Database,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import { cn } from '@/lib/utils';

/**
 * /agents — Skills marketplace skeleton.
 *
 * Strategy (from "one product, layered surfaces" memo):
 *   Skills are pre-configured bundles (glossary + connectors + prompts +
 *   actions) per persona. Q3 deliverable. This page is the catalog.
 */

interface Skill {
  id: string;
  persona: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tone: { bg: string; text: string; ring: string };
  bundles: { icon: LucideIcon; label: string; items: string[] }[];
  status: 'available' | 'coming-soon';
}

const KNOWLEDGE_TONE = { bg: 'bg-knowledge/15', text: 'text-knowledge', ring: 'ring-knowledge/30' };
const DATA_TONE = { bg: 'bg-data/15', text: 'text-data', ring: 'ring-data/30' };
const ACCENT_TONE = { bg: 'bg-accent/15', text: 'text-accent', ring: 'ring-accent/30' };
const GOV_TONE = {
  bg: 'bg-governance/15',
  text: 'text-governance',
  ring: 'ring-governance/30',
};
const DESTRUCTIVE_TONE = {
  bg: 'bg-destructive/15',
  text: 'text-destructive',
  ring: 'ring-destructive/30',
};
const MUTED_TONE = {
  bg: 'bg-fg-muted/10',
  text: 'text-fg-secondary',
  ring: 'ring-fg-muted/20',
};

const SKILLS: Skill[] = [
  {
    id: 'finance',
    persona: 'Finance',
    title: 'Finance Skill',
    description:
      'Board-ready answers: revenue, margin, churn, forecast, and recognition policy. Bundled glossary and audit defaults.',
    icon: TrendingUp,
    tone: KNOWLEDGE_TONE,
    bundles: [
      {
        icon: BookOpen,
        label: 'Glossary',
        items: ['Revenue', 'ARR / MRR', 'Active customer', 'Churn'],
      },
      { icon: Database, label: 'Connectors', items: ['Snowflake', 'NetSuite', 'Stripe', 'Salesforce'] },
      { icon: Workflow, label: 'Actions', items: ['Export to deck', 'Open FP&A ticket'] },
    ],
    status: 'coming-soon',
  },
  {
    id: 'revops',
    persona: 'RevOps',
    title: 'RevOps Skill',
    description:
      'Pipeline insight, account risk, quota performance, and CRM hygiene — joined across CRM and product usage.',
    icon: Target,
    tone: DATA_TONE,
    bundles: [
      {
        icon: BookOpen,
        label: 'Glossary',
        items: ['Pipeline', 'ACV / TCV', 'Win rate', 'Quota attainment'],
      },
      { icon: Database, label: 'Connectors', items: ['Salesforce', 'HubSpot', 'Outreach', 'Gong'] },
      { icon: Workflow, label: 'Actions', items: ['Update opportunity', 'Create task'] },
    ],
    status: 'coming-soon',
  },
  {
    id: 'engineering',
    persona: 'Engineering',
    title: 'Engineering Skill',
    description:
      'Trace ownership, lineage, incidents, and service dependencies across repos, runbooks, dashboards, and tickets.',
    icon: Code2,
    tone: ACCENT_TONE,
    bundles: [
      {
        icon: BookOpen,
        label: 'Glossary',
        items: ['Incident', 'SLO', 'MTTR', 'Service ownership'],
      },
      { icon: Database, label: 'Connectors', items: ['GitHub', 'Jira', 'PagerDuty', 'Datadog'] },
      { icon: Workflow, label: 'Actions', items: ['Open Jira ticket', 'Page on-call'] },
    ],
    status: 'coming-soon',
  },
  {
    id: 'security',
    persona: 'Security & Compliance',
    title: 'Security Skill',
    description:
      'Audit-grade answers about access, PII, and compliance. SOC2 evidence collection becomes a query.',
    icon: ShieldCheck,
    tone: DESTRUCTIVE_TONE,
    bundles: [
      { icon: BookOpen, label: 'Glossary', items: ['PII scope', 'Audit window', 'Compliance state'] },
      { icon: Database, label: 'Connectors', items: ['SIEM', 'IAM', 'Ticketing'] },
      { icon: Workflow, label: 'Actions', items: ['Rotate credentials', 'File evidence'] },
    ],
    status: 'coming-soon',
  },
  {
    id: 'data',
    persona: 'Data leaders',
    title: 'Semantic Layer Skill',
    description:
      'Centralize metric definitions, expose them as the single source of truth, and let employees self-serve.',
    icon: Database,
    tone: GOV_TONE,
    bundles: [
      {
        icon: BookOpen,
        label: 'Glossary',
        items: ['Metric versioning', 'Lineage', 'Freshness'],
      },
      { icon: Database, label: 'Connectors', items: ['dbt', 'Cube', 'Snowflake', 'BigQuery'] },
      { icon: Workflow, label: 'Actions', items: ['Publish definition', 'Deprecate metric'] },
    ],
    status: 'coming-soon',
  },
  {
    id: 'starter',
    persona: 'Every employee',
    title: 'Starter Skills',
    description:
      'Curated baseline for any company. Common glossary terms, stock prompts, and the safe-default action set.',
    icon: Users,
    tone: MUTED_TONE,
    bundles: [
      {
        icon: BookOpen,
        label: 'Glossary',
        items: ['Customer', 'Order', 'Revenue (basic)'],
      },
      { icon: Database, label: 'Connectors', items: ['Postgres', 'Notion', 'Slack'] },
      { icon: Workflow, label: 'Actions', items: ['Export CSV', 'Notify owner'] },
    ],
    status: 'available',
  },
];

export function AgentsPage() {
  const { toast } = useToast();
  const [installed, setInstalled] = useState<Set<string>>(new Set());

  const handleInstall = (skill: Skill) => {
    if (skill.status === 'coming-soon') {
      toast({
        title: `${skill.title} ships in Q3`,
        description: 'Configurable Skills are part of the next milestone.',
      });
      return;
    }
    setInstalled((prev) => new Set([...prev, skill.id]));
    toast({
      title: `Installed ${skill.title}`,
      description: 'Glossary, connectors, and prompts are now active for your tenant.',
    });
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 md:px-8 py-8 md:py-12">
        <header className="mb-10">
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-2">
            Skills marketplace
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Pre-configured Skills for every team
          </h1>
          <p className="text-fg-secondary mt-2 text-base max-w-2xl">
            Each Skill bundles a glossary, connectors, prompts, and actions tuned for a persona.
            Install one to give your team an opinionated starting point — extend or replace as
            you go.
          </p>
        </header>

        <div className="grid sm:grid-cols-2 gap-4">
          {SKILLS.map((s) => (
            <SkillCard
              key={s.id}
              skill={s}
              installed={installed.has(s.id)}
              onInstall={() => handleInstall(s)}
            />
          ))}
        </div>

        <section className="mt-16 glass-strong rounded-xl p-6">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-accent/15 text-accent flex items-center justify-center flex-shrink-0">
              <Bot className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <h2 className="text-base font-semibold tracking-tight">Build your own Skill</h2>
              <p className="text-sm text-fg-secondary mt-1.5 leading-relaxed">
                A Skill is a YAML-defined bundle: glossary terms, business rules, connectors,
                seed prompts, and allowed actions. The Skill SDK opens to customers and partners
                in <span className="text-fg">Q4</span>, with a CLI to package, sign, and publish
                Skills.
              </p>
            </div>
            <span className="text-xs px-2 py-1 rounded bg-governance/15 text-governance border border-governance/25 flex-shrink-0">
              Q4
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}

function SkillCard({
  skill,
  installed,
  onInstall,
}: {
  skill: Skill;
  installed: boolean;
  onInstall: () => void;
}) {
  const Icon = skill.icon;
  return (
    <article className="glass rounded-xl p-5 hover:border-border-strong transition flex flex-col">
      <div className="flex items-start gap-3 mb-4">
        <div
          className={cn(
            'w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ring-1',
            skill.tone.bg,
            skill.tone.text,
            skill.tone.ring
          )}
        >
          <Icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-semibold text-base">{skill.title}</h3>
            {skill.status === 'coming-soon' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-governance/15 text-governance border border-governance/25 uppercase tracking-wider">
                Q3
              </span>
            )}
          </div>
          <div className="text-xs text-fg-muted">For {skill.persona}</div>
        </div>
      </div>

      <p className="text-sm text-fg-secondary leading-relaxed mb-4 flex-1">
        {skill.description}
      </p>

      <ul className="space-y-2 mb-5">
        {skill.bundles.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <b.icon className="w-3.5 h-3.5 text-fg-muted mt-0.5 flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <span className="text-fg-secondary font-medium">{b.label}: </span>
              <span className="text-fg-muted">{b.items.join(' · ')}</span>
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-center justify-between">
        {installed ? (
          <Button variant="outline" size="sm" disabled>
            <Sparkles className="w-3.5 h-3.5" />
            Installed
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={onInstall}
            variant={skill.status === 'available' ? 'default' : 'outline'}
          >
            {skill.status === 'available' ? 'Install' : 'Notify me'}
          </Button>
        )}
      </div>
    </article>
  );
}

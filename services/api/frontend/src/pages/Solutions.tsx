/**
 * /solutions/:persona — persona-targeted landing surfaces.
 *
 * Strategy (from "one product, layered surfaces" memo):
 *   ONE Compass product. Persona-targeted marketing surfaces here, plus
 *   in-product Skills (Q3) for runtime configuration.
 */
import { Link, Navigate, useParams } from 'react-router-dom';
import { ArrowRight, Sparkles, Wrench, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface SolutionsContent {
  persona: string;
  heroEyebrow: string;
  heroHeadline: string;
  heroSubhead: string;
  wins: { title: string; description: string }[];
  suggestedSkill: string;
  quote?: { text: string; attribution: string };
}

export const PERSONA_CONTENT: Record<string, SolutionsContent> = {
  finance: {
    persona: 'CFO & Finance',
    heroEyebrow: 'Compass for Finance',
    heroHeadline: 'Board-ready answers, with the SQL attached.',
    heroSubhead:
      'Revenue, margin, churn, forecast, and board metrics — answered against your warehouse and your finance glossary, with full audit trail.',
    wins: [
      {
        title: 'Stop the 9pm scramble',
        description:
          'Ad-hoc CFO questions answered in seconds, not days. Source SQL attached for sign-off.',
      },
      {
        title: 'One definition of revenue',
        description:
          'Glossary and recognition rules applied automatically. No more "which dashboard is right?"',
      },
      {
        title: 'Audit-ready by default',
        description:
          'Every number ships with the rows it came from, the user who asked, and the exact moment.',
      },
    ],
    suggestedSkill: 'Finance Skill',
  },
  revops: {
    persona: 'RevOps & Sales',
    heroEyebrow: 'Compass for RevOps',
    heroHeadline: 'Pipeline insight across CRM, warehouse, and product.',
    heroSubhead:
      'Quota performance, deal risk, account health, and CRM hygiene — answered across Salesforce, your warehouse, and product usage.',
    wins: [
      {
        title: 'Deals at risk, in plain English',
        description:
          'Compass joins CRM with product usage to surface accounts whose engagement is dropping.',
      },
      {
        title: 'Stop the spreadsheet pulls',
        description:
          'Quota attainment, ramp curves, and territory analysis — without a 3-hour SQL request.',
      },
      {
        title: 'Govern the action',
        description:
          'Ask, verify, and update opportunities back in Salesforce — with approval logs.',
      },
    ],
    suggestedSkill: 'RevOps Skill',
  },
  data: {
    persona: 'Data leaders',
    heroEyebrow: 'Compass for Data Teams',
    heroHeadline: 'Stop being the bottleneck for every metric question.',
    heroSubhead:
      'Centralize definitions, expose them as the single source of truth, and let employees self-serve — without losing governance.',
    wins: [
      {
        title: 'One glossary, applied everywhere',
        description:
          'Define a metric once. Compass injects the definition into every answer that uses it.',
      },
      {
        title: 'Reduce repeated requests',
        description:
          'Stock questions ("what was Q3 revenue?") are now self-serve. Your team works on actually-new analysis.',
      },
      {
        title: 'Lineage built in',
        description:
          'Every answer cites the dbt model, the freshness, and the upstream pipeline — out of the box.',
      },
    ],
    suggestedSkill: 'Semantic Layer Skill',
  },
  engineering: {
    persona: 'Engineering',
    heroEyebrow: 'Compass for Engineering',
    heroHeadline: 'Trace ownership, lineage, and incidents in plain English.',
    heroSubhead:
      'Connect repos, runbooks, dashboards, and tickets. Ask "who owns this service?" or "what changed before this incident?" — across all of it.',
    wins: [
      {
        title: 'Ownership, instantly',
        description:
          'Code, services, and dashboards mapped to teams. No more "ask someone in Slack."',
      },
      {
        title: 'Incident timelines',
        description:
          'Pull the last 24h of changes across deploys, configs, and on-call escalations into one answer.',
      },
      {
        title: 'Take action under audit',
        description: 'Open Jira tickets or page on-call from the answer — with full audit trail.',
      },
    ],
    suggestedSkill: 'Engineering Skill',
  },
  security: {
    persona: 'Security & Compliance',
    heroEyebrow: 'Compass for Security',
    heroHeadline: 'See who asked what, on which data, when — for every query.',
    heroSubhead:
      'Tenant scope, role-based access, PII redaction, and audit log built in. SOC2 evidence collection becomes a query, not a quarter.',
    wins: [
      {
        title: 'Audit-ready answers',
        description:
          'Every Compass query is logged with the user, role, sources accessed, and PII redaction applied.',
      },
      {
        title: 'Permission-aware retrieval',
        description:
          'Row-level security at the source enforced before the answer renders. Users see only what they should.',
      },
      {
        title: 'Compliance in real time',
        description:
          'Ask "who accessed customer PII last week?" and get a defensible answer in seconds.',
      },
    ],
    suggestedSkill: 'Security Skill',
  },
  everyone: {
    persona: 'Every employee',
    heroEyebrow: 'Compass for Every Team',
    heroHeadline: 'Ask company questions without knowing where the answer lives.',
    heroSubhead:
      'Compass routes through your warehouse, docs, code, and SaaS tools — and returns answers anyone can verify and act on.',
    wins: [
      {
        title: 'No tool-hopping',
        description:
          'Stop guessing whether the answer is in Confluence, Notion, the warehouse, or a 6-tab Looker dashboard.',
      },
      {
        title: 'Plain language in, plain English out',
        description: 'No SQL required. But the SQL is shown if you want to verify it.',
      },
      {
        title: 'Built for trust',
        description: 'Every answer ships with citations and the path it took. No black boxes.',
      },
    ],
    suggestedSkill: 'Starter Skills (curated)',
  },
};

const PERSONA_TONES: Record<string, { ring: string; bg: string; text: string }> = {
  finance: { ring: 'ring-knowledge/30', bg: 'bg-knowledge/15', text: 'text-knowledge' },
  revops: { ring: 'ring-data/30', bg: 'bg-data/15', text: 'text-data' },
  data: { ring: 'ring-accent/30', bg: 'bg-accent/15', text: 'text-accent' },
  engineering: { ring: 'ring-governance/30', bg: 'bg-governance/15', text: 'text-governance' },
  security: { ring: 'ring-destructive/30', bg: 'bg-destructive/15', text: 'text-destructive' },
  everyone: { ring: 'ring-fg-muted/30', bg: 'bg-fg-muted/15', text: 'text-fg-secondary' },
};

export function SolutionsPage() {
  const { persona = 'everyone' } = useParams<{ persona: string }>();
  const content = PERSONA_CONTENT[persona];

  if (!content) {
    return <Navigate to="/solutions/everyone" replace />;
  }

  const tone = PERSONA_TONES[persona] ?? PERSONA_TONES.everyone;
  const otherPersonas = Object.entries(PERSONA_CONTENT).filter(([k]) => k !== persona);

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 md:px-8 py-12 md:py-20">
        {/* Eyebrow */}
        <div className={cn('inline-flex items-center gap-2 text-xs uppercase tracking-widest font-medium px-2.5 py-1 rounded-full', tone.bg, tone.text)}>
          <Sparkles className="w-3 h-3" />
          {content.heroEyebrow}
        </div>

        {/* Headline */}
        <h1 className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.05] mt-5 max-w-3xl">
          {content.heroHeadline}
        </h1>
        <p className="text-fg-secondary text-lg leading-relaxed mt-5 max-w-2xl">
          {content.heroSubhead}
        </p>

        {/* CTAs */}
        <div className="mt-8 flex items-center gap-3 flex-wrap">
          <Button asChild>
            <Link to="/">
              Try Compass <ArrowRight className="w-4 h-4" />
            </Link>
          </Button>
          <Button asChild variant="outline">
            <a href="#book-demo">Book a demo</a>
          </Button>
        </div>

        {/* Wins grid */}
        <section className="mt-20">
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-6">
            What you get
          </div>
          <ul className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {content.wins.map((w, i) => (
              <li key={i} className="glass rounded-xl p-5 hover:border-border-strong transition">
                <div className={cn('w-8 h-8 rounded-md flex items-center justify-center mb-3 ring-1', tone.bg, tone.text, tone.ring)}>
                  <Sparkles className="w-4 h-4" />
                </div>
                <h3 className="font-semibold text-base mb-1.5">{w.title}</h3>
                <p className="text-sm text-fg-secondary leading-relaxed">{w.description}</p>
              </li>
            ))}
          </ul>
        </section>

        {/* Suggested Skill */}
        <section className="mt-12 glass-strong rounded-xl p-6 flex items-start gap-4">
          <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0', tone.bg, tone.text)}>
            <Wrench className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-widest text-fg-muted mb-1">
              Recommended Skill
            </div>
            <h3 className="font-semibold text-base">{content.suggestedSkill}</h3>
            <p className="text-sm text-fg-secondary mt-1.5 leading-relaxed">
              Pre-configured glossary, connectors, prompts, and actions for {content.persona}. Ships with Skills marketplace in Q3.
            </p>
          </div>
          <span className="text-xs px-2 py-1 rounded bg-governance/15 text-governance border border-governance/25 flex-shrink-0">
            Q3
          </span>
        </section>

        {/* Other personas */}
        <section className="mt-16">
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-4">
            Compass for other teams
          </div>
          <div className="flex flex-wrap gap-2">
            {otherPersonas.map(([key, p]) => {
              const t = PERSONA_TONES[key] ?? PERSONA_TONES.everyone;
              return (
                <Link
                  key={key}
                  to={`/solutions/${key}`}
                  className={cn('inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md glass border border-border/60 hover:border-border-strong transition text-sm', t.text)}
                >
                  {p.persona}
                  <ArrowRight className="w-3 h-3 opacity-60" />
                </Link>
              );
            })}
          </div>
        </section>

        <div className="h-12" />
      </div>
    </div>
  );
}

// Re-export the icon type for callers (legacy)
export type { LucideIcon };

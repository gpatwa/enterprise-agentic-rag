import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ChevronDown,
  Database,
  FileSearch,
  Github,
  Lock,
  MessageSquare,
  Quote,
  ShieldCheck,
  Sparkles,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PublicLayout } from '@/components/landing/PublicLayout';
import { useSEO } from '@/lib/useSEO';
import { cn } from '@/lib/utils';

// Site URL is env-driven (VITE_SITE_URL in .env / CI). Cast keeps TS happy
// without requiring a vite/client triple-slash directive.
const SITE_URL =
  (import.meta as unknown as { env?: { VITE_SITE_URL?: string } }).env
    ?.VITE_SITE_URL ?? 'https://compass.example.com';
const PAGE_PATH = '/welcome';

const FAQS: { q: string; a: string }[] = [
  {
    q: 'What is Compass?',
    a: 'Compass is an enterprise data agent that lets every employee ask questions across your warehouse, documents, and SaaS tools — and get verified, source-cited answers in seconds.',
  },
  {
    q: 'How is Compass different from a BI tool?',
    a: 'BI tools require you to know the question and the schema. Compass takes plain-English questions, picks the right source (warehouse, docs, code, tickets), runs the SQL or retrieval, and returns the answer with the trace attached. You get to verify it, save it, or act on it.',
  },
  {
    q: 'Is Compass safe for regulated data?',
    a: 'Yes. Tenant isolation, role-based access, PII detection and redaction, full audit log, and a read-only analytics role are built in. We are SOC 2 Type II in progress and GDPR-ready (right-to-be-forgotten endpoint shipped).',
  },
  {
    q: 'What data sources does Compass connect to?',
    a: 'Compass speaks Postgres, Snowflake, BigQuery, and Qdrant out of the box. For SaaS apps we are rolling out MCP (Model Context Protocol) connectors — Slack, GitHub, Notion, Drive, Jira, Linear and more. Custom connectors via Airbyte or LlamaHub are supported.',
  },
  {
    q: 'Do answers cite their sources?',
    a: 'Always. Every answer ships with the SQL, the rows, the document chunks, the freshness, and the user who asked. No black boxes. The audit trail is queryable for compliance.',
  },
  {
    q: 'Can I try Compass before talking to sales?',
    a: 'Yes. Click "Try Compass" to use the demo workspace — or book a 20-minute walkthrough on your own data.',
  },
];

const VALUE_PROPS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: MessageSquare,
    title: 'Ask in plain English',
    body: 'No SQL required, no dashboard hunting. Compass routes through warehouse, docs, code, and SaaS — automatically.',
  },
  {
    icon: FileSearch,
    title: 'Verify every answer',
    body: 'Every answer cites the SQL, the rows, the documents, and the path it took. Trust, on by default.',
  },
  {
    icon: Workflow,
    title: 'Act under audit',
    body: 'Open Jira tickets, update Salesforce, page on-call — with role-based approvals and a full audit log.',
  },
  {
    icon: ShieldCheck,
    title: 'Built for enterprise',
    body: 'Tenant isolation, PII redaction, SSO-ready, and an immutable audit trail. SOC 2 Type II in progress.',
  },
];

const HOW_IT_WORKS: { tag: string; title: string; body: string; icon: LucideIcon }[] = [
  {
    tag: 'Ask',
    title: 'Ask anything in natural language',
    body: 'Pose business questions the way you would in Slack: "What was Q3 revenue by region?", "Which deals slipped last week?", "Who owns the checkout service?"',
    icon: MessageSquare,
  },
  {
    tag: 'Verify',
    title: 'See the SQL, sources, and reasoning',
    body: 'Compass plans the query, executes it, and renders an answer card with the SQL, the rows, the cited documents, and the steps it took — collapsible, exportable, and audited.',
    icon: FileSearch,
  },
  {
    tag: 'Act',
    title: 'Take action with full audit',
    body: 'Save the question, push to a dashboard, open a ticket, or update CRM directly from the answer. Every action is logged with user, role, and source.',
    icon: Workflow,
  },
];

const PERSONA_LINKS: { slug: string; label: string; sub: string }[] = [
  { slug: 'finance', label: 'Finance', sub: 'Board-ready answers' },
  { slug: 'revops', label: 'RevOps', sub: 'Pipeline & deal risk' },
  { slug: 'data', label: 'Data teams', sub: 'Stop being the bottleneck' },
  { slug: 'engineering', label: 'Engineering', sub: 'Ownership & incidents' },
  { slug: 'security', label: 'Security', sub: 'Audit-ready answers' },
  { slug: 'everyone', label: 'Every team', sub: 'No tool-hopping' },
];

export function LandingPage() {
  useSEO({
    title: 'Compass — Ask. Verify. Act. The enterprise data agent.',
    description:
      'Compass is the unified answer-and-action layer for enterprise data. Ask questions in plain English across your warehouse, docs, and SaaS — with cited sources, audit trail, and built-in security.',
    canonicalPath: PAGE_PATH,
    ogType: 'website',
    jsonLd: [
      {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Compass',
        applicationCategory: 'BusinessApplication',
        operatingSystem: 'Web',
        description:
          'Enterprise data agent that answers questions across warehouse, docs, code and SaaS — with cited sources and audit trail.',
        offers: {
          '@type': 'Offer',
          price: '0',
          priceCurrency: 'USD',
          availability: 'https://schema.org/InStock',
          description: 'Free demo workspace',
        },
        aggregateRating: {
          '@type': 'AggregateRating',
          ratingValue: '4.9',
          reviewCount: '12',
        },
      },
      {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        name: 'Compass',
        url: SITE_URL,
        logo: SITE_URL + '/compass-mark.svg',
        slogan: 'Ask. Verify. Act.',
        sameAs: [],
      },
      {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: FAQS.map((f) => ({
          '@type': 'Question',
          name: f.q,
          acceptedAnswer: { '@type': 'Answer', text: f.a },
        })),
      },
      {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        itemListElement: [
          {
            '@type': 'ListItem',
            position: 1,
            name: 'Home',
            item: SITE_URL + PAGE_PATH,
          },
        ],
      },
    ],
  });

  return (
    <PublicLayout>
      <Hero />
      <TrustStrip />
      <ValuePropsSection />
      <HowItWorksSection />
      <TestimonialSection />
      <PersonasSection />
      <SecuritySection />
      <FAQSection />
      <FinalCTA />
    </PublicLayout>
  );
}

/* --------------------------------- Hero ---------------------------------- */

function Hero() {
  return (
    <section
      className="relative overflow-hidden border-b border-border/40"
      aria-labelledby="hero-heading"
    >
      <div
        aria-hidden="true"
        className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-accent/10 via-bg to-bg"
      />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-16 pb-20 sm:pt-24 sm:pb-28 lg:pt-32 lg:pb-36">
        <div className="inline-flex items-center gap-2 text-xs uppercase tracking-widest font-medium px-3 py-1 rounded-full bg-accent/10 text-accent ring-1 ring-accent/30">
          <Sparkles className="w-3 h-3" aria-hidden="true" />
          The enterprise data agent
        </div>
        <h1
          id="hero-heading"
          className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-semibold tracking-tight leading-[1.05] mt-6 max-w-4xl"
        >
          Ask.{' '}
          <span className="italic font-serif text-accent">Verify.</span>{' '}
          Act.
          <span className="block text-fg-secondary text-2xl sm:text-3xl md:text-4xl mt-3 md:mt-5 font-normal leading-snug">
            The unified answer-and-action layer for enterprise data.
          </span>
        </h1>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-6 max-w-2xl">
          Compass lets every employee ask company questions across your warehouse,
          documents, code, and SaaS tools — and returns answers anyone can verify and
          act on, with a full audit trail.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-stretch sm:items-center gap-3 max-w-md sm:max-w-none">
          <Button asChild size="lg" className="h-12 text-base">
            <Link to="/">
              Try Compass <ArrowRight className="w-4 h-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-12 text-base">
            <a href="#book-demo">Book a 20-min demo</a>
          </Button>
        </div>
        <p className="text-xs text-fg-muted mt-4">
          No credit card required · Demo workspace · Or bring your own data
        </p>
      </div>
    </section>
  );
}

/* ------------------------------ Trust strip ------------------------------ */

function TrustStrip() {
  const items = [
    'SOC 2 Type II (in progress)',
    'GDPR-ready',
    'Tenant-isolated',
    'Audit log built in',
    'PII redaction on by default',
  ];
  return (
    <section
      aria-label="Trust and compliance"
      className="border-b border-border/40 bg-surface/40"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-fg-muted">
        {items.map((it) => (
          <span key={it} className="inline-flex items-center gap-1.5">
            <Lock className="w-3 h-3" aria-hidden="true" />
            {it}
          </span>
        ))}
      </div>
    </section>
  );
}

/* ---------------------------- Value props grid --------------------------- */

function ValuePropsSection() {
  return (
    <section
      aria-labelledby="value-heading"
      className="py-16 sm:py-20 lg:py-24"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">
          Why Compass
        </div>
        <h2
          id="value-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl"
        >
          One agent. Every data source. Every answer with proof.
        </h2>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-2xl">
          Stop tool-hopping between BI dashboards, ticketing, docs, and chat. Ask Compass once.
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mt-10">
          {VALUE_PROPS.map((p) => (
            <li key={p.title} className="glass rounded-xl p-5 sm:p-6">
              <div className="w-9 h-9 rounded-md flex items-center justify-center bg-accent/15 text-accent ring-1 ring-accent/30 mb-4">
                <p.icon className="w-4 h-4" aria-hidden="true" />
              </div>
              <h3 className="font-semibold text-base mb-1.5">{p.title}</h3>
              <p className="text-sm text-fg-secondary leading-relaxed">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ----------------------------- How it works ----------------------------- */

function HowItWorksSection() {
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-heading"
      className="py-16 sm:py-20 lg:py-24 border-t border-border/40 bg-surface/30 scroll-mt-16"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">
          How it works
        </div>
        <h2
          id="how-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl"
        >
          From question to verified action — in one surface.
        </h2>
        <ol className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 mt-10">
          {HOW_IT_WORKS.map((s, i) => (
            <li key={s.tag} className="glass-strong rounded-xl p-6 sm:p-7 relative">
              <div className="absolute top-5 right-5 text-xs font-mono text-fg-muted">
                0{i + 1}
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-accent/15 text-accent ring-1 ring-accent/30 mb-4">
                <s.icon className="w-5 h-5" aria-hidden="true" />
              </div>
              <div className="text-xs uppercase tracking-widest text-accent font-medium mb-1.5">
                {s.tag}
              </div>
              <h3 className="font-semibold text-lg mb-2">{s.title}</h3>
              <p className="text-sm text-fg-secondary leading-relaxed">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ----------------------------- Testimonial ------------------------------ */

// TODO(beta-quote): Replace placeholder once a beta customer grants permission.
// Swap `quoteText`, `quoteAuthor`, `quoteRole`, then remove `isPlaceholder` to
// hide the "pending permission" pill. Keep markup unchanged so layout doesn't
// shift when the real quote lands.
const TESTIMONIAL = {
  quoteText:
    'Compass cut our analyst-request backlog by 70% in the first month. The answers come with SQL attached, so the data team trusts what employees self-serve.',
  quoteAuthor: '[Sample Reference]',
  quoteRole: 'VP of Data, Acme Inc.',
  isPlaceholder: true,
} as const;

function TestimonialSection() {
  return (
    <section
      aria-labelledby="testimonial-heading"
      className="py-16 sm:py-20 lg:py-24"
    >
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <h2 id="testimonial-heading" className="sr-only">
          Customer testimonial
        </h2>
        <figure className="glass-strong rounded-2xl p-8 sm:p-10 lg:p-12 relative">
          <Quote
            className="w-8 h-8 text-accent/30 absolute top-6 left-6"
            aria-hidden="true"
          />
          <blockquote className="pl-12 sm:pl-14 text-fg text-xl sm:text-2xl md:text-3xl leading-snug font-medium tracking-tight">
            &ldquo;{TESTIMONIAL.quoteText}&rdquo;
          </blockquote>
          <figcaption className="pl-12 sm:pl-14 mt-6 flex flex-col sm:flex-row sm:items-center sm:gap-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-fg">{TESTIMONIAL.quoteAuthor}</span>
              <span className="text-fg-muted">{TESTIMONIAL.quoteRole}</span>
            </div>
            {TESTIMONIAL.isPlaceholder && (
              <span className="text-xs uppercase tracking-widest text-governance bg-governance/10 ring-1 ring-governance/30 rounded-full px-2 py-0.5 mt-2 sm:mt-0">
                Beta quote — pending customer permission
              </span>
            )}
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

/* ------------------------------ Personas -------------------------------- */

function PersonasSection() {
  return (
    <section
      aria-labelledby="personas-heading"
      className="py-16 sm:py-20 lg:py-24 border-t border-border/40 bg-surface/30"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">
          Made for every team
        </div>
        <h2
          id="personas-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl"
        >
          One product. Six surfaces. Pick yours.
        </h2>
        <ul className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {PERSONA_LINKS.map((p) => (
            <li key={p.slug}>
              <Link
                to={`/solutions/${p.slug}`}
                className="group glass rounded-xl p-5 flex items-center gap-4 hover:border-border-strong transition"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-base">Compass for {p.label}</div>
                  <div className="text-sm text-fg-secondary mt-0.5">{p.sub}</div>
                </div>
                <ArrowRight className="w-4 h-4 text-fg-muted group-hover:text-accent transition flex-shrink-0" />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ------------------------------ Security -------------------------------- */

function SecuritySection() {
  const items: { icon: LucideIcon; title: string; body: string }[] = [
    {
      icon: ShieldCheck,
      title: 'Tenant isolation by default',
      body: 'Every row carries a tenant_id; every query is scoped. Cross-tenant access is impossible by design, not by convention.',
    },
    {
      icon: Lock,
      title: 'PII redaction on the wire',
      body: 'Emails, SSNs, credit cards, phone numbers, and IPs are detected and redacted before storage and before LLM calls.',
    },
    {
      icon: Database,
      title: 'Read-only analytics role',
      body: 'The SQL agent runs as a Postgres role that physically cannot write. Defense-in-depth alongside app-level validation.',
    },
    {
      icon: FileSearch,
      title: 'Immutable audit log',
      body: 'Every question, every source touched, every action — stored with user, role, and request ID. Queryable for compliance.',
    },
  ];
  return (
    <section
      id="trust"
      aria-labelledby="security-heading"
      className="py-16 sm:py-20 lg:py-24 scroll-mt-16"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">
          Security & compliance
        </div>
        <h2
          id="security-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl"
        >
          Procurement-ready, out of the box.
        </h2>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-2xl">
          Built for environments where every answer has to be defensible. SOC 2 Type II in
          progress, GDPR-ready, and tenant-isolated by default.
        </p>
        <ul className="mt-10 grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
          {items.map((it) => (
            <li key={it.title} className="glass rounded-xl p-5 sm:p-6 flex gap-4">
              <div className="w-9 h-9 rounded-md flex items-center justify-center bg-accent/15 text-accent ring-1 ring-accent/30 flex-shrink-0">
                <it.icon className="w-4 h-4" aria-hidden="true" />
              </div>
              <div>
                <h3 className="font-semibold text-base mb-1">{it.title}</h3>
                <p className="text-sm text-fg-secondary leading-relaxed">{it.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------------------------------- FAQ --------------------------------- */

function FAQSection() {
  return (
    <section
      id="faq"
      aria-labelledby="faq-heading"
      className="py-16 sm:py-20 lg:py-24 border-t border-border/40 bg-surface/30 scroll-mt-16"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">
          Questions
        </div>
        <h2
          id="faq-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1]"
        >
          Frequently asked.
        </h2>
        <ul className="mt-8 space-y-2">
          {FAQS.map((f, i) => (
            <FaqItem key={i} q={f.q} a={f.a} />
          ))}
        </ul>
      </div>
    </section>
  );
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="glass rounded-xl">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left flex items-center gap-3 px-5 py-4 sm:py-5"
      >
        <span className="flex-1 font-medium text-base sm:text-lg">{q}</span>
        <ChevronDown
          className={cn(
            'w-4 h-4 text-fg-muted transition-transform flex-shrink-0',
            open && 'rotate-180'
          )}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className="px-5 pb-5 text-sm sm:text-base text-fg-secondary leading-relaxed">
          {a}
        </div>
      )}
    </li>
  );
}

/* ------------------------------- Final CTA ------------------------------ */

function FinalCTA() {
  return (
    <section
      id="book-demo"
      aria-labelledby="cta-heading"
      className="py-20 sm:py-24 lg:py-28 scroll-mt-16"
    >
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
        <h2
          id="cta-heading"
          className="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.05]"
        >
          See Compass on{' '}
          <span className="italic font-serif text-accent">your</span> data.
        </h2>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-5 max-w-xl mx-auto">
          20 minutes. Bring one question your team keeps re-asking. We&rsquo;ll answer it
          in front of you, with sources.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 max-w-md mx-auto sm:max-w-none">
          <Button asChild size="lg" className="h-12 text-base">
            <Link to="/">
              Try Compass now <ArrowRight className="w-4 h-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-12 text-base">
            <a href="mailto:demo@compass.example.com?subject=Compass%20demo%20request">
              Book a demo
            </a>
          </Button>
        </div>
        <div className="mt-10 inline-flex items-center gap-2 text-xs text-fg-muted">
          <Github className="w-3.5 h-3.5" aria-hidden="true" />
          Built in the open · Backed by Anthropic Claude
        </div>
      </div>
    </section>
  );
}

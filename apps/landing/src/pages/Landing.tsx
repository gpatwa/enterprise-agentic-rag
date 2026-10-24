import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  ChevronDown,
  Database,
  FileSearch,
  Lock,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PublicLayout } from '@/components/landing/PublicLayout';
import { useSEO } from '@/lib/useSEO';
import { cn } from '@/lib/utils';
import { APP_URL, PILOT_MAILTO, SITE_URL } from '@/config';

const PAGE_PATH = '/welcome';

const FAQS: { q: string; a: string }[] = [
  {
    q: 'What is Compass?',
    a: 'Compass answers business questions from your governed data. Ask in plain English; Compass resolves the question to certified metric definitions, compiles the SQL deterministically, enforces policy, and returns the answer with the SQL and evidence attached.',
  },
  {
    q: 'How is Compass different from a chat-with-your-data tool?',
    a: 'Those tools let a model write SQL and hope. Compass never runs model-written SQL. The model only extracts intent; a deterministic compiler builds the query from certified definitions. If the question is ambiguous, unsupported, or not permitted, Compass asks or refuses instead of guessing.',
  },
  {
    q: 'What stops a wrong or unsafe answer?',
    a: 'Certified semantic definitions, an intent check against your own terms, policy and purpose checks, small-group (cohort) suppression, a cost estimate before execution, and human review for costly or sensitive queries. Reviewers are people; automated assistants can only read and draft notes.',
  },
  {
    q: 'Can I see how an answer was produced?',
    a: 'Yes. Every answer carries the compiled SQL, parameters, the definitions used, and a tamper-evident evidence trail, and runs can be replayed. Result rows are not stored in the audit record.',
  },
  {
    q: 'What data does it run on?',
    a: 'PostgreSQL and DuckDB today, against semantic definitions kept in Git. Other warehouses are on the roadmap, not shipped. Compass Resolution Intelligence separately searches resolved support tickets with tenant-scoped retrieval.',
  },
  {
    q: 'Is Compass certified for compliance frameworks?',
    a: 'Not yet. Compass is in pilot and has not completed a SOC 2 audit or a formal independent security review. Ask us for the current security and evidence summary.',
  },
  {
    q: 'Can I try Compass?',
    a: 'Yes. Open the workspace to try the demo, or contact us to run a pilot on one of your datasets.',
  },
];

const VALUE_PROPS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: MessageSquare,
    title: 'Ask in plain English',
    body: 'No SQL, no dashboard hunting. Questions are mapped to the metrics and dimensions your data team has certified.',
  },
  {
    icon: FileSearch,
    title: 'Every answer shows its work',
    body: 'The compiled SQL, parameters, definitions used, and an evidence trail ship with the answer, and runs can be replayed.',
  },
  {
    icon: ShieldCheck,
    title: 'Refuses instead of guessing',
    body: 'Ambiguous, unsupported, or unauthorized questions get a clear refusal or a clarifying question, never a plausible-looking wrong number.',
  },
  {
    icon: Workflow,
    title: 'People decide the risky ones',
    body: 'Costly or sensitive queries wait for a human reviewer. Requesters cannot approve their own runs, and AI assistants can only read.',
  },
  {
    icon: Lock,
    title: 'Scoped to the asker',
    body: 'Answers are tenant-isolated and purpose-bound, small cohorts are suppressed, and queries run through a read-only database role.',
  },
];

const HOW_IT_WORKS: { tag: string; title: string; body: string; icon: LucideIcon }[] = [
  {
    tag: 'Ask',
    title: 'Ask a business question',
    body: 'Pose it the way you would in Slack: "What was Q3 revenue by region?" Compass resolves your terms against certified definitions.',
    icon: MessageSquare,
  },
  {
    tag: 'Verify',
    title: 'See the SQL and the evidence',
    body: 'The query is compiled deterministically from certified metrics, checked against policy and budget, and returned with the SQL, parameters, and evidence trail.',
    icon: FileSearch,
  },
  {
    tag: 'Review',
    title: 'Humans approve what matters',
    body: 'Expensive or sensitive runs pause for a named reviewer. Every decision is recorded alongside the run, and nothing executes before approval.',
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
    title: 'Compass — Governed answers from your data, with proof',
    description:
      'Ask business questions in plain English and get answers built from certified definitions — with the SQL, evidence trail, policy checks, and human review for risky queries. No model-written SQL.',
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
          'Governed analytics: plain-English questions answered from certified metric definitions, with the SQL, evidence trail, and human review attached.',
        offers: {
          '@type': 'Offer',
          price: '0',
          priceCurrency: 'USD',
          availability: 'https://schema.org/InStock',
          description: 'Demo workspace',
        },
      },
      {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        name: 'Compass',
        url: SITE_URL,
        logo: SITE_URL + '/compass-mark.svg',
        slogan: 'Governed answers, with proof.',
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
      <ResolutionMemorySection />
      <ValuePropsSection />
      <AnalyticsSection />
      <HowItWorksSection />
      <PersonasSection />
      <SecuritySection />
      <FAQSection />
      <FinalCTA />
    </PublicLayout>
  );
}

function ResolutionMemorySection() {
  return (
    <section
      id="resolution-memory"
      aria-labelledby="resolution-memory-heading"
      className="py-16 sm:py-20 lg:py-24 border-b border-border/40 bg-surface/20 scroll-mt-16"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 grid grid-cols-1 lg:grid-cols-[0.9fr_1.1fr] gap-10 lg:gap-16 items-start">
        <div>
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">Compass Resolution Intelligence</div>
          <h2 id="resolution-memory-heading" className="text-3xl sm:text-4xl font-semibold tracking-tight leading-[1.1] max-w-xl">
            Make every solved ticket searchable before you automate.
          </h2>
          <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-xl">
            OpenSearch combines exact terms, BM25, vector similarity, and deterministic hybrid ranking so agents can find the right prior resolution quickly.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            ['Ingest', 'Tickets, comments, and knowledge articles become versioned resolution memory.'],
            ['Retrieve', 'Tenant and ACL filters apply before results reach the agent.'],
            ['Trust', 'Citations, ranking explanations, reviewed actions, and audit evidence stay attached.'],
          ].map(([title, body]) => (
            <div key={title} className="border border-border/60 bg-background/70 p-5 rounded-xl">
              <div className="font-semibold">{title}</div>
              <p className="text-sm text-fg-secondary leading-relaxed mt-2">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------- Analytics product --------------------------- */

function AnalyticsSection() {
  return (
    <section
      id="analytics"
      aria-labelledby="analytics-heading"
      className="py-16 sm:py-20 lg:py-24 border-y border-border/40 bg-surface/30 scroll-mt-16"
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-10 lg:gap-16 items-center">
        <div>
          <div className="text-xs uppercase tracking-widest text-fg-muted mb-3">Compass Analytics</div>
          <h2 id="analytics-heading" className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl">
            Turn messy business questions into governed answers.
          </h2>
          <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-2xl">
            Certified metrics, typed intent, deterministic SQL, policy and cost checks, and an evidence trail your data team can inspect and replay.
          </p>
          <div className="mt-7 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <Button asChild size="lg" className="h-12 text-base">
              <a href={APP_URL}>
                Open the governed workspace <ArrowRight className="w-4 h-4" />
              </a>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-12 text-base">
              <a href="#book-demo">Talk to us about a pilot</a>
            </Button>
          </div>
        </div>
        <div className="glass-strong rounded-2xl p-6 sm:p-8" aria-label="Governed analytics workflow">
          <div className="flex items-center gap-3 pb-5 border-b border-border/60">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-accent/15 text-accent ring-1 ring-accent/30">
              <BarChart3 className="w-5 h-5" aria-hidden="true" />
            </div>
            <div><div className="font-semibold">Certified analytics path</div><div className="text-sm text-fg-secondary">Every step leaves evidence</div></div>
          </div>
          <ol className="mt-5 space-y-4">
            {['Select trusted context', 'Compile typed intent', 'Enforce policy and budget', 'Return answer with proof'].map((step, index) => (
              <li key={step} className="flex items-center gap-3 text-sm">
                <span className="w-6 h-6 rounded-full bg-accent/15 text-accent text-xs font-semibold flex items-center justify-center">{index + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
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
          Governed analytics
        </div>
        <h1
          id="hero-heading"
          className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-semibold tracking-tight leading-[1.05] mt-6 max-w-4xl"
        >
          Answers you can{' '}
          <span className="italic font-serif text-accent">defend.</span>
          <span className="block text-fg-secondary text-2xl sm:text-3xl md:text-4xl mt-3 md:mt-5 font-normal leading-snug">
            Ask in plain English. Get the number, the SQL, and the proof.
          </span>
        </h1>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-6 max-w-2xl">
          Compass answers business questions from your certified metric definitions.
          The model never writes SQL: a deterministic compiler does, under policy and
          budget checks, with human review for risky queries. If it cannot answer
          safely, it says so.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-stretch sm:items-center gap-3 max-w-md sm:max-w-none">
          <Button asChild size="lg" className="h-12 text-base">
            <a href={APP_URL}>
              Try Compass <ArrowRight className="w-4 h-4" />
            </a>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-12 text-base">
            <a href="#book-demo">Talk to us about a pilot</a>
          </Button>
        </div>
        <p className="text-xs text-fg-muted mt-4">
          Pilot-stage product · Demo workspace · Pilot on your own dataset
        </p>
      </div>
    </section>
  );
}

/* ------------------------------ Trust strip ------------------------------ */

function TrustStrip() {
  const items = [
    'No model-written SQL',
    'Certified definitions only',
    'Tenant-isolated',
    'Tamper-evident evidence trail',
    'Human review for risky queries',
  ];
  return (
    <section
      aria-label="Trust and governance"
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
          A fast answer is easy. A defensible one is the product.
        </h2>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-2xl">
          Self-service analytics fails when nobody trusts the number. Compass makes trust the default, so your data team stops being the bottleneck without losing control.
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 mt-10">
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
          From question to defensible answer.
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
          Built for the teams who get asked.
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
      title: 'Tenant isolation',
      body: 'Every run, plan, and result is scoped to the requesting tenant and purpose. Isolation is covered by adversarial tests, not just convention.',
    },
    {
      icon: Database,
      title: 'Read-only execution',
      body: 'Queries run through a database role that cannot write, in addition to application-level validation of every compiled plan.',
    },
    {
      icon: FileSearch,
      title: 'Tamper-evident evidence',
      body: 'Each step is appended to a hash-chained evidence trail. Result rows are not stored in the audit record.',
    },
    {
      icon: Lock,
      title: 'Separation of duties',
      body: 'Only people can approve reviews, and never their own request. Automated assistants are limited to read-only briefs and advisory notes.',
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
          Security & governance
        </div>
        <h2
          id="security-heading"
          className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] max-w-3xl"
        >
          Controls you can inspect, not just trust.
        </h2>
        <p className="text-fg-secondary text-base sm:text-lg leading-relaxed mt-4 max-w-2xl">
          Built for environments where every answer has to be defensible. Compass is in
          pilot: we have not completed a SOC 2 audit or a formal third-party security
          review, and we will share the evidence we do have.
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
          Bring one question your team keeps re-asking and the dataset behind it. We&rsquo;ll
          scope a pilot and show you the answer, the SQL, and the evidence.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 max-w-md mx-auto sm:max-w-none">
          <Button asChild size="lg" className="h-12 text-base">
            <a href={APP_URL}>
              Open the workspace <ArrowRight className="w-4 h-4" />
            </a>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-12 text-base">
            <a href={PILOT_MAILTO}>
              Request a pilot
            </a>
          </Button>
        </div>
        <div className="mt-10 inline-flex items-center gap-2 text-xs text-fg-muted">
          <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
          Pilot-stage · Local and Azure deployments
        </div>
      </div>
    </section>
  );
}

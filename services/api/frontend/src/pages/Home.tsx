import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { AskBox } from '@/components/home/AskBox';
import { QuickStart } from '@/components/home/QuickStart';
import { Pinned } from '@/components/home/Pinned';
import { RecentThreads } from '@/components/home/RecentThreads';
import { RightRail } from '@/components/layout/RightRail';
import type { LandingResponse } from '@/types';

/** Fallback data for offline / pre-backend dev. */
const MOCK: LandingResponse = {
  user: { id: 'u_1', name: 'Gopal', role: 'admin' },
  tenant: { id: 'acme-prod', name: 'Acme Corp', residency: 'us-east-1' },
  pinned_questions: [
    {
      id: 'q1',
      title: 'Revenue by month last year',
      last_run_at: new Date(Date.now() - 7_200_000).toISOString(),
      last_result_preview: 'Refreshed 2h ago · 12 rows · R$ 14.2M total',
    },
    {
      id: 'q2',
      title: 'Top 10 sellers Q1',
      last_run_at: new Date(Date.now() - 86_400_000).toISOString(),
      last_result_preview: 'Refreshed 1d ago · 10 rows · R$ 4.1M',
    },
  ],
  recent_threads: [
    {
      id: 't1',
      title: 'Investigating churn drop in São Paulo region',
      updated_at: new Date(Date.now() - 720_000).toISOString(),
      message_count: 6,
      active: true,
    },
    {
      id: 't2',
      title: 'Q1 board prep — revenue + delivery KPIs',
      updated_at: new Date(Date.now() - 3_600_000).toISOString(),
      message_count: 11,
    },
    {
      id: 't3',
      title: 'CFO question on payment methods',
      updated_at: new Date(Date.now() - 86_400_000).toISOString(),
      message_count: 3,
    },
  ],
  quick_start_categories: [
    {
      id: 'revenue',
      icon: 'trending-up',
      title: 'Revenue trends',
      description: 'Monthly · YoY · by category',
      questions: [{ id: 'r1', text: 'What was revenue by month?' }],
    },
    {
      id: 'products',
      icon: 'shopping-bag',
      title: 'Top products',
      description: 'Categories · sellers · items',
      questions: [{ id: 'p1', text: 'Top 10 categories by revenue' }],
    },
    {
      id: 'reviews',
      icon: 'star',
      title: 'Reviews & ratings',
      description: 'Scores · sentiment · regions',
      questions: [{ id: 'rv1', text: 'Average review by state' }],
    },
    {
      id: 'delivery',
      icon: 'truck',
      title: 'Delivery insights',
      description: 'Times · lateness · regions',
      questions: [{ id: 'd1', text: 'Avg delivery time by month' }],
    },
  ],
  sources: [
    { type: 'postgres', name: 'PostgreSQL', row_count: 1_550_851, status: 'fresh' },
    { type: 'qdrant', name: 'Qdrant Vector', chunk_count: 302, status: 'fresh' },
    { type: 'neo4j', name: 'Neo4j Graph', node_count: 2412, status: 'stale' },
    { type: 'slack', name: 'Slack export', status: 'not_connected' },
  ],
  knowledge_counts: { glossary: 12, business_rules: 8, code_context: 5 },
  governance: { pii_redaction: true, audit_logging: true },
};

export function HomePage() {
  const [data, setData] = useState<LandingResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getLanding()
      .then((d: LandingResponse) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        // Fall back to mock when backend isn't reachable yet (W1 dev).
        if (!cancelled) setData(MOCK);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-fg-muted">
        <div className="animate-pulse">Loading…</div>
      </div>
    );
  }

  return (
    <>
      {/* Center column */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-3xl mx-auto px-8 py-12">
          {/* Hero */}
          <div className="mb-8">
            <div className="text-sm text-fg-muted mb-2">Welcome back, {data.user.name}.</div>
            <h1 className="text-2xl font-semibold tracking-tight leading-tight text-fg">
              Ask. <span className="font-serif italic font-normal accent-grad-text">Verify.</span> Act.
            </h1>
            <p className="text-fg-secondary mt-3 text-base">
              Governed answers across data, documents, and code — with citations, SQL, lineage, and
              audit on every response.
            </p>
          </div>

          {/* Ask box */}
          <AskBox onSubmit={(q, scope) => console.log('ask', q, scope)} />

          {/* Quick-start */}
          <div className="mt-12">
            <QuickStart
              categories={data.quick_start_categories}
              onPickQuestion={(text) => console.log('pick', text)}
            />
          </div>

          <Pinned questions={data.pinned_questions} />
          <RecentThreads threads={data.recent_threads} />

          <div className="h-12" />
        </div>
      </div>

      {/* Right rail */}
      <RightRail
        sources={data.sources}
        knowledge={data.knowledge_counts}
        governance={data.governance}
        tenant={data.tenant}
        user={data.user}
      />
    </>
  );
}

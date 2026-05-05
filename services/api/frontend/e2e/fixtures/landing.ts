/** Mock /api/v1/home/landing payload used by E2E tests. */
export const LANDING_FIXTURE = {
  user: { id: 'gopal', name: 'Gopal', role: 'admin' },
  tenant: { id: 'acme-prod', name: 'Acme Corp', residency: 'us-east-1' },
  pinned_questions: [
    {
      id: 'pq_1',
      title: 'Revenue by month last year',
      last_run_at: new Date(Date.now() - 7_200_000).toISOString(),
      last_result_preview: 'Refreshed 2h ago · 12 rows · R$ 14.2M total',
    },
  ],
  recent_threads: [
    {
      id: 't_42',
      title: 'Investigating churn drop in São Paulo',
      updated_at: new Date(Date.now() - 720_000).toISOString(),
      message_count: 6,
      active: true,
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
      description: 'Categories · sellers',
      questions: [{ id: 'p1', text: 'Top 10 categories by revenue' }],
    },
    {
      id: 'reviews',
      icon: 'star',
      title: 'Reviews',
      description: 'Scores · sentiment',
      questions: [{ id: 'rv1', text: 'Average review by state' }],
    },
    {
      id: 'delivery',
      icon: 'truck',
      title: 'Delivery',
      description: 'Times · lateness',
      questions: [{ id: 'd1', text: 'Avg delivery time' }],
    },
  ],
  sources: [
    { type: 'postgres', name: 'PostgreSQL', row_count: 1_550_851, status: 'fresh' },
    { type: 'qdrant', name: 'Qdrant Vector', chunk_count: 302, status: 'fresh' },
    { type: 'neo4j', name: 'Neo4j Graph', node_count: 2412, status: 'stale' },
  ],
  knowledge_counts: { glossary: 12, business_rules: 8, code_context: 5 },
  governance: { pii_redaction: true, audit_logging: true },
};

export const SOURCES_HEALTH_FIXTURE = {
  sources: LANDING_FIXTURE.sources,
  probed_at: new Date().toISOString(),
};

/** A canonical NDJSON chat stream for the happy path. */
export function makeChatStream(sessionId: string, question: string): string {
  const event = (e: object) => JSON.stringify(e) + '\n';
  return [
    event({ type: 'status', node: 'planner', session_id: sessionId }),
    event({ type: 'status', node: 'data_analytics', session_id: sessionId }),
    event({
      type: 'sql_query',
      sql: 'SELECT month, SUM(payment_value) AS revenue FROM olist_orders o JOIN olist_order_payments op USING (order_id) GROUP BY 1 ORDER BY 1;',
      time_ms: 240,
      session_id: sessionId,
    }),
    event({
      type: 'data_result',
      columns: ['month', 'revenue'],
      rows: [
        { month: '2024-01', revenue: 138488 },
        { month: '2024-02', revenue: 222151 },
        { month: '2024-03', revenue: 305_412 },
      ],
      row_count: 3,
      session_id: sessionId,
    }),
    event({ type: 'status', node: 'responder', session_id: sessionId }),
    event({
      type: 'answer',
      content: `Revenue grew steadily across the first quarter, peaking at R$ 305,412 in March. ${question} [Source: olist_orders]`,
      session_id: sessionId,
    }),
    event({ type: 'status', node: 'evaluator', session_id: sessionId }),
    event({
      type: 'evaluation',
      score: 4,
      reasoning: 'Clear, evidenced answer.',
      session_id: sessionId,
    }),
    event({
      type: 'follow_ups',
      suggestions: ['Why did March spike?', 'Compare to last year?', 'Break down by category?'],
      session_id: sessionId,
    }),
    event({ type: 'status', node: '__end__', session_id: sessionId }),
  ].join('');
}

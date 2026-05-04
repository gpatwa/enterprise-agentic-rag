/**
 * /solutions/:persona — W2 placeholder.
 *
 * Strategy (locked in the "one product, layered surfaces" memo):
 *   ONE Compass product. Persona-targeted marketing surfaces here, plus
 *   in-product Skills (Q3) for runtime configuration.
 *
 * Personas served:
 *   - finance       (CFO buyer)
 *   - revops        (Sales/RevOps buyer)
 *   - data          (Data leader buyer)
 *   - engineering   (Engineering buyer)
 *   - security      (Security/Compliance buyer)
 *   - everyone      (generalist)
 *
 * Each variant shares the same layout but swaps:
 *   - Hero copy (verb specific to the persona's outcome)
 *   - 3 wins (concrete questions Compass answers for them)
 *   - Mock answer screenshot (in-product preview tailored)
 *   - Suggested Skills (Finance Skill, RevOps Skill, etc.)
 *   - Quote from a beta user in that role (PENDING — needs permission)
 *   - CTA (Book a demo)
 */

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
        description: 'Ad-hoc CFO questions answered in seconds, not days. Source SQL attached for sign-off.',
      },
      {
        title: 'One definition of revenue',
        description: 'Glossary and recognition rules applied automatically. No more "which dashboard is right?"',
      },
      {
        title: 'Audit-ready by default',
        description: 'Every number ships with the rows it came from, the user who asked, and the exact moment.',
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
        description: 'Compass joins CRM with product usage to surface accounts whose engagement is dropping.',
      },
      {
        title: 'Stop the spreadsheet pulls',
        description: 'Quota attainment, ramp curves, and territory analysis — without a 3-hour SQL request.',
      },
      {
        title: 'Govern the action',
        description: 'Ask, verify, and update opportunities back in Salesforce — with approval logs.',
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
        description: 'Define a metric once. Compass injects the definition into every answer that uses it.',
      },
      {
        title: 'Reduce repeated requests',
        description: 'Stock questions ("what was Q3 revenue?") are now self-serve. Your team works on actually-new analysis.',
      },
      {
        title: 'Lineage built in',
        description: 'Every answer cites the dbt model, the freshness, and the upstream pipeline — out of the box.',
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
        description: 'Code, services, and dashboards mapped to teams. No more "ask someone in Slack."',
      },
      {
        title: 'Incident timelines',
        description: 'Pull the last 24h of changes across deploys, configs, and on-call escalations into one answer.',
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
        description: 'Every Compass query is logged with the user, role, sources accessed, and PII redaction applied.',
      },
      {
        title: 'Permission-aware retrieval',
        description: 'Row-level security at the source enforced before the answer renders. Users see only what they should.',
      },
      {
        title: 'Compliance in real time',
        description: 'Ask "who accessed customer PII last week?" and get a defensible answer in seconds.',
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
        description: 'Stop guessing whether the answer is in Confluence, Notion, the warehouse, or a 6-tab Looker dashboard.',
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

export function SolutionsPage(_props: { persona: keyof typeof PERSONA_CONTENT }) {
  // Implementation intentionally omitted — W2 deliverable.
  // The shape of `PERSONA_CONTENT` above is the contract the marketing team
  // will fill in, and the layout will mirror the GTM landing page hero +
  // wins grid + suggested-Skill card.
  return null;
}

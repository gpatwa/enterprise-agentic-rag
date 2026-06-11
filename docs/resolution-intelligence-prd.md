# Customer Support Resolution Intelligence PRD

## Decision

Compass should enter the support-AI market as a neutral Resolution Intelligence layer, not as a helpdesk replacement or generic chatbot. The v1 wedge is to reduce repeat support tickets for B2B SaaS teams by turning historical tickets, comments, help-center articles, and escalation context into evidence-backed resolution playbooks and knowledge-gap recommendations.

## Target Customer

Primary ICP: mid-market B2B SaaS companies with 5-100 support agents, 3k-50k tickets/month, and a mixed support stack around Zendesk or Intercom plus Slack, Jira/Linear, CRM, and a help center.

Initial buyer: Head of Support, Support Operations, or CX Operations.

Initial users:
- Support operations manager: wants to find repeat ticket drivers and reduce support load.
- Tier-1/Tier-2 support agent: wants a trusted resolution path with citations.
- Product operations or PM: wants repeat issue evidence tied to product fixes.
- CX leader: wants measurable deflection, CSAT, and cost impact.

## Problem

Support teams already have answers buried across tickets, comments, KB articles, Slack escalations, Jira bugs, and CRM context. Existing helpdesk AI can draft replies, but buyers still struggle with:
- repeat ticket volume that keeps coming back;
- weak visibility into the root causes behind ticket spikes;
- stale or missing knowledge-base articles;
- unsafe automation without evidence or human review;
- vendor lock-in when support data spans several SaaS tools;
- unclear ROI from AI initiatives.

## Product Thesis

The durable value is not answering one ticket faster. The durable value is creating a closed loop:

repeat issue cluster -> evidence-backed resolution playbook -> KB/macro/product recommendation -> measured ticket reduction.

Compass wins if it becomes the support team's system of intelligence across Zendesk, Intercom, Slack, Jira/Linear, CRM, and knowledge sources.

## V1 Scope

The first local workflow must support:
- seed or sync support data;
- identify repeat issue clusters;
- open a repeat cluster;
- generate an evidence-backed resolution playbook;
- show cited prior tickets/articles/comments;
- recommend the KB or macro gap to close;
- estimate deflection opportunity from the analyzed ticket sample;
- keep human review in the loop before customer-facing automation.

## Non-Goals For V1

V1 will not:
- replace Zendesk or Intercom;
- send autonomous replies to customers;
- execute write actions in third-party tools;
- claim zero hallucination without deterministic citation verification;
- optimize for 10M-document scale before proving repeat-ticket reduction;
- build every SaaS connector before Zendesk/Intercom validation.

## Success Metrics

Product metrics:
- repeat clusters discovered per tenant;
- percentage of repeat clusters with solved evidence;
- playbooks generated per week;
- KB gaps identified and accepted;
- estimated deflectable tickets per cluster;
- actual repeat-ticket reduction after playbook/KB deployment;
- agent acceptance rate for recommended resolutions.

Quality metrics:
- citation coverage rate;
- unsupported-claim rate;
- precision@k for similar cases;
- recall@k for known repeat clusters;
- false automation risk rate;
- human-review escalation rate.

Operational metrics:
- sync success rate;
- indexing duration;
- retrieval latency;
- playbook generation latency;
- connector error rate;
- tenant data isolation test pass rate.

## Principal Product Decisions

1. Start with support-ops intelligence before autonomous agents. Buyers want measurable reduction and safety before automation.
2. Be neutral across helpdesks. Zendesk and Intercom are sources, not the product boundary.
3. Use evidence gating as the trust primitive. A playbook is only strong when it has cited solved examples and public-safe customer-facing evidence.
4. Treat KB gaps as first-class output. Deflection usually happens after the knowledge/macro/product gap is closed, not when an LLM drafts one answer.
5. Keep a human approval loop in v1. The product should make agents faster and support ops smarter before it acts directly with customers.

## V1 User Journey

1. Support ops opens `/support`.
2. They load demo data or sync Zendesk/Intercom.
3. Compass indexes tickets, comments, and articles.
4. Compass shows top repeat issue clusters.
5. Support ops selects a cluster such as `Export + Timeout`.
6. Compass builds a resolution workflow containing:
   - issue signature;
   - cited evidence;
   - agent-ready playbook;
   - customer response draft guardrailed for review;
   - KB or macro recommendation;
   - deflection estimate.
7. Support ops reviews evidence, then creates/updates a macro, KB article, or product bug.
8. Later releases compare repeat ticket volume before and after deployment.

## Acceptance Criteria

Local v1 is acceptable when:
- `/support` can seed demo support data;
- repeat clusters appear without requiring live connectors;
- a user can generate a playbook from a repeat cluster;
- the playbook includes evidence citations or explicitly marks itself as needing more evidence;
- the workflow includes a KB/macro recommendation;
- the workflow includes a deflection estimate with assumptions;
- tests cover workflow generation and no-match behavior;
- the docs clearly distinguish current v1 evidence gating from future deterministic hallucination verification.

## Risks

- Vector-only retrieval misses exact error codes and ticket identifiers. Mitigation: add BM25/full-text retrieval next.
- LLM-generated playbooks can overstate evidence. Mitigation: expose confidence, citations, and human-review status.
- Internal/private comments can leak into customer-facing drafts. Mitigation: add source visibility enforcement before customer automation.
- Customers may expect autonomous deflection immediately. Mitigation: position v1 as support-ops intelligence and agent-assist.
- ROI claims can be weak without before/after data. Mitigation: show estimated deflection now and actual deflection once customers deploy recommended KB/macros.

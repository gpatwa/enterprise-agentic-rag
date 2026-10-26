# Landing page messaging review (for CEO, Founder, CPO, CMO)

Status: **Review brief, not an approval.** Prepared by the implementing agent. Nothing here is signed off; each decision below needs a named person's answer in their own words. Live page: https://salmon-ground-06555890f.4.azurestaticapps.net/welcome (source: `apps/landing/src/pages/Landing.tsx`, a separate marketing site from the product apps).

## What the page says today

| Element | Current copy |
|---|---|
| Headline | "Agentic analytics you can trust." (previous draft: "Answers you can defend.") |
| Subhead | "Your team asks. Compass answers from definitions you've certified, and shows the SQL and evidence behind every number." |
| Supporting line | "The model never writes SQL. A deterministic compiler builds each query from your certified metrics, under policy and budget checks, and a person reviews anything risky. If Compass cannot answer safely, it says so." |
| Positioning | Governed analytics: certified definitions, no model-written SQL, refuses instead of guessing, human review for risky queries, tamper-evident evidence trail |
| Stage statement | "Pilot-stage product"; "we have not completed a SOC 2 audit or a formal third-party security review" |
| CTAs | "Try Compass" (opens the analytics pilot app), "Talk to us about a pilot" (mailto demo@kavachiq.com) |
| Personas | Finance, RevOps, Data, Engineering, Security, Every team |

## Positioning choice and the research behind it

The message is **governed, trustworthy agentic analytics**, not "Agentic RAG". Agentic RAG describes how the older support and search products work; it is a technique, not a buyer's problem. Headline candidates considered: "Answers your auditors will accept" (accurate but flat, avoids buyer vocabulary), "Trusted AI analytics, with the guardrails on", "AI that shows its work", and the chosen "Agentic analytics you can trust" (category language plus the trust claim).

Desk research (web, October 2026). Sources are mostly vendors; Gartner full reports were paywalled; this is not buyer research.

| Finding | Source | Reliability |
|---|---|---|
| Market is crowded: warehouse-native agents (Snowflake Cortex Analyst, Databricks Genie), BI vendors (ThoughtSpot, Omni, Sigma, Power BI, Looker), semantic-layer vendors (Cube, dbt), AI-analyst startups (Zenlytic, Hex) all pitch governed or trusted answers | [Rework guide](https://resources.rework.com/tools/ai-agents/best-ai-agents-for-data-analysis-2026), [ThoughtSpot](https://thoughtspot.com/press-releases/thoughtspot-expands-governed-enterprise-ai-with-snowflake-cortex-ai-and-semantic-views), [Omni vs Zenlytic](https://www.basedash.com/vs/omni-vs-zenlytic) | Vendor-sourced |
| Semantic-layer-grounded, deterministic query generation beats free-form text-to-SQL on enterprise accuracy | [dbt](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026), [Strategy](https://software.strategy.com/blog/70-80-percent-accuracy-isnt-good-enough-for-enterprise-ai), [arXiv paper](https://arxiv.org/pdf/2606.31041) (94% on Spider2-snow) | Two vendor, one academic |
| Buyers lack confidence in agent governance: 13% had governance structures, 19% high confidence in vendor hallucination protection, 75% piloting some agents but 15% fully autonomous | [IDM on Gartner](https://www.idm.net.au/node/15402), [The Register](https://theregister.com/2025/10/01/gartner_ai_agents) | Secondary reports of a Gartner survey of IT application leaders (2025) |
| Gartner (2026): agentic analytics adopters struggle with ROI, trust, governance, cost control; advice to enforce deterministic controls regardless of agent behavior | [Gartner abstracts](https://www.gartner.com/en/documents/8273821), [Gartner](https://www.gartner.com/doc/7412630) | Abstract only |
| Audit trails and approvals scaled to risk are rising requirements | [Immuta](https://www.immuta.com/blog/to-trust-ai-you-need-to-trust-your-data/), [Akka](https://trust.akka.io/csa-atf), [Saviynt](https://saviynt.com/blog/building-trust-ai-agents-accountability-audit) | Vendor opinion |

Implication: the architecture (semantic layer, deterministic compile) is table stakes, not a moat. The candidate edge is the combination of no model-written SQL, designed refusal, separation of duties (requesters cannot approve their own runs; AI assistants cannot decide), and a replayable tamper-evident evidence trail. We have **not** verified that competitors lack comparable approval gates, so the page must not say "no one else does this".

Not done: competitor product-documentation comparison, buyer interviews, pricing or willingness-to-pay work, Wren AI and Databricks Genie details.

## Claims and the evidence behind them

| Claim | Evidence | Confidence |
|---|---|---|
| Model never writes SQL; a deterministic compiler does | Code and adversarial tests (graph corpus, poisoning corpus) | High |
| Refuses or asks instead of guessing | Observed on the live pilot ("show me all orders" refused; small groups refused) | High |
| Small groups are suppressed (min group size 10) | Observed on the live pilot | High |
| Human review for costly/sensitive queries; requester cannot approve own run | Code and tests; review flow not yet exercised by real reviewers | Medium |
| Tamper-evident evidence trail; rows not stored in the audit record | Code and tests | High (tested), unproven at scale |
| Tenant isolation | Adversarial tests; one tenant only in the pilot | Medium |
| Read-only database role | Verified locally and in bootstrap | High |
| "Agentic analytics" category fit | Matches Gartner's category name; our runtime is a governed multi-step graph, not an open-ended autonomous agent | Medium: confirm the term fits how we want to be perceived |
| Works on PostgreSQL and DuckDB | Code and tests; one live PostgreSQL pilot | Medium |
| Answers for your own data in minutes | Not evidenced; the pilot uses sample data | Do not claim |

Removed because unevidenced: SOC 2 / GDPR status, aggregate rating, the 70% testimonial, Jira/Salesforce/on-call actions, SaaS connector list, "Backed by Anthropic", "Built in the open".

## Questions per role

**CEO**
0. Is trust the lead message ("Agentic analytics you can trust") given every competitor also claims governed or trusted answers, and is "pilot-stage" honesty a strength or a cost?
1. Is "governed answers, with proof" the story we want to lead with, or a growth/ROI story? (We have no ROI evidence yet.)
2. Who is the first buyer: data leader, security/compliance, or a business unit head?
3. Is stating "pilot-stage" and "no SOC 2 yet" acceptable externally, or do we withhold until we have a design partner?

**Founder**
1. Is the differentiation (no model-written SQL, refuses when unsure) accurate to the product vision, and is anything important missing (e.g. the knowledge/judgment graph direction, which is roadmap only)?
2. Which claims are you willing to defend in front of a skeptical customer today?
3. Is "Compass" the final name? The footer and SEO currently use it.

**CPO**
1. Does the page describe the product a pilot user actually gets today (analytics web app with a pasted access token, single dataset)?
2. Which persona pages (Finance, RevOps, Engineering, Security) are true enough to keep, given only one dataset type is supported?
3. Where should "Try Compass" lead? Today it links to the support app home, which has no backend on the landing site; the analytics app needs a token. A real sign-in flow is not built.

**CMO**
0. Does "Agentic analytics you can trust" differentiate, or should we hold "Answers your auditors will accept" / "AI that shows its work" for proof lines and social? Is "agentic" the right category word for us?
1. Is "Answers you can defend" a category-defining line or generic? What is the one-sentence positioning against "chat with your data" tools and BI copilots?
2. Who is the audience for the page (data leader, security/compliance, business unit head), and does the tone fit them? Is the pilot-stage honesty a trust asset or a conversion cost?
3. Proof: with no customers, which proof points can we show honestly (live demo, evidence trail screenshot, a sample refusal) instead of testimonials and ratings?
4. Naming and brand: is "Compass" cleared for use (trademark, domain), and what are the domain, SEO, and social-card plans? The page currently lives on an Azure default hostname.
5. Persona pages: which of Finance, RevOps, Data, Engineering, Security get dedicated campaigns, and does each message match something the product demonstrably does?
6. Call to action: "Try Compass" versus "Talk to us about a pilot". Which funnel do we want while we are pilot-only?

## Decisions to record

| Decision | Owner | Answer |
|---|---|---|
| Lead message and first buyer | CEO | |
| Which claims stay | Founder | |
| CTA destination and persona pages | CPO | |
| Public pilot-stage and no-SOC-2 wording | CEO + Founder | |
| Positioning line, brand/naming, domain, proof points | CMO | |

Known follow-ups regardless of answers: add a real domain (currently an Azure default hostname), fix the CTA target, and decide whether the in-app Agents page (which lists connectors and actions we do not ship) should be trimmed to match.

# Landing page messaging review (for CEO, Founder, CPO, CMO)

Status: **Review brief, not an approval.** Prepared by the implementing agent. Nothing here is signed off; each decision below needs a named person's answer in their own words. Live page: https://salmon-ground-06555890f.4.azurestaticapps.net/welcome (source: `apps/support-web/src/pages/Landing.tsx`).

## What the page says today

| Element | Current copy |
|---|---|
| Headline | "Answers you can defend." |
| Subhead | "Ask in plain English. Get the number, the SQL, and the proof." |
| Positioning | Governed analytics: certified definitions, no model-written SQL, refuses instead of guessing, human review for risky queries, tamper-evident evidence trail |
| Stage statement | "Pilot-stage product"; "we have not completed a SOC 2 audit or a formal third-party security review" |
| CTAs | "Try Compass", "Talk to us about a pilot" |
| Personas | Finance, RevOps, Data, Engineering, Security, Every team |

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
| Works on PostgreSQL and DuckDB | Code and tests; one live PostgreSQL pilot | Medium |
| Answers for your own data in minutes | Not evidenced; the pilot uses sample data | Do not claim |

Removed because unevidenced: SOC 2 / GDPR status, aggregate rating, the 70% testimonial, Jira/Salesforce/on-call actions, SaaS connector list, "Backed by Anthropic", "Built in the open".

## Questions per role

**CEO**
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

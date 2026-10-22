# Product Roadmap (proposal)

Status: **Proposal.** Written by the implementing agent from the repository state on 2026-10-22. Nothing here is an approval, a commitment, or a recorded human gate. The owner adopts, amends, or rejects each item in their own words. Dates are deliberately absent: sequencing is by evidence, not by calendar.

## Where we are

| Product | Purpose | Maturity |
|---|---|---|
| Analytics (`services/analytics-api`, `apps/analytics-web`) | Plain-English questions answered from certified semantic definitions: deterministic compiler (no model-written SQL), policy and cost checks, human review, tamper-evident evidence trail | Most mature. Deployed as a pilot on Azure (PostgreSQL, Azure OpenAI `gpt-5.6-luna` at medium reasoning effort). Verified end to end once |
| Resolution Intelligence / support (`services/api`, `apps/support-web`) | Search over resolved tickets, RAG, Neo4j graph search, agents | Older and broad; search moving to OpenSearch |
| Discovery (`services/discovery-api`, `apps/discovery-web`) | Immersive discovery and ranking | Planned/early; not verified here |
| Platform (control-plane, data-plane, gateway, sandbox) | Shared infrastructure | Supporting |

Graph capabilities today:

| Capability | Status |
|---|---|
| Ontology | Built for Analytics: tenant-scoped nodes and edges with provenance, derived from certified Git-backed contracts |
| Knowledge graph | Neo4j in the support/RAG product only; Analytics has no graph store |
| Judgment graph | Not built. Human review, evidence, and feedback exist as flat linked tables |

## What differentiates the product

Trustworthy answers, not chat. The model only extracts intent; a compiler builds the query from certified definitions; the system refuses or asks when unsure; costly or sensitive queries wait for a person; every answer carries its SQL and evidence. This targets buyers who cannot accept a plausible-looking wrong number.

## Known gaps

- No customers or real usage; everything is proven only by tests and one smoke run.
- Open human gates: thresholds, reference corpus, independent code reviews, cost-unit calibration against a real warehouse. Recorded approvals cover only the M0/M1/M5/M6/M7 gates.
- One warehouse family (PostgreSQL, DuckDB) and one certified contract per tenant.
- Security reviewed internally only; no third-party review, no SOC 2, no completed compliance programme.
- Pilot hardening: process-local quotas and answer handoff (single replica), advisory-only review assistant, Luna cost per answer unmeasured.

## Phases

### Phase 1: Prove one thing (pilot)
Goal: a real pilot on one real dataset with named reviewers.

- Onboard one dataset with human-authored, owner-approved definitions and policies (never certify an import as-is).
- Replace the sample corpus with 25 to 50 real questions; separate definition-owner and results-owner approval.
- Assign reviewer and analyst roles; run reviews through the real flow.
- Measure Luna cost and latency per answer; calibrate cost units against the real warehouse.
- Walk the operations runbooks in a game day with someone who did not write them.

Exit evidence: real answers reviewed by people, measured cost and latency, corrections captured as feedback.

### Phase 2: Broaden semantics
- More datasets and multiple contracts per tenant; additional warehouse adapters chosen by pilot demand.
- Analytics knowledge graph: lineage, ownership, glossary, and metric relationships, rebuildable from the Git-backed contracts (no separate source of truth).
- Shared contracts stay in `packages/platform_contracts`; no analytics code in the support API.

### Phase 3: Judgment graph (advisory only)
Prerequisite: weeks of real reviewer decisions from Phase 1.

- Model question, metric choice, policy decision, reviewer decision and reason, outcome, and feedback as nodes and edges, tenant-scoped.
- Precedent informs reviewers and never approves or refuses by itself. Any weight beyond advisory is a human decision.
- Adversarial tests first: precedent poisoning, cross-tenant leakage, and reviewer-bias feedback loops.

### Phase 4: Harden for trust
- Independent security review, then evidence for compliance frameworks only as completed.
- Multi-replica runtime (durable quota and answer handoff), upgrade and rollback runbooks, SLOs.
- Public claims limited to what is evidenced (see the landing page, which states pilot stage).

## Decisions needed from the owner

1. Pilot dataset and named reviewers (Phase 1).
2. Threshold and corpus approvals, in your own words.
3. Whether the knowledge graph should live in Neo4j, OpenSearch, or derived from contracts (recommendation: derive from contracts first).
4. How much weight precedent may ever carry (recommendation: advisory only).
5. Which compliance claim, if any, becomes true first.

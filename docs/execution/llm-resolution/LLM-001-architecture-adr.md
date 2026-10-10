# LLM-001: Resolution Intelligence Architecture ADR

## Objective

Create `docs/adr/ADR-LLM-001-resolution-intelligence.md`. Record the approved
role of LLMs in query understanding, bounded ranking, grounded resolution, and
typed action proposal while preserving deterministic authorization, policy,
approval, execution, and audit ownership.

## Dependencies

- OS-088 is complete.

## Read First

1. `docs/LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md`
2. `docs/adr/ADR-OS-001-opensearch-enterprise-search.md`
3. `services/api/app/search/models.py`
4. `services/api/app/search/service.py`
5. `services/api/app/support/resolver.py`
6. `services/api/app/routes/support.py`
7. `services/api/app/clients/base.py`

Do not read unrelated repository files.

## Owned Files

- Create `docs/adr/ADR-LLM-001-resolution-intelligence.md`.
- Do not edit application, test, dependency, configuration, or deployment
  files.

## Required ADR Sections

1. Status and date.
2. Context and existing baseline.
3. Decision and request flow.
4. LLM responsibilities.
5. Deterministic trust-layer responsibilities.
6. Model routing, token budgets, fallback, and kill switch.
7. Alternatives: LLM-only retrieval, deterministic RAG only, one large model
   for every stage, and specialized small/large model routing.
8. Security, privacy, tenant-isolation, and prompt-injection constraints.
9. Evaluation and rollout requirements.
10. Deferred learned-ranking and multimodal decisions.
11. Conditions that reopen the decision.

## Non-Negotiable Decisions

- OpenSearch and `SearchScope` own retrieval and authorization.
- LLMs cannot add candidates, modify scope, approve commands, or execute tools.
- Structured LLM output must pass a strict schema.
- Every model call is bounded, versioned, observable, and has a deterministic
  fallback.
- Live model calls, external action integrations, and cloud deployment are out
  of scope.

## Acceptance Evidence

- The ADR distinguishes retrieval, reasoning, policy, approval, and execution.
- It records cost-aware model routing and deterministic degradation.
- It does not claim implementation or production readiness.
- It links to the canonical LLM execution plan and OpenSearch ADR.
- `git diff --check` passes.

## Stop Conditions

Stop and report without editing other files if:

- OS-088 or the enterprise search contract is absent;
- an existing ADR assigns authorization or action approval to an LLM;
- the approved architecture now permits automatic external execution.

## Targeted Validation

```bash
git diff --check
```

## Commit

```text
docs(resolution): LLM-001 record LLM trust boundaries
```


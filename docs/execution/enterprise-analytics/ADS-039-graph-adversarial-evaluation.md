# ADS-039: Graph Adversarial Evaluation

Status: **Review**
Milestone: M3
Depends on: ADS-030 through ADS-038

## Deliverable

`app/runtime/graph_eval.py` supplies bounded graph case execution, resume-trace
checks, gate-order assertions, outcome expectations, and a required M3 scenario
coverage gate. Coverage includes answer, clarification, identity/policy refusal,
pending/approved/rejected/expired review, malformed intent, stale context,
budget, deadline, cycle, cancellation, and crash/resume.

## Evidence

- `services/analytics-api/app/runtime/graph_eval.py`
- `services/analytics-api/app/runtime/graph_factory.py`
- `make test-analytics`: **209 passed**.
- The run caught two regressions, both fixed before the passing run: an ADS-009 fixture used an unregistered `fake-v1` graph version, and standalone expected-trace steps were not rejecting illegal edges.
- The complete M3 adversarial scenario corpus is not present in the repository, so the 209-test suite is regression evidence, not an ADS-039 graph evaluation result.

## Remaining Gate

Author and run the required 15-case adversarial corpus against a fully composed
graph-v2 using injected local providers (no live OpenSearch or warehouse). The
cases must assert outcomes, typed error codes, durable review/resume behavior,
gate order, forbidden execution, and bounded termination. ADS-039 therefore
remains in **Review**, and M3's graph-and-policy human gate is still pending.
Do not interpret the existing suite as end-to-end graph evidence.

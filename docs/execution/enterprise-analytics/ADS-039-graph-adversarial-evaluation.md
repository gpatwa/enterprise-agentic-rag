# ADS-039: Graph Adversarial Evaluation

Status: **Complete**
Milestone: M3
Depends on: ADS-030 through ADS-038

## Deliverable

`app/runtime/graph_eval.py` supplies bounded graph case execution, resume-trace
checks, gate-order assertions, outcome expectations, and a required M3 scenario
coverage gate. Coverage includes answer, clarification, identity/policy refusal,
pending/approved/rejected/expired review, malformed intent, stale context,
budget, deadline, cycle, cancellation, and crash/resume.

The corpus composes the graph-v2 factory with the real bootstrap, context-pack,
structured-intent, ontology, certification, policy, compiler, cost, review, and
execution node handlers. External context search and the executor are injected
local fakes; no live OpenSearch or warehouse is contacted.

## Evidence

- `services/analytics-api/app/runtime/graph_eval.py`
- `services/analytics-api/app/runtime/graph_factory.py`
- `services/analytics-api/tests/test_ads039_graph_adversarial.py`: **15/15 required scenarios passed**, including durable review and resume, cycle termination, cancellation, and worker crash recovery.
- `make test-analytics`: **210 passed**.
- The evaluation exposed and fixed a resume-state defect: successful progress after human approval now restores the run to `active` before persisting its transition.

## Remaining Gate

ADS-039 and M3 are complete for the local fake-provider evaluation. Live
OpenSearch integration remains separate external work, and M1 semantic
certification remains a separate human gate. This evaluation does not claim
production data-source or warehouse validation.

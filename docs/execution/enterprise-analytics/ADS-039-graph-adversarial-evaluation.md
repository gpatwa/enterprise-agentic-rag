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
- Static validation: Ruff and `git diff --check` pass.

## Remaining Gate

The adversarial case corpus has not yet been run against the integrated graph.
ADS-039 therefore remains in **Review**, and M3's graph-and-policy human gate
is still pending. Do not interpret static checks as end-to-end evidence.

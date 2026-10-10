# Enterprise Analytics Task Packets

These packets are the first bounded assignments from the
[Enterprise Analytics Roadmap](../../ENTERPRISE_ANALYTICS_EXECUTION_PLAN.md).
They are written for independent coding-model sessions and human reviewers.

The next integrated program is defined in the
[Agentic Data Stack Execution Plan](../../AGENTIC_DATA_STACK_EXECUTION_PLAN.md).
It introduces `ADS-001` through `ADS-079` for ontology/context, harness,
bounded graph, safe learning-loop, enterprise runtime, and final evaluation
work. PostgreSQL is the first customer-shaped execution adapter; DuckDB is the
first embedded local and governed data-lake-file adapter. Expand one ADS packet
at a time in this directory before dispatching it to Luna.

Review the animated
[Agentic Data Stack system diagram](../../diagrams/agentic-data-stack-system.html)
and [request workflow](../../diagrams/agentic-data-stack-request.html) before
changing a major boundary. The Archify sources present the system boundaries
first, followed by the bounded graph, execution adapters, and improvement loop.

## Dispatch Order

| Packet | Can start | Merge order | Primary ownership |
|---|---|---:|---|
| [EA-001](EA-001-canonical-fixtures.md) | Now | 1 | Analytics test fixtures only |
| [EA-070](EA-070-design-partner-scorecard.md) | Now | Independent | Discovery artifacts only |
| [EA-003](EA-003-ast-sql-validation.md) | After EA-001 fixture shape is stable | 2 | SQL safety and parser dependency |
| [EA-004](EA-004-v2-outcome-contract.md) | After EA-001 fixture shape is stable | 2 | New v2 contract module |
| [EA-060](EA-060-evaluation-harness.md) | After EA-001 merges | 3 | Analytics evaluation package |

`EA-003` and `EA-004` may run concurrently because their owned file sets do
not overlap. `EA-060` consumes the fixtures from `EA-001`; refresh its branch
after `EA-001` merges.

## Dispatch Rules

1. Give each model one packet and a fresh worktree.
2. Require a commit before handoff; do not accept an uncommitted diff as done.
3. Do not let a delegated model expand scope without returning a written stop
   condition.
4. Use a separate session for adversarial review.
5. Merge in the order above and run the analytics CI-equivalent commands after
   every merge.

## Integration Gate

From the repository root:

```bash
ruff check services/analytics-api/app services/analytics-api/tests packages
PYTHONPATH="$PWD/services/analytics-api:$PWD" \
  pytest services/analytics-api/tests -v --tb=short
git diff --check
```

Do not commit or discard unrelated work already present in the repository.
